"""API routes for bulk ticket actions (status, assign, priority, comment)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from auth import require_admin
from jira_client import JiraClient
from issue_cache import cache
from models import (
    BulkAssignRequest,
    BulkCommentRequest,
    BulkPriorityRequest,
    BulkStatusRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tickets/bulk")

# Shared client instance
_client = JiraClient()


def _bulk_result(success: list[str], failed: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Return a list of per-ticket results matching the frontend BulkResult type."""
    results: list[dict[str, Any]] = []
    for key in success:
        results.append({"key": key, "success": True})
    for entry in failed:
        results.append({"key": entry["key"], "success": False, "error": entry.get("error", "")})
    return results


@router.post("/status")
async def bulk_status(req: BulkStatusRequest, _admin: dict = Depends(require_admin)) -> list[dict[str, Any]]:
    """Transition multiple issues to a new status."""
    success: list[str] = []
    failed: list[dict[str, str]] = []

    # Resolve transition name for cache update (same transition for all keys)
    transition_name = ""
    if req.keys:
        try:
            transitions = _client.get_transitions(req.keys[0])
            for t in transitions:
                if t.get("id") == req.transition_id:
                    transition_name = t.get("to", {}).get("name", t.get("name", ""))
                    break
        except Exception:
            pass

    for key in req.keys:
        try:
            _client.transition_issue(key, req.transition_id)
            success.append(key)
            if transition_name:
                cache.update_cached_field(key, "status", transition_name)
        except Exception as exc:
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)


@router.post("/assign")
async def bulk_assign(req: BulkAssignRequest, _admin: dict = Depends(require_admin)) -> list[dict[str, Any]]:
    """Reassign multiple issues to a single account."""
    success: list[str] = []
    failed: list[dict[str, str]] = []

    # Resolve display name for cache update
    display_name = ""
    if req.account_id:
        try:
            from config import JIRA_PROJECT
            users = _client.get_users_assignable(JIRA_PROJECT)
            for u in users:
                if u.get("accountId") == req.account_id:
                    display_name = u.get("displayName", "")
                    break
        except Exception:
            pass

    for key in req.keys:
        try:
            _client.assign_issue(key, req.account_id)
            success.append(key)
            cache.update_cached_field(key, "assignee", display_name)
        except Exception as exc:
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)


@router.post("/priority")
async def bulk_priority(req: BulkPriorityRequest, _admin: dict = Depends(require_admin)) -> list[dict[str, Any]]:
    """Change the priority of multiple issues."""
    success: list[str] = []
    failed: list[dict[str, str]] = []

    for key in req.keys:
        try:
            _client.update_priority(key, req.priority)
            success.append(key)
            cache.update_cached_field(key, "priority", req.priority)
        except Exception as exc:
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)


@router.post("/comment")
async def bulk_comment(req: BulkCommentRequest, _admin: dict = Depends(require_admin)) -> list[dict[str, Any]]:
    """Add the same comment to multiple issues."""
    success: list[str] = []
    failed: list[dict[str, str]] = []

    for key in req.keys:
        try:
            _client.add_comment(key, req.comment)
            success.append(key)
            # Bump updated timestamp in cache
            cache.update_cached_field(key, "updated", "")
        except Exception as exc:
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)
