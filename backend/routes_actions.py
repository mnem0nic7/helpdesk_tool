"""API routes for bulk ticket actions (status, assign, priority, comment)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from auth import require_admin
from jira_client import JiraClient
from jira_write_service import add_fallback_internal_audit_note, get_jira_write_context, prepend_fallback_actor_line
from issue_cache import cache
from models import (
    BulkAssignRequest,
    BulkCommentRequest,
    BulkPriorityRequest,
    BulkStatusRequest,
)
from site_context import key_is_visible_in_scope

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
    allowed_keys = [key for key in req.keys if key_is_visible_in_scope(key)]
    blocked_keys = [key for key in req.keys if key not in allowed_keys]
    failed.extend({"key": key, "error": "Ticket is not available on this site"} for key in blocked_keys)

    # Resolve transition name for cache update (same transition for all keys)
    transition_name = ""
    if allowed_keys:
        try:
            transitions = _client.get_transitions(allowed_keys[0])
            for t in transitions:
                if t.get("id") == req.transition_id:
                    transition_name = t.get("to", {}).get("name", t.get("name", ""))
                    break
        except Exception:
            logger.exception(
                "Bulk status transition lookup failed for %s via %s",
                allowed_keys[0],
                req.transition_id,
            )

    for key in allowed_keys:
        try:
            ctx = get_jira_write_context(_admin, shared_client=_client)
            ctx.client.transition_issue(key, req.transition_id)
            success.append(key)
            if transition_name:
                cache.update_cached_field(key, "status", transition_name)
            if ctx.is_fallback:
                add_fallback_internal_audit_note(
                    key,
                    action_summary=f"Bulk status change to {transition_name or req.transition_id}",
                    session=_admin,
                    shared_client=_client,
                )
        except Exception as exc:
            logger.exception("Bulk status transition failed for %s via %s", key, req.transition_id)
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)


@router.post("/assign")
async def bulk_assign(req: BulkAssignRequest, _admin: dict = Depends(require_admin)) -> list[dict[str, Any]]:
    """Reassign multiple issues to a single account."""
    success: list[str] = []
    failed: list[dict[str, str]] = []
    allowed_keys = [key for key in req.keys if key_is_visible_in_scope(key)]
    blocked_keys = [key for key in req.keys if key not in allowed_keys]
    failed.extend({"key": key, "error": "Ticket is not available on this site"} for key in blocked_keys)

    # Resolve display name for cache update
    display_name = ""
    project_name = ""
    if req.account_id:
        try:
            from config import JIRA_PROJECT
            project_name = JIRA_PROJECT
            users = _client.get_users_assignable(JIRA_PROJECT)
            for u in users:
                if u.get("accountId") == req.account_id:
                    display_name = u.get("displayName", "")
                    break
        except Exception:
            logger.exception(
                "Bulk assignee lookup failed for %s in project %s",
                req.account_id,
                project_name or "(unknown)",
            )

    for key in allowed_keys:
        try:
            ctx = get_jira_write_context(_admin, shared_client=_client)
            ctx.client.assign_issue(key, req.account_id)
            success.append(key)
            cache.update_cached_field(
                key,
                "assignee",
                {"displayName": display_name, "accountId": req.account_id},
            )
            if ctx.is_fallback:
                add_fallback_internal_audit_note(
                    key,
                    action_summary=f"Bulk assignee change to {display_name or req.account_id or 'Unassigned'}",
                    session=_admin,
                    shared_client=_client,
                )
        except Exception as exc:
            logger.exception("Bulk assign failed for %s to %s", key, req.account_id)
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)


@router.post("/priority")
async def bulk_priority(req: BulkPriorityRequest, _admin: dict = Depends(require_admin)) -> list[dict[str, Any]]:
    """Change the priority of multiple issues."""
    success: list[str] = []
    failed: list[dict[str, str]] = []
    allowed_keys = [key for key in req.keys if key_is_visible_in_scope(key)]
    blocked_keys = [key for key in req.keys if key not in allowed_keys]
    failed.extend({"key": key, "error": "Ticket is not available on this site"} for key in blocked_keys)

    for key in allowed_keys:
        try:
            ctx = get_jira_write_context(_admin, shared_client=_client)
            ctx.client.update_priority(key, req.priority)
            success.append(key)
            cache.update_cached_field(key, "priority", req.priority)
            if ctx.is_fallback:
                add_fallback_internal_audit_note(
                    key,
                    action_summary=f"Bulk priority change to {req.priority}",
                    session=_admin,
                    shared_client=_client,
                )
        except Exception as exc:
            logger.exception("Bulk priority update failed for %s to %s", key, req.priority)
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)


@router.post("/comment")
async def bulk_comment(req: BulkCommentRequest, _admin: dict = Depends(require_admin)) -> list[dict[str, Any]]:
    """Add the same comment to multiple issues."""
    success: list[str] = []
    failed: list[dict[str, str]] = []
    allowed_keys = [key for key in req.keys if key_is_visible_in_scope(key)]
    blocked_keys = [key for key in req.keys if key not in allowed_keys]
    failed.extend({"key": key, "error": "Ticket is not available on this site"} for key in blocked_keys)

    for key in allowed_keys:
        try:
            ctx = get_jira_write_context(_admin, shared_client=_client)
            comment_text = req.comment
            if ctx.is_fallback:
                comment_text = prepend_fallback_actor_line(comment_text, _admin)
            ctx.client.add_comment(key, comment_text)
            success.append(key)
            # Bump updated timestamp in cache
            cache.update_cached_field(key, "updated", "")
        except Exception as exc:
            logger.exception("Bulk comment failed for %s", key)
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)
