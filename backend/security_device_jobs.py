"""Background jobs for Azure security device-compliance actions."""

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

from azure_cache import azure_cache
from config import DATA_DIR
from models import SecurityDeviceActionType
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite
from user_admin_providers import UserAdminProviderError, user_admin_providers

logger = logging.getLogger(__name__)

_STATUS_VALUES = {"queued", "running", "completed", "failed"}
_DESTRUCTIVE_ACTIONS = {"device_retire", "device_wipe"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SecurityDeviceJobError(RuntimeError):
    """Raised when a security device action job cannot be created."""


class SecurityDeviceJobManager:
    """Durable FIFO queue for Azure security device actions."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "security_device_jobs.db")
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._bg_task: asyncio.Task[None] | None = None
        self._pending_params: dict[str, dict[str, Any]] = {}
        self._init_db()
        self._requeue_running_jobs()

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _sqlite_conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _conn(self):
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return self._sqlite_conn()

    def _sql(self, text: str) -> str:
        if self._use_postgres:
            return text.replace("?", "%s")
        return text

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            return
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS security_device_action_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    device_ids_json TEXT NOT NULL,
                    device_names_json TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    params_json TEXT NOT NULL DEFAULT '{}',
                    requested_by_email TEXT NOT NULL,
                    requested_by_name TEXT NOT NULL DEFAULT '',
                    requested_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    progress_current INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    progress_message TEXT NOT NULL DEFAULT '',
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS security_device_action_job_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    device_name TEXT NOT NULL DEFAULT '',
                    azure_ad_device_id TEXT NOT NULL DEFAULT '',
                    success INTEGER NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    before_summary_json TEXT NOT NULL DEFAULT '{}',
                    after_summary_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_security_device_action_job_results_job
                    ON security_device_action_job_results(job_id, id);
                """
            )
            conn.commit()

    def _requeue_running_jobs(self) -> None:
        with self._conn() as conn:
            conn.execute(
                self._sql(
                    """
                    UPDATE security_device_action_jobs
                    SET status = 'queued',
                        started_at = NULL,
                        completed_at = NULL,
                        progress_current = 0,
                        progress_message = 'Re-queued after restart',
                        error = ''
                    WHERE status = 'running'
                    """
                )
            )
            conn.commit()

    def _device_lookup(self) -> dict[str, dict[str, Any]]:
        rows = azure_cache._snapshot("managed_devices") or []
        return {
            str(item.get("id") or ""): item
            for item in rows
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }

    @staticmethod
    def _sorted_names(rows: list[dict[str, Any]]) -> list[str]:
        names = [str(item.get("device_name") or item.get("id") or "").strip() for item in rows]
        return sorted([name for name in names if name], key=str.lower)

    def create_job(
        self,
        *,
        action_type: SecurityDeviceActionType,
        device_ids: list[str],
        reason: str,
        params: dict[str, Any] | None,
        confirm_device_count: int | None,
        confirm_device_names: list[str] | None,
        requested_by_email: str,
        requested_by_name: str,
    ) -> dict[str, Any]:
        cleaned_ids: list[str] = []
        seen: set[str] = set()
        for item in device_ids:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned_ids.append(text)
        if not cleaned_ids:
            raise SecurityDeviceJobError("At least one target device is required.")

        provider, provider_key = user_admin_providers.provider_for_action(action_type)  # type: ignore[arg-type]
        if not getattr(provider, "enabled", False):
            raise SecurityDeviceJobError("Intune device-management provider is not configured.")

        device_lookup = self._device_lookup()
        target_rows = [device_lookup.get(device_id) for device_id in cleaned_ids]
        missing_ids = [device_id for device_id, row in zip(cleaned_ids, target_rows) if row is None]
        if missing_ids:
            raise SecurityDeviceJobError(
                "The current device compliance cache does not contain all selected devices. Refresh the lane and try again."
            )
        target_devices = [row for row in target_rows if isinstance(row, dict)]
        device_names = self._sorted_names(target_devices)

        if action_type in _DESTRUCTIVE_ACTIONS:
            if int(confirm_device_count or 0) != len(cleaned_ids):
                raise SecurityDeviceJobError(
                    f"Destructive confirmation failed. Confirm the selected device count ({len(cleaned_ids)}) before continuing."
                )
            confirmed_names = sorted(
                [str(item).strip() for item in (confirm_device_names or []) if str(item).strip()],
                key=str.lower,
            )
            if confirmed_names != device_names:
                raise SecurityDeviceJobError(
                    "Destructive confirmation failed. Confirm the exact selected device names before continuing."
                )

        job_id = uuid.uuid4().hex
        requested_at = _utcnow().isoformat()
        stored_params = dict(params or {})
        with self._conn() as conn:
            conn.execute(
                self._sql(
                    """
                    INSERT INTO security_device_action_jobs (
                        job_id,
                        status,
                        action_type,
                        device_ids_json,
                        device_names_json,
                        reason,
                        params_json,
                        requested_by_email,
                        requested_by_name,
                        requested_at,
                        progress_current,
                        progress_total,
                        progress_message
                    ) VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'Queued')
                    """
                ),
                (
                    job_id,
                    str(action_type),
                    json.dumps(cleaned_ids),
                    json.dumps(device_names),
                    str(reason or "").strip(),
                    json.dumps(stored_params),
                    requested_by_email,
                    requested_by_name,
                    requested_at,
                    len(cleaned_ids),
                ),
            )
            conn.commit()
        self._pending_params[job_id] = stored_params
        return self.get_job(job_id) or {
            "job_id": job_id,
            "status": "queued",
            "action_type": action_type,
            "device_ids": cleaned_ids,
            "device_names": device_names,
            "requested_by_email": requested_by_email,
            "requested_by_name": requested_by_name,
            "requested_at": requested_at,
            "started_at": None,
            "completed_at": None,
            "progress_current": 0,
            "progress_total": len(cleaned_ids),
            "progress_message": "Queued",
            "success_count": 0,
            "failure_count": 0,
            "results_ready": False,
            "reason": str(reason or "").strip(),
            "error": "",
        }

    def _coerce_job(self, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return None
        payload = dict(row)
        try:
            device_ids = json.loads(str(payload.get("device_ids_json") or "[]"))
        except json.JSONDecodeError:
            device_ids = []
        try:
            device_names = json.loads(str(payload.get("device_names_json") or "[]"))
        except json.JSONDecodeError:
            device_names = []
        status = str(payload.get("status") or "queued")
        if status not in _STATUS_VALUES:
            status = "queued"
        return {
            "job_id": str(payload.get("job_id") or ""),
            "status": status,
            "action_type": str(payload.get("action_type") or ""),
            "device_ids": [str(item) for item in device_ids if str(item).strip()],
            "device_names": [str(item) for item in device_names if str(item).strip()],
            "requested_by_email": str(payload.get("requested_by_email") or ""),
            "requested_by_name": str(payload.get("requested_by_name") or ""),
            "requested_at": str(payload.get("requested_at") or ""),
            "started_at": payload.get("started_at") or None,
            "completed_at": payload.get("completed_at") or None,
            "progress_current": int(payload.get("progress_current") or 0),
            "progress_total": int(payload.get("progress_total") or 0),
            "progress_message": str(payload.get("progress_message") or ""),
            "success_count": int(payload.get("success_count") or 0),
            "failure_count": int(payload.get("failure_count") or 0),
            "results_ready": status in {"completed", "failed"},
            "reason": str(payload.get("reason") or ""),
            "error": str(payload.get("error") or ""),
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                self._sql("SELECT * FROM security_device_action_jobs WHERE job_id = ?"),
                (job_id,),
            ).fetchone()
        return self._coerce_job(row)

    def get_job_results(self, job_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                self._sql(
                    """
                    SELECT *
                    FROM security_device_action_job_results
                    WHERE job_id = ?
                    ORDER BY id ASC
                    """
                ),
                (job_id,),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "device_id": str(row["device_id"] or ""),
                    "device_name": str(row["device_name"] or ""),
                    "azure_ad_device_id": str(row["azure_ad_device_id"] or ""),
                    "success": bool(row["success"]),
                    "summary": str(row["summary"] or ""),
                    "error": str(row["error"] or ""),
                    "before_summary": json.loads(str(row["before_summary_json"] or "{}")),
                    "after_summary": json.loads(str(row["after_summary_json"] or "{}")),
                }
            )
        return results

    async def start_worker(self) -> None:
        if self._bg_task and not self._bg_task.done():
            return
        self._bg_task = asyncio.get_running_loop().create_task(self._background_loop())

    async def stop_worker(self) -> None:
        if not self._bg_task:
            return
        self._bg_task.cancel()
        try:
            await self._bg_task
        except asyncio.CancelledError:
            pass
        self._bg_task = None

    def _params_for_job(self, job_id: str) -> dict[str, Any]:
        if job_id in self._pending_params:
            return dict(self._pending_params[job_id])
        with self._conn() as conn:
            row = conn.execute(
                self._sql("SELECT params_json FROM security_device_action_jobs WHERE job_id = ?"),
                (job_id,),
            ).fetchone()
        if not row:
            return {}
        try:
            return json.loads(str(row["params_json"] or "{}"))
        except json.JSONDecodeError:
            return {}

    def _update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = {self._placeholder()}" for key in fields)
        values = list(fields.values()) + [job_id]
        with self._conn() as conn:
            conn.execute(
                f"UPDATE security_device_action_jobs SET {assignments} WHERE job_id = {self._placeholder()}",
                values,
            )
            conn.commit()

    def _claim_next_job(self) -> dict[str, Any] | None:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    self._sql(
                        """
                        SELECT *
                        FROM security_device_action_jobs
                        WHERE status = 'queued'
                        ORDER BY requested_at ASC
                        LIMIT 1
                        """
                    )
                ).fetchone()
                if not row:
                    return None
                job_id = str(row["job_id"] or "")
                conn.execute(
                    self._sql(
                        """
                        UPDATE security_device_action_jobs
                        SET status = 'running',
                            started_at = ?,
                            completed_at = NULL,
                            progress_current = 0,
                            progress_message = 'Starting job',
                            success_count = 0,
                            failure_count = 0,
                            error = ''
                        WHERE job_id = ?
                        """
                    ),
                    (_utcnow().isoformat(), job_id),
                )
                conn.commit()
        return self.get_job(job_id)

    def _insert_result(
        self,
        *,
        job_id: str,
        device_id: str,
        device_name: str,
        azure_ad_device_id: str,
        success: bool,
        summary: str,
        error: str,
        before_summary: dict[str, Any],
        after_summary: dict[str, Any],
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                self._sql(
                    """
                    INSERT INTO security_device_action_job_results (
                        job_id,
                        device_id,
                        device_name,
                        azure_ad_device_id,
                        success,
                        summary,
                        error,
                        before_summary_json,
                        after_summary_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                ),
                (
                    job_id,
                    device_id,
                    device_name,
                    azure_ad_device_id,
                    1 if success else 0,
                    summary,
                    error,
                    json.dumps(before_summary),
                    json.dumps(after_summary),
                    _utcnow().isoformat(),
                ),
            )
            conn.commit()

    def _refresh_device_cache(self) -> None:
        refresh = getattr(azure_cache, "refresh_datasets", None)
        if callable(refresh):
            try:
                refresh(["device_compliance"], force=True)
            except Exception:
                logger.exception("Failed to refresh device compliance cache after security device job")

    def _process_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return

        device_lookup = self._device_lookup()
        params = self._params_for_job(job_id)
        action_type = str(job.get("action_type") or "")
        device_ids = [str(item) for item in job.get("device_ids") or []]
        success_count = 0
        failure_count = 0

        for index, device_id in enumerate(device_ids, start=1):
            device = device_lookup.get(device_id) or {}
            device_name = str(device.get("device_name") or device_id)
            azure_ad_device_id = str(device.get("azure_ad_device_id") or "")
            self._update_job(
                job_id,
                progress_current=index - 1,
                progress_total=len(device_ids),
                progress_message=f"Applying {action_type} to {device_name}",
                success_count=success_count,
                failure_count=failure_count,
            )
            try:
                result = user_admin_providers.execute(action_type, "", {**params, "device_ids": [device_id]})
                before_summary = dict(result.get("before_summary") or {"device_ids": [device_id]})
                after_summary = dict(result.get("after_summary") or {})
                summary = str(result.get("summary") or f"Queued {action_type.replace('_', ' ')}")
                self._insert_result(
                    job_id=job_id,
                    device_id=device_id,
                    device_name=device_name,
                    azure_ad_device_id=azure_ad_device_id,
                    success=True,
                    summary=summary,
                    error="",
                    before_summary=before_summary,
                    after_summary=after_summary,
                )
                success_count += 1
            except UserAdminProviderError as exc:
                self._insert_result(
                    job_id=job_id,
                    device_id=device_id,
                    device_name=device_name,
                    azure_ad_device_id=azure_ad_device_id,
                    success=False,
                    summary="Failed",
                    error=str(exc),
                    before_summary={"device_ids": [device_id]},
                    after_summary={},
                )
                failure_count += 1
            except Exception as exc:
                logger.exception("Security device action %s failed for %s", action_type, device_id)
                self._insert_result(
                    job_id=job_id,
                    device_id=device_id,
                    device_name=device_name,
                    azure_ad_device_id=azure_ad_device_id,
                    success=False,
                    summary="Failed",
                    error=str(exc),
                    before_summary={"device_ids": [device_id]},
                    after_summary={},
                )
                failure_count += 1

            self._update_job(
                job_id,
                progress_current=index,
                progress_total=len(device_ids),
                progress_message=f"Processed {index} of {len(device_ids)} device(s)",
                success_count=success_count,
                failure_count=failure_count,
            )

        final_status = "completed" if success_count or not failure_count else "failed"
        self._update_job(
            job_id,
            status=final_status,
            completed_at=_utcnow().isoformat(),
            progress_current=len(device_ids),
            progress_total=len(device_ids),
            progress_message="Completed" if final_status == "completed" else "Failed",
            success_count=success_count,
            failure_count=failure_count,
            error="" if final_status == "completed" else "All targets failed",
        )
        self._pending_params.pop(job_id, None)
        self._refresh_device_cache()

    async def _background_loop(self) -> None:
        while True:
            try:
                job = await asyncio.get_running_loop().run_in_executor(None, self._claim_next_job)
                if not job:
                    await asyncio.sleep(2)
                    continue
                await asyncio.get_running_loop().run_in_executor(None, self._process_job, str(job.get("job_id") or ""))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Security device job loop failed")
                await asyncio.sleep(2)


security_device_jobs = SecurityDeviceJobManager()
