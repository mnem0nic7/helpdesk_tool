"""Admin routes for the HR auto-cancel job (osidigital.com -> Cancelled by HR)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query

from auth import require_admin
from config import (
    HR_AUTO_CANCEL_ENABLED,
    HR_AUTO_CANCEL_LOOKBACK_MINUTES,
    HR_AUTO_CANCEL_PROJECTS,
    HR_AUTO_CANCEL_SENDER_DOMAINS,
    HR_AUTO_CANCEL_STATUS,
)
from hr_auto_cancel import hr_auto_cancel_job

router = APIRouter(prefix="/api/hr-auto-cancel", tags=["hr-auto-cancel"])


@router.get("/status", dependencies=[Depends(require_admin)])
async def get_status() -> dict[str, Any]:
    return {
        "enabled": HR_AUTO_CANCEL_ENABLED,
        "projects": HR_AUTO_CANCEL_PROJECTS,
        "sender_domains": HR_AUTO_CANCEL_SENDER_DOMAINS,
        "target_status": HR_AUTO_CANCEL_STATUS,
        "lookback_minutes": HR_AUTO_CANCEL_LOOKBACK_MINUTES,
        **hr_auto_cancel_job.summary(),
    }


@router.get("/actions", dependencies=[Depends(require_admin)])
async def list_actions(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    return {"actions": hr_auto_cancel_job.list_rows(limit)}


@router.get("/preview", dependencies=[Depends(require_admin)])
async def preview() -> dict[str, Any]:
    """Tickets the next cycle would cancel (read-only)."""
    return {"would_cancel": await asyncio.to_thread(hr_auto_cancel_job.preview)}
