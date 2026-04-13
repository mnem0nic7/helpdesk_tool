"""Durable store for Defender autonomous agent config, runs, and decisions."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Generator

from config import DATA_DIR
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DefenderAgentStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "defender_agent.db")
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

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            return
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS defender_agent_config (
                    id                    INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                    enabled               INTEGER NOT NULL DEFAULT 0,
                    min_severity          TEXT    NOT NULL DEFAULT 'high',
                    tier2_delay_minutes   INTEGER NOT NULL DEFAULT 15,
                    dry_run               INTEGER NOT NULL DEFAULT 0,
                    updated_at            TEXT    NOT NULL DEFAULT '',
                    updated_by            TEXT    NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS defender_agent_runs (
                    run_id          TEXT PRIMARY KEY,
                    started_at      TEXT NOT NULL,
                    completed_at    TEXT,
                    alerts_fetched  INTEGER NOT NULL DEFAULT 0,
                    alerts_new      INTEGER NOT NULL DEFAULT 0,
                    decisions_made  INTEGER NOT NULL DEFAULT 0,
                    actions_queued  INTEGER NOT NULL DEFAULT 0,
                    error           TEXT    NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_defender_runs_started
                    ON defender_agent_runs (started_at DESC);

                CREATE TABLE IF NOT EXISTS defender_agent_decisions (
                    decision_id         TEXT PRIMARY KEY,
                    run_id              TEXT NOT NULL,
                    alert_id            TEXT NOT NULL,
                    alert_title         TEXT NOT NULL DEFAULT '',
                    alert_severity      TEXT NOT NULL DEFAULT '',
                    alert_category      TEXT NOT NULL DEFAULT '',
                    alert_created_at    TEXT NOT NULL DEFAULT '',
                    service_source      TEXT NOT NULL DEFAULT '',
                    entities_json       TEXT NOT NULL DEFAULT '[]',
                    tier                INTEGER,
                    decision            TEXT NOT NULL DEFAULT 'skip',
                    action_type         TEXT NOT NULL DEFAULT '',
                    job_ids_json        TEXT NOT NULL DEFAULT '[]',
                    reason              TEXT NOT NULL DEFAULT '',
                    executed_at         TEXT NOT NULL,
                    not_before_at       TEXT,
                    cancelled           INTEGER NOT NULL DEFAULT 0,
                    cancelled_at        TEXT,
                    cancelled_by        TEXT NOT NULL DEFAULT '',
                    human_approved      INTEGER NOT NULL DEFAULT 0,
                    approved_at         TEXT,
                    approved_by         TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_defender_decisions_alert_id
                    ON defender_agent_decisions (alert_id);
                CREATE INDEX IF NOT EXISTS idx_defender_decisions_executed_at
                    ON defender_agent_decisions (executed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_defender_decisions_run_id
                    ON defender_agent_decisions (run_id, executed_at DESC);
                """
            )
            conn.commit()

    # -------------------------------------------------------------------------
    # Config
    # -------------------------------------------------------------------------

    _DEFAULT_CONFIG: dict[str, Any] = {
        "id": 1,
        "enabled": False,
        "min_severity": "high",
        "tier2_delay_minutes": 15,
        "dry_run": False,
        "updated_at": "",
        "updated_by": "",
    }

    def get_config(self) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM defender_agent_config WHERE id = 1").fetchone()
        if row is None:
            return dict(self._DEFAULT_CONFIG)
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        d["dry_run"] = bool(d["dry_run"])
        return d

    def upsert_config(
        self,
        *,
        enabled: bool,
        min_severity: str,
        tier2_delay_minutes: int,
        dry_run: bool,
        updated_by: str = "",
    ) -> dict[str, Any]:
        p = self._placeholder()
        now = _now()
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO defender_agent_config
                    (id, enabled, min_severity, tier2_delay_minutes, dry_run, updated_at, updated_by)
                VALUES (1, {p}, {p}, {p}, {p}, {p}, {p})
                ON CONFLICT(id) DO UPDATE SET
                    enabled             = excluded.enabled,
                    min_severity        = excluded.min_severity,
                    tier2_delay_minutes = excluded.tier2_delay_minutes,
                    dry_run             = excluded.dry_run,
                    updated_at          = excluded.updated_at,
                    updated_by          = excluded.updated_by
                """,
                (int(enabled), min_severity, tier2_delay_minutes, int(dry_run), now, updated_by),
            )
            conn.commit()
        return self.get_config()

    # -------------------------------------------------------------------------
    # Runs
    # -------------------------------------------------------------------------

    def create_run(self, run_id: str) -> None:
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO defender_agent_runs (run_id, started_at) VALUES ({p}, {p})",
                (run_id, _now()),
            )
            conn.commit()

    def complete_run(
        self,
        run_id: str,
        *,
        alerts_fetched: int,
        alerts_new: int,
        decisions_made: int,
        actions_queued: int,
        error: str = "",
    ) -> None:
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE defender_agent_runs
                   SET completed_at  = {p},
                       alerts_fetched = {p},
                       alerts_new    = {p},
                       decisions_made = {p},
                       actions_queued = {p},
                       error         = {p}
                 WHERE run_id = {p}
                """,
                (_now(), alerts_fetched, alerts_new, decisions_made, actions_queued, error, run_id),
            )
            conn.commit()

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        p = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM defender_agent_runs ORDER BY started_at DESC LIMIT {p}",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Decisions
    # -------------------------------------------------------------------------

    def create_decision(
        self,
        *,
        decision_id: str,
        run_id: str,
        alert_id: str,
        alert_title: str,
        alert_severity: str,
        alert_category: str,
        alert_created_at: str,
        service_source: str,
        entities: list[dict[str, Any]],
        tier: int | None,
        decision: str,
        action_type: str,
        job_ids: list[str],
        reason: str,
        not_before_at: str | None = None,
    ) -> dict[str, Any]:
        p = self._placeholder()
        now = _now()
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO defender_agent_decisions (
                    decision_id, run_id, alert_id, alert_title, alert_severity,
                    alert_category, alert_created_at, service_source, entities_json,
                    tier, decision, action_type, job_ids_json, reason,
                    executed_at, not_before_at
                ) VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
                """,
                (
                    decision_id, run_id, alert_id, alert_title, alert_severity,
                    alert_category, alert_created_at, service_source,
                    json.dumps(entities), tier, decision, action_type,
                    json.dumps(job_ids), reason, now, not_before_at,
                ),
            )
            conn.commit()
        return self.get_decision(decision_id) or {}

    def update_decision_jobs(self, decision_id: str, job_ids: list[str]) -> None:
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE defender_agent_decisions SET job_ids_json = {p} WHERE decision_id = {p}",
                (json.dumps(job_ids), decision_id),
            )
            conn.commit()

    def cancel_decision(self, decision_id: str, cancelled_by: str = "") -> dict[str, Any] | None:
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE defender_agent_decisions
                   SET cancelled = 1, cancelled_at = {p}, cancelled_by = {p}
                 WHERE decision_id = {p} AND cancelled = 0
                """,
                (_now(), cancelled_by, decision_id),
            )
            conn.commit()
        return self.get_decision(decision_id)

    def approve_decision(self, decision_id: str, approved_by: str = "") -> dict[str, Any] | None:
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE defender_agent_decisions
                   SET human_approved = 1, approved_at = {p}, approved_by = {p}
                 WHERE decision_id = {p} AND human_approved = 0
                """,
                (_now(), approved_by, decision_id),
            )
            conn.commit()
        return self.get_decision(decision_id)

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        p = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM defender_agent_decisions WHERE decision_id = {p}",
                (decision_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_decision(dict(row))

    def list_decisions(self, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        p = self._placeholder()
        with self._conn() as conn:
            total_row = conn.execute("SELECT COUNT(*) AS c FROM defender_agent_decisions").fetchone()
            total = int(total_row["c"]) if total_row else 0
            rows = conn.execute(
                f"""
                SELECT * FROM defender_agent_decisions
                 ORDER BY executed_at DESC
                 LIMIT {p} OFFSET {p}
                """,
                (limit, offset),
            ).fetchall()
        return [self._row_to_decision(dict(r)) for r in rows], total

    def get_seen_alert_ids(self, since_hours: int = 168) -> set[str]:
        """Return all alert IDs seen in the last N hours (default 7 days)."""
        since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
        p = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT alert_id FROM defender_agent_decisions WHERE executed_at >= {p}",
                (since,),
            ).fetchall()
        return {r["alert_id"] for r in rows}

    def list_pending_tier2(self) -> list[dict[str, Any]]:
        """T2 rows past their delay window, not yet dispatched, not cancelled."""
        now = _now()
        p = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM defender_agent_decisions
                 WHERE decision = 'queue'
                   AND cancelled = 0
                   AND human_approved = 0
                   AND job_ids_json = '[]'
                   AND not_before_at IS NOT NULL
                   AND not_before_at <= {p}
                 ORDER BY not_before_at ASC
                """,
                (now,),
            ).fetchall()
        return [self._row_to_decision(dict(r)) for r in rows]

    def get_summary(self) -> dict[str, Any]:
        """Quick counts for the security workspace hub."""
        now = _now()
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        p = self._placeholder()
        with self._conn() as conn:
            cfg = conn.execute("SELECT enabled FROM defender_agent_config WHERE id = 1").fetchone()
            run = conn.execute(
                "SELECT started_at, completed_at, error FROM defender_agent_runs"
                " ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            pending_approvals = conn.execute(
                "SELECT COUNT(*) AS c FROM defender_agent_decisions"
                " WHERE decision = 'recommend' AND human_approved = 0 AND cancelled = 0"
            ).fetchone()
            pending_tier2 = conn.execute(
                "SELECT COUNT(*) AS c FROM defender_agent_decisions"
                " WHERE decision = 'queue' AND cancelled = 0 AND job_ids_json = '[]'"
            ).fetchone()
            actions_today = conn.execute(
                f"SELECT COUNT(*) AS c FROM defender_agent_decisions"
                f" WHERE decision IN ('execute','queue') AND cancelled = 0 AND executed_at >= {p}",
                (today_start,),
            ).fetchone()
            recent = conn.execute(
                "SELECT * FROM defender_agent_decisions"
                " ORDER BY executed_at DESC LIMIT 10"
            ).fetchall()
        return {
            "enabled": bool((cfg or {}).get("enabled", 0)),
            "last_run_at": (run or {}).get("started_at"),
            "last_run_error": (run or {}).get("error", ""),
            "total_alerts_today": 0,
            "total_actions_today": int((actions_today or {}).get("c", 0)),
            "pending_approvals": int((pending_approvals or {}).get("c", 0)),
            "pending_tier2": int((pending_tier2 or {}).get("c", 0)),
            "recent_decisions": [self._row_to_decision(dict(r)) for r in recent],
        }

    @staticmethod
    def _row_to_decision(d: dict[str, Any]) -> dict[str, Any]:
        d["entities"] = json.loads(d.pop("entities_json", "[]") or "[]")
        d["job_ids"] = json.loads(d.pop("job_ids_json", "[]") or "[]")
        d["cancelled"] = bool(d.get("cancelled", 0))
        d["human_approved"] = bool(d.get("human_approved", 0))
        return d


defender_agent_store = DefenderAgentStore()
