# backend/tests/test_routes_retention.py
from __future__ import annotations

import tempfile

import pytest


@pytest.fixture(autouse=True)
def _fresh_retention_policy_store(monkeypatch):
    """retention_policy_store is a real module-level singleton also used by
    production code in routes_retention.py, and its _conn() falls back to
    the real shared Postgres database whenever DATABASE_URL is set (as it is
    in the backend container) rather than always using a private SQLite
    file. Swap in a fresh instance backed by its own temp SQLite file for
    each test instead of mutating the real singleton's data — the same
    pattern used by test_retention_policy_store.py / test_retention_cleanup_job.py
    (constructing RetentionPolicyStore(db_path=...)) and by
    test_routes_quarantine_release.py (monkeypatching the route module's
    singleton reference to a fresh instance). This also keeps state isolated
    between the test functions below that intentionally reuse the same
    team_id/channel_id, which would otherwise collide on the
    (team_id, channel_id) unique index if they shared one store."""
    from retention_policy_store import RetentionPolicyStore
    import retention_policy_store as rps_module
    import routes_retention

    store = RetentionPolicyStore(db_path=tempfile.mktemp(suffix=".db"))
    monkeypatch.setattr(rps_module, "retention_policy_store", store)
    monkeypatch.setattr(routes_retention, "retention_policy_store", store)
    return store


def _allow_retention(monkeypatch, email="test@example.com"):
    import auth
    monkeypatch.setattr(auth, "RETENTION_ALLOWED_USERS", email)


def test_connection_status_forbidden_when_not_allowlisted(test_client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "RETENTION_ALLOWED_USERS", "someone-else@example.com")
    resp = test_client.get("/api/retention/connection/status")
    assert resp.status_code == 403


def test_connection_status_disconnected_by_default(test_client, monkeypatch):
    _allow_retention(monkeypatch)
    resp = test_client.get("/api/retention/connection/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "disconnected"


def test_create_policy_rejects_out_of_range_days(test_client, monkeypatch):
    _allow_retention(monkeypatch)
    resp = test_client.post(
        "/api/retention/policies",
        json={"team_id": "t1", "team_name": "Eng", "channel_id": "c1", "channel_name": "General", "retention_days": 400},
    )
    assert resp.status_code == 400


def test_create_then_confirm_policy(test_client, monkeypatch):
    _allow_retention(monkeypatch)
    create_resp = test_client.post(
        "/api/retention/policies",
        json={"team_id": "t1", "team_name": "Eng", "channel_id": "c1", "channel_name": "General", "retention_days": 30},
    )
    assert create_resp.status_code == 200
    policy = create_resp.json()
    assert policy["status"] == "pending_preview"

    confirm_resp = test_client.post(f"/api/retention/policies/{policy['id']}/confirm")
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "active"


def test_create_policy_conflicts_when_channel_already_has_one(test_client, monkeypatch):
    _allow_retention(monkeypatch)
    body = {"team_id": "t1", "team_name": "Eng", "channel_id": "c1", "channel_name": "General", "retention_days": 30}
    first = test_client.post("/api/retention/policies", json=body)
    assert first.status_code == 200
    second = test_client.post("/api/retention/policies", json=body)
    assert second.status_code == 409


def test_patch_policy_retention_days_resets_status(test_client, monkeypatch):
    _allow_retention(monkeypatch)
    create_resp = test_client.post(
        "/api/retention/policies",
        json={"team_id": "t1", "team_name": "Eng", "channel_id": "c1", "channel_name": "General", "retention_days": 30},
    )
    policy_id = create_resp.json()["id"]
    test_client.post(f"/api/retention/policies/{policy_id}/confirm")

    patch_resp = test_client.patch(f"/api/retention/policies/{policy_id}", json={"retention_days": 60})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "pending_preview"
    assert patch_resp.json()["retention_days"] == 60


def test_list_runs_and_deletions_pagination(test_client, monkeypatch):
    import retention_policy_store as rps_module
    _allow_retention(monkeypatch)
    store = rps_module.retention_policy_store
    policy = store.create_policy(
        team_id="t1", team_name="Eng", channel_id="c1", channel_name="General", retention_days=30, created_by="x",
    )
    run_id = store.start_run(policy["id"])
    store.record_deletion(
        run_id=run_id, item_type="message", item_id="m1", sender_or_author="Alice",
        original_created_at="2026-01-01T00:00:00Z", status="deleted",
    )
    store.finish_run(run_id, outcome="ok", messages_deleted=1, attachments_deleted=0)

    runs_resp = test_client.get(f"/api/retention/runs?policy_id={policy['id']}")
    assert runs_resp.status_code == 200
    assert runs_resp.json()["total"] == 1

    deletions_resp = test_client.get(f"/api/retention/deletions?run_id={run_id}")
    assert deletions_resp.status_code == 200
    assert deletions_resp.json()["total"] == 1
