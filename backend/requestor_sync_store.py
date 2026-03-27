"""Durable storage for Office 365 requestor mirroring and Jira sync results."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_name_key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


class RequestorSyncStore:
    """SQLite-backed storage for requestor directory mirrors and sync history."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "requestor_sync.db")
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _sqlite_conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _conn(self):
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return self._sqlite_conn()

    def _backfill_from_sqlite_if_needed(self) -> None:
        if not self._use_postgres or not os.path.exists(self._db_path):
            return
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM directory_emails").fetchone()
            if row and int(row["count"]) > 0:
                return
        with self._sqlite_conn() as sqlite_conn:
            directory_rows = sqlite_conn.execute("SELECT * FROM directory_emails").fetchall()
            link_rows = sqlite_conn.execute("SELECT * FROM jira_requestor_links").fetchall()
        with self._conn() as conn:
            if directory_rows:
                conn.executemany(
                    """
                    INSERT INTO directory_emails (
                        email_key, entra_user_id, display_name, canonical_email, account_class, source_kind, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(email_key, entra_user_id, source_kind) DO NOTHING
                    """,
                    [
                        (
                            row["email_key"],
                            row["entra_user_id"],
                            row["display_name"],
                            row["canonical_email"],
                            row["account_class"],
                            row["source_kind"],
                            row["updated_at"],
                        )
                        for row in directory_rows
                    ],
                )
            if link_rows:
                conn.executemany(
                    """
                    INSERT INTO jira_requestor_links (
                        email_key, ticket_key, extracted_email, directory_user_id, directory_display_name,
                        canonical_email, jira_account_id, jira_display_name, match_source, sync_status, message,
                        first_seen_at, last_seen_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(email_key, ticket_key) DO NOTHING
                    """,
                    [
                        (
                            row["email_key"],
                            row["ticket_key"],
                            row["extracted_email"],
                            row["directory_user_id"],
                            row["directory_display_name"],
                            row["canonical_email"],
                            row["jira_account_id"],
                            row["jira_display_name"],
                            row["match_source"],
                            row["sync_status"],
                            row["message"],
                            row["first_seen_at"],
                            row["last_seen_at"],
                        )
                        for row in link_rows
                    ],
                )

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            self._backfill_from_sqlite_if_needed()
            return
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
                    match_source TEXT NOT NULL DEFAULT '',
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
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(jira_requestor_links)").fetchall()
            }
            if "match_source" not in columns:
                conn.execute(
                    "ALTER TABLE jira_requestor_links ADD COLUMN match_source TEXT NOT NULL DEFAULT ''"
                )
            conn.commit()

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
                        (
                            """
                            INSERT INTO directory_emails (
                                email_key,
                                entra_user_id,
                                display_name,
                                canonical_email,
                                account_class,
                                source_kind,
                                updated_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """
                            if self._use_postgres
                            else
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
                            """
                        ),
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
                WHERE email_key = %s
                ORDER BY canonical_email ASC, display_name ASC, entra_user_id ASC
                """,
                (normalized,),
            ).fetchall() if self._use_postgres else conn.execute(
                """
                SELECT email_key, entra_user_id, display_name, canonical_email, account_class, source_kind, updated_at
                FROM directory_emails
                WHERE email_key = ?
                ORDER BY canonical_email ASC, display_name ASC, entra_user_id ASC
                """,
                (normalized,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_directory_matches_by_display_name(self, display_name: str) -> list[dict[str, Any]]:
        normalized = _normalize_name_key(display_name)
        if not normalized:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT email_key, entra_user_id, display_name, canonical_email, account_class, source_kind, updated_at
                FROM directory_emails
                WHERE display_name <> ''
                ORDER BY canonical_email ASC, display_name ASC, entra_user_id ASC, source_kind ASC
                """
            ).fetchall()
        return [dict(row) for row in rows if _normalize_name_key(row["display_name"]) == normalized]

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
        match_source: str = "",
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
                        match_source,
                        sync_status,
                        message,
                        first_seen_at,
                        last_seen_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(email_key, ticket_key) DO UPDATE SET
                        extracted_email=excluded.extracted_email,
                        directory_user_id=excluded.directory_user_id,
                        directory_display_name=excluded.directory_display_name,
                        canonical_email=excluded.canonical_email,
                        jira_account_id=excluded.jira_account_id,
                        jira_display_name=excluded.jira_display_name,
                        match_source=excluded.match_source,
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
                        str(match_source or "").strip(),
                        str(sync_status or "").strip(),
                        str(message or "").strip(),
                        now,
                        now,
                    ),
                ) if self._use_postgres else conn.execute(
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
                        match_source,
                        sync_status,
                        message,
                        first_seen_at,
                        last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(email_key, ticket_key) DO UPDATE SET
                        extracted_email=excluded.extracted_email,
                        directory_user_id=excluded.directory_user_id,
                        directory_display_name=excluded.directory_display_name,
                        canonical_email=excluded.canonical_email,
                        jira_account_id=excluded.jira_account_id,
                        jira_display_name=excluded.jira_display_name,
                        match_source=excluded.match_source,
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
                        str(match_source or "").strip(),
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
                WHERE ticket_key = %s
                ORDER BY last_seen_at DESC
                LIMIT 1
                """,
                (normalized_ticket,),
            ).fetchone() if self._use_postgres else conn.execute(
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
                WHERE email_key = %s
                  AND jira_account_id <> ''
                ORDER BY last_seen_at DESC
                LIMIT 1
                """,
                (normalized,),
            ).fetchone() if self._use_postgres else conn.execute(
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
            LIMIT {'%s' if self._use_postgres else '?'}
        """
        params.append(max(1, int(limit)))
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


requestor_sync_store = RequestorSyncStore()
