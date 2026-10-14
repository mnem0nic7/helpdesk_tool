"""Admin routes for the Entra -> Jira HR ticket sync."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

import hr_entra_field_map as fmap
from auth import require_admin
from config import (
    HR_ENTRA_SYNC_ENABLED,
    HR_ENTRA_SYNC_LOOKBACK_MINUTES,
    HR_ENTRA_SYNC_POLL_SECONDS,
    HR_ENTRA_SYNC_PROJECTS,
    HR_ENTRA_SYNC_RETRY_MINUTES,
)
from hr_entra_sync import hr_entra_sync_job
from jira_client import validate_jira_key

router = APIRouter(prefix="/api/hr-entra-sync", tags=["hr-entra-sync"])


@router.get("/status", dependencies=[Depends(require_admin)])
async def get_status() -> dict[str, Any]:
    active = fmap.active_mappings()
    return {
        "enabled": HR_ENTRA_SYNC_ENABLED,
        "projects": HR_ENTRA_SYNC_PROJECTS,
        "retry_minutes": HR_ENTRA_SYNC_RETRY_MINUTES,
        "poll_seconds": HR_ENTRA_SYNC_POLL_SECONDS,
        "lookback_minutes": HR_ENTRA_SYNC_LOOKBACK_MINUTES,
        **hr_entra_sync_job.summary(),
        "mappings": [
            {
                "jira_name": m.jira_name,
                "jira_field_id": m.jira_field_id,
                "entra_source": (
                    {"manager_name": "manager → displayName", "manager_email": "manager → mail"}.get(m.derived or "")
                    or (m.entra_property or "").replace(fmap.EXT_PREFIX, "ext:")
                    or None
                ),
                "kind": m.kind,
                "active": m in active,
                "note": m.note,
            }
            for m in fmap.FIELD_MAP
        ],
        "active_fields": [m.jira_name for m in active],
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
async def run_for_issue(
    issue_key: str, dry_run: bool = True, email: str | None = None
) -> dict[str, Any]:
    """Run the sync for one ticket now. Defaults to a dry run that reports what would be written.

    ``email`` substitutes for the ticket's own email fields (testing tickets that carry none) and is
    only allowed on a dry run, so it can never write one person's data onto another's ticket.
    """
    try:
        validate_jira_key(issue_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if email and not dry_run:
        raise HTTPException(status_code=400, detail="email override is only allowed with dry_run=true")
    if email and not fmap.normalize_email(email):
        raise HTTPException(status_code=400, detail="email override is not a valid address")
    import asyncio

    result = await asyncio.to_thread(
        hr_entra_sync_job.sync_issue, issue_key, dry_run=dry_run, email_override=email
    )
    # Dry-run payload values are Entra data about a person; the page only needs which fields.
    if "fields_written" in result and dry_run:
        result = {**result, "fields_written": sorted(result["fields_written"])}
    return result
