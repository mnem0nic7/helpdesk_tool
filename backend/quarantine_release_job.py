"""Hourly Exchange Online quarantine auto-release job for trusted domains.

Runs as a leader-only background service. No test-mode/dry-run concept:
enabled=false means the job does nothing and writes no run row.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR, QUARANTINE_RELEASE_DEFAULT_DOMAINS
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(DATA_DIR, "quarantine_release.db")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_domains(text: str | None) -> list[str]:
    if not text:
        return []
    domains: list[str] = []
    for part in str(text).split(","):
        domain = part.strip().lower()
        if domain and domain not in domains:
            domains.append(domain)
    return domains


class QuarantineReleaseJob:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._bg_task = None
        self._init_db()

    # ------------------------------------------------------------------
    # Schema
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
                CREATE TABLE IF NOT EXISTS quarantine_release_settings (
                    id              INTEGER PRIMARY KEY DEFAULT 1,
                    enabled         SMALLINT NOT NULL DEFAULT 0,
                    allowed_domains TEXT NOT NULL DEFAULT '',
                    updated_at      TEXT NOT NULL DEFAULT '',
                    updated_by      TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quarantine_release_runs (
                    run_hour        TEXT PRIMARY KEY,
                    ran_at          TEXT NOT NULL,
                    domains_checked TEXT NOT NULL,
                    checked_count   INTEGER NOT NULL DEFAULT 0,
                    released_count  INTEGER NOT NULL DEFAULT 0,
                    failed_count    INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quarantine_releases (
                    id                TEXT PRIMARY KEY,
                    run_hour          TEXT NOT NULL,
                    message_identity  TEXT NOT NULL,
                    sender_address    TEXT NOT NULL,
                    recipient_address TEXT NOT NULL,
                    subject           TEXT NOT NULL DEFAULT '',
                    received_at       TEXT NOT NULL DEFAULT '',
                    quarantine_reason TEXT NOT NULL DEFAULT '',
                    status            TEXT NOT NULL,
                    error             TEXT,
                    released_at       TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_qr_run_hour
                    ON quarantine_releases (run_hour)
            """)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _get_settings(self) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT enabled, allowed_domains FROM quarantine_release_settings WHERE id = 1"
            ).fetchone()
            if row is None:
                ph = self._placeholder()
                conn.execute(
                    f"INSERT INTO quarantine_release_settings "
                    f"(id, enabled, allowed_domains, updated_at, updated_by) "
                    f"VALUES (1, 0, {ph}, {ph}, {ph})",
                    (QUARANTINE_RELEASE_DEFAULT_DOMAINS, _utcnow().isoformat(), "system"),
                )
                return {"enabled": False, "allowed_domains": _parse_domains(QUARANTINE_RELEASE_DEFAULT_DOMAINS)}
        return {"enabled": bool(row["enabled"]), "allowed_domains": _parse_domains(row["allowed_domains"])}

    # ------------------------------------------------------------------
    # Run gating
    # ------------------------------------------------------------------

    def _already_ran_this_hour(self, run_hour: str, conn: sqlite3.Connection) -> bool:
        ph = self._placeholder()
        row = conn.execute(
            f"SELECT 1 FROM quarantine_release_runs WHERE run_hour = {ph}",
            (run_hour,),
        ).fetchone()
        return row is not None


quarantine_release_job = QuarantineReleaseJob()
