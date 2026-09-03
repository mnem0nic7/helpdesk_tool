"""Tests for the AskHR/Benefits bot job core: schema, settings bootstrap, and updates."""
from __future__ import annotations

import tempfile


def _fresh_job():
    from askhr_bot_job import AskHrBotJob
    tmp = tempfile.mktemp(suffix=".db")
    return AskHrBotJob(db_path=tmp)


def test_get_settings_bootstraps_default_row_when_missing(monkeypatch):
    import config
    monkeypatch.setattr(config, "ASKHR_BOT_ENABLED_DEFAULT", False)
    import askhr_bot_job as job_module
    monkeypatch.setattr(job_module, "ASKHR_BOT_ENABLED_DEFAULT", False)

    job = _fresh_job()
    settings = job._get_settings()

    assert settings["enabled"] is False
    assert settings["poll_interval_seconds"] == 120
    assert settings["lookback_minutes"] == 15
    assert settings["askhr_checkpoint_at"] == ""
    assert settings["benefits_checkpoint_at"] == ""
    assert settings["trusted_domains"] == []
    assert settings["domain_refresh_interval_seconds"] == 3600
    assert settings["reporter_mode"] == "unset"

    # Second call reads the persisted row rather than re-bootstrapping.
    assert job._get_settings() == settings


def test_update_settings_partial_update_preserves_other_fields():
    job = _fresh_job()
    job._get_settings()  # bootstrap

    updated = job._update_settings(enabled=True, poll_interval_seconds=60, updated_by="admin@example.com")

    assert updated["enabled"] is True
    assert updated["poll_interval_seconds"] == 60
    assert updated["lookback_minutes"] == 15  # untouched

    again = job._update_settings(enabled=False)
    assert again["enabled"] is False
    assert again["poll_interval_seconds"] == 60  # still preserved


def test_update_settings_persists_trusted_domains_and_checkpoints():
    job = _fresh_job()
    job._get_settings()

    updated = job._update_settings(
        trusted_domains=["librasolutionsgroup.com", "movedocs.com"],
        askhr_checkpoint_at="2026-09-03T00:00:00+00:00",
    )

    assert updated["trusted_domains"] == ["librasolutionsgroup.com", "movedocs.com"]
    assert updated["askhr_checkpoint_at"] == "2026-09-03T00:00:00+00:00"


from unittest.mock import MagicMock, patch


def test_refresh_trusted_domains_calls_exchange_when_stale(monkeypatch):
    import askhr_bot_job as job_module
    from datetime import datetime, timezone

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(job_module, "_utcnow", lambda: now)

    job = _fresh_job()
    job._get_settings()  # bootstrap; trusted_domains_refreshed_at == ""

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.get_transport_rule_domains.return_value = ["librasolutionsgroup.com", "movedocs.com"]

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        job._refresh_trusted_domains_if_needed()

    exchange.get_transport_rule_domains.assert_called_once_with(job_module._TRANSPORT_RULE_IDENTITY)
    settings = job._get_settings()
    assert settings["trusted_domains"] == ["librasolutionsgroup.com", "movedocs.com"]
    assert settings["trusted_domains_refreshed_at"] == now.isoformat()


def test_refresh_trusted_domains_skips_when_still_fresh(monkeypatch):
    import askhr_bot_job as job_module
    from datetime import datetime, timezone

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(job_module, "_utcnow", lambda: now)

    job = _fresh_job()
    job._get_settings()
    job._update_settings(trusted_domains=["movedocs.com"], trusted_domains_refreshed_at=now.isoformat())

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        job._refresh_trusted_domains_if_needed()

    exchange.get_transport_rule_domains.assert_not_called()


def _sample_message(**overrides):
    base = {
        "internet_message_id": "<abc123@mail.example.com>",
        "graph_message_id": "AAMkAD...",
        "subject": "Need help with benefits",
        "sender_email": "jane@example.com",
        "sender_name": "Jane Doe",
        "received_at": "2026-09-03T09:00:00+00:00",
        "body": "Can someone help me with open enrollment?",
    }
    base.update(overrides)
    return base


def test_create_or_attach_ticket_probes_and_caches_raise_on_behalf_of(monkeypatch):
    job = _fresh_job()
    job._get_settings()

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None
    mock_jira.create_request.return_value = {"issueKey": "HRD-10"}
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)
    monkeypatch.setattr(mock_jira, "add_attachment", MagicMock(), raising=False)

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key=None)

    assert status == "created"
    assert issue_key == "HRD-10"
    assert error is None
    mock_jira.create_request.assert_called_once()
    assert job._get_settings()["reporter_mode"] == "raise_on_behalf_of"


