from datetime import datetime, timezone
from pathlib import Path

from exchange_online_client import (
    ExchangeOnlinePowerShellClient,
    ExchangeOnlinePowerShellError,
    _sanitize_powershell_error_text,
)


class StubAzureClient:
    configured = True

    def exchange_access_token(self) -> str:
        return "fake-token"


def test_get_delegate_mailboxes_for_user_uses_mailbox_identity_pipeline_for_full_access(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured_calls: list[dict[str, object]] = []

    def fake_run_script(
        script_body: str,
        *,
        extra_env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        cancel_requested=None,
    ):
        captured_calls.append(
            {
                "script_body": script_body,
                "extra_env": extra_env or {},
                "timeout_seconds": timeout_seconds,
                "cancel_requested": cancel_requested,
            }
        )
        return {"mailbox_count_scanned": 0, "mailboxes": []}

    monkeypatch.setattr(client, "_run_script", fake_run_script)
    cancel_requested = lambda: False

    result = client.get_delegate_mailboxes_for_user("delegate@example.com", cancel_requested=cancel_requested)

    assert result == {"mailbox_count_scanned": 0, "mailboxes": []}
    assert len(captured_calls) == 2
    assert captured_calls[0]["extra_env"] == {"DELEGATE_USER": "delegate@example.com"}
    assert captured_calls[0]["cancel_requested"] is cancel_requested
    assert captured_calls[1]["extra_env"] == {"DELEGATE_USER": "delegate@example.com"}
    assert captured_calls[1]["cancel_requested"] is cancel_requested
    assert int(captured_calls[1]["timeout_seconds"]) >= 600
    script_body = str(captured_calls[1]["script_body"])
    assert "$batchSize = 50" in script_body
    assert "Select-Object -Skip $offset -First $batchSize" in script_body
    assert "Get-EXOMailboxPermission -User $delegateUser -ErrorAction SilentlyContinue -ErrorVariable +batchErrors" in script_body
    assert "$fullAccessErrors += $batchErrors" in script_body
    assert "Start-Sleep -Seconds 2" in script_body
    assert "$unexpectedFullAccessErrors" in script_body
    assert "Get-EXOMailboxPermission -User $delegateUser -ResultSize Unlimited" not in script_body


def test_get_send_as_mailboxes_for_user_uses_mailbox_identity_batches(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(
        script_body: str,
        *,
        extra_env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        cancel_requested=None,
    ):
        captured["script_body"] = script_body
        captured["extra_env"] = extra_env or {}
        captured["timeout_seconds"] = timeout_seconds
        captured["cancel_requested"] = cancel_requested
        return {"mailbox_count_scanned": 0, "mailboxes": []}

    monkeypatch.setattr(client, "_run_script", fake_run_script)
    cancel_requested = lambda: False

    result = client.get_send_as_mailboxes_for_user("delegate@example.com", cancel_requested=cancel_requested)

    assert result == {"mailbox_count_scanned": 0, "mailboxes": []}
    assert captured["extra_env"] == {"DELEGATE_USER": "delegate@example.com"}
    assert int(captured["timeout_seconds"]) >= 600
    assert captured["cancel_requested"] is cancel_requested
    script_body = str(captured["script_body"])
    assert "$allMailboxes = @(Get-Mailbox -ResultSize Unlimited)" in script_body
    assert "$batchSize = 50" in script_body
    assert "Select-Object -Skip $offset -First $batchSize" in script_body
    assert "$batch |\n        Get-EXORecipientPermission -Trustee $delegateUser -ResultSize Unlimited -ErrorAction SilentlyContinue -ErrorVariable +batchErrors" in script_body
    assert "$unexpectedSendAsErrors" in script_body
    assert "Get-EXORecipientPermission -Trustee $delegateUser -ResultSize Unlimited |\n" not in script_body


class FakeProcess:
    def __init__(self, returncode: int = 0, stdout: str = "{}", stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        return self._stdout, self._stderr

    def kill(self):
        pass


def test_run_script_command_name_allow_list_includes_set_mailbox_and_remove_distribution_group_member(monkeypatch):
    client = ExchangeOnlinePowerShellClient(
        azure_client=StubAzureClient(), organization_override="contoso.onmicrosoft.com"
    )
    monkeypatch.setattr("exchange_online_client.shutil.which", lambda name: "/usr/bin/pwsh")
    captured: dict[str, str] = {}

    def fake_popen(args, **kwargs):
        captured["script"] = Path(args[-1]).read_text()
        return FakeProcess()

    monkeypatch.setattr("exchange_online_client.subprocess.Popen", fake_popen)

    client._run_script("Get-Mailbox -Identity 'x'")

    assert "'Set-Mailbox'" in captured["script"]
    assert "'Remove-DistributionGroupMember'" in captured["script"]


def test_convert_mailbox_to_shared_uses_set_mailbox_script(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        captured["script_body"] = script_body
        captured["extra_env"] = extra_env or {}
        return {"recipient_type": "SharedMailbox", "hidden_from_address_lists": True}

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    result = client.convert_mailbox_to_shared("jane@example.com")

    assert result == {
        "mailbox": "jane@example.com",
        "recipient_type": "SharedMailbox",
        "hidden_from_address_lists": True,
    }
    assert captured["extra_env"] == {"MAILBOX_IDENTITY": "jane@example.com"}
    assert "Set-Mailbox -Identity $mailboxIdentity -Type Shared" in captured["script_body"]


def test_remove_distribution_group_member_uses_remove_distributiongroupmember_script(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        captured["script_body"] = script_body
        captured["extra_env"] = extra_env or {}
        return {"removed": True}

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    result = client.remove_distribution_group_member("allstaff@example.com", "jane@example.com")

    assert result == {"group": "allstaff@example.com", "member": "jane@example.com", "removed": True}
    assert captured["extra_env"] == {
        "DL_GROUP_IDENTITY": "allstaff@example.com",
        "DL_MEMBER_IDENTITY": "jane@example.com",
    }
    assert (
        "Remove-DistributionGroupMember -Identity $groupIdentity -Member $memberIdentity"
        in captured["script_body"]
    )


def test_remove_distribution_group_member_requires_group_and_member():
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())

    try:
        client.remove_distribution_group_member("", "jane@example.com")
        assert False, "expected ExchangeOnlinePowerShellError"
    except ExchangeOnlinePowerShellError:
        pass

    try:
        client.remove_distribution_group_member("allstaff@example.com", "")
        assert False, "expected ExchangeOnlinePowerShellError"
    except ExchangeOnlinePowerShellError:
        pass

def test_run_script_command_name_allow_list_includes_quarantine_cmdlets(monkeypatch):
    client = ExchangeOnlinePowerShellClient(
        azure_client=StubAzureClient(), organization_override="contoso.onmicrosoft.com"
    )
    monkeypatch.setattr("exchange_online_client.shutil.which", lambda name: "/usr/bin/pwsh")
    captured: dict[str, str] = {}

    def fake_popen(args, **kwargs):
        captured["script"] = Path(args[-1]).read_text()
        return FakeProcess()

    monkeypatch.setattr("exchange_online_client.subprocess.Popen", fake_popen)

    client._run_script("Get-Mailbox -Identity 'x'")

    assert "'Get-QuarantineMessage'" in captured["script"]
    assert "'Release-QuarantineMessage'" in captured["script"]


def test_list_quarantine_messages_filters_by_domain_client_side(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        captured["script_body"] = script_body
        captured["extra_env"] = extra_env or {}
        return {
            "messages": [
                {
                    "identity": "msg-1",
                    "sender_address": "billing@complexlegal.com",
                    "recipient_address": "ap@example.com",
                    "subject": "Invoice",
                    "received_at": "2026-09-01T14:05:00Z",
                    "quarantine_reason": "Spam",
                }
            ]
        }

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    received_after = datetime(2026, 9, 1, 16, 0, 0, tzinfo=timezone.utc)
    result = client.list_quarantine_messages(
        ["complexlegal.com", "partner.org"], received_after=received_after
    )

    assert result == [
        {
            "identity": "msg-1",
            "sender_address": "billing@complexlegal.com",
            "recipient_address": "ap@example.com",
            "subject": "Invoice",
            "received_at": "2026-09-01T14:05:00Z",
            "quarantine_reason": "Spam",
        }
    ]
    assert captured["extra_env"] == {
        "QR_DOMAINS": "complexlegal.com,partner.org",
        "QR_START_RECEIVED": "2026-09-01T16:00:00+00:00",
    }
    assert "Get-QuarantineMessage" in captured["script_body"]
    assert "$env:QR_DOMAINS" in captured["script_body"]
    assert "-PageSize 100" in captured["script_body"]
    assert "-Page $page" in captured["script_body"]
    assert "while ($true)" in captured["script_body"]
    assert "Where-Object" in captured["script_body"]
    assert "SenderAddress" in captured["script_body"]
    assert "Split('@')" in captured["script_body"]
    assert "-SenderAddress \"*@$domain\"" not in captured["script_body"]


def test_list_quarantine_messages_scopes_query_to_start_received_date(monkeypatch):
    """Root cause of the 2026-09-01 timeout incident: an unfiltered sweep of the
    tenant's entire quarantine retention window (thousands of unrelated messages)
    on every hourly run. The query must be server-side scoped to new mail only."""
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        captured["script_body"] = script_body
        captured["extra_env"] = extra_env or {}
        return {"messages": []}

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    received_after = datetime(2026, 9, 1, 16, 0, 0, tzinfo=timezone.utc)
    client.list_quarantine_messages(["complexlegal.com"], received_after=received_after)

    assert captured["extra_env"]["QR_START_RECEIVED"] == "2026-09-01T16:00:00+00:00"
    assert "-StartReceivedDate" in captured["script_body"]
    assert "$env:QR_START_RECEIVED" in captured["script_body"]


def test_list_quarantine_messages_passes_through_timeout_seconds(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        captured["timeout_seconds"] = timeout_seconds
        return {"messages": []}

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    received_after = datetime(2026, 9, 1, 16, 0, 0, tzinfo=timezone.utc)
    client.list_quarantine_messages(
        ["complexlegal.com"], received_after=received_after, timeout_seconds=600
    )

    assert captured["timeout_seconds"] == 600


def test_list_quarantine_messages_defaults_timeout_seconds_to_none(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        captured["timeout_seconds"] = timeout_seconds
        return {"messages": []}

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    received_after = datetime(2026, 9, 1, 16, 0, 0, tzinfo=timezone.utc)
    client.list_quarantine_messages(["complexlegal.com"], received_after=received_after)

    assert captured["timeout_seconds"] is None


def test_list_quarantine_messages_returns_empty_list_for_no_domains():
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())

    received_after = datetime(2026, 9, 1, 16, 0, 0, tzinfo=timezone.utc)
    assert client.list_quarantine_messages([], received_after=received_after) == []


def test_list_quarantine_messages_coerces_single_dict_payload_to_list(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        return {"messages": {"identity": "msg-1", "sender_address": "a@complexlegal.com",
                              "recipient_address": "b@example.com", "subject": "", "received_at": "", "quarantine_reason": "Spam"}}

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    received_after = datetime(2026, 9, 1, 16, 0, 0, tzinfo=timezone.utc)
    result = client.list_quarantine_messages(["complexlegal.com"], received_after=received_after)

    assert len(result) == 1
    assert result[0]["identity"] == "msg-1"


def test_release_quarantine_message_uses_release_to_all(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        captured["script_body"] = script_body
        captured["extra_env"] = extra_env or {}
        return {"identity": "msg-1", "released": True}

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    result = client.release_quarantine_message("msg-1")

    assert result == {"identity": "msg-1", "released": True}
    assert captured["extra_env"] == {"QR_IDENTITY": "msg-1"}
    assert "Release-QuarantineMessage -Identity $identity -ReleaseToAll -Confirm:$false" in captured["script_body"]


def test_release_quarantine_message_requires_identity():
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())

    try:
        client.release_quarantine_message("")
        assert False, "expected ExchangeOnlinePowerShellError"
    except ExchangeOnlinePowerShellError:
        pass

def test_sanitize_powershell_error_text_removes_ansi_sequences():
    raw = "\x1b[31;1mGet-EXORecipientPermission:\x1b[0m Something failed\r\n\r\n\x1b[36;1mLine |\x1b[0m"

    cleaned = _sanitize_powershell_error_text(raw)

    assert cleaned == "Get-EXORecipientPermission: Something failed\n\nLine |"
