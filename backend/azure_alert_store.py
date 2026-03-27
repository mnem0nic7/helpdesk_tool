"""Postgres-aware store for Azure alert rules, history, and state tables."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from config import DATA_DIR
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AzureAlertStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "azure_alerts.db")
        self._use_postgres = postgres_enabled() and db_path is None
        self._init_db()

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _sqlite_conn(self) -> sqlite3.Connection:
        conn = connect_sqlite(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _conn(self) -> Generator[Any, None, None]:
        if self._use_postgres:
            ensure_postgres_schema()
            conn = connect_postgres()
        else:
            conn = self._sqlite_conn()
        try:
            yield conn
        finally:
            conn.close()

    def _backfill_from_sqlite_if_needed(self) -> None:
        if not self._use_postgres or not os.path.exists(self._db_path):
            return
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM azure_alert_rules").fetchone()
            if row and int(row["count"]) > 0:
                return
        with self._sqlite_conn() as sqlite_conn:
            rules = sqlite_conn.execute("SELECT * FROM azure_alert_rules").fetchall()
            history = sqlite_conn.execute("SELECT * FROM azure_alert_history").fetchall()
            vm_states = sqlite_conn.execute("SELECT * FROM azure_alert_vm_states").fetchall()
            user_states = sqlite_conn.execute("SELECT * FROM azure_alert_user_states").fetchall()
        with self._conn() as conn:
            if rules:
                conn.executemany(
                    """
                    INSERT INTO azure_alert_rules (
                        id, name, enabled, domain, trigger_type, trigger_config,
                        frequency, schedule_time, schedule_days, recipients,
                        teams_webhook_url, custom_subject, custom_message,
                        last_run, last_sent, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    [
                        (
                            row["id"],
                            row["name"],
                            row["enabled"],
                            row["domain"],
                            row["trigger_type"],
                            row["trigger_config"],
                            row["frequency"],
                            row["schedule_time"],
                            row["schedule_days"],
                            row["recipients"],
                            row["teams_webhook_url"],
                            row["custom_subject"],
                            row["custom_message"],
                            row["last_run"],
                            row["last_sent"],
                            row["created_at"],
                            row["updated_at"],
                        )
                        for row in rules
                    ],
                )
            if history:
                conn.executemany(
                    """
                    INSERT INTO azure_alert_history (
                        id, rule_id, rule_name, trigger_type, sent_at, recipients,
                        match_count, match_summary, status, error
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    [
                        (
                            row["id"],
                            row["rule_id"],
                            row["rule_name"],
                            row["trigger_type"],
                            row["sent_at"],
                            row["recipients"],
                            row["match_count"],
                            row["match_summary"],
                            row["status"],
                            row["error"],
                        )
                        for row in history
                    ],
                )
            if vm_states:
                conn.executemany(
                    """
                    INSERT INTO azure_alert_vm_states (vm_id, first_seen_deallocated)
                    VALUES (%s, %s)
                    ON CONFLICT(vm_id) DO NOTHING
                    """,
                    [(row["vm_id"], row["first_seen_deallocated"]) for row in vm_states],
                )
            if user_states:
                conn.executemany(
                    """
                    INSERT INTO azure_alert_user_states (user_id, enabled, recorded_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(user_id) DO NOTHING
                    """,
                    [(row["user_id"], row["enabled"], row["recorded_at"]) for row in user_states],
                )

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            self._backfill_from_sqlite_if_needed()
            return
        with self._conn() as conn:
            conn.executescript(
                """
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
                """
            )
            conn.commit()

    def _row_to_rule(self, row: Any) -> dict[str, Any]:
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
                   VALUES ({p},{p},1,{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},NULL,NULL,{p},{p})""".format(
                    p=self._placeholder()
                ),
                (
                    rule_id,
                    data["name"],
                    data["domain"],
                    data["trigger_type"],
                    json.dumps(data.get("trigger_config") or {}),
                    data.get("frequency", "daily"),
                    data.get("schedule_time", "09:00"),
                    data.get("schedule_days", "0,1,2,3,4"),
                    data.get("recipients", ""),
                    data.get("teams_webhook_url", ""),
                    data.get("custom_subject", ""),
                    data.get("custom_message", ""),
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_rule(rule_id)  # type: ignore[return-value]

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM azure_alert_rules WHERE id = {self._placeholder()}",
                (rule_id,),
            ).fetchone()
        return self._row_to_rule(row) if row else None

    def list_rules(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM azure_alert_rules ORDER BY created_at DESC").fetchall()
        return [self._row_to_rule(r) for r in rows]

    def update_rule(self, rule_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """UPDATE azure_alert_rules SET
                   name={p}, domain={p}, trigger_type={p}, trigger_config={p},
                   frequency={p}, schedule_time={p}, schedule_days={p},
                   recipients={p}, teams_webhook_url={p},
                   custom_subject={p}, custom_message={p}, updated_at={p}
                   WHERE id={p}""".format(p=self._placeholder()),
                (
                    data["name"],
                    data["domain"],
                    data["trigger_type"],
                    json.dumps(data.get("trigger_config") or {}),
                    data.get("frequency", "daily"),
                    data.get("schedule_time", "09:00"),
                    data.get("schedule_days", "0,1,2,3,4"),
                    data.get("recipients", ""),
                    data.get("teams_webhook_url", ""),
                    data.get("custom_subject", ""),
                    data.get("custom_message", ""),
                    now,
                    rule_id,
                ),
            )
            conn.commit()
        return self.get_rule(rule_id)

    def toggle_rule(self, rule_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            conn.execute(
                f"UPDATE azure_alert_rules SET enabled = 1 - enabled, updated_at = {self._placeholder()} WHERE id = {self._placeholder()}",
                (_now(), rule_id),
            )
            conn.commit()
        return self.get_rule(rule_id)

    def delete_rule(self, rule_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                f"DELETE FROM azure_alert_rules WHERE id = {self._placeholder()}",
                (rule_id,),
            )
            conn.commit()

    def update_last_run(self, rule_id: str, *, last_sent: bool = False) -> None:
        now = _now()
        with self._conn() as conn:
            if last_sent:
                conn.execute(
                    f"UPDATE azure_alert_rules SET last_run={self._placeholder()}, last_sent={self._placeholder()}, updated_at={self._placeholder()} WHERE id={self._placeholder()}",
                    (now, now, now, rule_id),
                )
            else:
                conn.execute(
                    f"UPDATE azure_alert_rules SET last_run={self._placeholder()}, updated_at={self._placeholder()} WHERE id={self._placeholder()}",
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
                   VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p})""".format(p=self._placeholder()),
                (
                    str(uuid.uuid4()),
                    rule_id,
                    rule_name,
                    trigger_type,
                    _now(),
                    recipients,
                    match_count,
                    json.dumps({"items": sample_items[:10]}),
                    status,
                    error,
                ),
            )
            conn.commit()

    def get_history(self, *, limit: int = 100, rule_id: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if rule_id:
                rows = conn.execute(
                    f"SELECT * FROM azure_alert_history WHERE rule_id={self._placeholder()} ORDER BY sent_at DESC LIMIT {self._placeholder()}",
                    (rule_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM azure_alert_history ORDER BY sent_at DESC LIMIT {self._placeholder()}",
                    (limit,),
                ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["match_summary"] = json.loads(d.get("match_summary") or "{}")
            result.append(d)
        return result

    def get_vm_first_seen_deallocated(self, vm_id: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT first_seen_deallocated FROM azure_alert_vm_states WHERE vm_id={self._placeholder()}",
                (vm_id,),
            ).fetchone()
        if not row:
            return None
        return row["first_seen_deallocated"] if hasattr(row, "keys") else row[0]

    def set_vm_first_seen_deallocated(self, vm_id: str, ts: str) -> None:
        with self._conn() as conn:
            if self._use_postgres:
                conn.execute(
                    "INSERT INTO azure_alert_vm_states (vm_id, first_seen_deallocated) VALUES (%s, %s) ON CONFLICT(vm_id) DO NOTHING",
                    (vm_id, ts),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO azure_alert_vm_states (vm_id, first_seen_deallocated) VALUES (?,?)",
                    (vm_id, ts),
                )
            conn.commit()

    def purge_vm_states(self, active_vm_ids: set[str]) -> None:
        with self._conn() as conn:
            rows = conn.execute("SELECT vm_id FROM azure_alert_vm_states").fetchall()
            stale = []
            for row in rows:
                vm_id = str(row["vm_id"] if hasattr(row, "keys") else row[0])
                if vm_id not in active_vm_ids:
                    stale.append(vm_id)
            for vm_id in stale:
                conn.execute(
                    f"DELETE FROM azure_alert_vm_states WHERE vm_id={self._placeholder()}",
                    (vm_id,),
                )
            conn.commit()

    def get_user_state(self, user_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT enabled, recorded_at FROM azure_alert_user_states WHERE user_id={self._placeholder()}",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        enabled = bool(row["enabled"] if hasattr(row, "keys") else row[0])
        recorded_at = row["recorded_at"] if hasattr(row, "keys") else row[1]
        return {"enabled": enabled, "recorded_at": recorded_at}

    def upsert_user_state(self, user_id: str, enabled: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO azure_alert_user_states (user_id, enabled, recorded_at)
                   VALUES ({p},{p},{p})
                   ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled, recorded_at=excluded.recorded_at""".format(
                    p=self._placeholder()
                ),
                (user_id, int(enabled), _now()),
            )
            conn.commit()


def _make_store() -> AzureAlertStore:
    return AzureAlertStore()


azure_alert_store: AzureAlertStore = _make_store()
