from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import emailgistics_helper_service as service_module
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


def test_emailgistics_sync_now_uses_dedicated_timeout_floor(monkeypatch):
    service = EmailgisticsHelperService(client=MagicMock(), exchange_client=FakeExchangeClient([]), sync_timeout_seconds=600)
    prepared = SimpleNamespace(
        exchange_client=SimpleNamespace(pwsh_path="/usr/bin/pwsh", timeout_seconds=240),
        script_dir=Path("/tmp"),
        script_path=Path("/tmp/syncUsers.ps1"),
        env={"EMAILGISTICS_NONINTERACTIVE": "1"},
    )

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout=None):
            assert timeout == 600
            return ("Users have been successfully synced.", "")

    monkeypatch.setattr(service, "_prepare_sync_users_execution", lambda shared_mailbox=None: prepared)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    result = service._run_sync_users_script(shared_mailbox="")

    assert result["status"] == "completed"
    assert result["message"] == "Ran Emailgistics sync for all configured mailboxes."


def test_prepare_sync_users_execution_uses_emailgistics_client_secret_settings(monkeypatch, tmp_path):
    script_dir = tmp_path / "syncUsers"
    script_dir.mkdir()
    (script_dir / "syncUsers.ps1").write_text("# test script\n", encoding="utf-8")

    service = EmailgisticsHelperService(
        client=MagicMock(),
        exchange_client=FakeExchangeClient([]),
        sync_script_dir=script_dir,
    )

    monkeypatch.setattr(service_module, "EMAILGISTICS_AUTH_MODE", "client_secret")
    monkeypatch.setattr(service_module, "EMAILGISTICS_TOKEN_VALID_URL", "https://emailgistics.example/token-valid")
    monkeypatch.setattr(service_module, "EMAILGISTICS_USER_SYNC_URL", "https://emailgistics.example/user-sync")
    monkeypatch.setattr(service_module, "EMAILGISTICS_AUTH_TOKEN", "emailgistics-token")
    monkeypatch.setattr(service_module, "EMAILGISTICS_TENANT_ID", "tenant-123")
    monkeypatch.setattr(service_module, "EMAILGISTICS_APP_ID", "app-123")
    monkeypatch.setattr(service_module, "EMAILGISTICS_CLIENT_SECRET", "secret-123")
    monkeypatch.setattr(service_module, "EMAILGISTICS_ORGANIZATION_DOMAIN", "oasisfinanciallytn.onmicrosoft.com")
    monkeypatch.setattr(service_module, "EMAILGISTICS_CERTIFICATE_PATH", "")
    monkeypatch.setattr(service_module, "EMAILGISTICS_CERTIFICATE_PASSWORD", "")
    monkeypatch.setattr(service_module, "EMAILGISTICS_CONFIGURED_MAILBOXES", ["shared@example.com"])
    monkeypatch.setattr(service_module, "EMAILGISTICS_SYNC_SECURITY_GROUPS", True)

    prepared = service._prepare_sync_users_execution("shared@example.com")

    assert prepared.script_path == script_dir / "syncUsers.ps1"
    assert prepared.env["EMAILGISTICS_AUTH_MODE"] == "client_secret"
    assert prepared.env["EMAILGISTICS_TENANT_ID"] == "tenant-123"
    assert prepared.env["EMAILGISTICS_APP_ID"] == "app-123"
    assert prepared.env["EMAILGISTICS_CLIENT_SECRET"] == "secret-123"
    assert prepared.env["EMAILGISTICS_ORGANIZATION_DOMAIN"] == "oasisfinanciallytn.onmicrosoft.com"
    assert prepared.env["EMAILGISTICS_CONFIGURED_MAILBOXES"] == "shared@example.com"
    assert prepared.env["EMAILGISTICS_TARGET_MAILBOX"] == "shared@example.com"
    assert "EMAILGISTICS_CERTIFICATE_PATH" not in prepared.env
    assert "EMAILGISTICS_CERTIFICATE_PASSWORD" not in prepared.env


