"""Shared single-lane background AI worker coordination."""

from __future__ import annotations

import asyncio
import heapq
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")

_DEFAULT_LANE_PRIORITIES: dict[str, int] = {
    "report_export_summary": 0,
    "report_batch_summary": 1,
    "auto_triage": 2,
    "technician_scoring": 3,
    "report_nightly_summary": 4,
}


@dataclass(order=True)
class _QueuedJob:
    priority: int
    order: int
    lane: str = field(compare=False)
    key: str | None = field(compare=False)
    work: Callable[[], Awaitable[Any]] = field(compare=False)
    future: asyncio.Future[Any] = field(compare=False)
    enqueued_at: str = field(compare=False)


class AIBackgroundWorker:
    """Coordinate a single background AI lane with non-preemptive priorities."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: list[_QueuedJob] = []
        self._queue_changed: asyncio.Event | None = None
        self._runner_task: asyncio.Task[None] | None = None
        self._current_job: dict[str, Any] | None = None
        self._counter = 0

    def _ensure_loop_state(self) -> tuple[asyncio.AbstractEventLoop, asyncio.Event]:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self._loop = loop
            self._queue = []
            self._queue_changed = asyncio.Event()
            self._runner_task = None
            self._current_job = None
            self._counter = 0
        assert self._queue_changed is not None
        if self._runner_task is None or self._runner_task.done():
            self._runner_task = loop.create_task(self._runner())
        return loop, self._queue_changed

    def status(self) -> dict[str, Any]:
        job = dict(self._current_job) if isinstance(self._current_job, dict) else None
        queued = [
            {
                "lane": item.lane,
                "key": item.key,
                "priority": item.priority,
                "enqueued_at": item.enqueued_at,
            }
            for item in sorted(self._queue)
        ]
        return {
            "busy": bool(job),
            "job": job,
            "queued": queued,
        }

    async def _runner(self) -> None:
        assert self._queue_changed is not None
        while True:
            while not self._queue:
                self._queue_changed.clear()
                await self._queue_changed.wait()
            item = heapq.heappop(self._queue)
            self._current_job = {
                "lane": item.lane,
                "key": item.key,
                "priority": item.priority,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "enqueued_at": item.enqueued_at,
            }
            try:
                result = await item.work()
            except Exception as exc:
                if not item.future.done():
                    item.future.set_exception(exc)
            else:
                if not item.future.done():
                    item.future.set_result(result)
            finally:
                self._current_job = None

    async def run_item(
        self,
        *,
        lane: str,
        key: str | None,
        work: Callable[[], Awaitable[T]],
        priority: int | None = None,
    ) -> T:
        loop, queue_changed = self._ensure_loop_state()
        resolved_priority = (
            int(priority)
            if priority is not None
            else _DEFAULT_LANE_PRIORITIES.get(lane, max(_DEFAULT_LANE_PRIORITIES.values()) + 1)
        )
        future: asyncio.Future[T] = loop.create_future()
        queued = _QueuedJob(
            priority=resolved_priority,
            order=self._counter,
            lane=lane,
            key=key,
            work=work,
            future=future,
            enqueued_at=datetime.now(timezone.utc).isoformat(),
        )
        self._counter += 1
        heapq.heappush(self._queue, queued)
        queue_changed.set()
        return await future


background_ai_worker = AIBackgroundWorker()
