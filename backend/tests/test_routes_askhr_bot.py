"""Tests for the AskHR bot admin API routes."""
from __future__ import annotations

from unittest.mock import MagicMock


def _job_with_settings(tmp_path, **overrides):
    import askhr_bot_job as job_module

    job = job_module.AskHrBotJob(db_path=str(tmp_path / "askhr.db"))
    job._get_settings()
    if overrides:
        job._update_settings(**overrides)
    return job


def test_get_status_reflects_settings_and_no_runs(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path, enabled=True)
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)

    resp = test_client.get("/api/askhr-bot/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["last_runs"]["askhr"] is None
    assert data["last_runs"]["benefits"] is None


def test_get_status_forbidden_for_non_admin(test_client, monkeypatch, tmp_path):
    import auth
    job = _job_with_settings(tmp_path)
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: email != "non-admin@example.com")
    non_admin_sid = auth.create_session("non-admin@example.com", "Non Admin")
    test_client.cookies.set("session_id", non_admin_sid)
    try:
        resp = test_client.get("/api/askhr-bot/status")
        assert resp.status_code == 403
    finally:
        test_client.cookies.set("session_id", auth.create_session("test@example.com", "Test User"))


def test_patch_settings_updates_enabled_and_poll_interval(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path)
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)

    resp = test_client.patch("/api/askhr-bot/settings", json={"enabled": True, "poll_interval_seconds": 60})
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["poll_interval_seconds"] == 60


def test_post_reporter_mode_reset_sets_unset(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path, reporter_mode="classic_reporter_field")
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)

    resp = test_client.post("/api/askhr-bot/reporter-mode/reset")
    assert resp.status_code == 200
    assert resp.json()["reporter_mode"] == "unset"


def test_get_runs_filters_by_mailbox(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path)
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO askhr_bot_runs (id, mailbox, run_started_at, messages_scanned, created_count, skipped_count, failed_count) "
            "VALUES ('r1', 'askhr', '2026-09-03T11:00:00+00:00', 2, 1, 1, 0)"
        )
        conn.execute(
            "INSERT INTO askhr_bot_runs (id, mailbox, run_started_at, messages_scanned, created_count, skipped_count, failed_count) "
            "VALUES ('r2', 'benefits', '2026-09-03T11:00:00+00:00', 1, 1, 0, 0)"
        )
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)

    resp = test_client.get("/api/askhr-bot/runs?mailbox=askhr")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "r1"


def _mock_azure_with_graph_message(**overrides):
    graph_message = {
        "id": "graph-1",
        "internetMessageId": "<m1@mail.example.com>",
        "subject": "Subject",
        "receivedDateTime": "2026-09-03T11:00:00Z",
        "from": {"emailAddress": {"address": "a@example.com", "name": "A Sender"}},
        "body": {"contentType": "text", "content": "the real message body"},
    }
    graph_message.update(overrides)
    mock_azure = MagicMock()
    mock_azure.graph_request.return_value = graph_message
    return mock_azure


def test_retry_creates_ticket_for_previously_failed_message(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path)
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO askhr_bot_messages "
            "(internet_message_id, mailbox, graph_message_id, subject, sender_email, received_at, "
            "status, jira_issue_key, error, processed_at) "
            "VALUES ('<m1@mail.example.com>', 'askhr', 'graph-1', 'Subject', 'a@example.com', "
            "'2026-09-03T11:00:00+00:00', 'failed', 'HRD-40', 'attachment failed: boom', '2026-09-03T11:01:00+00:00')"
        )
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)
    monkeypatch.setattr(
        job, "_create_or_attach_ticket",
        lambda mailbox, message, existing_issue_key: ("created", "HRD-40", None),
    )
    monkeypatch.setattr(job, "_azure_client", lambda: _mock_azure_with_graph_message())

    resp = test_client.post("/api/askhr-bot/messages/%3Cm1%40mail.example.com%3E/retry?mailbox=askhr")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "created"
    assert data["jira_issue_key"] == "HRD-40"


def test_retry_re_fetches_the_real_body_from_graph_instead_of_retrying_empty(test_client, monkeypatch, tmp_path):
    """Regression guard for HRD-1299/McMorris: askhr_bot_messages never
    stores the body, so retrying used to hardcode an empty description --
    silently producing a ticket with none of the original content. Retry
    must re-fetch the live message from Graph and pass its real body through.
    """
    job = _job_with_settings(tmp_path)
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO askhr_bot_messages "
            "(internet_message_id, mailbox, graph_message_id, subject, sender_email, received_at, "
            "status, jira_issue_key, error, processed_at) "
            "VALUES ('<m1@mail.example.com>', 'askhr', 'graph-1', 'Subject', 'a@example.com', "
            "'2026-09-03T11:00:00+00:00', 'failed', '', 'boom', '2026-09-03T11:01:00+00:00')"
        )
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)
    monkeypatch.setattr(job, "_azure_client", lambda: _mock_azure_with_graph_message())

    seen_messages = []

    def fake_create(mailbox, message, existing_issue_key):
        seen_messages.append(message)
        return "created", "HRD-40", None

    monkeypatch.setattr(job, "_create_or_attach_ticket", fake_create)

    resp = test_client.post("/api/askhr-bot/messages/%3Cm1%40mail.example.com%3E/retry?mailbox=askhr")
    assert resp.status_code == 200
    assert seen_messages[0]["body"] == "the real message body"
    assert seen_messages[0]["sender_name"] == "A Sender"


