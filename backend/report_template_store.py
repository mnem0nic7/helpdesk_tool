"""SQLite-backed persistence for saved report templates."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR
from models import ReportConfig, ReportTemplate
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

try:
    from psycopg import IntegrityError as PostgresIntegrityError
except ImportError:  # pragma: no cover - optional in some local test envs
    PostgresIntegrityError = sqlite3.IntegrityError


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row[1]) == column_name for row in rows)


_SEED_TEMPLATES: list[dict[str, Any]] = [
    {
        "seed_key": "primary-first-response-time",
        "site_scope": "primary",
        "name": "First Response Time",
        "category": "Operational",
        "description": "Track first-response performance with SLA response state and open-ticket detail.",
        "notes": "Ready for operational monitoring. This uses Jira's first-response SLA status; exact elapsed response minutes still live more naturally on the SLA page.",
        "readiness": "ready",
        "config": {
            "filters": {"open_only": True},
            "columns": [
                "key",
                "summary",
                "priority",
                "assignee",
                "created",
                "sla_first_response_status",
                "days_since_update",
            ],
            "sort_field": "created",
            "sort_dir": "desc",
            "group_by": "sla_first_response_status",
            "include_excluded": False,
        },
    },
    {
        "seed_key": "primary-response-followup-compliance",
        "site_scope": "primary",
        "name": "2-Hour Response & Daily Follow-Up",
        "category": "Operational",
        "description": "Track whether tickets receive an initial support response within 2 hours and at least one support follow-up every 24 hours until resolution.",
        "notes": "Tracks Jira first-response SLA plus Daily Public Follow-Up status from public JSM agent comments. Readiness becomes ready when the evaluated tickets have authoritative public-comment follow-up coverage in the local cache.",
        "readiness": "proxy",
        "include_in_master_export": False,
        "config": {
            "filters": {},
            "columns": [
                "key",
                "summary",
                "priority",
                "assignee",
                "status",
                "created",
                "resolved",
                "response_followup_status",
                "first_response_2h_status",
                "daily_followup_status",
                "last_support_touch_date",
                "support_touch_count",
            ],
            "sort_field": "created",
            "sort_dir": "desc",
            "group_by": "response_followup_status",
            "include_excluded": False,
        },
    },
    {
        "seed_key": "primary-mttr",
        "site_scope": "primary",
        "name": "Mean Time to Resolution",
        "category": "Executive",
        "description": "Resolved-ticket MTTR view with priority and service context.",
        "notes": "Ready. Change the grouping from priority to assignee or request type when you want team- or service-specific MTTR slices.",
        "readiness": "ready",
        "config": {
            "filters": {},
            "columns": [
                "key",
                "summary",
                "request_type",
                "priority",
                "assignee",
                "resolved",
                "calendar_ttr_hours",
            ],
            "sort_field": "resolved",
            "sort_dir": "desc",
            "group_by": "priority",
            "include_excluded": False,
        },
    },
    {
        "seed_key": "primary-fcr",
        "site_scope": "primary",
        "name": "First Contact Resolution",
        "category": "Quality",
        "description": "Starter FCR report using low comment volume as the current best proxy.",
        "notes": "Proxy. Exact first-contact resolution needs contact-cycle data; for now this template helps spot likely one-touch resolutions by request type and comment count.",
        "readiness": "proxy",
        "config": {
            "filters": {},
            "columns": [
                "key",
                "summary",
                "request_type",
                "assignee",
                "status",
                "resolution",
                "comment_count",
                "last_comment_author",
                "calendar_ttr_hours",
            ],
            "sort_field": "comment_count",
            "sort_dir": "asc",
            "group_by": "request_type",
            "include_excluded": False,
        },
    },
    {
        "seed_key": "primary-sla-compliance",
        "site_scope": "primary",
        "name": "SLA Compliance Rate",
        "category": "Executive",
        "description": "Resolution and first-response SLA compliance from the current ticket population.",
        "notes": "Ready. Grouping defaults to resolution SLA status because it is the most executive-friendly compliance view.",
        "readiness": "ready",
        "config": {
            "filters": {},
            "columns": [
                "key",
                "summary",
                "priority",
                "assignee",
                "created",
                "sla_first_response_status",
                "sla_resolution_status",
            ],
            "sort_field": "created",
            "sort_dir": "desc",
            "group_by": "sla_resolution_status",
            "include_excluded": False,
        },
    },
    {
        "seed_key": "primary-ticket-volume-category",
        "site_scope": "primary",
        "name": "Ticket Volume by Category",
        "category": "Executive",
        "description": "Incoming demand grouped by request type with supporting workflow detail.",
        "notes": "Ready. This is the cleanest current demand view for One Queue / One Catalog reporting.",
        "readiness": "ready",
        "config": {
            "filters": {},
            "columns": [
                "key",
                "summary",
                "request_type",
                "work_category",
                "priority",
                "status",
                "created",
                "reporter",
            ],
            "sort_field": "created",
            "sort_dir": "desc",
            "group_by": "request_type",
            "include_excluded": False,
        },
    },
    {
        "seed_key": "primary-backlog-aging",
        "site_scope": "primary",
        "name": "Backlog Size & Aging",
        "category": "Operational",
        "description": "Open-ticket backlog ordered by age and staleness.",
        "notes": "Ready. Use this as the primary operational cleanup queue and change the grouping to assignee when you want ownership review.",
        "readiness": "ready",
        "config": {
            "filters": {"open_only": True},
            "columns": [
                "key",
                "summary",
                "status",
                "priority",
                "assignee",
                "age_days",
                "days_since_update",
                "created",
                "updated",
            ],
            "sort_field": "age_days",
            "sort_dir": "desc",
            "group_by": "status",
            "include_excluded": False,
        },
    },
    {
        "seed_key": "primary-reopen-rate",
        "site_scope": "primary",
        "name": "Reopen Rate",
        "category": "Optimization",
        "description": "Review template reserved for reopen analysis once ticket-history signals are available.",
        "notes": "Gap. Exact reopen rate needs Jira status-history or changelog ingestion; this starter view highlights recently touched resolved work for manual review until that feed is added.",
        "readiness": "gap",
        "config": {
            "filters": {},
            "columns": [
                "key",
                "summary",
                "status",
                "resolution",
                "assignee",
                "resolved",
                "updated",
                "comment_count",
            ],
            "sort_field": "updated",
            "sort_dir": "desc",
            "group_by": "resolution",
            "include_excluded": False,
        },
    },
    {
        "seed_key": "primary-escalation-rate",
        "site_scope": "primary",
        "name": "Escalation Rate",
        "category": "Operational",
        "description": "Starter escalation review slice for tickets likely needing Tier 2 or Tier 3 attention.",
        "notes": "Gap. Exact escalation rate needs assignment-tier history or escalation markers; this report is a manual-review bridge until those signals are captured.",
        "readiness": "gap",
        "config": {
            "filters": {},
            "columns": [
                "key",
                "summary",
                "request_type",
                "priority",
                "assignee",
                "work_category",
                "updated",
                "comment_count",
            ],
            "sort_field": "updated",
            "sort_dir": "desc",
            "group_by": "assignee",
            "include_excluded": False,
        },
    },
    {
        "seed_key": "primary-agent-utilization",
        "site_scope": "primary",
        "name": "Agent Utilization",
        "category": "Capacity",
        "description": "Assignee workload and resolution mix for capacity review.",
        "notes": "Proxy. This is a strong operational workload view, but exact utilization still requires time-tracking or activity-based effort data.",
        "readiness": "proxy",
        "config": {
            "filters": {},
            "columns": [
                "key",
                "summary",
                "assignee",
                "status",
                "priority",
                "age_days",
                "calendar_ttr_hours",
                "updated",
            ],
            "sort_field": "updated",
            "sort_dir": "desc",
            "group_by": "assignee",
            "include_excluded": False,
        },
    },
    {
        "seed_key": "primary-csat",
        "site_scope": "primary",
        "name": "Customer Satisfaction (CSAT)",
        "category": "Experience",
        "description": "Reserved template for CSAT-linked reporting once survey data is available.",
        "notes": "Gap. Exact CSAT needs survey data in the ticket dataset; this template is a placeholder so the reporting surface is ready when that feed is connected.",
        "readiness": "gap",
        "config": {
            "filters": {},
            "columns": [
                "key",
                "summary",
                "reporter",
                "assignee",
                "status",
                "resolved",
                "request_type",
                "comment_count",
            ],
            "sort_field": "resolved",
            "sort_dir": "desc",
            "group_by": "assignee",
            "include_excluded": False,
        },
    },
]


class ReportTemplateStore:
    """Persist saved report templates by site scope."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "report_templates.db")
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()
        self._sync_seed_templates()

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
            row = conn.execute("SELECT COUNT(*) AS count FROM report_templates").fetchone()
            if row and int(row["count"]) > 0:
                return
        with self._sqlite_conn() as sqlite_conn:
            template_rows = sqlite_conn.execute("SELECT * FROM report_templates").fetchall()
            deleted_seed_rows = sqlite_conn.execute("SELECT * FROM deleted_seed_keys").fetchall()
        with self._conn() as conn:
            if template_rows:
                conn.executemany(
                    """
                    INSERT INTO report_templates (
                        id, seed_key, site_scope, name, description, category, notes, readiness, is_seed,
                        include_in_master_export, config_json, created_by_email, created_by_name, updated_by_email,
                        updated_by_name, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    [
                        (
                            row["id"],
                            row["seed_key"],
                            row["site_scope"],
                            row["name"],
                            row["description"],
                            row["category"],
                            row["notes"],
                            row["readiness"],
                            row["is_seed"],
                            row["include_in_master_export"],
                            row["config_json"],
                            row["created_by_email"],
                            row["created_by_name"],
                            row["updated_by_email"],
                            row["updated_by_name"],
                            row["created_at"],
                            row["updated_at"],
                        )
                        for row in template_rows
                    ],
                )
            if deleted_seed_rows:
                conn.executemany(
                    """
                    INSERT INTO deleted_seed_keys (seed_key, deleted_at)
                    VALUES (%s, %s)
                    ON CONFLICT(seed_key) DO NOTHING
                    """,
                    [(row["seed_key"], row["deleted_at"]) for row in deleted_seed_rows],
                )

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            self._backfill_from_sqlite_if_needed()
            return
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS report_templates (
                    id TEXT PRIMARY KEY,
                    seed_key TEXT UNIQUE,
                    site_scope TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    readiness TEXT NOT NULL DEFAULT 'custom',
                    is_seed INTEGER NOT NULL DEFAULT 0,
                    include_in_master_export INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT NOT NULL,
                    created_by_email TEXT NOT NULL DEFAULT '',
                    created_by_name TEXT NOT NULL DEFAULT '',
                    updated_by_email TEXT NOT NULL DEFAULT '',
                    updated_by_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(site_scope, name)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deleted_seed_keys (
                    seed_key TEXT PRIMARY KEY,
                    deleted_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_report_templates_scope
                ON report_templates(site_scope, category, name)
                """
            )
            if not _column_exists(conn, "report_templates", "include_in_master_export"):
                conn.execute(
                    """
                    ALTER TABLE report_templates
                    ADD COLUMN include_in_master_export INTEGER NOT NULL DEFAULT 1
                    """
                )

    def _row_to_template(self, row: sqlite3.Row) -> ReportTemplate:
        payload = dict(row)
        payload["is_seed"] = bool(payload.get("is_seed"))
        payload["include_in_master_export"] = bool(payload.get("include_in_master_export", 1))
        payload["config"] = ReportConfig(**json.loads(str(payload.get("config_json") or "{}")))
        payload.pop("config_json", None)
        payload.pop("seed_key", None)
        return ReportTemplate(**payload)

    def _sync_seed_templates(self) -> None:
        now = _utcnow()
        with self._conn() as conn:
            deleted_seed_keys = {
                str(row["seed_key"] if hasattr(row, "keys") else row[0])
                for row in conn.execute("SELECT seed_key FROM deleted_seed_keys").fetchall()
            }
            for template in _SEED_TEMPLATES:
                seed_key = str(template["seed_key"])
                if seed_key in deleted_seed_keys:
                    continue
                seed_query = (
                    "SELECT id, created_at FROM report_templates WHERE seed_key = %s"
                    if self._use_postgres
                    else
                    "SELECT id, created_at FROM report_templates WHERE seed_key = ?"
                )
                existing = conn.execute(
                    seed_query,
                    (seed_key,),
                ).fetchone()
                if existing is not None:
                    continue
                config_json = json.dumps(template["config"], sort_keys=True)
                try:
                    insert_query = """
                        INSERT INTO report_templates (
                            id, seed_key, site_scope, name, description, category, notes,
                            readiness, is_seed, include_in_master_export, config_json, created_by_email, created_by_name,
                            updated_by_email, updated_by_name, created_at, updated_at
                        ) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 1, {placeholder}, {placeholder}, '', 'System', '', 'System', {placeholder}, {placeholder})
                    """.replace("{placeholder}", "%s" if self._use_postgres else "?")
                    conn.execute(
                        insert_query,
                        (
                            seed_key,
                            seed_key,
                            template["site_scope"],
                            template["name"],
                            template["description"],
                            template["category"],
                            template["notes"],
                            template["readiness"],
                            1 if template.get("include_in_master_export", True) else 0,
                            config_json,
                            now,
                            now,
                        ),
                    )
                except (sqlite3.IntegrityError, PostgresIntegrityError):
                    # If a user already created a template with the same site/name, keep
                    # their version and skip the built-in insert.
                    continue

    def list_templates(self, site_scope: str) -> list[ReportTemplate]:
        with self._conn() as conn:
            query = """
                SELECT *
                FROM report_templates
                WHERE site_scope = {placeholder}
                ORDER BY category ASC, name ASC
            """.replace("{placeholder}", "%s" if self._use_postgres else "?")
            rows = conn.execute(
                query,
                (site_scope,),
            ).fetchall()
        return [self._row_to_template(row) for row in rows]

    def get_template(self, template_id: str, site_scope: str) -> ReportTemplate | None:
        with self._conn() as conn:
            query = "SELECT * FROM report_templates WHERE id = {placeholder} AND site_scope = {placeholder}".replace(
                "{placeholder}",
                "%s" if self._use_postgres else "?",
            )
            row = conn.execute(
                query,
                (template_id, site_scope),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_template(row)

    def create_template(
        self,
        *,
        site_scope: str,
        name: str,
        description: str,
        category: str,
        notes: str,
        include_in_master_export: bool,
        config: ReportConfig,
        actor_email: str,
        actor_name: str,
    ) -> ReportTemplate:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Template name is required")
        template_id = uuid.uuid4().hex
        now = _utcnow()
        try:
            with self._conn() as conn:
                query = """
                    INSERT INTO report_templates (
                        id, seed_key, site_scope, name, description, category, notes,
                        readiness, is_seed, include_in_master_export, config_json, created_by_email, created_by_name,
                        updated_by_email, updated_by_name, created_at, updated_at
                    ) VALUES ({placeholder}, NULL, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 'custom', 0, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
                """.replace("{placeholder}", "%s" if self._use_postgres else "?")
                conn.execute(
                    query,
                    (
                        template_id,
                        site_scope,
                        normalized_name,
                        description.strip(),
                        category.strip(),
                        notes.strip(),
                        1 if include_in_master_export else 0,
                        config.model_dump_json(),
                        actor_email.strip(),
                        actor_name.strip(),
                        actor_email.strip(),
                        actor_name.strip(),
                        now,
                        now,
                    ),
                )
        except (sqlite3.IntegrityError, PostgresIntegrityError) as exc:
            raise ValueError(f"A template named '{normalized_name}' already exists on this site.") from exc
        created = self.get_template(template_id, site_scope)
        if created is None:
            raise RuntimeError("Failed to load created report template")
        return created

    def update_template(
        self,
        *,
        template_id: str,
        site_scope: str,
        name: str,
        description: str,
        category: str,
        notes: str,
        include_in_master_export: bool,
        config: ReportConfig,
        actor_email: str,
        actor_name: str,
    ) -> ReportTemplate:
        existing = self.get_template(template_id, site_scope)
        if existing is None:
            raise KeyError("Template not found")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Template name is required")
        try:
            with self._conn() as conn:
                query = """
                    UPDATE report_templates
                    SET name = {placeholder},
                        description = {placeholder},
                        category = {placeholder},
                        notes = {placeholder},
                        include_in_master_export = {placeholder},
                        config_json = {placeholder},
                        updated_by_email = {placeholder},
                        updated_by_name = {placeholder},
                        updated_at = {placeholder}
                    WHERE id = {placeholder} AND site_scope = {placeholder}
                """.replace("{placeholder}", "%s" if self._use_postgres else "?")
                conn.execute(
                    query,
                    (
                        normalized_name,
                        description.strip(),
                        category.strip(),
                        notes.strip(),
                        1 if include_in_master_export else 0,
                        config.model_dump_json(),
                        actor_email.strip(),
                        actor_name.strip(),
                        _utcnow(),
                        template_id,
                        site_scope,
                    ),
                )
        except (sqlite3.IntegrityError, PostgresIntegrityError) as exc:
            raise ValueError(f"A template named '{normalized_name}' already exists on this site.") from exc
        updated = self.get_template(template_id, site_scope)
        if updated is None:
            raise RuntimeError("Failed to load updated report template")
        return updated

    def delete_template(self, template_id: str, site_scope: str) -> None:
        with self._conn() as conn:
            select_query = "SELECT seed_key FROM report_templates WHERE id = {placeholder} AND site_scope = {placeholder}".replace(
                "{placeholder}",
                "%s" if self._use_postgres else "?",
            )
            existing = conn.execute(
                select_query,
                (template_id, site_scope),
            ).fetchone()
            if existing is None:
                raise KeyError("Template not found")
            seed_key = str(existing["seed_key"] or "").strip()
            if seed_key:
                deleted_query = """
                    INSERT INTO deleted_seed_keys (seed_key, deleted_at)
                    VALUES ({placeholder}, {placeholder})
                    ON CONFLICT(seed_key) DO UPDATE SET deleted_at = excluded.deleted_at
                """.replace("{placeholder}", "%s" if self._use_postgres else "?")
                conn.execute(
                    deleted_query,
                    (seed_key, _utcnow()),
                )
            delete_query = "DELETE FROM report_templates WHERE id = {placeholder} AND site_scope = {placeholder}".replace(
                "{placeholder}",
                "%s" if self._use_postgres else "?",
            )
            conn.execute(
                delete_query,
                (template_id, site_scope),
            )

    def set_master_export_inclusion(
        self,
        *,
        template_id: str,
        site_scope: str,
        include_in_master_export: bool,
        actor_email: str,
        actor_name: str,
    ) -> ReportTemplate:
        existing = self.get_template(template_id, site_scope)
        if existing is None:
            raise KeyError("Template not found")
        with self._conn() as conn:
            query = """
                UPDATE report_templates
                SET include_in_master_export = {placeholder},
                    updated_by_email = {placeholder},
                    updated_by_name = {placeholder},
                    updated_at = {placeholder}
                WHERE id = {placeholder} AND site_scope = {placeholder}
            """.replace("{placeholder}", "%s" if self._use_postgres else "?")
            conn.execute(
                query,
                (
                    1 if include_in_master_export else 0,
                    actor_email.strip(),
                    actor_name.strip(),
                    _utcnow(),
                    template_id,
                    site_scope,
                ),
            )
        updated = self.get_template(template_id, site_scope)
        if updated is None:
            raise RuntimeError("Failed to load updated report template")
        return updated


report_template_store = ReportTemplateStore()
