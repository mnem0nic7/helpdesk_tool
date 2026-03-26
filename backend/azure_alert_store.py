"""SQLite-backed store for Azure alert rules, history, and state tables."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from sqlite_utils import connect_sqlite


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AzureAlertStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = connect_sqlite(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS azure_alert_rules (
                    id              TEXT PRIMARY KEY,
                    name            TEXT NOT NULL,
                    enabled         INTEGER NOT NULL DEFAULT 1,
                    domain          TEXT NOT NULL,
                    trigger_type    TEXT NOT NULL,
                    trigger_config  TEXT NOT NULL DEFAULT '{}',
                    frequency       TEXT NOT NULL,
                    schedule_time   TEXT NOT NULL DEFAULT '09:00',
                    schedule_days   TEXT NOT NULL DEFAULT '0,1,2,3,4',
                    recipients      TEXT NOT NULL DEFAULT '',
                    teams_webhook_url TEXT NOT NULL DEFAULT '',
                    custom_subject  TEXT NOT NULL DEFAULT '',
                    custom_message  TEXT NOT NULL DEFAULT '',
                    last_run        TEXT,
                    last_sent       TEXT,
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_azure_alert_rules_domain_enabled
                    ON azure_alert_rules (domain, enabled);
                CREATE TABLE IF NOT EXISTS azure_alert_history (
                    id              TEXT PRIMARY KEY,
                    rule_id         TEXT NOT NULL REFERENCES azure_alert_rules(id) ON DELETE CASCADE,
                    rule_name       TEXT NOT NULL,
                    trigger_type    TEXT NOT NULL,
                    sent_at         TEXT NOT NULL,
                    recipients      TEXT NOT NULL,
                    match_count     INTEGER NOT NULL DEFAULT 0,
                    match_summary   TEXT NOT NULL DEFAULT '{}',
                    status          TEXT NOT NULL,
                    error           TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_azure_alert_history_rule_sent
                    ON azure_alert_history (rule_id, sent_at);
                CREATE TABLE IF NOT EXISTS azure_alert_vm_states (
                    vm_id                   TEXT PRIMARY KEY,
                    first_seen_deallocated  TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS azure_alert_user_states (
                    user_id     TEXT PRIMARY KEY,
                    enabled     INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL
                );
            """)
            conn.commit()

    def _row_to_rule(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["trigger_config"] = json.loads(d.get("trigger_config") or "{}")
        d["enabled"] = bool(d["enabled"])
        return d

    def create_rule(self, data: dict[str, Any]) -> dict[str, Any]:
        rule_id = str(uuid.uuid4())
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO azure_alert_rules
                   (id, name, enabled, domain, trigger_type, trigger_config,
                    frequency, schedule_time, schedule_days, recipients,
                    teams_webhook_url, custom_subject, custom_message,
                    last_run, last_sent, created_at, updated_at)
                   VALUES (?,?,1,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?)""",
                (
                    rule_id, data["name"], data["domain"], data["trigger_type"],
                    json.dumps(data.get("trigger_config") or {}),
                    data.get("frequency", "daily"),
                    data.get("schedule_time", "09:00"),
                    data.get("schedule_days", "0,1,2,3,4"),
                    data.get("recipients", ""),
                    data.get("teams_webhook_url", ""),
                    data.get("custom_subject", ""),
                    data.get("custom_message", ""),
                    now, now,
                ),
            )
            conn.commit()
        return self.get_rule(rule_id)  # type: ignore[return-value]

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM azure_alert_rules WHERE id = ?", (rule_id,)
            ).fetchone()
        return self._row_to_rule(row) if row else None

    def list_rules(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM azure_alert_rules ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def update_rule(self, rule_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """UPDATE azure_alert_rules SET
                   name=?, domain=?, trigger_type=?, trigger_config=?,
                   frequency=?, schedule_time=?, schedule_days=?,
                   recipients=?, teams_webhook_url=?,
                   custom_subject=?, custom_message=?, updated_at=?
                   WHERE id=?""",
                (
                    data["name"], data["domain"], data["trigger_type"],
                    json.dumps(data.get("trigger_config") or {}),
                    data.get("frequency", "daily"),
                    data.get("schedule_time", "09:00"),
                    data.get("schedule_days", "0,1,2,3,4"),
                    data.get("recipients", ""),
                    data.get("teams_webhook_url", ""),
                    data.get("custom_subject", ""),
                    data.get("custom_message", ""),
                    now, rule_id,
                ),
            )
            conn.commit()
        return self.get_rule(rule_id)

    def toggle_rule(self, rule_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE azure_alert_rules SET enabled = 1 - enabled, updated_at = ? WHERE id = ?",
                (_now(), rule_id),
            )
            conn.commit()
        return self.get_rule(rule_id)

    def delete_rule(self, rule_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM azure_alert_rules WHERE id = ?", (rule_id,))
            conn.commit()

    def update_last_run(self, rule_id: str, *, last_sent: bool = False) -> None:
        now = _now()
        with self._conn() as conn:
            if last_sent:
                conn.execute(
                    "UPDATE azure_alert_rules SET last_run=?, last_sent=?, updated_at=? WHERE id=?",
                    (now, now, now, rule_id),
                )
            else:
                conn.execute(
                    "UPDATE azure_alert_rules SET last_run=?, updated_at=? WHERE id=?",
                    (now, now, rule_id),
                )
            conn.commit()

    def record_history(
        self,
        rule_id: str,
        rule_name: str,
        trigger_type: str,
        recipients: str,
        match_count: int,
        sample_items: list[dict[str, Any]],
        status: str,
        error: str | None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO azure_alert_history
                   (id, rule_id, rule_name, trigger_type, sent_at, recipients,
                    match_count, match_summary, status, error)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), rule_id, rule_name, trigger_type,
                    _now(), recipients, match_count,
                    json.dumps({"items": sample_items[:10]}),
                    status, error,
                ),
            )
            conn.commit()

    def get_history(
        self, *, limit: int = 100, rule_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if rule_id:
                rows = conn.execute(
                    "SELECT * FROM azure_alert_history WHERE rule_id=? ORDER BY sent_at DESC LIMIT ?",
                    (rule_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM azure_alert_history ORDER BY sent_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["match_summary"] = json.loads(d.get("match_summary") or "{}")
            result.append(d)
        return result

    # ── VM state tracking ──────────────────────────────────────────────────────

    def get_vm_first_seen_deallocated(self, vm_id: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT first_seen_deallocated FROM azure_alert_vm_states WHERE vm_id=?",
                (vm_id,),
            ).fetchone()
        return row[0] if row else None

    def set_vm_first_seen_deallocated(self, vm_id: str, ts: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO azure_alert_vm_states (vm_id, first_seen_deallocated) VALUES (?,?)",
                (vm_id, ts),
            )
            conn.commit()

    def purge_vm_states(self, active_vm_ids: set[str]) -> None:
        """Remove tracking rows for VMs no longer deallocated."""
        with self._conn() as conn:
            rows = conn.execute("SELECT vm_id FROM azure_alert_vm_states").fetchall()
            stale = [r[0] for r in rows if r[0] not in active_vm_ids]
            for vm_id in stale:
                conn.execute("DELETE FROM azure_alert_vm_states WHERE vm_id=?", (vm_id,))
            conn.commit()

    # ── User state tracking ────────────────────────────────────────────────────

    def get_user_state(self, user_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT enabled, recorded_at FROM azure_alert_user_states WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return {"enabled": bool(row[0]), "recorded_at": row[1]} if row else None

    def upsert_user_state(self, user_id: str, enabled: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO azure_alert_user_states (user_id, enabled, recorded_at)
                   VALUES (?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled, recorded_at=excluded.recorded_at""",
                (user_id, int(enabled), _now()),
            )
            conn.commit()


def _make_store() -> AzureAlertStore:
    from config import DATA_DIR
    import os
    return AzureAlertStore(os.path.join(DATA_DIR, "azure_alerts.db"))


azure_alert_store: AzureAlertStore = _make_store()