def test_create_or_attach_ticket_falls_back_to_classic_reporter_on_403(monkeypatch):
    import requests

    job = _fresh_job()
    job._get_settings()

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None
    forbidden = requests.exceptions.HTTPError(response=MagicMock(status_code=403))
    mock_jira.create_request.side_effect = forbidden
    mock_jira.create_issue_with_reporter.return_value = {"key": "HRD-11"}
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key=None)

    assert status == "created"
    assert issue_key == "HRD-11"
    mock_jira.create_issue_with_reporter.assert_called_once()
    assert job._get_settings()["reporter_mode"] == "classic_reporter_field"


def test_create_or_attach_ticket_uses_cached_reporter_mode_without_probing(monkeypatch):
    job = _fresh_job()
    job._get_settings()
    job._update_settings(reporter_mode="classic_reporter_field")

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None
    mock_jira.create_issue_with_reporter.return_value = {"key": "HRD-12"}
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    job._create_or_attach_ticket("benefits", _sample_message(), existing_issue_key=None)

    mock_jira.create_request.assert_not_called()
    mock_jira.create_issue_with_reporter.assert_called_once()


def test_create_or_attach_ticket_uses_jql_fallback_when_local_lookup_is_empty(monkeypatch):
    """The 'other half' of the no-duplicate-ticket guarantee: even when the
    caller has no locally-known issue key, the JQL-based
    find_issue_by_internet_message_id fallback can still find a ticket a
    prior run created (e.g. if that run failed to persist the key locally),
    and ticket creation must be skipped in that case too.
    """
    job = _fresh_job()
    job._get_settings()

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = "HRD-99"
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key=None)

    assert status == "created"
    assert issue_key == "HRD-99"
    assert error is None
    mock_jira.create_request.assert_not_called()
    mock_jira.create_issue_with_reporter.assert_not_called()
    mock_jira.find_issue_by_internet_message_id.assert_called_once()
    mock_azure.graph_raw_request.assert_called_once()


def test_create_or_attach_ticket_skips_creation_when_issue_key_already_exists(monkeypatch):
    job = _fresh_job()
    job._get_settings()

    mock_jira = MagicMock()
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key="HRD-9")

    assert status == "created"
    assert issue_key == "HRD-9"
    mock_jira.create_request.assert_not_called()
    mock_jira.create_issue_with_reporter.assert_not_called()
    mock_jira.find_issue_by_internet_message_id.assert_not_called()


def test_create_or_attach_ticket_records_attachment_failure_but_keeps_issue_key(monkeypatch):
    job = _fresh_job()
    job._get_settings()
    job._update_settings(reporter_mode="raise_on_behalf_of")

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None
    mock_jira.create_request.return_value = {"issueKey": "HRD-13"}
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.side_effect = RuntimeError("graph timeout")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key=None)

    assert status == "failed"
    assert issue_key == "HRD-13"
    assert "graph timeout" in error


def test_attach_email_does_not_send_json_content_type_for_multipart_upload(monkeypatch):
    """Guards against the JiraClient session's default Content-Type: application/json
    header corrupting the multipart attachment upload.

    requests.Session.merge_setting() only lets `requests` auto-compute the
    correct `multipart/form-data; boundary=...` Content-Type header when no
    Content-Type is already present after header merging. Since JiraClient's
    session sets a *default* `Content-Type: application/json` header, a naive
    `session.post(url, files=..., headers={"X-Atlassian-Token": "no-check"})`
    call would merge in the session default (because the per-call headers dict
    doesn't mention Content-Type at all) and ship a JSON content type on a
    multipart body — silently corrupting the upload. This test exercises the
    *real* requests.Session merge/prepare path (only Session.send is stubbed,
    right before the socket) to prove the header actually shipped is the
    multipart one, not the session's JSON default.
    """
    import requests

    job = _fresh_job()
    job._get_settings()

    real_session = requests.Session()
    real_session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    captured = {}

    def fake_send(prepared_request, **kwargs):
        captured["headers"] = dict(prepared_request.headers)
        captured["body"] = prepared_request.body
        response = requests.Response()
        response.status_code = 200
        response._content = b"[]"
        response.request = prepared_request
        return response

    monkeypatch.setattr(real_session, "send", fake_send)

    mock_jira = MagicMock()
    mock_jira.session = real_session
    mock_jira.base_url = "https://example.atlassian.net"
    mock_jira._TIMEOUT = (10, 30)
    mock_jira._raise_for_status = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None

    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")

    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    job._attach_email("askhr", _sample_message(), "HRD-99")

    sent_content_type = captured["headers"].get("Content-Type", "")
    assert sent_content_type.startswith("multipart/form-data; boundary=")
    assert b"raw-eml-bytes" in captured["body"]


