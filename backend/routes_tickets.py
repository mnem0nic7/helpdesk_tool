"""API routes for ticket listing, detail, assignees, and statuses."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from config import JIRA_PROJECT
from jira_client import JiraClient
from metrics import issue_to_row

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Shared client instance
_client = JiraClient()


@router.get("/tickets")
async def list_tickets(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
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
    """Return a paginated, filtered list of OIT tickets."""
    # Build JQL from filters
    clauses: list[str] = [
        f"project = {JIRA_PROJECT}",
        '(labels is EMPTY OR labels not in ("oasisdev"))',
    ]

    if status:
        clauses.append(f'status = "{status}"')
    if priority:
        clauses.append(f'priority = "{priority}"')
    if assignee:
        clauses.append(f'assignee = "{assignee}"')
    if issue_type:
        clauses.append(f'issuetype = "{issue_type}"')
    if search:
        # Jira text search across summary and description
        clauses.append(f'text ~ "{search}"')
    if open_only:
        clauses.append('statusCategory != "Done"')
    if stale_only:
        clauses.append("updated <= -7d")
    if created_after:
        clauses.append(f'created >= "{created_after}"')
    if created_before:
        clauses.append(f'created <= "{created_before}"')

    jql = " AND ".join(clauses) + " ORDER BY created DESC"

    start_at = (page - 1) * page_size

    data = _client.search(jql, max_results=page_size, start_at=start_at)
    issues = data.get("issues", [])
    is_last = data.get("isLast", True)

    return {
        "tickets": [issue_to_row(iss) for iss in issues],
        "has_more": not is_last,
        "page": page,
        "page_size": page_size,
    }


@router.get("/tickets/{key}")
async def get_ticket(key: str) -> dict[str, Any]:
    """Return detail for a single ticket."""
    try:
        issue = _client.get_issue(key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Issue {key} not found: {exc}")
    return issue_to_row(issue)


@router.get("/assignees")
async def get_assignees() -> list[dict[str, Any]]:
    """Return the list of assignable users for the OIT project."""
    users = _client.get_users_assignable(JIRA_PROJECT)
    return [
        {
            "accountId": u.get("accountId", ""),
            "displayName": u.get("displayName", ""),
            "emailAddress": u.get("emailAddress", ""),
        }
        for u in users
    ]


@router.get("/statuses/{key}")
async def get_statuses(key: str) -> list[dict[str, Any]]:
    """Return available transitions for a given issue."""
    try:
        transitions = _client.get_transitions(key)
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Could not get transitions for {key}: {exc}",
        )
    return [
        {"id": t.get("id", ""), "name": t.get("name", "")}
        for t in transitions
    ]
