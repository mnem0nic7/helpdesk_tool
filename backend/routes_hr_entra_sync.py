"""Admin routes for the Entra -> Jira HR ticket sync."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

import hr_entra_field_map as fmap
from auth import require_admin
from config import HR_ENTRA_SYNC_ENABLED, HR_ENTRA_SYNC_PROJECTS, HR_ENTRA_SYNC_RETRY_MINUTES
from hr_entra_sync import hr_entra_sync_job
from jira_client import validate_jira_key

router = APIRouter(prefix="/api/hr-entra-sync", tags=["hr-entra-sync"])


@router.get("/status", dependencies=[Depends(require_admin)])
async def get_status() -> dict[str, Any]:
    return {
        "enabled": HR_ENTRA_SYNC_ENABLED,
        "projects": HR_ENTRA_SYNC_PROJECTS,
        "retry_minutes": HR_ENTRA_SYNC_RETRY_MINUTES,
        "active_fields": [m.jira_name for m in fmap.active_mappings()],
        "inactive_fields": [
            {"jira_name": m.jira_name, "enabled": m.enabled, "has_jira_field_id": bool(m.jira_field_id), "note": m.note}
            for m in fmap.FIELD_MAP
            if m not in fmap.active_mappings()
        ],
    }


@router.get("/issues", dependencies=[Depends(require_admin)])
async def list_issues(
    status: str | None = None, limit: int = Query(100, ge=1, le=500)
) -> dict[str, Any]:
    return {"issues": hr_entra_sync_job.list_rows(status=status, limit=limit)}


@router.post("/issues/{issue_key}/run", dependencies=[Depends(require_admin)])
async def run_for_issue(issue_key: str, dry_run: bool = True) -> dict[str, Any]:
    """Run the sync for one ticket now. Defaults to a dry run that reports what would be written."""
    try:
        validate_jira_key(issue_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    import asyncio

    return await asyncio.to_thread(hr_entra_sync_job.sync_issue, issue_key, dry_run=dry_run)
