"""Durable storage for Office 365 requestor mirroring and Jira sync results."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RequestorSyncStore:
    """SQLite-backed storage for requestor directory mirrors and sync history."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "requestor_sync.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS directory_emails (
                    email_key TEXT NOT NULL,
                    entra_user_id TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    canonical_email TEXT NOT NULL DEFAULT '',
                    account_class TEXT NOT NULL DEFAULT '',
                    source_kind TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (email_key, entra_user_id, source_kind)
                );

                CREATE TABLE IF NOT EXISTS jira_requestor_links (
                    email_key TEXT NOT NULL DEFAULT '',
                    ticket_key TEXT NOT NULL,
                    extracted_email TEXT NOT NULL DEFAULT '',
                    directory_user_id TEXT NOT NULL DEFAULT '',
                    directory_display_name TEXT NOT NULL DEFAULT '',
                    canonical_email TEXT NOT NULL DEFAULT '',
                    jira_account_id TEXT NOT NULL DEFAULT '',
                    jira_display_name TEXT NOT NULL DEFAULT '',
                    sync_status TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (email_key, ticket_key)
                );

                CREATE INDEX IF NOT EXISTS idx_directory_emails_key
                    ON directory_emails (email_key, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_requestor_links_ticket
                    ON jira_requestor_links (ticket_key, last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS idx_requestor_links_email
                    ON jira_requestor_links (email_key, last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS idx_requestor_links_status
                    ON jira_requestor_links (sync_status, last_seen_at DESC);
                """
            )

    def replace_directory_emails(self, entries: list[dict[str, str]]) -> None:
        timestamp = _utcnow_iso()
        rows = [
            (
                str(item.get("email_key") or "").strip().lower(),
                str(item.get("entra_user_id") or "").strip(),
                str(item.get("display_name") or "").strip(),
                str(item.get("canonical_email") or "").strip().lower(),
                str(item.get("account_class") or "").strip(),
                str(item.get("source_kind") or "").strip(),
                timestamp,
            )
            for item in entries
            if str(item.get("email_key") or "").strip()
            and str(item.get("entra_user_id") or "").strip()
        ]
        with self._lock:
            with self._conn() as conn:
                conn.execute("DELETE FROM directory_emails")
                if rows:
                    conn.executemany(
                        """
                        INSERT INTO directory_emails (
                            email_key,
                            entra_user_id,
                            display_name,
                            canonical_email,
                            account_class,
                            source_kind,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
                conn.commit()

    def get_directory_matches(self, email_key: str) -> list[dict[str, Any]]:
        normalized = str(email_key or "").strip().lower()
        if not normalized:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT email_key, entra_user_id, display_name, canonical_email, account_class, source_kind, updated_at
                FROM directory_emails
                WHERE email_key = ?
                ORDER BY canonical_email ASC, display_name ASC, entra_user_id ASC
                """,
                (normalized,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_requestor_link(
        self,
        *,
        email_key: str,
        ticket_key: str,
        extracted_email: str,
        directory_user_id: str = "",
        directory_display_name: str = "",
        canonical_email: str = "",
        jira_account_id: str = "",
        jira_display_name: str = "",
        sync_status: str,
        message: str,
    ) -> None:
        normalized_key = str(email_key or "").strip().lower()
        normalized_ticket = str(ticket_key or "").strip().upper()
        if not normalized_ticket:
            return
        now = _utcnow_iso()
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO jira_requestor_links (
                        email_key,
                        ticket_key,
                        extracted_email,
                        directory_user_id,
                        directory_display_name,
                        canonical_email,
                        jira_account_id,
                        jira_display_name,
                        sync_status,
                        message,
                        first_seen_at,
                        last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(email_key, ticket_key) DO UPDATE SET
                        extracted_email=excluded.extracted_email,
                        directory_user_id=excluded.directory_user_id,
                        directory_display_name=excluded.directory_display_name,
                        canonical_email=excluded.canonical_email,
                        jira_account_id=excluded.jira_account_id,
                        jira_display_name=excluded.jira_display_name,
                        sync_status=excluded.sync_status,
                        message=excluded.message,
                        last_seen_at=excluded.last_seen_at
                    """,
                    (
                        normalized_key,
                        normalized_ticket,
                        str(extracted_email or "").strip().lower(),
                        str(directory_user_id or "").strip(),
                        str(directory_display_name or "").strip(),
                        str(canonical_email or "").strip().lower(),
                        str(jira_account_id or "").strip(),
                        str(jira_display_name or "").strip(),
                        str(sync_status or "").strip(),
                        str(message or "").strip(),
                        now,
                        now,
                    ),
                )
                conn.commit()

    def get_ticket_state(self, ticket_key: str) -> dict[str, Any] | None:
        normalized_ticket = str(ticket_key or "").strip().upper()
        if not normalized_ticket:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM jira_requestor_links
                WHERE ticket_key = ?
                ORDER BY last_seen_at DESC
                LIMIT 1
                """,
                (normalized_ticket,),
            ).fetchone()
        return dict(row) if row else None

    def get_recent_success_for_email(self, email_key: str) -> dict[str, Any] | None:
        normalized = str(email_key or "").strip().lower()
        if not normalized:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM jira_requestor_links
                WHERE email_key = ?
                  AND jira_account_id <> ''
                ORDER BY last_seen_at DESC
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
        return dict(row) if row else None

    def has_recent_ticket_state(self, ticket_key: str, *, max_age_minutes: int = 60) -> bool:
        state = self.get_ticket_state(ticket_key)
        if not state:
            return False
        try:
            last_seen = datetime.fromisoformat(str(state.get("last_seen_at") or ""))
        except ValueError:
            return False
        age_seconds = (datetime.now(timezone.utc) - last_seen.astimezone(timezone.utc)).total_seconds()
        return age_seconds <= max_age_minutes * 60

    def list_recent_status(self, *, limit: int = 100, failures_only: bool = False) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if failures_only:
            clauses.append("jira_account_id = ''")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT *
            FROM jira_requestor_links
            {where_sql}
            ORDER BY last_seen_at DESC
            LIMIT ?
        """
        params.append(max(1, int(limit)))
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


requestor_sync_store = RequestorSyncStore()
