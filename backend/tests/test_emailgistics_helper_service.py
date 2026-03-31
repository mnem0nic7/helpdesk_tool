from __future__ import annotations

from unittest.mock import MagicMock

from emailgistics_helper_service import EmailgisticsHelperError, EmailgisticsHelperService


class FakeExchangeClient:
    def __init__(self, call_log: list[str]) -> None:
        self.call_log = call_log
        self.timeout_seconds = 240
        self.pwsh_path = "/usr/bin/pwsh"

    def organization(self) -> str:
        return "tenant.onmicrosoft.com"

    def grant_full_access_permission(self, mailbox_identifier: str, user_identifier: str, *, cancel_requested=None):
        assert cancel_requested is None
        self.call_log.append("grant_full_access")
        assert mailbox_identifier == "shared@example.com"
        assert user_identifier == "user@example.com"
        return {
            "status": "completed",
            "message": "Granted Full Access on shared@example.com to user@example.com.",
        }

    def grant_send_as_permission(self, mailbox_identifier: str, user_identifier: str, *, cancel_requested=None):
        assert cancel_requested is None
        self.call_log.append("grant_send_as")
        assert mailbox_identifier == "shared@example.com"
        assert user_identifier == "user@example.com"
        return {
            "status": "completed",
            "message": "Granted Send As on shared@example.com to user@example.com.",
        }


def test_emailgistics_helper_runs_steps_in_order(monkeypatch):
    call_log: list[str] = []
    exchange_client = FakeExchangeClient(call_log)
    service = EmailgisticsHelperService(client=MagicMock(), exchange_client=exchange_client)

    monkeypatch.setattr(
        service,
        "_resolve_user",
        lambda mailbox: call_log.append("resolve_user") or {
            "id": "user-1",
            "display_name": "User Example",
            "principal_name": "user@example.com",
            "primary_address": "user@example.com",
        },
    )
    monkeypatch.setattr(
        service,
        "_resolve_shared_mailbox",
        lambda mailbox, *, anchor_mailbox: call_log.append("resolve_shared_mailbox") or {
            "display_name": "Shared Example",
            "principal_name": "shared@example.com",
            "primary_address": "shared@example.com",
        },
    )
    monkeypatch.setattr(
        service,
        "_resolve_addin_group",
        lambda: call_log.append("resolve_addin_group") or {
            "id": "group-1",
            "display_name": "Emailgistics_UserAddin",
        },
    )
    monkeypatch.setattr(
        service,
        "_prepare_sync_users_execution",
        lambda shared_mailbox: call_log.append("prepare_sync") or MagicMock(name="sync_execution"),
    )
    monkeypatch.setattr(
        service,
        "_add_user_to_group",
        lambda *, user, group: call_log.append("add_to_group") or {
            "status": "already_present",
            "message": "user@example.com is already in Emailgistics_UserAddin.",
        },
    )
    monkeypatch.setattr(
        service,
        "_run_sync_users_script",
        lambda shared_mailbox, *, execution=None: call_log.append("run_sync") or {
            "status": "completed",
            "message": "Ran Emailgistics sync for shared@example.com.",
            "output": "Users have been successfully synced.",
        },
    )

    result = service.run(user_mailbox="user@example.com", shared_mailbox="shared@example.com")

    assert result["status"] == "completed"
    assert [step["status"] for step in result["steps"]] == [
        "completed",
        "completed",
        "already_present",
        "completed",
    ]
    assert result["sync_output"] == "Users have been successfully synced."
    assert call_log == [
        "resolve_user",
        "resolve_shared_mailbox",
        "resolve_addin_group",
        "prepare_sync",
        "grant_full_access",
        "grant_send_as",
        "add_to_group",
        "run_sync",
    ]


