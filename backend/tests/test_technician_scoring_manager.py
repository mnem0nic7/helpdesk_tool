from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import technician_scoring_manager as manager_module
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


def test_preview_scope_run_raises_while_issue_cache_is_warming(monkeypatch):
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

    monkeypatch.setattr(manager_module, "cache", SimpleNamespace(initialized=False, warming=True))

    with pytest.raises(RuntimeError, match="Issue cache is still warming"):
        manager.preview_scope_run("primary")


@pytest.mark.asyncio
async def test_run_scope_once_skips_scheduled_scoring_while_cache_is_warming(monkeypatch):
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

    monkeypatch.setattr(manager_module, "cache", SimpleNamespace(initialized=False, warming=True))

    result = await manager.run_scope_once("primary", trigger="scheduled")

    assert result["started"] is False
    assert "warming" in result["message"].lower()
    assert progress["primary"]["last_error"]
