from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from azure_vm_export_jobs import AzureVMExportJobManager


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
