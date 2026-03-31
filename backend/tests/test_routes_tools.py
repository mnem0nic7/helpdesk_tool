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


def test_clear_finished_onedrive_copy_jobs_returns_deleted_count(test_client, monkeypatch):
    import routes_tools

    mock_jobs = MagicMock()
    mock_jobs.clear_finished_jobs.return_value = 3
    monkeypatch.setattr(routes_tools, "onedrive_copy_jobs", mock_jobs)

    resp = test_client.post("/api/tools/onedrive-copy/jobs/clear-finished", headers={"host": "it-app.movedocs.com"})

    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 3}
    mock_jobs.clear_finished_jobs.assert_called_once_with()


def test_tools_routes_allow_any_authenticated_user(test_client):
    sid = create_session("someone@example.com", "Someone Else")
    test_client.cookies.set("session_id", sid)

    resp = test_client.get("/api/tools/onedrive-copy/login-audit?limit=5", headers={"host": "it-app.movedocs.com"})

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_tools_routes_require_authentication(test_client):
    test_client.cookies.clear()

    resp = test_client.get("/api/tools/onedrive-copy/jobs", headers={"host": "it-app.movedocs.com"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


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


def test_list_mailbox_delegates_is_available_on_primary_and_azure(test_client, monkeypatch):
    import routes_tools

    mock_providers = MagicMock()
    mock_providers.list_mailbox_delegates.return_value = {
        "mailbox": "shared@example.com",
        "display_name": "Shared Mailbox",
        "principal_name": "shared@example.com",
        "primary_address": "shared@example.com",
        "provider_enabled": True,
        "supported_permission_types": ["send_on_behalf", "send_as", "full_access"],
        "permission_counts": {
            "send_on_behalf": 1,
            "send_as": 1,
            "full_access": 0,
        },
        "note": "Mailbox delegates are listed read-only from Exchange Online for Send on behalf, Send As, and Full Access.",
        "delegate_count": 1,
        "delegates": [
            {
                "identity": "delegate@example.com",
                "display_name": "Delegate User",
                "principal_name": "delegate@example.com",
                "mail": "delegate@example.com",
                "permission_types": ["send_on_behalf", "send_as"],
            }
        ],
    }
    monkeypatch.setattr(routes_tools, "user_admin_providers", mock_providers)

    primary = test_client.get(
        "/api/tools/mailbox-delegates?mailbox=shared@example.com",
        headers={"host": "it-app.movedocs.com"},
    )
    azure = test_client.get(
        "/api/tools/mailbox-delegates?mailbox=shared@example.com",
        headers={"host": "azure.movedocs.com"},
    )

    assert primary.status_code == 200
    assert primary.json()["delegate_count"] == 1
    assert primary.json()["delegates"][0]["mail"] == "delegate@example.com"
    assert azure.status_code == 200
    assert azure.json()["permission_counts"]["send_as"] == 1
    assert mock_providers.list_mailbox_delegates.call_count == 2


def test_list_delegate_mailboxes_is_available_on_primary_and_azure(test_client, monkeypatch):
    import routes_tools

    mock_providers = MagicMock()
    mock_providers.list_delegate_mailboxes_for_user.return_value = {
        "user": "delegate@example.com",
        "display_name": "Delegate User",
        "principal_name": "delegate@example.com",
        "primary_address": "delegate@example.com",
        "provider_enabled": True,
        "supported_permission_types": ["send_on_behalf", "send_as", "full_access"],
        "permission_counts": {
            "send_on_behalf": 1,
            "send_as": 1,
            "full_access": 1,
        },
        "note": "Scanned 15 mailboxes for Send on behalf, Send As, and Full Access.",
        "mailbox_count": 1,
        "scanned_mailbox_count": 15,
        "mailboxes": [
            {
                "identity": "shared@example.com",
                "display_name": "Shared Mailbox",
                "principal_name": "shared@example.com",
                "primary_address": "shared@example.com",
                "permission_types": ["send_on_behalf", "send_as", "full_access"],
            }
        ],
    }
    monkeypatch.setattr(routes_tools, "user_admin_providers", mock_providers)

    primary = test_client.get(
        "/api/tools/delegate-mailboxes?user=delegate@example.com",
        headers={"host": "it-app.movedocs.com"},
    )
    azure = test_client.get(
        "/api/tools/delegate-mailboxes?user=delegate@example.com",
        headers={"host": "azure.movedocs.com"},
    )

    assert primary.status_code == 200
    assert primary.json()["mailbox_count"] == 1
    assert primary.json()["mailboxes"][0]["primary_address"] == "shared@example.com"
    assert azure.status_code == 200
    assert azure.json()["scanned_mailbox_count"] == 15
    assert mock_providers.list_delegate_mailboxes_for_user.call_count == 2


def test_mailbox_delegate_routes_translate_exchange_permission_errors(test_client, monkeypatch):
    import routes_tools

    mock_providers = MagicMock()
    mock_providers.list_mailbox_delegates.side_effect = UserAdminProviderError(
        "POST https://outlook.office365.com/adminapi/v2.0/example/Mailbox failed (403): "
        '{"error":{"code":"ErrorAccessDenied","message":"Access is denied."}}'
    )
    monkeypatch.setattr(routes_tools, "user_admin_providers", mock_providers)

    resp = test_client.get(
        "/api/tools/mailbox-delegates?mailbox=shared@example.com",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 502
    assert resp.json()["detail"] == (
        "Mailbox delegation lookup is not enabled for the shared Exchange app yet. "
        "The Entra app registration needs Office 365 Exchange Online application permission "
        "Exchange.ManageAsAppV2 with admin consent plus an Exchange RBAC role such as Recipient Management "
        "before this tool can read mailbox delegation."
    )


def test_create_delegate_mailbox_job_queues_a_persisted_scan(test_client, monkeypatch):
    import routes_tools

    mock_manager = MagicMock()
    mock_manager.create_job.return_value = {
        "job_id": "delegate-job-1",
        "site_scope": "primary",
        "status": "queued",
        "phase": "queued",
        "requested_by_email": "test@example.com",
        "requested_by_name": "Test User",
        "user": "delegate@example.com",
        "display_name": "",
        "principal_name": "delegate@example.com",
        "primary_address": "delegate@example.com",
        "provider_enabled": True,
        "supported_permission_types": ["send_on_behalf", "send_as", "full_access"],
        "permission_counts": {},
        "note": "",
        "mailbox_count": 0,
        "scanned_mailbox_count": 0,
        "mailboxes": [],
        "requested_at": "2026-03-31T18:00:00Z",
        "started_at": None,
        "completed_at": None,
        "progress_current": 0,
        "progress_total": 0,
        "progress_message": "Queued",
        "error": None,
        "events": [],
    }
    mock_saved = MagicMock()
    mock_cache = MagicMock()
    mock_cache.list_directory_objects.return_value = []
    monkeypatch.setattr(routes_tools, "mailbox_delegate_scan_jobs", mock_manager)
    monkeypatch.setattr(routes_tools, "onedrive_copy_jobs", mock_saved)
    monkeypatch.setattr(routes_tools, "azure_cache", mock_cache)

    resp = test_client.post(
        "/api/tools/delegate-mailboxes/jobs",
        headers={"host": "it-app.movedocs.com"},
        json={"user": "delegate@example.com"},
    )

    assert resp.status_code == 202
    assert resp.json()["job_id"] == "delegate-job-1"
    mock_manager.create_job.assert_called_once_with(
        site_scope="primary",
        user="delegate@example.com",
        requested_by_email="test@example.com",
        requested_by_name="Test User",
    )
    mock_saved.remember_user_option.assert_called_once_with(
        "delegate@example.com",
        principal_name="delegate@example.com",
        source_hint="manual",
        used_by_email="test@example.com",
    )


def test_delegate_mailbox_job_routes_list_and_fetch_current_users_jobs(test_client, monkeypatch):
    import routes_tools

    mock_manager = MagicMock()
    job_payload = {
        "job_id": "delegate-job-1",
        "site_scope": "primary",
        "status": "running",
        "phase": "scanning_exchange_permissions",
        "requested_by_email": "test@example.com",
        "requested_by_name": "Test User",
        "user": "delegate@example.com",
        "display_name": "Delegate User",
        "principal_name": "delegate@example.com",
        "primary_address": "delegate@example.com",
        "provider_enabled": True,
        "supported_permission_types": ["send_on_behalf", "send_as", "full_access"],
        "permission_counts": {},
        "note": "",
        "mailbox_count": 0,
        "scanned_mailbox_count": 15,
        "mailboxes": [],
        "requested_at": "2026-03-31T18:00:00Z",
        "started_at": "2026-03-31T18:00:05Z",
        "completed_at": None,
        "progress_current": 3,
        "progress_total": 4,
        "progress_message": "Checking Exchange permissions for Send As and Full Access",
        "error": None,
        "events": [
            {
                "event_id": 1,
                "level": "info",
                "message": "Queued delegate mailbox scan for delegate@example.com.",
                "created_at": "2026-03-31T18:00:00Z",
            }
        ],
    }
    mock_manager.list_jobs_for_user.return_value = [job_payload]
    mock_manager.get_job.return_value = job_payload
    mock_manager.job_belongs_to.return_value = True
    monkeypatch.setattr(routes_tools, "mailbox_delegate_scan_jobs", mock_manager)

    list_resp = test_client.get(
        "/api/tools/delegate-mailboxes/jobs?limit=5",
        headers={"host": "it-app.movedocs.com"},
    )
    detail_resp = test_client.get(
        "/api/tools/delegate-mailboxes/jobs/delegate-job-1",
        headers={"host": "it-app.movedocs.com"},
    )

    assert list_resp.status_code == 200
    assert list_resp.json()[0]["job_id"] == "delegate-job-1"
    assert detail_resp.status_code == 200
    assert detail_resp.json()["phase"] == "scanning_exchange_permissions"
    mock_manager.list_jobs_for_user.assert_called_once_with("test@example.com", limit=5)
    mock_manager.job_belongs_to.assert_called_once_with("delegate-job-1", "test@example.com", is_admin=True)


def test_clear_finished_delegate_mailbox_jobs_returns_deleted_count(test_client, monkeypatch):
    import routes_tools

    mock_manager = MagicMock()
    mock_manager.clear_finished_jobs_for_user.return_value = 2
    monkeypatch.setattr(routes_tools, "mailbox_delegate_scan_jobs", mock_manager)

    resp = test_client.post(
        "/api/tools/delegate-mailboxes/jobs/clear-finished",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 2}
    mock_manager.clear_finished_jobs_for_user.assert_called_once_with("test@example.com")


def test_delegate_mailbox_job_detail_rejects_other_users(test_client, monkeypatch):
    import routes_tools

    mock_manager = MagicMock()
    mock_manager.get_job.return_value = {
        "job_id": "delegate-job-1",
        "site_scope": "primary",
        "status": "running",
        "phase": "scanning_exchange_permissions",
        "requested_by_email": "someone@example.com",
        "requested_by_name": "Someone",
        "user": "delegate@example.com",
        "display_name": "",
        "principal_name": "delegate@example.com",
        "primary_address": "delegate@example.com",
        "provider_enabled": True,
        "supported_permission_types": ["send_on_behalf", "send_as", "full_access"],
        "permission_counts": {},
        "note": "",
        "mailbox_count": 0,
        "scanned_mailbox_count": 0,
        "mailboxes": [],
        "requested_at": "2026-03-31T18:00:00Z",
        "started_at": None,
        "completed_at": None,
        "progress_current": 0,
        "progress_total": 4,
        "progress_message": "Queued",
        "error": None,
        "events": [],
    }
    mock_manager.job_belongs_to.return_value = False
    monkeypatch.setattr(routes_tools, "mailbox_delegate_scan_jobs", mock_manager)

    resp = test_client.get(
        "/api/tools/delegate-mailboxes/jobs/delegate-job-1",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "You do not have access to this mailbox delegate scan job"


def test_cancel_delegate_mailbox_job_for_current_user(test_client, monkeypatch):
    import routes_tools

    mock_manager = MagicMock()
    mock_manager.get_job.return_value = {
        "job_id": "delegate-job-1",
        "site_scope": "primary",
        "status": "running",
        "phase": "scanning_exchange_permissions",
        "requested_by_email": "test@example.com",
        "requested_by_name": "Test User",
        "user": "delegate@example.com",
        "display_name": "Delegate User",
        "principal_name": "delegate@example.com",
        "primary_address": "delegate@example.com",
        "provider_enabled": True,
        "supported_permission_types": ["send_on_behalf", "send_as", "full_access"],
        "permission_counts": {},
        "note": "",
        "mailbox_count": 0,
        "scanned_mailbox_count": 15,
        "mailboxes": [],
        "requested_at": "2026-03-31T18:00:00Z",
        "started_at": "2026-03-31T18:00:05Z",
        "completed_at": None,
        "progress_current": 3,
        "progress_total": 4,
        "progress_message": "Checking Exchange permissions for Send As and Full Access",
        "error": None,
        "events": [],
    }
    mock_manager.job_belongs_to.return_value = True
    mock_manager.cancel_job.return_value = True
    monkeypatch.setattr(routes_tools, "mailbox_delegate_scan_jobs", mock_manager)

    resp = test_client.post(
        "/api/tools/delegate-mailboxes/jobs/delegate-job-1/cancel",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True, "message": "Mailbox delegate scan cancelled."}
    mock_manager.cancel_job.assert_called_once_with("delegate-job-1")


def test_cancel_delegate_mailbox_job_returns_finished_message(test_client, monkeypatch):
    import routes_tools

    mock_manager = MagicMock()
    mock_manager.get_job.return_value = {
        "job_id": "delegate-job-1",
        "site_scope": "primary",
        "status": "completed",
        "phase": "completed",
        "requested_by_email": "test@example.com",
        "requested_by_name": "Test User",
        "user": "delegate@example.com",
        "display_name": "Delegate User",
        "principal_name": "delegate@example.com",
        "primary_address": "delegate@example.com",
        "provider_enabled": True,
        "supported_permission_types": ["send_on_behalf", "send_as", "full_access"],
        "permission_counts": {},
        "note": "",
        "mailbox_count": 1,
        "scanned_mailbox_count": 15,
        "mailboxes": [],
        "requested_at": "2026-03-31T18:00:00Z",
        "started_at": "2026-03-31T18:00:05Z",
        "completed_at": "2026-03-31T18:05:00Z",
        "progress_current": 4,
        "progress_total": 4,
        "progress_message": "Mailbox delegate scan completed",
        "error": None,
        "events": [],
    }
    mock_manager.job_belongs_to.return_value = True
    mock_manager.cancel_job.return_value = False
    monkeypatch.setattr(routes_tools, "mailbox_delegate_scan_jobs", mock_manager)

    resp = test_client.post(
        "/api/tools/delegate-mailboxes/jobs/delegate-job-1/cancel",
        headers={"host": "it-app.movedocs.com"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"cancelled": False, "message": "Mailbox delegate scan is already finished."}


def test_emailgistics_helper_runs_for_admin_tools_users(test_client, monkeypatch):
    import routes_tools

    mock_service = MagicMock()
    mock_service.run.return_value = {
        "status": "completed",
        "user_mailbox": "user@example.com",
        "shared_mailbox": "shared@example.com",
        "resolved_user_display_name": "User Example",
        "resolved_user_principal_name": "user@example.com",
        "resolved_shared_display_name": "Shared Example",
        "resolved_shared_principal_name": "shared@example.com",
        "addin_group_name": "Emailgistics_UserAddin",
        "note": "Emailgistics Helper finished for user@example.com on shared@example.com.",
        "error": "",
        "sync_output": "Users have been successfully synced.",
        "steps": [
            {"key": "full_access", "label": "Grant Full Access", "status": "completed", "message": "ok"},
            {"key": "send_as", "label": "Grant Send As", "status": "completed", "message": "ok"},
            {"key": "addin_group", "label": "Add To Emailgistics_UserAddin", "status": "completed", "message": "ok"},
            {"key": "sync_users", "label": "Run Emailgistics Sync", "status": "completed", "message": "ok"},
        ],
    }
    monkeypatch.setattr(routes_tools, "emailgistics_helper_service", mock_service)

    resp = test_client.post(
        "/api/tools/emailgistics-helper",
        headers={"host": "it-app.movedocs.com"},
        json={"user_mailbox": "user@example.com", "shared_mailbox": "shared@example.com"},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    mock_service.run.assert_called_once_with(
        user_mailbox="user@example.com",
        shared_mailbox="shared@example.com",
    )


def test_emailgistics_sync_now_runs_for_admin_tools_users(test_client, monkeypatch):
    import routes_tools

    mock_service = MagicMock()
    mock_service.run_sync_only.return_value = {
        "status": "completed",
        "user_mailbox": "",
        "shared_mailbox": "shared@example.com",
        "resolved_user_display_name": "",
        "resolved_user_principal_name": "",
        "resolved_shared_display_name": "Shared Example",
        "resolved_shared_principal_name": "shared@example.com",
        "addin_group_name": "Emailgistics_UserAddin",
        "note": "Emailgistics sync finished for shared@example.com.",
        "error": "",
        "sync_output": "Users have been successfully synced.",
        "steps": [
            {"key": "sync_users", "label": "Run Emailgistics Sync", "status": "completed", "message": "ok"},
        ],
    }
    monkeypatch.setattr(routes_tools, "emailgistics_helper_service", mock_service)

    resp = test_client.post(
        "/api/tools/emailgistics-helper/sync-now",
        headers={"host": "it-app.movedocs.com"},
        json={"shared_mailbox": "shared@example.com"},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    mock_service.run_sync_only.assert_called_once_with(shared_mailbox="shared@example.com")


def test_emailgistics_helper_rejects_non_admin_users(test_client, monkeypatch):
    import routes_tools

    monkeypatch.setattr(routes_tools, "session_is_admin", lambda session: False)

    resp = test_client.post(
        "/api/tools/emailgistics-helper",
        headers={"host": "it-app.movedocs.com"},
        json={"user_mailbox": "user@example.com", "shared_mailbox": "shared@example.com"},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin access is required for Emailgistics tools"


def test_emailgistics_sync_now_rejects_non_admin_users(test_client, monkeypatch):
    import routes_tools

    monkeypatch.setattr(routes_tools, "session_is_admin", lambda session: False)

    resp = test_client.post(
        "/api/tools/emailgistics-helper/sync-now",
        headers={"host": "it-app.movedocs.com"},
        json={"shared_mailbox": "shared@example.com"},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin access is required for Emailgistics tools"
