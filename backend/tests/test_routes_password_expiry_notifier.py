"""Tests for password expiry notifier API routes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def test_get_status_no_db_row(test_client, monkeypatch, tmp_path):
    """GET /status returns enabled=False and null last_run when no rows exist."""
    import password_expiry_notifier as pen_module

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    resp = test_client.get("/api/password-expiry-notifier/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["last_run"] is None
    assert data["config"]["max_age_days"] == 90
    assert data["config"]["days_before"] == 14


def test_get_status_with_db_row(test_client, monkeypatch, tmp_path):
    """GET /status returns enabled=True when DB settings row has enabled=1."""
    import password_expiry_notifier as pen_module

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    with notifier._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO password_expiry_notifier_settings (id, enabled, updated_at, updated_by) VALUES (1, 1, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), "admin@example.com"),
        )
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    resp = test_client.get("/api/password-expiry-notifier/status")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


def test_get_runs_pagination(test_client, monkeypatch, tmp_path):
    """GET /runs returns rows newest-first with correct total."""
    import password_expiry_notifier as pen_module

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    with notifier._sqlite_conn() as conn:
        for d in ["2026-05-01", "2026-05-02", "2026-05-03"]:
            conn.execute(
                "INSERT INTO password_expiry_notify_runs (run_date, ran_at, users_notified, test_mode) VALUES (?, ?, ?, ?)",
                (d, f"{d}T02:00:00+00:00", 5, 1),
            )
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    resp = test_client.get("/api/password-expiry-notifier/runs?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["items"][0]["run_date"] == "2026-05-03"


def test_get_notifications_pagination(test_client, monkeypatch, tmp_path):
    """GET /notifications returns rows newest-first with correct total."""
    import password_expiry_notifier as pen_module

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    with notifier._sqlite_conn() as conn:
        for i, ts in enumerate(["2026-05-01T02:00:00+00:00", "2026-05-02T02:00:00+00:00"]):
            conn.execute(
                "INSERT INTO password_expiry_notifications "
                "(id, sam_account_name, email, expiry_date, days_until_expiry, notified_at, test_mode) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, f"user{i}", f"user{i}@corp.com", "2026-06-01", 10 - i, ts, 1),
            )
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    resp = test_client.get("/api/password-expiry-notifier/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["items"][0]["notified_at"] == "2026-05-02T02:00:00+00:00"


def test_patch_settings_admin(test_client, monkeypatch, tmp_path):
    """PATCH /settings with admin session enables the notifier."""
    import password_expiry_notifier as pen_module

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    resp = test_client.patch("/api/password-expiry-notifier/settings", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


def test_patch_settings_non_admin_forbidden(test_client, monkeypatch, tmp_path):
    """PATCH /settings with non-admin session returns 403."""
    import auth
    import password_expiry_notifier as pen_module

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    # get_session re-evaluates is_admin via is_admin_user; patch it to gate on email
    monkeypatch.setattr(auth, "is_admin_user", lambda email: email != "non-admin@example.com")
    non_admin_sid = auth.create_session("non-admin@example.com", "Non Admin")
    test_client.cookies.set("session_id", non_admin_sid)
    try:
        resp = test_client.patch("/api/password-expiry-notifier/settings", json={"enabled": True})
        assert resp.status_code == 403
    finally:
        test_client.cookies.set("session_id", auth.create_session("test@example.com", "Test User"))
