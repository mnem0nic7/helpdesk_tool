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


def test_find_user_by_email_prefers_exact_email_match(monkeypatch):
    client = JiraClient()
    monkeypatch.setattr(
        client,
        "search_users",
        lambda query: [
            {"accountId": "acct-1", "emailAddress": "jane@example.com", "accountType": "atlassian"},
            {"accountId": "acct-2", "emailAddress": "jane.other@example.com", "accountType": "atlassian"},
        ],
    )

    user = client.find_user_by_email("Jane@Example.com")
    assert user is not None
    assert user["accountId"] == "acct-1"


def test_find_user_by_email_accepts_single_candidate_with_hidden_email(monkeypatch):
    client = JiraClient()
    monkeypatch.setattr(
        client,
        "search_users",
        lambda query: [
            {"accountId": "acct-1", "emailAddress": "", "accountType": "atlassian"},
        ],
    )

    user = client.find_user_by_email("jane@example.com")
    assert user is not None
    assert user["accountId"] == "acct-1"


def test_find_user_by_email_rejects_ambiguous_hidden_email_candidates(monkeypatch):
    client = JiraClient()
    monkeypatch.setattr(
        client,
        "search_users",
        lambda query: [
            {"accountId": "acct-1", "emailAddress": "", "accountType": "atlassian"},
            {"accountId": "acct-2", "emailAddress": "", "accountType": "atlassian"},
        ],
    )

    assert client.find_user_by_email("jane@example.com") is None


def test_find_user_by_email_ignores_app_and_customer_accounts(monkeypatch):
    client = JiraClient()
    monkeypatch.setattr(
        client,
        "search_users",
        lambda query: [
            {"accountId": "acct-app", "emailAddress": "", "accountType": "app"},
            {"accountId": "acct-1", "emailAddress": "jane@example.com", "accountType": "atlassian"},
        ],
    )

    user = client.find_user_by_email("jane@example.com")
    assert user is not None
    assert user["accountId"] == "acct-1"


def test_find_user_by_email_returns_none_for_blank_input():
    client = JiraClient()
    assert client.find_user_by_email("") is None
    assert client.find_user_by_email("   ") is None


def test_deactivate_user_account_requires_admin_api_key(monkeypatch):
    import jira_client as jc

    monkeypatch.setattr(jc, "ATLASSIAN_ADMIN_API_KEY", "")
    client = JiraClient()

    try:
        client.deactivate_user_account("acct-1")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "ATLASSIAN_ADMIN_API_KEY" in str(exc)


def test_deactivate_user_account_posts_to_lifecycle_disable(monkeypatch):
    import jira_client as jc

    monkeypatch.setattr(jc, "ATLASSIAN_ADMIN_API_KEY", "admin-key")
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(jc.requests, "post", fake_post)
    client = JiraClient()
    client.deactivate_user_account("acct-1", message="Offboarded")

    assert captured["url"] == "https://api.atlassian.com/users/acct-1/manage/lifecycle/disable"
    assert captured["headers"]["Authorization"] == "Bearer admin-key"
    assert captured["json"] == {"message": "Offboarded"}


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


def test_create_request_posts_raise_on_behalf_of_payload():
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"issueKey": "HRD-1"}
    client.session.post = MagicMock(return_value=response)  # type: ignore[method-assign]

    result = client.create_request(
        service_desk_id="73",
        request_type_id="420",
        raise_on_behalf_of="qm:tenant:askhr-account-id",
        summary="Help with benefits",
        description="Originally sent by: Jane Doe <jane@example.com> on 2026-09-03 09:00\n\nBody text",
    )

    assert result["issueKey"] == "HRD-1"
    url = client.session.post.call_args.args[0]
    payload = client.session.post.call_args.kwargs["json"]
    assert url == "https://example.atlassian.net/rest/servicedeskapi/request"
    assert payload["serviceDeskId"] == "73"
    assert payload["requestTypeId"] == "420"
    assert payload["raiseOnBehalfOf"] == "qm:tenant:askhr-account-id"
    assert payload["requestFieldValues"]["summary"] == "Help with benefits"


def test_create_issue_with_reporter_posts_classic_issue_payload():
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"key": "HRD-2"}
    client.session.post = MagicMock(return_value=response)  # type: ignore[method-assign]

    result = client.create_issue_with_reporter(
        project_key="hrd",
        issue_type="Emailed request",
        summary="Help with benefits",
        description="Body text",
        reporter_account_id="qm:tenant:askhr-account-id",
    )

    assert result["key"] == "HRD-2"
    url = client.session.post.call_args.args[0]
    payload = client.session.post.call_args.kwargs["json"]
    assert url == "https://example.atlassian.net/rest/api/3/issue"
    assert payload["fields"]["project"]["key"] == "HRD"
    assert payload["fields"]["issuetype"]["name"] == "Emailed request"
    assert payload["fields"]["reporter"]["id"] == "qm:tenant:askhr-account-id"


def test_find_issue_by_internet_message_id_returns_key_when_found():
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"issues": [{"key": "HRD-3"}]}
    client.session.post = MagicMock(return_value=response)  # type: ignore[method-assign]

    key = client.find_issue_by_internet_message_id("<abc123@mail.example.com>", project_key="HRD")

    assert key == "HRD-3"
    url = client.session.post.call_args.args[0]
    payload = client.session.post.call_args.kwargs["json"]
    assert url == "https://example.atlassian.net/rest/api/3/search/jql"
    assert "HRD" in payload["jql"]
    assert "abc123@mail.example.com" in payload["jql"]


def test_find_issue_by_internet_message_id_returns_none_when_not_found():
    client = JiraClient(base_url="https://example.atlassian.net", email="user@example.com", token="token")
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"issues": []}
    client.session.post = MagicMock(return_value=response)  # type: ignore[method-assign]

    assert client.find_issue_by_internet_message_id("<missing@mail.example.com>", project_key="HRD") is None
