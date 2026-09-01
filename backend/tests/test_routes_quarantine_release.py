"""Tests for quarantine release job API routes."""
from __future__ import annotations

import uuid


def test_get_status_no_settings_row_bootstraps_disabled(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    resp = test_client.get("/api/quarantine-release/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["allowed_domains"] == ["complexlegal.com"]
    assert data["last_run"] is None


def test_get_status_reflects_last_run(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO quarantine_release_runs (run_hour, ran_at, domains_checked, checked_count, released_count, failed_count) "
            "VALUES ('2026-09-01T14:00:00Z', '2026-09-01T14:02:00+00:00', 'complexlegal.com', 3, 3, 0)"
        )
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    resp = test_client.get("/api/quarantine-release/status")
    assert resp.status_code == 200
    last_run = resp.json()["last_run"]
    assert last_run["run_hour"] == "2026-09-01T14:00:00Z"
    assert last_run["released_count"] == 3
    assert last_run["error"] is None


def test_get_status_surfaces_run_error(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO quarantine_release_runs "
            "(run_hour, ran_at, domains_checked, checked_count, released_count, failed_count, error) "
            "VALUES ('2026-09-01T15:00:00Z', '2026-09-01T15:01:00+00:00', 'complexlegal.com', 0, 0, 0, "
            "'Exchange Online PowerShell timed out after 600 seconds.')"
        )
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    resp = test_client.get("/api/quarantine-release/status")
    assert resp.status_code == 200
    last_run = resp.json()["last_run"]
    assert last_run["error"] == "Exchange Online PowerShell timed out after 600 seconds."


def test_get_status_forbidden_for_non_admin(test_client, monkeypatch, tmp_path):
    import auth
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: email != "non-admin@example.com")
    non_admin_sid = auth.create_session("non-admin@example.com", "Non Admin")
    test_client.cookies.set("session_id", non_admin_sid)
    try:
        resp = test_client.get("/api/quarantine-release/status")
        assert resp.status_code == 403
    finally:
        test_client.cookies.set("session_id", auth.create_session("test@example.com", "Test User"))


def test_get_runs_pagination(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    with job._sqlite_conn() as conn:
        for hour in ["2026-09-01T12:00:00Z", "2026-09-01T13:00:00Z", "2026-09-01T14:00:00Z"]:
            conn.execute(
                "INSERT INTO quarantine_release_runs (run_hour, ran_at, domains_checked, checked_count, released_count, failed_count) "
                "VALUES (?, ?, 'complexlegal.com', 1, 1, 0)",
                (hour, f"{hour[:-1]}+00:00"),
            )
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    resp = test_client.get("/api/quarantine-release/runs?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["items"][0]["run_hour"] == "2026-09-01T14:00:00Z"


def test_get_runs_rejects_negative_limit_and_offset(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    assert test_client.get("/api/quarantine-release/runs?limit=-5").status_code == 422
    assert test_client.get("/api/quarantine-release/runs?offset=-1").status_code == 422
    assert test_client.get("/api/quarantine-release/runs?limit=0").status_code == 422


def test_get_releases_rejects_negative_limit_and_offset(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    assert test_client.get("/api/quarantine-release/releases?limit=-5").status_code == 422
    assert test_client.get("/api/quarantine-release/releases?offset=-1").status_code == 422


def test_get_releases_pagination_and_run_hour_filter(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO quarantine_releases "
            "(id, run_hour, message_identity, sender_address, recipient_address, subject, received_at, quarantine_reason, status, error, released_at) "
            "VALUES (?, '2026-09-01T14:00:00Z', 'msg-1', 'a@complexlegal.com', 'b@example.com', 'Invoice', '', 'Spam', 'released', NULL, '2026-09-01T14:02:00+00:00')",
            (uuid.uuid4().hex,),
        )
        conn.execute(
            "INSERT INTO quarantine_releases "
            "(id, run_hour, message_identity, sender_address, recipient_address, subject, received_at, quarantine_reason, status, error, released_at) "
            "VALUES (?, '2026-09-01T13:00:00Z', 'msg-2', 'c@complexlegal.com', 'd@example.com', 'Statement', '', 'Bulk', 'released', NULL, '2026-09-01T13:02:00+00:00')",
            (uuid.uuid4().hex,),
        )
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    resp_all = test_client.get("/api/quarantine-release/releases")
    assert resp_all.json()["total"] == 2

    resp_filtered = test_client.get("/api/quarantine-release/releases?run_hour=2026-09-01T14:00:00Z")
    data = resp_filtered.json()
    assert data["total"] == 1
    assert data["items"][0]["message_identity"] == "msg-1"


def test_patch_settings_admin_updates_enabled_and_domains(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    resp = test_client.patch(
        "/api/quarantine-release/settings",
        json={"enabled": True, "allowed_domains": ["complexlegal.com", "partner.org"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["allowed_domains"] == ["complexlegal.com", "partner.org"]


def test_patch_settings_partial_update_preserves_other_field(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    test_client.patch(
        "/api/quarantine-release/settings",
        json={"enabled": True, "allowed_domains": ["complexlegal.com"]},
    )
    resp = test_client.patch("/api/quarantine-release/settings", json={"enabled": False})
    data = resp.json()
    assert data["enabled"] is False
    assert data["allowed_domains"] == ["complexlegal.com"]


def test_patch_settings_forbidden_for_non_admin(test_client, monkeypatch, tmp_path):
    import auth
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: email != "non-admin@example.com")
    non_admin_sid = auth.create_session("non-admin@example.com", "Non Admin")
    test_client.cookies.set("session_id", non_admin_sid)
    try:
        resp = test_client.patch("/api/quarantine-release/settings", json={"enabled": True})
        assert resp.status_code == 403
    finally:
        test_client.cookies.set("session_id", auth.create_session("test@example.com", "Test User"))
