"""API routes for cache status and manual refresh."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends

from auth import require_admin
from config import JIRA_BASE_URL
from issue_cache import cache

router = APIRouter(prefix="/api")


@router.get("/cache/status")
async def cache_status() -> dict[str, Any]:
    """Return current cache state."""
    return {**cache.status(), "jira_base_url": JIRA_BASE_URL}


@router.post("/cache/refresh")
async def cache_refresh(background_tasks: BackgroundTasks, _admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Trigger a full cache refresh (non-blocking — poll /cache/status for progress)."""
    if cache.refreshing:
        return {**cache.status(), "jira_base_url": JIRA_BASE_URL, "message": "Refresh already in progress"}

    async def _run() -> None:
        await asyncio.get_running_loop().run_in_executor(None, cache.trigger_refresh)

    background_tasks.add_task(_run)
    return {**cache.status(), "jira_base_url": JIRA_BASE_URL, "started": True}


@router.post("/cache/refresh/incremental")
async def cache_refresh_incremental(background_tasks: BackgroundTasks, _admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Trigger an incremental cache refresh (non-blocking — poll /cache/status for progress)."""
    if cache.refreshing:
        return {**cache.status(), "jira_base_url": JIRA_BASE_URL, "message": "Refresh already in progress"}

    async def _run() -> None:
        await asyncio.get_running_loop().run_in_executor(None, cache.trigger_incremental_refresh)

    background_tasks.add_task(_run)
    return {**cache.status(), "jira_base_url": JIRA_BASE_URL, "started": True}


@router.post("/cache/refresh/cancel")
async def cancel_refresh() -> dict[str, Any]:
    """Cancel an in-progress cache refresh."""
    cancelled = cache.cancel_refresh()
    return {"cancelled": cancelled}


_enrich_status: dict[str, Any] = {"running": False, "enriched": 0}


@router.post("/cache/enrich-request-types")
async def enrich_request_types(background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Enrich all cached issues missing request type data (runs in background)."""
    if _enrich_status["running"]:
        return {"started": False, "message": "Enrichment already running", **_enrich_status}

    def _run() -> None:
        _enrich_status.update(running=True, enriched=0)
        try:
            enriched = cache.enrich_missing_request_types()
            _enrich_status["enriched"] = enriched
        finally:
            _enrich_status["running"] = False

    async def _run_bg() -> None:
        await asyncio.get_running_loop().run_in_executor(None, _run)

    background_tasks.add_task(_run_bg)
    return {"started": True, "message": "Request type enrichment started in background"}


@router.get("/cache/enrich-status")
async def enrich_status() -> dict[str, Any]:
    """Check enrichment progress."""
    return dict(_enrich_status)
