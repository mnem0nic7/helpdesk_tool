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


def test_refresh_trusted_domains_keeps_previous_list_when_exchange_returns_empty(monkeypatch):
    """Fail closed, not open. get_transport_rule_domains() returns [] both for
    a genuinely empty rule and for a degraded Exchange response, and an empty
    trusted_domains list makes _should_process() treat every sender as
    external -- which would mass-file HRD tickets for internal mail for a
    whole refresh interval. So an empty result must leave BOTH the cached
    domain list and its refreshed-at stamp untouched, letting the next cycle
    retry (and leaving the staleness visible on /api/askhr-bot/status).
    """
    import askhr_bot_job as job_module
    from datetime import datetime, timezone

    stale_at = "2026-09-01T00:00:00+00:00"
    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(job_module, "_utcnow", lambda: now)

    job = _fresh_job()
    job._get_settings()
    job._update_settings(
        trusted_domains=["librasolutionsgroup.com", "movedocs.com"],
        trusted_domains_refreshed_at=stale_at,
        domain_refresh_interval_seconds=3600,
    )
    before = job._get_settings()

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.get_transport_rule_domains.return_value = []

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        job._refresh_trusted_domains_if_needed()

    # It did try (the cache was stale) ...
    exchange.get_transport_rule_domains.assert_called_once_with(job_module._TRANSPORT_RULE_IDENTITY)
    # ... but nothing was overwritten.
    after = job._get_settings()
    assert after["trusted_domains"] == before["trusted_domains"] == ["librasolutionsgroup.com", "movedocs.com"]
    assert after["trusted_domains_refreshed_at"] == stale_at


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
    mock_jira.create_customer.side_effect = RuntimeError("customer resolution not under test here")
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
    mock_jira.create_customer.side_effect = RuntimeError("customer resolution not under test here")
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key=None)

    assert status == "created"
    assert issue_key == "HRD-11"
    mock_jira.create_issue_with_reporter.assert_called_once()
    assert mock_jira.create_issue_with_reporter.call_args.kwargs["issue_type"] == "Email Request"
    assert job._get_settings()["reporter_mode"] == "classic_reporter_field"


def test_classic_issue_types_match_live_hrd_project_names():
    """Confirmed against HRD's real createmeta on 2026-09-03 — the original
    placeholders ("Emailed request", "Benefits") did not exist as issue types
    and caused every classic-fallback ticket to fail with a 400."""
    import askhr_bot_job as job_module

    assert job_module.CLASSIC_ISSUE_TYPES == {
        "askhr": "Email Request",
        "benefits": "Comp & Benefits",
    }


def test_create_or_attach_ticket_uses_cached_reporter_mode_without_probing(monkeypatch):
    job = _fresh_job()
    job._get_settings()
    job._update_settings(reporter_mode="classic_reporter_field")

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None
    mock_jira.create_issue_with_reporter.return_value = {"key": "HRD-12"}
    mock_jira.create_customer.side_effect = RuntimeError("customer resolution not under test here")
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
    mock_jira.create_customer.side_effect = RuntimeError("customer resolution not under test here")
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.side_effect = RuntimeError("graph timeout")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key=None)

    assert status == "failed"
    assert issue_key == "HRD-13"
    assert "graph timeout" in error


def test_create_or_attach_ticket_uploads_real_attachments_after_the_eml(monkeypatch):
    job = _fresh_job()
    job._get_settings()
    job._update_settings(reporter_mode="raise_on_behalf_of")

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None
    mock_jira.create_request.return_value = {"issueKey": "HRD-14"}
    mock_jira.create_customer.side_effect = RuntimeError("customer resolution not under test here")
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)
    monkeypatch.setattr(
        job, "_fetch_real_attachments",
        lambda mailbox, message: [{"name": "receipt.pdf", "content_type": "application/pdf", "content": b"x"}],
    )

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key=None)

    assert status == "created"
    assert issue_key == "HRD-14"
    assert error is None
    # One upload for the .eml, one for the real attachment.
    assert mock_jira.session.post.call_count == 2


