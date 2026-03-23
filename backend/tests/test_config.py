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


def test_cost_export_config_defaults_and_bool_parsing(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATA_DIR", "/tmp/azure-data")
    monkeypatch.setenv("AZURE_COST_EXPORTS_ENABLED", "true")
    monkeypatch.delenv("AZURE_COST_EXPORT_ROOT", raising=False)
    monkeypatch.delenv("AZURE_COST_EXPORT_MANIFEST_DB_PATH", raising=False)
    monkeypatch.delenv("AZURE_COST_EXPORT_STAGING_DIR", raising=False)
    monkeypatch.delenv("AZURE_COST_EXPORT_QUARANTINE_DIR", raising=False)

    config = _reload_config()

    assert config.AZURE_COST_EXPORTS_ENABLED is True
    assert config.AZURE_COST_EXPORT_ROOT == "/tmp/azure-data/azure_cost_exports"
    assert config.AZURE_COST_EXPORT_MANIFEST_DB_PATH == "/tmp/azure-data/azure_export_deliveries.db"
    assert config.AZURE_COST_EXPORT_STAGING_DIR == "/tmp/azure-data/azure_cost_exports/_staged"
    assert config.AZURE_COST_EXPORT_QUARANTINE_DIR == "/tmp/azure-data/azure_cost_exports/_quarantine"


def test_reporting_handoff_config_defaults_and_overrides(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AZURE_REPORTING_POWER_BI_URL", "https://app.powerbi.com/groups/example")
    monkeypatch.setenv("AZURE_REPORTING_COST_ANALYSIS_URL", "https://portal.azure.com/#blade/Microsoft_Azure_CostManagement/Menu/costanalysis")
    monkeypatch.setenv("AZURE_REPORTING_POWER_BI_LABEL", "FinOps Workspace")
    monkeypatch.delenv("AZURE_REPORTING_COST_ANALYSIS_LABEL", raising=False)

    config = _reload_config()

    assert config.AZURE_REPORTING_POWER_BI_URL == "https://app.powerbi.com/groups/example"
    assert config.AZURE_REPORTING_COST_ANALYSIS_URL.startswith("https://portal.azure.com/")
    assert config.AZURE_REPORTING_POWER_BI_LABEL == "FinOps Workspace"
    assert config.AZURE_REPORTING_COST_ANALYSIS_LABEL == "Azure Cost Analysis"
