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
DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
DATABASE_CONNECT_TIMEOUT_SECONDS: int = int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "10"))
REDIS_URL: str = os.getenv("REDIS_URL", "").strip()
REDIS_NAMESPACE: str = os.getenv("REDIS_NAMESPACE", "altlassian").strip() or "altlassian"
STORAGE_DUAL_WRITE_SQLITE: bool = os.getenv("STORAGE_DUAL_WRITE_SQLITE", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
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
EXCHANGE_ONLINE_ORGANIZATION: str = os.getenv("EXCHANGE_ONLINE_ORGANIZATION", "").strip()
EXCHANGE_POWERSHELL_TIMEOUT_SECONDS: int = int(os.getenv("EXCHANGE_POWERSHELL_TIMEOUT_SECONDS", "240"))
EXCHANGE_DELEGATE_SCAN_TIMEOUT_SECONDS: int = int(
    os.getenv("EXCHANGE_DELEGATE_SCAN_TIMEOUT_SECONDS", str(max(EXCHANGE_POWERSHELL_TIMEOUT_SECONDS, 600)))
)
EMAILGISTICS_SYNC_TIMEOUT_SECONDS: int = int(
    os.getenv("EMAILGISTICS_SYNC_TIMEOUT_SECONDS", str(max(EXCHANGE_POWERSHELL_TIMEOUT_SECONDS, 1800)))
)
EMAILGISTICS_AUTH_MODE: str = os.getenv("EMAILGISTICS_AUTH_MODE", "client_secret").strip().lower()
if EMAILGISTICS_AUTH_MODE not in {"client_secret", "certificate"}:
    EMAILGISTICS_AUTH_MODE = "client_secret"
EMAILGISTICS_TOKEN_VALID_URL: str = os.getenv("EMAILGISTICS_TOKEN_VALID_URL", "").strip()
EMAILGISTICS_USER_SYNC_URL: str = os.getenv("EMAILGISTICS_USER_SYNC_URL", "").strip()
EMAILGISTICS_AUTH_TOKEN: str = os.getenv("EMAILGISTICS_AUTH_TOKEN", "").strip()
EMAILGISTICS_TENANT_ID: str = os.getenv("EMAILGISTICS_TENANT_ID", ENTRA_TENANT_ID).strip()
EMAILGISTICS_APP_ID: str = os.getenv("EMAILGISTICS_APP_ID", ENTRA_CLIENT_ID).strip()
EMAILGISTICS_CLIENT_SECRET: str = os.getenv("EMAILGISTICS_CLIENT_SECRET", ENTRA_CLIENT_SECRET).strip()
EMAILGISTICS_ORGANIZATION_DOMAIN: str = (
    os.getenv("EMAILGISTICS_ORGANIZATION_DOMAIN", EXCHANGE_ONLINE_ORGANIZATION).strip()
)
EMAILGISTICS_CERTIFICATE_PATH: str = os.getenv("EMAILGISTICS_CERTIFICATE_PATH", "").strip()
EMAILGISTICS_CERTIFICATE_PASSWORD: str = os.getenv("EMAILGISTICS_CERTIFICATE_PASSWORD", "").strip()
EMAILGISTICS_CONFIGURED_MAILBOXES: list[str] = [
    mailbox.lower()
    for mailbox in _env_csv("EMAILGISTICS_CONFIGURED_MAILBOXES")
    if mailbox.strip()
]
EMAILGISTICS_SYNC_SECURITY_GROUPS: bool = os.getenv("EMAILGISTICS_SYNC_SECURITY_GROUPS", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
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
]  # deprecated; the Tools surface is available to all authenticated users
APP_RUNTIME_BLUEGREEN_ENABLED: bool = os.getenv("APP_RUNTIME_BLUEGREEN_ENABLED", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
APP_RUNTIME_COLOR: str = os.getenv("APP_RUNTIME_COLOR", "single").strip().lower() or "single"
APP_RUNTIME_LEASE_SECONDS: int = int(os.getenv("APP_RUNTIME_LEASE_SECONDS", "30"))
APP_RUNTIME_HEARTBEAT_SECONDS: int = int(os.getenv("APP_RUNTIME_HEARTBEAT_SECONDS", "5"))
DEPLOY_CONTROL_SECRET: str = os.getenv("DEPLOY_CONTROL_SECRET", "").strip()
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


def _default_azure_finops_duckdb_path() -> str:
    base_path = os.path.join(DATA_DIR, "azure_finops.duckdb")
    if not APP_RUNTIME_BLUEGREEN_ENABLED:
        return base_path
    if APP_RUNTIME_COLOR not in {"blue", "green"}:
        return base_path
    return os.path.join(DATA_DIR, f"azure_finops_{APP_RUNTIME_COLOR}.duckdb")


# Local AI provider (Ollama)
OLLAMA_ENABLED: bool = _env_bool("OLLAMA_ENABLED", "0")
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "nemotron-3-nano:4b").strip() or "nemotron-3-nano:4b"
OLLAMA_FAST_MODEL: str = (
    os.getenv("OLLAMA_FAST_MODEL", "nemotron-3-nano:4b").strip() or "nemotron-3-nano:4b"
)
OLLAMA_REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("OLLAMA_REQUEST_TIMEOUT_SECONDS", "300"))
OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "15m").strip() or "15m"
OLLAMA_SECURITY_ENABLED: bool = _env_bool(
    "OLLAMA_SECURITY_ENABLED",
    "1" if OLLAMA_ENABLED else "0",
)
OLLAMA_SECURITY_BASE_URL: str = os.getenv("OLLAMA_SECURITY_BASE_URL", OLLAMA_BASE_URL).rstrip("/")
OLLAMA_SECURITY_MODEL: str = os.getenv("OLLAMA_SECURITY_MODEL", OLLAMA_MODEL).strip() or OLLAMA_MODEL

