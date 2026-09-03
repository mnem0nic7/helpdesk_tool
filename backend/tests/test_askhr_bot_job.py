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


from unittest.mock import MagicMock, patch


def test_refresh_trusted_domains_calls_exchange_when_stale(monkeypatch):
    import askhr_bot_job as job_module
    from datetime import datetime, timezone

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(job_module, "_utcnow", lambda: now)

    job = _fresh_job()
    job._get_settings()  # bootstrap; trusted_domains_refreshed_at == ""

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.get_transport_rule_domains.return_value = ["librasolutionsgroup.com", "movedocs.com"]

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        job._refresh_trusted_domains_if_needed()

    exchange.get_transport_rule_domains.assert_called_once_with(job_module._TRANSPORT_RULE_IDENTITY)
    settings = job._get_settings()
    assert settings["trusted_domains"] == ["librasolutionsgroup.com", "movedocs.com"]
    assert settings["trusted_domains_refreshed_at"] == now.isoformat()


def test_refresh_trusted_domains_skips_when_still_fresh(monkeypatch):
    import askhr_bot_job as job_module
    from datetime import datetime, timezone

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(job_module, "_utcnow", lambda: now)

    job = _fresh_job()
    job._get_settings()
    job._update_settings(trusted_domains=["movedocs.com"], trusted_domains_refreshed_at=now.isoformat())

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        job._refresh_trusted_domains_if_needed()

    exchange.get_transport_rule_domains.assert_not_called()
