"""Tests for the quarantine auto-release job core: settings and hour-gating."""
from __future__ import annotations

import tempfile


def _fresh_job():
    from quarantine_release_job import QuarantineReleaseJob
    tmp = tempfile.mktemp(suffix=".db")
    return QuarantineReleaseJob(db_path=tmp)


def test_parse_domains_splits_and_normalizes():
    from quarantine_release_job import _parse_domains

    assert _parse_domains("complexlegal.com, Example.com ,,") == ["complexlegal.com", "example.com"]
    assert _parse_domains("") == []
    assert _parse_domains(None) == []


def test_get_settings_bootstraps_default_row_when_missing(monkeypatch):
    import config
    monkeypatch.setattr(config, "QUARANTINE_RELEASE_DEFAULT_DOMAINS", "complexlegal.com")
    import quarantine_release_job as qrj_module
    monkeypatch.setattr(qrj_module, "QUARANTINE_RELEASE_DEFAULT_DOMAINS", "complexlegal.com")

    job = _fresh_job()
    settings = job._get_settings()

    assert settings == {"enabled": False, "allowed_domains": ["complexlegal.com"]}

    # Second call reads the now-persisted row rather than re-bootstrapping.
    settings_again = job._get_settings()
    assert settings_again == {"enabled": False, "allowed_domains": ["complexlegal.com"]}


def test_get_settings_reads_persisted_enabled_and_domains():
    job = _fresh_job()
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO quarantine_release_settings (id, enabled, allowed_domains, updated_at, updated_by) "
            "VALUES (1, 1, 'complexlegal.com,partner.org', '2026-09-01T00:00:00+00:00', 'admin@example.com')"
        )

    settings = job._get_settings()

    assert settings == {"enabled": True, "allowed_domains": ["complexlegal.com", "partner.org"]}


def test_already_ran_this_hour_true_after_run_row_inserted():
    job = _fresh_job()
    run_hour = "2026-09-01T14:00:00Z"
    with job._sqlite_conn() as conn:
        assert job._already_ran_this_hour(run_hour, conn) is False
        conn.execute(
            "INSERT INTO quarantine_release_runs (run_hour, ran_at, domains_checked, checked_count, released_count, failed_count) "
            "VALUES (?, ?, ?, 0, 0, 0)",
            (run_hour, "2026-09-01T14:01:00+00:00", "complexlegal.com"),
        )
    with job._sqlite_conn() as conn:
        assert job._already_ran_this_hour(run_hour, conn) is True


from unittest.mock import MagicMock, patch


def _seed_settings(job, *, enabled: bool, domains: str = "complexlegal.com"):
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO quarantine_release_settings (id, enabled, allowed_domains, updated_at, updated_by) "
            "VALUES (1, ?, ?, '2026-09-01T00:00:00+00:00', 'admin@example.com')",
            (1 if enabled else 0, domains),
        )


async def test_run_hourly_job_skips_when_disabled_and_writes_no_run_row():
    job = _fresh_job()
    _seed_settings(job, enabled=False)

    mock_uap_module = MagicMock()
    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        await job.run_hourly_job()

    mock_uap_module.user_admin_providers.mailbox.exchange_powershell.list_quarantine_messages.assert_not_called()
    with job._sqlite_conn() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM quarantine_release_runs").fetchone()["c"]
    assert count == 0


