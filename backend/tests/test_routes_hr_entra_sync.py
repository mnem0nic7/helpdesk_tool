"""Admin API for the Entra -> Jira HR ticket sync."""
from __future__ import annotations

import hr_entra_sync as s
from tests.test_hr_entra_sync import FakeAzure, FakeJira, _issue, _user


def _job(tmp_path, jira=None, azure=None):
    return s.HrEntraSyncJob(db_path=str(tmp_path / "hr.db"), jira=jira or FakeJira(), azure=azure or FakeAzure())


def test_status_lists_active_and_inactive_fields(test_client):
    data = test_client.get("/api/hr-entra-sync/status").json()
    assert data["projects"] and "Job Title" in data["active_fields"]
    inactive = {f["jira_name"]: f for f in data["inactive_fields"]}
    assert inactive["FLSA Status"]["enabled"] is False and inactive["FLSA Status"]["note"]
    assert inactive["Associate ID"]["enabled"] is False and inactive["Associate ID"]["has_jira_field_id"] is True


def test_status_forbidden_for_non_admin(test_client, monkeypatch):
    import auth

    monkeypatch.setattr(auth, "is_admin_user", lambda email: False)
    sid = auth.create_session("non-admin@example.com", "Non Admin")
    test_client.cookies.set("session_id", sid)
    try:
        assert test_client.get("/api/hr-entra-sync/status").status_code == 403
        assert test_client.post("/api/hr-entra-sync/issues/HRD-1/run").status_code == 403
    finally:
        test_client.cookies.delete("session_id")


def test_manual_run_defaults_to_dry_run(test_client, monkeypatch, tmp_path):
    import routes_hr_entra_sync

    jira = FakeJira({"HRD-1": _issue(customfield_12879="jdoe@x.com")})
    job = _job(tmp_path, jira, FakeAzure({"jdoe@x.com": [_user()]}))
    monkeypatch.setattr(routes_hr_entra_sync, "hr_entra_sync_job", job)
    body = test_client.post("/api/hr-entra-sync/issues/HRD-1/run").json()
    assert body["outcome"] == "synced" and body["dry_run"] is True and jira.updates == []
    live = test_client.post("/api/hr-entra-sync/issues/HRD-1/run?dry_run=false").json()
    assert live["dry_run"] is False and len(jira.updates) == 1


def test_manual_run_rejects_bad_key(test_client):
    assert test_client.post("/api/hr-entra-sync/issues/not-a-key/run").status_code == 400
