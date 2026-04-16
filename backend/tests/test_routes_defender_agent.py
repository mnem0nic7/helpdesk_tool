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
