"""Configuration loader for the OIT Helpdesk Dashboard backend."""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the backend directory
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

JIRA_EMAIL: str = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN: str = os.getenv("JIRA_API_TOKEN", "")
JIRA_BASE_URL: str = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_PROJECT: str = os.getenv("JIRA_PROJECT", "OIT")
AZURE_FINOPS_RECOMMENDATION_JIRA_PROJECT: str = (
    os.getenv("AZURE_FINOPS_RECOMMENDATION_JIRA_PROJECT", JIRA_PROJECT).strip() or JIRA_PROJECT
)
AZURE_FINOPS_RECOMMENDATION_JIRA_ISSUE_TYPE: str = (
    os.getenv("AZURE_FINOPS_RECOMMENDATION_JIRA_ISSUE_TYPE", "Task").strip() or "Task"
)
AZURE_FINOPS_RECOMMENDATION_TEAMS_WEBHOOK_URL: str = (
    os.getenv("AZURE_FINOPS_RECOMMENDATION_TEAMS_WEBHOOK_URL", "").strip()
)
AZURE_FINOPS_RECOMMENDATION_TEAMS_CHANNEL_LABEL: str = (
    os.getenv("AZURE_FINOPS_RECOMMENDATION_TEAMS_CHANNEL_LABEL", "FinOps").strip() or "FinOps"
)
DATA_DIR: str = os.getenv("DATA_DIR", "/app/data")
PRIMARY_APP_HOST: str = os.getenv("PRIMARY_APP_HOST", "it-app.movedocs.com")
OASISDEV_APP_HOST: str = os.getenv("OASISDEV_APP_HOST", "oasisdev.movedocs.com")
AZURE_APP_HOST: str = os.getenv("AZURE_APP_HOST", "azure.movedocs.com")

# AI provider API keys
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# Microsoft Entra ID (Azure AD) authentication
ENTRA_TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID: str = os.getenv("ENTRA_CLIENT_ID", "")
ENTRA_CLIENT_SECRET: str = os.getenv("ENTRA_CLIENT_SECRET", "")
ALLOWED_USERS: str = os.getenv("ALLOWED_USERS", "")  # comma-separated emails, empty = all
ADMIN_USERS: str = os.getenv("ADMIN_USERS", "")  # comma-separated emails for write operations, empty = all authenticated


def _is_test_runtime() -> bool:
    env = os.getenv("APP_ENV", "").strip().lower()
    return bool(os.getenv("PYTEST_CURRENT_TEST")) or env in {"test", "testing"}


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_json_object(name: str) -> dict[str, object]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{name} must decode to a JSON object")
    return payload


# Local AI provider (Ollama)
OLLAMA_ENABLED: bool = _env_bool("OLLAMA_ENABLED", "0")
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b").strip() or "qwen2.5:7b"
OLLAMA_FAST_MODEL: str = os.getenv("OLLAMA_FAST_MODEL", "qwen2.5:3b").strip() or "qwen2.5:3b"
OLLAMA_REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("OLLAMA_REQUEST_TIMEOUT_SECONDS", "300"))
OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "15m").strip() or "15m"

# Auto-triage and fast structured AI defaults
AUTO_TRIAGE_MODEL: str = os.getenv("AUTO_TRIAGE_MODEL", OLLAMA_FAST_MODEL).strip() or OLLAMA_FAST_MODEL
TECHNICIAN_SCORE_MODEL: str = os.getenv("TECHNICIAN_SCORE_MODEL", OLLAMA_FAST_MODEL).strip() or OLLAMA_FAST_MODEL
AZURE_ALERT_RULE_MODEL: str = os.getenv("AZURE_ALERT_RULE_MODEL", OLLAMA_FAST_MODEL).strip() or OLLAMA_FAST_MODEL
TECHNICIAN_SCORE_POLL_INTERVAL_MINUTES: int = int(os.getenv("TECHNICIAN_SCORE_POLL_INTERVAL_MINUTES", "60"))


def _load_app_secret_key() -> str:
    configured = os.getenv("APP_SECRET_KEY", "").strip()
    if not configured:
        if _is_test_runtime():
            return "test-secret-key"
        raise RuntimeError("APP_SECRET_KEY must be set to a strong random value before starting the app.")
    if configured == "change-me-in-production" and not _is_test_runtime():
        raise RuntimeError(
            "APP_SECRET_KEY is using the insecure placeholder value. Set a strong random secret before starting the app."
        )
    return configured


APP_SECRET_KEY: str = _load_app_secret_key()

