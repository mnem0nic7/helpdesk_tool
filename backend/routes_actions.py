"""API routes for bulk ticket actions (status, assign, priority, comment)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from jira_client import JiraClient
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


def _bulk_result(success: list[str], failed: list[dict[str, str]]) -> dict[str, Any]:
    """Return a standard bulk-action response envelope."""
    return {"success": success, "failed": failed}


@router.post("/status")
async def bulk_status(req: BulkStatusRequest) -> dict[str, Any]:
    """Transition multiple issues to a new status."""
    success: list[str] = []
    failed: list[dict[str, str]] = []

    for key in req.keys:
        try:
            _client.transition_issue(key, req.transition_id)
            success.append(key)
        except Exception as exc:
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)


@router.post("/assign")
async def bulk_assign(req: BulkAssignRequest) -> dict[str, Any]:
    """Reassign multiple issues to a single account."""
    success: list[str] = []
    failed: list[dict[str, str]] = []

    for key in req.keys:
        try:
            _client.assign_issue(key, req.account_id)
            success.append(key)
        except Exception as exc:
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)


@router.post("/priority")
async def bulk_priority(req: BulkPriorityRequest) -> dict[str, Any]:
    """Change the priority of multiple issues."""
    success: list[str] = []
    failed: list[dict[str, str]] = []

    for key in req.keys:
        try:
            _client.update_priority(key, req.priority)
            success.append(key)
        except Exception as exc:
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)


@router.post("/comment")
async def bulk_comment(req: BulkCommentRequest) -> dict[str, Any]:
    """Add the same comment to multiple issues."""
    success: list[str] = []
    failed: list[dict[str, str]] = []

    for key in req.keys:
        try:
            _client.add_comment(key, req.comment)
            success.append(key)
        except Exception as exc:
            failed.append({"key": key, "error": str(exc)})

    return _bulk_result(success, failed)
