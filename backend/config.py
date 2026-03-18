"""Configuration loader for the OIT Helpdesk Dashboard backend."""

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
DATA_DIR: str = os.getenv("DATA_DIR", "/app/data")
PRIMARY_APP_HOST: str = os.getenv("PRIMARY_APP_HOST", "it-app.movedocs.com")
OASISDEV_APP_HOST: str = os.getenv("OASISDEV_APP_HOST", "oasisdev.movedocs.com")
AZURE_APP_HOST: str = os.getenv("AZURE_APP_HOST", "azure.movedocs.com")

# AI provider API keys
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# Auto-triage model (runs automatically on new tickets during cache refresh)
AUTO_TRIAGE_MODEL: str = os.getenv("AUTO_TRIAGE_MODEL", "gpt-4o-mini")

# Microsoft Entra ID (Azure AD) authentication
ENTRA_TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID: str = os.getenv("ENTRA_CLIENT_ID", "")
ENTRA_CLIENT_SECRET: str = os.getenv("ENTRA_CLIENT_SECRET", "")
ALLOWED_USERS: str = os.getenv("ALLOWED_USERS", "")  # comma-separated emails, empty = all
ADMIN_USERS: str = os.getenv("ADMIN_USERS", "")  # comma-separated emails for write operations, empty = all authenticated
APP_SECRET_KEY: str = os.getenv("APP_SECRET_KEY", "change-me-in-production")

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
if APP_SECRET_KEY == "change-me-in-production":
    import warnings
    warnings.warn(
        "APP_SECRET_KEY is using the insecure default. Set it in .env for production.",
        stacklevel=1,
    )
