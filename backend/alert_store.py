"""SQLite store for alert rules and alert history."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)


class AlertStore:
    """Manages alert rules and send history in SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "alerts.db")
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _sqlite_conn(self) -> sqlite3.Connection:
        conn = connect_sqlite(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _conn(self):
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return self._sqlite_conn()

    def _backfill_from_sqlite_if_needed(self) -> None:
        if not self._use_postgres or not os.path.exists(self._db_path):
            return
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM alert_rules").fetchone()
            if row and int(row["count"]) > 0:
                return
        with self._sqlite_conn() as sqlite_conn:
            rules = sqlite_conn.execute("SELECT * FROM alert_rules").fetchall()
            history = sqlite_conn.execute("SELECT * FROM alert_history").fetchall()
            seen = sqlite_conn.execute("SELECT * FROM alert_seen_tickets").fetchall()
        with self._conn() as conn:
            if rules:
                conn.executemany(
                    """
                    INSERT INTO alert_rules (
                        id, site_scope, name, enabled, trigger_type, trigger_config, frequency,
                        schedule_time, schedule_days, recipients, cc, filters, last_run, last_sent,
                        created_at, updated_at, custom_subject, custom_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    [
                        (
                            row["id"],
                            row["site_scope"],
                            row["name"],
                            row["enabled"],
                            row["trigger_type"],
                            row["trigger_config"],
                            row["frequency"],
                            row["schedule_time"],
                            row["schedule_days"],
                            row["recipients"],
                            row["cc"],
                            row["filters"],
                            row["last_run"],
                            row["last_sent"],
                            row["created_at"],
                            row["updated_at"],
                            row["custom_subject"],
                            row["custom_message"],
                        )
                        for row in rules
                    ],
                )
            if history:
                conn.executemany(
                    """
                    INSERT INTO alert_history (
                        id, site_scope, rule_id, rule_name, trigger_type, sent_at, recipients,
                        ticket_count, ticket_keys, status, error
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    [
                        (
                            row["id"],
                            row["site_scope"],
                            row["rule_id"],
                            row["rule_name"],
                            row["trigger_type"],
                            row["sent_at"],
                            row["recipients"],
                            row["ticket_count"],
                            row["ticket_keys"],
                            row["status"],
                            row["error"],
                        )
                        for row in history
                    ],
                )
            if seen:
                conn.executemany(
                    """
                    INSERT INTO alert_seen_tickets (rule_id, ticket_key, seen_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(rule_id, ticket_key) DO NOTHING
                    """,
                    [(row["rule_id"], row["ticket_key"], row["seen_at"]) for row in seen],
                )

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            self._backfill_from_sqlite_if_needed()
            return
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_scope TEXT NOT NULL DEFAULT 'primary',
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    trigger_type TEXT NOT NULL,
                    trigger_config TEXT NOT NULL DEFAULT '{}',
                    frequency TEXT NOT NULL DEFAULT 'daily',
                    schedule_time TEXT NOT NULL DEFAULT '08:00',
                    schedule_days TEXT NOT NULL DEFAULT '0,1,2,3,4',
                    recipients TEXT NOT NULL,
                    cc TEXT NOT NULL DEFAULT '',
                    filters TEXT NOT NULL DEFAULT '{}',
                    last_run TEXT,
                    last_sent TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            # Migrate: add custom_subject and custom_message if missing
            cols = {r[1] for r in conn.execute("PRAGMA table_info(alert_rules)").fetchall()}
            if "site_scope" not in cols:
                conn.execute("ALTER TABLE alert_rules ADD COLUMN site_scope TEXT NOT NULL DEFAULT 'primary'")
            if "custom_subject" not in cols:
                conn.execute("ALTER TABLE alert_rules ADD COLUMN custom_subject TEXT NOT NULL DEFAULT ''")
            if "custom_message" not in cols:
                conn.execute("ALTER TABLE alert_rules ADD COLUMN custom_message TEXT NOT NULL DEFAULT ''")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_scope TEXT NOT NULL DEFAULT 'primary',
                    rule_id INTEGER NOT NULL,
                    rule_name TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    sent_at TEXT NOT NULL DEFAULT (datetime('now')),
                    recipients TEXT NOT NULL,
                    ticket_count INTEGER NOT NULL DEFAULT 0,
                    ticket_keys TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'sent',
                    error TEXT,
                    FOREIGN KEY (rule_id) REFERENCES alert_rules(id) ON DELETE CASCADE
                )
            """)
            history_cols = {r[1] for r in conn.execute("PRAGMA table_info(alert_history)").fetchall()}
            if "site_scope" not in history_cols:
                conn.execute("ALTER TABLE alert_history ADD COLUMN site_scope TEXT NOT NULL DEFAULT 'primary'")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_seen_tickets (
                    rule_id INTEGER NOT NULL,
                    ticket_key TEXT NOT NULL,
                    seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (rule_id, ticket_key),
                    FOREIGN KEY (rule_id) REFERENCES alert_rules(id) ON DELETE CASCADE
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_rules_scope_enabled "
                "ON alert_rules(site_scope, enabled)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_history_rule_scope_sent "
                "ON alert_history(rule_id, site_scope, sent_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_history_scope_sent "
                "ON alert_history(site_scope, sent_at)"
            )

    # -----------------------------------------------------------------------
    # Alert Rules CRUD
    # -----------------------------------------------------------------------

    def get_rules(self, site_scope: str = "primary") -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM alert_rules WHERE site_scope = {self._placeholder()} ORDER BY created_at DESC",
                (site_scope,),
            ).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def get_rule(self, rule_id: int, site_scope: str = "primary") -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM alert_rules WHERE id = {self._placeholder()} AND site_scope = {self._placeholder()}",
                (rule_id, site_scope),
            ).fetchone()
        return self._row_to_rule(row) if row else None

    def get_enabled_rules(self, site_scope: str = "primary") -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM alert_rules WHERE enabled = 1 AND site_scope = {self._placeholder()} ORDER BY id",
                (site_scope,),
            ).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def create_rule(self, data: dict[str, Any]) -> dict[str, Any]:
        rule_id: int | None = None
        with self._conn() as conn:
            if self._use_postgres:
                row = conn.execute(
                    """INSERT INTO alert_rules
                       (site_scope, name, enabled, trigger_type, trigger_config, frequency,
                        schedule_time, schedule_days, recipients, cc, filters,
                        custom_subject, custom_message, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (
                        data.get("site_scope", "primary"),
                        data["name"],
                        1 if data.get("enabled", True) else 0,
                        data["trigger_type"],
                        json.dumps(data.get("trigger_config", {})),
                        data.get("frequency", "daily"),
                        data.get("schedule_time", "08:00"),
                        data.get("schedule_days", "0,1,2,3,4"),
                        data["recipients"],
                        data.get("cc", ""),
                        json.dumps(data.get("filters", {})),
                        data.get("custom_subject", ""),
                        data.get("custom_message", ""),
                        datetime.now(timezone.utc).isoformat(),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                ).fetchone()
                rule_id = int(row["id"]) if row else None
            else:
                cur = conn.execute(
                    """INSERT INTO alert_rules
                       (site_scope, name, enabled, trigger_type, trigger_config, frequency,
                        schedule_time, schedule_days, recipients, cc, filters,
                        custom_subject, custom_message)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        data.get("site_scope", "primary"),
                        data["name"],
                        1 if data.get("enabled", True) else 0,
                        data["trigger_type"],
                        json.dumps(data.get("trigger_config", {})),
                        data.get("frequency", "daily"),
                        data.get("schedule_time", "08:00"),
                        data.get("schedule_days", "0,1,2,3,4"),
                        data["recipients"],
                        data.get("cc", ""),
                        json.dumps(data.get("filters", {})),
                        data.get("custom_subject", ""),
                        data.get("custom_message", ""),
                    ),
                )
                rule_id = cur.lastrowid
        return self.get_rule(rule_id, site_scope=data.get("site_scope", "primary"))  # type: ignore[arg-type, return-value]

    def update_rule(self, rule_id: int, data: dict[str, Any], site_scope: str = "primary") -> dict[str, Any] | None:
        existing = self.get_rule(rule_id, site_scope=site_scope)
        if not existing:
            return None

        with self._conn() as conn:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """UPDATE alert_rules SET
                   name={p}, enabled={p}, trigger_type={p}, trigger_config={p},
                   frequency={p}, schedule_time={p}, schedule_days={p},
                   recipients={p}, cc={p}, filters={p},
                   custom_subject={p}, custom_message={p},
                   updated_at={p}
                   WHERE id={p} AND site_scope={p}""".format(p=self._placeholder()),
                (
                    data.get("name", existing["name"]),
                    1 if data.get("enabled", existing["enabled"]) else 0,
                    data.get("trigger_type", existing["trigger_type"]),
                    json.dumps(data.get("trigger_config", existing["trigger_config"])),
                    data.get("frequency", existing["frequency"]),
                    data.get("schedule_time", existing["schedule_time"]),
                    data.get("schedule_days", existing["schedule_days"]),
                    data.get("recipients", existing["recipients"]),
                    data.get("cc", existing.get("cc", "")),
                    json.dumps(data.get("filters", existing["filters"])),
                    data.get("custom_subject", existing.get("custom_subject", "")),
                    data.get("custom_message", existing.get("custom_message", "")),
                    now,
                    rule_id,
                    site_scope,
                ),
            )
        return self.get_rule(rule_id, site_scope=site_scope)

    def delete_rule(self, rule_id: int, site_scope: str = "primary") -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                f"DELETE FROM alert_rules WHERE id = {self._placeholder()} AND site_scope = {self._placeholder()}",
                (rule_id, site_scope),
            )
        return cur.rowcount > 0

    def update_last_run(self, rule_id: int, sent: bool = False, site_scope: str = "primary") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            if sent:
                conn.execute(
                    f"UPDATE alert_rules SET last_run={self._placeholder()}, last_sent={self._placeholder()} WHERE id={self._placeholder()} AND site_scope={self._placeholder()}",
                    (now, now, rule_id, site_scope),
                )
            else:
                conn.execute(
                    f"UPDATE alert_rules SET last_run={self._placeholder()} WHERE id={self._placeholder()} AND site_scope={self._placeholder()}",
                    (now, rule_id, site_scope),
                )

    # -----------------------------------------------------------------------
    # Alert History
    # -----------------------------------------------------------------------

    def record_send(
        self,
        rule: dict[str, Any],
        ticket_keys: list[str],
        status: str = "sent",
        error: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO alert_history
                   (site_scope, rule_id, rule_name, trigger_type, recipients,
                    ticket_count, ticket_keys, status, error)
                   VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})""".format(p=self._placeholder()),
                (
                    rule.get("site_scope", "primary"),
                    rule["id"],
                    rule["name"],
                    rule["trigger_type"],
                    rule["recipients"],
                    len(ticket_keys),
                    json.dumps(ticket_keys),
                    status,
                    error,
                ),
            )

    # -----------------------------------------------------------------------
    # Seen ticket tracking for "new ticket" alerts
    # -----------------------------------------------------------------------

    def get_seen_ticket_keys(self, rule_id: int) -> set[str]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT ticket_key FROM alert_seen_tickets WHERE rule_id = {self._placeholder()}",
                (rule_id,),
            ).fetchall()
        return {str(row["ticket_key"]) for row in rows}

    def mark_ticket_keys_seen(self, rule_id: int, ticket_keys: list[str]) -> None:
        keys = [key for key in dict.fromkeys(ticket_keys) if key]
        if not keys:
            return

        seen_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            if self._use_postgres:
                conn.executemany(
                    """INSERT INTO alert_seen_tickets
                       (rule_id, ticket_key, seen_at)
                       VALUES (%s, %s, %s)
                       ON CONFLICT(rule_id, ticket_key) DO NOTHING""",
                    [(rule_id, key, seen_at) for key in keys],
                )
            else:
                conn.executemany(
                    """INSERT OR IGNORE INTO alert_seen_tickets
                       (rule_id, ticket_key, seen_at)
                       VALUES (?, ?, ?)""",
                    [(rule_id, key, seen_at) for key in keys],
                )

    def replace_seen_ticket_keys(self, rule_id: int, ticket_keys: list[str]) -> None:
        keys = [key for key in dict.fromkeys(ticket_keys) if key]
        seen_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                f"DELETE FROM alert_seen_tickets WHERE rule_id = {self._placeholder()}",
                (rule_id,),
            )
            if keys:
                conn.executemany(
                    """INSERT INTO alert_seen_tickets
                       (rule_id, ticket_key, seen_at)
                       VALUES ({p}, {p}, {p})""".format(p=self._placeholder()),
                    [(rule_id, key, seen_at) for key in keys],
                )

    def clear_seen_ticket_keys(self, rule_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                f"DELETE FROM alert_seen_tickets WHERE rule_id = {self._placeholder()}",
                (rule_id,),
            )

    def get_history(self, limit: int = 50, rule_id: int | None = None, site_scope: str = "primary") -> list[dict[str, Any]]:
        with self._conn() as conn:
            if rule_id is not None:
                rows = conn.execute(
                    """SELECT * FROM alert_history
                       WHERE rule_id = {p} AND site_scope = {p}
                       ORDER BY sent_at DESC LIMIT {p}""".format(p=self._placeholder()),
                    (rule_id, site_scope, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM alert_history WHERE site_scope = {self._placeholder()} ORDER BY sent_at DESC LIMIT {self._placeholder()}",
                    (site_scope, limit),
                ).fetchall()
        return [self._row_to_history(r) for r in rows]

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _row_to_rule(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        d["trigger_config"] = json.loads(d.get("trigger_config") or "{}")
        d["filters"] = json.loads(d.get("filters") or "{}")
        return d

    @staticmethod
    def _row_to_history(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["ticket_keys"] = json.loads(d.get("ticket_keys") or "[]")
        return d


# Module singleton
alert_store = AlertStore()
