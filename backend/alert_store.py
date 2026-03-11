"""SQLite store for alert rules and alert history."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR

logger = logging.getLogger(__name__)


class AlertStore:
    """Manages alert rules and send history in SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "alerts.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
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
                "SELECT * FROM alert_rules WHERE site_scope = ? ORDER BY created_at DESC",
                (site_scope,),
            ).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def get_rule(self, rule_id: int, site_scope: str = "primary") -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM alert_rules WHERE id = ? AND site_scope = ?",
                (rule_id, site_scope),
            ).fetchone()
        return self._row_to_rule(row) if row else None

    def get_enabled_rules(self, site_scope: str = "primary") -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM alert_rules WHERE enabled = 1 AND site_scope = ? ORDER BY id",
                (site_scope,),
            ).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def create_rule(self, data: dict[str, Any]) -> dict[str, Any]:
        rule_id: int | None = None
        with self._conn() as conn:
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
            conn.execute(
                """UPDATE alert_rules SET
                   name=?, enabled=?, trigger_type=?, trigger_config=?,
                   frequency=?, schedule_time=?, schedule_days=?,
                   recipients=?, cc=?, filters=?,
                   custom_subject=?, custom_message=?,
                   updated_at=datetime('now')
                   WHERE id=? AND site_scope=?""",
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
                    rule_id,
                    site_scope,
                ),
            )
        return self.get_rule(rule_id, site_scope=site_scope)

    def delete_rule(self, rule_id: int, site_scope: str = "primary") -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM alert_rules WHERE id = ? AND site_scope = ?",
                (rule_id, site_scope),
            )
        return cur.rowcount > 0

    def update_last_run(self, rule_id: int, sent: bool = False, site_scope: str = "primary") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            if sent:
                conn.execute(
                    "UPDATE alert_rules SET last_run=?, last_sent=? WHERE id=? AND site_scope=?",
                    (now, now, rule_id, site_scope),
                )
            else:
                conn.execute(
                    "UPDATE alert_rules SET last_run=? WHERE id=? AND site_scope=?",
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
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                "SELECT ticket_key FROM alert_seen_tickets WHERE rule_id = ?",
                (rule_id,),
            ).fetchall()
        return {str(row["ticket_key"]) for row in rows}

    def mark_ticket_keys_seen(self, rule_id: int, ticket_keys: list[str]) -> None:
        keys = [key for key in dict.fromkeys(ticket_keys) if key]
        if not keys:
            return

        seen_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
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
            conn.execute("DELETE FROM alert_seen_tickets WHERE rule_id = ?", (rule_id,))
            if keys:
                conn.executemany(
                    """INSERT INTO alert_seen_tickets
                       (rule_id, ticket_key, seen_at)
                       VALUES (?, ?, ?)""",
                    [(rule_id, key, seen_at) for key in keys],
                )

    def clear_seen_ticket_keys(self, rule_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM alert_seen_tickets WHERE rule_id = ?", (rule_id,))

    def get_history(self, limit: int = 50, rule_id: int | None = None, site_scope: str = "primary") -> list[dict[str, Any]]:
        with self._conn() as conn:
            if rule_id is not None:
                rows = conn.execute(
                    """SELECT * FROM alert_history
                       WHERE rule_id = ? AND site_scope = ?
                       ORDER BY sent_at DESC LIMIT ?""",
                    (rule_id, site_scope, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alert_history WHERE site_scope = ? ORDER BY sent_at DESC LIMIT ?",
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
