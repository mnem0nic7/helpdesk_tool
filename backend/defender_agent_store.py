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

                CREATE TABLE IF NOT EXISTS defender_agent_watchlist (
                    id           TEXT PRIMARY KEY,
                    entity_type  TEXT NOT NULL,
                    entity_id    TEXT NOT NULL,
                    entity_name  TEXT NOT NULL DEFAULT '',
                    reason       TEXT NOT NULL DEFAULT '',
                    boost_tier   INTEGER NOT NULL DEFAULT 0,
                    created_by   TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL,
                    active       INTEGER NOT NULL DEFAULT 1
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_defender_watchlist_entity
                    ON defender_agent_watchlist (entity_id, active);

                CREATE TABLE IF NOT EXISTS defender_agent_rule_overrides (
                    rule_id         TEXT PRIMARY KEY,
                    disabled        INTEGER NOT NULL DEFAULT 0,
                    confidence_score INTEGER,
                    updated_at      TEXT NOT NULL DEFAULT '',
                    updated_by      TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS defender_agent_custom_rules (
                    id              TEXT PRIMARY KEY,
                    name            TEXT NOT NULL DEFAULT '',
                    match_field     TEXT NOT NULL DEFAULT 'title',
                    match_value     TEXT NOT NULL DEFAULT '',
                    match_mode      TEXT NOT NULL DEFAULT 'contains',
                    tier            INTEGER NOT NULL DEFAULT 3,
                    action_type     TEXT NOT NULL DEFAULT 'start_investigation',
                    confidence_score INTEGER NOT NULL DEFAULT 50,
                    enabled         INTEGER NOT NULL DEFAULT 1,
                    created_by      TEXT NOT NULL DEFAULT '',
                    created_at      TEXT NOT NULL DEFAULT ''
                );
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
            "ALTER TABLE defender_agent_decisions ADD COLUMN mitre_techniques_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE defender_agent_config ADD COLUMN entity_cooldown_hours INTEGER NOT NULL DEFAULT 24",
            "ALTER TABLE defender_agent_config ADD COLUMN alert_dedup_window_minutes INTEGER NOT NULL DEFAULT 30",
            "ALTER TABLE defender_agent_decisions ADD COLUMN remediation_confirmed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE defender_agent_decisions ADD COLUMN remediation_failed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE defender_agent_decisions ADD COLUMN confirmed_at TEXT",
            "ALTER TABLE defender_agent_decisions ADD COLUMN confidence_score INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE defender_agent_config ADD COLUMN min_confidence INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE defender_agent_decisions ADD COLUMN disposition TEXT",
            "ALTER TABLE defender_agent_decisions ADD COLUMN disposition_note TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE defender_agent_decisions ADD COLUMN disposition_by TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE defender_agent_decisions ADD COLUMN disposition_at TEXT",
            "ALTER TABLE defender_agent_decisions ADD COLUMN investigation_notes_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE defender_agent_decisions ADD COLUMN watchlisted_entities_json TEXT NOT NULL DEFAULT '[]'",
            """CREATE TABLE IF NOT EXISTS defender_agent_watchlist (
                    id           TEXT PRIMARY KEY,
                    entity_type  TEXT NOT NULL,
                    entity_id    TEXT NOT NULL,
                    entity_name  TEXT NOT NULL DEFAULT '',
                    reason       TEXT NOT NULL DEFAULT '',
                    boost_tier   INTEGER NOT NULL DEFAULT 0,
                    created_by   TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL,
                    active       INTEGER NOT NULL DEFAULT 1
                )""",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_defender_watchlist_entity ON defender_agent_watchlist (entity_id, active)",
            """CREATE TABLE IF NOT EXISTS defender_agent_rule_overrides (
                    rule_id         TEXT PRIMARY KEY,
                    disabled        INTEGER NOT NULL DEFAULT 0,
                    confidence_score INTEGER,
                    updated_at      TEXT NOT NULL DEFAULT '',
                    updated_by      TEXT NOT NULL DEFAULT ''
                )""",
            """CREATE TABLE IF NOT EXISTS defender_agent_custom_rules (
                    id              TEXT PRIMARY KEY,
                    name            TEXT NOT NULL DEFAULT '',
                    match_field     TEXT NOT NULL DEFAULT 'title',
                    match_value     TEXT NOT NULL DEFAULT '',
                    match_mode      TEXT NOT NULL DEFAULT 'contains',
                    tier            INTEGER NOT NULL DEFAULT 3,
                    action_type     TEXT NOT NULL DEFAULT 'start_investigation',
                    confidence_score INTEGER NOT NULL DEFAULT 50,
                    enabled         INTEGER NOT NULL DEFAULT 1,
                    created_by      TEXT NOT NULL DEFAULT '',
                    created_at      TEXT NOT NULL DEFAULT ''
                )""",
            "ALTER TABLE defender_agent_decisions ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE defender_agent_config ADD COLUMN poll_interval_seconds INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE defender_agent_config ADD COLUMN teams_tier1_webhook TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE defender_agent_config ADD COLUMN teams_tier2_webhook TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE defender_agent_config ADD COLUMN teams_tier3_webhook TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE defender_agent_decisions ADD COLUMN resolved INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE defender_agent_decisions ADD COLUMN resolved_at TEXT",
            "ALTER TABLE defender_agent_decisions ADD COLUMN resolved_by TEXT NOT NULL DEFAULT ''",
            """CREATE TABLE IF NOT EXISTS defender_agent_playbooks (
                    id           TEXT PRIMARY KEY,
                    name         TEXT NOT NULL DEFAULT '',
                    description  TEXT NOT NULL DEFAULT '',
                    actions_json TEXT NOT NULL DEFAULT '[]',
                    enabled      INTEGER NOT NULL DEFAULT 1,
                    created_by   TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL DEFAULT '',
                    updated_at   TEXT NOT NULL DEFAULT ''
                )""",
            "ALTER TABLE defender_agent_custom_rules ADD COLUMN playbook_id TEXT",
            "ALTER TABLE defender_agent_decisions ADD COLUMN ai_narrative TEXT",
            "ALTER TABLE defender_agent_decisions ADD COLUMN ai_narrative_generated_at TEXT",
            "ALTER TABLE defender_agent_custom_rules ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''",
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
        "entity_cooldown_hours": 24,
        "alert_dedup_window_minutes": 30,
        "min_confidence": 0,
        "poll_interval_seconds": 0,
        "teams_tier1_webhook": "",
        "teams_tier2_webhook": "",
        "teams_tier3_webhook": "",
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
        if "entity_cooldown_hours" not in d:
            d["entity_cooldown_hours"] = 24
        if "alert_dedup_window_minutes" not in d:
            d["alert_dedup_window_minutes"] = 30
        if "min_confidence" not in d:
            d["min_confidence"] = 0
        if "poll_interval_seconds" not in d:
            d["poll_interval_seconds"] = 0
        if "teams_tier1_webhook" not in d:
            d["teams_tier1_webhook"] = ""
        if "teams_tier2_webhook" not in d:
            d["teams_tier2_webhook"] = ""
        if "teams_tier3_webhook" not in d:
            d["teams_tier3_webhook"] = ""
        return d

    def upsert_config(
        self,
        *,
        enabled: bool,
        min_severity: str,
        tier2_delay_minutes: int,
        dry_run: bool,
        entity_cooldown_hours: int = 24,
        alert_dedup_window_minutes: int = 30,
        min_confidence: int = 0,
        poll_interval_seconds: int = 0,
        teams_tier1_webhook: str = "",
        teams_tier2_webhook: str = "",
        teams_tier3_webhook: str = "",
        updated_by: str = "",
    ) -> dict[str, Any]:
        p = self._placeholder()
        now = _now()
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO defender_agent_config
                    (id, enabled, min_severity, tier2_delay_minutes, dry_run,
                     entity_cooldown_hours, alert_dedup_window_minutes, min_confidence,
                     poll_interval_seconds,
                     teams_tier1_webhook, teams_tier2_webhook, teams_tier3_webhook,
                     updated_at, updated_by)
                VALUES (1, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                ON CONFLICT(id) DO UPDATE SET
                    enabled                    = excluded.enabled,
                    min_severity               = excluded.min_severity,
                    tier2_delay_minutes        = excluded.tier2_delay_minutes,
                    dry_run                    = excluded.dry_run,
                    entity_cooldown_hours      = excluded.entity_cooldown_hours,
                    alert_dedup_window_minutes = excluded.alert_dedup_window_minutes,
                    min_confidence             = excluded.min_confidence,
                    poll_interval_seconds      = excluded.poll_interval_seconds,
                    teams_tier1_webhook        = excluded.teams_tier1_webhook,
                    teams_tier2_webhook        = excluded.teams_tier2_webhook,
                    teams_tier3_webhook        = excluded.teams_tier3_webhook,
                    updated_at                 = excluded.updated_at,
                    updated_by                 = excluded.updated_by
                """,
                (int(enabled), min_severity, tier2_delay_minutes, int(dry_run),
                 entity_cooldown_hours, alert_dedup_window_minutes, min_confidence,
                 poll_interval_seconds,
                 teams_tier1_webhook, teams_tier2_webhook, teams_tier3_webhook,
                 now, updated_by),
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
        mitre_techniques: list[str] | None = None,
        confidence_score: int = 0,
        watchlisted_entities: list[dict[str, Any]] | None = None,
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
                    executed_at, not_before_at, alert_raw_json, mitre_techniques_json,
                    confidence_score, watchlisted_entities_json
                ) VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
                """,
                (
                    decision_id, run_id, alert_id, alert_title, alert_severity,
                    alert_category, alert_created_at, service_source,
                    json.dumps(entities), tier, decision, action_type,
                    json.dumps(ats), json.dumps(job_ids), reason, now, not_before_at,
                    json.dumps(alert_raw) if alert_raw else "",
                    json.dumps(mitre_techniques or []),
                    confidence_score,
                    json.dumps(watchlisted_entities or []),
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

    def resolve_decision(self, decision_id: str, resolved_by: str = "") -> dict[str, Any] | None:
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE defender_agent_decisions
                   SET resolved = {p}, resolved_at = {p}, resolved_by = {p}
                 WHERE decision_id = {p}
                """,
                (1, _now(), resolved_by, decision_id),
            )
            conn.commit()
        return self.get_decision(decision_id)

    def set_decision_narrative(self, decision_id: str, narrative: str) -> None:
        p = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE defender_agent_decisions SET ai_narrative = {p}, ai_narrative_generated_at = {p} WHERE decision_id = {p}",
                (narrative, _now(), decision_id),
            )
            conn.commit()

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

    def list_decisions(
        self,
        limit: int = 100,
        offset: int = 0,
        decision_filter: str | None = None,
        mitre_technique: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        p = self._placeholder()
        where_clauses: list[str] = []
        params: list[object] = []

        if decision_filter == "action_recommended":
            where_clauses.append(f"decision != {p}")
            params.append("skip")
        elif decision_filter:
            where_clauses.append(f"decision = {p}")
            params.append(decision_filter)

        if mitre_technique:
            where_clauses.append(f"mitre_techniques_json LIKE {p}")
            params.append(f"%{mitre_technique}%")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        with self._conn() as conn:
            total_row = conn.execute(f"SELECT COUNT(*) AS c FROM defender_agent_decisions {where_sql}", params).fetchone()
            total = int(total_row["c"]) if total_row else 0
            rows = conn.execute(
                f"""
                SELECT * FROM defender_agent_decisions
                 {where_sql}
                 ORDER BY executed_at DESC
                 LIMIT {p} OFFSET {p}
                """,
                [*params, limit, offset],
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

    # -------------------------------------------------------------------------
    # Entity cooldown
    # -------------------------------------------------------------------------

    def get_recent_entity_actions(self, hours: int = 24) -> dict[str, set[str]]:
        """Return {entity_id: {action_types}} for non-skip decisions in the last N hours.

        Used by the agent cycle to detect when an entity has already been
        acted on recently so the same action is not repeated.
        Only decisions that produced jobs (i.e. the action was actually dispatched)
        are counted — queued-but-not-yet-executed T2 rows and recommend-only rows
        are excluded so the cooldown doesn't block the original dispatch.
        """
        if hours <= 0:
            return {}
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        p = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT entities_json, action_types_json, action_type
                  FROM defender_agent_decisions
                 WHERE executed_at >= {p}
                   AND decision != 'skip'
                   AND job_ids_json != '[]'
                """,
                (since,),
            ).fetchall()
        result: dict[str, set[str]] = {}
        for row in rows:
            entities = json.loads(row["entities_json"] or "[]")
            ats = json.loads(row["action_types_json"] or "[]")
            if not ats and row["action_type"]:
                ats = [row["action_type"]]
            for entity in entities:
                eid = str(entity.get("id") or "")
                if not eid:
                    continue
                if eid not in result:
                    result[eid] = set()
                result[eid].update(ats)
        return result

    # -------------------------------------------------------------------------
    # Alert deduplication
    # -------------------------------------------------------------------------

    def get_recent_decisions_for_dedup(self, since_minutes: int = 30) -> list[dict[str, Any]]:
        """Return lightweight decision records created in the last N minutes for dedup index.

        Only non-skip, non-cancelled decisions are included (i.e. decisions that
        actually represent actions taken or queued).  The returned dicts are minimal
        — only decision_id, entities, and action_types — to keep the in-memory
        dedup index small.
        """
        if since_minutes <= 0:
            return []
        since = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat()
        p = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT decision_id, entities_json, action_type, action_types_json
                  FROM defender_agent_decisions
                 WHERE executed_at >= {p}
                   AND decision != 'skip'
                   AND cancelled = 0
                """,
                (since,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            ats = json.loads(row["action_types_json"] or "[]")
            if not ats and row["action_type"]:
                ats = [row["action_type"]]
            result.append({
                "decision_id": row["decision_id"],
                "entities": json.loads(row["entities_json"] or "[]"),
                "action_types": ats,
            })
        return result

    # -------------------------------------------------------------------------
    # Remediation confirmation
    # -------------------------------------------------------------------------

    def get_unconfirmed_actioned_decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return dispatched decisions that have not yet been confirmed or marked failed.

        Only decisions with actual job_ids are returned — T3 decisions awaiting
        approval and T2 decisions still in the cancellation window have empty
        job_ids and are excluded.  Skipped decisions are also excluded.
        """
        p = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT decision_id, job_ids_json, entities_json, action_type, action_types_json
                  FROM defender_agent_decisions
                 WHERE job_ids_json != {p}
                   AND decision != {p}
                   AND remediation_confirmed = {p}
                   AND remediation_failed = {p}
                 ORDER BY executed_at DESC
                 LIMIT {p}
                """,
                ("[]", "skip", 0, 0, limit),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            ats = json.loads(row["action_types_json"] or "[]")
            if not ats and row["action_type"]:
                ats = [row["action_type"]]
            result.append({
                "decision_id": row["decision_id"],
                "job_ids": json.loads(row["job_ids_json"] or "[]"),
                "entities": json.loads(row["entities_json"] or "[]"),
                "action_types": ats,
            })
        return result

    def update_decision_remediation(
        self,
        decision_id: str,
        *,
        confirmed: bool,
        failed: bool,
    ) -> None:
        p = self._placeholder()
        now = _now()
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE defender_agent_decisions
                   SET remediation_confirmed = {p},
                       remediation_failed    = {p},
                       confirmed_at          = {p}
                 WHERE decision_id = {p}
                """,
                (int(confirmed), int(failed), now, decision_id),
            )
            conn.commit()

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
        d["resolved"] = bool(d.get("resolved", 0))
        raw_str = d.pop("alert_raw_json", "") or ""
        if include_raw:
            d["alert_raw"] = json.loads(raw_str) if raw_str else {}
        d["alert_written_back"] = bool(d.get("alert_written_back", 0))
        d["mitre_techniques"] = json.loads(d.pop("mitre_techniques_json", "[]") or "[]")
        d["remediation_confirmed"] = bool(d.get("remediation_confirmed", 0))
        d["remediation_failed"] = bool(d.get("remediation_failed", 0))
        d["confidence_score"] = int(d.get("confidence_score") or 0)
        d.setdefault("disposition", None)
        d.setdefault("disposition_note", "")
        d.setdefault("disposition_by", "")
        d.setdefault("disposition_at", None)
        raw_notes = d.pop("investigation_notes_json", "[]") or "[]"
        d["investigation_notes"] = json.loads(raw_notes)
        raw_wl = d.pop("watchlisted_entities_json", "[]") or "[]"
        d["watchlisted_entities"] = json.loads(raw_wl)
        raw_tags = d.pop("tags_json", "[]") or "[]"
        d["tags"] = json.loads(raw_tags)
        d.setdefault("ai_narrative", None)
        d.setdefault("ai_narrative_generated_at", None)
        return d


    # -------------------------------------------------------------------------
    # Entity timeline
    # -------------------------------------------------------------------------

    def get_entity_timeline(
        self,
        entity_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return decisions that involve a specific entity, newest first.

        entity_id may be an Azure AD user/device ID, UPN, or device name.
        Uses a LIKE pre-filter on entities_json (fast for typical volumes)
        followed by a Python-side exact-match check so partial substrings
        (e.g. "ada" matching "ada-admin") are not included.
        """
        if not entity_id:
            return []
        search = entity_id.lower()
        p = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM defender_agent_decisions
                 WHERE entities_json LIKE {p}
                 ORDER BY executed_at DESC
                 LIMIT {p}
                """,
                (f"%{entity_id}%", limit * 5),  # over-fetch; filter below
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            d = self._row_to_decision(dict(row), include_raw=False)
            # Exact match: check entity id or name in the parsed list
            entities = d.get("entities") or []
            matched = any(
                search == str(e.get("id") or "").lower() or
                search == str(e.get("name") or "").lower()
                for e in entities
            )
            if matched:
                results.append(d)
            if len(results) >= limit:
                break
        return results

    # -------------------------------------------------------------------------
    # Analyst disposition
    # -------------------------------------------------------------------------

    _VALID_DISPOSITIONS = {"true_positive", "false_positive", "inconclusive"}

    def set_decision_disposition(
        self,
        decision_id: str,
        disposition: str,
        *,
        note: str = "",
        by: str = "",
    ) -> dict[str, Any] | None:
        """Set or update the analyst disposition on a decision.

        disposition must be one of: true_positive | false_positive | inconclusive.
        Pass disposition=None to clear (treated as empty string → stored as NULL).
        Returns the updated decision or None if not found.
        """
        if disposition not in self._VALID_DISPOSITIONS:
            raise ValueError(f"disposition must be one of {self._VALID_DISPOSITIONS}")
        p = self._placeholder()
        now = _now()
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE defender_agent_decisions
                   SET disposition      = {p},
                       disposition_note = {p},
                       disposition_by   = {p},
                       disposition_at   = {p}
                 WHERE decision_id = {p}
                """,
                (disposition, note, by, now, decision_id),
            )
            conn.commit()
        return self.get_decision(decision_id)

    # -------------------------------------------------------------------------
    # Watchlist
    # -------------------------------------------------------------------------

    _VALID_WATCHLIST_ENTITY_TYPES = {"user", "device"}

    def add_watchlist_entry(
        self,
        entity_type: str,
        entity_id: str,
        entity_name: str = "",
        reason: str = "",
        boost_tier: bool = False,
        created_by: str = "",
    ) -> dict[str, Any]:
        """Add an entity to the watchlist.

        If the entity_id is already active in the watchlist, updates the
        existing entry's metadata instead of inserting a duplicate.
        """
        if entity_type not in self._VALID_WATCHLIST_ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of {self._VALID_WATCHLIST_ENTITY_TYPES}")
        entity_id = (entity_id or "").strip()
        if not entity_id:
            raise ValueError("entity_id cannot be empty")
        p = self._placeholder()
        now = _now()
        entry_id = str(uuid.uuid4())
        with self._conn() as conn:
            # Check if already active
            existing = conn.execute(
                f"SELECT id FROM defender_agent_watchlist WHERE entity_id = {p} AND active = 1",
                (entity_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    f"""
                    UPDATE defender_agent_watchlist
                       SET entity_type = {p}, entity_name = {p}, reason = {p},
                           boost_tier = {p}, created_by = {p}, created_at = {p}
                     WHERE id = {p}
                    """,
                    (entity_type, entity_name, reason, int(boost_tier), created_by, now, existing["id"]),
                )
                entry_id = existing["id"]
            else:
                conn.execute(
                    f"""
                    INSERT INTO defender_agent_watchlist
                        (id, entity_type, entity_id, entity_name, reason, boost_tier, created_by, created_at, active)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},1)
                    """,
                    (entry_id, entity_type, entity_id, entity_name, reason, int(boost_tier), created_by, now),
                )
            conn.commit()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM defender_agent_watchlist WHERE id = {p}", (entry_id,)
            ).fetchone()
        return self._row_to_watchlist(dict(row))

    def remove_watchlist_entry(self, entry_id: str) -> bool:
        """Deactivate a watchlist entry. Returns True if found, False otherwise."""
        p = self._placeholder()
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE defender_agent_watchlist SET active = 0 WHERE id = {p} AND active = 1",
                (entry_id,),
            )
            conn.commit()
        return (cur.rowcount or 0) > 0

    def list_watchlist(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        """Return watchlist entries, newest first."""
        with self._conn() as conn:
            if include_inactive:
                rows = conn.execute(
                    "SELECT * FROM defender_agent_watchlist ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM defender_agent_watchlist WHERE active = 1 ORDER BY created_at DESC"
                ).fetchall()
        return [self._row_to_watchlist(dict(r)) for r in rows]

    def get_watchlist_lookup(self) -> dict[str, dict[str, Any]]:
        """Return a lookup dict keyed by lower-cased entity_id for the active watchlist.

        Used by the agent cycle to check entities in O(1).
        """
        entries = self.list_watchlist()
        return {e["entity_id"].lower(): e for e in entries}

    @staticmethod
    def _row_to_watchlist(d: dict[str, Any]) -> dict[str, Any]:
        d["active"] = bool(d.get("active", 1))
        d["boost_tier"] = bool(d.get("boost_tier", 0))
        return d

    # -------------------------------------------------------------------------
    # Investigation notes
    # -------------------------------------------------------------------------

    def append_investigation_note(
        self,
        decision_id: str,
        text: str,
        *,
        by: str = "",
    ) -> dict[str, Any] | None:
        """Append an analyst note to a decision's investigation log.

        Notes are stored as a JSON array: [{text, by, at}, ...].
        Returns the updated decision, or None if not found.
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("note text cannot be empty")
        p = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT investigation_notes_json FROM defender_agent_decisions WHERE decision_id = {p}",
                (decision_id,),
            ).fetchone()
            if row is None:
                return None
            existing: list[dict[str, Any]] = json.loads(row["investigation_notes_json"] or "[]")
            existing.append({"text": text, "by": by, "at": _now()})
            conn.execute(
                f"UPDATE defender_agent_decisions SET investigation_notes_json = {p} WHERE decision_id = {p}",
                (json.dumps(existing), decision_id),
            )
            conn.commit()
        return self.get_decision(decision_id)

    def get_disposition_stats(self) -> dict[str, Any]:
        """Return aggregate TP/FP/Inconclusive counts and per-tier breakdown.

        Counts non-skip decisions only (skips are not dispositioned by analysts).
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT tier, disposition, COUNT(*) AS c
                  FROM defender_agent_decisions
                 WHERE decision != 'skip'
                 GROUP BY tier, disposition
                """
            ).fetchall()
            total_row = conn.execute(
                "SELECT COUNT(*) AS c FROM defender_agent_decisions WHERE decision != 'skip'"
            ).fetchone()
            reviewed_row = conn.execute(
                "SELECT COUNT(*) AS c FROM defender_agent_decisions"
                " WHERE decision != 'skip' AND disposition IS NOT NULL"
            ).fetchone()
        total = int(total_row["c"]) if total_row else 0
        reviewed = int(reviewed_row["c"]) if reviewed_row else 0

        counts: dict[str, int] = {"true_positive": 0, "false_positive": 0, "inconclusive": 0}
        by_tier: dict[str, dict[str, int]] = {}
        for row in rows:
            tier_key = f"T{row['tier']}" if row["tier"] else "skip"
            disp = row["disposition"] or "unreviewed"
            cnt = int(row["c"])
            if disp in counts:
                counts[disp] += cnt
            if tier_key not in by_tier:
                by_tier[tier_key] = {}
            by_tier[tier_key][disp] = by_tier[tier_key].get(disp, 0) + cnt

        fp_rate = round(counts["false_positive"] / reviewed, 3) if reviewed > 0 else 0.0
        return {
            "total_actioned": total,
            "reviewed": reviewed,
            "unreviewed": total - reviewed,
            "true_positive": counts["true_positive"],
            "false_positive": counts["false_positive"],
            "inconclusive": counts["inconclusive"],
            "false_positive_rate": fp_rate,
            "by_tier": by_tier,
        }


    # -------------------------------------------------------------------------
    # Agent metrics
    # -------------------------------------------------------------------------

    def get_agent_metrics(self, days: int = 30) -> dict[str, Any]:
        """Return aggregate operational metrics for the agent over the last N days.

        Returns tier distribution, daily decision volumes, top affected entities,
        top alert titles, disposition summary, and FP rate trend.
        """
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        p = self._placeholder()
        with self._conn() as conn:
            # Tier / decision type distribution
            tier_rows = conn.execute(
                f"""
                SELECT decision, tier, COUNT(*) AS c
                  FROM defender_agent_decisions
                 WHERE executed_at >= {p}
                 GROUP BY decision, tier
                """,
                (since,),
            ).fetchall()

            # Daily decision volumes (all decisions)
            daily_rows = conn.execute(
                f"""
                SELECT SUBSTR(executed_at, 1, 10) AS day, COUNT(*) AS c
                  FROM defender_agent_decisions
                 WHERE executed_at >= {p}
                 GROUP BY day
                 ORDER BY day
                """,
                (since,),
            ).fetchall()

            # Top 10 most-affected entities (by number of decisions)
            entity_rows = conn.execute(
                f"""
                SELECT entities_json
                  FROM defender_agent_decisions
                 WHERE executed_at >= {p}
                """,
                (since,),
            ).fetchall()

            # Top 10 alert titles
            title_rows = conn.execute(
                f"""
                SELECT alert_title, COUNT(*) AS c
                  FROM defender_agent_decisions
                 WHERE executed_at >= {p}
                   AND alert_title IS NOT NULL AND alert_title != ''
                 GROUP BY alert_title
                 ORDER BY c DESC
                 LIMIT 10
                """,
                (since,),
            ).fetchall()

            # Disposition summary (non-skip only) for the period
            disp_rows = conn.execute(
                f"""
                SELECT disposition, COUNT(*) AS c
                  FROM defender_agent_decisions
                 WHERE executed_at >= {p}
                   AND decision != 'skip'
                 GROUP BY disposition
                """,
                (since,),
            ).fetchall()

            # Action type distribution
            action_rows = conn.execute(
                f"""
                SELECT action_type, COUNT(*) AS c
                  FROM defender_agent_decisions
                 WHERE executed_at >= {p}
                   AND action_type IS NOT NULL AND action_type != ''
                 GROUP BY action_type
                 ORDER BY c DESC
                 LIMIT 10
                """,
                (since,),
            ).fetchall()

        # Build tier distribution
        by_tier: dict[str, int] = {"T1": 0, "T2": 0, "T3": 0, "skip": 0}
        for row in tier_rows:
            dec = row["decision"]
            if dec == "skip":
                by_tier["skip"] += int(row["c"])
            elif dec == "execute":
                by_tier["T1"] += int(row["c"])
            elif dec == "queue":
                by_tier["T2"] += int(row["c"])
            elif dec == "recommend":
                by_tier["T3"] += int(row["c"])

        # Build daily volumes
        daily_volumes = [{"date": r["day"], "count": int(r["c"])} for r in daily_rows]

        # Aggregate entity counts from JSON blobs
        entity_counts: dict[str, dict[str, Any]] = {}
        for row in entity_rows:
            try:
                entities = json.loads(row["entities_json"] or "[]")
            except (json.JSONDecodeError, TypeError):
                continue
            for e in entities:
                key = str(e.get("id") or e.get("name") or "")
                if not key:
                    continue
                if key not in entity_counts:
                    entity_counts[key] = {"id": key, "name": e.get("name") or key, "type": e.get("type", ""), "count": 0}
                entity_counts[key]["count"] += 1
        top_entities = sorted(entity_counts.values(), key=lambda x: x["count"], reverse=True)[:10]

        # Top alert titles
        top_alert_titles = [{"title": r["alert_title"], "count": int(r["c"])} for r in title_rows]

        # Disposition summary
        disp_summary: dict[str, int] = {"true_positive": 0, "false_positive": 0, "inconclusive": 0, "unreviewed": 0}
        for row in disp_rows:
            key = row["disposition"] or "unreviewed"
            if key in disp_summary:
                disp_summary[key] += int(row["c"])
            else:
                disp_summary["unreviewed"] += int(row["c"])

        reviewed = disp_summary["true_positive"] + disp_summary["false_positive"] + disp_summary["inconclusive"]
        fp_rate = round(disp_summary["false_positive"] / reviewed, 3) if reviewed > 0 else 0.0

        # Action type distribution
        top_actions = [{"action": r["action_type"], "count": int(r["c"])} for r in action_rows]

        total = sum(by_tier.values())
        return {
            "period_days": days,
            "total_decisions": total,
            "by_tier": by_tier,
            "daily_volumes": daily_volumes,
            "top_entities": top_entities,
            "top_alert_titles": top_alert_titles,
            "disposition_summary": disp_summary,
            "false_positive_rate": fp_rate,
            "top_actions": top_actions,
        }


    # -------------------------------------------------------------------------
    # Rule overrides (Phase 17)
    # -------------------------------------------------------------------------

    def get_rule_overrides(self) -> dict[str, dict[str, Any]]:
        """Return {rule_id: override_dict} for all overridden rules."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM defender_agent_rule_overrides"
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            d = dict(row)
            d["disabled"] = bool(d.get("disabled", 0))
            result[d["rule_id"]] = d
        return result

    def upsert_rule_override(
        self,
        rule_id: str,
        *,
        disabled: bool = False,
        confidence_score: int | None = None,
        updated_by: str = "",
    ) -> dict[str, Any]:
        """Create or update a rule override. Returns the stored override dict."""
        p = self._placeholder()
        now = _now()
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO defender_agent_rule_overrides
                    (rule_id, disabled, confidence_score, updated_at, updated_by)
                VALUES ({p}, {p}, {p}, {p}, {p})
                ON CONFLICT(rule_id) DO UPDATE SET
                    disabled         = excluded.disabled,
                    confidence_score = excluded.confidence_score,
                    updated_at       = excluded.updated_at,
                    updated_by       = excluded.updated_by
                """,
                (rule_id, int(disabled), confidence_score, now, updated_by),
            )
            conn.commit()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM defender_agent_rule_overrides WHERE rule_id = {p}", (rule_id,)
            ).fetchone()
        d = dict(row)
        d["disabled"] = bool(d.get("disabled", 0))
        return d

    # -------------------------------------------------------------------------
    # Custom detection rules (Phase 18)
    # -------------------------------------------------------------------------

    def list_custom_rules(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM defender_agent_custom_rules WHERE enabled = 1 ORDER BY created_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM defender_agent_custom_rules ORDER BY created_at"
                ).fetchall()
        return [self._row_to_custom_rule(dict(r)) for r in rows]

    def create_custom_rule(
        self,
        *,
        name: str,
        match_field: str,
        match_value: str,
        match_mode: str = "contains",
        tier: int = 3,
        action_type: str = "start_investigation",
        confidence_score: int = 50,
        created_by: str = "",
        playbook_id: str | None = None,
    ) -> dict[str, Any]:
        rid = str(uuid.uuid4())
        p = self._placeholder()
        now = _now()
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO defender_agent_custom_rules
                    (id, name, match_field, match_value, match_mode, tier, action_type,
                     confidence_score, enabled, created_by, created_at, updated_at, playbook_id)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},1,{p},{p},{p},{p})
                """,
                (rid, name, match_field, match_value, match_mode, tier, action_type,
                 confidence_score, created_by, now, now, playbook_id),
            )
            conn.commit()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM defender_agent_custom_rules WHERE id = {p}", (rid,)
            ).fetchone()
        return self._row_to_custom_rule(dict(row))

    def delete_custom_rule(self, rule_id: str) -> bool:
        p = self._placeholder()
        with self._conn() as conn:
            cur = conn.execute(
                f"DELETE FROM defender_agent_custom_rules WHERE id = {p}", (rule_id,)
            )
            conn.commit()
        return (cur.rowcount or 0) > 0

    def toggle_custom_rule(self, rule_id: str, *, enabled: bool) -> dict[str, Any] | None:
        p = self._placeholder()
        now = _now()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE defender_agent_custom_rules SET enabled = {p}, updated_at = {p} WHERE id = {p}",
                (int(enabled), now, rule_id),
            )
            conn.commit()
            row = conn.execute(
                f"SELECT * FROM defender_agent_custom_rules WHERE id = {p}", (rule_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_custom_rule(dict(row))

    def update_custom_rule(self, rule_id: str, **kwargs: Any) -> dict[str, Any] | None:
        _allowed = {"name", "match_field", "match_value", "match_mode", "tier",
                    "action_type", "confidence_score", "playbook_id"}
        p = self._placeholder()
        now = _now()
        sets: list[str] = [f"updated_at = {p}"]
        vals: list[Any] = [now]
        for key, value in kwargs.items():
            if key not in _allowed:
                continue
            sets.append(f"{key} = {p}")
            vals.append(value)
        if len(sets) == 1:  # only updated_at — no real changes
            with self._conn() as conn:
                row = conn.execute(
                    f"SELECT * FROM defender_agent_custom_rules WHERE id = {p}", (rule_id,)
                ).fetchone()
            return self._row_to_custom_rule(dict(row)) if row else None
        vals.append(rule_id)
        sql = f"UPDATE defender_agent_custom_rules SET {', '.join(sets)} WHERE id = {p}"
        with self._conn() as conn:
            conn.execute(sql, vals)
            conn.commit()
            row = conn.execute(
                f"SELECT * FROM defender_agent_custom_rules WHERE id = {p}", (rule_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_custom_rule(dict(row))

    @staticmethod
    def _row_to_custom_rule(d: dict[str, Any]) -> dict[str, Any]:
        d["enabled"] = bool(d.get("enabled", 1))
        return d

    # -------------------------------------------------------------------------
    # Playbooks (Phase 20)
    # -------------------------------------------------------------------------

    def list_playbooks(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        import json as _json
        p = self._placeholder()
        with self._conn() as conn:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM defender_agent_playbooks WHERE enabled = 1 ORDER BY created_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM defender_agent_playbooks ORDER BY created_at"
                ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["enabled"] = bool(d.get("enabled", 1))
            try:
                d["actions"] = _json.loads(d.get("actions_json") or "[]")
            except Exception:
                d["actions"] = []
            result.append(d)
        return result

    def get_playbook(self, playbook_id: str) -> dict[str, Any] | None:
        import json as _json
        p = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM defender_agent_playbooks WHERE id = {p}", (playbook_id,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["enabled"] = bool(d.get("enabled", 1))
        try:
            d["actions"] = _json.loads(d.get("actions_json") or "[]")
        except Exception:
            d["actions"] = []
        return d

    def create_playbook(
        self,
        *,
        name: str,
        description: str = "",
        actions: list[str],
        created_by: str = "",
    ) -> dict[str, Any]:
        import json as _json
        pid = str(uuid.uuid4())
        p = self._placeholder()
        now = _now()
        actions_json = _json.dumps(actions)
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO defender_agent_playbooks
                    (id, name, description, actions_json, enabled, created_by, created_at, updated_at)
                VALUES ({p},{p},{p},{p},1,{p},{p},{p})
                """,
                (pid, name, description, actions_json, created_by, now, now),
            )
            conn.commit()
        return self.get_playbook(pid)  # type: ignore[return-value]

    def update_playbook(
        self,
        playbook_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        actions: list[str] | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any] | None:
        import json as _json
        p = self._placeholder()
        now = _now()
        sets: list[str] = [f"updated_at = {p}"]
        vals: list[Any] = [now]
        if name is not None:
            sets.append(f"name = {p}")
            vals.append(name)
        if description is not None:
            sets.append(f"description = {p}")
            vals.append(description)
        if actions is not None:
            sets.append(f"actions_json = {p}")
            vals.append(_json.dumps(actions))
        if enabled is not None:
            sets.append(f"enabled = {p}")
            vals.append(int(enabled))
        vals.append(playbook_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE defender_agent_playbooks SET {', '.join(sets)} WHERE id = {p}",
                vals,
            )
            conn.commit()
        return self.get_playbook(playbook_id)

    def delete_playbook(self, playbook_id: str) -> bool:
        p = self._placeholder()
        with self._conn() as conn:
            cur = conn.execute(
                f"DELETE FROM defender_agent_playbooks WHERE id = {p}", (playbook_id,)
            )
            conn.commit()
        return (cur.rowcount or 0) > 0

    def get_playbook_actions_map(self) -> dict[str, list[str]]:
        """Return {playbook_id: [action_type, ...]} for all enabled playbooks."""
        return {p["id"]: p["actions"] for p in self.list_playbooks(enabled_only=True)}

    def list_rules_for_playbook(self, playbook_id: str) -> list[dict[str, Any]]:
        p = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM defender_agent_custom_rules WHERE playbook_id = {p} ORDER BY created_at",
                (playbook_id,),
            ).fetchall()
        return [self._row_to_custom_rule(dict(r)) for r in rows]

    # -------------------------------------------------------------------------
    # Alert tagging (Phase 19)
    # -------------------------------------------------------------------------

    def add_decision_tag(self, decision_id: str, tag: str) -> dict[str, Any] | None:
        tag = (tag or "").strip().lower()
        if not tag:
            raise ValueError("tag cannot be empty")
        p = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT tags_json FROM defender_agent_decisions WHERE decision_id = {p}",
                (decision_id,),
            ).fetchone()
            if row is None:
                return None
            tags: list[str] = json.loads(row["tags_json"] or "[]")
            if tag not in tags:
                tags.append(tag)
                conn.execute(
                    f"UPDATE defender_agent_decisions SET tags_json = {p} WHERE decision_id = {p}",
                    (json.dumps(tags), decision_id),
                )
                conn.commit()
        return self.get_decision(decision_id)

    def remove_decision_tag(self, decision_id: str, tag: str) -> dict[str, Any] | None:
        tag = (tag or "").strip().lower()
        p = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT tags_json FROM defender_agent_decisions WHERE decision_id = {p}",
                (decision_id,),
            ).fetchone()
            if row is None:
                return None
            tags: list[str] = json.loads(row["tags_json"] or "[]")
            tags = [t for t in tags if t != tag]
            conn.execute(
                f"UPDATE defender_agent_decisions SET tags_json = {p} WHERE decision_id = {p}",
                (json.dumps(tags), decision_id),
            )
            conn.commit()
        return self.get_decision(decision_id)

    def list_known_tags(self) -> list[str]:
        """Return a deduplicated sorted list of all tags used across decisions."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT tags_json FROM defender_agent_decisions"
                " WHERE tags_json IS NOT NULL AND tags_json != '[]'"
            ).fetchall()
        tag_set: set[str] = set()
        for row in rows:
            for t in json.loads(row["tags_json"] or "[]"):
                if t:
                    tag_set.add(str(t))
        return sorted(tag_set)


    # -------------------------------------------------------------------------
    # Security runtime config (AI-05: site-wide model picker)
    # -------------------------------------------------------------------------

    def get_security_runtime_config(self) -> dict[str, Any]:
        """Return the current security site runtime config overrides."""
        try:
            with self._conn() as conn:
                rows = conn.execute("SELECT key, value FROM security_runtime_config").fetchall()
            return {row["key"]: row["value"] for row in rows}
        except Exception:
            return {}

    def set_security_runtime_config(self, key: str, value: str) -> None:
        """Upsert a security runtime config key."""
        p = self._placeholder()
        with self._conn() as conn:
            if self._use_postgres:
                conn.execute(
                    f"INSERT INTO security_runtime_config (key, value) VALUES ({p}, {p})"
                    f" ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (key, value),
                )
            else:
                conn.execute(
                    f"INSERT OR REPLACE INTO security_runtime_config (key, value) VALUES ({p}, {p})",
                    (key, value),
                )
            conn.commit()


defender_agent_store = DefenderAgentStore()