def test_create_or_attach_ticket_still_reports_created_when_a_real_attachment_fails(monkeypatch):
    """A failing real-attachment upload is non-fatal to the message status --
    see _attach_real_attachments' docstring for why a raise here would risk
    duplicate attachments on retry.
    """
    job = _fresh_job()
    job._get_settings()
    job._update_settings(reporter_mode="raise_on_behalf_of")

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None
    mock_jira.create_request.return_value = {"issueKey": "HRD-15"}
    mock_jira.create_customer.side_effect = RuntimeError("customer resolution not under test here")
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)
    monkeypatch.setattr(
        job, "_fetch_real_attachments",
        lambda mailbox, message: [{"name": "bad.pdf", "content_type": "application/pdf", "content": b"x"}],
    )
    monkeypatch.setattr(job, "_upload_attachment", MagicMock(side_effect=[None, RuntimeError("boom")]))

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key=None)

    assert status == "created"
    assert issue_key == "HRD-15"
    assert error is None


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


def _fake_file_attachment(**overrides):
    import base64

    base = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": "receipt.pdf",
        "contentType": "application/pdf",
        "size": 50_000,
        "isInline": False,
        "contentBytes": base64.b64encode(b"pdf-bytes").decode("ascii"),
    }
    base.update(overrides)
    return base


def test_fetch_real_attachments_decodes_a_normal_file_attachment():
    job = _fresh_job()
    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = [_fake_file_attachment()]

    with patch.object(job, "_azure_client", return_value=mock_azure):
        attachments = job._fetch_real_attachments("askhr", _sample_message())

    assert attachments == [{"name": "receipt.pdf", "content_type": "application/pdf", "content": b"pdf-bytes"}]


def test_fetch_real_attachments_skips_small_inline_signature_images():
    job = _fresh_job()
    small_logo = _fake_file_attachment(name="logo.png", isInline=True, size=5_000)
    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = [small_logo]

    with patch.object(job, "_azure_client", return_value=mock_azure):
        attachments = job._fetch_real_attachments("askhr", _sample_message())

    assert attachments == []


def test_fetch_real_attachments_keeps_large_inline_images():
    """A pasted screenshot is also isInline=True, but it's real content --
    only small, signature-sized inline images should be dropped.
    """
    job = _fresh_job()
    pasted_screenshot = _fake_file_attachment(name="screenshot.png", isInline=True, size=500_000)
    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = [pasted_screenshot]

    with patch.object(job, "_azure_client", return_value=mock_azure):
        attachments = job._fetch_real_attachments("askhr", _sample_message())

    assert [a["name"] for a in attachments] == ["screenshot.png"]


def test_fetch_real_attachments_skips_non_file_attachment_types():
    job = _fresh_job()
    item_attachment = {"@odata.type": "#microsoft.graph.itemAttachment", "name": "forwarded.eml"}
    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = [item_attachment]

    with patch.object(job, "_azure_client", return_value=mock_azure):
        attachments = job._fetch_real_attachments("askhr", _sample_message())

    assert attachments == []


def test_attach_real_attachments_uploads_each_one():
    job = _fresh_job()
    mock_jira = MagicMock()
    mock_jira.base_url = "https://example.atlassian.net"
    mock_jira._TIMEOUT = (10, 30)
    response = MagicMock(status_code=200)
    mock_jira.session.post.return_value = response
    mock_jira._raise_for_status = MagicMock()
    job._jira = mock_jira

    monkeypatch_attachments = [
        {"name": "receipt.pdf", "content_type": "application/pdf", "content": b"pdf-bytes"},
        {"name": "receipt2.pdf", "content_type": "application/pdf", "content": b"more-bytes"},
    ]
    with patch.object(job, "_fetch_real_attachments", return_value=monkeypatch_attachments):
        job._attach_real_attachments("askhr", _sample_message(), "HRD-70")

    assert mock_jira.session.post.call_count == 2
    uploaded_names = [call.kwargs["files"]["file"][0] for call in mock_jira.session.post.call_args_list]
    assert uploaded_names == ["receipt.pdf", "receipt2.pdf"]


