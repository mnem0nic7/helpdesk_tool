"""API routes for ticket listing, detail, and ticket-level actions."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from attachment_service import (
    AttachmentPreviewError,
    build_content_disposition,
    ensure_office_preview_pdf,
    fetch_attachment_content,
    find_attachment,
    preview_kind_for_attachment,
    serialize_attachment,
)
from ai_client import extract_adf_text
from auth import require_admin
from config import JIRA_BASE_URL, JIRA_PROJECT
from issue_cache import cache
from jira_client import JiraClient, validate_jira_key
from jira_write_service import add_fallback_internal_audit_note, get_jira_write_context, prepend_fallback_actor_line
from metrics import (
    _is_open,
    is_excluded_from_stale,
    issue_to_row,
    matches_libra_support_filter,
    sync_occ_ticket_id_field,
)
from models import TicketCommentRequest, TicketCreateRequest, TicketRefreshRequest, TicketTransitionRequest, TicketUpdateRequest
from requestor_sync_service import requestor_sync_service
from request_type import extract_request_type_name_from_fields
from site_context import get_current_site_scope, get_scoped_issues, key_is_visible_in_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_client = JiraClient()
_STALE_DAYS = 1
_DEFAULT_CREATE_ISSUE_TYPE = "[System] Service request"


def _match(issue: dict[str, Any], **filters: Any) -> bool:
    """Return True if the issue matches all provided filters."""
    fields = issue.get("fields", {})
    status_obj = fields.get("status") or {}
    status_category_name = ((status_obj.get("statusCategory") or {}).get("name") or "")
    is_terminal = status_category_name == "Done" or not _is_open(issue)

    if filters.get("status"):
        if status_obj.get("name", "") != filters["status"]:
            return False

    if filters.get("priority"):
        priority_obj = fields.get("priority") or {}
        if priority_obj.get("name", "") != filters["priority"]:
            return False

    if filters.get("assignee"):
        assignee_obj = fields.get("assignee") or {}
        assignee_name = assignee_obj.get("displayName", "") if isinstance(assignee_obj, dict) else ""
        if filters["assignee"] == "unassigned":
            if assignee_name:
                return False
        elif assignee_name != filters["assignee"]:
            return False

    if filters.get("issue_type"):
        issuetype_obj = fields.get("issuetype") or {}
        if issuetype_obj.get("name", "") != filters["issue_type"]:
            return False

    if filters.get("label"):
        labels = fields.get("labels") or []
        target = str(filters["label"]).lower()
        if not any(str(label).lower() == target for label in labels):
            return False

    if not matches_libra_support_filter(issue, filters.get("libra_support")):
        return False

    if filters.get("search"):
        term = filters["search"].lower()
        summary = (fields.get("summary") or "").lower()
        desc = ""
        desc_field = fields.get("description")
        if isinstance(desc_field, str):
            desc = desc_field.lower()
        elif isinstance(desc_field, dict):
            import json
            desc = json.dumps(desc_field).lower()
        key = issue.get("key", "").lower()
        if term not in summary and term not in desc and term not in key:
            return False

    if filters.get("open_only") and is_terminal:
        return False

    if filters.get("stale_only") and is_terminal:
        return False

    if filters.get("stale_only"):
        if is_excluded_from_stale(issue, scope=get_current_site_scope()):
            return False
        updated_str = fields.get("updated", "")
        if not updated_str:
            return False

        try:
            updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            days_since = (datetime.now(timezone.utc) - updated).total_seconds() / 86400.0
            if days_since < _STALE_DAYS:
                return False
        except (ValueError, TypeError):
            return False

    if filters.get("created_after"):
        created_str = fields.get("created", "")
        if created_str:
            try:
                created = datetime.fromisoformat(created_str.replace("Z", "+00:00")).date()
                from datetime import date

                if created < date.fromisoformat(filters["created_after"]):
                    return False
            except (ValueError, TypeError):
                return False
        else:
            return False

    if filters.get("created_before"):
        created_str = fields.get("created", "")
        if created_str:
            try:
                created = datetime.fromisoformat(created_str.replace("Z", "+00:00")).date()
                from datetime import date

                if created > date.fromisoformat(filters["created_before"]):
                    return False
            except (ValueError, TypeError):
                return False
        else:
            return False

    return True


def _issue_url(key: str) -> str:
    return f"{JIRA_BASE_URL.rstrip('/')}/browse/{key}" if JIRA_BASE_URL else ""


def _get_cached_issue(key: str) -> dict[str, Any] | None:
    all_issues = {iss["key"]: iss for iss in cache.get_all_issues() if iss.get("key")}
    return all_issues.get(key)


def _get_issue_and_attachment(key: str, attachment_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    issue = _get_cached_issue(key)
    attachment = find_attachment(issue or {}, attachment_id) if issue else None
    if attachment:
        return issue, attachment

    issue = _client.get_issue(key)
    cache.upsert_issue(issue)
    attachment = find_attachment(issue, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found on this ticket")
    return issue, attachment


def _ticket_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return extract_adf_text(value)
    return ""


def _comment_timestamp(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("iso8601") or value.get("jira") or value.get("friendly") or ""
    return ""


def _serialize_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for comment in comments or []:
        author = comment.get("author") or {}
        result.append(
            {
                "id": str(comment.get("id", "")),
                "author": (
                    author.get("displayName")
                    or author.get("name")
                    or author.get("emailAddress")
                    or "Unknown"
                ),
                "created": _comment_timestamp(comment.get("created")),
                "updated": _comment_timestamp(comment.get("updated")),
                "body": _ticket_text(comment.get("body")),
                "public": bool(comment.get("public", False)),
            }
        )
    return result


def _serialize_attachments(issue: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = issue.get("fields", {}).get("attachment") or []
    result: list[dict[str, Any]] = []
    ticket_key = str(issue.get("key") or "").strip()
    for attachment in attachments:
        result.append(serialize_attachment(ticket_key, attachment))
    return result


def _serialize_issue_links(issue: dict[str, Any]) -> list[dict[str, Any]]:
    links = issue.get("fields", {}).get("issuelinks") or []
    result: list[dict[str, Any]] = []
    for link in links:
        link_type = link.get("type") or {}
        outward = link.get("outwardIssue")
        inward = link.get("inwardIssue")
        linked_issue = outward or inward
        direction = "outward" if outward else "inward" if inward else ""
        if not linked_issue:
            continue
        linked_fields = linked_issue.get("fields", {})
        status_name = ((linked_fields.get("status") or {}).get("name") or "")
        result.append(
            {
                "direction": direction,
                "relationship": link_type.get("outward" if outward else "inward", ""),
                "type": link_type.get("name", ""),
                "key": linked_issue.get("key", ""),
                "summary": linked_fields.get("summary", ""),
                "status": status_name,
                "url": _issue_url(linked_issue.get("key", "")),
            }
        )
    return result


def _ticket_detail(
    issue: dict[str, Any],
    comments: list[dict[str, Any]] | None = None,
    *,
    requestor_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields = issue.get("fields", {})
    request_field = fields.get("customfield_11102") or {}
    request_links = request_field.get("_links") if isinstance(request_field, dict) else {}
    return {
        "ticket": issue_to_row(issue),
        "description": _ticket_text(fields.get("description")),
        "steps_to_recreate": _ticket_text(fields.get("customfield_11121")),
        "request_type": extract_request_type_name_from_fields(fields),
        "work_category": fields.get("customfield_11239") or "",
        "comments": _serialize_comments(comments or []),
        "attachments": _serialize_attachments(issue),
        "issue_links": _serialize_issue_links(issue),
        "jira_url": request_links.get("agent") or _issue_url(issue.get("key", "")),
        "portal_url": request_links.get("web", ""),
        "requestor_identity": requestor_identity or requestor_sync_service.get_requestor_identity(issue),
        "raw_issue": issue,
    }


def _get_assignable_display_name(account_id: str | None) -> str:
    if not account_id:
        return ""
    try:
        users = _client.get_users_assignable(JIRA_PROJECT)
    except Exception:
        logger.exception("Failed to resolve Jira display name from assignable users for account %s", account_id)
        return ""
    for user in users:
        if user.get("accountId") == account_id:
            return user.get("displayName", "")
    return ""


def _get_user_display_name(account_id: str | None) -> str:
    if not account_id:
        return ""
    display_name = _get_assignable_display_name(account_id)
    if display_name:
        return display_name
    try:
        return (_client.get_user(account_id) or {}).get("displayName", "")
    except Exception:
        logger.exception("Failed to resolve Jira display name for account %s", account_id)
        return ""


def _load_ticket_detail(key: str, issue: dict[str, Any] | None = None) -> dict[str, Any]:
    issue = issue or _client.get_issue(key)
    requestor_result = requestor_sync_service.maybe_reconcile_issue(issue)
    comments = _client.get_request_comments(key)
    issue_fields = issue.setdefault("fields", {})
    issue_fields["comment"] = {
        "comments": comments,
        "total": len(comments),
    }
    sync_occ_ticket_id_field(issue_fields)
    cache.upsert_issue(issue)
    return _ticket_detail(issue, comments, requestor_identity=requestor_result["requestor_identity"])


def _ensure_ticket_visible(key: str) -> None:
    if not key_is_visible_in_scope(key):
        raise HTTPException(status_code=404, detail=f"Issue {key} not found")


def _unique_ticket_keys(keys: list[str]) -> list[str]:
    unique_keys: list[str] = []
    seen: set[str] = set()
    for raw_key in keys:
        key = str(raw_key or "").strip().upper()
        if not key or key in seen:
            continue
        unique_keys.append(key)
        seen.add(key)
    return unique_keys


@router.get("/tickets")
async def list_tickets(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    assignee: Optional[str] = Query(None),
    issue_type: Optional[str] = Query(None),
    label: Optional[str] = Query(None),
    libra_support: Optional[Literal["all", "libra_support", "non_libra_support"]] = Query(None),
    search: Optional[str] = Query(None),
    open_only: bool = Query(False),
    stale_only: bool = Query(False),
    created_after: Optional[str] = Query(None),
    created_before: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
) -> dict[str, Any]:
    """Return filtered OIT tickets from cache with pagination."""
    issues = get_scoped_issues()

    filters = {
        "status": status,
        "priority": priority,
        "assignee": assignee,
        "issue_type": issue_type,
        "label": label,
        "libra_support": libra_support,
        "search": search,
        "open_only": open_only,
        "stale_only": stale_only,
        "created_after": created_after,
        "created_before": created_before,
    }

    matched = [iss for iss in issues if _match(iss, **filters)]
    matched.sort(key=lambda iss: iss.get("fields", {}).get("created", ""), reverse=True)
    page = matched[offset : offset + limit]

    return {
        "tickets": [issue_to_row(iss) for iss in page],
        "matched_count": len(matched),
        "total_count": len(issues),
    }


@router.get("/filter-options")
async def get_filter_options() -> dict[str, list[str]]:
    """Return distinct statuses, priorities, issue types, and labels from cached tickets."""
    issues = get_scoped_issues()
    statuses: set[str] = set()
    priorities: set[str] = set()
    issue_types: set[str] = set()
    labels: set[str] = set()
    components: set[str] = set()
    work_categories: set[str] = set()
    for iss in issues:
        fields = iss.get("fields", {})
        status_name = (fields.get("status") or {}).get("name")
        if status_name:
            statuses.add(status_name)
        priority_name = (fields.get("priority") or {}).get("name")
        if priority_name:
            priorities.add(priority_name)
        issue_type_name = (fields.get("issuetype") or {}).get("name")
        if issue_type_name:
            issue_types.add(issue_type_name)
        for label in fields.get("labels") or []:
            if label:
                labels.add(str(label))
        for component in fields.get("components") or []:
            if isinstance(component, dict):
                component_name = str(component.get("name", "")).strip()
                if component_name:
                    components.add(component_name)
        work_category = str(fields.get("customfield_11239") or "").strip()
        if work_category:
            work_categories.add(work_category)
    priority_order = ["Highest", "High", "Medium", "Low", "Lowest", "New"]
    sorted_priorities = [p for p in priority_order if p in priorities] + sorted(priorities - set(priority_order))
    return {
        "statuses": sorted(statuses),
        "priorities": sorted_priorities,
        "issue_types": sorted(issue_types),
        "labels": sorted(labels),
        "components": sorted(components),
        "work_categories": sorted(work_categories),
    }


@router.get("/priorities")
async def get_priorities() -> list[dict[str, str]]:
    """Return available Jira priorities."""
    priorities = _client.get_priorities()
    return [
        {"id": str(priority.get("id", "")), "name": priority.get("name", "")}
        for priority in priorities
        if priority.get("name")
    ]


@router.get("/request-types")
async def get_request_types() -> list[dict[str, str]]:
    """Return request types that appear in the current scope's cached tickets.

    The `id` field is the numeric Jira request type ID required by
    customfield_11102 when writing; `name` is the human-readable label.
    """
    issues = get_scoped_issues()
    seen: dict[str, dict[str, str]] = {}
    for iss in issues:
        fields = iss.get("fields", {})
        # customfield_10010 carries the full requestType object including the numeric id.
        rt = (fields.get("customfield_10010") or {}).get("requestType") or {}
        name = rt.get("name", "").strip()
        rt_id = str(rt.get("id", "")).strip()
        if name and rt_id and name not in seen:
            seen[name] = {"id": rt_id, "name": name, "description": rt.get("description", "")}
    return sorted(seen.values(), key=lambda x: x["name"])


@router.get("/assignees")
async def get_assignees() -> list[dict[str, Any]]:
    """Return assignees that appear in the current scope's cached tickets."""
    issues = get_scoped_issues()
    seen: dict[str, dict[str, Any]] = {}
    for iss in issues:
        assignee = (iss.get("fields") or {}).get("assignee") or {}
        account_id = assignee.get("accountId", "")
        display_name = assignee.get("displayName", "")
        if account_id and display_name and account_id not in seen:
            seen[account_id] = {
                "account_id": account_id,
                "display_name": display_name,
                "email_address": assignee.get("emailAddress", ""),
            }
    return sorted(seen.values(), key=lambda x: x["display_name"])


