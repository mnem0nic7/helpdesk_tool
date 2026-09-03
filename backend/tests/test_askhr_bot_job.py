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
