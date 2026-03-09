"""API routes for ticket listing, detail, and ticket-level actions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ai_client import extract_adf_text
from auth import require_admin
from config import JIRA_BASE_URL, JIRA_PROJECT
from issue_cache import cache
from jira_client import JiraClient, validate_jira_key
from metrics import issue_to_row
from models import TicketCommentRequest, TicketTransitionRequest, TicketUpdateRequest
from request_type import extract_request_type_name_from_fields

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_client = JiraClient()
_STALE_DAYS = 1


def _match(issue: dict[str, Any], **filters: Any) -> bool:
    """Return True if the issue matches all provided filters."""
    fields = issue.get("fields", {})

    if filters.get("status"):
        status_obj = fields.get("status") or {}
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

    if filters.get("open_only"):
        status_obj = fields.get("status") or {}
        sc = status_obj.get("statusCategory") or {}
        if sc.get("name", "") == "Done":
            return False

    if filters.get("stale_only"):
        updated_str = fields.get("updated", "")
        if updated_str:
            try:
                updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                days_since = (datetime.now(timezone.utc) - updated).total_seconds() / 86400.0
                if days_since < _STALE_DAYS:
                    return False
            except (ValueError, TypeError):
                return False
        else:
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
    for attachment in attachments:
        result.append(
            {
                "id": str(attachment.get("id", "")),
                "filename": attachment.get("filename", ""),
                "mime_type": attachment.get("mimeType", ""),
                "size": attachment.get("size", 0),
                "created": attachment.get("created", ""),
                "author": ((attachment.get("author") or {}).get("displayName") or ""),
                "content_url": attachment.get("content", ""),
                "thumbnail_url": attachment.get("thumbnail", ""),
            }
        )
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


def _ticket_detail(issue: dict[str, Any], comments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
        "raw_issue": issue,
    }


def _get_assignable_display_name(account_id: str | None) -> str:
    if not account_id:
        return ""
    try:
        users = _client.get_users_assignable(JIRA_PROJECT)
    except Exception:
        return ""
    for user in users:
        if user.get("accountId") == account_id:
            return user.get("displayName", "")
    return ""


def _load_ticket_detail(key: str) -> dict[str, Any]:
    issue = _client.get_issue(key)
    comments = _client.get_request_comments(key)
    return _ticket_detail(issue, comments)


@router.get("/tickets")
async def list_tickets(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    assignee: Optional[str] = Query(None),
    issue_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    open_only: bool = Query(False),
    stale_only: bool = Query(False),
    created_after: Optional[str] = Query(None),
    created_before: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
) -> dict[str, Any]:
    """Return filtered OIT tickets from cache with pagination."""
    issues = cache.get_filtered_issues()

    filters = {
        "status": status,
        "priority": priority,
        "assignee": assignee,
        "issue_type": issue_type,
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
    """Return distinct statuses, priorities, and issue types from cached tickets."""
    issues = cache.get_filtered_issues()
    statuses: set[str] = set()
    priorities: set[str] = set()
    issue_types: set[str] = set()
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
    priority_order = ["Highest", "High", "Medium", "Low", "Lowest", "New"]
    sorted_priorities = [p for p in priority_order if p in priorities] + sorted(priorities - set(priority_order))
    return {
        "statuses": sorted(statuses),
        "priorities": sorted_priorities,
        "issue_types": sorted(issue_types),
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
    """Return available request types for the configured service desk."""
    service_desk_id = _client.get_service_desk_id_for_project(JIRA_PROJECT)
    if not service_desk_id:
        return []
    request_types = _client.get_request_types(service_desk_id)
    return [
        {
            "id": str(request_type.get("id", "")),
            "name": request_type.get("name", ""),
            "description": request_type.get("description", ""),
        }
        for request_type in request_types
        if request_type.get("id") and request_type.get("name")
    ]


@router.get("/assignees")
async def get_assignees() -> list[dict[str, Any]]:
    """Return the list of assignable users for the OIT project."""
    users = _client.get_users_assignable(JIRA_PROJECT)
    return [
        {
            "account_id": u.get("accountId", ""),
            "display_name": u.get("displayName", ""),
            "email_address": u.get("emailAddress", ""),
        }
        for u in users
    ]


@router.get("/statuses/{key}")
async def get_statuses(key: str) -> list[dict[str, Any]]:
    """Return available transitions for a given issue."""
    try:
        validate_jira_key(key)
        transitions = _client.get_transitions(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except Exception:
        raise HTTPException(status_code=404, detail=f"Could not get transitions for {key}")
    return [
        {
            "id": t.get("id", ""),
            "name": t.get("name", ""),
            "to_status": (t.get("to") or {}).get("name", ""),
        }
        for t in transitions
    ]


@router.get("/tickets/{key}")
async def get_ticket(key: str) -> dict[str, Any]:
    """Return detailed information for a single ticket."""
    try:
        validate_jira_key(key)
        return _load_ticket_detail(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except Exception:
        raise HTTPException(status_code=404, detail=f"Issue {key} not found")


@router.put("/tickets/{key}")
async def update_ticket(
    key: str,
    body: TicketUpdateRequest,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Update editable fields on a single ticket."""
    try:
        validate_jira_key(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")

    fields = body.model_fields_set
    if not fields:
        raise HTTPException(status_code=400, detail="No updates requested")

    try:
        if "summary" in fields:
            if body.summary is None or not body.summary.strip():
                raise HTTPException(status_code=400, detail="summary cannot be empty")
            _client.update_summary(key, body.summary.strip())
            cache.update_cached_field(key, "summary", body.summary.strip())

        if "description" in fields:
            _client.update_description(key, body.description or "")
            cache.update_cached_field(key, "description", body.description or "")

        if "priority" in fields:
            if not body.priority:
                raise HTTPException(status_code=400, detail="priority cannot be empty")
            _client.update_priority(key, body.priority)
            cache.update_cached_field(key, "priority", body.priority)

        if "assignee_account_id" in fields:
            account_id = body.assignee_account_id or None
            _client.assign_issue(key, account_id)
            cache.update_cached_field(key, "assignee", _get_assignable_display_name(account_id))

        if "request_type_id" in fields:
            if not body.request_type_id:
                raise HTTPException(status_code=400, detail="request_type_id cannot be empty")
            _client.set_request_type(key, body.request_type_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update ticket %s", key)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    issue = _client.get_issue(key)
    request_type = extract_request_type_name_from_fields(issue.get("fields", {}))
    if request_type:
        cache.update_cached_field(key, "request_type", request_type)
    comments = _client.get_request_comments(key)
    return _ticket_detail(issue, comments)


@router.post("/tickets/{key}/transition")
async def transition_ticket(
    key: str,
    body: TicketTransitionRequest,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Transition a ticket to a new status."""
    try:
        validate_jira_key(key)
        transition_name = ""
        transitions = _client.get_transitions(key)
        for transition in transitions:
            if transition.get("id") == body.transition_id:
                transition_name = (transition.get("to") or {}).get("name", transition.get("name", ""))
                break
        _client.transition_issue(key, body.transition_id)
        if transition_name:
            cache.update_cached_field(key, "status", transition_name)
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
        _client.add_request_comment(key, body.comment.strip(), public=body.public)
        cache.update_cached_field(key, "updated", "")
        return _load_ticket_detail(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except Exception as exc:
        logger.exception("Failed to comment on ticket %s", key)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
