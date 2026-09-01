"""Hourly Exchange Online quarantine auto-release job for trusted domains.

Runs as a leader-only background service. No test-mode/dry-run concept:
enabled=false means the job does nothing and writes no run row.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import uuid
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

    # ------------------------------------------------------------------
    # Run recording
    # ------------------------------------------------------------------

    def _record_release(
        self,
        *,
        run_hour: str,
        message: dict[str, Any],
        status: str,
        error: str | None,
        conn: sqlite3.Connection,
    ) -> None:
        ph = self._placeholder()
        conn.execute(
            f"""INSERT INTO quarantine_releases
                (id, run_hour, message_identity, sender_address, recipient_address,
                 subject, received_at, quarantine_reason, status, error, released_at)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
            (
                uuid.uuid4().hex,
                run_hour,
                str(message.get("identity") or ""),
                str(message.get("sender_address") or ""),
                str(message.get("recipient_address") or ""),
                str(message.get("subject") or ""),
                str(message.get("received_at") or ""),
                str(message.get("quarantine_reason") or ""),
                status,
                error,
                _utcnow().isoformat(),
            ),
        )

    def _record_run(
        self,
        *,
        run_hour: str,
        domains: list[str],
        checked_count: int,
        released_count: int,
        failed_count: int,
        conn: sqlite3.Connection,
    ) -> None:
        ph = self._placeholder()
        conn.execute(
            f"""INSERT INTO quarantine_release_runs
                (run_hour, ran_at, domains_checked, checked_count, released_count, failed_count)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph})""",
            (run_hour, _utcnow().isoformat(), ",".join(domains), checked_count, released_count, failed_count),
        )

    async def run_hourly_job(self) -> None:
        import user_admin_providers as _uap_module

        current_hour = _utcnow().replace(minute=0, second=0, microsecond=0)
        run_hour = current_hour.strftime("%Y-%m-%dT%H:00:00Z")

        with self._conn() as conn:
            if self._already_ran_this_hour(run_hour, conn):
                return

        settings = self._get_settings()
        if not settings["enabled"]:
            return
        domains = settings["allowed_domains"]
        if not domains:
            return

        exchange = _uap_module.user_admin_providers.mailbox.exchange_powershell
        loop = asyncio.get_event_loop()

        try:
            messages = await loop.run_in_executor(None, lambda: exchange.list_quarantine_messages(domains))
        except Exception:
            logger.exception("Quarantine release job: failed to list quarantine messages")
            return

        released = 0
        failed = 0
        for message in messages:
            identity = str(message.get("identity") or "").strip()
            if not identity:
                continue
            try:
                await loop.run_in_executor(None, lambda: exchange.release_quarantine_message(identity))
                status, error = "released", None
                released += 1
            except Exception as exc:
                status, error = "failed", str(exc)
                failed += 1
            with self._conn() as conn:
                self._record_release(run_hour=run_hour, message=message, status=status, error=error, conn=conn)

        with self._conn() as conn:
            self._record_run(
                run_hour=run_hour,
                domains=domains,
                checked_count=len(messages),
                released_count=released,
                failed_count=failed,
                conn=conn,
            )

        logger.info(
            "Quarantine release job: run %s complete — %d checked, %d released, %d failed",
            run_hour, len(messages), released, failed,
        )


quarantine_release_job = QuarantineReleaseJob()