def test_attach_real_attachments_skips_a_failing_upload_without_raising():
    """One bad attachment must not block the rest -- and must not raise,
    since a raise here would mark the whole message 'failed' and retry from
    scratch next cycle, re-uploading attachments that already succeeded.
    """
    job = _fresh_job()
    mock_jira = MagicMock()
    mock_jira.base_url = "https://example.atlassian.net"
    mock_jira._TIMEOUT = (10, 30)
    mock_jira.session.post.return_value = MagicMock(status_code=200)
    mock_jira._raise_for_status = MagicMock(side_effect=[RuntimeError("upload failed"), None])
    job._jira = mock_jira

    attachments = [
        {"name": "bad.pdf", "content_type": "application/pdf", "content": b"x"},
        {"name": "good.pdf", "content_type": "application/pdf", "content": b"y"},
    ]
    with patch.object(job, "_fetch_real_attachments", return_value=attachments):
        job._attach_real_attachments("askhr", _sample_message(), "HRD-71")

    assert mock_jira.session.post.call_count == 2


def test_resolve_customer_account_id_creates_and_caches_new_sender():
    job = _fresh_job()

    mock_jira = MagicMock()
    mock_jira.create_customer.return_value = {"accountId": "qm:tenant:new-customer-id"}
    job._jira = mock_jira

    account_id = job._resolve_customer_account_id("jane@example.com", "Jane Doe")

    assert account_id == "qm:tenant:new-customer-id"
    mock_jira.create_customer.assert_called_once_with(
        email="jane@example.com", display_name="Jane Doe", strict_conflict_status_code=True
    )
    with job._sqlite_conn() as conn:
        row = conn.execute(
            "SELECT jira_account_id FROM askhr_bot_customer_accounts WHERE sender_email = ?",
            ("jane@example.com",),
        ).fetchone()
    assert row["jira_account_id"] == "qm:tenant:new-customer-id"


def test_resolve_customer_account_id_uses_local_cache_without_calling_jira():
    job = _fresh_job()
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO askhr_bot_customer_accounts (sender_email, jira_account_id, created_at) "
            "VALUES ('jane@example.com', 'qm:tenant:cached-id', '2026-09-01T00:00:00+00:00')"
        )

    mock_jira = MagicMock()
    job._jira = mock_jira

    account_id = job._resolve_customer_account_id("jane@example.com", "Jane Doe")

    assert account_id == "qm:tenant:cached-id"
    mock_jira.create_customer.assert_not_called()


def test_resolve_customer_account_id_falls_back_to_search_when_already_exists(monkeypatch):
    import requests

    job = _fresh_job()

    mock_jira = MagicMock()
    already_exists = requests.exceptions.HTTPError(response=MagicMock(status_code=409))
    mock_jira.create_customer.side_effect = already_exists
    mock_jira.find_user_account_id_by_email.return_value = "qm:tenant:existing-id"
    job._jira = mock_jira

    account_id = job._resolve_customer_account_id("jane@example.com", "Jane Doe")

    assert account_id == "qm:tenant:existing-id"
    mock_jira.find_user_account_id_by_email.assert_called_once_with("jane@example.com")
    with job._sqlite_conn() as conn:
        row = conn.execute(
            "SELECT jira_account_id FROM askhr_bot_customer_accounts WHERE sender_email = ?",
            ("jane@example.com",),
        ).fetchone()
    assert row["jira_account_id"] == "qm:tenant:existing-id"


def test_resolve_customer_account_id_raises_when_already_exists_but_search_is_empty(monkeypatch):
    """Jira Cloud's user-search index has eventual-consistency lag for
    recently created accounts, so an "already exists" 409 combined with an
    empty search is a real, expected outcome -- not a bug -- and must raise
    so the caller (_create_ticket) falls back to the generic reporter."""
    import requests

    job = _fresh_job()

    mock_jira = MagicMock()
    already_exists = requests.exceptions.HTTPError(response=MagicMock(status_code=409))
    mock_jira.create_customer.side_effect = already_exists
    mock_jira.find_user_account_id_by_email.return_value = None
    job._jira = mock_jira

    try:
        job._resolve_customer_account_id("jane@example.com", "Jane Doe")
        assert False, "expected an exception"
    except RuntimeError:
        pass


