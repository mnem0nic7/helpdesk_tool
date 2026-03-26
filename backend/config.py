"""Configuration loader for the OIT Helpdesk Dashboard backend."""

import json
import os
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

# Load .env from the backend directory
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

JIRA_EMAIL: str = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN: str = os.getenv("JIRA_API_TOKEN", "")
JIRA_BASE_URL: str = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_PROJECT: str = os.getenv("JIRA_PROJECT", "OIT")


def _env_custom_field_id(name: str) -> str:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ""
    if raw.startswith("customfield_"):
        return raw
    if raw.isdigit():
        return f"customfield_{raw}"
    return raw


def _env_csv(name: str) -> list[str]:
    return [part.strip() for part in os.getenv(name, "").split(",") if part.strip()]


def _env_auth_provider(name: str, default: str) -> str:
    raw = os.getenv(name, default).strip().lower()
    if raw in {"entra", "atlassian"}:
        return raw
    return default


_REQUESTOR_OCC_NAME_DOMAIN_PRIORITY_DEFAULT = [
    "librasolutionsgroup.com",
    "oasisfinancial.com",
    "probateadvance.com",
    "movedocs.com",
    "mdunderwriting.com",
    "oasislegal.com",
    "atticusbilling.com",
    "medchex.org",
    "medicallegalsolutions.net",
    "medlienlegal.com",
    "medport.com",
    "myoasis.com",
    "omni-healthcare.com",
    "omniglofin.com",
    "omnihealthcare.org",
    "peak-fundinggroup.com",
    "accidentmeds.com",
    "benefitresource.com",
    "canyonmedicalbilling.com",
    "chirocapital.com",
    "chirocapital.net",
    "cliqfund.com",
    "encytemanagement.com",
    "globalrecservices.com",
    "glofin.com",
    "grsfunding.com",
    "injuryfinance.com",
    "injuryfinance.net",
    "injuryfinance.us",
    "injuryfinance.us.com",
    "keyhealth.net",
    "radnetpiservicing.com",
    "relieffunding.com",
    "syndeocare.com",
    "thetriosolution.com",
    "thetriosolutions.com",
    "oasisfinanciallytn.onmicrosoft.com",
]


TRACKED_JIRA_PROJECT_KEYS: list[str] = [
    key.strip().upper()
    for key in (_env_csv("TRACKED_JIRA_PROJECT_KEYS") or [JIRA_PROJECT])
    if key.strip()
]


JIRA_FOLLOWUP_LAST_PUBLIC_AGENT_TOUCH_FIELD_ID: str = _env_custom_field_id(
    "JIRA_FOLLOWUP_LAST_PUBLIC_AGENT_TOUCH_FIELD_ID"
)
JIRA_FOLLOWUP_PUBLIC_AGENT_TOUCH_COUNT_FIELD_ID: str = _env_custom_field_id(
    "JIRA_FOLLOWUP_PUBLIC_AGENT_TOUCH_COUNT_FIELD_ID"
)
JIRA_FOLLOWUP_STATUS_FIELD_ID: str = _env_custom_field_id("JIRA_FOLLOWUP_STATUS_FIELD_ID")
JIRA_FOLLOWUP_BREACHED_AT_FIELD_ID: str = _env_custom_field_id("JIRA_FOLLOWUP_BREACHED_AT_FIELD_ID")
JIRA_FOLLOWUP_AGENT_GROUPS: list[str] = _env_csv("JIRA_FOLLOWUP_AGENT_GROUPS")
JIRA_FOLLOWUP_CUSTOM_FIELD_IDS: list[str] = [
    field_id
    for field_id in (
        JIRA_FOLLOWUP_LAST_PUBLIC_AGENT_TOUCH_FIELD_ID,
        JIRA_FOLLOWUP_PUBLIC_AGENT_TOUCH_COUNT_FIELD_ID,
        JIRA_FOLLOWUP_STATUS_FIELD_ID,
        JIRA_FOLLOWUP_BREACHED_AT_FIELD_ID,
    )
    if field_id
]
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
PRIMARY_AUTH_PROVIDER: str = _env_auth_provider("PRIMARY_AUTH_PROVIDER", "atlassian")
OASISDEV_AUTH_PROVIDER: str = _env_auth_provider("OASISDEV_AUTH_PROVIDER", "atlassian")
AZURE_AUTH_PROVIDER: str = _env_auth_provider("AZURE_AUTH_PROVIDER", "entra")

