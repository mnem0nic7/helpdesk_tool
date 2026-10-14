"""Admin API for the HR auto-cancel job."""
from __future__ import annotations

from tests.test_hr_auto_cancel import FakeJira, _issue, NOW
import hr_auto_cancel as ac


def _job(tmp_path, issues):
    return ac.HrAutoCancelJob(db_path=str(tmp_path / "ac.db"), jira=FakeJira(issues))


def test_status_reports_settings_and_counts(test_client, monkeypatch, tmp_path):
    import routes_hr_auto_cancel as r

    job = _job(tmp_path, [_issue("HRD-1", "support@osidigital.com")])
    job.run_cycle_sync(NOW)
    monkeypatch.setattr(r, "hr_auto_cancel_job", job)
    data = test_client.get("/api/hr-auto-cancel/status").json()
    assert data["target_status"] == "Cancelled by HR" and "osidigital.com" in data["sender_domains"]
    assert data["counts"]["cancelled"] == 1 and "HRD" in data["projects"]
    assert test_client.get("/api/hr-auto-cancel/actions").json()["actions"][0]["issue_key"] == "HRD-1"


def test_preview_is_read_only(test_client, monkeypatch, tmp_path):
    import routes_hr_auto_cancel as r

    jira = FakeJira([_issue("HRD-1", "support@osidigital.com")])
    job = ac.HrAutoCancelJob(db_path=str(tmp_path / "ac.db"), jira=jira)
    monkeypatch.setattr(r, "hr_auto_cancel_job", job)
    body = test_client.get("/api/hr-auto-cancel/preview").json()
    assert [c["key"] for c in body["would_cancel"]] == ["HRD-1"] and jira.done == []


def test_routes_are_admin_only(test_client, monkeypatch):
    import auth

    monkeypatch.setattr(auth, "is_admin_user", lambda email: False)
    sid = auth.create_session("non-admin@example.com", "Non Admin")
    test_client.cookies.set("session_id", sid)
    try:
        for path in ("status", "actions", "preview"):
            assert test_client.get(f"/api/hr-auto-cancel/{path}").status_code == 403
    finally:
        test_client.cookies.delete("session_id")
