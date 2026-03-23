from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_work_scheduler import AIWorkScheduler


def _build_scheduler(*, cache, manager, qa_poll_interval_seconds: float = 3600) -> AIWorkScheduler:
    return AIWorkScheduler(
        cache=cache,
        technician_scoring_manager=manager,
        qa_poll_interval_seconds=qa_poll_interval_seconds,
        idle_interval_seconds=0.01,
        defer_interval_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_scheduler_prefers_auto_triage_before_qa() -> None:
    cache = MagicMock()
    cache.warming = False
    cache._auto_triage_new_tickets = AsyncMock()

    def auto_triage_status(scope=None):
        if scope is None:
            return {"running": False, "pending_count": 1}
        if scope == "primary":
            return {"running": False, "pending_keys": ["OIT-101"]}
        return {"running": False, "pending_keys": []}

    cache.auto_triage_status.side_effect = auto_triage_status

    manager = MagicMock()
    manager.get_progress.return_value = {"running": False}
    manager.preview_scope_run.return_value = {"total_tickets": 1}
    manager.run_scope_once = AsyncMock()

    scheduler = _build_scheduler(cache=cache, manager=manager)

    outcome = await scheduler._run_once()

    assert outcome == "processed"
    cache._auto_triage_new_tickets.assert_awaited_once_with(["OIT-101"])
    manager.run_scope_once.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduler_rechecks_auto_triage_before_next_qa_item() -> None:
    cache = MagicMock()
    cache.warming = False
    cache._auto_triage_new_tickets = AsyncMock()

    state = {"phase": "qa_first"}

    def auto_triage_status(scope=None):
        triage_pending = state["phase"] == "triage_second"
        if scope is None:
            return {"running": False, "pending_count": 1 if triage_pending else 0}
        if scope == "primary":
            return {"running": False, "pending_keys": ["OIT-500"] if triage_pending else []}
        return {"running": False, "pending_keys": []}

    cache.auto_triage_status.side_effect = auto_triage_status

    manager = MagicMock()
    manager.get_progress.return_value = {"running": False}
    manager.preview_scope_run.return_value = {"total_tickets": 1}

    async def fake_run_scope_once(scope, *, reset=False, limit=None, trigger="manual"):
        state["phase"] = "triage_second"
        return {"started": True, "total_tickets": 1}

    manager.run_scope_once = AsyncMock(side_effect=fake_run_scope_once)

    scheduler = _build_scheduler(cache=cache, manager=manager)

    first_outcome = await scheduler._run_once()
    second_outcome = await scheduler._run_once()

    assert first_outcome == "processed"
    assert second_outcome == "processed"
    manager.run_scope_once.assert_awaited_once_with("primary", limit=1, trigger="scheduled")
    cache._auto_triage_new_tickets.assert_awaited_once_with(["OIT-500"])


@pytest.mark.asyncio
async def test_scheduler_sets_next_hourly_qa_sweep_only_after_backlog_is_empty() -> None:
    cache = MagicMock()
    cache.warming = False
    cache._auto_triage_new_tickets = AsyncMock()

    def auto_triage_status(scope=None):
        if scope is None:
            return {"running": False, "pending_count": 0}
        return {"running": False, "pending_keys": []}

    cache.auto_triage_status.side_effect = auto_triage_status

    manager = MagicMock()
    manager.get_progress.return_value = {"running": False}
    manager.preview_scope_run.return_value = {"total_tickets": 0}
    manager.run_scope_once = AsyncMock()

    scheduler = _build_scheduler(cache=cache, manager=manager, qa_poll_interval_seconds=600)
    before = scheduler._next_qa_sweep_at

    outcome = await scheduler._run_once()

    assert outcome == "idle"
    assert scheduler._next_qa_sweep_at > before
    assert scheduler._next_qa_sweep_at - scheduler._utcnow() <= timedelta(seconds=600)
    manager.run_scope_once.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduler_defers_qa_while_manual_qa_is_running() -> None:
    cache = MagicMock()
    cache.warming = False
    cache._auto_triage_new_tickets = AsyncMock()

    def auto_triage_status(scope=None):
        if scope is None:
            return {"running": False, "pending_count": 0}
        return {"running": False, "pending_keys": []}

    cache.auto_triage_status.side_effect = auto_triage_status

    manager = MagicMock()
    manager.get_progress.side_effect = lambda scope: {"running": scope == "primary"}
    manager.preview_scope_run.return_value = {"total_tickets": 1}
    manager.run_scope_once = AsyncMock()

    scheduler = _build_scheduler(cache=cache, manager=manager)

    outcome = await scheduler._run_once()

    assert outcome == "deferred"
    manager.run_scope_once.assert_not_awaited()
