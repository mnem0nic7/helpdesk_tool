"""Focused tests for Jira helpers."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import requests

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


def test_get_service_desk_customers_sends_experimental_opt_in_header():
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"values": [], "isLastPage": True}
    client.session.get = MagicMock(return_value=response)  # type: ignore[method-assign]

    customers = client.get_service_desk_customers("desk-1", query="grace@example.com")

    assert customers == []
    headers = client.session.get.call_args.kwargs["headers"]
    assert headers["X-ExperimentalApi"] == "opt-in"


def test_create_customer_does_not_send_experimental_header():
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"accountId": "acct-1"}
    client.session.post = MagicMock(return_value=response)  # type: ignore[method-assign]

    client.create_customer(email="grace@example.com", display_name="Grace Hopper")

    assert client.session.post.call_args.kwargs.get("headers") is None


def test_add_customers_to_service_desk_does_not_send_experimental_header():
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")
    response = MagicMock()
    response.ok = True
    client.session.post = MagicMock(return_value=response)  # type: ignore[method-assign]

    client.add_customers_to_service_desk("desk-1", ["acct-1"])

    assert client.session.post.call_args.kwargs.get("headers") is None


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


def test_get_request_comments_falls_back_to_issue_comments_on_404():
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")

    class _Response:
        def __init__(self, *, status_code: int, payload: dict | None = None) -> None:
            self.status_code = status_code
            self.ok = status_code < 400
            self.reason = "Not Found" if status_code == 404 else "OK"
            self._payload = payload or {}
            self.text = ""
            self.request = MagicMock()
            self.headers = {}

        def json(self) -> dict:
            return self._payload

    session = MagicMock()
    session.get.side_effect = [
        _Response(status_code=404),
        _Response(
            status_code=200,
            payload={
                "comments": [
                    {
                        "id": "1",
                        "created": "2026-03-01T08:00:00+00:00",
                        "author": {"accountId": "acc-agent"},
                        "jsdPublic": True,
                    },
                    {
                        "id": "2",
                        "created": "2026-03-01T09:00:00+00:00",
                        "author": {"accountId": "acc-agent"},
                        "jsdPublic": False,
                    },
                ],
                "startAt": 0,
                "maxResults": 100,
                "total": 2,
            },
        ),
    ]
    client._thread_local.session = session

    comments = client.get_request_comments("OIT-123")

    assert [comment["id"] for comment in comments] == ["1", "2"]
    assert comments[0]["public"] is True
    assert comments[1]["public"] is False


def test_get_request_comments_raises_non_404_errors():
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")

    response = MagicMock()
    response.status_code = 500
    response.ok = False
    response.reason = "Server Error"
    response.request = MagicMock()
    response.text = "boom"
    response.headers = {}
    session = MagicMock()
    session.get.return_value = response
    client._thread_local.session = session

    try:
        client.get_request_comments("OIT-123")
    except requests.HTTPError:
        pass
    else:
        raise AssertionError("Expected HTTPError for non-404 comment failure")