async def test_run_hourly_job_releases_matching_messages_and_records_run(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import quarantine_release_job as qrj_module

    hour = datetime(2026, 9, 1, 19, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(qrj_module, "_utcnow", lambda: hour)

    job = _fresh_job()
    _seed_settings(job, enabled=True, domains="complexlegal.com")

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.list_quarantine_messages.return_value = [
        {
            "identity": "msg-1",
            "sender_address": "billing@complexlegal.com",
            "recipient_address": "ap@example.com",
            "subject": "Invoice",
            "received_at": "2026-09-01T14:05:00Z",
            "quarantine_reason": "Spam",
        }
    ]
    exchange.release_quarantine_message.return_value = {"identity": "msg-1", "released": True}

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        await job.run_hourly_job()

    exchange.list_quarantine_messages.assert_called_once_with(
        ["complexlegal.com"],
        received_after=hour - timedelta(hours=qrj_module._QUARANTINE_LOOKBACK_HOURS),
        timeout_seconds=600,
    )
    exchange.release_quarantine_message.assert_called_once_with("msg-1")

    with job._sqlite_conn() as conn:
        run = conn.execute("SELECT * FROM quarantine_release_runs").fetchone()
        release = conn.execute("SELECT * FROM quarantine_releases").fetchone()
    assert run["checked_count"] == 1
    assert run["released_count"] == 1
    assert run["failed_count"] == 0
    assert release["status"] == "released"
    assert release["sender_address"] == "billing@complexlegal.com"


async def test_run_hourly_job_records_failure_without_aborting_other_messages():
    job = _fresh_job()
    _seed_settings(job, enabled=True, domains="complexlegal.com")

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.list_quarantine_messages.return_value = [
        {"identity": "msg-1", "sender_address": "a@complexlegal.com", "recipient_address": "x@example.com",
         "subject": "", "received_at": "", "quarantine_reason": "Spam"},
        {"identity": "msg-2", "sender_address": "b@complexlegal.com", "recipient_address": "y@example.com",
         "subject": "", "received_at": "", "quarantine_reason": "Phish"},
    ]
    exchange.release_quarantine_message.side_effect = [RuntimeError("boom"), {"identity": "msg-2", "released": True}]

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        await job.run_hourly_job()

    assert exchange.release_quarantine_message.call_count == 2
    with job._sqlite_conn() as conn:
        run = conn.execute("SELECT * FROM quarantine_release_runs").fetchone()
        statuses = {r["message_identity"]: r["status"] for r in conn.execute("SELECT * FROM quarantine_releases")}
    assert run["released_count"] == 1
    assert run["failed_count"] == 1
    assert statuses == {"msg-1": "failed", "msg-2": "released"}


async def test_run_hourly_job_does_not_reattempt_a_message_already_released_in_a_prior_run(monkeypatch):
    """Get-QuarantineMessage keeps returning a message for its whole retention window even
    after release. Simulate two separate hourly runs (via monkeypatching _utcnow, since the
    hour-gating key is derived from wall-clock time) where the mocked list call returns the
    SAME identity both times, and assert the second run does not re-attempt the release and
    records zero counts for that message rather than a spurious failure."""
    import quarantine_release_job as qrj_module
    from datetime import datetime, timezone

    job = _fresh_job()
    _seed_settings(job, enabled=True, domains="complexlegal.com")

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    same_message = {
        "identity": "msg-1",
        "sender_address": "billing@complexlegal.com",
        "recipient_address": "ap@example.com",
        "subject": "Invoice",
        "received_at": "2026-09-01T14:05:00Z",
        "quarantine_reason": "Spam",
    }
    exchange.list_quarantine_messages.return_value = [dict(same_message)]
    exchange.release_quarantine_message.return_value = {"identity": "msg-1", "released": True}

    hour1 = datetime(2026, 9, 1, 14, tzinfo=timezone.utc)
    hour2 = datetime(2026, 9, 1, 15, tzinfo=timezone.utc)

    monkeypatch.setattr(qrj_module, "_utcnow", lambda: hour1)
    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        await job.run_hourly_job()

    assert exchange.release_quarantine_message.call_count == 1

    monkeypatch.setattr(qrj_module, "_utcnow", lambda: hour2)
    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        await job.run_hourly_job()

    # Second hour's fetch returned the same already-released identity; it must be
    # filtered out before the release loop, so release is still only called once total.
    assert exchange.release_quarantine_message.call_count == 1

    with job._sqlite_conn() as conn:
        run_hour_2 = conn.execute(
            "SELECT * FROM quarantine_release_runs WHERE run_hour = ?",
            ("2026-09-01T15:00:00Z",),
        ).fetchone()
    assert run_hour_2 is not None
    assert run_hour_2["checked_count"] == 0
    assert run_hour_2["released_count"] == 0
    assert run_hour_2["failed_count"] == 0

    with job._sqlite_conn() as conn:
        release_count = conn.execute("SELECT COUNT(*) AS c FROM quarantine_releases").fetchone()["c"]
    assert release_count == 1


async def test_run_hourly_job_records_run_row_with_error_when_listing_fails(monkeypatch):
    """A failed list_quarantine_messages() call used to just log and return, leaving NO
    run row — indistinguishable from a job that's never run. It must now record a run row
    with the error populated so /status can surface the failure."""
    from datetime import datetime, timedelta, timezone
    import quarantine_release_job as qrj_module

    hour = datetime(2026, 9, 1, 19, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(qrj_module, "_utcnow", lambda: hour)

    job = _fresh_job()
    _seed_settings(job, enabled=True, domains="complexlegal.com")

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.list_quarantine_messages.side_effect = RuntimeError("timed out after 600 seconds")

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        await job.run_hourly_job()

    exchange.list_quarantine_messages.assert_called_once_with(
        ["complexlegal.com"],
        received_after=hour - timedelta(hours=qrj_module._QUARANTINE_LOOKBACK_HOURS),
        timeout_seconds=600,
    )
    with job._sqlite_conn() as conn:
        run = conn.execute("SELECT * FROM quarantine_release_runs").fetchone()
    assert run is not None
    assert run["checked_count"] == 0
    assert run["released_count"] == 0
    assert run["failed_count"] == 0
    assert run["error"] == "timed out after 600 seconds"


async def test_run_hourly_job_warns_and_skips_message_with_missing_identity(caplog):
    job = _fresh_job()
    _seed_settings(job, enabled=True, domains="complexlegal.com")

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.list_quarantine_messages.return_value = [
        {
            "identity": "",
            "sender_address": "nobody@complexlegal.com",
            "recipient_address": "x@example.com",
            "subject": "Mystery",
            "received_at": "",
            "quarantine_reason": "Spam",
        }
    ]

    import logging
    with caplog.at_level(logging.WARNING, logger="quarantine_release_job"):
        with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
            await job.run_hourly_job()

    exchange.release_quarantine_message.assert_not_called()
    assert any("missing identity" in record.message for record in caplog.records)
    with job._sqlite_conn() as conn:
        release_count = conn.execute("SELECT COUNT(*) AS c FROM quarantine_releases").fetchone()["c"]
    assert release_count == 0


async def test_run_hourly_job_skips_if_already_ran_this_hour():
    job = _fresh_job()
    _seed_settings(job, enabled=True, domains="complexlegal.com")

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.list_quarantine_messages.return_value = []

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        await job.run_hourly_job()
        await job.run_hourly_job()

    assert exchange.list_quarantine_messages.call_count == 1


async def test_start_and_stop_background_runner_does_not_raise():
    import asyncio

    job = _fresh_job()
    job.start_background_runner()
    assert job._bg_task is not None
    await asyncio.sleep(0)
    job.stop_background_runner()
    await asyncio.sleep(0)
    assert job._bg_task.cancelled() or job._bg_task.done()
