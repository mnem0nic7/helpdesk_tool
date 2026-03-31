"""Persistent AI summary generation for report templates."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Sequence

from ai_background_worker import background_ai_worker
from ai_client import get_available_models, invoke_model_text, select_available_ollama_model
from config import DATA_DIR, OLLAMA_MODEL, REPORT_AI_SUMMARY_MODEL, REPORT_AI_SUMMARY_NIGHTLY_HOUR_UTC
from issue_cache import cache
from models import (
    ReportAISummary,
    ReportAISummaryBatchItem,
    ReportAISummaryBatchStartResponse,
    ReportAISummaryBatchStatus,
    ReportTemplate,
)
from report_template_store import report_template_store
from report_workbook_builder import ReportWorkbookBuilder, resolve_report_window_spec
from site_context import filter_issues_for_scope
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_REPORT_AI_SUMMARY_PROMPT_VERSION = "v2_7day_master_exec_focus"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _summary_db_path() -> str:
    return str(Path(DATA_DIR) / "report_ai_summaries.db")


def _ensure_data_dir() -> None:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def _clean_text(value: str, *, max_length: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _normalize_summary_text(raw: Any, *, max_length: int) -> str:
    text = str(raw or "")
    text = re.sub(r"(?m)^\s*(?:[•*\-]|\d+[.)])\s*", "", text)
    text = re.sub(r"\s*\n+\s*", " ", text)
    return _clean_text(text, max_length=max_length)


def _normalize_bullets(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    bullets: list[str] = []
    for item in raw:
        text = _clean_text(str(item or ""), max_length=220)
        if text:
            bullets.append(text)
    return bullets[:4]


def _rewrite_finding_as_sentence(value: Any) -> str:
    text = _normalize_summary_text(value, max_length=320).lstrip("🟢🟡🔴⚠️ ").strip()
    replacements = {
        "SLA Compliance: ": "Over the last 7 days, SLA compliance was ",
        "MTTR Tail Risk: overall 7d P95 is ": "MTTR remained a watch area, with the overall 7-day P95 at ",
        "Response Discipline: ": "Response discipline was mixed: ",
        "Backlog: ": "Backlog now sits at ",
        "Data Quality: ": "Data quality note: ",
    }
    for prefix, replacement in replacements.items():
        if text.startswith(prefix):
            return replacement + text[len(prefix) :]
    return text


def _build_conversational_fallback_summary(findings: Sequence[str], *, template_name: str) -> str:
    sentences = [
        _rewrite_finding_as_sentence(item)
        for item in findings
        if str(item or "").strip()
    ]
    if not sentences:
        return _clean_text(f"{template_name}: report summary unavailable.", max_length=240)

    summary = sentences[0]
    for sentence in sentences[1:]:
        candidate = _clean_text(f"{summary} {sentence}", max_length=240)
        if candidate == summary:
            break
        summary = candidate
        if len(summary) >= 220:
            break
    return summary


def _extract_json_object(raw: str) -> dict[str, Any]:
    payload = str(raw or "").strip()
    if not payload:
        raise ValueError("Empty AI response")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        start = payload.find("{")
        end = payload.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(payload[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("AI response must decode to an object")
    return data


def _split_data_version(value: str) -> tuple[str, str]:
    refresh_token, _, prompt_version = str(value or "").partition("|")
    return refresh_token.strip(), prompt_version.strip()


@dataclass
class _SummaryGenerationResult:
    status: str
    source: str
    summary: str
    bullets: list[str]
    fallback_used: bool
    model_used: str
    generated_at: str
    template_version: str
    data_version: str
    error: str = ""


class ReportAISummaryService:
    """Manage cached report AI summaries and manual generation batches."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _summary_db_path()
        self._use_postgres = postgres_enabled() and db_path is None
        self._nightly_task: asyncio.Task[None] | None = None
        self._batch_tasks: set[asyncio.Task[Any]] = set()
        self._stop_event: asyncio.Event | None = None
        self._last_nightly_run_day: str | None = None
        self._init_db()

    def _sqlite_connect(self) -> sqlite3.Connection:
        _ensure_data_dir()
        return connect_sqlite(self._db_path)

    def _connect(self):
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return self._sqlite_connect()

    def _backfill_from_sqlite_if_needed(self) -> None:
        if not self._use_postgres or not Path(self._db_path).exists():
            return
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM report_ai_summaries").fetchone()
            if row and int(row["count"]) > 0:
                return
        with self._sqlite_connect() as sqlite_conn:
            summary_rows = sqlite_conn.execute("SELECT * FROM report_ai_summaries").fetchall()
            batch_rows = sqlite_conn.execute("SELECT * FROM report_ai_summary_batches").fetchall()
            batch_item_rows = sqlite_conn.execute("SELECT * FROM report_ai_summary_batch_items").fetchall()
        with self._connect() as conn:
            if summary_rows:
                conn.executemany(
                    """
                    INSERT INTO report_ai_summaries (
                        site_scope, template_id, template_name, source, status, summary, bullets_json, fallback_used,
                        model_used, generated_at, template_version, data_version, error, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(site_scope, template_id, source) DO NOTHING
                    """,
                    [
                        (
                            row["site_scope"],
                            row["template_id"],
                            row["template_name"],
                            row["source"],
                            row["status"],
                            row["summary"],
                            row["bullets_json"],
                            row["fallback_used"],
                            row["model_used"],
                            row["generated_at"],
                            row["template_version"],
                            row["data_version"],
                            row["error"],
                            row["created_at"],
                            row["updated_at"],
                        )
                        for row in summary_rows
                    ],
                )
            if batch_rows:
                conn.executemany(
                    """
                    INSERT INTO report_ai_summary_batches (
                        batch_id, site_scope, status, requested_at, started_at, completed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT(batch_id) DO NOTHING
                    """,
                    [
                        (
                            row["batch_id"],
                            row["site_scope"],
                            row["status"],
                            row["requested_at"],
                            row["started_at"],
                            row["completed_at"],
                        )
                        for row in batch_rows
                    ],
                )
            if batch_item_rows:
                conn.executemany(
                    """
                    INSERT INTO report_ai_summary_batch_items (
                        batch_id, template_id, template_name, source, status, summary, bullets_json,
                        fallback_used, model_used, generated_at, error
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(batch_id, template_id) DO NOTHING
                    """,
                    [
                        (
                            row["batch_id"],
                            row["template_id"],
                            row["template_name"],
                            row["source"],
                            row["status"],
                            row["summary"],
                            row["bullets_json"],
                            row["fallback_used"],
                            row["model_used"],
                            row["generated_at"],
                            row["error"],
                        )
                        for row in batch_item_rows
                    ],
                )

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            self._backfill_from_sqlite_if_needed()
            return
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS report_ai_summaries (
                    site_scope TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    template_name TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ready',
                    summary TEXT NOT NULL DEFAULT '',
                    bullets_json TEXT NOT NULL DEFAULT '[]',
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    model_used TEXT NOT NULL DEFAULT '',
                    generated_at TEXT,
                    template_version TEXT NOT NULL DEFAULT '',
                    data_version TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (site_scope, template_id, source)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS report_ai_summary_batches (
                    batch_id TEXT PRIMARY KEY,
                    site_scope TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    requested_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS report_ai_summary_batch_items (
                    batch_id TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    template_name TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    status TEXT NOT NULL DEFAULT 'queued',
                    summary TEXT NOT NULL DEFAULT '',
                    bullets_json TEXT NOT NULL DEFAULT '[]',
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    model_used TEXT NOT NULL DEFAULT '',
                    generated_at TEXT,
                    error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (batch_id, template_id)
                )
                """
            )

    async def start_worker(self) -> None:
        if self._nightly_task and not self._nightly_task.done():
            return
        self._stop_event = asyncio.Event()
        self._nightly_task = asyncio.create_task(self._nightly_loop())

    async def stop_worker(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        task = self._nightly_task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._nightly_task = None
        batch_tasks = list(self._batch_tasks)
        for task in batch_tasks:
            if not task.done():
                task.cancel()
        if batch_tasks:
            await asyncio.gather(*batch_tasks, return_exceptions=True)
        self._batch_tasks.clear()

    def _register_task(self, task: asyncio.Task[Any]) -> None:
        self._batch_tasks.add(task)
        task.add_done_callback(self._batch_tasks.discard)

    def _current_data_version(self) -> str:
        return f"{cache.status().get('last_refresh') or ''}|{_REPORT_AI_SUMMARY_PROMPT_VERSION}"

    def _template_summary_is_current(
        self,
        summary: ReportAISummary,
        *,
        template: ReportTemplate,
        data_version: str,
    ) -> bool:
        summary_refresh_token, summary_prompt_version = _split_data_version(summary.data_version)
        current_refresh_token, current_prompt_version = _split_data_version(data_version)
        data_version_matches = summary.data_version == data_version
        if summary_prompt_version and current_prompt_version and summary_prompt_version == current_prompt_version:
            if current_refresh_token:
                data_version_matches = summary_refresh_token == current_refresh_token
            else:
                # Reuse the latest stored summary after a cold start when the
                # persisted Jira refresh token has not been reloaded yet.
                data_version_matches = True
        return (
            summary.template_version == template.updated_at
            and data_version_matches
            and summary.status in {"ready", "fallback"}
        )

    def _summary_from_row(self, row: sqlite3.Row) -> ReportAISummary:
        bullets = json.loads(str(row["bullets_json"] or "[]"))
        return ReportAISummary(
            template_id=str(row["template_id"] or ""),
            template_name=str(row["template_name"] or ""),
            site_scope=str(row["site_scope"] or ""),
            source=str(row["source"] or "manual"),
            status=str(row["status"] or "ready"),
            summary=str(row["summary"] or ""),
            bullets=[str(item) for item in bullets if str(item or "").strip()],
            fallback_used=bool(row["fallback_used"]),
            model_used=str(row["model_used"] or ""),
            generated_at=str(row["generated_at"] or "") or None,
            template_version=str(row["template_version"] or ""),
            data_version=str(row["data_version"] or ""),
            error=str(row["error"] or ""),
        )

    def _batch_item_from_row(self, row: sqlite3.Row) -> ReportAISummaryBatchItem:
        bullets = json.loads(str(row["bullets_json"] or "[]"))
        return ReportAISummaryBatchItem(
            template_id=str(row["template_id"] or ""),
            template_name=str(row["template_name"] or ""),
            status=str(row["status"] or "queued"),
            source=str(row["source"] or "manual"),
            summary=str(row["summary"] or ""),
            bullets=[str(item) for item in bullets if str(item or "").strip()],
            fallback_used=bool(row["fallback_used"]),
            model_used=str(row["model_used"] or ""),
            generated_at=str(row["generated_at"] or "") or None,
            error=str(row["error"] or ""),
        )

    def list_current_summaries(self, site_scope: str) -> list[ReportAISummary]:
        if site_scope != "primary":
            return []
        templates = report_template_store.list_templates(site_scope)
        if not templates:
            return []
        templates_by_id = {template.id: template for template in templates}
        data_version = self._current_data_version()
        with self._connect() as conn:
            query = """
                SELECT *
                FROM report_ai_summaries
                WHERE site_scope = {placeholder}
            """.replace("{placeholder}", "%s" if self._use_postgres else "?")
            rows = conn.execute(
                query,
                (site_scope,),
            ).fetchall()
        latest: dict[tuple[str, str], ReportAISummary] = {}
        for row in rows:
            summary = self._summary_from_row(row)
            latest[(summary.template_id, summary.source)] = summary

        current: list[ReportAISummary] = []
        for template in templates:
            source = "manual" if template.include_in_master_export else "nightly"
            summary = latest.get((template.id, source))
            if summary and self._template_summary_is_current(summary, template=template, data_version=data_version):
                current.append(summary)
        return current

    def get_current_master_summaries(self, site_scope: str, templates: Sequence[ReportTemplate]) -> dict[str, ReportAISummary]:
        if site_scope != "primary":
            return {}
        data_version = self._current_data_version()
        with self._connect() as conn:
            query = """
                SELECT *
                FROM report_ai_summaries
                WHERE site_scope = {placeholder}
                  AND source = 'manual'
            """.replace("{placeholder}", "%s" if self._use_postgres else "?")
            rows = conn.execute(
                query,
                (site_scope,),
            ).fetchall()
        summaries_by_id = {
            summary.template_id: summary
            for summary in (self._summary_from_row(row) for row in rows)
        }
        current: dict[str, ReportAISummary] = {}
        for template in templates:
            if not template.include_in_master_export:
                continue
            summary = summaries_by_id.get(template.id)
            if summary and self._template_summary_is_current(summary, template=template, data_version=data_version):
                current[template.id] = summary
        return current

    def _upsert_summary(
        self,
        *,
        site_scope: str,
        template: ReportTemplate,
        result: _SummaryGenerationResult,
    ) -> ReportAISummary:
        now = _utcnow_iso()
        with self._connect() as conn:
            query = """
                INSERT INTO report_ai_summaries (
                    site_scope,
                    template_id,
                    template_name,
                    source,
                    status,
                    summary,
                    bullets_json,
                    fallback_used,
                    model_used,
                    generated_at,
                    template_version,
                    data_version,
                    error,
                    created_at,
                    updated_at
                ) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
                ON CONFLICT(site_scope, template_id, source) DO UPDATE SET
                    template_name = excluded.template_name,
                    status = excluded.status,
                    summary = excluded.summary,
                    bullets_json = excluded.bullets_json,
                    fallback_used = excluded.fallback_used,
                    model_used = excluded.model_used,
                    generated_at = excluded.generated_at,
                    template_version = excluded.template_version,
                    data_version = excluded.data_version,
                    error = excluded.error,
                    updated_at = excluded.updated_at
            """.replace("{placeholder}", "%s" if self._use_postgres else "?")
            conn.execute(
                query,
                (
                    site_scope,
                    template.id,
                    template.name,
                    result.source,
                    result.status,
                    result.summary,
                    json.dumps(result.bullets),
                    1 if result.fallback_used else 0,
                    result.model_used,
                    result.generated_at,
                    result.template_version,
                    result.data_version,
                    result.error,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM report_ai_summaries
                WHERE site_scope = {placeholder}
                  AND template_id = {placeholder}
                  AND source = {placeholder}
                """.replace("{placeholder}", "%s" if self._use_postgres else "?"),
                (site_scope, template.id, result.source),
            ).fetchone()
        assert row is not None
        return self._summary_from_row(row)

    def _create_batch(self, *, site_scope: str, templates: Sequence[ReportTemplate]) -> ReportAISummaryBatchStartResponse:
        batch_id = uuid.uuid4().hex
        requested_at = _utcnow_iso()
        with self._connect() as conn:
            batch_query = """
                INSERT INTO report_ai_summary_batches (batch_id, site_scope, status, requested_at)
                VALUES ({placeholder}, {placeholder}, 'queued', {placeholder})
            """.replace("{placeholder}", "%s" if self._use_postgres else "?")
            conn.execute(
                batch_query,
                (batch_id, site_scope, requested_at),
            )
            item_query = """
                INSERT INTO report_ai_summary_batch_items (
                    batch_id,
                    template_id,
                    template_name,
                    source,
                    status
                ) VALUES ({placeholder}, {placeholder}, {placeholder}, 'manual', 'queued')
            """.replace("{placeholder}", "%s" if self._use_postgres else "?")
            conn.executemany(
                item_query,
                [(batch_id, template.id, template.name) for template in templates],
            )
        return ReportAISummaryBatchStartResponse(
            batch_id=batch_id,
            site_scope=site_scope,
            status="queued",
            item_count=len(templates),
            requested_at=requested_at,
        )

    def _update_batch(
        self,
        batch_id: str,
        *,
        status: str,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        with self._connect() as conn:
            query = """
                UPDATE report_ai_summary_batches
                SET status = {placeholder},
                    started_at = COALESCE({placeholder}, started_at),
                    completed_at = COALESCE({placeholder}, completed_at)
                WHERE batch_id = {placeholder}
            """.replace("{placeholder}", "%s" if self._use_postgres else "?")
            conn.execute(
                query,
                (status, started_at, completed_at, batch_id),
            )

    def _update_batch_item(
        self,
        batch_id: str,
        template_id: str,
        *,
        status: str,
        summary: str = "",
        bullets: Sequence[str] | None = None,
        fallback_used: bool = False,
        model_used: str = "",
        generated_at: str | None = None,
        error: str = "",
    ) -> None:
        with self._connect() as conn:
            query = """
                UPDATE report_ai_summary_batch_items
                SET status = {placeholder},
                    summary = {placeholder},
                    bullets_json = {placeholder},
                    fallback_used = {placeholder},
                    model_used = {placeholder},
                    generated_at = {placeholder},
                    error = {placeholder}
                WHERE batch_id = {placeholder}
                  AND template_id = {placeholder}
            """.replace("{placeholder}", "%s" if self._use_postgres else "?")
            conn.execute(
                query,
                (
                    status,
                    summary,
                    json.dumps(list(bullets or [])),
                    1 if fallback_used else 0,
                    model_used,
                    generated_at,
                    error,
                    batch_id,
                    template_id,
                ),
            )

    def _batch_status_from_rows(self, batch_row: sqlite3.Row, item_rows: Sequence[sqlite3.Row]) -> ReportAISummaryBatchStatus:
        items = [self._batch_item_from_row(row) for row in item_rows]
        return ReportAISummaryBatchStatus(
            batch_id=str(batch_row["batch_id"] or ""),
            site_scope=str(batch_row["site_scope"] or ""),
            status=str(batch_row["status"] or "queued"),
            item_count=len(items),
            requested_at=str(batch_row["requested_at"] or ""),
            started_at=str(batch_row["started_at"] or "") or None,
            completed_at=str(batch_row["completed_at"] or "") or None,
            items=items,
        )

    def get_batch_status(self, batch_id: str, site_scope: str) -> ReportAISummaryBatchStatus:
        with self._connect() as conn:
            batch_query = """
                SELECT *
                FROM report_ai_summary_batches
                WHERE batch_id = {placeholder}
                  AND site_scope = {placeholder}
            """.replace("{placeholder}", "%s" if self._use_postgres else "?")
            batch_row = conn.execute(
                batch_query,
                (batch_id, site_scope),
            ).fetchone()
            if batch_row is None:
                raise KeyError(batch_id)
            item_query = """
                SELECT *
                FROM report_ai_summary_batch_items
                WHERE batch_id = {placeholder}
                ORDER BY lower(template_name)
            """.replace("{placeholder}", "%s" if self._use_postgres else "?")
            item_rows = conn.execute(
                item_query,
                (batch_id,),
            ).fetchall()
        return self._batch_status_from_rows(batch_row, item_rows)

    async def start_manual_batch(self, site_scope: str) -> ReportAISummaryBatchStartResponse:
        if site_scope != "primary":
            raise PermissionError("AI summaries are only available on the primary site.")
        templates = [
            template
            for template in report_template_store.list_templates(site_scope)
            if template.include_in_master_export
        ]
        batch = self._create_batch(site_scope=site_scope, templates=templates)
        if not templates:
            self._update_batch(batch.batch_id, status="completed", started_at=batch.requested_at, completed_at=batch.requested_at)
            return ReportAISummaryBatchStartResponse(
                batch_id=batch.batch_id,
                site_scope=batch.site_scope,
                status="completed",
                item_count=0,
                requested_at=batch.requested_at,
            )
        task = asyncio.create_task(self._run_manual_batch(batch.batch_id, site_scope, templates))
        self._register_task(task)
        return batch

    async def _run_manual_batch(
        self,
        batch_id: str,
        site_scope: str,
        templates: Sequence[ReportTemplate],
    ) -> None:
        started_at = _utcnow_iso()
        self._update_batch(batch_id, status="running", started_at=started_at)
        data_version = self._current_data_version()
        tasks = [
            asyncio.create_task(
                self._enqueue_template_summary(
                    batch_id=batch_id,
                    site_scope=site_scope,
                    template=template,
                    source="manual",
                    lane="report_batch_summary",
                    data_version=data_version,
                )
            )
            for template in templates
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        failed = any(isinstance(result, Exception) for result in results)
        self._update_batch(
            batch_id,
            status="failed" if failed else "completed",
            completed_at=_utcnow_iso(),
        )

    async def _enqueue_template_summary(
        self,
        *,
        batch_id: str | None,
        site_scope: str,
        template: ReportTemplate,
        source: str,
        lane: str,
        data_version: str,
    ) -> ReportAISummary:
        async def work() -> ReportAISummary:
            if batch_id:
                self._update_batch_item(batch_id, template.id, status="running")
            result = await asyncio.to_thread(
                self._generate_summary_result,
                site_scope,
                template,
                source,
                data_version,
            )
            summary = self._upsert_summary(site_scope=site_scope, template=template, result=result)
            if batch_id:
                self._update_batch_item(
                    batch_id,
                    template.id,
                    status=summary.status,
                    summary=summary.summary,
                    bullets=summary.bullets,
                    fallback_used=summary.fallback_used,
                    model_used=summary.model_used,
                    generated_at=summary.generated_at,
                    error=summary.error,
                )
            return summary

        try:
            return await background_ai_worker.run_item(
                lane=lane,
                key=f"{site_scope}:{template.id}",
                work=work,
            )
        except Exception as exc:
            logger.exception("Failed to generate report AI summary for %s", template.name)
            if batch_id:
                self._update_batch_item(batch_id, template.id, status="failed", error=str(exc))
            raise

    def _templates_for_summary_source(self, site_scope: str, *, source: str) -> list[ReportTemplate]:
        templates = report_template_store.list_templates(site_scope)
        if source == "manual":
            return [template for template in templates if template.include_in_master_export]
        return [template for template in templates if not template.include_in_master_export]

    async def _nightly_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                now = _utcnow()
                if now.hour >= REPORT_AI_SUMMARY_NIGHTLY_HOUR_UTC and self._last_nightly_run_day != now.date().isoformat():
                    self._last_nightly_run_day = now.date().isoformat()
                    await self._run_nightly_once()
                await asyncio.wait_for(self._stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Nightly report AI summary loop failed")

    async def _run_nightly_once(self) -> None:
        site_scope = "primary"
        templates = self._templates_for_summary_source(site_scope, source="nightly")
        if not templates:
            return
        data_version = self._current_data_version()
        current = {
            summary.template_id: summary
            for summary in self.list_current_summaries(site_scope)
            if summary.source == "nightly"
        }
        for template in templates:
            summary = current.get(template.id)
            if summary and self._template_summary_is_current(summary, template=template, data_version=data_version):
                continue
            await self._enqueue_template_summary(
                batch_id=None,
                site_scope=site_scope,
                template=template,
                source="nightly",
                lane="report_nightly_summary",
                data_version=data_version,
            )

    def _issues_for_site_scope(self, site_scope: str) -> list[dict[str, Any]]:
        if site_scope == "azure":
            return []
        return filter_issues_for_scope(cache.get_all_issues(), site_scope)

    def _resolve_model_id(self) -> str | None:
        available = get_available_models()
        return select_available_ollama_model(
            available,
            preferred_model_id=REPORT_AI_SUMMARY_MODEL,
            fallback_model_id=OLLAMA_MODEL,
        )

    def _build_summary_prompt(
        self,
        *,
        template: ReportTemplate,
        context: dict[str, Any],
        window_label: str,
        window_start: date,
        window_end: date,
        source: str,
    ) -> tuple[str, str]:
        def _fmt_metric(value: Any, metric_type: str) -> str:
            if metric_type == "percent":
                return f"{float(value or 0.0):.1%}"
            if metric_type == "integer":
                return f"{int(value or 0):,}"
            return f"{float(value or 0.0):,.1f}h"

        def _group_row(rows: Sequence[dict[str, Any]], label: str) -> dict[str, Any] | None:
            return next((row for row in rows if str(row.get("group") or "").strip().lower() == label.lower()), None)

        def _rate_from_rows(rows: Sequence[dict[str, Any]]) -> str:
            total = sum(int(row.get("count") or 0) for row in rows)
            if total <= 0:
                return "0.0%"
            met = int((_group_row(rows, "Met") or {}).get("count") or 0)
            return f"{(met / total):.1%}"

        kpi_lines = []
        for row in context.get("kpis") or []:
            metric_type = str(row.get("type") or "integer")
            kpi_lines.append(
                (
                    f"- {row['label']}: current_7d={_fmt_metric(row.get('value_7d'), metric_type)}, "
                    f"prior_7d={_fmt_metric(row.get('prior_7d'), metric_type)}, "
                    f"delta_vs_prior_7d={_fmt_metric(row.get('delta'), metric_type)}, "
                    f"30d_context={_fmt_metric(row.get('value_30d'), metric_type)}"
                )
            )

        problem_areas = [
            str(item or "").strip()
            for item in (context.get("problem_areas") or [])[:3]
            if str(item or "").strip()
        ]
        gaps = [
            f"- {gap.limitation}: {gap.recommendation}"
            for gap in (context.get("gaps") or [])[:3]
        ]
        top_category_rows_7 = context.get("top_category_rows_7") or context.get("top_category_rows") or []
        group_rows = [
            f"- {row.get('group')}: count={int(row.get('count') or 0):,}, avg_ttr={float(row.get('avg_ttr_hours') or 0.0):.1f}h, p95_ttr={float(row.get('p95_ttr_hours') or 0.0):.1f}h"
            for row in top_category_rows_7[:5]
        ]
        sla_rows_7 = context.get("sla_rows_7") or []
        first_response_rows_7 = context.get("first_response_rows_7") or []
        followup_rows_7 = context.get("followup_rows_7") or []
        mttr_priority_rows_7 = context.get("mttr_priority_rows_7") or context.get("mttr_priority_rows") or []
        high_priority_rows = [
            row
            for row in mttr_priority_rows_7
            if str(row.get("group") or "").strip().lower() in {"high", "highest"}
        ]
        high_priority_focus = max(
            high_priority_rows or mttr_priority_rows_7 or [{"group": "(none)", "avg_ttr_hours": 0.0, "p95_ttr_hours": 0.0}],
            key=lambda row: (float(row.get("p95_ttr_hours") or 0.0), float(row.get("avg_ttr_hours") or 0.0)),
        )
        breached_sla = _group_row(sla_rows_7, "BREACHED") or {}
        breached_first_response = _group_row(first_response_rows_7, "BREACHED") or {}
        breached_followup = _group_row(followup_rows_7, "BREACHED") or {}
        prompt_mode = "master" if source == "manual" else "template"
        if prompt_mode == "master":
            system = (
                "You write concise, executive-friendly service desk summaries for a master workbook. "
                "Lead with current 7-day performance, use 30-day values only as secondary context, "
                "and explicitly distinguish First Response SLA from the stricter 2-Hour Response + Daily Follow-Up metric. "
                "Prefer concrete counts and categories over generic commentary. "
                "Respond with valid JSON only using the key summary. "
                "summary must be one short conversational paragraph of 2 to 4 sentences. "
                "Do not use bullets, numbered lists, labels, or headings inside the summary. "
                "Do not mention missing data unless it materially affects interpretation."
            )
        else:
            system = (
                "You write concise, executive-friendly service desk summaries. "
                "Respond with valid JSON only using the key summary. "
                "summary must be one short conversational paragraph of 2 to 4 sentences. "
                "Do not use bullets, numbered lists, labels, or headings inside the summary. "
                "Do not mention missing data unless it materially affects interpretation."
            )
        user_msg = "\n".join(
            [
                f"Template: {template.name}",
                f"Description: {template.description or 'Saved report template'}",
                f"Category: {template.category or 'Uncategorized'}",
                f"Window: {window_label} ({window_start.isoformat()} to {window_end.isoformat()})",
                f"Readiness: {template.readiness or 'custom'}",
                f"Grouped by: {template.config.group_by or 'detail view'}",
                f"Prompt mode: {prompt_mode}",
                f"Prior 7-day comparison window: {context['prior_7_window_start'].isoformat()} to {context['prior_7_window_end'].isoformat()}",
                "",
                "Executive KPI snapshot (7-day primary, 30-day context):",
                *(kpi_lines or ["- No KPI rows available"]),
                "",
                "7-day SLA breakdown:",
                (
                    f"- Met={int((_group_row(sla_rows_7, 'Met') or {}).get('count') or 0):,}, "
                    f"BREACHED={int(breached_sla.get('count') or 0):,}, "
                    f"BREACHED avg TTR={float(breached_sla.get('avg_ttr_hours') or 0.0):.1f}h"
                ),
                "",
                "7-day response discipline:",
                (
                    f"- First Response SLA met rate={_rate_from_rows(first_response_rows_7)}, "
                    f"first-response BREACHED={int(breached_first_response.get('count') or 0):,}"
                ),
                (
                    f"- 2-Hour Response + Daily Follow-Up met rate={_rate_from_rows(followup_rows_7)}, "
                    f"follow-up BREACHED={int(breached_followup.get('count') or 0):,}"
                ),
                "",
                "7-day high-priority MTTR focus:",
                (
                    f"- {high_priority_focus.get('group') or '(none)'} "
                    f"avg={float(high_priority_focus.get('avg_ttr_hours') or 0.0):.1f}h, "
                    f"p95={float(high_priority_focus.get('p95_ttr_hours') or 0.0):.1f}h"
                ),
                "",
                "Top weekly request categories:",
                *(group_rows or ["- No grouped findings available"]),
                "",
                "Current problem areas:",
                *(problem_areas or ["- No explicit problem areas available"]),
                "",
                "Current data gaps:",
                *(gaps or ["- No material data gaps recorded"]),
                "",
                "Write the summary so the 7-day story leads. Use 30-day values only as supporting context, not the headline.",
                'Return JSON like {"summary":"..."}.',
            ]
        )
        return system, user_msg

    def _build_fallback_result(
        self,
        *,
        template: ReportTemplate,
        builder: ReportWorkbookBuilder,
        context: dict[str, Any],
        source: str,
        data_version: str,
        error: str,
    ) -> _SummaryGenerationResult:
        anomaly = builder._detect_escalation_anomaly(context.get("trend_rows") or [])
        findings = builder._build_key_findings(context, anomaly=anomaly)
        summary = _build_conversational_fallback_summary(findings, template_name=template.name)
        return _SummaryGenerationResult(
            status="fallback",
            source=source,
            summary=summary,
            bullets=[],
            fallback_used=True,
            model_used="",
            generated_at=_utcnow_iso(),
            template_version=template.updated_at,
            data_version=data_version,
            error=error,
        )

    def _generate_summary_result(
        self,
        site_scope: str,
        template: ReportTemplate,
        source: str,
        data_version: str,
    ) -> _SummaryGenerationResult:
        issues = self._issues_for_site_scope(site_scope)
        builder = ReportWorkbookBuilder(
            all_issues=issues,
            site_scope=site_scope,
            today=_utcnow().date(),
            enable_changelog_fetch=False,
        )
        facts = builder._facts_for_config(template.config)
        context = builder._build_dashboard_context(
            report_name=template.name,
            report_description=template.description or "Saved report template",
            facts=facts,
            template=template,
        )
        window_spec = resolve_report_window_spec(template.config, today=builder.today)
        model_id = self._resolve_model_id()
        if not model_id:
            return self._build_fallback_result(
                template=template,
                builder=builder,
                context=context,
                source=source,
                data_version=data_version,
                error="No AI model is currently available.",
            )
        system, user_msg = self._build_summary_prompt(
            template=template,
            context=context,
            window_label=window_spec.label,
            window_start=window_spec.start,
            window_end=window_spec.end,
            source=source,
        )
        try:
            raw = invoke_model_text(
                model_id,
                system,
                user_msg,
                feature_surface="report_ai_summary",
                app_surface="reports",
                temperature=0.2,
                max_output_tokens=500,
                json_output=True,
                metadata={
                    "template_id": template.id,
                    "site_scope": site_scope,
                    "summary_source": source,
                },
            )
            payload = _extract_json_object(raw)
            summary = _normalize_summary_text(payload.get("summary"), max_length=240)
            bullets = _normalize_bullets(payload.get("bullets"))
            if not summary:
                raise ValueError("AI response did not contain a summary")
            return _SummaryGenerationResult(
                status="ready",
                source=source,
                summary=summary,
                bullets=bullets,
                fallback_used=False,
                model_used=model_id,
                generated_at=_utcnow_iso(),
                template_version=template.updated_at,
                data_version=data_version,
            )
        except Exception as exc:
            logger.warning("Falling back to deterministic report summary for %s: %s", template.name, exc)
            return self._build_fallback_result(
                template=template,
                builder=builder,
                context=context,
                source=source,
                data_version=data_version,
                error=str(exc),
            )


report_ai_summary_service = ReportAISummaryService()
