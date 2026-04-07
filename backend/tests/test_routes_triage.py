"""Tests for AI triage routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from models import AIModel, TechnicianScore, TriageResult, TriageSuggestion


class TestAutoTriageRoutes:
    def test_run_status_returns_activity_counts_and_health(
        self,
        test_client,
        monkeypatch,
    ):
        import routes_triage
        from triage_store import store

        store.clear_auto_triaged()
        now = datetime.now(timezone.utc).isoformat()
        store.mark_auto_triaged("OIT-100")
        store.record_auto_triage_activity(
            "OIT-100",
            "changed",
            source="auto",
            processed_at=now,
            model="qwen3.5:4b",
            fields_changed=["priority"],
        )
        store.mark_auto_triaged("OIT-200")
        store.record_auto_triage_activity(
            "OIT-200",
            "no_change",
            source="auto",
            processed_at=now,
            model="qwen3.5:4b",
            fields_changed=[],
        )
        store.mark_auto_triaged("OIT-300")
        store.record_auto_triage_activity(
            "OIT-300",
            "backfill",
            source="legacy_backfill",
            processed_at=now,
            fields_changed=[],
            legacy_backfill=True,
        )
        store.record_auto_triage_activity(
            "OIT-400",
            "failed",
            source="auto",
            processed_at=now,
            model="qwen3.5:4b",
            fields_changed=[],
            error="RuntimeError: apply failed",
        )
        monkeypatch.setattr(
            routes_triage.cache,
            "auto_triage_status",
            lambda scope: {
                "running": False,
                "current_key": None,
                "pending_count": 1,
                "pending_keys": ["OIT-400"],
                "last_started": None,
                "last_finished": now,
            },
        )
        monkeypatch.setattr(
            routes_triage,
            "get_available_models",
            lambda: [AIModel(id="qwen3.5:4b", name="qwen3.5:4b", provider="ollama")],
        )

        resp = test_client.get("/api/triage/run-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["processed_count"] == 2
        assert data["ai_processed_count"] == 2
        assert data["changed_count"] == 1
        assert data["no_change_count"] == 1
        assert data["backfilled_count"] == 1
        assert data["failed_count"] == 1
        assert data["remaining_count"] == 1
        assert data["health"] == "healthy"
        assert data["health_message"] == ""

        store.clear_auto_triaged()

    def test_run_all_default_uses_processed_backfill_before_selecting_keys(
        self,
        test_client,
        monkeypatch,
    ):
        import routes_triage
        from triage_store import store

        store.clear_auto_triaged()
        auto_triage = AsyncMock()

        def _backfill() -> None:
            store.mark_auto_triaged("OIT-100")
            store.record_auto_triage_activity(
                "OIT-100",
                "backfill",
                source="legacy_backfill",
                legacy_backfill=True,
            )

        monkeypatch.setattr(routes_triage.cache, "ensure_auto_triage_processed_backfill", _backfill)
        monkeypatch.setattr(
            routes_triage,
            "get_available_models",
            lambda: [AIModel(id="qwen3.5:4b", name="qwen3.5:4b", provider="ollama")],
        )
        monkeypatch.setattr(routes_triage.cache, "_auto_triage_new_tickets", auto_triage)

        resp = test_client.post("/api/triage/run-all", json={})

        assert resp.status_code == 200
        assert resp.json()["started"] is True
        assert resp.json()["total_tickets"] == 3
        auto_triage.assert_awaited_once()
        assert auto_triage.await_args.args[0] == ["OIT-400", "OIT-300", "OIT-200"]

        store.clear_auto_triaged()

    def test_run_all_reprocess_excludes_backfill_activity(
        self,
        test_client,
        monkeypatch,
    ):
        import routes_triage
        from triage_store import store

        store.clear_auto_triaged()
        store.mark_auto_triaged("OIT-100")
        store.record_auto_triage_activity("OIT-100", "changed", source="auto", model="qwen3.5:4b")
        store.mark_auto_triaged("OIT-200")
        store.record_auto_triage_activity("OIT-200", "no_change", source="auto", model="qwen3.5:4b")
        store.mark_auto_triaged("OIT-300")
        store.record_auto_triage_activity(
            "OIT-300",
            "backfill",
            source="legacy_backfill",
            legacy_backfill=True,
        )
        auto_triage = AsyncMock()

        monkeypatch.setattr(
            routes_triage,
            "get_available_models",
            lambda: [AIModel(id="qwen3.5:4b", name="qwen3.5:4b", provider="ollama")],
        )
        monkeypatch.setattr(routes_triage.cache, "_auto_triage_new_tickets", auto_triage)

        resp = test_client.post("/api/triage/run-all", json={"reprocess": True})

        assert resp.status_code == 200
        assert resp.json()["started"] is True
        assert resp.json()["total_tickets"] == 2
        auto_triage.assert_awaited_once()
        assert auto_triage.await_args.args[0] == ["OIT-200", "OIT-100"]

        store.clear_auto_triaged()

    def test_run_status_reports_broken_when_no_models_are_available(
        self,
        test_client,
        monkeypatch,
    ):
        import routes_triage
        from triage_store import store

        store.clear_auto_triaged()
        monkeypatch.setattr(
            routes_triage.cache,
            "auto_triage_status",
            lambda scope: {
                "running": False,
                "current_key": None,
                "pending_count": 4,
                "pending_keys": ["OIT-100", "OIT-200", "OIT-300", "OIT-400"],
                "last_started": None,
                "last_finished": None,
            },
        )
        monkeypatch.setattr(routes_triage, "get_available_models", lambda: [])

        resp = test_client.get("/api/triage/run-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["health"] == "broken"
        assert "no available AI model" in data["health_message"]

    def test_run_status_reports_broken_for_processed_keys_missing_activity(
        self,
        test_client,
        monkeypatch,
    ):
        import routes_triage
        from triage_store import store

        store.clear_auto_triaged()
        store.mark_auto_triaged("OIT-100")
        monkeypatch.setattr(
            routes_triage.cache,
            "auto_triage_status",
            lambda scope: {
                "running": False,
                "current_key": None,
                "pending_count": 3,
                "pending_keys": ["OIT-200", "OIT-300", "OIT-400"],
                "last_started": None,
                "last_finished": None,
            },
        )
        monkeypatch.setattr(
            routes_triage,
            "get_available_models",
            lambda: [AIModel(id="qwen3.5:4b", name="qwen3.5:4b", provider="ollama")],
        )

        resp = test_client.get("/api/triage/run-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["health"] == "broken"
        assert "without matching activity records" in data["health_message"]

    def test_run_status_reports_broken_when_pending_without_recent_success(
        self,
        test_client,
        monkeypatch,
    ):
        import routes_triage
        from triage_store import store

        store.clear_auto_triaged()
        stale_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
        store.mark_auto_triaged("OIT-100")
        store.record_auto_triage_activity(
            "OIT-100",
            "changed",
            source="auto",
            processed_at=stale_timestamp,
            model="qwen3.5:4b",
            fields_changed=["priority"],
        )
        monkeypatch.setattr(
            routes_triage.cache,
            "auto_triage_status",
            lambda scope: {
                "running": False,
                "current_key": None,
                "pending_count": 3,
                "pending_keys": ["OIT-200", "OIT-300", "OIT-400"],
                "last_started": None,
                "last_finished": stale_timestamp,
            },
        )
        monkeypatch.setattr(
            routes_triage,
            "get_available_models",
            lambda: [AIModel(id="qwen3.5:4b", name="qwen3.5:4b", provider="ollama")],
        )

        resp = test_client.get("/api/triage/run-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["health"] == "broken"
        assert "no successful auto-triage activity" in data["health_message"]

    def test_run_all_treats_placeholder_model_string_as_unset(
        self,
        test_client,
        monkeypatch,
    ):
        import routes_triage
        from triage_store import store

        store.clear_auto_triaged()

        auto_triage = AsyncMock()
        monkeypatch.setattr(
            routes_triage,
            "get_available_models",
            lambda: [
                AIModel(id="qwen3.5:4b", name="qwen3.5:4b", provider="ollama"),
                AIModel(id="nemotron-3-nano:4b", name="nemotron-3-nano:4b", provider="ollama"),
            ],
        )
        monkeypatch.setattr(routes_triage.cache, "_auto_triage_new_tickets", auto_triage)

        resp = test_client.post("/api/triage/run-all", json={"model": "None", "limit": 1})

        assert resp.status_code == 200
        assert resp.json()["started"] is True
        assert resp.json()["total_tickets"] == 1
        auto_triage.assert_awaited_once()
        assert auto_triage.await_args.kwargs["model_id"] == "nemotron-3-nano:4b"

        store.clear_auto_triaged()

    def test_run_all_passes_explicit_model_to_background_worker(
        self,
        test_client,
        monkeypatch,
    ):
        import routes_triage
        from triage_store import store

        store.clear_auto_triaged()

        auto_triage = AsyncMock()
        monkeypatch.setattr(
            routes_triage,
            "get_available_models",
            lambda: [
                AIModel(id="qwen3.5:4b", name="qwen3.5:4b", provider="ollama"),
                AIModel(id="nemotron-3-nano:4b", name="nemotron-3-nano:4b", provider="ollama"),
            ],
        )
        monkeypatch.setattr(routes_triage.cache, "_auto_triage_new_tickets", auto_triage)

        resp = test_client.post("/api/triage/run-all", json={"model": "nemotron-3-nano:4b", "limit": 1})

        assert resp.status_code == 200
        assert resp.json()["started"] is True
        auto_triage.assert_awaited_once()
        assert auto_triage.await_args.kwargs["model_id"] == "nemotron-3-nano:4b"

        store.clear_auto_triaged()

    def test_run_all_returns_clear_error_when_no_models_are_available(
        self,
        test_client,
        monkeypatch,
    ):
        import routes_triage

        monkeypatch.setattr(routes_triage, "get_available_models", lambda: [])

        resp = test_client.post("/api/triage/run-all", json={})

        assert resp.status_code == 400
        assert resp.json()["detail"] == "No AI model available. Ensure Ollama is running and the configured local model is pulled."


class TestTechnicianScoringRoutes:
    def test_score_run_status_counts_closed_tickets(self, test_client, monkeypatch):
        import routes_triage
        from triage_store import store

        store.clear_technician_scores()
        routes_triage._score_progress.update(
            running=False, processed=0, total=0, current_key=None, cancel=False
        )
        monkeypatch.setattr(
            routes_triage.technician_scoring_manager,
            "get_priority_gate",
            lambda scope: {
                "blocked": True,
                "message": "Processing new tickets takes priority.",
                "reason": "auto_triage_priority",
                "pending_count": 2,
                "running": True,
                "current_key": "OIT-1",
                "scope": scope,
            },
        )

        resp = test_client.get("/api/triage/score-run-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["remaining_count"] == 2
        assert data["processed_count"] == 0
        assert data["priority_blocked"] is True
        assert data["priority_pending_count"] == 2

    def test_score_closed_persists_scores_for_closed_tickets(self, test_client, monkeypatch):
        import routes_triage
        import technician_scoring_manager as scoring_manager_module
        from triage_store import store

        store.clear_technician_scores()
        routes_triage._score_progress.update(
            running=False, processed=0, total=0, current_key=None, cancel=False
        )

        monkeypatch.setattr(
            scoring_manager_module,
            "get_available_models",
            lambda: [AIModel(id="qwen3.5:4b", name="qwen3.5:4b", provider="ollama")],
        )
        monkeypatch.setattr(routes_triage._client, "get_request_comments", lambda key: [])
        monkeypatch.setattr(
            scoring_manager_module,
            "score_closed_ticket",
            lambda issue, request_comments, model_id: TechnicianScore(
                key=issue.get("key", ""),
                communication_score=4,
                communication_notes="Clear reply to the user.",
                documentation_score=3,
                documentation_notes="Basic resolution notes.",
                score_summary="Solid communication with average documentation.",
                model_used=model_id,
                created_at="2026-03-04T12:00:00+00:00",
            ),
        )

        resp = test_client.post("/api/triage/score-closed")
        assert resp.status_code == 200
        assert resp.json()["started"] is True
        assert resp.json()["total_tickets"] == 2

        scores_resp = test_client.get("/api/triage/technician-scores")
        assert scores_resp.status_code == 200
        scores = scores_resp.json()
        assert len(scores) == 2
        assert all(score["overall_score"] == 3.5 for score in scores)
        assert {score["key"] for score in scores} == {"OIT-300", "OIT-400"}

    def test_triage_log_supports_server_side_search(self, test_client, monkeypatch):
        import routes_triage

        monkeypatch.setattr(
            routes_triage.store,
            "get_triage_log",
            lambda limit=500, search="": [
                {
                    "key": "OIT-300",
                    "field": "status",
                    "old_value": "Open",
                    "new_value": "Waiting on printer vendor",
                    "confidence": 0.9,
                    "model": "gpt-test",
                    "source": "auto",
                    "approved_by": None,
                    "timestamp": "2026-03-04T12:00:00+00:00",
                }
            ]
            if search == "printer"
            else [],
        )

        resp = test_client.get("/api/triage/log?search=printer")

        assert resp.status_code == 200
        assert resp.json() == [
            {
                "key": "OIT-300",
                "field": "status",
                "old_value": "Open",
                "new_value": "Waiting on printer vendor",
                "confidence": 0.9,
                "model": "gpt-test",
                "source": "auto",
                "approved_by": None,
                "timestamp": "2026-03-04T12:00:00+00:00",
            }
        ]

    def test_technician_scores_support_server_side_search(self, test_client, monkeypatch):
        import routes_triage

        monkeypatch.setattr(
            routes_triage.store,
            "list_technician_scores",
            lambda limit=500: [
                TechnicianScore(
                    key="OIT-300",
                    communication_score=4,
                    communication_notes="Clear printer update.",
                    documentation_score=3,
                    documentation_notes="Documented the printer vendor callback.",
                    score_summary="Printer ticket was handled clearly.",
                    model_used="gpt-test",
                    created_at="2026-03-04T12:00:00+00:00",
                ),
                TechnicianScore(
                    key="OIT-400",
                    communication_score=2,
                    communication_notes="Sparse VPN notes.",
                    documentation_score=2,
                    documentation_notes="VPN reset details missing.",
                    score_summary="VPN documentation needs work.",
                    model_used="gpt-test",
                    created_at="2026-03-04T12:30:00+00:00",
                ),
            ],
        )

        resp = test_client.get("/api/triage/technician-scores?search=printer")

        assert resp.status_code == 200
        assert [item["key"] for item in resp.json()] == ["OIT-300"]

    def test_technician_scores_support_exact_ticket_lookup(self, test_client, monkeypatch):
        import routes_triage

        monkeypatch.setattr(
            routes_triage.store,
            "get_technician_score",
            lambda key: TechnicianScore(
                key=key,
                communication_score=5,
                communication_notes="Excellent follow-up.",
                documentation_score=4,
                documentation_notes="Clear resolution notes.",
                score_summary="Strong closeout quality.",
                model_used="qwen3.5:4b",
                created_at="2026-03-04T12:00:00+00:00",
            )
            if key == "OIT-300"
            else None,
        )

        resp = test_client.get("/api/triage/technician-scores?key=OIT-300")

        assert resp.status_code == 200
        payload = resp.json()
        assert len(payload) == 1
        assert payload[0]["key"] == "OIT-300"
        assert payload[0]["overall_score"] == 4.5


class TestSuggestionApplyRoutes:
    def test_apply_single_field_normalizes_new_priority_to_low(self, test_client, mock_cache, monkeypatch):
        import routes_triage
        from triage_store import store

        key = "OIT-100"
        store.delete(key)
        store.save(
            TriageResult(
                key=key,
                suggestions=[
                    TriageSuggestion(
                        field="priority",
                        current_value="New",
                        suggested_value="New",
                        reasoning="Leave as-is.",
                        confidence=0.83,
                    )
                ],
                model_used="gpt-test",
                created_at="2026-03-17T20:00:00+00:00",
            )
        )

        applied: list[tuple[str, str]] = []
        monkeypatch.setattr(routes_triage._client, "update_priority", lambda issue_key, value: applied.append((issue_key, value)))

        resp = test_client.post("/api/triage/apply-field", json={"key": key, "field": "priority"})

        assert resp.status_code == 200
        assert resp.json()["applied"] is True
        assert applied == [(key, "Low")]
        mock_cache.update_cached_field.assert_called_with(key, "priority", "Low")
        store.delete(key)

    def test_apply_single_field_updates_reporter_with_account_id(self, test_client, mock_cache, monkeypatch):
        import routes_triage
        from triage_store import store

        key = "OIT-100"
        store.delete(key)
        store.save(
            TriageResult(
                key=key,
                suggestions=[
                    TriageSuggestion(
                        field="reporter",
                        current_value="OSIJIRAOCC",
                        suggested_value="Raza Abidi",
                        reasoning='Ticket description explicitly says "Ticket Created By: Raza Abidi".',
                        confidence=0.99,
                    )
                ],
                model_used="gpt-test",
                created_at="2026-03-17T20:00:00+00:00",
            )
        )

        applied: list[tuple[str, str]] = []
        monkeypatch.setattr(routes_triage._client, "find_user_account_id", lambda name: "acct-reporter-1")
        monkeypatch.setattr(
            routes_triage._client,
            "update_reporter",
            lambda issue_key, account_id: applied.append((issue_key, account_id)),
        )

        resp = test_client.post("/api/triage/apply-field", json={"key": key, "field": "reporter"})

        assert resp.status_code == 200
        assert resp.json()["applied"] is True
        assert applied == [(key, "acct-reporter-1")]
        mock_cache.update_cached_field.assert_called_with(
            key,
            "reporter",
            {"displayName": "Raza Abidi", "accountId": "acct-reporter-1"},
        )
        store.delete(key)
