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