def test_resolve_customer_account_id_reraises_non_409_errors():
    import requests

    job = _fresh_job()

    mock_jira = MagicMock()
    server_error = requests.exceptions.HTTPError(response=MagicMock(status_code=500))
    mock_jira.create_customer.side_effect = server_error
    job._jira = mock_jira

    try:
        job._resolve_customer_account_id("jane@example.com", "Jane Doe")
        assert False, "expected the 500 to propagate"
    except requests.exceptions.HTTPError:
        pass
    mock_jira.find_user_account_id_by_email.assert_not_called()


def test_build_description_converts_html_body_to_adf_instead_of_dumping_raw_markup():
    """Regression guard for HRD-1333: an HTML body must not end up as a
    literal '<html><head>...' string in the ticket description.
    """
    job = _fresh_job()
    message = _sample_message(
        body="<p>plain <b>bold</b> text</p>", body_content_type="html",
        sender_name="Jane Doe", sender_email="jane@example.com", received_at="2026-09-03T09:00:00+00:00",
    )

    description = job._build_description(message)

    assert description["type"] == "doc"
    header_paragraph, body_paragraph = description["content"]
    header_text = "".join(n["text"] for n in header_paragraph["content"] if n["type"] == "text")
    assert header_text == "Originally sent by: Jane Doe <jane@example.com> on 2026-09-03T09:00:00+00:00"
    assert body_paragraph == {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": "plain "},
            {"type": "text", "text": "bold", "marks": [{"type": "strong"}]},
            {"type": "text", "text": " text"},
        ],
    }
    # No raw HTML tags leaked into the converted body text (the header's
    # "<jane@example.com>" is expected and not part of what's being guarded).
    body_text = "".join(n["text"] for n in body_paragraph["content"] if n["type"] == "text")
    assert "<" not in body_text and ">" not in body_text


def test_build_description_treats_plain_text_body_as_plain_text():
    """Graph reports contentType 'text' for plain-text mail -- that path must
    keep working exactly like before (no HTML parsing attempted).
    """
    job = _fresh_job()
    message = _sample_message(body="Can someone help me with open enrollment?", body_content_type="text")

    description = job._build_description(message)

    _, body_paragraph = description["content"]
    assert body_paragraph == {
        "type": "paragraph",
        "content": [{"type": "text", "text": "Can someone help me with open enrollment?"}],
    }


def test_build_description_truncates_an_oversized_body_instead_of_failing_jira():
    """Regression guard for HRD-1299/McMorris: a reply that quotes an entire
    negotiation thread can exceed Jira's ~32,767-character field limit,
    which makes ticket creation fail outright with a 400 -- and because
    creation never got an issue key, the .eml audit copy never gets attached
    either, so the message is lost until someone manually recovers it from
    the mailbox. The description body must be capped well under that limit,
    with a note that the full message wasn't lost (once the ticket exists,
    _attach_email still attaches the untruncated original).
    """
    import askhr_bot_job as job_module

    job = _fresh_job()
    huge_body = "x" * (job_module._MAX_DESCRIPTION_BODY_CHARS + 5_000)
    message = _sample_message(body=huge_body, body_content_type="text")

    description = job._build_description(message)

    header_paragraph, *body_paragraphs = description["content"]
    body_text = "".join(
        n["text"] for paragraph in body_paragraphs for n in paragraph["content"] if n["type"] == "text"
    )
    assert len(body_text) < job_module._MAX_DESCRIPTION_BODY_CHARS + 200
    assert "truncated" in body_text.lower()
    assert body_text.startswith("x" * 100)


def test_build_description_does_not_truncate_a_normal_sized_body():
    job = _fresh_job()
    message = _sample_message(body="A perfectly normal, short message.", body_content_type="text")

    description = job._build_description(message)

    _, body_paragraph = description["content"]
    body_text = "".join(n["text"] for n in body_paragraph["content"] if n["type"] == "text")
    assert body_text == "A perfectly normal, short message."


def test_create_ticket_uses_resolved_sender_as_reporter():
    job = _fresh_job()
    job._get_settings()
    job._update_settings(reporter_mode="raise_on_behalf_of")

    mock_jira = MagicMock()
    mock_jira.create_customer.return_value = {"accountId": "qm:tenant:sender-id"}
    mock_jira.create_request.return_value = {"issueKey": "HRD-50"}
    job._jira = mock_jira

    issue_key = job._create_ticket("askhr", _sample_message())

    assert issue_key == "HRD-50"
    import askhr_bot_job as job_module

    mock_jira.create_request.assert_called_once_with(
        service_desk_id=job_module.JSM_SERVICE_DESK_ID,
        request_type_id="420",
        raise_on_behalf_of="qm:tenant:sender-id",
        summary=_sample_message()["subject"],
        description=job._build_description(_sample_message()),
    )


