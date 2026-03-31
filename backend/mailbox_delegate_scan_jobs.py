"""Durable background jobs for org-wide mailbox delegate scans."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from azure_client import AzureClient
from config import DATA_DIR, MAILBOX_DELEGATE_SCAN_JOB_RETENTION_DAYS
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite
from user_admin_providers import MailboxAdminProvider, UserAdminProviderCancelled, UserAdminProviderError

logger = logging.getLogger(__name__)

_STATUS_VALUES = {"queued", "running", "completed", "failed", "cancelled"}
_PHASE_VALUES = {
    "queued",
    "resolving_user",
    "scanning_send_on_behalf",
    "scanning_exchange_permissions",
    "merging_results",
    "completed",
    "failed",
    "cancelled",
}
_PERMISSION_TYPES = ["send_on_behalf", "send_as", "full_access"]
_EVENT_LOG_LIMIT = 100


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _friendly_delegate_error(message: str) -> str:
    text = str(message or "").strip()
    if "adminapi/v2.0" in text and "(403)" in text:
        return (
            "Mailbox delegation lookup is not enabled for the shared Exchange app yet. "
            "The Entra app registration needs Office 365 Exchange Online application permission "
            "Exchange.ManageAsAppV2 with admin consent plus an Exchange RBAC role such as Recipient Management "
            "before this tool can read mailbox delegation."
        )
    if "pwsh is not installed" in text or "ExchangeOnlineManagement" in text or "Connect-ExchangeOnline" in text:
        return (
            "Mailbox delegation lookup needs Exchange Online PowerShell support on the app runtime. "
            "Install pwsh plus the ExchangeOnlineManagement module so the app can read Send As and Full Access."
        )
    if "timed out" in text.lower():
        return (
            "Mailbox delegation lookup took too long to finish. "
            "Try the scan again; if it keeps timing out, the tenant-side Exchange query may need tuning."
        )
    return text


def _json_loads_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _json_loads_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


class MailboxDelegateScanJobManager:
    """Postgres-aware FIFO queue for org-wide mailbox delegate scans."""

    def __init__(
        self,
        db_path: str | None = None,
        *,
        provider_factory: Callable[[], MailboxAdminProvider] | None = None,
    ) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "mailbox_delegate_scan_jobs.db")
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.RLock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._bg_task: asyncio.Task[None] | None = None
        self._provider_factory = provider_factory or (lambda: MailboxAdminProvider(AzureClient()))
        self._init_db()
        self._requeue_running_jobs()
        self._cleanup_expired_jobs()

    def _conn(self) -> sqlite3.Connection:
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return connect_sqlite(self._db_path)

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            return
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mailbox_delegate_scan_jobs (
                    job_id TEXT PRIMARY KEY,
                    site_scope TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    requested_by_email TEXT NOT NULL,
                    requested_by_name TEXT NOT NULL,
                    user_identifier TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    principal_name TEXT NOT NULL DEFAULT '',
                    primary_address TEXT NOT NULL DEFAULT '',
                    provider_enabled INTEGER NOT NULL DEFAULT 0,
                    supported_permission_types_json TEXT NOT NULL DEFAULT '[]',
                    permission_counts_json TEXT NOT NULL DEFAULT '{}',
                    note TEXT NOT NULL DEFAULT '',
                    mailbox_count INTEGER NOT NULL DEFAULT 0,
                    scanned_mailbox_count INTEGER NOT NULL DEFAULT 0,
                    mailboxes_json TEXT NOT NULL DEFAULT '[]',
                    requested_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    progress_current INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    progress_message TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS mailbox_delegate_scan_job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mailbox_delegate_scan_jobs_requested
                    ON mailbox_delegate_scan_jobs (requested_by_email, requested_at DESC);
                CREATE INDEX IF NOT EXISTS idx_mailbox_delegate_scan_jobs_status
                    ON mailbox_delegate_scan_jobs (status, requested_at DESC);
                CREATE INDEX IF NOT EXISTS idx_mailbox_delegate_scan_job_events_job
                    ON mailbox_delegate_scan_job_events (job_id, event_id DESC);
                """
            )
            conn.commit()

    def _cleanup_expired_jobs(self) -> None:
        cutoff = (_utcnow() - timedelta(days=MAILBOX_DELEGATE_SCAN_JOB_RETENTION_DAYS)).isoformat()
        placeholder = self._placeholder()
        with self._conn() as conn:
            expired_ids = [
                str(row["job_id"])
                for row in conn.execute(
                    """
                    SELECT job_id
                    FROM mailbox_delegate_scan_jobs
                    WHERE completed_at IS NOT NULL
                      AND completed_at < {0}
                    """.format(placeholder),
                    (cutoff,),
                ).fetchall()
            ]
            if expired_ids:
                conn.executemany(
                    f"DELETE FROM mailbox_delegate_scan_job_events WHERE job_id = {placeholder}",
                    [(job_id,) for job_id in expired_ids],
                )
                conn.executemany(
                    f"DELETE FROM mailbox_delegate_scan_jobs WHERE job_id = {placeholder}",
                    [(job_id,) for job_id in expired_ids],
                )
            conn.commit()

    def _requeue_running_jobs(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE mailbox_delegate_scan_jobs
                SET status = 'queued',
                    phase = 'queued',
                    started_at = NULL,
                    completed_at = NULL,
                    progress_current = 0,
                    progress_total = 0,
                    progress_message = 'Re-queued after restart',
                    error = ''
                WHERE status = 'running'
                """
            )
            conn.commit()

    def _append_event(self, job_id: str, level: str, message: str) -> None:
        normalized_level = str(level or "info").strip().lower()
        if normalized_level not in {"info", "warning", "error"}:
            normalized_level = "info"
        placeholder = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO mailbox_delegate_scan_job_events (job_id, level, message, created_at)
                VALUES ({0}, {0}, {0}, {0})
                """.format(placeholder),
                (job_id, normalized_level, str(message or ""), _utcnow().isoformat()),
            )
            conn.execute(
                """
                DELETE FROM mailbox_delegate_scan_job_events
                WHERE job_id = {0}
                  AND event_id NOT IN (
                    SELECT event_id
                    FROM mailbox_delegate_scan_job_events
                    WHERE job_id = {0}
                    ORDER BY event_id DESC
                    LIMIT {1}
                  )
                """.format(placeholder, self._placeholder()),
                (job_id, job_id, _EVENT_LOG_LIMIT),
            )
            conn.commit()

    def _coerce_job(self, row: sqlite3.Row | dict[str, Any] | None, *, include_events: bool = False) -> dict[str, Any] | None:
        if not row:
            return None
        payload = dict(row)
        status = str(payload.get("status") or "queued")
        phase = str(payload.get("phase") or "queued")
        job_id = str(payload.get("job_id") or "")
        return {
            "job_id": job_id,
            "site_scope": str(payload.get("site_scope") or "primary"),
            "status": status if status in _STATUS_VALUES else "queued",
            "phase": phase if phase in _PHASE_VALUES else "queued",
            "requested_by_email": str(payload.get("requested_by_email") or ""),
            "requested_by_name": str(payload.get("requested_by_name") or ""),
            "user": str(payload.get("user_identifier") or ""),
            "display_name": str(payload.get("display_name") or ""),
            "principal_name": str(payload.get("principal_name") or ""),
            "primary_address": str(payload.get("primary_address") or ""),
            "provider_enabled": bool(payload.get("provider_enabled")),
            "supported_permission_types": _json_loads_list(payload.get("supported_permission_types_json")) or list(_PERMISSION_TYPES),
            "permission_counts": _json_loads_dict(payload.get("permission_counts_json")),
            "note": str(payload.get("note") or ""),
            "mailbox_count": int(payload.get("mailbox_count") or 0),
            "scanned_mailbox_count": int(payload.get("scanned_mailbox_count") or 0),
            "mailboxes": _json_loads_list(payload.get("mailboxes_json")),
            "requested_at": str(payload.get("requested_at") or ""),
            "started_at": payload.get("started_at") or None,
            "completed_at": payload.get("completed_at") or None,
            "progress_current": int(payload.get("progress_current") or 0),
            "progress_total": int(payload.get("progress_total") or 0),
            "progress_message": str(payload.get("progress_message") or ""),
            "error": str(payload.get("error") or "") or None,
            "events": self.get_job_events(job_id) if include_events else [],
        }

    def _cancel_event_for_job(self, job_id: str) -> threading.Event:
        with self._lock:
            return self._cancel_events.setdefault(job_id, threading.Event())

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(job_id)
        return bool(event and event.is_set())

    def _clear_cancel_request(self, job_id: str) -> None:
        with self._lock:
            self._cancel_events.pop(job_id, None)

    def _update_job(self, job_id: str, *, skip_if_cancelled: bool = False, **fields: Any) -> None:
        if not fields:
            return
        placeholder = self._placeholder()
        assignments = ", ".join(f"{key} = {placeholder}" for key in fields)
        values = list(fields.values()) + [job_id]
        query = f"UPDATE mailbox_delegate_scan_jobs SET {assignments} WHERE job_id = {placeholder}"
        if skip_if_cancelled:
            query += " AND status <> 'cancelled'"
        with self._conn() as conn:
            conn.execute(query, values)
            conn.commit()

    def create_job(
        self,
        *,
        site_scope: str,
        user: str,
        requested_by_email: str,
        requested_by_name: str,
    ) -> dict[str, Any]:
        normalized_user = str(user or "").strip()
        if not normalized_user:
            raise ValueError("User UPN or email is required")
        requested_email = str(requested_by_email or "").strip().lower()
        if not requested_email:
            raise ValueError("A signed-in user email is required")

        job_id = uuid.uuid4().hex
        requested_at = _utcnow().isoformat()
        placeholder = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO mailbox_delegate_scan_jobs (
                    job_id,
                    site_scope,
                    status,
                    phase,
                    requested_by_email,
                    requested_by_name,
                    user_identifier,
                    provider_enabled,
                    supported_permission_types_json,
                    requested_at,
                    progress_message
                )
                VALUES (
                    {0}, {0}, 'queued', 'queued', {0}, {0}, {0}, 1, {0}, {0}, 'Queued'
                )
                """.format(placeholder),
                (
                    job_id,
                    str(site_scope or "primary"),
                    requested_email,
                    str(requested_by_name or ""),
                    normalized_user,
                    json.dumps(_PERMISSION_TYPES, separators=(",", ":")),
                    requested_at,
                ),
            )
            conn.commit()
        self._append_event(job_id, "info", f"Queued delegate mailbox scan for {normalized_user}.")
        return self.get_job(job_id, include_events=True) or {
            "job_id": job_id,
            "site_scope": site_scope,
            "status": "queued",
            "phase": "queued",
            "requested_by_email": requested_email,
            "requested_by_name": requested_by_name,
            "user": normalized_user,
            "display_name": "",
            "principal_name": normalized_user,
            "primary_address": normalized_user,
            "provider_enabled": True,
            "supported_permission_types": list(_PERMISSION_TYPES),
            "permission_counts": {},
            "note": "",
            "mailbox_count": 0,
            "scanned_mailbox_count": 0,
            "mailboxes": [],
            "requested_at": requested_at,
            "started_at": None,
            "completed_at": None,
            "progress_current": 0,
            "progress_total": 0,
            "progress_message": "Queued",
            "error": None,
            "events": [],
        }

    def cancel_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        if str(job.get("status") or "") in {"completed", "failed", "cancelled"}:
            return False

        self._cancel_event_for_job(job_id).set()
        cancellation_message = (
            "Mailbox delegate scan cancelled before it started."
            if str(job.get("status") or "") == "queued"
            else "Mailbox delegate scan cancelled by user. Stopping the current Exchange query."
        )
        self._update_job(
            job_id,
            status="cancelled",
            phase="cancelled",
            completed_at=_utcnow().isoformat(),
            note="Mailbox delegate scan cancelled by user.",
            progress_message=cancellation_message,
            error="",
        )
        self._append_event(job_id, "warning", cancellation_message)
        return True

    def get_job(self, job_id: str, *, include_events: bool = False) -> dict[str, Any] | None:
        placeholder = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM mailbox_delegate_scan_jobs WHERE job_id = {placeholder}",
                (job_id,),
            ).fetchone()
        return self._coerce_job(row, include_events=include_events)

    def get_job_events(self, job_id: str) -> list[dict[str, Any]]:
        placeholder = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT event_id, level, message, created_at
                FROM mailbox_delegate_scan_job_events
                WHERE job_id = {0}
                ORDER BY event_id DESC
                LIMIT {1}
                """.format(placeholder, self._placeholder()),
                (job_id, _EVENT_LOG_LIMIT),
            ).fetchall()
        return [
            {
                "event_id": int(row["event_id"]),
                "level": str(row["level"] or "info"),
                "message": str(row["message"] or ""),
                "created_at": str(row["created_at"] or ""),
            }
            for row in rows
        ]

    def list_jobs_for_user(self, email: str, *, limit: int = 20) -> list[dict[str, Any]]:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return []
        placeholder = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM mailbox_delegate_scan_jobs
                WHERE requested_by_email = {0}
                ORDER BY requested_at DESC
                LIMIT {0}
                """.format(placeholder),
                (normalized_email, max(1, int(limit))),
            ).fetchall()
        return [self._coerce_job(row, include_events=False) for row in rows if row]

    def clear_finished_jobs_for_user(self, email: str) -> int:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return 0
        placeholder = self._placeholder()
        with self._conn() as conn:
            finished_ids = [
                str(row["job_id"])
                for row in conn.execute(
                    """
                    SELECT job_id
                    FROM mailbox_delegate_scan_jobs
                    WHERE requested_by_email = {0}
                      AND completed_at IS NOT NULL
                    """.format(placeholder),
                    (normalized_email,),
                ).fetchall()
            ]
            if not finished_ids:
                return 0
            conn.executemany(
                f"DELETE FROM mailbox_delegate_scan_job_events WHERE job_id = {placeholder}",
                [(job_id,) for job_id in finished_ids],
            )
            conn.executemany(
                f"DELETE FROM mailbox_delegate_scan_jobs WHERE job_id = {placeholder}",
                [(job_id,) for job_id in finished_ids],
            )
            conn.commit()
        with self._lock:
            for job_id in finished_ids:
                self._cancel_events.pop(job_id, None)
        return len(finished_ids)

    def job_belongs_to(self, job_id: str, email: str, *, is_admin: bool = False) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        if is_admin:
            return True
        return str(job.get("requested_by_email") or "").lower() == str(email or "").lower()

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
            placeholder = self._placeholder()
            with self._conn() as conn:
                row = conn.execute(
                    """
                    SELECT *
                    FROM mailbox_delegate_scan_jobs
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
                    UPDATE mailbox_delegate_scan_jobs
                    SET status = 'running',
                        phase = 'resolving_user',
                        started_at = {0},
                        completed_at = NULL,
                        progress_current = 0,
                        progress_total = 4,
                        progress_message = 'Resolving user identity',
                        error = ''
                    WHERE job_id = {0}
                    """.format(placeholder),
                    (_utcnow().isoformat(), job_id),
                )
                conn.commit()
            self._clear_cancel_request(job_id)
            return self.get_job(job_id)

    def _raise_if_cancel_requested(self, job_id: str) -> None:
        if self._is_cancel_requested(job_id):
            raise UserAdminProviderCancelled("Mailbox delegate scan cancelled by user.")
        job = self.get_job(job_id)
        if job and str(job.get("status") or "") == "cancelled":
            raise UserAdminProviderCancelled("Mailbox delegate scan cancelled by user.")

    def _process_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return

        user = str(job.get("user") or "")
        last_phase = ""

        def progress_callback(payload: dict[str, Any]) -> None:
            nonlocal last_phase
            if not isinstance(payload, dict):
                return
            if self._is_cancel_requested(job_id):
                return
            fields: dict[str, Any] = {}
            phase = str(payload.get("phase") or "").strip()
            if phase in _PHASE_VALUES:
                fields["phase"] = phase
            if "progress_current" in payload:
                fields["progress_current"] = int(payload.get("progress_current") or 0)
            if "progress_total" in payload:
                fields["progress_total"] = int(payload.get("progress_total") or 0)
            message = str(payload.get("progress_message") or "").strip()
            if message:
                fields["progress_message"] = message
            if "scanned_mailbox_count" in payload:
                fields["scanned_mailbox_count"] = int(payload.get("scanned_mailbox_count") or 0)
            if fields:
                self._update_job(job_id, skip_if_cancelled=True, **fields)
            if phase and phase != last_phase and message:
                last_phase = phase
                self._append_event(job_id, "info", message)

        try:
            self._append_event(job_id, "info", f"Starting delegate mailbox scan for {user}.")
            self._raise_if_cancel_requested(job_id)
            provider = self._provider_factory()
            result = provider.list_delegate_mailboxes_for_user(
                user,
                progress_callback=progress_callback,
                cancel_requested=lambda: self._is_cancel_requested(job_id),
            )
            self._raise_if_cancel_requested(job_id)
            permission_counts = result.get("permission_counts") if isinstance(result.get("permission_counts"), dict) else {}
            mailboxes = result.get("mailboxes") if isinstance(result.get("mailboxes"), list) else []
            note = str(result.get("note") or "").strip()
            completed_message = note or "Mailbox delegate scan completed."
            self._update_job(
                job_id,
                skip_if_cancelled=True,
                status="completed",
                phase="completed",
                display_name=str(result.get("display_name") or ""),
                principal_name=str(result.get("principal_name") or user),
                primary_address=str(result.get("primary_address") or user),
                provider_enabled=int(bool(result.get("provider_enabled"))),
                supported_permission_types_json=json.dumps(
                    result.get("supported_permission_types") or list(_PERMISSION_TYPES),
                    separators=(",", ":"),
                ),
                permission_counts_json=json.dumps(permission_counts, separators=(",", ":")),
                note=note,
                mailbox_count=int(result.get("mailbox_count") or 0),
                scanned_mailbox_count=int(result.get("scanned_mailbox_count") or 0),
                mailboxes_json=json.dumps(mailboxes, separators=(",", ":")),
                completed_at=_utcnow().isoformat(),
                progress_current=4,
                progress_total=4,
                progress_message=completed_message,
                error="",
            )
            self._append_event(job_id, "info", completed_message)
        except UserAdminProviderCancelled:
            latest = self.get_job(job_id)
            if latest and str(latest.get("status") or "") != "cancelled":
                self._update_job(
                    job_id,
                    status="cancelled",
                    phase="cancelled",
                    completed_at=_utcnow().isoformat(),
                    note="Mailbox delegate scan cancelled by user.",
                    progress_message="Mailbox delegate scan cancelled by user.",
                    error="",
                )
                self._append_event(job_id, "warning", "Mailbox delegate scan cancelled by user.")
        except Exception as exc:
            latest = self.get_job(job_id)
            if latest and str(latest.get("status") or "") == "cancelled":
                return
            logger.exception("Mailbox delegate scan job %s failed", job_id)
            friendly_error = _friendly_delegate_error(str(exc))
            self._append_event(job_id, "error", friendly_error)
            self._update_job(
                job_id,
                skip_if_cancelled=True,
                status="failed",
                phase="failed",
                completed_at=_utcnow().isoformat(),
                progress_message="Mailbox delegate scan failed",
                error=friendly_error,
            )
        finally:
            self._clear_cancel_request(job_id)

    async def _background_loop(self) -> None:
        while True:
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._cleanup_expired_jobs)
                job = await asyncio.get_running_loop().run_in_executor(None, self._claim_next_job)
                if not job:
                    await asyncio.sleep(3)
                    continue
                job_id = str(job.get("job_id") or "")
                await asyncio.get_running_loop().run_in_executor(None, self._process_job, job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Mailbox delegate scan background worker loop failed")
                await asyncio.sleep(3)


mailbox_delegate_scan_jobs = MailboxDelegateScanJobManager()
