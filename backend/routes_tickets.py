"""API routes for ticket listing, detail, assignees, and statuses."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from config import JIRA_PROJECT
from issue_cache import cache
from jira_client import JiraClient
from metrics import issue_to_row

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Shared client instance (still needed for single-ticket detail, assignees, transitions)
_client = JiraClient()

# Stale threshold — matches metrics.py _STALE_DAYS
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
            # ADF format — search the text content
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
) -> dict[str, Any]:
    """Return all filtered OIT tickets from cache."""
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

    # Sort by created date descending
    matched.sort(
        key=lambda iss: iss.get("fields", {}).get("created", ""),
        reverse=True,
    )

    return {
        "tickets": [issue_to_row(iss) for iss in matched],
        "total_count": len(issues),
    }


@router.get("/tickets/{key}")
async def get_ticket(key: str) -> dict[str, Any]:
    """Return detail for a single ticket."""
    from jira_client import validate_jira_key
    try:
        validate_jira_key(key)
        issue = _client.get_issue(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except Exception:
        raise HTTPException(status_code=404, detail=f"Issue {key} not found")
    return issue_to_row(issue)


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
    from jira_client import validate_jira_key
    try:
        validate_jira_key(key)
        transitions = _client.get_transitions(key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid issue key: {key}")
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=f"Could not get transitions for {key}",
        )
    return [
        {"id": t.get("id", ""), "name": t.get("name", "")}
        for t in transitions
    ]
