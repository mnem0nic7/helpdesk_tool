"""Tests for the offboarding-runs API endpoints in routes_tools.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_stub(run_id: str = "run1", status: str = "completed") -> dict:
    return {
        "run_id": run_id,
        "entra_user_id": "user-1",
        "ad_sam": "jdoe",
        "display_name": "Jane Doe",
        "actor_email": "test@example.com",
        "lanes_requested": ["entra_disable", "ad_disable"],
        "status": status,
        "has_errors": False,
        "created_at": "2026-04-01T00:00:00+00:00",
        "started_at": "2026-04-01T00:00:01+00:00",
        "finished_at": "2026-04-01T00:00:05+00:00",
        "steps": [],
    }


# ---------------------------------------------------------------------------
# POST /offboarding-runs → 202
# ---------------------------------------------------------------------------

def test_create_offboarding_run_returns_202_with_run_id(test_client, monkeypatch):
    import routes_tools
    import offboarding_runs as or_module

    mock_store = MagicMock()
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)
    monkeypatch.setattr(or_module, "offboarding_runs", mock_store)

    with patch("routes_tools.run_offboarding"):
        resp = test_client.post(
            "/api/tools/offboarding-runs",
            json={
                "entra_user_id": "user-1",
                "ad_sam": "jdoe",
                "display_name": "Jane Doe",
                "lanes": ["entra_disable", "ad_disable"],
            },
            headers={"host": "it-app.movedocs.com"},
        )

    assert resp.status_code == 202
    payload = resp.json()
    assert "run_id" in payload
    assert payload["status"] == "queued"
    mock_store.create_run.assert_called_once()


def test_create_offboarding_run_rejects_unknown_lane(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.post(
        "/api/tools/offboarding-runs",
        json={
            "entra_user_id": "user-1",
            "lanes": ["entra_disable", "not_a_real_lane"],
        },
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 400
    assert "not_a_real_lane" in resp.json()["detail"]


def test_create_offboarding_run_rejects_entra_lane_without_entra_user_id(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.post(
        "/api/tools/offboarding-runs",
        json={"lanes": ["entra_disable"]},
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 400
    assert "entra_user_id" in resp.json()["detail"]


def test_create_offboarding_run_rejects_ad_lane_without_ad_sam(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.post(
        "/api/tools/offboarding-runs",
        json={"entra_user_id": "user-1", "lanes": ["ad_disable"]},
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 400
    assert "ad_sam" in resp.json()["detail"]


def test_create_offboarding_run_rejects_empty_lanes(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.post(
        "/api/tools/offboarding-runs",
        json={"entra_user_id": "user-1", "lanes": []},
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /offboarding-runs
# ---------------------------------------------------------------------------

def test_list_offboarding_runs_returns_recent_runs(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.list_runs.return_value = [_run_stub()]
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.get(
        "/api/tools/offboarding-runs",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    assert resp.json()[0]["run_id"] == "run1"
    mock_store.list_runs.assert_called_once_with(limit=20)


# ---------------------------------------------------------------------------
# GET /offboarding-runs/{run_id}
# ---------------------------------------------------------------------------

def test_get_offboarding_run_returns_run_with_steps(test_client, monkeypatch):
    import routes_tools

    run = _run_stub("abc123")
    run["steps"] = [
        {
            "step_id": "s1",
            "run_id": "abc123",
            "lane": "entra_disable",
            "sequence": 0,
            "status": "ok",
            "message": "Disabled sign-in",
            "detail": None,
            "started_at": "2026-04-01T00:00:01+00:00",
            "finished_at": "2026-04-01T00:00:02+00:00",
        }
    ]
    mock_store = MagicMock()
    mock_store.get_run.return_value = run
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.get(
        "/api/tools/offboarding-runs/abc123",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["run_id"] == "abc123"
    assert payload["steps"][0]["lane"] == "entra_disable"


def test_get_offboarding_run_returns_404_when_not_found(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_run.return_value = None
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.get(
        "/api/tools/offboarding-runs/doesnotexist",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /offboarding-runs/{run_id}/csv
# ---------------------------------------------------------------------------

def test_get_offboarding_run_csv_returns_csv_download(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_run.return_value = _run_stub("run1")
    mock_store.render_csv.return_value = "run_id,display_name,lane,status,started_at,finished_at,message,detail\nrun1,Jane Doe,entra_disable,ok,,,,\n"
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.get(
        "/api/tools/offboarding-runs/run1/csv",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "run1" in resp.text
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_get_offboarding_run_csv_returns_404_when_run_missing(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_run.return_value = None
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.get(
        "/api/tools/offboarding-runs/missing/csv",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /offboarding-runs/{run_id}/retry-lane
# ---------------------------------------------------------------------------

def test_retry_offboarding_lane_requeues_background_task(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_run.return_value = _run_stub("run1")
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    with patch("routes_tools.run_offboarding"):
        resp = test_client.post(
            "/api/tools/offboarding-runs/run1/retry-lane",
            json={"lane": "entra_disable"},
            headers={"host": "it-app.movedocs.com"},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["run_id"] == "run1"
    assert payload["lane"] == "entra_disable"
    assert payload["status"] == "requeued"


def test_retry_offboarding_lane_returns_404_for_missing_run(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_run.return_value = None
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.post(
        "/api/tools/offboarding-runs/missing/retry-lane",
        json={"lane": "entra_disable"},
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 404


def test_retry_offboarding_lane_returns_400_for_unknown_lane(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.get_run.return_value = _run_stub("run1")
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.post(
        "/api/tools/offboarding-runs/run1/retry-lane",
        json={"lane": "not_a_lane"},
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /offboarding-runs/launch-exit-workflow
# ---------------------------------------------------------------------------

def test_launch_exit_workflow_returns_workflow_id_and_deep_link(test_client, monkeypatch):
    import routes_tools
    import user_exit_workflows as uew_module

    mock_uew = MagicMock()
    mock_uew.create_workflow.return_value = {
        "workflow_id": "wf-1",
        "user_id": "user-1",
        "status": "running",
        "steps": [],
        "manual_tasks": [],
    }
    monkeypatch.setattr(routes_tools, "user_exit_workflows", mock_uew)
    monkeypatch.setattr(uew_module, "user_exit_workflows", mock_uew)

    resp = test_client.post(
        "/api/tools/offboarding-runs/launch-exit-workflow",
        json={"entra_user_id": "user-1", "display_name": "Jane Doe"},
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["workflow_id"] == "wf-1"
    assert payload["deep_link"] == "/users?workflow=wf-1"


# ---------------------------------------------------------------------------
# Admin gate
# ---------------------------------------------------------------------------

def test_offboarding_runs_require_authentication(test_client):
    test_client.cookies.clear()

    resp = test_client.get(
        "/api/tools/offboarding-runs",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 401


def test_offboarding_runs_available_on_azure_host(test_client, monkeypatch):
    import routes_tools

    mock_store = MagicMock()
    mock_store.list_runs.return_value = []
    monkeypatch.setattr(routes_tools, "offboarding_runs", mock_store)

    resp = test_client.get(
        "/api/tools/offboarding-runs",
        headers={"host": "azure.movedocs.com"},
    )

    assert resp.status_code == 200