def test_retry_targets_the_named_mailbox_when_both_have_the_same_message_id(test_client, monkeypatch, tmp_path):
    """The same email can be addressed to both AskHR@ and Benefits@, so a
    Message-ID alone doesn't identify a row. The retry route must act on the
    row for the mailbox the caller named, never the other mailbox's copy.
    """
    job = _job_with_settings(tmp_path)
    with job._sqlite_conn() as conn:
        for mailbox, graph_id, issue_key in (("askhr", "graph-a", "HRD-50"), ("benefits", "graph-b", "HRD-51")):
            conn.execute(
                "INSERT INTO askhr_bot_messages "
                "(internet_message_id, mailbox, graph_message_id, subject, sender_email, received_at, "
                "status, jira_issue_key, error, processed_at) "
                "VALUES ('<dual@mail.example.com>', ?, ?, 'Subject', 'a@example.com', "
                "'2026-09-03T11:00:00+00:00', 'failed', ?, 'attachment failed: boom', '2026-09-03T11:01:00+00:00')",
                (mailbox, graph_id, issue_key),
            )
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)

    def fake_graph_request(method, path, params=None):
        graph_id = "graph-a" if "graph-a" in path else "graph-b"
        return {
            "id": graph_id,
            "internetMessageId": "<dual@mail.example.com>",
            "subject": "Subject",
            "receivedDateTime": "2026-09-03T11:00:00Z",
            "from": {"emailAddress": {"address": "a@example.com", "name": "A"}},
            "body": {"contentType": "text", "content": "body"},
        }

    mock_azure = MagicMock()
    mock_azure.graph_request.side_effect = fake_graph_request
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    seen: list[tuple[str, str, str | None]] = []

    def fake_create(mailbox, message, existing_issue_key):
        seen.append((mailbox, message["graph_message_id"], existing_issue_key))
        return "created", existing_issue_key, None

    monkeypatch.setattr(job, "_create_or_attach_ticket", fake_create)

    resp = test_client.post("/api/askhr-bot/messages/%3Cdual%40mail.example.com%3E/retry?mailbox=benefits")
    assert resp.status_code == 200
    assert resp.json()["mailbox"] == "benefits"
    assert resp.json()["jira_issue_key"] == "HRD-51"
    # Acted on the benefits row's Graph message, not the AskHR copy's.
    assert seen == [("benefits", "graph-b", "HRD-51")]

    # The AskHR row is untouched by the benefits retry.
    with job._sqlite_conn() as conn:
        rows = {
            r["mailbox"]: (r["status"], r["jira_issue_key"])
            for r in conn.execute(
                "SELECT mailbox, status, jira_issue_key FROM askhr_bot_messages "
                "WHERE internet_message_id = '<dual@mail.example.com>'"
            )
        }
    assert rows["askhr"] == ("failed", "HRD-50")
    assert rows["benefits"] == ("created", "HRD-51")


def test_retry_requires_a_mailbox(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path)
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)

    resp = test_client.post("/api/askhr-bot/messages/%3Cm1%40mail.example.com%3E/retry")
    assert resp.status_code == 422

    resp = test_client.post("/api/askhr-bot/messages/%3Cm1%40mail.example.com%3E/retry?mailbox=nope")
    assert resp.status_code == 400


def test_retry_records_failure_when_create_or_attach_raises(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path)
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO askhr_bot_messages "
            "(internet_message_id, mailbox, graph_message_id, subject, sender_email, received_at, "
            "status, jira_issue_key, error, processed_at) "
            "VALUES ('<m2@mail.example.com>', 'askhr', 'graph-2', 'Subject', 'a@example.com', "
            "'2026-09-03T11:00:00+00:00', 'failed', 'HRD-41', 'attachment failed: boom', '2026-09-03T11:01:00+00:00')"
        )
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)

    def _raise(mailbox, message, existing_issue_key):
        raise RuntimeError("jira api hiccup")

    monkeypatch.setattr(job, "_create_or_attach_ticket", _raise)
    monkeypatch.setattr(
        job, "_azure_client",
        lambda: _mock_azure_with_graph_message(id="graph-2", internetMessageId="<m2@mail.example.com>"),
    )

    resp = test_client.post("/api/askhr-bot/messages/%3Cm2%40mail.example.com%3E/retry?mailbox=askhr")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["jira_issue_key"] == "HRD-41"
    assert "jira api hiccup" in data["error"]

    with job._sqlite_conn() as conn:
        row = conn.execute(
            "SELECT status, jira_issue_key, error FROM askhr_bot_messages WHERE internet_message_id = ?",
            ("<m2@mail.example.com>",),
        ).fetchone()
    assert row["status"] == "failed"
    assert row["jira_issue_key"] == "HRD-41"
    assert "jira api hiccup" in row["error"]
