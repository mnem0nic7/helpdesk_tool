from __future__ import annotations

import asyncio

import pytest

from ai_background_worker import AIBackgroundWorker


@pytest.mark.asyncio
async def test_background_ai_worker_runs_jobs_serially():
    worker = AIBackgroundWorker()
    events: list[str] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def first_job() -> str:
        events.append("first-start")
        first_started.set()
        await release_first.wait()
        events.append("first-end")
        return "first"

    async def second_job() -> str:
        events.append("second-start")
        return "second"

    task_one = asyncio.create_task(
        worker.run_item(lane="auto_triage", key="OIT-1", work=first_job)
    )
    await first_started.wait()

    task_two = asyncio.create_task(
        worker.run_item(lane="technician_scoring", key="OIT-2", work=second_job)
    )

    await asyncio.sleep(0.02)
    assert events == ["first-start"]
    assert worker.status()["busy"] is True

    release_first.set()
    assert await task_one == "first"
    assert await task_two == "second"
    assert events == ["first-start", "first-end", "second-start"]
    assert worker.status()["busy"] is False
