from __future__ import annotations

from unittest.mock import MagicMock

from auth import create_session
from user_admin_providers import UserAdminProviderError


def test_tools_routes_are_not_available_on_oasis(test_client):
    resp = test_client.get("/api/tools/onedrive-copy/jobs", headers={"host": "oasisdev.movedocs.com"})
    assert resp.status_code == 404


def test_search_onedrive_copy_users_returns_directory_matches(test_client, monkeypatch):
    import routes_tools

    mock_cache = MagicMock()
    mock_cache.list_directory_objects.return_value = [
        {
            "id": "user-1",
            "display_name": "Ada Lovelace",
            "principal_name": "ada@example.com",
            "mail": "ada@example.com",
            "enabled": False,
        }
    ]
    mock_jobs = MagicMock()
    mock_jobs.list_saved_user_options.return_value = [
        {
            "id": "saved:ada@example.com",
            "display_name": "Ada Saved",
            "principal_name": "ada@example.com",
            "mail": "",
            "enabled": None,
            "source": "saved",
        },
        {
            "id": "saved:grace@example.com",
            "display_name": "Grace Hopper",
            "principal_name": "grace@example.com",
            "mail": "",
            "enabled": None,
            "source": "saved",
        },
    ]
    monkeypatch.setattr(routes_tools, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_tools, "onedrive_copy_jobs", mock_jobs)

    resp = test_client.get(
        "/api/tools/onedrive-copy/users?search=ada&limit=10",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload[0]["display_name"] == "Ada Lovelace"
    assert payload[0]["principal_name"] == "ada@example.com"
    assert payload[0]["source"] == "entra"
    assert payload[1]["display_name"] == "Grace Hopper"
    assert payload[1]["source"] == "saved"
    mock_cache.list_directory_objects.assert_called_once_with("users", search="ada")
    mock_jobs.list_saved_user_options.assert_called_once_with(search="ada", limit=10)


def test_search_onedrive_copy_users_returns_recent_saved_matches_for_empty_search(test_client, monkeypatch):
    import routes_tools

    mock_cache = MagicMock()
    mock_jobs = MagicMock()
    mock_jobs.list_saved_user_options.return_value = [
        {
            "id": "saved:former@example.com",
            "display_name": "Former User",
            "principal_name": "former@example.com",
            "mail": "",
            "enabled": None,
            "source": "saved",
        }
    ]
    monkeypatch.setattr(routes_tools, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_tools, "onedrive_copy_jobs", mock_jobs)

    resp = test_client.get(
        "/api/tools/onedrive-copy/users?search=&limit=10",
        headers={"host": "azure.movedocs.com"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload == [
        {
            "id": "saved:former@example.com",
            "display_name": "Former User",
            "principal_name": "former@example.com",
            "mail": "",
            "enabled": None,
            "source": "saved",
        }
    ]
    mock_cache.list_directory_objects.assert_not_called()
    mock_jobs.list_saved_user_options.assert_called_once_with(search="", limit=10)


def test_create_onedrive_copy_job_is_available_on_primary_and_azure(test_client, monkeypatch):
    import routes_tools

    mock_jobs = MagicMock()
    mock_jobs.list_saved_user_options.return_value = []
    mock_jobs.create_job.side_effect = [
        {
            "job_id": "job-primary",
            "site_scope": "primary",
            "status": "queued",
            "phase": "queued",
            "requested_by_email": "test@example.com",
            "requested_by_name": "Test User",
            "source_upn": "source@example.com",
            "destination_upn": "dest@example.com",
            "destination_folder": "CopiedFiles",
            "test_mode": False,
            "test_file_limit": 25,
            "exclude_system_folders": True,
            "requested_at": "2026-03-26T18:00:00Z",
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
        },
        {
            "job_id": "job-azure",
            "site_scope": "azure",
            "status": "queued",
            "phase": "queued",
            "requested_by_email": "test@example.com",
            "requested_by_name": "Test User",
            "source_upn": "source@example.com",
            "destination_upn": "dest@example.com",
            "destination_folder": "CopiedFiles",
            "test_mode": True,
            "test_file_limit": 5,
            "exclude_system_folders": False,
            "requested_at": "2026-03-26T18:01:00Z",
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
        },
    ]
    mock_cache = MagicMock()
    mock_cache.list_directory_objects.side_effect = [
        [
            {
                "id": "source-user",
                "display_name": "Source User",
                "principal_name": "source@example.com",
                "mail": "source@example.com",
                "enabled": True,
            }
        ],
        [
            {
                "id": "dest-user",
                "display_name": "Dest User",
                "principal_name": "dest@example.com",
                "mail": "dest@example.com",
                "enabled": True,
            }
        ],
        [
            {
                "id": "source-user",
                "display_name": "Source User",
                "principal_name": "source@example.com",
                "mail": "source@example.com",
                "enabled": True,
            }
        ],
        [
            {
                "id": "dest-user",
                "display_name": "Dest User",
                "principal_name": "dest@example.com",
                "mail": "dest@example.com",
                "enabled": True,
            }
        ],
    ]
    monkeypatch.setattr(routes_tools, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_tools, "onedrive_copy_jobs", mock_jobs)

    primary = test_client.post(
        "/api/tools/onedrive-copy/jobs",
        headers={"host": "it-app.movedocs.com"},
        json={
            "source_upn": "source@example.com",
            "destination_upn": "dest@example.com",
            "destination_folder": "CopiedFiles",
            "test_mode": False,
            "test_file_limit": 25,
            "exclude_system_folders": True,
        },
    )
    azure = test_client.post(
        "/api/tools/onedrive-copy/jobs",
        headers={"host": "azure.movedocs.com"},
        json={
            "source_upn": "source@example.com",
            "destination_upn": "dest@example.com",
            "destination_folder": "CopiedFiles",
            "test_mode": True,
            "test_file_limit": 5,
            "exclude_system_folders": False,
        },
    )

    assert primary.status_code == 202
    assert primary.json()["site_scope"] == "primary"
    assert azure.status_code == 202
    assert azure.json()["site_scope"] == "azure"
    assert mock_jobs.remember_user_option.call_count == 4


def test_create_onedrive_copy_job_returns_validation_errors(test_client, monkeypatch):
    import routes_tools

    mock_jobs = MagicMock()
    mock_jobs.list_saved_user_options.return_value = []
    mock_jobs.create_job.side_effect = ValueError("Source and destination UPNs must be different")
    mock_cache = MagicMock()
    mock_cache.list_directory_objects.return_value = []
    monkeypatch.setattr(routes_tools, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_tools, "onedrive_copy_jobs", mock_jobs)

    resp = test_client.post(
        "/api/tools/onedrive-copy/jobs",
        headers={"host": "it-app.movedocs.com"},
        json={
            "source_upn": "same@example.com",
            "destination_upn": "same@example.com",
            "destination_folder": "CopiedFiles",
            "test_mode": False,
            "test_file_limit": 25,
            "exclude_system_folders": True,
        },
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Source and destination UPNs must be different"


def test_list_and_get_onedrive_copy_jobs_are_visible_to_any_authenticated_user(test_client, monkeypatch):
    import routes_tools

    mock_jobs = MagicMock()
    mock_jobs.list_jobs.return_value = [
        {
            "job_id": "job-1",
            "site_scope": "primary",
            "status": "running",
            "phase": "enumerating",
            "requested_by_email": "alice@example.com",
            "requested_by_name": "Alice",
            "source_upn": "source@example.com",
            "destination_upn": "dest@example.com",
            "destination_folder": "CopiedFiles",
            "test_mode": False,
            "test_file_limit": 25,
            "exclude_system_folders": True,
            "requested_at": "2026-03-26T18:00:00Z",
            "started_at": "2026-03-26T18:00:10Z",
            "completed_at": None,
            "progress_current": 5,
            "progress_total": 10,
            "progress_message": "Walking the full source OneDrive tree",
            "total_folders_found": 12,
            "total_files_found": 40,
            "folders_created": 0,
            "files_dispatched": 0,
            "files_failed": 0,
            "error": None,
            "events": [],
        }
    ]
    mock_jobs.get_job.return_value = {
        **mock_jobs.list_jobs.return_value[0],
        "events": [
            {
                "event_id": 1,
                "level": "info",
                "message": "Queued copy from source@example.com to dest@example.com into 'CopiedFiles'.",
                "created_at": "2026-03-26T18:00:00Z",
            }
        ],
    }
    monkeypatch.setattr(routes_tools, "onedrive_copy_jobs", mock_jobs)

    list_resp = test_client.get("/api/tools/onedrive-copy/jobs", headers={"host": "azure.movedocs.com"})
    detail_resp = test_client.get("/api/tools/onedrive-copy/jobs/job-1", headers={"host": "it-app.movedocs.com"})

    assert list_resp.status_code == 200
    assert list_resp.json()[0]["requested_by_email"] == "alice@example.com"
    assert detail_resp.status_code == 200
    assert detail_resp.json()["events"][0]["level"] == "info"


def test_tools_routes_require_explicit_tools_access(test_client):
    sid = create_session("someone@example.com", "Someone Else")
    test_client.cookies.set("session_id", sid)

    resp = test_client.get("/api/tools/onedrive-copy/jobs", headers={"host": "it-app.movedocs.com"})

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Tools access is restricted"


def test_login_audit_route_returns_recent_logins_for_allowed_users(test_client):
    resp = test_client.get("/api/tools/onedrive-copy/login-audit?limit=5", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload
    assert payload[0]["email"]
    assert payload[0]["created_at"]


def test_list_mailbox_rules_is_available_on_primary_and_azure(test_client, monkeypatch):
    import routes_tools

    mock_providers = MagicMock()
    mock_providers.list_mailbox_rules.return_value = {
        "mailbox": "ada@example.com",
        "display_name": "Ada Lovelace",
        "principal_name": "ada@example.com",
        "primary_address": "ada@example.com",
        "provider_enabled": True,
        "note": "Rules are listed read-only from the mailbox Inbox.",
        "rule_count": 1,
        "rules": [
            {
                "id": "rule-1",
                "display_name": "Move GitHub alerts",
                "sequence": 1,
                "is_enabled": True,
                "has_error": False,
                "stop_processing_rules": True,
                "conditions_summary": ["From addresses: alerts@github.com"],
                "exceptions_summary": [],
                "actions_summary": ["Move to folder: GitHub", "Stop processing more rules"],
            }
        ],
    }
    monkeypatch.setattr(routes_tools, "user_admin_providers", mock_providers)

    primary = test_client.get(
        "/api/tools/mailbox-rules?mailbox=ada@example.com",
        headers={"host": "it-app.movedocs.com"},
    )
    azure = test_client.get(
        "/api/tools/mailbox-rules?mailbox=ada@example.com",
        headers={"host": "azure.movedocs.com"},
    )

    assert primary.status_code == 200
    assert primary.json()["rule_count"] == 1
    assert primary.json()["rules"][0]["display_name"] == "Move GitHub alerts"
    assert azure.status_code == 200
    assert azure.json()["principal_name"] == "ada@example.com"
    assert mock_providers.list_mailbox_rules.call_count == 2


def test_list_mailbox_rules_returns_provider_errors(test_client, monkeypatch):
    import routes_tools

    mock_providers = MagicMock()
    mock_providers.list_mailbox_rules.side_effect = UserAdminProviderError("Graph denied access to message rules")
    monkeypatch.setattr(routes_tools, "user_admin_providers", mock_providers)

    resp = test_client.get(
        "/api/tools/mailbox-rules?mailbox=ada@example.com",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 502
    assert resp.json()["detail"] == "Graph denied access to message rules"


def test_list_mailbox_rules_translates_graph_message_rule_permission_errors(test_client, monkeypatch):
    import routes_tools

    mock_providers = MagicMock()
    mock_providers.list_mailbox_rules.side_effect = UserAdminProviderError(
        "GET https://graph.microsoft.com/v1.0/users/example/mailFolders/inbox/messageRules failed (403): "
        '{"error":{"code":"ErrorAccessDenied","message":"Access is denied. Check credentials and try again."}}'
    )
    monkeypatch.setattr(routes_tools, "user_admin_providers", mock_providers)

    resp = test_client.get(
        "/api/tools/mailbox-rules?mailbox=ada@example.com",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 502
    assert resp.json()["detail"] == (
        "Mailbox rule lookup is not enabled for the shared Graph app yet. "
        "The Entra app registration needs Microsoft Graph application permission "
        "MailboxSettings.Read with admin consent before this tool can list Inbox rules."
    )