# AI provider API keys
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# Microsoft Entra ID (Azure AD) authentication
ENTRA_TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID: str = os.getenv("ENTRA_CLIENT_ID", "")
ENTRA_CLIENT_SECRET: str = os.getenv("ENTRA_CLIENT_SECRET", "")
ALLOWED_USERS: str = os.getenv("ALLOWED_USERS", "")  # comma-separated emails, empty = all
ADMIN_USERS: str = os.getenv("ADMIN_USERS", "")  # comma-separated emails for write operations, empty = all authenticated

# Atlassian OAuth for user-on-behalf-of Jira writes
ATLASSIAN_CLIENT_ID: str = os.getenv("ATLASSIAN_CLIENT_ID", "").strip()
ATLASSIAN_CLIENT_SECRET: str = os.getenv("ATLASSIAN_CLIENT_SECRET", "").strip()
ATLASSIAN_ALLOWED_SITE_URL: str = (
    os.getenv("ATLASSIAN_ALLOWED_SITE_URL", JIRA_BASE_URL).strip().rstrip("/") or JIRA_BASE_URL
)
ATLASSIAN_TOKEN_ENCRYPTION_KEY: str = os.getenv("ATLASSIAN_TOKEN_ENCRYPTION_KEY", "").strip()
ATLASSIAN_ACCESS_GROUPS: list[str] = _env_csv("ATLASSIAN_ACCESS_GROUPS") or [
    "jira-servicemanagement-users-keyjira",
    "MoveDocs Service Desk Agents",
]
ATLASSIAN_ADMIN_GROUPS: list[str] = _env_csv("ATLASSIAN_ADMIN_GROUPS") or [
    "MoveDocs Service Desk Agents",
]
TOOLS_ALLOWED_IDENTIFIERS: list[str] = _env_csv("TOOLS_ALLOWED_IDENTIFIERS") or [
    "gallison",
    "wberry",
]
REQUESTOR_OCC_NAME_DOMAIN_PRIORITY: list[str] = [
    domain.lower()
    for domain in (_env_csv("REQUESTOR_OCC_NAME_DOMAIN_PRIORITY") or _REQUESTOR_OCC_NAME_DOMAIN_PRIORITY_DEFAULT)
    if domain.strip()
]
REQUESTOR_IGNORED_EMAILS: list[str] = [
    email.lower()
    for email in (
        _env_csv("REQUESTOR_IGNORED_EMAILS") or ["emailquarantine@librasolutionsgroup.com"]
    )
    if email.strip()
]


AuthProvider = Literal["entra", "atlassian"]


def get_auth_provider_for_scope(scope: str) -> AuthProvider:
    normalized = (scope or "").strip().lower()
    if normalized == "azure":
        return AZURE_AUTH_PROVIDER  # type: ignore[return-value]
    if normalized == "oasisdev":
        return OASISDEV_AUTH_PROVIDER  # type: ignore[return-value]
    return PRIMARY_AUTH_PROVIDER  # type: ignore[return-value]


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
REPORT_AI_SUMMARY_MODEL: str = os.getenv("REPORT_AI_SUMMARY_MODEL", OLLAMA_MODEL).strip() or OLLAMA_MODEL
TECHNICIAN_SCORE_POLL_INTERVAL_MINUTES: int = int(os.getenv("TECHNICIAN_SCORE_POLL_INTERVAL_MINUTES", "60"))
REPORT_AI_SUMMARY_NIGHTLY_HOUR_UTC: int = int(os.getenv("REPORT_AI_SUMMARY_NIGHTLY_HOUR_UTC", "6"))


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
ONEDRIVE_COPY_BATCH_SIZE: int = int(os.getenv("ONEDRIVE_COPY_BATCH_SIZE", "10"))
ONEDRIVE_COPY_MAX_RETRIES: int = int(os.getenv("ONEDRIVE_COPY_MAX_RETRIES", "5"))
ONEDRIVE_COPY_RETRY_DELAY_BASE_SECONDS: int = int(
    os.getenv("ONEDRIVE_COPY_RETRY_DELAY_BASE_SECONDS", "10")
)
ONEDRIVE_COPY_JOB_RETENTION_DAYS: int = int(os.getenv("ONEDRIVE_COPY_JOB_RETENTION_DAYS", "14"))
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
