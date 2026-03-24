"""Focused tests for Jira user matching helpers."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from jira_client import JiraClient


def test_find_user_account_id_returns_exact_unique_match(monkeypatch):
    client = JiraClient()
    monkeypatch.setattr(
        client,
        "search_users",
        lambda query: [
            {"accountId": "acct-1", "displayName": "Raza Abidi", "active": True},
            {"accountId": "acct-2", "displayName": "Raza Ali Abidi", "active": True},
        ],
    )

    assert client.find_user_account_id("Raza Abidi") == "acct-1"


def test_find_user_account_id_allows_single_middle_name_match(monkeypatch):
    client = JiraClient()
    monkeypatch.setattr(
        client,
        "search_users",
        lambda query: [
            {"accountId": "acct-2", "displayName": "Raza Ali Abidi", "active": True},
        ],
    )

    assert client.find_user_account_id("Raza Abidi") == "acct-2"


def test_find_user_account_id_rejects_ambiguous_middle_name_matches(monkeypatch):
    client = JiraClient()
    monkeypatch.setattr(
        client,
        "search_users",
        lambda query: [
            {"accountId": "acct-2", "displayName": "Raza Ali Abidi", "active": True},
            {"accountId": "acct-3", "displayName": "Raza Ahmad Abidi", "active": True},
        ],
    )

    assert client.find_user_account_id("Raza Abidi") is None


def test_find_user_account_id_does_not_match_extra_first_or_last_names(monkeypatch):
    client = JiraClient()
    monkeypatch.setattr(
        client,
        "search_users",
        lambda query: [
            {"accountId": "acct-2", "displayName": "Mohammed Raza Abidi", "active": True},
            {"accountId": "acct-3", "displayName": "Raza Abidi Khan", "active": True},
        ],
    )

    assert client.find_user_account_id("Raza Abidi") is None


def test_create_issue_posts_expected_payload():
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")
    response = MagicMock()
    response.json.return_value = {"id": "10001", "key": "OIT-999"}
    response.ok = True
    client.session.post = MagicMock(return_value=response)  # type: ignore[method-assign]

    created = client.create_issue(
        project_key="oit",
        summary="Follow up on Azure recommendation",
        issue_type="Task",
        description="Line one\n\nLine two",
        labels=["azure-finops", "compute"],
    )

    assert created["key"] == "OIT-999"
    url = client.session.post.call_args.args[0]
    payload = client.session.post.call_args.kwargs["json"]
    assert url == "https://example.atlassian.net/rest/api/3/issue"
    assert payload["fields"]["project"]["key"] == "OIT"
    assert payload["fields"]["issuetype"]["name"] == "Task"
    assert payload["fields"]["summary"] == "Follow up on Azure recommendation"
    assert payload["fields"]["labels"] == ["azure-finops", "compute"]
    assert payload["fields"]["description"]["type"] == "doc"


def test_get_issue_changelog_all_paginates(monkeypatch):
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")

    calls: list[int] = []

    def fake_page(key: str, *, start_at: int = 0, max_results: int = 100):
        calls.append(start_at)
        if start_at == 0:
            return {
                "values": [{"id": "1"}, {"id": "2"}],
                "startAt": 0,
                "maxResults": 2,
                "total": 3,
            }
        return {
            "values": [{"id": "3"}],
            "startAt": 2,
            "maxResults": 2,
            "total": 3,
        }

    monkeypatch.setattr(client, "get_issue_changelog_page", fake_page)

    histories = client.get_issue_changelog_all("OIT-123")

    assert [item["id"] for item in histories] == ["1", "2", "3"]
    assert calls == [0, 2]


def test_get_thread_session_is_isolated_per_thread():
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")

    main_session = client._get_thread_session()
    worker_sessions: list[object] = []

    def _worker() -> None:
        worker_sessions.append(client._get_thread_session())

    first = threading.Thread(target=_worker)
    second = threading.Thread(target=_worker)
    first.start()
    second.start()
    first.join()
    second.join()

    assert len(worker_sessions) == 2
    assert worker_sessions[0] is not main_session
    assert worker_sessions[1] is not main_session
    assert worker_sessions[0] is not worker_sessions[1]
