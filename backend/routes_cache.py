"""API routes for cache status and manual refresh."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks

from config import JIRA_BASE_URL
from issue_cache import cache

router = APIRouter(prefix="/api")


@router.get("/cache/status")
async def cache_status() -> dict[str, Any]:
    """Return current cache state."""
    return {**cache.status(), "jira_base_url": JIRA_BASE_URL}


@router.post("/cache/refresh")
async def cache_refresh() -> dict[str, Any]:
    """Trigger a full cache refresh (blocking)."""
    await asyncio.get_event_loop().run_in_executor(None, cache.trigger_refresh)
    return cache.status()


@router.post("/cache/refresh/incremental")
async def cache_refresh_incremental() -> dict[str, Any]:
    """Trigger an incremental cache refresh — only issues updated in last 10 min."""
    await asyncio.get_event_loop().run_in_executor(
        None, cache.trigger_incremental_refresh
    )
    return cache.status()


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

    background_tasks.add_task(asyncio.get_event_loop().run_in_executor, None, _run)
    return {"started": True, "message": "Request type enrichment started in background"}


@router.get("/cache/enrich-status")
async def enrich_status() -> dict[str, Any]:
    """Check enrichment progress."""
    return dict(_enrich_status)
