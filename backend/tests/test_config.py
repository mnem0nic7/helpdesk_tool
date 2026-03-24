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
    monkeypatch.delenv("AZURE_FINOPS_DUCKDB_PATH", raising=False)
    monkeypatch.delenv("AZURE_COST_EXPORT_STAGING_DIR", raising=False)
    monkeypatch.delenv("AZURE_COST_EXPORT_QUARANTINE_DIR", raising=False)

    config = _reload_config()

    assert config.AZURE_COST_EXPORTS_ENABLED is True
    assert config.AZURE_COST_EXPORT_ROOT == "/tmp/azure-data/azure_cost_exports"
    assert config.AZURE_COST_EXPORT_MANIFEST_DB_PATH == "/tmp/azure-data/azure_export_deliveries.db"
    assert config.AZURE_FINOPS_DUCKDB_PATH == "/tmp/azure-data/azure_finops.duckdb"
    assert config.AZURE_COST_EXPORT_STAGING_DIR == "/tmp/azure-data/azure_cost_exports/_staged"
    assert config.AZURE_COST_EXPORT_QUARANTINE_DIR == "/tmp/azure-data/azure_cost_exports/_quarantine"


def test_reporting_handoff_config_defaults_and_overrides(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JIRA_PROJECT", "OIT")
    monkeypatch.setenv("AZURE_REPORTING_POWER_BI_URL", "https://app.powerbi.com/groups/example")
    monkeypatch.setenv("AZURE_REPORTING_COST_ANALYSIS_URL", "https://portal.azure.com/#blade/Microsoft_Azure_CostManagement/Menu/costanalysis")
    monkeypatch.setenv("AZURE_REPORTING_POWER_BI_LABEL", "FinOps Workspace")
    monkeypatch.setenv("AZURE_FINOPS_RECOMMENDATION_JIRA_PROJECT", "FINOPS")
    monkeypatch.setenv("AZURE_FINOPS_RECOMMENDATION_JIRA_ISSUE_TYPE", "Story")
    monkeypatch.setenv("AZURE_FINOPS_RECOMMENDATION_TEAMS_WEBHOOK_URL", "https://hooks.example.test/finops")
    monkeypatch.setenv("AZURE_FINOPS_RECOMMENDATION_TEAMS_CHANNEL_LABEL", "FinOps Watch")
    monkeypatch.delenv("AZURE_REPORTING_COST_ANALYSIS_LABEL", raising=False)

    config = _reload_config()

    assert config.AZURE_REPORTING_POWER_BI_URL == "https://app.powerbi.com/groups/example"
    assert config.AZURE_REPORTING_COST_ANALYSIS_URL.startswith("https://portal.azure.com/")
    assert config.AZURE_REPORTING_POWER_BI_LABEL == "FinOps Workspace"
    assert config.AZURE_REPORTING_COST_ANALYSIS_LABEL == "Azure Cost Analysis"
    assert config.AZURE_AVD_SESSION_HISTORY_LOOKBACK_DAYS == 90
    assert config.AZURE_FINOPS_RECOMMENDATION_JIRA_PROJECT == "FINOPS"
    assert config.AZURE_FINOPS_RECOMMENDATION_JIRA_ISSUE_TYPE == "Story"
    assert config.AZURE_FINOPS_RECOMMENDATION_TEAMS_WEBHOOK_URL == "https://hooks.example.test/finops"
    assert config.AZURE_FINOPS_RECOMMENDATION_TEAMS_CHANNEL_LABEL == "FinOps Watch"


def test_ollama_config_defaults_and_overrides(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/")
    monkeypatch.setenv("OLLAMA_MODEL", "")
    monkeypatch.setenv("OLLAMA_FAST_MODEL", "")
    monkeypatch.delenv("OLLAMA_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "")
    monkeypatch.setenv("AUTO_TRIAGE_MODEL", "")
    monkeypatch.setenv("TECHNICIAN_SCORE_MODEL", "")
    monkeypatch.setenv("AZURE_ALERT_RULE_MODEL", "")

    config = _reload_config()

    assert config.OLLAMA_ENABLED is True
    assert config.OLLAMA_BASE_URL == "http://localhost:11434"
    assert config.OLLAMA_MODEL == "qwen2.5:7b"
    assert config.OLLAMA_FAST_MODEL == "qwen2.5:3b"
    assert config.OLLAMA_REQUEST_TIMEOUT_SECONDS == 300
    assert config.OLLAMA_KEEP_ALIVE == "15m"
    assert config.AUTO_TRIAGE_MODEL == "qwen2.5:3b"
    assert config.TECHNICIAN_SCORE_MODEL == "qwen2.5:3b"
    assert config.AZURE_ALERT_RULE_MODEL == "qwen2.5:3b"


def test_ai_pricing_config_parses_json(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(
        "AZURE_FINOPS_AI_PRICING_JSON",
        '{"providers":{"ollama":{"input_per_1k_tokens":0,"output_per_1k_tokens":0,"currency":"USD"}}}',
    )

    config = _reload_config()

    assert config.AZURE_FINOPS_AI_PRICING["providers"]["ollama"]["currency"] == "USD"


def test_ai_team_mapping_config_parses_json(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(
        "AZURE_FINOPS_AI_TEAM_MAPPINGS_JSON",
        (
            '{"feature_surfaces":{"ticket_auto_triage":"Service Desk"},'
            '"app_surfaces":{"azure_portal":"FinOps"},'
            '"actor_ids":{"azure-alerts":"FinOps"}}'
        ),
    )

    config = _reload_config()

    assert config.AZURE_FINOPS_AI_TEAM_MAPPINGS["feature_surfaces"]["ticket_auto_triage"] == "Service Desk"
    assert config.AZURE_FINOPS_AI_TEAM_MAPPINGS["app_surfaces"]["azure_portal"] == "FinOps"
    assert config.AZURE_FINOPS_AI_TEAM_MAPPINGS["actor_ids"]["azure-alerts"] == "FinOps"


def test_safe_script_hook_config_parses_json(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(
        "AZURE_FINOPS_SAFE_SCRIPT_HOOKS_JSON",
        (
            '{"vm_echo":{"label":"VM Echo","command":["python3","/app/backend/scripts/azure_finops_safe_hook_echo.py"],'
            '"allowed_categories":["compute"],"allowed_opportunity_types":["rightsizing"],"default_dry_run":true}}'
        ),
    )

    config = _reload_config()

    assert config.AZURE_FINOPS_SAFE_SCRIPT_HOOKS["vm_echo"]["label"] == "VM Echo"
