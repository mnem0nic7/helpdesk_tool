"""Shared single-lane background AI worker coordination."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


class AIBackgroundWorker:
    """Coordinate a single background AI lane across auto-triage and QA scoring."""

    def __init__(self) -> None:
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._current_job: dict[str, Any] | None = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:
            self._lock = asyncio.Lock()
            self._loop = loop
        return self._lock

    def status(self) -> dict[str, Any]:
        job = dict(self._current_job) if isinstance(self._current_job, dict) else None
        return {
            "busy": bool(self._lock and self._lock.locked()),
            "job": job,
        }

    async def run_item(
        self,
        *,
        lane: str,
        key: str | None,
        work: Callable[[], Awaitable[T]],
    ) -> T:
        lock = self._get_lock()
        async with lock:
            self._current_job = {
                "lane": lane,
                "key": key,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                return await work()
            finally:
                self._current_job = None


background_ai_worker = AIBackgroundWorker()
