"""Tests for AI triage routes."""

from __future__ import annotations

from models import AIModel, TechnicianScore, TriageResult, TriageSuggestion


class TestTechnicianScoringRoutes:
    def test_score_run_status_counts_closed_tickets(self, test_client):
        import routes_triage
        from triage_store import store

        store.clear_technician_scores()
        routes_triage._score_progress.update(
            running=False, processed=0, total=0, current_key=None, cancel=False
        )

        resp = test_client.get("/api/triage/score-run-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["remaining_count"] == 2
        assert data["processed_count"] == 0

    def test_score_closed_persists_scores_for_closed_tickets(self, test_client, monkeypatch):
        import routes_triage
        from triage_store import store

        store.clear_technician_scores()
        routes_triage._score_progress.update(
            running=False, processed=0, total=0, current_key=None, cancel=False
        )

        monkeypatch.setattr(
            routes_triage,
            "get_available_models",
            lambda: [AIModel(id="qwen2.5:7b", name="qwen2.5:7b", provider="ollama")],
        )
        monkeypatch.setattr(routes_triage._client, "get_request_comments", lambda key: [])
        monkeypatch.setattr(
            routes_triage,
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


class TestSuggestionApplyRoutes:
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
