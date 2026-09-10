"""Persistence for Teams retention policies, worker runs, and the per-item
deletion audit trail. Pure storage — no Graph calls live here."""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

_DB_PATH = os.path.join(DATA_DIR, "retention_policies.db")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class RetentionPolicyStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _sqlite_conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _conn(self):
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
                CREATE TABLE IF NOT EXISTS retention_policies (
                    id             TEXT PRIMARY KEY,
                    team_id        TEXT NOT NULL,
                    team_name      TEXT NOT NULL DEFAULT '',
                    channel_id     TEXT NOT NULL,
                    channel_name   TEXT NOT NULL DEFAULT '',
                    retention_days INTEGER NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'pending_preview',
                    created_by     TEXT NOT NULL DEFAULT '',
                    created_at     TEXT NOT NULL DEFAULT '',
                    updated_at     TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_retention_policies_channel
                    ON retention_policies (team_id, channel_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retention_runs (
                    id                  TEXT PRIMARY KEY,
                    policy_id           TEXT NOT NULL,
                    started_at          TEXT NOT NULL,
                    finished_at         TEXT,
                    outcome             TEXT NOT NULL DEFAULT 'running',
                    messages_deleted    INTEGER NOT NULL DEFAULT 0,
                    attachments_deleted INTEGER NOT NULL DEFAULT 0,
                    error               TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_retention_runs_policy
                    ON retention_runs (policy_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retention_deletions (
                    id                  TEXT PRIMARY KEY,
                    run_id              TEXT NOT NULL,
                    item_type           TEXT NOT NULL,
                    item_id             TEXT NOT NULL,
                    sender_or_author    TEXT NOT NULL DEFAULT '',
                    original_created_at TEXT NOT NULL DEFAULT '',
                    deleted_at          TEXT NOT NULL,
                    status              TEXT NOT NULL,
                    error               TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_retention_deletions_run
                    ON retention_deletions (run_id)
            """)

    # -- policies --

    def create_policy(
        self, *, team_id: str, team_name: str, channel_id: str, channel_name: str,
        retention_days: int, created_by: str,
    ) -> dict[str, Any]:
        ph = self._placeholder()
        policy_id = uuid.uuid4().hex
        now = _utcnow()
        with self._conn() as conn:
            conn.execute(
                f"""INSERT INTO retention_policies
                    (id, team_id, team_name, channel_id, channel_name, retention_days, status, created_by, created_at, updated_at)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},'pending_preview',{ph},{ph},{ph})""",
                (policy_id, team_id, team_name, channel_id, channel_name, retention_days, created_by, now, now),
            )
        policy = self.get_policy(policy_id)
        assert policy is not None
        return policy

    def get_policy(self, policy_id: str) -> dict[str, Any] | None:
        ph = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT id, team_id, team_name, channel_id, channel_name, retention_days, status, "
                f"created_by, created_at, updated_at FROM retention_policies WHERE id = {ph}",
                (policy_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_policy_for_channel(self, team_id: str, channel_id: str) -> dict[str, Any] | None:
        ph = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT id, team_id, team_name, channel_id, channel_name, retention_days, status, "
                f"created_by, created_at, updated_at FROM retention_policies "
                f"WHERE team_id = {ph} AND channel_id = {ph}",
                (team_id, channel_id),
            ).fetchone()
        return dict(row) if row else None

    def list_policies(self, *, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        ph = self._placeholder()
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) AS cnt FROM retention_policies").fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT id, team_id, team_name, channel_id, channel_name, retention_days, status, "
                f"created_by, created_at, updated_at FROM retention_policies "
                f"ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows], total

    def list_active_policies(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, team_id, team_name, channel_id, channel_name, retention_days, status, "
                "created_by, created_at, updated_at FROM retention_policies WHERE status = 'active'"
            ).fetchall()
        return [dict(r) for r in rows]

    def confirm_policy(self, policy_id: str) -> dict[str, Any] | None:
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE retention_policies SET status = 'active', updated_at = {ph} WHERE id = {ph}",
                (_utcnow(), policy_id),
            )
        return self.get_policy(policy_id)

    def update_policy(
        self, policy_id: str, *, retention_days: int | None = None, status: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_policy(policy_id)
        if not current:
            return None
        new_days = current["retention_days"] if retention_days is None else retention_days
        if retention_days is not None:
            new_status = "pending_preview"
        elif status is not None:
            new_status = status
        else:
            new_status = current["status"]
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE retention_policies SET retention_days = {ph}, status = {ph}, updated_at = {ph} WHERE id = {ph}",
                (new_days, new_status, _utcnow(), policy_id),
            )
        return self.get_policy(policy_id)

    # -- runs / deletions --

    def start_run(self, policy_id: str) -> str:
        ph = self._placeholder()
        run_id = uuid.uuid4().hex
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO retention_runs (id, policy_id, started_at, outcome) VALUES ({ph},{ph},{ph},'running')",
                (run_id, policy_id, _utcnow()),
            )
        return run_id

    def finish_run(
        self, run_id: str, *, outcome: str, messages_deleted: int, attachments_deleted: int, error: str | None = None,
    ) -> None:
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE retention_runs SET finished_at = {ph}, outcome = {ph}, messages_deleted = {ph}, "
                f"attachments_deleted = {ph}, error = {ph} WHERE id = {ph}",
                (_utcnow(), outcome, messages_deleted, attachments_deleted, error, run_id),
            )

    def record_deletion(
        self, *, run_id: str, item_type: str, item_id: str, sender_or_author: str,
        original_created_at: str, status: str, error: str | None = None,
    ) -> None:
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"""INSERT INTO retention_deletions
                    (id, run_id, item_type, item_id, sender_or_author, original_created_at, deleted_at, status, error)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (uuid.uuid4().hex, run_id, item_type, item_id, sender_or_author, original_created_at, _utcnow(), status, error),
            )

    def list_runs(
        self, *, policy_id: str | None = None, limit: int = 30, offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        ph = self._placeholder()
        columns = "id, policy_id, started_at, finished_at, outcome, messages_deleted, attachments_deleted, error"
        with self._conn() as conn:
            if policy_id:
                total = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM retention_runs WHERE policy_id = {ph}", (policy_id,)
                ).fetchone()["cnt"]
                rows = conn.execute(
                    f"SELECT {columns} FROM retention_runs WHERE policy_id = {ph} "
                    f"ORDER BY started_at DESC LIMIT {ph} OFFSET {ph}",
                    (policy_id, limit, offset),
                ).fetchall()
            else:
                total = conn.execute("SELECT COUNT(*) AS cnt FROM retention_runs").fetchone()["cnt"]
                rows = conn.execute(
                    f"SELECT {columns} FROM retention_runs ORDER BY started_at DESC LIMIT {ph} OFFSET {ph}",
                    (limit, offset),
                ).fetchall()
        return [dict(r) for r in rows], total

    def list_deletions(
        self, *, run_id: str | None = None, limit: int = 50, offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        ph = self._placeholder()
        columns = "id, run_id, item_type, item_id, sender_or_author, original_created_at, deleted_at, status, error"
        with self._conn() as conn:
            if run_id:
                total = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM retention_deletions WHERE run_id = {ph}", (run_id,)
                ).fetchone()["cnt"]
                rows = conn.execute(
                    f"SELECT {columns} FROM retention_deletions WHERE run_id = {ph} "
                    f"ORDER BY deleted_at DESC LIMIT {ph} OFFSET {ph}",
                    (run_id, limit, offset),
                ).fetchall()
            else:
                total = conn.execute("SELECT COUNT(*) AS cnt FROM retention_deletions").fetchone()["cnt"]
                rows = conn.execute(
                    f"SELECT {columns} FROM retention_deletions ORDER BY deleted_at DESC LIMIT {ph} OFFSET {ph}",
                    (limit, offset),
                ).fetchall()
        return [dict(r) for r in rows], total


retention_policy_store = RetentionPolicyStore()
