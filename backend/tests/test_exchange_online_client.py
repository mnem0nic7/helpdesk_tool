from exchange_online_client import ExchangeOnlinePowerShellClient, _sanitize_powershell_error_text


class StubAzureClient:
    configured = True


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


def test_sanitize_powershell_error_text_removes_ansi_sequences():
    raw = "\x1b[31;1mGet-EXORecipientPermission:\x1b[0m Something failed\r\n\r\n\x1b[36;1mLine |\x1b[0m"

    cleaned = _sanitize_powershell_error_text(raw)

    assert cleaned == "Get-EXORecipientPermission: Something failed\n\nLine |"
