"""Background jobs and durable audit storage for user administration actions."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from azure_cache import azure_cache
from config import DATA_DIR
from models import UserAdminActionType
from sqlite_utils import connect_sqlite
from user_admin_providers import UserAdminProviderError, user_admin_providers

logger = logging.getLogger(__name__)

_STATUS_VALUES = {"queued", "running", "completed", "failed"}
_MAX_TARGET_ATTEMPTS = 3
_DEFAULT_RETRY_DELAY_SECONDS = 2
_SECRET_KEYS = {"new_password", "password", "secret", "token", "temporary_password"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_for_storage(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if any(secret_key in key.lower() for secret_key in _SECRET_KEYS):
                sanitized[key] = "[redacted]"
            else:
                sanitized[key] = _sanitize_for_storage(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_for_storage(item) for item in value]
    return value


class UserAdminJobManager:
    """SQLite-backed FIFO queue for user-management jobs with audit history."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "user_admin_jobs.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._bg_task: asyncio.Task[None] | None = None
        self._ephemeral_results: dict[str, dict[str, str]] = {}
        self._pending_params: dict[str, dict[str, Any]] = {}
        self._init_db()
        self._requeue_running_jobs()

    def _conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_admin_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    target_user_ids_json TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    requested_by_email TEXT NOT NULL,
                    requested_by_name TEXT NOT NULL,
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
                CREATE TABLE IF NOT EXISTS user_admin_job_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    target_user_id TEXT NOT NULL,
                    target_display_name TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    before_summary_json TEXT NOT NULL DEFAULT '{}',
                    after_summary_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_user_admin_job_results_job
                    ON user_admin_job_results (job_id, id);
                CREATE TABLE IF NOT EXISTS user_admin_audit (
                    audit_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    actor_email TEXT NOT NULL,
                    actor_name TEXT NOT NULL DEFAULT '',
                    target_user_id TEXT NOT NULL,
                    target_display_name TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    params_summary_json TEXT NOT NULL DEFAULT '{}',
                    before_summary_json TEXT NOT NULL DEFAULT '{}',
                    after_summary_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_user_admin_audit_target
                    ON user_admin_audit (target_user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_user_admin_audit_created
                    ON user_admin_audit (created_at DESC);
                """
            )
            conn.commit()

    def _coerce_job(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        payload = dict(row)
        try:
            target_user_ids = json.loads(str(payload.get("target_user_ids_json") or "[]"))
        except json.JSONDecodeError:
            target_user_ids = []
        status = str(payload.get("status") or "queued")
        if status not in _STATUS_VALUES:
            status = "queued"
        return {
            "job_id": str(payload.get("job_id") or ""),
            "status": status,
            "action_type": str(payload.get("action_type") or ""),
            "provider": str(payload.get("provider") or "entra"),
            "target_user_ids": [str(item) for item in target_user_ids if str(item).strip()],
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
            "error": str(payload.get("error") or ""),
            "one_time_results_available": bool(self._ephemeral_results.get(str(payload.get("job_id") or ""))),
        }

    def _row_to_result(self, row: sqlite3.Row, *, include_one_time_secret: bool = False) -> dict[str, Any]:
        job_id = str(row["job_id"] or "")
        target_user_id = str(row["target_user_id"] or "")
        secret = None
        if include_one_time_secret:
            secret = (self._ephemeral_results.get(job_id) or {}).get(target_user_id)
        return {
            "target_user_id": target_user_id,
            "target_display_name": str(row["target_display_name"] or ""),
            "provider": str(row["provider"] or "entra"),
            "success": bool(row["success"]),
            "summary": str(row["summary"] or ""),
            "error": str(row["error"] or ""),
            "before_summary": json.loads(str(row["before_summary_json"] or "{}")),
            "after_summary": json.loads(str(row["after_summary_json"] or "{}")),
            "one_time_secret": secret,
        }

    def _update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [job_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE user_admin_jobs SET {assignments} WHERE job_id = ?", values)
            conn.commit()

    def _requeue_running_jobs(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE user_admin_jobs
                SET status = 'queued',
                    started_at = NULL,
                    completed_at = NULL,
                    progress_current = 0,
                    progress_message = 'Re-queued after restart',
                    error = ''
                WHERE status = 'running'
                """
            )
            conn.commit()

    def create_job(
        self,
        *,
        action_type: UserAdminActionType,
        target_user_ids: list[str],
        params: dict[str, Any] | None,
        requested_by_email: str,
        requested_by_name: str,
    ) -> dict[str, Any]:
        cleaned_user_ids = [str(item).strip() for item in target_user_ids if str(item).strip()]
        if not cleaned_user_ids:
            raise ValueError("At least one target user is required")

        provider, provider_key = user_admin_providers.provider_for_action(action_type)
        if not getattr(provider, "enabled", False):
            raise ValueError(f"{provider_key} provider is not configured")

        job_id = uuid.uuid4().hex
        requested_at = _utcnow().isoformat()
        params_json = json.dumps(_sanitize_for_storage(params or {}))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO user_admin_jobs (
                    job_id,
                    status,
                    action_type,
                    provider,
                    target_user_ids_json,
                    params_json,
                    requested_by_email,
                    requested_by_name,
                    requested_at,
                    progress_current,
                    progress_total,
                    progress_message
                )
                VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, 0, ?, 'Queued')
                """,
                (
                    job_id,
                    str(action_type),
                    provider_key,
                    json.dumps(cleaned_user_ids),
                    params_json,
                    requested_by_email,
                    requested_by_name,
                    requested_at,
                    len(cleaned_user_ids),
                ),
            )
            conn.commit()
        self._pending_params[job_id] = dict(params or {})
        return self.get_job(job_id) or {
            "job_id": job_id,
            "status": "queued",
            "action_type": action_type,
            "provider": provider_key,
            "target_user_ids": cleaned_user_ids,
            "requested_by_email": requested_by_email,
            "requested_by_name": requested_by_name,
            "requested_at": requested_at,
            "started_at": None,
            "completed_at": None,
            "progress_current": 0,
            "progress_total": len(cleaned_user_ids),
            "progress_message": "Queued",
            "success_count": 0,
            "failure_count": 0,
            "results_ready": False,
            "error": "",
            "one_time_results_available": False,
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM user_admin_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._coerce_job(row)

    def get_job_results(self, job_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM user_admin_job_results
                WHERE job_id = ?
                ORDER BY id ASC
                """,
                (job_id,),
            ).fetchall()
        results = [self._row_to_result(row, include_one_time_secret=True) for row in rows]
        self._ephemeral_results.pop(job_id, None)
        return results

    def job_belongs_to(self, job_id: str, email: str, *, is_admin: bool = False) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        if is_admin:
            return True
        return str(job.get("requested_by_email") or "").lower() == str(email or "").lower()

    def list_audit(self, *, limit: int = 100, target_user_id: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if target_user_id:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM user_admin_audit
                    WHERE target_user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (target_user_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM user_admin_audit
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "audit_id": str(row["audit_id"] or ""),
                    "job_id": str(row["job_id"] or ""),
                    "actor_email": str(row["actor_email"] or ""),
                    "actor_name": str(row["actor_name"] or ""),
                    "target_user_id": str(row["target_user_id"] or ""),
                    "target_display_name": str(row["target_display_name"] or ""),
                    "provider": str(row["provider"] or "entra"),
                    "action_type": str(row["action_type"] or ""),
                    "params_summary": json.loads(str(row["params_summary_json"] or "{}")),
                    "before_summary": json.loads(str(row["before_summary_json"] or "{}")),
                    "after_summary": json.loads(str(row["after_summary_json"] or "{}")),
                    "status": str(row["status"] or ""),
                    "error": str(row["error"] or ""),
                    "created_at": str(row["created_at"] or ""),
                }
            )
        return results

    def record_audit_entry(
        self,
        *,
        job_id: str = "",
        actor_email: str,
        actor_name: str,
        target_user_id: str,
        target_display_name: str,
        provider: str,
        action_type: UserAdminActionType,
        params: dict[str, Any] | None = None,
        before_summary: dict[str, Any] | None = None,
        after_summary: dict[str, Any] | None = None,
        status: str,
        error: str = "",
    ) -> None:
        self._record_audit(
            job_id=job_id,
            actor_email=actor_email,
            actor_name=actor_name,
            target_user_id=target_user_id,
            target_display_name=target_display_name,
            provider=provider,
            action_type=action_type,
            params=params or {},
            before_summary=before_summary or {},
            after_summary=after_summary or {},
            status=status,
            error=error,
        )

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

    def _claim_next_job(self) -> dict[str, Any] | None:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    """
                    SELECT *
                    FROM user_admin_jobs
                    WHERE status = 'queued'
                    ORDER BY requested_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                if not row:
                    return None
                job_id = str(row["job_id"] or "")
                conn.execute(
                    """
                    UPDATE user_admin_jobs
                    SET status = 'running',
                        started_at = ?,
                        completed_at = NULL,
                        progress_current = 0,
                        progress_message = 'Starting job',
                        success_count = 0,
                        failure_count = 0,
                        error = ''
                    WHERE job_id = ?
                    """,
                    (_utcnow().isoformat(), job_id),
                )
                conn.commit()
            return self.get_job(job_id)

    def _lookup_display_name(self, user_id: str) -> str:
        for item in azure_cache.list_directory_objects("users", search=""):
            if str(item.get("id") or "") == user_id:
                return str(item.get("display_name") or user_id)
        return user_id

    def _insert_result(
        self,
        *,
        job_id: str,
        target_user_id: str,
        target_display_name: str,
        provider: str,
        success: bool,
        summary: str,
        error: str,
        before_summary: dict[str, Any],
        after_summary: dict[str, Any],
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO user_admin_job_results (
                    job_id,
                    target_user_id,
                    target_display_name,
                    provider,
                    success,
                    summary,
                    error,
                    before_summary_json,
                    after_summary_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    target_user_id,
                    target_display_name,
                    provider,
                    1 if success else 0,
                    summary,
                    error,
                    json.dumps(_sanitize_for_storage(before_summary)),
                    json.dumps(_sanitize_for_storage(after_summary)),
                    _utcnow().isoformat(),
                ),
            )
            conn.commit()

    def _record_audit(
        self,
        *,
        job_id: str,
        actor_email: str,
        actor_name: str,
        target_user_id: str,
        target_display_name: str,
        provider: str,
        action_type: UserAdminActionType,
        params: dict[str, Any],
        before_summary: dict[str, Any],
        after_summary: dict[str, Any],
        status: str,
        error: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO user_admin_audit (
                    audit_id,
                    job_id,
                    actor_email,
                    actor_name,
                    target_user_id,
                    target_display_name,
                    provider,
                    action_type,
                    params_summary_json,
                    before_summary_json,
                    after_summary_json,
                    status,
                    error,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    job_id,
                    actor_email,
                    actor_name,
                    target_user_id,
                    target_display_name,
                    provider,
                    str(action_type),
                    json.dumps(_sanitize_for_storage(params)),
                    json.dumps(_sanitize_for_storage(before_summary)),
                    json.dumps(_sanitize_for_storage(after_summary)),
                    status,
                    error,
                    _utcnow().isoformat(),
                ),
            )
            conn.commit()

    def _params_for_job(self, job_id: str) -> dict[str, Any]:
        if job_id in self._pending_params:
            return dict(self._pending_params[job_id])
        with self._conn() as conn:
            row = conn.execute(
                "SELECT params_json FROM user_admin_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if not row:
            return {}
        try:
            return json.loads(str(row["params_json"] or "{}"))
        except json.JSONDecodeError:
            return {}

    def _refresh_touched_users(self, user_ids: list[str]) -> None:
        user_ids = [user_id for user_id in user_ids if user_id]
        if not user_ids:
            return
        refresh_users = getattr(azure_cache, "refresh_directory_users", None)
        if callable(refresh_users):
            refresh_users(user_ids)
            return
        try:
            azure_cache.refresh_datasets(["directory"], force=True)
        except Exception:
            logger.exception("Failed to refresh Azure directory cache after user-admin job")

    def _process_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return

        action_type = str(job.get("action_type") or "")
        target_user_ids = [str(item) for item in job.get("target_user_ids") or []]
        params = self._params_for_job(job_id)
        actor_email = str(job.get("requested_by_email") or "")
        actor_name = str(job.get("requested_by_name") or "")
        success_count = 0
        failure_count = 0
        touched_users: list[str] = []

        for index, target_user_id in enumerate(target_user_ids, start=1):
            target_display_name = self._lookup_display_name(target_user_id)
            self._update_job(
                job_id,
                progress_current=index - 1,
                progress_total=len(target_user_ids),
                progress_message=f"Applying {action_type} to {target_display_name}",
                success_count=success_count,
                failure_count=failure_count,
            )
            last_error = ""
            for attempt in range(1, _MAX_TARGET_ATTEMPTS + 1):
                try:
                    result = user_admin_providers.execute(action_type, target_user_id, params)
                    provider = str(result.get("provider") or job.get("provider") or "entra")
                    before_summary = dict(result.get("before_summary") or {})
                    after_summary = dict(result.get("after_summary") or {})
                    summary = str(result.get("summary") or "Completed")
                    one_time_secret = result.get("one_time_secret")

                    self._insert_result(
                        job_id=job_id,
                        target_user_id=target_user_id,
                        target_display_name=target_display_name,
                        provider=provider,
                        success=True,
                        summary=summary,
                        error="",
                        before_summary=before_summary,
                        after_summary=after_summary,
                    )
                    self._record_audit(
                        job_id=job_id,
                        actor_email=actor_email,
                        actor_name=actor_name,
                        target_user_id=target_user_id,
                        target_display_name=target_display_name,
                        provider=provider,
                        action_type=action_type,
                        params=params,
                        before_summary=before_summary,
                        after_summary=after_summary,
                        status="success",
                        error="",
                    )
                    if one_time_secret:
                        self._ephemeral_results.setdefault(job_id, {})[target_user_id] = str(one_time_secret)
                    success_count += 1
                    touched_users.append(target_user_id)
                    last_error = ""
                    break
                except UserAdminProviderError as exc:
                    last_error = str(exc)
                    retry_after = exc.retry_after_seconds
                    if attempt < _MAX_TARGET_ATTEMPTS and retry_after is not None:
                        time.sleep(max(1, retry_after))
                        continue
                    if attempt < _MAX_TARGET_ATTEMPTS and "429" in last_error:
                        time.sleep(_DEFAULT_RETRY_DELAY_SECONDS * attempt)
                        continue
                    break
                except Exception as exc:
                    last_error = str(exc)
                    logger.exception("User-admin action %s failed for %s", action_type, target_user_id)
                    break
            else:
                last_error = last_error or "Unknown error"

            if last_error:
                failure_count += 1
                provider = str(job.get("provider") or "entra")
                self._insert_result(
                    job_id=job_id,
                    target_user_id=target_user_id,
                    target_display_name=target_display_name,
                    provider=provider,
                    success=False,
                    summary="Failed",
                    error=last_error,
                    before_summary={},
                    after_summary={},
                )
                self._record_audit(
                    job_id=job_id,
                    actor_email=actor_email,
                    actor_name=actor_name,
                    target_user_id=target_user_id,
                    target_display_name=target_display_name,
                    provider=provider,
                    action_type=action_type,
                    params=params,
                    before_summary={},
                    after_summary={},
                    status="failed",
                    error=last_error,
                )

            self._update_job(
                job_id,
                progress_current=index,
                progress_total=len(target_user_ids),
                progress_message=f"Processed {index} of {len(target_user_ids)} user(s)",
                success_count=success_count,
                failure_count=failure_count,
            )

        final_status = "completed" if success_count or not failure_count else "failed"
        self._update_job(
            job_id,
            status=final_status,
            completed_at=_utcnow().isoformat(),
            progress_current=len(target_user_ids),
            progress_total=len(target_user_ids),
            progress_message="Completed" if final_status == "completed" else "Failed",
            success_count=success_count,
            failure_count=failure_count,
            error="" if final_status == "completed" else "All targets failed",
        )
        self._pending_params.pop(job_id, None)
        self._refresh_touched_users(touched_users)

    async def _background_loop(self) -> None:
        while True:
            try:
                job = await asyncio.get_running_loop().run_in_executor(None, self._claim_next_job)
                if not job:
                    await asyncio.sleep(2)
                    continue
                job_id = str(job.get("job_id") or "")
                await asyncio.get_running_loop().run_in_executor(None, self._process_job, job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("User-admin background job loop failed")
                await asyncio.sleep(2)


user_admin_jobs = UserAdminJobManager()
