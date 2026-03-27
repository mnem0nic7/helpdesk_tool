from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from azure_vm_export_jobs import AzureVMExportJobManager


def _create_export_jobs_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS export_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            requester_name TEXT NOT NULL,
            scope TEXT NOT NULL,
            lookback_days INTEGER NOT NULL,
            filters_json TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            progress_current INTEGER NOT NULL DEFAULT 0,
            progress_total INTEGER NOT NULL DEFAULT 0,
            progress_message TEXT NOT NULL DEFAULT '',
            file_name TEXT,
            file_path TEXT,
            file_size INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            notified_at TEXT,
            notification_error TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_export_jobs_status_requested_at "
        "ON export_jobs(status, requested_at)"
    )


def test_postgres_mode_backfills_legacy_jobs_and_requeues_running_jobs(tmp_path, monkeypatch):
    legacy_db_path = tmp_path / "azure_vm_export_jobs.db"
    pg_db_path = tmp_path / "azure_vm_export_jobs_postgres.db"

    legacy_manager = AzureVMExportJobManager(db_path=str(legacy_db_path))
    with legacy_manager._conn() as conn:
        conn.execute(
            """
            INSERT INTO export_jobs (
                job_id,
                status,
                recipient_email,
                requester_name,
                scope,
                lookback_days,
                filters_json,
                requested_at,
                started_at,
                progress_current,
                progress_total,
                progress_message
            )
            VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?, 2, 10, 'Working')
            """,
            (
                "job-running",
                "user@example.com",
                "Example User",
                "all",
                30,
                "{}",
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    monkeypatch.setattr("azure_vm_export_jobs.DATA_DIR", tmp_path)
    monkeypatch.setattr("azure_vm_export_jobs.postgres_enabled", lambda: True)
    monkeypatch.setattr("azure_vm_export_jobs.ensure_postgres_schema", lambda: None)
    monkeypatch.setattr(AzureVMExportJobManager, "_placeholder", lambda self: "?")

    def fake_connect_postgres(*, row_factory=sqlite3.Row):
        conn = sqlite3.connect(pg_db_path)
        if row_factory is not None:
            conn.row_factory = row_factory
        return conn

    monkeypatch.setattr("azure_vm_export_jobs.connect_postgres", fake_connect_postgres)

    manager = AzureVMExportJobManager()
    job = manager.get_job("job-running")

    assert manager._use_postgres is True
    assert job is not None
    assert job["status"] == "queued"
    assert job["progress_current"] == 0
    assert job["progress_message"] == "Re-queued after restart"
    assert job["recipient_email"] == "user@example.com"


def test_explicit_db_path_keeps_sqlite_fallback_when_postgres_is_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr("azure_vm_export_jobs.postgres_enabled", lambda: True)

    def fail_connect_postgres(*args, **kwargs):
        raise AssertionError("connect_postgres should not be used when db_path is explicit")

    monkeypatch.setattr("azure_vm_export_jobs.connect_postgres", fail_connect_postgres)

    manager = AzureVMExportJobManager(db_path=str(tmp_path / "azure_vm_export_jobs.db"))

    assert manager._use_postgres is False
    job = manager.create_job(
        recipient_email="user@example.com",
        requester_name="Example User",
        scope="filtered",
        lookback_days=30,
        filters={"search": "wvd"},
    )

    assert job["status"] == "queued"
    assert manager.get_job(job["job_id"]) is not None


def test_create_job_persists_export_request(tmp_path):
    manager = AzureVMExportJobManager(db_path=str(tmp_path / "azure_vm_export_jobs.db"))

    job = manager.create_job(
        recipient_email="user@example.com",
        requester_name="Example User",
        scope="filtered",
        lookback_days=30,
        filters={"search": "wvd", "subscription_id": "sub-1"},
    )

    assert job["status"] == "queued"
    assert job["recipient_email"] == "user@example.com"
    assert job["scope"] == "filtered"
    assert job["filters"]["search"] == "wvd"
    assert manager.get_job(job["job_id"]) is not None


def test_running_jobs_are_requeued_on_manager_startup(tmp_path):
    db_path = str(tmp_path / "azure_vm_export_jobs.db")
    manager = AzureVMExportJobManager(db_path=db_path)

    with manager._conn() as conn:
        conn.execute(
            """
            INSERT INTO export_jobs (
                job_id,
                status,
                recipient_email,
                requester_name,
                scope,
                lookback_days,
                filters_json,
                requested_at,
                started_at,
                progress_current,
                progress_total,
                progress_message
            )
            VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?, 2, 10, 'Working')
            """,
            (
                "job-running",
                "user@example.com",
                "Example User",
                "all",
                30,
                "{}",
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    restarted = AzureVMExportJobManager(db_path=db_path)
    job = restarted.get_job("job-running")

    assert job is not None
    assert job["status"] == "queued"
    assert job["progress_current"] == 0
    assert job["progress_message"] == "Re-queued after restart"


def test_cleanup_expired_files_removes_old_workbooks(tmp_path):
    db_path = str(tmp_path / "azure_vm_export_jobs.db")
    manager = AzureVMExportJobManager(db_path=db_path)
    workbook_path = tmp_path / "old_export.xlsx"
    workbook_path.write_bytes(b"excel")

    expired_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    with manager._conn() as conn:
        conn.execute(
            """
            INSERT INTO export_jobs (
                job_id,
                status,
                recipient_email,
                requester_name,
                scope,
                lookback_days,
                filters_json,
                requested_at,
                completed_at,
                file_name,
                file_path,
                file_size
            )
            VALUES (?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-expired",
                "user@example.com",
                "Example User",
                "all",
                30,
                "{}",
                expired_at,
                expired_at,
                "old_export.xlsx",
                str(workbook_path),
                workbook_path.stat().st_size,
            ),
        )
        conn.commit()

    manager._cleanup_expired_files()
    job = manager.get_job("job-expired")

    assert not os.path.exists(workbook_path)
    assert job is not None
    assert job["file_name"] is None
    assert job["file_ready"] is False


def test_send_notification_marks_job_notified(tmp_path, monkeypatch):
    manager = AzureVMExportJobManager(db_path=str(tmp_path / "azure_vm_export_jobs.db"))
    job = manager.create_job(
        recipient_email="user@example.com",
        requester_name="Example User",
        scope="all",
        lookback_days=30,
        filters={},
    )
    manager._update_job(
        job["job_id"],
        status="completed",
        completed_at=datetime.now(timezone.utc).isoformat(),
        file_name="azure_vm_costs.xlsx",
        file_path=str(tmp_path / "azure_vm_costs.xlsx"),
    )

    async def fake_send_email(to, subject, html_body, sender="it-ai@librasolutionsgroup.com", cc=None):
        assert to == ["user@example.com"]
        assert "ready" in subject.lower()
        assert "download" in html_body.lower()
        return True

    monkeypatch.setattr("azure_vm_export_jobs.send_email", fake_send_email)

    asyncio.run(manager._send_notification(manager.get_job(job["job_id"])))
    updated = manager.get_job(job["job_id"])

    assert updated is not None
    assert updated["notified_at"] is not None
    assert updated["notification_error"] is None


def test_process_job_marks_export_failed_without_workbook_on_timeout(tmp_path, monkeypatch):
    manager = AzureVMExportJobManager(db_path=str(tmp_path / "azure_vm_export_jobs.db"))
    job = manager.create_job(
        recipient_email="user@example.com",
        requester_name="Example User",
        scope="all",
        lookback_days=30,
        filters={},
    )

    monkeypatch.setattr(
        "azure_vm_export_jobs.azure_cache.build_virtual_machine_cost_export",
        lambda **kwargs: (_ for _ in ()).throw(
            TimeoutError("Azure Cost throttling prevented export completion within 45 minutes")
        ),
    )

    manager._process_job(job["job_id"])
    updated = manager.get_job(job["job_id"])

    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["file_name"] is None
    assert updated["file_ready"] is False
    assert "throttling prevented export completion" in str(updated["error"])


def test_send_failure_notification_calls_out_throttling(tmp_path, monkeypatch):
    manager = AzureVMExportJobManager(db_path=str(tmp_path / "azure_vm_export_jobs.db"))
    job = manager.create_job(
        recipient_email="user@example.com",
        requester_name="Example User",
        scope="all",
        lookback_days=30,
        filters={},
    )
    manager._update_job(
        job["job_id"],
        status="failed",
        completed_at=datetime.now(timezone.utc).isoformat(),
        error="Azure Cost throttling prevented export completion within 45 minutes after repeated 429 responses",
    )

    async def fake_send_email(to, subject, html_body, sender="it-ai@librasolutionsgroup.com", cc=None):
        assert to == ["user@example.com"]
        assert "failed" in subject.lower()
        assert "throttled" in html_body.lower()
        return True

    monkeypatch.setattr("azure_vm_export_jobs.send_email", fake_send_email)

    asyncio.run(manager._send_notification(manager.get_job(job["job_id"])))
    updated = manager.get_job(job["job_id"])

    assert updated is not None
    assert updated["notified_at"] is not None
