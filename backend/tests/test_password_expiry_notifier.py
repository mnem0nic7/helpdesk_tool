"""Tests for password expiry notifier."""
import importlib
import os
import sys


def test_config_defaults(monkeypatch):
    """Config vars have correct defaults."""
    monkeypatch.delenv("PASSWORD_EXPIRY_NOTIFY_ENABLED", raising=False)
    monkeypatch.delenv("AD_MAX_PWD_AGE_DAYS", raising=False)
    monkeypatch.delenv("PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE", raising=False)

    # Re-import config with cleared env
    if "config" in sys.modules:
        del sys.modules["config"]
    import config as cfg

    assert cfg.PASSWORD_EXPIRY_NOTIFY_ENABLED is False
    assert cfg.AD_MAX_PWD_AGE_DAYS == 90
    assert cfg.PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE == 14


from datetime import date, datetime, timezone, timedelta


def _make_user(pwd_last_set_days_ago: int | None, enabled: bool = True, email: str = "user@example.com") -> dict:
    if pwd_last_set_days_ago is None:
        pwd_last_set = None
    else:
        dt = datetime.now(timezone.utc) - timedelta(days=pwd_last_set_days_ago)
        pwd_last_set = dt.isoformat()
    return {
        "sam_account_name": "jdoe",
        "display_name": "Jane Doe",
        "email": email,
        "pwd_last_set": pwd_last_set,
        "flags": {"enabled": enabled},
    }


def test_days_until_expiry_normal():
    from password_expiry_notifier import _days_until_expiry
    # Password set 80 days ago with 90-day max age → 10 days left
    result = _days_until_expiry(_make_user(80), max_age_days=90)
    assert result == 10


def test_days_until_expiry_no_pwd_last_set():
    from password_expiry_notifier import _days_until_expiry
    result = _days_until_expiry(_make_user(None), max_age_days=90)
    assert result is None


def test_days_until_expiry_already_expired():
    from password_expiry_notifier import _days_until_expiry
    # Password set 95 days ago → already expired
    result = _days_until_expiry(_make_user(95), max_age_days=90)
    assert result is not None and result <= 0


def test_should_notify_true():
    from password_expiry_notifier import _should_notify
    # 10 days left, window is 14 → should notify
    user = _make_user(80)
    days = _should_notify(user, max_age_days=90, days_before=14)
    assert days == 10


def test_should_notify_false_outside_window():
    from password_expiry_notifier import _should_notify
    # 30 days left → outside 14-day window
    user = _make_user(60)
    assert _should_notify(user, max_age_days=90, days_before=14) is None


def test_should_notify_false_disabled():
    from password_expiry_notifier import _should_notify
    user = _make_user(80, enabled=False)
    assert _should_notify(user, max_age_days=90, days_before=14) is None


def test_should_notify_false_no_email():
    from password_expiry_notifier import _should_notify
    user = _make_user(80, email="")
    assert _should_notify(user, max_age_days=90, days_before=14) is None


def test_should_notify_false_no_pwd_last_set():
    from password_expiry_notifier import _should_notify
    user = _make_user(None)
    assert _should_notify(user, max_age_days=90, days_before=14) is None


import sqlite3
import tempfile
import os
import uuid


def _make_notifier(tmp_path: str, enabled: bool = False):
    from password_expiry_notifier import PasswordExpiryNotifier
    db = os.path.join(tmp_path, "test_pen.db")
    notifier = PasswordExpiryNotifier(db_path=db)
    notifier._notify_enabled = enabled
    return notifier


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def test_already_ran_today_false(tmp_path):
    n = _make_notifier(str(tmp_path))
    with n._sqlite_conn() as conn:
        assert n._already_ran_today(conn) is False


def test_already_ran_today_true(tmp_path):
    n = _make_notifier(str(tmp_path))
    today = _today()
    with n._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO password_expiry_notify_runs (run_date, ran_at, users_notified, test_mode) VALUES (?,?,?,?)",
            (today, datetime.now(timezone.utc).isoformat(), 0, 1),
        )
        assert n._already_ran_today(conn) is True


def test_already_notified_today_false(tmp_path):
    n = _make_notifier(str(tmp_path))
    with n._sqlite_conn() as conn:
        assert n._already_notified_today("jdoe", conn) is False


def test_already_notified_today_true(tmp_path):
    n = _make_notifier(str(tmp_path))
    today = _today()
    with n._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO password_expiry_notifications (id, sam_account_name, email, expiry_date, days_until_expiry, notified_at, test_mode) VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, "jdoe", "jdoe@x.com", "2026-06-01", 5, f"{today}T00:00:00+00:00", 1),
        )
        assert n._already_notified_today("jdoe", conn) is True


def test_already_notified_today_different_day(tmp_path):
    n = _make_notifier(str(tmp_path))
    with n._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO password_expiry_notifications (id, sam_account_name, email, expiry_date, days_until_expiry, notified_at, test_mode) VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, "jdoe", "jdoe@x.com", "2026-06-01", 5, "2020-01-01T00:00:00+00:00", 1),
        )
        assert n._already_notified_today("jdoe", conn) is False


def test_record_notification_writes_row(tmp_path):
    n = _make_notifier(str(tmp_path))
    with n._sqlite_conn() as conn:
        n._record_notification(
            sam="jdoe",
            email="jdoe@x.com",
            expiry_date="2026-06-01",
            days=10,
            test_mode=True,
            conn=conn,
        )
        row = conn.execute(
            "SELECT * FROM password_expiry_notifications WHERE sam_account_name='jdoe'"
        ).fetchone()
    assert row is not None
    assert row["days_until_expiry"] == 10
    assert row["test_mode"] == 1


def test_record_run_writes_row(tmp_path):
    n = _make_notifier(str(tmp_path))
    today = _today()
    with n._sqlite_conn() as conn:
        n._record_run(users_notified=3, test_mode=True, conn=conn)
        row = conn.execute(
            "SELECT * FROM password_expiry_notify_runs WHERE run_date=?", (today,)
        ).fetchone()
    assert row is not None
    assert row["users_notified"] == 3
    assert row["test_mode"] == 1