# Secondary Ollama instance for load-sharing triage/QA (optional)
OLLAMA_SECONDARY_BASE_URL: str = os.getenv("OLLAMA_SECONDARY_BASE_URL", "").strip().rstrip("/")
OLLAMA_SECONDARY_ENABLED: bool = _env_bool("OLLAMA_SECONDARY_ENABLED", "1" if OLLAMA_SECONDARY_BASE_URL else "0")

# Auto-triage and fast structured AI defaults
AUTO_TRIAGE_MODEL: str = os.getenv("AUTO_TRIAGE_MODEL", OLLAMA_FAST_MODEL).strip() or OLLAMA_FAST_MODEL
TECHNICIAN_SCORE_MODEL: str = os.getenv("TECHNICIAN_SCORE_MODEL", OLLAMA_FAST_MODEL).strip() or OLLAMA_FAST_MODEL
AZURE_ALERT_RULE_MODEL: str = os.getenv("AZURE_ALERT_RULE_MODEL", OLLAMA_FAST_MODEL).strip() or OLLAMA_FAST_MODEL
REPORT_AI_SUMMARY_MODEL: str = os.getenv("REPORT_AI_SUMMARY_MODEL", OLLAMA_FAST_MODEL).strip() or OLLAMA_FAST_MODEL
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
AZURE_DEVICE_COMPLIANCE_REFRESH_MINUTES: int = int(os.getenv("AZURE_DEVICE_COMPLIANCE_REFRESH_MINUTES", "15"))
AZURE_CONDITIONAL_ACCESS_REFRESH_MINUTES: int = int(os.getenv("AZURE_CONDITIONAL_ACCESS_REFRESH_MINUTES", "15"))
AZURE_COST_REFRESH_MINUTES: int = int(os.getenv("AZURE_COST_REFRESH_MINUTES", "60"))
AZURE_DEFENDER_ALERT_CACHE_MINUTES: int = int(os.getenv("AZURE_DEFENDER_ALERT_CACHE_MINUTES", "5"))
AZURE_DEFENDER_AGENT_POLL_SECONDS: int = int(os.getenv("AZURE_DEFENDER_AGENT_POLL_SECONDS", "120"))
DEFENDER_AGENT_TEAMS_WEBHOOK_URL: str = os.getenv("DEFENDER_AGENT_TEAMS_WEBHOOK_URL", "").strip()
DEFENDER_AGENT_TEAMS_NOTIFY_T1: bool = os.getenv("DEFENDER_AGENT_TEAMS_NOTIFY_T1", "false").lower() == "true"
DEFENDER_AGENT_TEAMS_NOTIFY_T2: bool = os.getenv("DEFENDER_AGENT_TEAMS_NOTIFY_T2", "true").lower() == "true"
DEFENDER_AGENT_MAX_JOBS_PER_CYCLE: int = int(os.getenv("DEFENDER_AGENT_MAX_JOBS_PER_CYCLE", "10"))
AZURE_COST_LOOKBACK_DAYS: int = int(os.getenv("AZURE_COST_LOOKBACK_DAYS", "30"))
AZURE_CONDITIONAL_ACCESS_LOOKBACK_DAYS: int = int(os.getenv("AZURE_CONDITIONAL_ACCESS_LOOKBACK_DAYS", "30"))
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
MAILBOX_DELEGATE_SCAN_JOB_RETENTION_DAYS: int = int(os.getenv("MAILBOX_DELEGATE_SCAN_JOB_RETENTION_DAYS", "14"))
AZURE_COST_EXPORTS_ENABLED: bool = _env_bool("AZURE_COST_EXPORTS_ENABLED", "0")
AZURE_COST_EXPORT_ROOT: str = os.getenv("AZURE_COST_EXPORT_ROOT", os.path.join(DATA_DIR, "azure_cost_exports"))
AZURE_COST_EXPORT_DATASETS: str = os.getenv("AZURE_COST_EXPORT_DATASETS", "FOCUS")
AZURE_COST_EXPORT_MANIFEST_DB_PATH: str = os.getenv(
    "AZURE_COST_EXPORT_MANIFEST_DB_PATH",
    os.path.join(DATA_DIR, "azure_export_deliveries.db"),
)
AZURE_FINOPS_DUCKDB_PATH: str = os.getenv(
    "AZURE_FINOPS_DUCKDB_PATH",
    _default_azure_finops_duckdb_path(),
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
AZURE_VIRTUAL_DESKTOP_UTILIZATION_LOOKBACK_DAYS: int = int(
    os.getenv("AZURE_VIRTUAL_DESKTOP_UTILIZATION_LOOKBACK_DAYS", "7")
)
AZURE_VIRTUAL_DESKTOP_UNDERUTILIZED_THRESHOLD_PERCENT: float = float(
    os.getenv("AZURE_VIRTUAL_DESKTOP_UNDERUTILIZED_THRESHOLD_PERCENT", "50")
)
AZURE_VIRTUAL_DESKTOP_OVERUTILIZED_THRESHOLD_PERCENT: float = float(
    os.getenv("AZURE_VIRTUAL_DESKTOP_OVERUTILIZED_THRESHOLD_PERCENT", "100")
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


# On-premises Active Directory (LDAP)
AD_SERVER: str = os.getenv("AD_SERVER", "").strip()          # e.g. ldap://dc1.corp.local or ldaps://dc1.corp.local
AD_PORT: int = int(os.getenv("AD_PORT", "0"))                # 0 = auto (389 plain, 636 SSL)
AD_USE_SSL: bool = os.getenv("AD_USE_SSL", "").strip().lower() in {"1", "true", "yes"}
AD_BASE_DN: str = os.getenv("AD_BASE_DN", "").strip()        # e.g. DC=corp,DC=local
AD_BIND_DN: str = os.getenv("AD_BIND_DN", "").strip()        # e.g. CN=svc_account,OU=Service Accounts,DC=corp,DC=local
AD_BIND_PASSWORD: str = os.getenv("AD_BIND_PASSWORD", "").strip()
