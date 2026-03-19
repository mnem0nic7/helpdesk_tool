from __future__ import annotations

from unittest.mock import MagicMock


def test_user_exit_preflight_returns_primary_payload(test_client, monkeypatch):
    import routes_user_exit

    mock_workflows = MagicMock()
    mock_workflows.build_preflight.return_value = {
        "user_id": "user-1",
        "user_display_name": "Ada Lovelace",
        "user_principal_name": "ada@example.com",
        "profile_key": "oasis",
        "profile_label": "Oasis",
        "scope_summary": "Hybrid exit workflow (Oasis)",
        "on_prem_required": True,
        "requires_on_prem_username_override": False,
        "on_prem_sam_account_name": "adal",
        "on_prem_distinguished_name": "CN=Ada Lovelace,OU=Users,DC=oasis,DC=local",
        "mailbox_expected": True,
        "direct_license_count": 1,
        "direct_licenses": [],
        "managed_devices": [],
        "manual_tasks": [],
        "steps": [],
        "warnings": [],
        "active_workflow": None,
    }
    monkeypatch.setattr(routes_user_exit, "user_exit_workflows", mock_workflows)

    resp = test_client.get("/api/user-exit/users/user-1/preflight", headers={"host": "it-app.movedocs.com"})

    assert resp.status_code == 200
    assert resp.json()["profile_key"] == "oasis"


def test_user_exit_routes_are_primary_only(test_client):
    azure = test_client.get("/api/user-exit/users/user-1/preflight", headers={"host": "azure.movedocs.com"})
    oasis = test_client.get("/api/user-exit/users/user-1/preflight", headers={"host": "oasisdev.movedocs.com"})

    assert azure.status_code == 404
    assert oasis.status_code == 404


def test_create_retry_and_complete_user_exit_workflow(test_client, monkeypatch):
    import routes_user_exit

    workflow_payload = {
        "workflow_id": "workflow-1",
        "user_id": "user-1",
        "user_display_name": "Ada Lovelace",
        "user_principal_name": "ada@example.com",
        "requested_by_email": "test@example.com",
        "requested_by_name": "Test User",
        "status": "awaiting_manual",
        "profile_key": "oasis",
        "on_prem_required": True,
        "requires_on_prem_username_override": False,
        "on_prem_sam_account_name": "adal",
        "on_prem_distinguished_name": "CN=Ada Lovelace,OU=Users,DC=oasis,DC=local",
        "created_at": "2026-03-19T00:00:00Z",
        "started_at": "2026-03-19T00:01:00Z",
        "completed_at": None,
        "error": "",
        "steps": [
            {
                "step_id": "step-1",
                "step_key": "disable_sign_in",
                "label": "Disable Entra Sign-In",
                "provider": "entra",
                "status": "completed",
                "order_index": 1,
                "profile_key": "",
                "summary": "Disabled sign-in",
                "error": "",
                "before_summary": {},
                "after_summary": {},
                "created_at": "2026-03-19T00:00:00Z",
                "started_at": None,
                "completed_at": "2026-03-19T00:02:00Z",
                "retry_count": 0,
            }
        ],
        "manual_tasks": [
            {
                "task_id": "task-1",
                "label": "RingCentral",
                "status": "pending",
                "notes": "",
                "completed_at": None,
                "completed_by_email": "",
                "completed_by_name": "",
            }
        ],
    }

    mock_workflows = MagicMock()
    mock_workflows.create_workflow.return_value = workflow_payload
    mock_workflows.get_workflow.return_value = workflow_payload
    mock_workflows.retry_step.return_value = workflow_payload
    mock_workflows.complete_manual_task.return_value = {**workflow_payload, "status": "completed", "completed_at": "2026-03-19T00:10:00Z"}
    monkeypatch.setattr(routes_user_exit, "user_exit_workflows", mock_workflows)

    create_resp = test_client.post(
        "/api/user-exit/workflows",
        headers={"host": "it-app.movedocs.com"},
        json={"user_id": "user-1", "typed_upn_confirmation": "ada@example.com"},
    )
    get_resp = test_client.get("/api/user-exit/workflows/workflow-1", headers={"host": "it-app.movedocs.com"})
    retry_resp = test_client.post(
        "/api/user-exit/workflows/workflow-1/retry-step",
        headers={"host": "it-app.movedocs.com"},
        json={"step_id": "step-1"},
    )
    complete_resp = test_client.post(
        "/api/user-exit/workflows/workflow-1/manual-tasks/task-1/complete",
        headers={"host": "it-app.movedocs.com"},
        json={"notes": "Confirmed with Facilities"},
    )

    assert create_resp.status_code == 200
    assert get_resp.status_code == 200
    assert retry_resp.status_code == 200
    assert complete_resp.status_code == 200
    assert complete_resp.json()["status"] == "completed"


def test_user_exit_agent_routes_require_shared_secret(test_client, monkeypatch):
    import routes_user_exit

    mock_workflows = MagicMock()
    mock_workflows.claim_agent_step.return_value = None
    monkeypatch.setattr(routes_user_exit, "USER_EXIT_AGENT_SHARED_SECRET", "secret-123")
    monkeypatch.setattr(routes_user_exit, "user_exit_workflows", mock_workflows)

    unauthorized = test_client.post(
        "/api/user-exit/agent/steps/claim",
        headers={"host": "it-app.movedocs.com"},
        json={"agent_id": "agent-1", "profile_keys": ["oasis"]},
    )
    authorized = test_client.post(
        "/api/user-exit/agent/steps/claim",
        headers={"host": "it-app.movedocs.com", "x-user-exit-agent-secret": "secret-123"},
        json={"agent_id": "agent-1", "profile_keys": ["oasis"]},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_user_exit_agent_completion_returns_workflow(test_client, monkeypatch):
    import routes_user_exit

    workflow_payload = {
        "workflow_id": "workflow-2",
        "user_id": "user-2",
        "user_display_name": "Grace Hopper",
        "user_principal_name": "grace@example.com",
        "requested_by_email": "test@example.com",
        "requested_by_name": "Test User",
        "status": "running",
        "profile_key": "canyon",
        "on_prem_required": True,
        "requires_on_prem_username_override": False,
        "on_prem_sam_account_name": "graceh",
        "on_prem_distinguished_name": "",
        "created_at": "2026-03-19T00:00:00Z",
        "started_at": "2026-03-19T00:01:00Z",
        "completed_at": None,
        "error": "",
        "steps": [],
        "manual_tasks": [],
    }
    mock_workflows = MagicMock()
    mock_workflows.complete_agent_step.return_value = workflow_payload
    monkeypatch.setattr(routes_user_exit, "USER_EXIT_AGENT_SHARED_SECRET", "secret-123")
    monkeypatch.setattr(routes_user_exit, "user_exit_workflows", mock_workflows)

    resp = test_client.post(
        "/api/user-exit/agent/steps/step-1/complete",
        headers={"host": "it-app.movedocs.com", "x-user-exit-agent-secret": "secret-123"},
        json={
            "agent_id": "agent-1",
            "status": "completed",
            "summary": "Mailbox converted to shared",
            "error": "",
            "before_summary": {"mailbox_type": "UserMailbox"},
            "after_summary": {"mailbox_type": "SharedMailbox"},
        },
    )

    assert resp.status_code == 200
    assert resp.json()["workflow_id"] == "workflow-2"
