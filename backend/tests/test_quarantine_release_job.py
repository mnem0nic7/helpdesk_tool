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
