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
                     updated_at, updated_by)
                VALUES (1, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                ON CONFLICT(id) DO UPDATE SET
                    enabled                    = excluded.enabled,
                    min_severity               = excluded.min_severity,
                    tier2_delay_minutes        = excluded.tier2_delay_minutes,
                    dry_run                    = excluded.dry_run,
                    entity_cooldown_hours      = excluded.entity_cooldown_hours,
                    alert_dedup_window_minutes = excluded.alert_dedup_window_minutes,
                    min_confidence             = excluded.min_confidence,
                    updated_at                 = excluded.updated_at,
                    updated_by                 = excluded.updated_by
                """,
                (int(enabled), min_severity, tier2_delay_minutes, int(dry_run),
                 entity_cooldown_hours, alert_dedup_window_minutes, min_confidence, now, updated_by),
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
                    confidence_score
                ) VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})
                """,
                (
                    decision_id, run_id, alert_id, alert_title, alert_severity,
                    alert_category, alert_created_at, service_source,
                    json.dumps(entities), tier, decision, action_type,
                    json.dumps(ats), json.dumps(job_ids), reason, now, not_before_at,
                    json.dumps(alert_raw) if alert_raw else "",
                    json.dumps(mitre_techniques or []),
                    confidence_score,
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
        return d


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


defender_agent_store = DefenderAgentStore()
