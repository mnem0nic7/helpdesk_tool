"""AskHR/Benefits mailbox-to-Jira bot.

Runs as a leader-only background service. Polls the AskHR and Benefits
mailboxes, filters by trusted sender domain, and creates HRD Jira tickets
with AskHR/Benefits as reporter instead of the original external sender.
No test-mode/dry-run concept: enabled=false means the job does nothing.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from config import ASKHR_BOT_ENABLED_DEFAULT, DATA_DIR
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(DATA_DIR, "askhr_bot.db")

MAILBOXES: dict[str, dict[str, str]] = {
    "askhr": {"address": "AskHR@librasolutionsgroup.com", "request_type_id": "420"},
    "benefits": {"address": "Benefits@librasolutionsgroup.com", "request_type_id": "619"},
}
PAYROLL_BYPASS_SENDER = "payroll@librasolutionsgroup.com"
JSM_SERVICE_DESK_ID = "73"
JSM_PROJECT_KEY = "HRD"
REPORTER_ACCOUNT_IDS: dict[str, str] = {
    "askhr": "qm:43cd1b99-1808-44a4-95b1-09e2c82c645a:9528d568-c455-4457-9ce4-edd8d58b218c",
    "benefits": "qm:43cd1b99-1808-44a4-95b1-09e2c82c645a:5f896e59-af49-457a-a456-edaa7515d98a",
}

_TRANSPORT_RULE_IDENTITY = "Forward External Mail to Jira - AskHR"

_SETTINGS_FIELDS = (
    "enabled",
    "poll_interval_seconds",
    "lookback_minutes",
    "askhr_checkpoint_at",
    "benefits_checkpoint_at",
    "trusted_domains",
    "trusted_domains_refreshed_at",
    "domain_refresh_interval_seconds",
    "reporter_mode",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _settings_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "enabled": bool(row["enabled"]),
        "poll_interval_seconds": int(row["poll_interval_seconds"]),
        "lookback_minutes": int(row["lookback_minutes"]),
        "askhr_checkpoint_at": str(row["askhr_checkpoint_at"] or ""),
        "benefits_checkpoint_at": str(row["benefits_checkpoint_at"] or ""),
        "trusted_domains": json.loads(row["trusted_domains"] or "[]"),
        "trusted_domains_refreshed_at": str(row["trusted_domains_refreshed_at"] or ""),
        "domain_refresh_interval_seconds": int(row["domain_refresh_interval_seconds"]),
        "reporter_mode": str(row["reporter_mode"] or "unset"),
    }


class AskHrBotJob:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._bg_task = None
        self._init_db()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _sqlite_conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _conn(self) -> sqlite3.Connection:
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return self._sqlite_conn()

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            return
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS askhr_bot_settings (
                    id                              INTEGER PRIMARY KEY DEFAULT 1,
                    enabled                         SMALLINT NOT NULL DEFAULT 0,
                    poll_interval_seconds           INTEGER NOT NULL DEFAULT 120,
                    lookback_minutes                INTEGER NOT NULL DEFAULT 15,
                    askhr_checkpoint_at             TEXT NOT NULL DEFAULT '',
                    benefits_checkpoint_at          TEXT NOT NULL DEFAULT '',
                    trusted_domains                 TEXT NOT NULL DEFAULT '[]',
                    trusted_domains_refreshed_at    TEXT NOT NULL DEFAULT '',
                    domain_refresh_interval_seconds INTEGER NOT NULL DEFAULT 3600,
                    reporter_mode                   TEXT NOT NULL DEFAULT 'unset',
                    updated_at                      TEXT NOT NULL DEFAULT '',
                    updated_by                      TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS askhr_bot_runs (
                    id               TEXT PRIMARY KEY,
                    mailbox          TEXT NOT NULL,
                    run_started_at   TEXT NOT NULL,
                    messages_scanned INTEGER NOT NULL DEFAULT 0,
                    created_count    INTEGER NOT NULL DEFAULT 0,
                    skipped_count    INTEGER NOT NULL DEFAULT 0,
                    failed_count     INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS askhr_bot_messages (
                    internet_message_id TEXT PRIMARY KEY,
                    mailbox              TEXT NOT NULL,
                    graph_message_id     TEXT NOT NULL,
                    subject               TEXT NOT NULL DEFAULT '',
                    sender_email          TEXT NOT NULL DEFAULT '',
                    received_at           TEXT NOT NULL DEFAULT '',
                    status                TEXT NOT NULL,
                    jira_issue_key        TEXT,
                    error                 TEXT,
                    processed_at          TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_askhr_bot_messages_mailbox_received
                    ON askhr_bot_messages (mailbox, received_at)
            """)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _get_settings(self) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT enabled, poll_interval_seconds, lookback_minutes, askhr_checkpoint_at, "
                "benefits_checkpoint_at, trusted_domains, trusted_domains_refreshed_at, "
                "domain_refresh_interval_seconds, reporter_mode "
                "FROM askhr_bot_settings WHERE id = 1"
            ).fetchone()
            if row is None:
                ph = self._placeholder()
                defaults = (1, 1 if ASKHR_BOT_ENABLED_DEFAULT else 0, 120, 15, "", "", "[]", "", 3600, "unset",
                            _utcnow().isoformat(), "system")
                conn.execute(
                    f"INSERT INTO askhr_bot_settings "
                    f"(id, enabled, poll_interval_seconds, lookback_minutes, askhr_checkpoint_at, "
                    f"benefits_checkpoint_at, trusted_domains, trusted_domains_refreshed_at, "
                    f"domain_refresh_interval_seconds, reporter_mode, updated_at, updated_by) "
                    f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                    defaults,
                )
                return {
                    "enabled": bool(ASKHR_BOT_ENABLED_DEFAULT),
                    "poll_interval_seconds": 120,
                    "lookback_minutes": 15,
                    "askhr_checkpoint_at": "",
                    "benefits_checkpoint_at": "",
                    "trusted_domains": [],
                    "trusted_domains_refreshed_at": "",
                    "domain_refresh_interval_seconds": 3600,
                    "reporter_mode": "unset",
                }
        return _settings_row_to_dict(row)

    def _update_settings(self, *, updated_by: str = "system", **fields: Any) -> dict[str, Any]:
        current = self._get_settings()
        for key, value in fields.items():
            if key not in _SETTINGS_FIELDS:
                raise ValueError(f"Unknown settings field: {key}")
            current[key] = value
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO askhr_bot_settings "
                f"(id, enabled, poll_interval_seconds, lookback_minutes, askhr_checkpoint_at, "
                f"benefits_checkpoint_at, trusted_domains, trusted_domains_refreshed_at, "
                f"domain_refresh_interval_seconds, reporter_mode, updated_at, updated_by) "
                f"VALUES (1,{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph}) "
                f"ON CONFLICT (id) DO UPDATE SET "
                f"enabled = excluded.enabled, poll_interval_seconds = excluded.poll_interval_seconds, "
                f"lookback_minutes = excluded.lookback_minutes, askhr_checkpoint_at = excluded.askhr_checkpoint_at, "
                f"benefits_checkpoint_at = excluded.benefits_checkpoint_at, trusted_domains = excluded.trusted_domains, "
                f"trusted_domains_refreshed_at = excluded.trusted_domains_refreshed_at, "
                f"domain_refresh_interval_seconds = excluded.domain_refresh_interval_seconds, "
                f"reporter_mode = excluded.reporter_mode, updated_at = excluded.updated_at, "
                f"updated_by = excluded.updated_by",
                (
                    1 if current["enabled"] else 0,
                    current["poll_interval_seconds"],
                    current["lookback_minutes"],
                    current["askhr_checkpoint_at"],
                    current["benefits_checkpoint_at"],
                    json.dumps(current["trusted_domains"]),
                    current["trusted_domains_refreshed_at"],
                    current["domain_refresh_interval_seconds"],
                    current["reporter_mode"],
                    _utcnow().isoformat(),
                    updated_by,
                ),
            )
        return current
