from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _reload_config():
    import config

    return importlib.reload(config)


def test_config_rejects_insecure_default_app_secret(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("APP_SECRET_KEY", "change-me-in-production")

    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        _reload_config()._load_app_secret_key()


def test_config_allows_test_runtime_without_explicit_app_secret(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "")
    monkeypatch.setenv("APP_ENV", "test")

    config = _reload_config()

    assert config._load_app_secret_key() == "test-secret-key"