def test_should_process_skips_trusted_domain_and_allows_payroll_bypass():
    job = _fresh_job()
    trusted = ["librasolutionsgroup.com", "movedocs.com"]

    assert job._should_process("someone@librasolutionsgroup.com", trusted) is False
    assert job._should_process("outsider@example.com", trusted) is True
    assert job._should_process("payroll@librasolutionsgroup.com", trusted) is True


async def test_run_cycle_skips_entirely_when_disabled():
    job = _fresh_job()
    job._get_settings()  # bootstrap, enabled=False by default

    mock_azure = MagicMock()
    with patch.object(job, "_azure_client", return_value=mock_azure):
        await job.run_cycle()

    mock_azure.graph_paged_get.assert_not_called()
    with job._sqlite_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM askhr_bot_runs").fetchone()["c"] == 0


async def test_run_cycle_creates_ticket_for_untrusted_sender_and_advances_checkpoint(monkeypatch):
    import askhr_bot_job as job_module

    job = _fresh_job()
    job._get_settings()
    job._update_settings(
        enabled=True,
        trusted_domains=["librasolutionsgroup.com"],
        trusted_domains_refreshed_at="2026-09-03T00:00:00+00:00",
        domain_refresh_interval_seconds=3600,
    )
    monkeypatch.setattr(job_module, "_utcnow", lambda: __import__("datetime").datetime(
        2026, 9, 3, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc
    ))
    # _refresh_trusted_domains_if_needed is exercised in isolation elsewhere
    # (test_refresh_trusted_domains_*); with the mocked "now" 12h past the
    # refreshed_at above, it would otherwise consider itself stale and reach
    # out to the real (unmocked, unavailable-in-CI) Exchange PowerShell path.
    # Stub it out so this test stays focused on the polling/checkpoint behavior.
    monkeypatch.setattr(job, "_refresh_trusted_domains_if_needed", lambda: None)

    graph_message = {
        "id": "graph-1",
        "internetMessageId": "<abc@mail.example.com>",
        "subject": "Need benefits help",
        "receivedDateTime": "2026-09-03T11:00:00Z",
        "from": {"emailAddress": {"address": "outsider@example.com", "name": "Outsider Person"}},
        "body": {"content": "Please help"},
    }
    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = [graph_message]
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)
    monkeypatch.setattr(
        job, "_create_or_attach_ticket", lambda mailbox, message, existing_issue_key: ("created", "HRD-20", None)
    )

    await job.run_cycle()

    with job._sqlite_conn() as conn:
        runs = conn.execute("SELECT * FROM askhr_bot_runs").fetchall()
        messages = conn.execute("SELECT * FROM askhr_bot_messages").fetchall()
    # Two mailboxes polled (askhr, benefits) -> at least one run row per mailbox.
    assert len(runs) == 2
    assert any(m["jira_issue_key"] == "HRD-20" for m in messages)
    settings = job._get_settings()
    assert settings["askhr_checkpoint_at"] == "2026-09-03T11:00:00+00:00" or settings["benefits_checkpoint_at"] == "2026-09-03T11:00:00+00:00"


async def test_run_cycle_records_skip_for_trusted_domain_sender(monkeypatch):
    job = _fresh_job()
    job._get_settings()
    job._update_settings(
        enabled=True,
        trusted_domains=["librasolutionsgroup.com"],
        trusted_domains_refreshed_at="2026-09-03T00:00:00+00:00",
    )
    monkeypatch.setattr(job, "_refresh_trusted_domains_if_needed", lambda: None)

    graph_message = {
        "id": "graph-2",
        "internetMessageId": "<internal@mail.example.com>",
        "subject": "Internal note",
        "receivedDateTime": "2026-09-03T11:05:00Z",
        "from": {"emailAddress": {"address": "hr@librasolutionsgroup.com", "name": "HR Team"}},
        "body": {"content": "FYI"},
    }
    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = [graph_message]
    import unittest.mock as mock_lib
    with mock_lib.patch.object(job, "_azure_client", return_value=mock_azure):
        with mock_lib.patch.object(job, "_create_or_attach_ticket") as create_mock:
            await job.run_cycle()
            create_mock.assert_not_called()

    with job._sqlite_conn() as conn:
        row = conn.execute(
            "SELECT status FROM askhr_bot_messages WHERE internet_message_id = ?",
            ("<internal@mail.example.com>",),
        ).fetchone()
    assert row["status"] == "skipped_internal_domain"


