"""Tests for AI triage routes."""

from __future__ import annotations

from models import TechnicianScore, TriageResult, TriageSuggestion


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
