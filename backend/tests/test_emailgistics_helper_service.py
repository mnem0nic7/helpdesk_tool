from __future__ import annotations

from unittest.mock import MagicMock

from emailgistics_helper_service import EmailgisticsHelperService


class FakeExchangeClient:
    def __init__(self, call_log: list[str]) -> None:
        self.call_log = call_log

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


def test_emailgistics_helper_runs_access_and_group_steps(monkeypatch):
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
        "_add_user_to_group",
        lambda *, user, group: call_log.append("add_to_group") or {
            "status": "already_present",
            "message": "user@example.com is already in Emailgistics_UserAddin.",
        },
    )

    result = service.run(user_mailbox="user@example.com", shared_mailbox="shared@example.com")

    assert result["status"] == "completed"
    assert [step["status"] for step in result["steps"]] == [
        "completed",
        "completed",
        "already_present",
    ]
    assert call_log == [
        "resolve_user",
        "resolve_shared_mailbox",
        "resolve_addin_group",
        "grant_full_access",
        "grant_send_as",
        "add_to_group",
    ]
