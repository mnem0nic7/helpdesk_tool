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
                    enabled               INTEGER NOT NULL DEFAULT 1,
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
                    skips           INTEGER NOT NULL DEFAULT 0,
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
                    approved_by         TEXT NOT NULL DEFAULT '',
                    alert_raw_json      TEXT NOT NULL DEFAULT '',
                    alert_written_back  INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_defender_decisions_alert_id
                    ON defender_agent_decisions (alert_id);
                CREATE INDEX IF NOT EXISTS idx_defender_decisions_executed_at
                    ON defender_agent_decisions (executed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_defender_decisions_run_id
                    ON defender_agent_decisions (run_id, executed_at DESC);

                CREATE TABLE IF NOT EXISTS defender_agent_suppressions (
                    id                TEXT PRIMARY KEY,
                    suppression_type  TEXT NOT NULL,
                    value             TEXT NOT NULL,
                    reason            TEXT NOT NULL DEFAULT '',
                    created_by        TEXT NOT NULL DEFAULT '',
                    created_at        TEXT NOT NULL,
                    expires_at        TEXT,
                    active            INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_defender_suppressions_active
                    ON defender_agent_suppressions (active, expires_at);
                """
            )
            conn.commit()

        # Idempotent migrations for existing DBs — each opens its own connection
        # because the CREATE TABLE context manager above closes the connection on exit.
        for ddl in (
            "ALTER TABLE defender_agent_runs ADD COLUMN skips INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE defender_agent_decisions ADD COLUMN action_types_json TEXT NOT NULL DEFAULT '[]'",
            """CREATE TABLE IF NOT EXISTS defender_agent_suppressions (
                    id TEXT PRIMARY KEY,
                    suppression_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    active INTEGER NOT NULL DEFAULT 1
                )""",
            "CREATE INDEX IF NOT EXISTS idx_defender_suppressions_active ON defender_agent_suppressions (active, expires_at)",
        ):
            try:
                with self._conn() as _mc:
                    _mc.execute(ddl)
                    _mc.commit()
            except Exception:
                pass  # column already exists

    # -------------------------------------------------------------------------
    # Config
    # -------------------------------------------------------------------------

    _DEFAULT_CONFIG: dict[str, Any] = {
        "id": 1,
        "enabled": True,
        "min_severity": "medium",
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
        skips: int = 0,
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
                       skips         = {p},
                       error         = {p}
                 WHERE run_id = {p}
                """,
                (_now(), alerts_fetched, alerts_new, decisions_made, actions_queued, skips, error, run_id),
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
        action_types: list[str] | None = None,
        job_ids: list[str],
        reason: str,
        not_before_at: str | None = None,
        alert_raw: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        p = self._placeholder()
        now = _now()
        # Normalize action_types: always a list; action_type is the primary (first) element
        ats = action_types if action_types else ([action_type] if action_type else [])
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO defender_agent_decisions (
                    decision_id, run_id, alert_id, alert_title, alert_severity,
                    alert_category, alert_created_at, service_source, entities_json,
                    tier, decision, action_type, action_types_json, job_ids_json, reason,
                    executed_at, not_before_at, alert_raw_json
                ) VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
                """,
                (
                    decision_id, run_id, alert_id, alert_title, alert_severity,
                    alert_category, alert_created_at, service_source,
                    json.dumps(entities), tier, decision, action_type,
                    json.dumps(ats), json.dumps(job_ids), reason, now, not_before_at,
                    json.dumps(alert_raw) if alert_raw else "",
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

    def update_decision_writeback(self, decision_id: str) -> None:
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE defender_agent_decisions SET alert_written_back = {p} WHERE decision_id = {p}",
                (1, decision_id),
            )
            conn.commit()

    def cancel_decision(self, decision_id: str, cancelled_by: str = "") -> dict[str, Any] | None:
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE defender_agent_decisions
                   SET cancelled = {p}, cancelled_at = {p}, cancelled_by = {p}
                 WHERE decision_id = {p} AND cancelled = {p}
                """,
                (1, _now(), cancelled_by, decision_id, 0),
            )
            conn.commit()
        return self.get_decision(decision_id)

    def approve_decision(self, decision_id: str, approved_by: str = "") -> dict[str, Any] | None:
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE defender_agent_decisions
                   SET human_approved = {p}, approved_at = {p}, approved_by = {p}
                 WHERE decision_id = {p} AND human_approved = {p}
                """,
                (1, _now(), approved_by, decision_id, 0),
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
        return self._row_to_decision(dict(row), include_raw=True)

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
        return [self._row_to_decision(dict(r), include_raw=False) for r in rows], total

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
                   AND cancelled = {p}
                   AND human_approved = {p}
                   AND job_ids_json = '[]'
                   AND not_before_at IS NOT NULL
                   AND not_before_at <= {p}
                 ORDER BY not_before_at ASC
                """,
                (0, 0, now),
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
                f"SELECT COUNT(*) AS c FROM defender_agent_decisions"
                f" WHERE decision = 'recommend' AND human_approved = {p} AND cancelled = {p}",
                (0, 0),
            ).fetchone()
            pending_tier2 = conn.execute(
                f"SELECT COUNT(*) AS c FROM defender_agent_decisions"
                f" WHERE decision = 'queue' AND cancelled = {p} AND job_ids_json = '[]'",
                (0,),
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
        cfg_d = dict(cfg) if cfg else {}
        run_d = dict(run) if run else {}
        pt2_d = dict(pending_tier2) if pending_tier2 else {}
        pa_d = dict(pending_approvals) if pending_approvals else {}
        at_d = dict(actions_today) if actions_today else {}
        return {
            "enabled": bool(cfg_d.get("enabled", 0)),
            "last_run_at": run_d.get("started_at"),
            "last_run_error": run_d.get("error", ""),
            "total_alerts_today": 0,
            "total_actions_today": int(at_d.get("c", 0)),
            "pending_approvals": int(pa_d.get("c", 0)),
            "pending_tier2": int(pt2_d.get("c", 0)),
            "recent_decisions": [self._row_to_decision(dict(r), include_raw=False) for r in recent],
        }

    # -------------------------------------------------------------------------
    # Suppressions
    # -------------------------------------------------------------------------

    def create_suppression(
        self,
        *,
        suppression_type: str,
        value: str,
        reason: str = "",
        created_by: str = "",
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        sid = uuid.uuid4().hex
        now = _now()
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO defender_agent_suppressions
                    (id, suppression_type, value, reason, created_by, created_at, expires_at, active)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p})
                """,
                (sid, suppression_type, value, reason, created_by, now, expires_at, 1),
            )
            conn.commit()
        return self.get_suppression(sid) or {}

    def get_suppression(self, suppression_id: str) -> dict[str, Any] | None:
        p = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM defender_agent_suppressions WHERE id = {p}",
                (suppression_id,),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["active"] = bool(d.get("active", 1))
        return d

    def list_suppressions(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        now = _now()
        p = self._placeholder()
        with self._conn() as conn:
            if include_inactive:
                rows = conn.execute(
                    "SELECT * FROM defender_agent_suppressions ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT * FROM defender_agent_suppressions
                     WHERE active = {p}
                       AND (expires_at IS NULL OR expires_at > {p})
                     ORDER BY created_at DESC
                    """,
                    (1, now),
                ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["active"] = bool(d.get("active", 1))
            result.append(d)
        return result

    def delete_suppression(self, suppression_id: str) -> bool:
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE defender_agent_suppressions SET active = {p} WHERE id = {p}",
                (0, suppression_id),
            )
            conn.commit()
        row = self.get_suppression(suppression_id)
        return row is not None

    def get_active_suppressions(self) -> list[dict[str, Any]]:
        return self.list_suppressions(include_inactive=False)

    @staticmethod
    def _row_to_decision(d: dict[str, Any], *, include_raw: bool = False) -> dict[str, Any]:
        d["entities"] = json.loads(d.pop("entities_json", "[]") or "[]")
        d["job_ids"] = json.loads(d.pop("job_ids_json", "[]") or "[]")
        raw_ats = json.loads(d.pop("action_types_json", "[]") or "[]")
        # Ensure action_types is always populated (fall back to [action_type] for older rows)
        if raw_ats:
            d["action_types"] = raw_ats
        else:
            d["action_types"] = [d["action_type"]] if d.get("action_type") else []
        d["cancelled"] = bool(d.get("cancelled", 0))
        d["human_approved"] = bool(d.get("human_approved", 0))
        raw_str = d.pop("alert_raw_json", "") or ""
        if include_raw:
            d["alert_raw"] = json.loads(raw_str) if raw_str else {}
        d["alert_written_back"] = bool(d.get("alert_written_back", 0))
        return d


defender_agent_store = DefenderAgentStore()