def test_prepare_sync_users_execution_uses_certificate_settings(monkeypatch, tmp_path):
    script_dir = tmp_path / "syncUsers"
    script_dir.mkdir()
    (script_dir / "syncUsers.ps1").write_text("# test script\n", encoding="utf-8")
    certificate_path = tmp_path / "emailgistics-auth.pfx"
    certificate_path.write_bytes(b"fake-pfx")

    service = EmailgisticsHelperService(
        client=MagicMock(),
        exchange_client=FakeExchangeClient([]),
        sync_script_dir=script_dir,
    )

    monkeypatch.setattr(service_module, "EMAILGISTICS_AUTH_MODE", "certificate")
    monkeypatch.setattr(service_module, "EMAILGISTICS_TOKEN_VALID_URL", "https://emailgistics.example/token-valid")
    monkeypatch.setattr(service_module, "EMAILGISTICS_USER_SYNC_URL", "https://emailgistics.example/user-sync")
    monkeypatch.setattr(service_module, "EMAILGISTICS_AUTH_TOKEN", "emailgistics-token")
    monkeypatch.setattr(service_module, "EMAILGISTICS_TENANT_ID", "tenant-123")
    monkeypatch.setattr(service_module, "EMAILGISTICS_APP_ID", "app-123")
    monkeypatch.setattr(service_module, "EMAILGISTICS_CLIENT_SECRET", "")
    monkeypatch.setattr(service_module, "EMAILGISTICS_ORGANIZATION_DOMAIN", "oasisfinanciallytn.onmicrosoft.com")
    monkeypatch.setattr(service_module, "EMAILGISTICS_CERTIFICATE_PATH", str(certificate_path))
    monkeypatch.setattr(service_module, "EMAILGISTICS_CERTIFICATE_PASSWORD", "pfx-password")
    monkeypatch.setattr(service_module, "EMAILGISTICS_CONFIGURED_MAILBOXES", ["shared@example.com"])
    monkeypatch.setattr(service_module, "EMAILGISTICS_SYNC_SECURITY_GROUPS", False)

    prepared = service._prepare_sync_users_execution("")

    assert prepared.env["EMAILGISTICS_AUTH_MODE"] == "certificate"
    assert prepared.env["EMAILGISTICS_TENANT_ID"] == "tenant-123"
    assert prepared.env["EMAILGISTICS_APP_ID"] == "app-123"
    assert prepared.env["EMAILGISTICS_ORGANIZATION_DOMAIN"] == "oasisfinanciallytn.onmicrosoft.com"
    assert prepared.env["EMAILGISTICS_CERTIFICATE_PATH"] == str(certificate_path)
    assert prepared.env["EMAILGISTICS_CERTIFICATE_PASSWORD"] == "pfx-password"
    assert prepared.env["EMAILGISTICS_CONFIGURED_MAILBOXES"] == "shared@example.com"
    assert "EMAILGISTICS_CLIENT_SECRET" not in prepared.env
    assert "EMAILGISTICS_TARGET_MAILBOX" not in prepared.env


def test_prepare_sync_users_execution_requires_readable_certificate_file(monkeypatch, tmp_path):
    script_dir = tmp_path / "syncUsers"
    script_dir.mkdir()
    (script_dir / "syncUsers.ps1").write_text("# test script\n", encoding="utf-8")

    service = EmailgisticsHelperService(
        client=MagicMock(),
        exchange_client=FakeExchangeClient([]),
        sync_script_dir=script_dir,
    )

    monkeypatch.setattr(service_module, "EMAILGISTICS_AUTH_MODE", "certificate")
    monkeypatch.setattr(service_module, "EMAILGISTICS_TOKEN_VALID_URL", "https://emailgistics.example/token-valid")
    monkeypatch.setattr(service_module, "EMAILGISTICS_USER_SYNC_URL", "https://emailgistics.example/user-sync")
    monkeypatch.setattr(service_module, "EMAILGISTICS_AUTH_TOKEN", "emailgistics-token")
    monkeypatch.setattr(service_module, "EMAILGISTICS_TENANT_ID", "tenant-123")
    monkeypatch.setattr(service_module, "EMAILGISTICS_APP_ID", "app-123")
    monkeypatch.setattr(service_module, "EMAILGISTICS_CLIENT_SECRET", "")
    monkeypatch.setattr(service_module, "EMAILGISTICS_ORGANIZATION_DOMAIN", "oasisfinanciallytn.onmicrosoft.com")
    monkeypatch.setattr(service_module, "EMAILGISTICS_CERTIFICATE_PATH", str(tmp_path / "missing-auth.pfx"))
    monkeypatch.setattr(service_module, "EMAILGISTICS_CERTIFICATE_PASSWORD", "pfx-password")
    monkeypatch.setattr(service_module, "EMAILGISTICS_CONFIGURED_MAILBOXES", ["shared@example.com"])

    with pytest.raises(EmailgisticsHelperError, match="certificate file was not found or is unreadable"):
        service._prepare_sync_users_execution("")
