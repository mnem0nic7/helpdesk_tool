"""Focused tests for Jira user matching helpers."""

from __future__ import annotations

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
