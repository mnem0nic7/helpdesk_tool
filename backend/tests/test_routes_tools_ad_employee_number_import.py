"""Tests for the AD employee-number bulk import API endpoints in routes_tools.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _job_stub(job_id: str = "job1", status: str = "awaiting_confirmation") -> dict:
    return {
        "job_id": job_id,
        "requested_by": "test@example.com",
        "filename": "hr.csv",
        "status": status,
        "total_rows": 3,
        "update_count": 1,
        "no_change_count": 1,
        "not_found_count": 1,
        "skipped_count": 0,
        "applied_count": 0,
        "apply_failed_count": 0,
        "error": "",
        "created_at": "2026-04-01T00:00:00+00:00",
        "updated_at": "2026-04-01T00:00:00+00:00",
        "completed_at": None,
    }


def _row_stub(row_id: str = "row1", action: str = "update") -> dict:
    return {
        "id": row_id,
        "job_id": "job1",
        "row_index": 0,
        "source_email": "jane@example.com",
        "ad_sam": "jdoe",
        "ad_display_name": "Jane Doe",
        "current_employee_number": "OLD",
        "new_employee_number": "NEW",
        "action": action,
        "applied": False,
        "apply_error": "",
    }


# ---------------------------------------------------------------------------
# POST /ad-employee-number-import/jobs
# ---------------------------------------------------------------------------

def test_create_import_job_returns_202_and_starts_matching(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    with patch("routes_tools.run_matching_phase"):
        resp = test_client.post(
            "/api/tools/ad-employee-number-import/jobs",
            files={"file": ("hr.csv", b"emails_work_value,ENT_employeeNumber\njane@example.com,NEW\n", "text/csv")},
            headers={"host": "it-app.movedocs.com"},
        )

    assert resp.status_code == 202
    payload = resp.json()
    assert "job_id" in payload
    assert payload["status"] == "queued"
    mock_store.create_job.assert_called_once()


def test_create_import_job_rejects_non_csv_extension(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    resp = test_client.post(
        "/api/tools/ad-employee-number-import/jobs",
        files={"file": ("hr.txt", b"anything", "text/plain")},
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 400
    assert ".csv" in resp.json()["detail"]


def test_create_import_job_rejects_oversized_file(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    oversized = b"x" * (10 * 1024 * 1024 + 1)
    resp = test_client.post(
        "/api/tools/ad-employee-number-import/jobs",
        files={"file": ("hr.csv", oversized, "text/csv")},
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /ad-employee-number-import/jobs
# ---------------------------------------------------------------------------

def test_list_import_jobs_returns_recent_jobs(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.list_jobs.return_value = [_job_stub()]
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    resp = test_client.get(
        "/api/tools/ad-employee-number-import/jobs",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    assert resp.json()[0]["job_id"] == "job1"


# ---------------------------------------------------------------------------
# GET /ad-employee-number-import/jobs/{job_id}
# ---------------------------------------------------------------------------

def test_get_import_job_returns_job_and_rows(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_job.return_value = _job_stub()
    mock_store.list_rows.return_value = [_row_stub()]
    mock_store.count_rows.return_value = 1
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    resp = test_client.get(
        "/api/tools/ad-employee-number-import/jobs/job1",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["job_id"] == "job1"
    assert payload["rows"][0]["id"] == "row1"
    assert payload["rows_total"] == 1


def test_get_import_job_passes_action_filter_through(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_job.return_value = _job_stub()
    mock_store.list_rows.return_value = []
    mock_store.count_rows.return_value = 0
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    resp = test_client.get(
        "/api/tools/ad-employee-number-import/jobs/job1?action=not_found&limit=10&offset=5",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    mock_store.list_rows.assert_called_once_with("job1", action="not_found", limit=10, offset=5)
    mock_store.count_rows.assert_called_once_with("job1", action="not_found")


def test_get_import_job_returns_404_when_missing(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_job.return_value = None
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    resp = test_client.get(
        "/api/tools/ad-employee-number-import/jobs/missing",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /ad-employee-number-import/jobs/{job_id}/confirm
# ---------------------------------------------------------------------------

def test_confirm_import_job_starts_apply_phase(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_job.return_value = _job_stub(status="awaiting_confirmation")
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    with patch("routes_tools.run_apply_phase"):
        resp = test_client.post(
            "/api/tools/ad-employee-number-import/jobs/job1/confirm",
            json={"excluded_row_ids": ["row2"]},
            headers={"host": "it-app.movedocs.com"},
        )

    assert resp.status_code == 202
    assert resp.json()["status"] == "applying"


def test_confirm_import_job_returns_404_when_missing(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_job.return_value = None
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    resp = test_client.post(
        "/api/tools/ad-employee-number-import/jobs/missing/confirm",
        json={"excluded_row_ids": []},
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 404


def test_confirm_import_job_rejects_wrong_status(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_job.return_value = _job_stub(status="matching")
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    resp = test_client.post(
        "/api/tools/ad-employee-number-import/jobs/job1/confirm",
        json={"excluded_row_ids": []},
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /ad-employee-number-import/jobs/{job_id}/cancel
# ---------------------------------------------------------------------------

def test_cancel_import_job_cancels_when_awaiting_confirmation(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_job.return_value = _job_stub(status="awaiting_confirmation")
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    resp = test_client.post(
        "/api/tools/ad-employee-number-import/jobs/job1/cancel",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True
    mock_store.update_job_status.assert_called_once_with("job1", status="cancelled")


def test_cancel_import_job_no_ops_when_already_finished(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_job.return_value = _job_stub(status="completed")
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    resp = test_client.post(
        "/api/tools/ad-employee-number-import/jobs/job1/cancel",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    assert resp.json()["cancelled"] is False
    mock_store.update_job_status.assert_not_called()


# ---------------------------------------------------------------------------
# GET /ad-employee-number-import/jobs/{job_id}/csv
# ---------------------------------------------------------------------------

def test_get_import_job_csv_returns_csv_download(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_job.return_value = _job_stub()
    mock_store.render_csv.return_value = "row_index,source_email\n0,jane@example.com\n"
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    resp = test_client.get(
        "/api/tools/ad-employee-number-import/jobs/job1/csv",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "jane@example.com" in resp.text
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_get_import_job_csv_returns_404_when_missing(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_job.return_value = None
    monkeypatch.setattr(routes_tools, "ad_employee_number_import_jobs", mock_store)

    resp = test_client.get(
        "/api/tools/ad-employee-number-import/jobs/missing/csv",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Admin gate
# ---------------------------------------------------------------------------

def test_import_jobs_require_authentication(test_client):
    test_client.cookies.clear()

    resp = test_client.get(
        "/api/tools/ad-employee-number-import/jobs",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 401
