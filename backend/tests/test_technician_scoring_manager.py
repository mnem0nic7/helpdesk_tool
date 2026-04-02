from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import technician_scoring_manager as manager_module
from models import TechnicianScore
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


def test_preview_scope_run_raises_while_auto_triage_has_priority(monkeypatch):
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

    monkeypatch.setattr(
        manager_module,
        "cache",
        SimpleNamespace(
            initialized=True,
            warming=False,
            auto_triage_status=lambda: {
                "running": True,
                "current_key": "OIT-123",
                "pending_count": 3,
            },
        ),
    )

    with pytest.raises(RuntimeError, match="Processing new tickets takes priority"):
        manager.preview_scope_run("primary")


def test_select_model_id_prefers_technician_score_model_and_falls_back(monkeypatch):
    monkeypatch.setattr(
        manager_module,
        "get_available_models",
        lambda: [
            SimpleNamespace(id="nemotron-3-nano:4b", provider="ollama"),
            SimpleNamespace(id="qwen3.5:4b", provider="ollama"),
        ],
    )
    monkeypatch.setattr(manager_module, "TECHNICIAN_SCORE_MODEL", "nemotron-3-nano:4b")
    monkeypatch.setattr(manager_module, "OLLAMA_MODEL", "qwen3.5:4b")

    assert TechnicianScoringManager._select_model_id() == "nemotron-3-nano:4b"

    monkeypatch.setattr(
        manager_module,
        "get_available_models",
        lambda: [SimpleNamespace(id="qwen3.5:4b", provider="ollama")],
    )

    assert TechnicianScoringManager._select_model_id() == "qwen3.5:4b"


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


@pytest.mark.asyncio
async def test_run_scope_once_pauses_when_auto_triage_becomes_priority(monkeypatch):
    progress = {
        "primary": new_progress_state(),
        "oasisdev": new_progress_state(),
    }
    store = MagicMock()
    manager = TechnicianScoringManager(
        client=MagicMock(),
        store=store,
        progress_by_scope=progress,
        poll_interval_seconds=60,
    )

    issues_by_key = {
        "OIT-300": {"key": "OIT-300", "fields": {"status": {"statusCategory": {"name": "Done"}}}},
        "OIT-400": {"key": "OIT-400", "fields": {"status": {"statusCategory": {"name": "Done"}}}},
    }
    monkeypatch.setattr(
        manager,
        "preview_scope_run",
        lambda scope, *, reset=False, limit=None: {
            "scope": scope,
            "model_id": "qwen3.5:4b",
            "issues_by_key": issues_by_key,
            "keys_to_process": ["OIT-300", "OIT-400"],
            "total_tickets": 2,
        },
    )
    monkeypatch.setattr(manager._client, "get_request_comments", lambda key: [])
    monkeypatch.setattr(
        manager_module,
        "score_closed_ticket",
        lambda issue, request_comments, model_id: TechnicianScore(
            key=issue.get("key", ""),
            communication_score=4,
            communication_notes="Clear",
            documentation_score=4,
            documentation_notes="Documented",
            score_summary="Good closeout.",
            model_used=model_id,
            created_at="2026-03-23T00:00:00+00:00",
        ),
    )

    states = iter(
        [
            {"blocked": False, "message": "", "reason": "", "pending_count": 0, "running": False, "current_key": None, "scope": "primary"},
            {"blocked": False, "message": "", "reason": "", "pending_count": 0, "running": False, "current_key": None, "scope": "primary"},
            {
                "blocked": True,
                "message": "Processing new tickets takes priority over technician QA scoring.",
                "reason": "auto_triage_priority",
                "pending_count": 1,
                "running": True,
                "current_key": "OIT-500",
                "scope": "primary",
            },
        ]
    )
    monkeypatch.setattr(manager, "get_priority_gate", lambda scope: next(states))

    result = await manager.run_scope_once("primary", trigger="manual")

    assert result["started"] is True
    assert store.save_technician_score.call_count == 1
    assert store.save_technician_score.call_args[0][0].key == "OIT-300"
    assert progress["primary"]["processed"] == 1
    assert "Processing new tickets takes priority" in str(progress["primary"]["last_error"])
