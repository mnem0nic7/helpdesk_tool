"""Tests for the AskHR/Benefits bot job core: schema, settings bootstrap, and updates."""
from __future__ import annotations

import tempfile


def _fresh_job():
    from askhr_bot_job import AskHrBotJob
    tmp = tempfile.mktemp(suffix=".db")
    return AskHrBotJob(db_path=tmp)


def test_get_settings_bootstraps_default_row_when_missing(monkeypatch):
    import config
    monkeypatch.setattr(config, "ASKHR_BOT_ENABLED_DEFAULT", False)
    import askhr_bot_job as job_module
    monkeypatch.setattr(job_module, "ASKHR_BOT_ENABLED_DEFAULT", False)

    job = _fresh_job()
    settings = job._get_settings()

    assert settings["enabled"] is False
    assert settings["poll_interval_seconds"] == 120
    assert settings["lookback_minutes"] == 15
    assert settings["askhr_checkpoint_at"] == ""
    assert settings["benefits_checkpoint_at"] == ""
    assert settings["trusted_domains"] == []
    assert settings["domain_refresh_interval_seconds"] == 3600
    assert settings["reporter_mode"] == "unset"

    # Second call reads the persisted row rather than re-bootstrapping.
    assert job._get_settings() == settings


def test_update_settings_partial_update_preserves_other_fields():
    job = _fresh_job()
    job._get_settings()  # bootstrap

    updated = job._update_settings(enabled=True, poll_interval_seconds=60, updated_by="admin@example.com")

    assert updated["enabled"] is True
    assert updated["poll_interval_seconds"] == 60
    assert updated["lookback_minutes"] == 15  # untouched

    again = job._update_settings(enabled=False)
    assert again["enabled"] is False
    assert again["poll_interval_seconds"] == 60  # still preserved


def test_update_settings_persists_trusted_domains_and_checkpoints():
    job = _fresh_job()
    job._get_settings()

    updated = job._update_settings(
        trusted_domains=["librasolutionsgroup.com", "movedocs.com"],
        askhr_checkpoint_at="2026-09-03T00:00:00+00:00",
    )

    assert updated["trusted_domains"] == ["librasolutionsgroup.com", "movedocs.com"]
    assert updated["askhr_checkpoint_at"] == "2026-09-03T00:00:00+00:00"
