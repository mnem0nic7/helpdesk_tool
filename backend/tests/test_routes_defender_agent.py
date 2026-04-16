"""Tests for routes_defender_agent — config, decisions, cancel/approve, summary."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from defender_agent_store import DefenderAgentStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path):
    return DefenderAgentStore(db_path=str(tmp_path / "defender.db"))


@pytest.fixture()
def defender_client(test_client, store, monkeypatch):
    """test_client with the defender_agent_store singleton replaced by a real store."""
    import routes_defender_agent
    monkeypatch.setattr(routes_defender_agent, "defender_agent_store", store)
    return test_client


AZURE_HOST = {"host": "azure.movedocs.com"}


# ---------------------------------------------------------------------------
# Site-scope guard
# ---------------------------------------------------------------------------

def test_get_config_returns_404_on_primary_host(defender_client):
    resp = defender_client.get("/api/azure/security/defender-agent/config")
    assert resp.status_code == 404


def test_get_config_200_on_azure_host(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/config", headers=AZURE_HOST
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "enabled" in body
    assert "min_severity" in body


# ---------------------------------------------------------------------------
# Config update
# ---------------------------------------------------------------------------

def test_update_config_persists(defender_client, store):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/config",
        headers=AZURE_HOST,
        json={"enabled": False, "min_severity": "critical"},
    )
    assert resp.status_code == 200
    cfg = store.get_config()
    assert cfg["enabled"] is False
    assert cfg["min_severity"] == "critical"


# ---------------------------------------------------------------------------
# List / get decisions
# ---------------------------------------------------------------------------

def test_list_decisions_empty(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/decisions", headers=AZURE_HOST
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decisions"] == []
    assert body["total"] == 0


def test_list_decisions_returns_created_decisions(defender_client, store):
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-1",
        run_id="run-1",
        alert_id="ext-1",
        alert_title="Suspicious Sign-In",
        alert_severity="high",
        alert_category="SuspiciousActivity",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="microsoftDefenderForIdentity",
        tier=1,
        decision="execute",
        action_type="revoke_sessions",
        action_types=["revoke_sessions"],
        job_ids=[],
        reason="Auto-revoke",
        entities=[],
    )
    resp = defender_client.get(
        "/api/azure/security/defender-agent/decisions", headers=AZURE_HOST
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["decisions"][0]["decision_id"] == "dec-1"


def test_get_decision_not_found(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/decisions/missing-id", headers=AZURE_HOST
    )
    assert resp.status_code == 404


def test_get_decision_found(defender_client, store):
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-1",
        run_id="run-1",
        alert_id="ext-1",
        alert_title="Suspicious Sign-In",
        alert_severity="high",
        alert_category="SuspiciousActivity",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="microsoftDefenderForIdentity",
        tier=1,
        decision="execute",
        action_type="revoke_sessions",
        action_types=["revoke_sessions"],
        job_ids=[],
        reason="Auto-revoke",
        entities=[],
    )
    resp = defender_client.get(
        "/api/azure/security/defender-agent/decisions/dec-1", headers=AZURE_HOST
    )
    assert resp.status_code == 200
    assert resp.json()["decision_id"] == "dec-1"


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def test_cancel_decision_not_found(defender_client):
    resp = defender_client.post(
        "/api/azure/security/defender-agent/decisions/missing/cancel",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 404


def test_cancel_decision_success(defender_client, store):
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-t2",
        run_id="run-1",
        alert_id="ext-2",
        alert_title="Password Spray",
        alert_severity="high",
        alert_category="CredentialAccess",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="microsoftDefenderForIdentity",
        tier=2,
        decision="queue",
        action_type="disable_sign_in",
        action_types=["disable_sign_in"],
        job_ids=[],
        reason="Queued by agent",
        entities=[],
    )
    resp = defender_client.post(
        "/api/azure/security/defender-agent/decisions/dec-t2/cancel",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True


def test_cancel_already_cancelled_returns_400(defender_client, store):
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-t2",
        run_id="run-1",
        alert_id="ext-3",
        alert_title="MFA Fatigue",
        alert_severity="medium",
        alert_category="CredentialAccess",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="microsoftDefenderForIdentity",
        tier=2,
        decision="queue",
        action_type="disable_sign_in",
        action_types=["disable_sign_in"],
        job_ids=[],
        reason="Queued by agent",
        entities=[],
    )
    store.cancel_decision("dec-t2")
    resp = defender_client.post(
        "/api/azure/security/defender-agent/decisions/dec-t2/cancel",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Approve (T3)
# ---------------------------------------------------------------------------

def test_approve_decision_not_found(defender_client):
    resp = defender_client.post(
        "/api/azure/security/defender-agent/decisions/missing/approve",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 404


def test_approve_non_recommend_decision_returns_400(defender_client, store):
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-t1",
        run_id="run-1",
        alert_id="ext-4",
        alert_title="Suspicious Sign-In",
        alert_severity="high",
        alert_category="SuspiciousActivity",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="microsoftDefenderForIdentity",
        tier=1,
        decision="execute",
        action_type="revoke_sessions",
        action_types=["revoke_sessions"],
        job_ids=[],
        reason="Auto",
        entities=[],
    )
    resp = defender_client.post(
        "/api/azure/security/defender-agent/decisions/dec-t1/approve",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_get_summary_on_azure_host(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/summary", headers=AZURE_HOST
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "enabled" in body
    assert "pending_approvals" in body
    assert "pending_tier2" in body
    assert "recent_decisions" in body


def test_get_summary_404_on_primary_host(defender_client):
    resp = defender_client.get("/api/azure/security/defender-agent/summary")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def test_list_runs_empty(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/runs", headers=AZURE_HOST
    )
    assert resp.status_code == 200
    assert resp.json() == []  # route returns a plain list


def test_list_runs_returns_completed_run(defender_client, store):
    store.create_run("run-1")
    store.complete_run("run-1", alerts_fetched=3, alerts_new=2, decisions_made=2, actions_queued=1)
    resp = defender_client.get(
        "/api/azure/security/defender-agent/runs", headers=AZURE_HOST
    )
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run-1"
    assert runs[0]["alerts_fetched"] == 3


# ---------------------------------------------------------------------------
# Suppressions
# ---------------------------------------------------------------------------

def test_list_suppressions_empty(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/suppressions", headers=AZURE_HOST
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["suppressions"] == []
    assert body["total"] == 0


def test_create_suppression_admin_only(defender_client):
    """Non-admin session should return 403."""
    resp = defender_client.post(
        "/api/azure/security/defender-agent/suppressions",
        headers=AZURE_HOST,
        json={"suppression_type": "entity_user", "value": "user@example.com", "reason": "test"},
    )
    # test_client fixture uses admin session, so expect 200 here
    assert resp.status_code == 200
    body = resp.json()
    assert body["suppression_type"] == "entity_user"
    assert body["value"] == "user@example.com"
    assert body["active"] is True


def test_create_suppression_persists_in_list(defender_client):
    defender_client.post(
        "/api/azure/security/defender-agent/suppressions",
        headers=AZURE_HOST,
        json={"suppression_type": "alert_title", "value": "password spray"},
    )
    resp = defender_client.get(
        "/api/azure/security/defender-agent/suppressions", headers=AZURE_HOST
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["suppressions"][0]["value"] == "password spray"


def test_delete_suppression_deactivates(defender_client, store):
    row = store.create_suppression(suppression_type="entity_device", value="DEVICE-001")
    resp = defender_client.delete(
        f"/api/azure/security/defender-agent/suppressions/{row['id']}",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False
    # Should no longer appear in active list
    list_resp = defender_client.get(
        "/api/azure/security/defender-agent/suppressions", headers=AZURE_HOST
    )
    assert list_resp.json()["total"] == 0


def test_delete_suppression_not_found(defender_client):
    resp = defender_client.delete(
        "/api/azure/security/defender-agent/suppressions/nonexistent",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 404


def test_suppressions_404_on_primary_host(defender_client):
    resp = defender_client.get("/api/azure/security/defender-agent/suppressions")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Phase 7 — entity_cooldown_hours config route
# ---------------------------------------------------------------------------

def test_get_config_includes_entity_cooldown_hours(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/config", headers=AZURE_HOST
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "entity_cooldown_hours" in body
    assert isinstance(body["entity_cooldown_hours"], int)


def test_update_config_entity_cooldown_hours(defender_client):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/config",
        json={"enabled": True, "entity_cooldown_hours": 48},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["entity_cooldown_hours"] == 48


def test_update_config_entity_cooldown_hours_zero(defender_client):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/config",
        json={"enabled": True, "entity_cooldown_hours": 0},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["entity_cooldown_hours"] == 0


def test_update_config_entity_cooldown_hours_max(defender_client):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/config",
        json={"enabled": True, "entity_cooldown_hours": 168},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["entity_cooldown_hours"] == 168


# ---------------------------------------------------------------------------
# Phase 8 — alert_dedup_window_minutes config route
# ---------------------------------------------------------------------------

def test_get_config_includes_alert_dedup_window_minutes(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/config", headers=AZURE_HOST
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "alert_dedup_window_minutes" in body
    assert isinstance(body["alert_dedup_window_minutes"], int)


def test_update_config_alert_dedup_window_minutes(defender_client):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/config",
        json={"enabled": True, "alert_dedup_window_minutes": 60},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["alert_dedup_window_minutes"] == 60


def test_update_config_alert_dedup_window_zero(defender_client):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/config",
        json={"enabled": True, "alert_dedup_window_minutes": 0},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["alert_dedup_window_minutes"] == 0


# ---------------------------------------------------------------------------
# Phase 9 — remediation fields in decision response
# ---------------------------------------------------------------------------

def test_decision_includes_remediation_fields(defender_client, store):
    row = store.create_decision(
        decision_id="dec-rem-route",
        run_id="run-r",
        alert_id="alert-r",
        alert_title="Test",
        alert_severity="high",
        alert_category="Malware",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="mde",
        tier=1,
        decision="execute",
        action_type="revoke_sessions",
        action_types=["revoke_sessions"],
        job_ids=[],
        reason="test",
        entities=[],
    )
    resp = defender_client.get(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "remediation_confirmed" in body
    assert "remediation_failed" in body
    assert body["remediation_confirmed"] is False
    assert body["remediation_failed"] is False


# ---------------------------------------------------------------------------
# Phase 10 — Confidence score route tests
# ---------------------------------------------------------------------------

def test_update_config_min_confidence(defender_client, store):
    defaults = store.get_config()
    resp = defender_client.put(
        "/api/azure/security/defender-agent/config",
        json={
            "enabled": defaults["enabled"],
            "min_severity": defaults["min_severity"],
            "tier2_delay_minutes": defaults["tier2_delay_minutes"],
            "dry_run": defaults["dry_run"],
            "entity_cooldown_hours": defaults["entity_cooldown_hours"],
            "alert_dedup_window_minutes": defaults["alert_dedup_window_minutes"],
            "min_confidence": 70,
        },
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["min_confidence"] == 70


def test_get_config_includes_min_confidence(defender_client, store):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/config",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert "min_confidence" in resp.json()


def test_decision_includes_confidence_score(defender_client, store):
    row = store.create_decision(
        decision_id="dec-confroute",
        run_id="run-cr",
        alert_id="alert-cr",
        alert_title="Test Confidence",
        alert_severity="high",
        alert_category="Malware",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="mde",
        tier=1,
        decision="execute",
        action_type="revoke_sessions",
        action_types=["revoke_sessions"],
        job_ids=[],
        reason="test",
        entities=[],
        confidence_score=85,
    )
    resp = defender_client.get(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "confidence_score" in body
    assert body["confidence_score"] == 85


# ---------------------------------------------------------------------------
# Phase 12 — Analyst disposition route tests
# ---------------------------------------------------------------------------

def _make_route_decision(store, decision_id: str, decision: str = "execute") -> dict:
    store.create_run("run-route")
    return store.create_decision(
        decision_id=decision_id,
        run_id="run-route",
        alert_id=f"alert-{decision_id}",
        alert_title="Test Alert",
        alert_severity="high",
        alert_category="Malware",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="mde",
        tier=1,
        decision=decision,
        action_type="revoke_sessions",
        action_types=["revoke_sessions"],
        job_ids=[],
        reason="test",
        entities=[],
    )


def test_set_disposition_true_positive(defender_client, store):
    row = _make_route_decision(store, "dec-disp-tp", "execute")
    resp = defender_client.post(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}/disposition",
        json={"disposition": "true_positive", "note": "Confirmed malware"},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["disposition"] == "true_positive"
    assert body["disposition_note"] == "Confirmed malware"


def test_set_disposition_false_positive(defender_client, store):
    row = _make_route_decision(store, "dec-disp-fp", "queue")
    resp = defender_client.post(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}/disposition",
        json={"disposition": "false_positive"},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["disposition"] == "false_positive"


def test_set_disposition_invalid_422(defender_client, store):
    row = _make_route_decision(store, "dec-disp-invalid", "execute")
    resp = defender_client.post(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}/disposition",
        json={"disposition": "banana"},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 422


def test_set_disposition_not_found_404(defender_client):
    resp = defender_client.post(
        "/api/azure/security/defender-agent/decisions/nonexistent/disposition",
        json={"disposition": "true_positive"},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 404


def test_get_disposition_stats(defender_client, store):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/disposition-stats",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "total_actioned" in body
    assert "false_positive_rate" in body
    assert "by_tier" in body


def test_decision_includes_disposition_fields(defender_client, store):
    row = _make_route_decision(store, "dec-disp-fields", "execute")
    resp = defender_client.get(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "disposition" in body
    assert body["disposition"] is None
    assert "disposition_note" in body
    assert "disposition_at" in body


# ---------------------------------------------------------------------------
# Phase 13: Entity timeline route
# ---------------------------------------------------------------------------

def test_entity_timeline_empty(defender_client, store):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/entities/nobody%40example.com/timeline",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["entity_id"] == "nobody@example.com"
    assert body["decisions"] == []
    assert body["total"] == 0


def test_entity_timeline_returns_matching_decisions(defender_client, store):
    store.create_run("run-1")
    store.create_decision(
        decision_id="dec-tl-1",
        run_id="run-1",
        alert_id="a-tl-1",
        alert_title="TL Test",
        alert_severity="high",
        alert_category="Suspicious",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="mde",
        tier=1,
        decision="execute",
        action_type="revoke_sessions",
        action_types=["revoke_sessions"],
        job_ids=[],
        reason="r",
        entities=[{"type": "user", "id": "tl-user-1", "name": "tl@example.com"}],
        not_before_at=None,
    )
    resp = defender_client.get(
        "/api/azure/security/defender-agent/entities/tl-user-1/timeline",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["entity_id"] == "tl-user-1"
    assert body["total"] == 1
    assert body["decisions"][0]["decision_id"] == "dec-tl-1"


def test_entity_timeline_limit_param(defender_client, store):
    store.create_run("run-1")
    for i in range(5):
        store.create_decision(
            decision_id=f"dec-tl-lim-{i}",
            run_id="run-1",
            alert_id=f"a-tl-lim-{i}",
            alert_title=f"TL Limit {i}",
            alert_severity="medium",
            alert_category="Suspicious",
            alert_created_at="2026-04-16T00:00:00Z",
            service_source="mde",
            tier=1,
            decision="execute",
            action_type="revoke_sessions",
            action_types=["revoke_sessions"],
            job_ids=[],
            reason="r",
            entities=[{"type": "user", "id": "lim-tl-user", "name": "lim-tl@example.com"}],
            not_before_at=None,
        )
    resp = defender_client.get(
        "/api/azure/security/defender-agent/entities/lim-tl-user/timeline?limit=3",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["decisions"]) == 3


# ---------------------------------------------------------------------------
# Phase 14: Agent metrics route
# ---------------------------------------------------------------------------

def test_get_agent_metrics_200(defender_client, store):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/metrics",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "total_decisions" in body
    assert "by_tier" in body
    assert "daily_volumes" in body
    assert "top_entities" in body
    assert "disposition_summary" in body
    assert "false_positive_rate" in body


def test_get_agent_metrics_days_param(defender_client, store):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/metrics?days=7",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["period_days"] == 7


def test_get_agent_metrics_invalid_days(defender_client, store):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/metrics?days=0",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Phase 15: Investigation notes route
# ---------------------------------------------------------------------------

def test_add_note_success(defender_client, store):
    store.create_run("run-1")
    row = _make_route_decision(store, "dec-note-1", "execute")
    resp = defender_client.post(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}/notes",
        json={"text": "Investigating lateral movement pattern"},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["investigation_notes"]) == 1
    assert body["investigation_notes"][0]["text"] == "Investigating lateral movement pattern"


def test_add_note_multiple_appends(defender_client, store):
    store.create_run("run-1")
    row = _make_route_decision(store, "dec-note-2", "execute")
    for note in ("Note 1", "Note 2", "Note 3"):
        defender_client.post(
            f"/api/azure/security/defender-agent/decisions/{row['decision_id']}/notes",
            json={"text": note},
            headers=AZURE_HOST,
        )
    resp = defender_client.get(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert len(resp.json()["investigation_notes"]) == 3


def test_add_note_empty_text_422(defender_client, store):
    store.create_run("run-1")
    row = _make_route_decision(store, "dec-note-empty", "execute")
    resp = defender_client.post(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}/notes",
        json={"text": ""},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 422


def test_add_note_not_found_404(defender_client, store):
    resp = defender_client.post(
        "/api/azure/security/defender-agent/decisions/nonexistent/notes",
        json={"text": "hello"},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 404


def test_decision_includes_investigation_notes_field(defender_client, store):
    store.create_run("run-1")
    row = _make_route_decision(store, "dec-note-field", "execute")
    resp = defender_client.get(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "investigation_notes" in body
    assert body["investigation_notes"] == []


# ---------------------------------------------------------------------------
# Phase 16: Watchlist routes
# ---------------------------------------------------------------------------

def test_get_watchlist_empty(defender_client, store):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/watchlist",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["entries"] == []
    assert body["total"] == 0


def test_add_watchlist_entry_admin(defender_client, store):
    resp = defender_client.post(
        "/api/azure/security/defender-agent/watchlist",
        json={"entity_type": "user", "entity_id": "vip@example.com", "reason": "VIP", "boost_tier": True},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["entity_id"] == "vip@example.com"
    assert body["boost_tier"] is True


def test_get_watchlist_returns_entry(defender_client, store):
    defender_client.post(
        "/api/azure/security/defender-agent/watchlist",
        json={"entity_type": "device", "entity_id": "LAPTOP-001"},
        headers=AZURE_HOST,
    )
    resp = defender_client.get(
        "/api/azure/security/defender-agent/watchlist",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_remove_watchlist_entry(defender_client, store):
    add_resp = defender_client.post(
        "/api/azure/security/defender-agent/watchlist",
        json={"entity_type": "user", "entity_id": "del@example.com"},
        headers=AZURE_HOST,
    )
    entry_id = add_resp.json()["id"]
    del_resp = defender_client.delete(
        f"/api/azure/security/defender-agent/watchlist/{entry_id}",
        headers=AZURE_HOST,
    )
    assert del_resp.status_code == 200
    # Should be gone
    list_resp = defender_client.get(
        "/api/azure/security/defender-agent/watchlist",
        headers=AZURE_HOST,
    )
    assert list_resp.json()["total"] == 0


def test_remove_watchlist_not_found_404(defender_client, store):
    resp = defender_client.delete(
        "/api/azure/security/defender-agent/watchlist/nonexistent",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 404


def test_watchlist_invalid_entity_type_422(defender_client, store):
    resp = defender_client.post(
        "/api/azure/security/defender-agent/watchlist",
        json={"entity_type": "ip", "entity_id": "1.2.3.4"},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Phase 17: Built-in rule management routes
# ---------------------------------------------------------------------------

def test_list_rules_returns_all_rules(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/rules",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) > 0
    rule = body[0]
    assert "rule_id" in rule
    assert "tier" in rule
    assert "decision" in rule
    assert "disabled" in rule


def test_list_rules_have_stable_ids(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/rules",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    ids = [r["rule_id"] for r in resp.json()]
    assert "rule_00" in ids


def test_update_rule_disable(defender_client, store):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/rules/rule_00",
        json={"disabled": True},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["disabled"] is True
    assert body["rule_id"] == "rule_00"


def test_update_rule_override_confidence(defender_client, store):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/rules/rule_00",
        json={"disabled": False, "confidence_score": 99},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["override_confidence"] == 99


def test_update_rule_not_found_404(defender_client):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/rules/does_not_exist",
        json={"disabled": True},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 404


def test_overrides_persist_in_list_rules(defender_client, store):
    defender_client.put(
        "/api/azure/security/defender-agent/rules/rule_01",
        json={"disabled": True},
        headers=AZURE_HOST,
    )
    resp = defender_client.get(
        "/api/azure/security/defender-agent/rules",
        headers=AZURE_HOST,
    )
    rule_01 = next(r for r in resp.json() if r["rule_id"] == "rule_01")
    assert rule_01["disabled"] is True


# ---------------------------------------------------------------------------
# Phase 18: Custom detection rules routes
# ---------------------------------------------------------------------------

def test_list_custom_rules_empty(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/custom-rules",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_custom_rule(defender_client):
    resp = defender_client.post(
        "/api/azure/security/defender-agent/custom-rules",
        json={
            "name": "Catch phishing keywords",
            "match_field": "title",
            "match_value": "phishing",
            "match_mode": "contains",
            "tier": 2,
            "action_type": "revoke_sessions",
            "confidence_score": 75,
        },
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["match_value"] == "phishing"
    assert body["tier"] == 2
    assert body["enabled"] is True


def test_list_custom_rules_after_create(defender_client):
    defender_client.post(
        "/api/azure/security/defender-agent/custom-rules",
        json={"match_value": "ransomware", "tier": 1, "action_type": "revoke_sessions"},
        headers=AZURE_HOST,
    )
    resp = defender_client.get(
        "/api/azure/security/defender-agent/custom-rules",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    rules = resp.json()
    assert any(r["match_value"] == "ransomware" for r in rules)


def test_delete_custom_rule(defender_client):
    create_resp = defender_client.post(
        "/api/azure/security/defender-agent/custom-rules",
        json={"match_value": "todelete", "tier": 3, "action_type": "start_investigation"},
        headers=AZURE_HOST,
    )
    rid = create_resp.json()["id"]
    del_resp = defender_client.delete(
        f"/api/azure/security/defender-agent/custom-rules/{rid}",
        headers=AZURE_HOST,
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True
    list_resp = defender_client.get(
        "/api/azure/security/defender-agent/custom-rules",
        headers=AZURE_HOST,
    )
    assert not any(r["id"] == rid for r in list_resp.json())


def test_delete_custom_rule_not_found(defender_client):
    resp = defender_client.delete(
        "/api/azure/security/defender-agent/custom-rules/nonexistent",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 404


def test_toggle_custom_rule_disable(defender_client):
    cr = defender_client.post(
        "/api/azure/security/defender-agent/custom-rules",
        json={"match_value": "toggle-me", "tier": 3, "action_type": "start_investigation"},
        headers=AZURE_HOST,
    ).json()
    resp = defender_client.put(
        f"/api/azure/security/defender-agent/custom-rules/{cr['id']}/toggle?enabled=false",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_enabled_only_filter(defender_client):
    cr = defender_client.post(
        "/api/azure/security/defender-agent/custom-rules",
        json={"match_value": "disabled-rule", "tier": 3, "action_type": "start_investigation"},
        headers=AZURE_HOST,
    ).json()
    defender_client.put(
        f"/api/azure/security/defender-agent/custom-rules/{cr['id']}/toggle?enabled=false",
        headers=AZURE_HOST,
    )
    resp = defender_client.get(
        "/api/azure/security/defender-agent/custom-rules?enabled_only=true",
        headers=AZURE_HOST,
    )
    ids = [r["id"] for r in resp.json()]
    assert cr["id"] not in ids


# ---------------------------------------------------------------------------
# Phase 19: Alert tagging routes
# ---------------------------------------------------------------------------

def test_list_known_tags_empty(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/tags",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["tags"] == []


def test_add_tag_to_decision(defender_client, store):
    store.create_run("run-1")
    row = _make_route_decision(store, "dec-tag-1", "execute")
    resp = defender_client.post(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}/tags/malware",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "malware" in body["tags"]


def test_add_tag_idempotent(defender_client, store):
    store.create_run("run-1")
    row = _make_route_decision(store, "dec-tag-idem", "execute")
    for _ in range(3):
        defender_client.post(
            f"/api/azure/security/defender-agent/decisions/{row['decision_id']}/tags/phishing",
            headers=AZURE_HOST,
        )
    resp = defender_client.get(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}",
        headers=AZURE_HOST,
    )
    assert resp.json()["tags"].count("phishing") == 1


def test_remove_tag_from_decision(defender_client, store):
    store.create_run("run-1")
    row = _make_route_decision(store, "dec-tag-rm", "execute")
    defender_client.post(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}/tags/fp",
        headers=AZURE_HOST,
    )
    resp = defender_client.delete(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}/tags/fp",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert "fp" not in resp.json()["tags"]


def test_list_known_tags_after_tag(defender_client, store):
    store.create_run("run-1")
    row = _make_route_decision(store, "dec-tag-known", "execute")
    defender_client.post(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}/tags/critical-asset",
        headers=AZURE_HOST,
    )
    resp = defender_client.get(
        "/api/azure/security/defender-agent/tags",
        headers=AZURE_HOST,
    )
    assert "critical-asset" in resp.json()["tags"]


def test_add_tag_not_found_404(defender_client):
    resp = defender_client.post(
        "/api/azure/security/defender-agent/decisions/nonexistent/tags/foo",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 404


def test_decision_includes_tags_field(defender_client, store):
    store.create_run("run-1")
    row = _make_route_decision(store, "dec-tags-field", "execute")
    resp = defender_client.get(
        f"/api/azure/security/defender-agent/decisions/{row['decision_id']}",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert "tags" in resp.json()
    assert resp.json()["tags"] == []


# ---------------------------------------------------------------------------
# Phase 20: Configurable poll interval
# ---------------------------------------------------------------------------

def test_config_includes_poll_interval_seconds(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/config",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert "poll_interval_seconds" in resp.json()


def test_update_config_poll_interval(defender_client):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/config",
        json={"enabled": True, "poll_interval_seconds": 300},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["poll_interval_seconds"] == 300


def test_update_config_poll_interval_zero_allowed(defender_client):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/config",
        json={"enabled": True, "poll_interval_seconds": 0},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["poll_interval_seconds"] == 0


# ---------------------------------------------------------------------------
# Phase 21: Decision CSV export
# ---------------------------------------------------------------------------

def test_export_decisions_empty_csv(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/decisions/export",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    # Only header row
    lines = resp.text.strip().splitlines()
    assert len(lines) == 1
    assert "decision_id" in lines[0]


def test_export_decisions_contains_rows(defender_client, store):
    store.create_run("run-export")
    store.create_decision(
        decision_id="dec-export-1",
        run_id="run-export",
        alert_id="alert-export-1",
        alert_title="Export Test",
        alert_severity="high",
        alert_category="Malware",
        alert_created_at="2026-04-16T00:00:00Z",
        service_source="mde",
        tier=1,
        decision="execute",
        action_type="revoke_sessions",
        action_types=["revoke_sessions"],
        job_ids=[],
        reason="export test",
        entities=[],
    )
    resp = defender_client.get(
        "/api/azure/security/defender-agent/decisions/export?days=365",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    lines = resp.text.strip().splitlines()
    assert len(lines) == 2
    assert "Export Test" in lines[1]


def test_export_decisions_content_disposition(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/decisions/export?days=7",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert "defender-decisions-7d.csv" in resp.headers.get("content-disposition", "")


# ---------------------------------------------------------------------------
# Phase 22: Notification routing (per-tier webhook config)
# ---------------------------------------------------------------------------

def test_config_includes_tier_webhooks(defender_client):
    resp = defender_client.get(
        "/api/azure/security/defender-agent/config",
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "teams_tier1_webhook" in body
    assert "teams_tier2_webhook" in body
    assert "teams_tier3_webhook" in body


def test_update_config_tier_webhooks(defender_client):
    resp = defender_client.put(
        "/api/azure/security/defender-agent/config",
        json={
            "enabled": True,
            "teams_tier1_webhook": "https://example.com/hook1",
            "teams_tier2_webhook": "https://example.com/hook2",
            "teams_tier3_webhook": "https://example.com/hook3",
        },
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["teams_tier1_webhook"] == "https://example.com/hook1"
    assert body["teams_tier2_webhook"] == "https://example.com/hook2"
    assert body["teams_tier3_webhook"] == "https://example.com/hook3"


def test_update_config_clear_tier_webhooks(defender_client):
    # Set then clear
    defender_client.put(
        "/api/azure/security/defender-agent/config",
        json={"enabled": True, "teams_tier1_webhook": "https://example.com/hook1"},
        headers=AZURE_HOST,
    )
    resp = defender_client.put(
        "/api/azure/security/defender-agent/config",
        json={"enabled": True, "teams_tier1_webhook": ""},
        headers=AZURE_HOST,
    )
    assert resp.status_code == 200
    assert resp.json()["teams_tier1_webhook"] == ""
