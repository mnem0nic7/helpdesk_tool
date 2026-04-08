"""FastAPI routes for the deactivation scheduling system."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_authenticated_user, require_can_manage_users
from deactivation_schedule import deactivation_schedule

router = APIRouter(prefix="/api/deactivation-schedule", tags=["deactivation-schedule"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CreateDeactivationJobRequest(BaseModel):
    ticket_key: str
    display_name: str
    entra_user_id: str
    ad_sam: str = ""
    run_at: str  # ISO-8601 UTC datetime string
    timezone_label: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("")
async def create_job(
    body: CreateDeactivationJobRequest,
    user: dict[str, Any] = Depends(require_can_manage_users),
) -> dict[str, Any]:
    """Schedule a new deactivation job."""
    try:
        run_at_dt = datetime.fromisoformat(body.run_at)
        if run_at_dt.tzinfo is None:
            run_at_dt = run_at_dt.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid run_at datetime: {exc}")

    created_by = user.get("email") or user.get("name") or "unknown"

    job = deactivation_schedule.create(
        ticket_key=body.ticket_key,
        display_name=body.display_name,
        entra_user_id=body.entra_user_id,
        ad_sam=body.ad_sam,
        run_at=run_at_dt,
        timezone_label=body.timezone_label,
        created_by=created_by,
    )
    return job


@router.get("", dependencies=[Depends(require_authenticated_user)])
async def list_all_jobs(limit: int = 100) -> list[dict[str, Any]]:
    """List recent deactivation jobs (most recent first)."""
    return deactivation_schedule.list_all(limit=limit)


@router.get("/{ticket_key}", dependencies=[Depends(require_authenticated_user)])
async def list_jobs_for_ticket(ticket_key: str) -> list[dict[str, Any]]:
    """List deactivation jobs for a specific ticket."""
    return deactivation_schedule.list_for_ticket(ticket_key)


@router.delete("/{job_id}", dependencies=[Depends(require_can_manage_users)])
async def cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel a pending deactivation job."""
    cancelled = deactivation_schedule.cancel(job_id)
    if not cancelled:
        raise HTTPException(
            status_code=404,
            detail="Job not found or is not in a cancellable state (must be pending)",
        )
    job = deactivation_schedule.get(job_id)
    return job or {"job_id": job_id, "status": "cancelled"}