# Azure portal integration
AZURE_ROOT_MANAGEMENT_GROUP_ID: str = os.getenv("AZURE_ROOT_MANAGEMENT_GROUP_ID", "")
AZURE_INVENTORY_REFRESH_MINUTES: int = int(os.getenv("AZURE_INVENTORY_REFRESH_MINUTES", "15"))
AZURE_DIRECTORY_REFRESH_MINUTES: int = int(os.getenv("AZURE_DIRECTORY_REFRESH_MINUTES", "15"))
AZURE_COST_REFRESH_MINUTES: int = int(os.getenv("AZURE_COST_REFRESH_MINUTES", "60"))
AZURE_COST_LOOKBACK_DAYS: int = int(os.getenv("AZURE_COST_LOOKBACK_DAYS", "30"))
AZURE_VM_EXPORT_RETENTION_DAYS: int = int(os.getenv("AZURE_VM_EXPORT_RETENTION_DAYS", "7"))
AZURE_VM_EXPORT_COST_CHUNK_SIZE: int = int(os.getenv("AZURE_VM_EXPORT_COST_CHUNK_SIZE", "5"))
AZURE_VM_EXPORT_COST_INTER_CHUNK_DELAY_SECONDS: float = float(
    os.getenv("AZURE_VM_EXPORT_COST_INTER_CHUNK_DELAY_SECONDS", "2")
)
AZURE_VM_EXPORT_MAX_RUNTIME_MINUTES: int = int(os.getenv("AZURE_VM_EXPORT_MAX_RUNTIME_MINUTES", "45"))
AZURE_VM_EXPORT_RETRY_BUFFER_SECONDS: int = int(os.getenv("AZURE_VM_EXPORT_RETRY_BUFFER_SECONDS", "2"))
AZURE_VM_EXPORT_SHARED_MAX_RUNTIME_SECONDS: int = int(
    os.getenv("AZURE_VM_EXPORT_SHARED_MAX_RUNTIME_SECONDS", "90")
)
AZURE_COST_INTER_QUERY_DELAY_SECONDS: float = float(os.getenv("AZURE_COST_INTER_QUERY_DELAY_SECONDS", "2"))
AZURE_COST_MAX_RETRIES: int = int(os.getenv("AZURE_COST_MAX_RETRIES", "5"))
AZURE_COST_EXPORTS_ENABLED: bool = _env_bool("AZURE_COST_EXPORTS_ENABLED", "0")
AZURE_COST_EXPORT_ROOT: str = os.getenv("AZURE_COST_EXPORT_ROOT", os.path.join(DATA_DIR, "azure_cost_exports"))
AZURE_COST_EXPORT_DATASETS: str = os.getenv("AZURE_COST_EXPORT_DATASETS", "FOCUS")
AZURE_COST_EXPORT_MANIFEST_DB_PATH: str = os.getenv(
    "AZURE_COST_EXPORT_MANIFEST_DB_PATH",
    os.path.join(DATA_DIR, "azure_export_deliveries.db"),
)
AZURE_FINOPS_DUCKDB_PATH: str = os.getenv(
    "AZURE_FINOPS_DUCKDB_PATH",
    os.path.join(DATA_DIR, "azure_finops.duckdb"),
)
AZURE_FINOPS_AI_PRICING: dict[str, object] = _env_json_object("AZURE_FINOPS_AI_PRICING_JSON")
AZURE_FINOPS_AI_TEAM_MAPPINGS: dict[str, object] = _env_json_object("AZURE_FINOPS_AI_TEAM_MAPPINGS_JSON")
AZURE_FINOPS_SAFE_SCRIPT_HOOKS: dict[str, object] = _env_json_object("AZURE_FINOPS_SAFE_SCRIPT_HOOKS_JSON")
AZURE_COST_EXPORT_STAGING_DIR: str = os.getenv(
    "AZURE_COST_EXPORT_STAGING_DIR",
    os.path.join(DATA_DIR, "azure_cost_exports", "_staged"),
)
AZURE_COST_EXPORT_QUARANTINE_DIR: str = os.getenv(
    "AZURE_COST_EXPORT_QUARANTINE_DIR",
    os.path.join(DATA_DIR, "azure_cost_exports", "_quarantine"),
)
AZURE_COST_EXPORT_EXPECTED_CADENCE_HOURS: int = int(os.getenv("AZURE_COST_EXPORT_EXPECTED_CADENCE_HOURS", "24"))
AZURE_COST_EXPORT_POLL_INTERVAL_MINUTES: int = int(os.getenv("AZURE_COST_EXPORT_POLL_INTERVAL_MINUTES", "15"))
AZURE_VIRTUAL_DESKTOP_REMOVAL_THRESHOLD_DAYS: int = int(
    os.getenv("AZURE_VIRTUAL_DESKTOP_REMOVAL_THRESHOLD_DAYS", "14")
)
AZURE_AVD_SESSION_HISTORY_LOOKBACK_DAYS: int = int(
    os.getenv("AZURE_AVD_SESSION_HISTORY_LOOKBACK_DAYS", "90")
)
AZURE_REPORTING_POWER_BI_URL: str = os.getenv("AZURE_REPORTING_POWER_BI_URL", "").strip()
AZURE_REPORTING_POWER_BI_LABEL: str = os.getenv("AZURE_REPORTING_POWER_BI_LABEL", "Shared Cost Dashboard").strip()
AZURE_REPORTING_COST_ANALYSIS_URL: str = os.getenv("AZURE_REPORTING_COST_ANALYSIS_URL", "").strip()
AZURE_REPORTING_COST_ANALYSIS_LABEL: str = os.getenv(
    "AZURE_REPORTING_COST_ANALYSIS_LABEL",
    "Azure Cost Analysis",
).strip()
USER_EXIT_AGENT_SHARED_SECRET: str = os.getenv("USER_EXIT_AGENT_SHARED_SECRET", "")
USER_EXIT_AGENT_STEP_LEASE_SECONDS: int = int(os.getenv("USER_EXIT_AGENT_STEP_LEASE_SECONDS", "120"))