def test_create_ticket_falls_back_to_generic_reporter_when_resolution_fails():
    job = _fresh_job()
    job._get_settings()
    job._update_settings(reporter_mode="raise_on_behalf_of")

    mock_jira = MagicMock()
    mock_jira.create_customer.side_effect = RuntimeError("boom")
    mock_jira.create_request.return_value = {"issueKey": "HRD-51"}
    job._jira = mock_jira

    issue_key = job._create_ticket("askhr", _sample_message())

    assert issue_key == "HRD-51"
    import askhr_bot_job as job_module

    mock_jira.create_request.assert_called_once_with(
        service_desk_id=job_module.JSM_SERVICE_DESK_ID,
        request_type_id="420",
        raise_on_behalf_of=job_module.REPORTER_ACCOUNT_IDS["askhr"],
        summary=_sample_message()["subject"],
        description=job._build_description(_sample_message()),
    )


def test_fetch_message_from_graph_builds_a_full_message_dict():
    """Regression guard for the retry route: the DB only stores metadata
    (subject/sender/timestamps), never the body -- so retrying a
    previously-failed message must re-fetch the real body (and sender name)
    from Graph rather than retrying with an empty description.
    """
    job = _fresh_job()
    mock_azure = MagicMock()
    mock_azure.graph_request.return_value = {
        "id": "graph-99",
        "internetMessageId": "<m1@mail.example.com>",
        "subject": "Re: Separation Information",
        "receivedDateTime": "2026-09-04T14:14:18Z",
        "from": {"emailAddress": {"address": "jenny@example.com", "name": "Jenny McMorris"}},
        "body": {"contentType": "html", "content": "<p>still waiting to hear back</p>"},
    }

    with patch.object(job, "_azure_client", return_value=mock_azure):
        message = job._fetch_message_from_graph("askhr", "graph-99")

    assert message == {
        "internet_message_id": "<m1@mail.example.com>",
        "graph_message_id": "graph-99",
        "subject": "Re: Separation Information",
        "sender_email": "jenny@example.com",
        "sender_name": "Jenny McMorris",
        "received_at": "2026-09-04T14:14:18+00:00",
        "body": "<p>still waiting to hear back</p>",
        "body_content_type": "html",
    }
    mock_azure.graph_request.assert_called_once_with(
        "GET", "users/AskHR@librasolutionsgroup.com/messages/graph-99",
        params={"$select": "id,internetMessageId,subject,receivedDateTime,from,body"},
    )


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


async def test_same_message_id_in_both_mailboxes_gets_independent_rows_and_attempts(monkeypatch):
    """A message addressed to both AskHR@ and Benefits@ arrives in both
    Inboxes with the same internetMessageId. Each mailbox must get its own
    detail row and its own ticket-creation attempt -- with the old
    Message-ID-only primary key, whichever mailbox was polled second saw the
    first one's row (status='created') and silently skipped its own ticket.
    """
    job = _fresh_job()
    job._get_settings()
    job._update_settings(enabled=True, trusted_domains=["librasolutionsgroup.com"])
    monkeypatch.setattr(job, "_refresh_trusted_domains_if_needed", lambda: None)

    # Same internetMessageId in both mailboxes, different Graph message ids
    # (each mailbox stores its own copy of the mail).
    def graph_paged_get(path, params=None, headers=None):
        graph_id = "graph-askhr" if "AskHR@" in path else "graph-benefits"
        return [{
            "id": graph_id,
            "internetMessageId": "<dual@mail.example.com>",
            "subject": "Question for HR",
            "receivedDateTime": "2026-09-03T11:00:00Z",
            "from": {"emailAddress": {"address": "outsider@example.com", "name": "Outsider"}},
            "body": {"content": "Please help"},
        }]

    mock_azure = MagicMock()
    mock_azure.graph_paged_get.side_effect = graph_paged_get
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    attempts = []

    def fake_create(mailbox, message, existing_issue_key):
        attempts.append((mailbox, message["graph_message_id"]))
        return "created", f"HRD-{len(attempts)}", None

    monkeypatch.setattr(job, "_create_or_attach_ticket", fake_create)

    await job.run_cycle()

    # One independent creation attempt per mailbox, each with that mailbox's
    # own Graph message id.
    assert sorted(attempts) == [("askhr", "graph-askhr"), ("benefits", "graph-benefits")]

    with job._sqlite_conn() as conn:
        rows = {
            r["mailbox"]: (r["graph_message_id"], r["status"], r["jira_issue_key"])
            for r in conn.execute(
                "SELECT mailbox, graph_message_id, status, jira_issue_key FROM askhr_bot_messages "
                "WHERE internet_message_id = '<dual@mail.example.com>'"
            )
        }
    assert set(rows) == {"askhr", "benefits"}
    assert rows["askhr"][0] == "graph-askhr"
    assert rows["benefits"][0] == "graph-benefits"
    assert rows["askhr"][2] != rows["benefits"][2]