@router.get("/users")
async def list_users() -> list[dict[str, Any]]:
    """Return active Jira users assignable to the current project."""
    try:
        raw_users = _client.get_users_assignable(JIRA_PROJECT)
    except Exception as exc:
        logger.exception("Failed to load assignable Jira users")
        raise HTTPException(
            status_code=502,
            detail="Could not load Jira users. Please try again in a moment.",
        ) from exc

    seen: dict[str, dict[str, Any]] = {}
    for user in raw_users:
        account_id = str(user.get("accountId", "")).strip()
        display_name = str(user.get("displayName", "")).strip()
        if not account_id or not display_name or account_id in seen:
            continue
        if user.get("active") is False:
            continue
        seen[account_id] = {
            "account_id": account_id,
            "display_name": display_name,
            "email_address": str(user.get("emailAddress", "")).strip(),
        }
    return sorted(seen.values(), key=lambda x: x["display_name"])


@router.get("/users/search")
async def search_users(q: str = Query(default="", max_length=100)) -> list[dict[str, Any]]:
    """Search Jira users by name or email for manual ticket edits."""
    query = q.strip()
    if len(query) < 2:
        return []
    try:
        raw_users = _client.search_users(query)
    except Exception as exc:
        logger.exception("Failed Jira user search for query '%s'", query)
        raise HTTPException(
            status_code=502,
            detail="User search failed. Please try again in a moment.",
        ) from exc

    seen: dict[str, dict[str, Any]] = {}
    for user in raw_users:
        account_id = str(user.get("accountId", "")).strip()
        display_name = str(user.get("displayName", "")).strip()
        if not account_id or not display_name or account_id in seen:
            continue
        if user.get("active") is False:
            continue
        seen[account_id] = {
            "account_id": account_id,
            "display_name": display_name,
            "email_address": str(user.get("emailAddress", "")).strip(),
        }
    return sorted(seen.values(), key=lambda x: x["display_name"])


