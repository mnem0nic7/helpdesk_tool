"""Tests for closed-ticket technician scoring routes."""

from __future__ import annotations

from models import TechnicianScore


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
