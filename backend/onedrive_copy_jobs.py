"""Durable background jobs for copying full OneDrive trees between users."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from azure_client import AzureApiError, AzureClient
from config import (
    DATA_DIR,
    ONEDRIVE_COPY_BATCH_SIZE,
    ONEDRIVE_COPY_JOB_RETENTION_DAYS,
    ONEDRIVE_COPY_MAX_RETRIES,
    ONEDRIVE_COPY_RETRY_DELAY_BASE_SECONDS,
)
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_STATUS_VALUES = {"queued", "running", "completed", "failed"}
_PHASE_VALUES = {
    "queued",
    "resolving_drives",
    "enumerating",
    "creating_folders",
    "dispatching_copy",
    "completed",
    "failed",
}
_SYSTEM_FOLDERS = (
    "Apps",
    "Attachments",
    "Microsoft Teams Chat Files",
    "Microsoft Copilot Chat Files",
    "Recordings",
    "Videos",
)
_EVENT_LOG_LIMIT = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OneDriveCopyJobManager:
    """Postgres-aware FIFO queue for OneDrive copy jobs."""

    def __init__(
        self,
        db_path: str | None = None,
        *,
        client_factory: Callable[[], AzureClient] | None = None,
    ) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "onedrive_copy_jobs.db")
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._bg_task: asyncio.Task[None] | None = None
        self._client_factory = client_factory or AzureClient
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
            self._backfill_from_sqlite_if_needed()
            return
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS onedrive_copy_jobs (
                    job_id TEXT PRIMARY KEY,
                    site_scope TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    requested_by_email TEXT NOT NULL,
                    requested_by_name TEXT NOT NULL,
                    source_upn TEXT NOT NULL,
                    destination_upn TEXT NOT NULL,
                    destination_folder TEXT NOT NULL,
                    test_mode INTEGER NOT NULL DEFAULT 0,
                    test_file_limit INTEGER NOT NULL DEFAULT 25,
                    exclude_system_folders INTEGER NOT NULL DEFAULT 1,
                    requested_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    progress_current INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    progress_message TEXT NOT NULL DEFAULT '',
                    total_folders_found INTEGER NOT NULL DEFAULT 0,
                    total_files_found INTEGER NOT NULL DEFAULT 0,
                    folders_created INTEGER NOT NULL DEFAULT 0,
                    files_dispatched INTEGER NOT NULL DEFAULT 0,
                    files_failed INTEGER NOT NULL DEFAULT 0,
                    source_drive_id TEXT NOT NULL DEFAULT '',
                    destination_drive_id TEXT NOT NULL DEFAULT '',
                    destination_top_folder_id TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS onedrive_copy_job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_onedrive_copy_jobs_requested_at
                    ON onedrive_copy_jobs (requested_at DESC);
                CREATE INDEX IF NOT EXISTS idx_onedrive_copy_events_job
                    ON onedrive_copy_job_events (job_id, event_id DESC);
                CREATE TABLE IF NOT EXISTS onedrive_copy_saved_upns (
                    normalized_upn TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL DEFAULT '',
                    principal_name TEXT NOT NULL DEFAULT '',
                    mail TEXT NOT NULL DEFAULT '',
                    source_hint TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    last_used_by_email TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_onedrive_copy_saved_upns_last_used
                    ON onedrive_copy_saved_upns (last_used_at DESC);
                """
            )
            conn.commit()

    def _backfill_from_sqlite_if_needed(self) -> None:
        if not self._use_postgres or not os.path.exists(self._db_path):
            return
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM onedrive_copy_jobs) AS job_count,
                    (SELECT COUNT(*) FROM onedrive_copy_job_events) AS event_count,
                    (SELECT COUNT(*) FROM onedrive_copy_saved_upns) AS saved_count
                """
            ).fetchone()
            if rows and all(int(rows[key] or 0) > 0 for key in ("job_count", "event_count", "saved_count")):
                return
        with connect_sqlite(self._db_path) as sqlite_conn:
            job_rows = sqlite_conn.execute("SELECT * FROM onedrive_copy_jobs").fetchall()
            event_rows = sqlite_conn.execute("SELECT * FROM onedrive_copy_job_events").fetchall()
            saved_rows = sqlite_conn.execute("SELECT * FROM onedrive_copy_saved_upns").fetchall()
        with self._conn() as conn:
            if job_rows:
                conn.executemany(
                    """
                    INSERT INTO onedrive_copy_jobs (
                        job_id,
                        site_scope,
                        status,
                        phase,
                        requested_by_email,
                        requested_by_name,
                        source_upn,
                        destination_upn,
                        destination_folder,
                        test_mode,
                        test_file_limit,
                        exclude_system_folders,
                        requested_at,
                        started_at,
                        completed_at,
                        progress_current,
                        progress_total,
                        progress_message,
                        total_folders_found,
                        total_files_found,
                        folders_created,
                        files_dispatched,
                        files_failed,
                        source_drive_id,
                        destination_drive_id,
                        destination_top_folder_id,
                        error
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT(job_id) DO NOTHING
                    """,
                    [
                        tuple(row[column] for column in (
                            "job_id",
                            "site_scope",
                            "status",
                            "phase",
                            "requested_by_email",
                            "requested_by_name",
                            "source_upn",
                            "destination_upn",
                            "destination_folder",
                            "test_mode",
                            "test_file_limit",
                            "exclude_system_folders",
                            "requested_at",
                            "started_at",
                            "completed_at",
                            "progress_current",
                            "progress_total",
                            "progress_message",
                            "total_folders_found",
                            "total_files_found",
                            "folders_created",
                            "files_dispatched",
                            "files_failed",
                            "source_drive_id",
                            "destination_drive_id",
                            "destination_top_folder_id",
                            "error",
                        ))
                        for row in job_rows
                    ],
                )
            if event_rows:
                conn.executemany(
                    """
                    INSERT INTO onedrive_copy_job_events (
                        job_id,
                        level,
                        message,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        (
                            row["job_id"],
                            row["level"],
                            row["message"],
                            row["created_at"],
                        )
                        for row in event_rows
                    ],
                )
            if saved_rows:
                conn.executemany(
                    """
                    INSERT INTO onedrive_copy_saved_upns (
                        normalized_upn,
                        display_name,
                        principal_name,
                        mail,
                        source_hint,
                        created_at,
                        updated_at,
                        last_used_at,
                        last_used_by_email
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(normalized_upn) DO NOTHING
                    """,
                    [
                        (
                            row["normalized_upn"],
                            row["display_name"],
                            row["principal_name"],
                            row["mail"],
                            row["source_hint"],
                            row["created_at"],
                            row["updated_at"],
                            row["last_used_at"],
                            row["last_used_by_email"],
                        )
                        for row in saved_rows
                    ],
                )
            conn.commit()

    @staticmethod
    def _normalize_upn(value: str) -> str:
        return str(value or "").strip().lower()

    def remember_user_option(
        self,
        upn: str,
        *,
        display_name: str = "",
        principal_name: str = "",
        mail: str = "",
        source_hint: str = "manual",
        used_by_email: str = "",
    ) -> None:
        normalized_upn = self._normalize_upn(principal_name or mail or upn)
        if not normalized_upn:
            return
        now = _utcnow().isoformat()
        display_name = str(display_name or "").strip()
        principal_name = str(principal_name or normalized_upn).strip()
        mail = str(mail or "").strip()
        used_by_email = str(used_by_email or "").strip().lower()
        normalized_source = "entra" if str(source_hint or "").strip().lower() == "entra" else "manual"
        placeholder = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO onedrive_copy_saved_upns (
                    normalized_upn,
                    display_name,
                    principal_name,
                    mail,
                    source_hint,
                    created_at,
                    updated_at,
                    last_used_at,
                    last_used_by_email
                )
                VALUES ({0}, {0}, {0}, {0}, {0}, {0}, {0}, {0}, {0})
                ON CONFLICT(normalized_upn) DO UPDATE SET
                    display_name = CASE
                        WHEN excluded.display_name <> '' THEN excluded.display_name
                        ELSE onedrive_copy_saved_upns.display_name
                    END,
                    principal_name = CASE
                        WHEN excluded.principal_name <> '' THEN excluded.principal_name
                        ELSE onedrive_copy_saved_upns.principal_name
                    END,
                    mail = CASE
                        WHEN excluded.mail <> '' THEN excluded.mail
                        ELSE onedrive_copy_saved_upns.mail
                    END,
                    source_hint = CASE
                        WHEN excluded.source_hint = 'entra' THEN 'entra'
                        ELSE onedrive_copy_saved_upns.source_hint
                    END,
                    updated_at = excluded.updated_at,
                    last_used_at = excluded.last_used_at,
                    last_used_by_email = CASE
                        WHEN excluded.last_used_by_email <> '' THEN excluded.last_used_by_email
                        ELSE onedrive_copy_saved_upns.last_used_by_email
                    END
                """.format(placeholder),
                (
                    normalized_upn,
                    display_name,
                    principal_name,
                    mail,
                    normalized_source,
                    now,
                    now,
                    now,
                    used_by_email,
                ),
            )
            conn.commit()

    def list_saved_user_options(self, *, search: str = "", limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT normalized_upn, display_name, principal_name, mail, source_hint, last_used_at
                FROM onedrive_copy_saved_upns
                ORDER BY last_used_at DESC, principal_name ASC, normalized_upn ASC
                """
            ).fetchall()
        search_lower = str(search or "").strip().lower()
        result: list[dict[str, Any]] = []
        for row in rows:
            normalized_upn = self._normalize_upn(str(row["normalized_upn"] or ""))
            if not normalized_upn:
                continue
            display_name = str(row["display_name"] or "").strip()
            principal_name = str(row["principal_name"] or "").strip() or normalized_upn
            mail = str(row["mail"] or "").strip()
            if search_lower:
                haystack = " ".join([normalized_upn, display_name, principal_name, mail]).lower()
                if search_lower not in haystack:
                    continue
            result.append(
                {
                    "id": f"saved:{normalized_upn}",
                    "display_name": display_name,
                    "principal_name": principal_name,
                    "mail": mail,
                    "enabled": None,
                    "source": "saved",
                    "last_used_at": str(row["last_used_at"] or ""),
                }
            )
            if len(result) >= max(1, int(limit)):
                break
        return result

    def _cleanup_expired_jobs(self) -> None:
        cutoff = (_utcnow() - timedelta(days=ONEDRIVE_COPY_JOB_RETENTION_DAYS)).isoformat()
        placeholder = self._placeholder()
        with self._conn() as conn:
            expired_ids = [
                str(row["job_id"])
                for row in conn.execute(
                    """
                    SELECT job_id
                    FROM onedrive_copy_jobs
                    WHERE completed_at IS NOT NULL
                      AND completed_at < {0}
                    """.format(placeholder),
                    (cutoff,),
                ).fetchall()
            ]
            if expired_ids:
                conn.executemany(
                    f"DELETE FROM onedrive_copy_job_events WHERE job_id = {placeholder}",
                    [(job_id,) for job_id in expired_ids],
                )
                conn.executemany(
                    f"DELETE FROM onedrive_copy_jobs WHERE job_id = {placeholder}",
                    [(job_id,) for job_id in expired_ids],
                )
            conn.commit()

    def _requeue_running_jobs(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE onedrive_copy_jobs
                SET status = 'queued',
                    phase = 'queued',
                    started_at = NULL,
                    completed_at = NULL,
                    progress_current = 0,
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
                INSERT INTO onedrive_copy_job_events (job_id, level, message, created_at)
                VALUES ({0}, {0}, {0}, {0})
                """.format(placeholder),
                (job_id, normalized_level, str(message or ""), _utcnow().isoformat()),
            )
            conn.execute(
                """
                DELETE FROM onedrive_copy_job_events
                WHERE job_id = {0}
                  AND event_id NOT IN (
                    SELECT event_id
                    FROM onedrive_copy_job_events
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
            "source_upn": str(payload.get("source_upn") or ""),
            "destination_upn": str(payload.get("destination_upn") or ""),
            "destination_folder": str(payload.get("destination_folder") or ""),
            "test_mode": bool(payload.get("test_mode")),
            "test_file_limit": int(payload.get("test_file_limit") or 25),
            "exclude_system_folders": bool(payload.get("exclude_system_folders")),
            "requested_at": str(payload.get("requested_at") or ""),
            "started_at": payload.get("started_at") or None,
            "completed_at": payload.get("completed_at") or None,
            "progress_current": int(payload.get("progress_current") or 0),
            "progress_total": int(payload.get("progress_total") or 0),
            "progress_message": str(payload.get("progress_message") or ""),
            "total_folders_found": int(payload.get("total_folders_found") or 0),
            "total_files_found": int(payload.get("total_files_found") or 0),
            "folders_created": int(payload.get("folders_created") or 0),
            "files_dispatched": int(payload.get("files_dispatched") or 0),
            "files_failed": int(payload.get("files_failed") or 0),
            "error": str(payload.get("error") or "") or None,
            "events": self.get_job_events(job_id) if include_events else [],
        }

    def _update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        placeholder = self._placeholder()
        assignments = ", ".join(f"{key} = {placeholder}" for key in fields)
        values = list(fields.values()) + [job_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE onedrive_copy_jobs SET {assignments} WHERE job_id = {placeholder}", values)
            conn.commit()

    def create_job(
        self,
        *,
        site_scope: str,
        source_upn: str,
        destination_upn: str,
        destination_folder: str,
        test_mode: bool,
        test_file_limit: int,
        exclude_system_folders: bool,
        requested_by_email: str,
        requested_by_name: str,
    ) -> dict[str, Any]:
        source = str(source_upn or "").strip()
        destination = str(destination_upn or "").strip()
        folder = str(destination_folder or "").strip()
        if not source:
            raise ValueError("Source UPN is required")
        if not destination:
            raise ValueError("Destination UPN is required")
        if not folder:
            raise ValueError("Destination folder is required")
        if source.lower() == destination.lower():
            raise ValueError("Source and destination UPNs must be different")

        job_id = uuid.uuid4().hex
        requested_at = _utcnow().isoformat()
        placeholder = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO onedrive_copy_jobs (
                    job_id,
                    site_scope,
                    status,
                    phase,
                    requested_by_email,
                    requested_by_name,
                    source_upn,
                    destination_upn,
                    destination_folder,
                    test_mode,
                    test_file_limit,
                    exclude_system_folders,
                    requested_at,
                    progress_message
                )
                VALUES (
                    {0}, {0}, 'queued', 'queued', {0}, {0}, {0}, {0}, {0}, {0}, {0}, {0}, {0}, 'Queued'
                )
                """.format(placeholder),
                (
                    job_id,
                    str(site_scope or "primary"),
                    requested_by_email,
                    requested_by_name,
                    source,
                    destination,
                    folder,
                    int(bool(test_mode)),
                    int(test_file_limit or 25),
                    int(bool(exclude_system_folders)),
                    requested_at,
                ),
            )
            conn.commit()
        self.remember_user_option(source, principal_name=source, source_hint="manual", used_by_email=requested_by_email)
        self.remember_user_option(destination, principal_name=destination, source_hint="manual", used_by_email=requested_by_email)
        self._append_event(job_id, "info", f"Queued copy from {source} to {destination} into '{folder}'.")
        return self.get_job(job_id, include_events=True) or {
            "job_id": job_id,
            "site_scope": site_scope,
            "status": "queued",
            "phase": "queued",
            "requested_by_email": requested_by_email,
            "requested_by_name": requested_by_name,
            "source_upn": source,
            "destination_upn": destination,
            "destination_folder": folder,
            "test_mode": bool(test_mode),
            "test_file_limit": int(test_file_limit or 25),
            "exclude_system_folders": bool(exclude_system_folders),
            "requested_at": requested_at,
            "started_at": None,
            "completed_at": None,
            "progress_current": 0,
            "progress_total": 0,
            "progress_message": "Queued",
            "total_folders_found": 0,
            "total_files_found": 0,
            "folders_created": 0,
            "files_dispatched": 0,
            "files_failed": 0,
            "error": None,
            "events": [],
        }

    def get_job(self, job_id: str, *, include_events: bool = False) -> dict[str, Any] | None:
        placeholder = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM onedrive_copy_jobs WHERE job_id = {placeholder}",
                (job_id,),
            ).fetchone()
        return self._coerce_job(row, include_events=include_events)

    def get_job_events(self, job_id: str) -> list[dict[str, Any]]:
        placeholder = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT event_id, level, message, created_at
                FROM onedrive_copy_job_events
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

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        placeholder = self._placeholder()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM onedrive_copy_jobs
                ORDER BY requested_at DESC
                LIMIT {0}
                """.format(placeholder),
                (max(1, int(limit)),),
            ).fetchall()
        return [self._coerce_job(row, include_events=False) for row in rows if row]

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
                    FROM onedrive_copy_jobs
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
                    UPDATE onedrive_copy_jobs
                    SET status = 'running',
                        phase = 'resolving_drives',
                        started_at = {0},
                        completed_at = NULL,
                        progress_current = 0,
                        progress_total = 0,
                        progress_message = 'Resolving OneDrive IDs',
                        error = ''
                    WHERE job_id = {0}
                    """.format(placeholder),
                    (_utcnow().isoformat(), job_id),
                )
                conn.commit()
            return self.get_job(job_id)

    def _set_phase(self, job_id: str, phase: str, message: str, **extra_fields: Any) -> None:
        fields = {"phase": phase, "progress_message": message, **extra_fields}
        self._update_job(job_id, **fields)

    @staticmethod
    def _display_file_path(file_item: dict[str, Any]) -> str:
        relative_path = str(file_item.get("relative_path") or "").strip("/")
        name = str(file_item.get("name") or "").strip()
        if relative_path and name:
            return f"{relative_path}/{name}"
        return name or relative_path or "Unnamed file"

    def _walk_tree_recursive(
        self,
        client: AzureClient,
        source_upn: str,
        folder_id: str,
        rel_path: str,
        *,
        exclude_system_folders: bool,
        folders: list[str],
        files: list[dict[str, str]],
        job_id: str,
    ) -> None:
        children = client.list_user_drive_children(source_upn, folder_id)
        for item in children:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            if isinstance(item.get("folder"), dict):
                if exclude_system_folders and not rel_path and name in _SYSTEM_FOLDERS:
                    self._append_event(job_id, "info", f"Skipped root system folder '{name}'.")
                    continue
                sub_path = f"{rel_path}/{name}" if rel_path else name
                folders.append(sub_path)
                self._walk_tree_recursive(
                    client,
                    source_upn,
                    str(item.get("id") or ""),
                    sub_path,
                    exclude_system_folders=exclude_system_folders,
                    folders=folders,
                    files=files,
                    job_id=job_id,
                )
            else:
                files.append(
                    {
                        "item_id": str(item.get("id") or ""),
                        "name": name,
                        "relative_path": rel_path,
                    }
                )

    @staticmethod
    def _folders_needed_for_files(files: list[dict[str, str]]) -> list[str]:
        required: set[str] = set()
        for file_item in files:
            relative_path = str(file_item.get("relative_path") or "").strip("/")
            if not relative_path:
                continue
            current = relative_path
            while current:
                required.add(current)
                if "/" not in current:
                    break
                current = current.rsplit("/", 1)[0]
        return sorted(required, key=lambda path: len([part for part in path.split("/") if part]))

    def _process_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return

        client = self._client_factory()
        source_upn = str(job.get("source_upn") or "")
        destination_upn = str(job.get("destination_upn") or "")
        destination_folder = str(job.get("destination_folder") or "")
        test_mode = bool(job.get("test_mode"))
        test_file_limit = int(job.get("test_file_limit") or 25)
        exclude_system_folders = bool(job.get("exclude_system_folders"))

        try:
            self._set_phase(job_id, "resolving_drives", "Resolving source and destination OneDrives")
            source_drive = client.get_user_drive(source_upn)
            destination_drive = client.get_user_drive(destination_upn)
            source_root = client.get_user_drive_root(source_upn)
            source_drive_id = str(source_drive.get("id") or "").strip()
            destination_drive_id = str(destination_drive.get("id") or "").strip()
            source_root_id = str(source_root.get("id") or "root").strip() or "root"
            if not source_drive_id or not destination_drive_id:
                raise RuntimeError("Unable to resolve OneDrive IDs for the source or destination user")

            destination_top_folder = client.create_user_drive_folder(destination_upn, "root", destination_folder)
            destination_top_folder_id = str(destination_top_folder.get("id") or "").strip()
            if not destination_top_folder_id:
                raise RuntimeError("Unable to create the top-level destination folder")
            self._update_job(
                job_id,
                source_drive_id=source_drive_id,
                destination_drive_id=destination_drive_id,
                destination_top_folder_id=destination_top_folder_id,
            )
            self._append_event(job_id, "info", f"Created destination folder '{destination_folder}'.")

            all_folders: list[str] = []
            all_files: list[dict[str, str]] = []
            self._set_phase(job_id, "enumerating", "Walking the full source OneDrive tree")
            self._walk_tree_recursive(
                client,
                source_upn,
                source_root_id,
                "",
                exclude_system_folders=exclude_system_folders,
                folders=all_folders,
                files=all_files,
                job_id=job_id,
            )
            self._update_job(
                job_id,
                total_folders_found=len(all_folders),
                total_files_found=len(all_files),
            )
            if not all_folders and not all_files:
                raise RuntimeError("Nothing was found in the source OneDrive")

            files_to_dispatch = list(all_files)
            if test_mode:
                files_to_dispatch = files_to_dispatch[:test_file_limit]
                self._append_event(
                    job_id,
                    "info",
                    f"Test mode enabled; dispatching only the first {len(files_to_dispatch)} file(s).",
                )

            folders_to_create = list(all_folders)
            if test_mode:
                folders_to_create = self._folders_needed_for_files(files_to_dispatch)

            sorted_folders = sorted(
                folders_to_create,
                key=lambda path: len([part for part in path.split("/") if part]),
            )
            folder_id_cache: dict[str, str] = {"": destination_top_folder_id}
            self._set_phase(
                job_id,
                "creating_folders",
                f"Creating {len(sorted_folders)} destination folder(s)",
                progress_current=0,
                progress_total=len(sorted_folders),
                folders_created=0,
            )
            folders_created = 0
            for folder_path in sorted_folders:
                if folder_path in folder_id_cache:
                    continue
                segments = [segment for segment in folder_path.split("/") if segment]
                if not segments:
                    continue
                parent_path = "/".join(segments[:-1])
                parent_id = folder_id_cache.get(parent_path, destination_top_folder_id)
                created_folder = client.create_user_drive_folder(destination_upn, parent_id, segments[-1])
                created_id = str(created_folder.get("id") or "").strip()
                if not created_id:
                    raise RuntimeError(f"Unable to create folder '{folder_path}' in the destination OneDrive")
                folder_id_cache[folder_path] = created_id
                folders_created += 1
                self._update_job(
                    job_id,
                    folders_created=folders_created,
                    progress_current=folders_created,
                    progress_total=len(sorted_folders),
                    progress_message=f"Created {folders_created}/{len(sorted_folders)} destination folder(s)",
                )

            total_dispatch = len(files_to_dispatch)
            self._set_phase(
                job_id,
                "dispatching_copy",
                f"Dispatching {total_dispatch} file copy request(s)",
                progress_current=0,
                progress_total=total_dispatch,
                files_dispatched=0,
                files_failed=0,
            )

            files_dispatched = 0
            files_failed = 0
            for batch_start in range(0, total_dispatch, ONEDRIVE_COPY_BATCH_SIZE):
                batch_files = files_to_dispatch[batch_start : batch_start + ONEDRIVE_COPY_BATCH_SIZE]
                request_by_id: dict[str, dict[str, Any]] = {}
                pending_requests: list[dict[str, Any]] = []
                next_id = 1
                for file_item in batch_files:
                    parent_id = folder_id_cache.get(str(file_item.get("relative_path") or ""), destination_top_folder_id)
                    if not parent_id:
                        files_failed += 1
                        self._append_event(
                            job_id,
                            "error",
                            f"No destination folder was available for '{self._display_file_path(file_item)}'.",
                        )
                        continue
                    request_id = str(next_id)
                    next_id += 1
                    request_payload = {
                        "id": request_id,
                        "method": "POST",
                        "url": f"/users/{source_upn}/drive/items/{file_item['item_id']}/copy?@microsoft.graph.conflictBehavior=rename",
                        "headers": {"Content-Type": "application/json"},
                        "body": {
                            "parentReference": {
                                "driveId": destination_drive_id,
                                "id": parent_id,
                            },
                            "name": file_item["name"],
                        },
                    }
                    request_by_id[request_id] = {
                        "request": request_payload,
                        "file": file_item,
                    }
                    pending_requests.append(request_payload)

                retry_count = 0
                while pending_requests and retry_count <= ONEDRIVE_COPY_MAX_RETRIES:
                    if retry_count > 0:
                        delay_seconds = ONEDRIVE_COPY_RETRY_DELAY_BASE_SECONDS * (2 ** (retry_count - 1))
                        self._append_event(
                            job_id,
                            "warning",
                            f"Graph throttled part of a batch; retrying {len(pending_requests)} item(s) in {delay_seconds} seconds.",
                        )
                        time.sleep(delay_seconds)

                    try:
                        batch_response = client.graph_batch_request(pending_requests)
                    except AzureApiError as exc:
                        if exc.status_code == 429 and retry_count < ONEDRIVE_COPY_MAX_RETRIES:
                            retry_count += 1
                            continue
                        self._append_event(job_id, "error", f"Batch dispatch failed: {exc}")
                        for pending in pending_requests:
                            file_item = request_by_id[str(pending.get('id') or '')]["file"]
                            files_failed += 1
                            self._append_event(
                                job_id,
                                "error",
                                f"Failed to dispatch '{self._display_file_path(file_item)}'.",
                            )
                        pending_requests = []
                        break

                    responses = batch_response.get("responses")
                    if not isinstance(responses, list):
                        self._append_event(job_id, "error", "Graph batch response was missing item responses.")
                        for pending in pending_requests:
                            file_item = request_by_id[str(pending.get('id') or '')]["file"]
                            files_failed += 1
                            self._append_event(
                                job_id,
                                "error",
                                f"Failed to dispatch '{self._display_file_path(file_item)}'.",
                            )
                        pending_requests = []
                        break

                    seen_ids: set[str] = set()
                    throttled_requests: list[dict[str, Any]] = []
                    for response in responses:
                        response_id = str(response.get("id") or "")
                        if response_id not in request_by_id:
                            continue
                        seen_ids.add(response_id)
                        file_item = request_by_id[response_id]["file"]
                        status_code = int(response.get("status") or 0)
                        if status_code == 202:
                            files_dispatched += 1
                        elif status_code == 429:
                            throttled_requests.append(request_by_id[response_id]["request"])
                        else:
                            files_failed += 1
                            error_body = response.get("body")
                            error_text = json.dumps(error_body, separators=(",", ":")) if error_body else f"status {status_code}"
                            self._append_event(
                                job_id,
                                "error",
                                f"Dispatch failed for '{self._display_file_path(file_item)}' ({status_code}): {error_text}",
                            )

                    for pending in pending_requests:
                        pending_id = str(pending.get("id") or "")
                        if pending_id in seen_ids:
                            continue
                        file_item = request_by_id[pending_id]["file"]
                        files_failed += 1
                        self._append_event(
                            job_id,
                            "error",
                            f"Graph batch omitted a response for '{self._display_file_path(file_item)}'.",
                        )

                    pending_requests = throttled_requests
                    self._update_job(
                        job_id,
                        files_dispatched=files_dispatched,
                        files_failed=files_failed,
                        progress_current=files_dispatched + files_failed,
                        progress_total=total_dispatch,
                        progress_message=f"Processed {files_dispatched + files_failed}/{total_dispatch} file copy request(s)",
                    )
                    retry_count += 1

                if pending_requests:
                    for pending in pending_requests:
                        pending_id = str(pending.get("id") or "")
                        file_item = request_by_id[pending_id]["file"]
                        files_failed += 1
                        self._append_event(
                            job_id,
                            "error",
                            f"Gave up after retries on '{self._display_file_path(file_item)}'.",
                        )
                    self._update_job(
                        job_id,
                        files_dispatched=files_dispatched,
                        files_failed=files_failed,
                        progress_current=files_dispatched + files_failed,
                        progress_total=total_dispatch,
                        progress_message=f"Processed {files_dispatched + files_failed}/{total_dispatch} file copy request(s)",
                    )

            completed_message = (
                "Copy requests dispatched. SharePoint may continue processing files in the background."
            )
            self._append_event(job_id, "info", completed_message)
            self._update_job(
                job_id,
                status="completed",
                phase="completed",
                completed_at=_utcnow().isoformat(),
                progress_current=files_dispatched + files_failed,
                progress_total=total_dispatch,
                progress_message=completed_message,
                files_dispatched=files_dispatched,
                files_failed=files_failed,
                error="",
            )
        except Exception as exc:
            logger.exception("OneDrive copy job %s failed", job_id)
            self._append_event(job_id, "error", str(exc))
            self._update_job(
                job_id,
                status="failed",
                phase="failed",
                completed_at=_utcnow().isoformat(),
                progress_message="OneDrive copy failed",
                error=str(exc),
            )

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
                logger.exception("OneDrive copy background worker loop failed")
                await asyncio.sleep(3)


onedrive_copy_jobs = OneDriveCopyJobManager()