async def test_run_cycle_one_message_failure_does_not_abort_the_batch(monkeypatch):
    job = _fresh_job()
    job._get_settings()
    job._update_settings(enabled=True, trusted_domains=[], trusted_domains_refreshed_at="2026-09-03T00:00:00+00:00")
    monkeypatch.setattr(job, "_refresh_trusted_domains_if_needed", lambda: None)

    messages = [
        {
            "id": "graph-3", "internetMessageId": "<m1@mail.example.com>", "subject": "One",
            "receivedDateTime": "2026-09-03T11:00:00Z",
            "from": {"emailAddress": {"address": "a@example.com", "name": "A"}}, "body": {"content": "x"},
        },
        {
            "id": "graph-4", "internetMessageId": "<m2@mail.example.com>", "subject": "Two",
            "receivedDateTime": "2026-09-03T11:01:00Z",
            "from": {"emailAddress": {"address": "b@example.com", "name": "B"}}, "body": {"content": "y"},
        },
    ]
    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = messages
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    def fake_create(mailbox, message, existing_issue_key):
        if message["internet_message_id"] == "<m1@mail.example.com>":
            raise RuntimeError("jira down")
        return "created", "HRD-30", None

    monkeypatch.setattr(job, "_create_or_attach_ticket", fake_create)

    await job.run_cycle()

    with job._sqlite_conn() as conn:
        statuses = {
            r["internet_message_id"]: r["status"]
            for r in conn.execute("SELECT internet_message_id, status FROM askhr_bot_messages")
        }
    assert statuses["<m1@mail.example.com>"] == "failed"
    assert statuses["<m2@mail.example.com>"] == "created"


async def test_poll_mailbox_lookback_window_handles_z_suffixed_checkpoint(monkeypatch):
    """Regression guard for the known Graph-timestamp risk: receivedDateTime (and
    any checkpoint derived from it) is UTC with a literal 'Z' suffix. The repo's
    backend venv is Python 3.12 (verified via `backend/.venv/bin/python --version`),
    which parses 'Z' natively in datetime.fromisoformat(), but this test proves the
    checkpoint/lookback-window math actually works end-to-end with a raw
    'Z'-suffixed checkpoint value rather than assuming it from the version alone.
    """
    job = _fresh_job()
    job._get_settings()
    job._update_settings(
        enabled=True,
        trusted_domains=[],
        trusted_domains_refreshed_at="2026-09-03T00:00:00+00:00",
        askhr_checkpoint_at="2026-09-03T10:00:00Z",
        lookback_minutes=15,
    )
    monkeypatch.setattr(job, "_refresh_trusted_domains_if_needed", lambda: None)

    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = []
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    settings = job._get_settings()
    await job._poll_mailbox("askhr", settings)

    _, call_kwargs = mock_azure.graph_paged_get.call_args
    filter_clause = call_kwargs["params"]["$filter"]
    # since = checkpoint (10:00:00Z) - lookback (15m) = 09:45:00Z
    assert "2026-09-03T09:45:00Z" in filter_clause


async def test_run_cycle_runs_domain_refresh_off_the_event_loop(monkeypatch):
    """_refresh_trusted_domains_if_needed() can do blocking subprocess I/O
    (Exchange Online PowerShell via pwsh, up to ~240s) when the trusted-domain
    cache is stale. run_cycle() is awaited directly from the shared FastAPI
    event loop, so it must schedule that call via run_in_executor rather than
    calling it inline -- otherwise it would stall every other request and
    background service sharing that loop for the duration. This spies on the
    running loop's run_in_executor to prove the refresh call is actually
    routed through it, not called synchronously.
    """
    import asyncio

    job = _fresh_job()
    job._get_settings()
    job._update_settings(enabled=True, trusted_domains=[])

    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = []
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    refresh_call_count = 0

    def fake_refresh():
        nonlocal refresh_call_count
        refresh_call_count += 1

    monkeypatch.setattr(job, "_refresh_trusted_domains_if_needed", fake_refresh)

    loop = asyncio.get_event_loop()
    real_run_in_executor = loop.run_in_executor
    executor_funcs = []

    def spy_run_in_executor(executor, func, *args):
        executor_funcs.append(func)
        return real_run_in_executor(executor, func, *args)

    monkeypatch.setattr(loop, "run_in_executor", spy_run_in_executor)

    await job.run_cycle()

    assert fake_refresh in executor_funcs
    assert refresh_call_count == 1
