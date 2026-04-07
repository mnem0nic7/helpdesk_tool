"""Scheduled user deactivation store and background runner.

Each scheduled deactivation is tied to a Jira ticket key so operators
can see which ticket triggered it.  The runner fires every 30 seconds
and executes any jobs whose run_at has passed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 30  # seconds
_DB_PATH = os.path.join(DATA_DIR, "deactivation_schedule.db")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeactivationScheduleStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._bg_task: asyncio.Task[None] | None = None
        self._init_db()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _sqlite_conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _conn(self) -> sqlite3.Connection:
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return self._sqlite_conn()

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            return
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS deactivation_schedule (
                    job_id          TEXT PRIMARY KEY,
                    ticket_key      TEXT NOT NULL,
                    display_name    TEXT NOT NULL,
                    entra_user_id   TEXT NOT NULL,
                    ad_sam          TEXT NOT NULL,
                    run_at          TEXT NOT NULL,
                    timezone_label  TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    result_json     TEXT,
                    created_at      TEXT NOT NULL,
                    created_by      TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_deact_status ON deactivation_schedule (status, run_at)")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        ticket_key: str,
        display_name: str,
        entra_user_id: str,
        ad_sam: str,
        run_at: datetime,
        timezone_label: str,
        created_by: str,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        now = _utcnow().isoformat()
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO deactivation_schedule
                    (job_id, ticket_key, display_name, entra_user_id, ad_sam,
                     run_at, timezone_label, status, created_at, created_by)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},'pending',{ph},{ph})
                """,
                (job_id, ticket_key, display_name, entra_user_id, ad_sam,
                 run_at.isoformat(), timezone_label, now, created_by),
            )
        return self.get(job_id)  # type: ignore[return-value]

    def get(self, job_id: str) -> dict[str, Any] | None:
        ph = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM deactivation_schedule WHERE job_id = {ph}", (job_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_for_ticket(self, ticket_key: str) -> list[dict[str, Any]]:
        ph = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM deactivation_schedule WHERE ticket_key = {ph} ORDER BY run_at",
                (ticket_key,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def list_all(self, limit: int = 100) -> list[dict[str, Any]]:
        ph = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM deactivation_schedule ORDER BY run_at DESC LIMIT {ph}",
                (limit,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def cancel(self, job_id: str) -> bool:
        ph = self._placeholder()
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE deactivation_schedule SET status='cancelled' WHERE job_id={ph} AND status='pending'",
                (job_id,),
            )
        return (cur.rowcount or 0) > 0

    def _claim_due(self) -> list[dict[str, Any]]:
        """Atomically fetch-and-mark pending jobs whose run_at <= now."""
        ph = self._placeholder()
        now = _utcnow().isoformat()
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM deactivation_schedule
                WHERE status = 'pending' AND run_at <= {ph}
                ORDER BY run_at
                LIMIT 20
                """,
                (now,),
            ).fetchall()
            jobs = [_row_to_dict(r) for r in rows]
            if jobs:
                ids = [j["job_id"] for j in jobs]
                placeholders = ",".join([ph] * len(ids))
                conn.execute(
                    f"UPDATE deactivation_schedule SET status='running' WHERE job_id IN ({placeholders})",
                    ids,
                )
        return jobs

    def _finish(self, job_id: str, status: str, result: dict[str, Any]) -> None:
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE deactivation_schedule SET status={ph}, result_json={ph} WHERE job_id={ph}",
                (status, json.dumps(result), job_id),
            )

    # ------------------------------------------------------------------
    # Background runner
    # ------------------------------------------------------------------

    def start_background_runner(self) -> None:
        loop = asyncio.get_event_loop()
        self._bg_task = loop.create_task(self._run_loop())

    def stop_background_runner(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()

    async def _run_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(_POLL_INTERVAL)
                due = self._claim_due()
                for job in due:
                    asyncio.get_event_loop().create_task(self._execute(job))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Deactivation schedule runner error: %s", exc)

    async def _execute(self, job: dict[str, Any]) -> None:
        from user_admin_jobs import user_admin_jobs
        import ad_client as ad

        job_id = job["job_id"]
        entra_user_id = job.get("entra_user_id", "")
        ad_sam = job.get("ad_sam", "")
        result: dict[str, Any] = {}

        # Entra
        try:
            entra_job = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: user_admin_jobs.create_job(
                    action_type="disable_sign_in",
                    target_user_ids=[entra_user_id],
                    params={},
                    requested_by_email="deactivation-scheduler@system",
                    requested_by_name="Deactivation Scheduler",
                ),
            )
            result["entra"] = f"Job queued: {entra_job['job_id']}"
        except Exception as exc:
            result["entra"] = f"Error: {exc}"
            logger.error("Deactivation Entra step failed for %s: %s", job_id, exc)

        # AD
        if ad_sam:
            try:
                await asyncio.get_event_loop().run_in_executor(None, lambda: ad.disable_user(ad_sam))
                result["ad"] = f"Disabled AD account: {ad_sam}"
            except Exception as exc:
                result["ad"] = f"Error: {exc}"
                logger.error("Deactivation AD step failed for %s: %s", job_id, exc)
        else:
            result["ad"] = "No AD account linked"

        overall = "completed" if "Error" not in result.get("entra", "") else "failed"
        self._finish(job_id, overall, result)
        logger.info(
            "Deactivation job %s finished: entra=%s ad=%s",
            job_id, result.get("entra"), result.get("ad"),
        )


def _row_to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return dict(row)
    # sqlite3.Row via column access
    cols = ["job_id", "ticket_key", "display_name", "entra_user_id", "ad_sam",
            "run_at", "timezone_label", "status", "result_json", "created_at", "created_by"]
    d = {c: row[c] for c in cols if c in row.keys()}
    if "result_json" in d and d["result_json"]:
        try:
            d["result"] = json.loads(d["result_json"])
        except Exception:
            d["result"] = {}
    else:
        d["result"] = {}
    return d


deactivation_schedule = DeactivationScheduleStore()
