from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from technician_scoring_manager import TechnicianScoringManager, new_progress_state


@pytest.mark.asyncio
async def test_background_loop_runs_scheduled_scoring_for_both_scopes(monkeypatch):
    progress = {
        "primary": new_progress_state(),
        "oasisdev": new_progress_state(),
    }
    manager = TechnicianScoringManager(
        client=MagicMock(),
        store=MagicMock(),
        progress_by_scope=progress,
        poll_interval_seconds=60,
    )
    manager._poll_interval_seconds = 0.01

    seen: list[tuple[str, str]] = []

    async def fake_run_scope_once(scope, *, reset=False, limit=None, trigger="manual"):
        seen.append((scope, trigger))
        return {"started": True, "total_tickets": 0}

    monkeypatch.setattr(manager, "run_scope_once", fake_run_scope_once)

    await manager.start_worker()
    await asyncio.sleep(0.05)
    await manager.stop_worker()

    assert ("primary", "scheduled") in seen
    assert ("oasisdev", "scheduled") in seen