def test_emailgistics_helper_stops_before_permissions_when_sync_prereqs_fail(monkeypatch):
    call_log: list[str] = []
    exchange_client = FakeExchangeClient(call_log)
    service = EmailgisticsHelperService(client=MagicMock(), exchange_client=exchange_client)

    monkeypatch.setattr(
        service,
        "_resolve_user",
        lambda mailbox: {
            "id": "user-1",
            "display_name": "User Example",
            "principal_name": "user@example.com",
            "primary_address": "user@example.com",
        },
    )
    monkeypatch.setattr(
        service,
        "_resolve_shared_mailbox",
        lambda mailbox, *, anchor_mailbox: {
            "display_name": "Shared Example",
            "principal_name": "shared@example.com",
            "primary_address": "shared@example.com",
        },
    )
    monkeypatch.setattr(
        service,
        "_resolve_addin_group",
        lambda: {
            "id": "group-1",
            "display_name": "Emailgistics_UserAddin",
        },
    )
    monkeypatch.setattr(
        service,
        "_prepare_sync_users_execution",
        lambda shared_mailbox: (_ for _ in ()).throw(
            EmailgisticsHelperError("Emailgistics automation is not fully configured on the app runtime.")
        ),
    )

    result = service.run(user_mailbox="user@example.com", shared_mailbox="shared@example.com")

    assert result["status"] == "failed"
    assert result["error"] == "Emailgistics automation is not fully configured on the app runtime."
    assert result["steps"][0]["status"] == "failed"
    assert call_log == []


def test_emailgistics_sync_now_runs_only_sync_script(monkeypatch):
    call_log: list[str] = []
    exchange_client = FakeExchangeClient(call_log)
    service = EmailgisticsHelperService(client=MagicMock(), exchange_client=exchange_client)

    monkeypatch.setattr(
        service,
        "_resolve_shared_mailbox",
        lambda mailbox, *, anchor_mailbox: call_log.append("resolve_shared_mailbox") or {
            "display_name": "Shared Example",
            "principal_name": "shared@example.com",
            "primary_address": "shared@example.com",
        },
    )
    monkeypatch.setattr(
        service,
        "_prepare_sync_users_execution",
        lambda shared_mailbox: call_log.append("prepare_sync") or MagicMock(name="sync_execution"),
    )
    monkeypatch.setattr(
        service,
        "_run_sync_users_script",
        lambda shared_mailbox, *, execution=None: call_log.append("run_sync") or {
            "status": "completed",
            "message": "Ran Emailgistics sync for shared@example.com.",
            "output": "Users have been successfully synced.",
        },
    )

    result = service.run_sync_only(shared_mailbox="shared@example.com")

    assert result["status"] == "completed"
    assert result["user_mailbox"] == ""
    assert [step["status"] for step in result["steps"]] == ["completed"]
    assert result["sync_output"] == "Users have been successfully synced."
    assert call_log == [
        "resolve_shared_mailbox",
        "prepare_sync",
        "run_sync",
    ]


def test_emailgistics_sync_now_runs_all_configured_mailboxes_without_target(monkeypatch):
    call_log: list[str] = []
    exchange_client = FakeExchangeClient(call_log)
    service = EmailgisticsHelperService(client=MagicMock(), exchange_client=exchange_client)

    monkeypatch.setattr(
        service,
        "_prepare_sync_users_execution",
        lambda shared_mailbox=None: call_log.append(f"prepare_sync:{shared_mailbox}") or MagicMock(name="sync_execution"),
    )
    monkeypatch.setattr(
        service,
        "_run_sync_users_script",
        lambda shared_mailbox=None, *, execution=None: call_log.append(f"run_sync:{shared_mailbox}") or {
            "status": "completed",
            "message": "Ran Emailgistics sync for all configured mailboxes.",
            "output": "Users have been successfully synced.",
        },
    )

    result = service.run_sync_only(shared_mailbox="")

    assert result["status"] == "completed"
    assert result["shared_mailbox"] == ""
    assert result["resolved_shared_principal_name"] == ""
    assert result["note"] == "Emailgistics sync finished for all configured mailboxes."
    assert [step["status"] for step in result["steps"]] == ["completed"]
    assert call_log == [
        "prepare_sync:None",
        "run_sync:None",
    ]
