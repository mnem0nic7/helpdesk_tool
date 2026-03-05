"""API routes for cache status and manual refresh."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

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