async def test_existing_message_row_is_scoped_to_the_mailbox():
    job = _fresh_job()
    job._get_settings()
    message = _sample_message(internet_message_id="<dual@mail.example.com>")

    with job._conn() as conn:
        job._record_message(
            mailbox="askhr", message=message, status="created",
            jira_issue_key="HRD-60", error=None, conn=conn,
        )

    with job._conn() as conn:
        assert job._existing_message_row("askhr", "<dual@mail.example.com>", conn)["jira_issue_key"] == "HRD-60"
        # The benefits mailbox has never seen this message -> no row.
        assert job._existing_message_row("benefits", "<dual@mail.example.com>", conn) is None


async def test_poll_mailbox_lookback_window_handles_z_suffixed_checkpoint(monkeypatch):
    """Regression guard for the known Graph-timestamp risk: receivedDateTime (and
    any checkpoint derived from it) is UTC with a literal 'Z' suffix. The repo's
    backend venv is Python 3.12 (verified via `backend/.venv/bin/python --version`),
    which parses 'Z' natively in datetime.fromisoformat(), but this test proves the
    checkpoint/lookback-window math actually works end-to-end with a raw
    'Z'-suffixed checkpoint value rather than assuming it from the version alone.
    """
    from datetime import datetime, timedelta, timezone

    # Checkpoint must stay within the 24h catch-up cap (_MAX_CATCHUP_HOURS) or
    # _poll_mailbox clamps `since` to `now - 24h`, which would replace the
    # literal checkpoint-derived filter clause this test is asserting on.
    checkpoint_dt = datetime.now(timezone.utc) - timedelta(hours=2)
    checkpoint_at = checkpoint_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    expected_since = (checkpoint_dt - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")

    job = _fresh_job()
    job._get_settings()
    job._update_settings(
        enabled=True,
        trusted_domains=[],
        trusted_domains_refreshed_at=datetime.now(timezone.utc).isoformat(),
        askhr_checkpoint_at=checkpoint_at,
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
    # since = checkpoint - lookback (15m)
    assert expected_since in filter_clause


async def test_poll_mailbox_clamps_a_far_past_checkpoint_to_the_catchup_cap(monkeypatch):
    """A checkpoint left far in the past (bot disabled for days, leader down)
    must not make one cycle sweep the whole intervening Inbox -- the same
    failure shape as the 2026-09-01 quarantine-sweep timeout. The Graph
    $filter must reflect the clamped window, not the real gap.
    """
    import askhr_bot_job as job_module
    from datetime import datetime, timezone

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(job_module, "_utcnow", lambda: now)

    job = _fresh_job()
    job._get_settings()
    job._update_settings(
        enabled=True,
        trusted_domains=["librasolutionsgroup.com"],
        trusted_domains_refreshed_at=now.isoformat(),
        # 10 days stale.
        askhr_checkpoint_at="2026-08-24T12:00:00+00:00",
        lookback_minutes=15,
    )
    monkeypatch.setattr(job, "_refresh_trusted_domains_if_needed", lambda: None)

    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = []
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    await job._poll_mailbox("askhr", job._get_settings())

    _, call_kwargs = mock_azure.graph_paged_get.call_args
    filter_clause = call_kwargs["params"]["$filter"]
    # Clamped to now - _MAX_CATCHUP_HOURS (24h) = 2026-09-02T12:00:00Z,
    # NOT the raw checkpoint-minus-lookback of 2026-08-24T11:45:00Z.
    assert job_module._MAX_CATCHUP_HOURS == 24
    assert "2026-09-02T12:00:00Z" in filter_clause
    assert "2026-08-24" not in filter_clause


async def test_poll_mailbox_does_not_clamp_a_recent_checkpoint(monkeypatch):
    """The cap is a floor, not a fixed window -- a normal recent checkpoint
    must still produce its own checkpoint-minus-lookback `since`.
    """
    import askhr_bot_job as job_module
    from datetime import datetime, timezone

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(job_module, "_utcnow", lambda: now)

    job = _fresh_job()
    job._get_settings()
    job._update_settings(
        enabled=True,
        trusted_domains=["librasolutionsgroup.com"],
        trusted_domains_refreshed_at=now.isoformat(),
        askhr_checkpoint_at="2026-09-03T11:50:00+00:00",
        lookback_minutes=15,
    )
    monkeypatch.setattr(job, "_refresh_trusted_domains_if_needed", lambda: None)

    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = []
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    await job._poll_mailbox("askhr", job._get_settings())

    _, call_kwargs = mock_azure.graph_paged_get.call_args
    assert "2026-09-03T11:35:00Z" in call_kwargs["params"]["$filter"]


async def test_poll_mailbox_does_not_force_graph_to_strip_html_body(monkeypatch):
    """An earlier fix for HRD-1333 asked Graph for a stripped plain-text body
    via `Prefer: outlook.body-content-type="text"`. That was reverted once
    _build_description gained a real HTML-to-ADF converter (email_html_to_adf)
    -- forcing plain text would throw away formatting entirely, defeating the
    point. Graph's default (HTML) must be allowed through untouched.
    """
    job = _fresh_job()
    job._get_settings()
    job._update_settings(enabled=True, trusted_domains=[], trusted_domains_refreshed_at="2026-09-03T00:00:00+00:00")
    monkeypatch.setattr(job, "_refresh_trusted_domains_if_needed", lambda: None)

    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = []
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    await job._poll_mailbox("askhr", job._get_settings())

    _, call_kwargs = mock_azure.graph_paged_get.call_args
    assert call_kwargs.get("headers") in (None, {})


async def test_poll_mailbox_threads_graph_content_type_into_the_message(monkeypatch):
    """_create_or_attach_ticket (and therefore _build_description) needs to
    know whether Graph reported the body as html or text -- verify
    _poll_mailbox actually passes that through rather than dropping it.
    """
    job = _fresh_job()
    job._get_settings()
    job._update_settings(enabled=True, trusted_domains=[], trusted_domains_refreshed_at="2026-09-03T00:00:00+00:00")
    monkeypatch.setattr(job, "_refresh_trusted_domains_if_needed", lambda: None)

    graph_message = {
        "id": "graph-html-1",
        "internetMessageId": "<html-body@mail.example.com>",
        "subject": "Receipt",
        "receivedDateTime": "2026-09-03T11:00:00Z",
        "from": {"emailAddress": {"address": "outsider@example.com", "name": "Outsider"}},
        "body": {"contentType": "html", "content": "<p>hi</p>"},
    }
    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = [graph_message]
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    seen_messages = []

    def fake_create(mailbox, message, existing_issue_key):
        seen_messages.append(message)
        return "created", "HRD-40", None

    monkeypatch.setattr(job, "_create_or_attach_ticket", fake_create)

    await job._poll_mailbox("askhr", job._get_settings())

    assert seen_messages[0]["body_content_type"] == "html"


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


async def test_start_and_stop_background_runner_does_not_raise():
    import asyncio

    job = _fresh_job()
    job.start_background_runner()
    assert job._bg_task is not None
    await asyncio.sleep(0)
    job.stop_background_runner()
    await asyncio.sleep(0)
    assert job._bg_task.cancelled() or job._bg_task.done()
