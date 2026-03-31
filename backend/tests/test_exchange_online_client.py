from exchange_online_client import ExchangeOnlinePowerShellClient


class StubAzureClient:
    configured = True


def test_get_delegate_mailboxes_for_user_uses_mailbox_identity_pipeline_for_full_access(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(script_body: str, *, extra_env: dict[str, str] | None = None):
        captured["script_body"] = script_body
        captured["extra_env"] = extra_env or {}
        return {"mailbox_count_scanned": 0, "mailboxes": []}

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    result = client.get_delegate_mailboxes_for_user("delegate@example.com")

    assert result == {"mailbox_count_scanned": 0, "mailboxes": []}
    assert captured["extra_env"] == {"DELEGATE_USER": "delegate@example.com"}
    script_body = str(captured["script_body"])
    assert "$mailboxIdentities |" in script_body
    assert "Get-EXOMailboxPermission -User $delegateUser" in script_body
    assert "Get-EXOMailboxPermission -User $delegateUser -ResultSize Unlimited" not in script_body
