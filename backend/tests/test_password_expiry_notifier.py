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