@router.get("/statuses/{key}")
async def get_statuses(key: str) -> list[dict[str, Any]]:
    """Return available transitions for a given issue."""
    try:
        validate_jira_key(key)
        _ensure_ticket_visible(key)
        transitions = _client.get_transitions(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except Exception:
        logger.exception("Failed to load transitions for ticket %s", key)
        raise HTTPException(status_code=404, detail=f"Could not get transitions for {key}")
    return [
        {
            "id": t.get("id", ""),
            "name": t.get("name", ""),
            "to_status": (t.get("to") or {}).get("name", ""),
        }
        for t in transitions
    ]


@router.post("/tickets/refresh-visible")
async def refresh_visible_tickets(body: TicketRefreshRequest) -> dict[str, Any]:
    """Refresh the currently displayed ticket rows from live Jira data."""
    requested_keys = _unique_ticket_keys(body.keys)
    visible_keys: list[str] = []
    skipped_keys: list[str] = []

    for key in requested_keys:
        try:
            validate_jira_key(key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if key_is_visible_in_scope(key):
            visible_keys.append(key)
        else:
            skipped_keys.append(key)

    try:
        refreshed_issues = await asyncio.get_running_loop().run_in_executor(
            None,
            cache.refresh_issue_keys,
            visible_keys,
        )
    except Exception as exc:
        logger.exception("Failed to refresh visible tickets from Jira")
        raise HTTPException(
            status_code=502,
            detail="Jira refresh failed. Please try again in a moment.",
        ) from exc
    refreshed_keys = [issue.get("key", "") for issue in refreshed_issues if issue.get("key")]
    refreshed_key_set = set(refreshed_keys)
    for issue in refreshed_issues:
        result = requestor_sync_service.maybe_reconcile_issue(issue)
        if result.get("updated"):
            cache.upsert_issue(issue)

    return {
        "requested_count": len(requested_keys),
        "visible_count": len(visible_keys),
        "refreshed_count": len(refreshed_keys),
        "refreshed_keys": refreshed_keys,
        "skipped_keys": skipped_keys,
        "missing_keys": [key for key in visible_keys if key not in refreshed_key_set],
    }


@router.get("/tickets/{key}")
async def get_ticket(key: str) -> dict[str, Any]:
    """Return detailed information for a single ticket."""
    try:
        validate_jira_key(key)
        _ensure_ticket_visible(key)
        return _load_ticket_detail(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except Exception:
        logger.exception("Failed to load ticket detail for %s", key)
        raise HTTPException(status_code=404, detail=f"Issue {key} not found")


@router.post("/tickets")
async def create_ticket(
    body: TicketCreateRequest,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Create a new Jira service request ticket on the primary host."""
    if get_current_site_scope() != "primary":
        raise HTTPException(status_code=404, detail="Ticket creation is only available on it-app")

    summary = str(body.summary or "").strip()
    priority = str(body.priority or "").strip()
    request_type_id = str(body.request_type_id or "").strip()
    description = str(body.description or "")

    if not summary:
        raise HTTPException(status_code=400, detail="summary cannot be empty")
    if not priority:
        raise HTTPException(status_code=400, detail="priority cannot be empty")
    if not request_type_id:
        raise HTTPException(status_code=400, detail="request_type_id cannot be empty")

    try:
        ctx = get_jira_write_context(_admin, shared_client=_client)
        created_issue = ctx.client.create_issue(
            project_key=JIRA_PROJECT,
            issue_type=_DEFAULT_CREATE_ISSUE_TYPE,
            summary=summary,
            description=description,
        )
        key = str(created_issue.get("key") or "").strip().upper()
        if not key:
            raise HTTPException(status_code=502, detail="Jira did not return a created issue key")
        ctx.client.update_priority(key, priority)
        ctx.client.set_request_type(key, request_type_id)
        if ctx.is_fallback:
            add_fallback_internal_audit_note(
                key,
                action_summary=f"Created ticket with priority {priority} and request type {request_type_id}",
                session=_admin,
                shared_client=_client,
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to create ticket in project %s", JIRA_PROJECT)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    issue = _client.get_issue(key)
    cache.upsert_issue(issue)
    detail = _load_ticket_detail(key, issue=issue)
    return {
        "created_key": key,
        "created_id": str(created_issue.get("id") or "").strip(),
        "detail": detail,
    }


@router.post("/tickets/{key}/sync-reporter")
async def sync_ticket_reporter(
    key: str,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Compatibility endpoint for unified requestor reconciliation."""
    del _admin
    try:
        validate_jira_key(key)
        _ensure_ticket_visible(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")

    try:
        issue = _client.get_issue(key)
        requestor_result = requestor_sync_service.reconcile_issue(issue, force=True)
        return {
            "detail": _load_ticket_detail(key, issue=issue),
            "updated": bool(requestor_result["updated"]),
            "message": requestor_result["message"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to sync reporter for ticket %s", key)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tickets/{key}/sync-requestor")
async def sync_ticket_requestor(
    key: str,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Reconcile a ticket requestor against Office 365 and Jira customers."""
    del _admin
    try:
        validate_jira_key(key)
        _ensure_ticket_visible(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")

    try:
        issue = _client.get_issue(key)
        result = requestor_sync_service.reconcile_issue(issue, force=True)
        detail = _load_ticket_detail(key, issue=issue)
        return {
            "detail": detail,
            "updated": bool(result["updated"]),
            "message": result["message"],
        }
    except HTTPException:
        raise
    except requests.HTTPError as exc:
        logger.exception("Failed to sync requestor for ticket %s", key)
        status_code = getattr(getattr(exc, "response", None), "status_code", None) or 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to sync requestor for ticket %s", key)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/requestor-sync/status")
async def get_requestor_sync_status(
    limit: int = Query(default=50, ge=1, le=200),
    failures_only: bool = Query(default=False),
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Return recent Office 365 requestor reconciliation outcomes."""
    del _admin
    return {"items": requestor_sync_service.list_recent_status(limit=limit, failures_only=failures_only)}


@router.put("/tickets/{key}")
async def update_ticket(
    key: str,
    body: TicketUpdateRequest,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Update editable fields on a single ticket."""
    try:
        validate_jira_key(key)
        _ensure_ticket_visible(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")

    fields = set(body.model_fields_set) - {"reporter_display_name"}
    if not fields:
        raise HTTPException(status_code=400, detail="No updates requested")

    try:
        ctx = get_jira_write_context(_admin, shared_client=_client)
        audit_lines: list[str] = []
        if "summary" in fields:
            if body.summary is None or not body.summary.strip():
                raise HTTPException(status_code=400, detail="summary cannot be empty")
            summary = body.summary.strip()
            ctx.client.update_summary(key, summary)
            cache.update_cached_field(key, "summary", summary)
            audit_lines.append(f"Summary updated to {summary!r}")

        if "description" in fields:
            description = body.description or ""
            ctx.client.update_description(key, description)
            cache.update_cached_field(key, "description", description)
            audit_lines.append("Description updated")

        if "priority" in fields:
            if not body.priority:
                raise HTTPException(status_code=400, detail="priority cannot be empty")
            ctx.client.update_priority(key, body.priority)
            cache.update_cached_field(key, "priority", body.priority)
            audit_lines.append(f"Priority updated to {body.priority}")

        if "assignee_account_id" in fields:
            account_id = body.assignee_account_id or None
            ctx.client.assign_issue(key, account_id)
            assignee_name = _get_assignable_display_name(account_id)
            cache.update_cached_field(
                key,
                "assignee",
                {
                    "displayName": assignee_name,
                    "accountId": account_id or "",
                },
            )
            audit_lines.append(f"Assignee updated to {assignee_name or 'Unassigned'}")

        if "reporter_account_id" in fields:
            account_id = body.reporter_account_id or None
            if not account_id:
                raise HTTPException(status_code=400, detail="reporter_account_id cannot be empty")
            reporter_name = body.reporter_display_name or _get_user_display_name(account_id)
            ctx.client.update_reporter(key, account_id)
            cache.update_cached_field(
                key,
                "reporter",
                {
                    "displayName": reporter_name,
                    "accountId": account_id,
                },
            )
            audit_lines.append(f"Reporter updated to {reporter_name or account_id}")

        if "request_type_id" in fields:
            if not body.request_type_id:
                raise HTTPException(status_code=400, detail="request_type_id cannot be empty")
            ctx.client.set_request_type(key, body.request_type_id)
            audit_lines.append(f"Request type updated to {body.request_type_id}")

        if "components" in fields:
            component_names = []
            for component in body.components or []:
                name = str(component).strip()
                if name and name not in component_names:
                    component_names.append(name)
            editable_components = ctx.client.get_editable_components(key)
            editable_component_ids_by_name = {
                str(component.get("name") or "").strip().casefold(): str(component.get("id") or "").strip()
                for component in editable_components
                if str(component.get("name") or "").strip() and str(component.get("id") or "").strip()
            }
            unknown_components = [
                name for name in component_names if name.casefold() not in editable_component_ids_by_name
            ]
            if unknown_components:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Component changes must use an existing Jira component for this project. "
                        f"Unknown component(s): {', '.join(unknown_components)}."
                    ),
                )
            ctx.client.update_components_by_id(
                key,
                [editable_component_ids_by_name[name.casefold()] for name in component_names],
            )
            audit_lines.append(
                f"Components updated to {', '.join(component_names) if component_names else '(none)'}"
            )

        if "work_category" in fields:
            work_category = (body.work_category or "").strip() or None
            ctx.client.update_work_category(key, work_category)
            audit_lines.append(f"Work category updated to {work_category or '(blank)'}")
        if ctx.is_fallback and audit_lines:
            add_fallback_internal_audit_note(
                key,
                action_summary="; ".join(audit_lines),
                session=_admin,
                shared_client=_client,
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update ticket %s", key)
        if "You do not have permission to create new components" in str(exc):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Component changes must use an existing Jira component for this project. "
                    "Choose one from the suggestions and try again."
                ),
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    issue = _client.get_issue(key)
    request_type = extract_request_type_name_from_fields(issue.get("fields", {}))
    if request_type:
        cache.update_cached_field(key, "request_type", request_type)
    return _load_ticket_detail(key, issue=issue)


@router.post("/tickets/{key}/transition")
async def transition_ticket(
    key: str,
    body: TicketTransitionRequest,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Transition a ticket to a new status."""
    try:
        validate_jira_key(key)
        _ensure_ticket_visible(key)
        transition_name = ""
        transitions = _client.get_transitions(key)
        for transition in transitions:
            if transition.get("id") == body.transition_id:
                transition_name = (transition.get("to") or {}).get("name", transition.get("name", ""))
                break
        ctx = get_jira_write_context(_admin, shared_client=_client)
        ctx.client.transition_issue(key, body.transition_id)
        if transition_name:
            cache.update_cached_field(key, "status", transition_name)
        if ctx.is_fallback:
            add_fallback_internal_audit_note(
                key,
                action_summary=f"Status changed to {transition_name or body.transition_id}",
                session=_admin,
                shared_client=_client,
            )
        return _load_ticket_detail(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except Exception as exc:
        logger.exception("Failed to transition ticket %s", key)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tickets/{key}/comment")
async def comment_ticket(
    key: str,
    body: TicketCommentRequest,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Add a comment to a ticket."""
    if not body.comment.strip():
        raise HTTPException(status_code=400, detail="comment cannot be empty")
    try:
        validate_jira_key(key)
        _ensure_ticket_visible(key)
        ctx = get_jira_write_context(_admin, shared_client=_client)
        comment_text = body.comment.strip()
        if ctx.is_fallback:
            comment_text = prepend_fallback_actor_line(comment_text, _admin)
        ctx.client.add_request_comment(key, comment_text, public=body.public)
        cache.update_cached_field(key, "updated", "")
        return _load_ticket_detail(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except Exception as exc:
        logger.exception("Failed to comment on ticket %s", key)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tickets/{key}/remove-oasisdev-label")
async def remove_oasisdev_label(
    key: str,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Remove the oasisdev label from a ticket and add an internal note.

    Used from the OasisDev queue to reclassify a ticket that was incorrectly
    tagged. Removes all labels containing 'oasisdev', posts an internal note,
    and moves the issue into the primary ticket scope.
    """
    try:
        validate_jira_key(key)
        _ensure_ticket_visible(key)

        # Read current labels from the cached issue
        all_issues = {iss["key"]: iss for iss in cache.get_all_issues() if iss.get("key")}
        issue = all_issues.get(key)
        current_labels: list[str] = (issue or {}).get("fields", {}).get("labels") or []
        new_labels = [lbl for lbl in current_labels if "oasisdev" not in lbl.lower()]

        # Write updates to Jira
        ctx = get_jira_write_context(_admin, shared_client=_client)
        ctx.client.update_issue_fields(key, {"labels": new_labels})
        note_text = (
            "This ticket has been reviewed and confirmed to be unrelated to OasisDev. "
            "The oasisdev label has been removed."
        )
        if ctx.is_fallback:
            note_text = prepend_fallback_actor_line(note_text, _admin)
        ctx.client.add_request_comment(key, note_text, public=False)

        # Keep cache coherent
        cache.update_cached_labels(key, new_labels)

        return _load_ticket_detail(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to remove oasisdev label from ticket %s", key)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tickets/{key}/attachments/{attachment_id}/download")
async def download_ticket_attachment(key: str, attachment_id: str) -> Response:
    """Download the original Jira attachment through the app."""
    try:
        validate_jira_key(key)
        _ensure_ticket_visible(key)
        _issue, attachment = _get_issue_and_attachment(key, attachment_id)
        blob, media_type = fetch_attachment_content(_client, attachment)
        filename = str(attachment.get("filename") or "").strip() or "attachment"
        headers = {
            "Content-Disposition": build_content_disposition(filename, inline=False),
            "Cache-Control": "private, no-store",
        }
        return Response(content=blob, media_type=media_type, headers=headers)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except HTTPException:
        raise
    except AttachmentPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to download attachment %s for %s", attachment_id, key)
        raise HTTPException(status_code=502, detail="Could not download attachment.") from exc


@router.get("/tickets/{key}/attachments/{attachment_id}/preview")
async def preview_ticket_attachment(key: str, attachment_id: str) -> Response:
    """Preview browser-viewable original attachment content."""
    try:
        validate_jira_key(key)
        _ensure_ticket_visible(key)
        _issue, attachment = _get_issue_and_attachment(key, attachment_id)
        preview_kind = preview_kind_for_attachment(
            str(attachment.get("filename") or ""),
            str(attachment.get("mimeType") or ""),
        )
        if preview_kind not in {"image", "pdf", "text"}:
            raise HTTPException(status_code=415, detail="Attachment does not support native inline preview")
        blob, media_type = fetch_attachment_content(_client, attachment)
        filename = str(attachment.get("filename") or "").strip() or "attachment"
        headers = {
            "Content-Disposition": build_content_disposition(filename, inline=True),
            "Cache-Control": "private, no-store",
        }
        return Response(content=blob, media_type=media_type, headers=headers)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except HTTPException:
        raise
    except AttachmentPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to preview attachment %s for %s", attachment_id, key)
        raise HTTPException(status_code=502, detail="Could not preview attachment.") from exc


@router.get("/tickets/{key}/attachments/{attachment_id}/preview-converted")
async def preview_ticket_attachment_converted(key: str, attachment_id: str) -> FileResponse:
    """Preview supported Office attachments as converted PDFs."""
    try:
        validate_jira_key(key)
        _ensure_ticket_visible(key)
        _issue, attachment = _get_issue_and_attachment(key, attachment_id)
        cache_path = ensure_office_preview_pdf(_client, attachment)
        filename = str(attachment.get("filename") or "").strip() or "attachment"
        stem = filename.rsplit(".", 1)[0] or filename
        return FileResponse(
            cache_path,
            media_type="application/pdf",
            filename=f"{stem}.pdf",
            content_disposition_type="inline",
            headers={"Cache-Control": "private, no-store"},
        )
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except HTTPException:
        raise
    except AttachmentPreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to generate converted preview for attachment %s on %s", attachment_id, key)
        raise HTTPException(status_code=502, detail="Could not generate Office preview.") from exc
