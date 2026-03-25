"""Tests for Office 365 requestor mirroring and Jira customer reconciliation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATA_DIR", str(Path(__file__).resolve().parent / ".tmp_requestor"))
os.environ.setdefault("JIRA_EMAIL", "test@example.com")
os.environ.setdefault("JIRA_API_TOKEN", "test-token")
os.environ.setdefault("JIRA_BASE_URL", "https://example.atlassian.net")

from requestor_sync_service import RequestorSyncService
from requestor_sync_store import RequestorSyncStore


def _issue(description: str, *, reporter: dict | None = None) -> dict:
    return {
        "key": "OIT-123",
        "fields": {
            "project": {"key": "OIT"},
            "description": {
                "version": 1,
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": description}]},
                ],
            },
            "reporter": reporter or {"displayName": "OSIJIRAOCC", "accountId": "acct-occ"},
            "status": {"name": "Open", "statusCategory": {"name": "To Do"}},
        },
    }


class FakeJiraClient:
    def __init__(self) -> None:
        self.created_customers: list[tuple[str, str]] = []
        self.service_desk_adds: list[tuple[str, list[str]]] = []
        self.reporter_updates: list[tuple[str, str]] = []

    def get_service_desk_id_for_project(self, project_key: str) -> str:
        return "desk-1"

    def search_users(self, query: str, max_results: int = 50) -> list[dict]:
        return []

    def get_service_desk_customers(self, service_desk_id: str, *, query: str = "") -> list[dict]:
        return []

    def create_customer(self, *, email: str, display_name: str, strict_conflict_status_code: bool = False) -> dict:
        self.created_customers.append((email, display_name))
        return {
            "accountId": "acct-grace",
            "displayName": display_name,
            "emailAddress": email,
        }

    def add_customers_to_service_desk(self, service_desk_id: str, account_ids: list[str]) -> None:
        self.service_desk_adds.append((service_desk_id, account_ids))

    def update_reporter(self, key: str, account_id: str) -> None:
        self.reporter_updates.append((key, account_id))


def test_refresh_directory_emails_indexes_mail_upn_and_proxy_aliases(tmp_path):
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    service = RequestorSyncService(store=store, client=FakeJiraClient())

    count = service.refresh_directory_emails(
        [
            {
                "id": "user-1",
                "display_name": "Grace Hopper",
                "mail": "Grace.Hopper@example.com",
                "primary_mail": "Grace.Hopper@example.com",
                "principal_name": "ghopper@example.onmicrosoft.com",
                "email_aliases": ["g.hopper@example.com", "helpdesk@example.com"],
                "account_class": "shared_mailbox",
            }
        ]
    )

    assert count == 5
    mail_match = store.get_directory_matches("grace.hopper@example.com")
    alias_match = store.get_directory_matches("helpdesk@example.com")
    upn_match = store.get_directory_matches("ghopper@example.onmicrosoft.com")

    assert mail_match[0]["canonical_email"] == "grace.hopper@example.com"
    assert alias_match[0]["account_class"] == "shared_mailbox"
    assert upn_match[0]["source_kind"] == "upn"


def test_extract_requestor_identity_prefers_real_reporter_email(tmp_path):
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    service = RequestorSyncService(store=store, client=FakeJiraClient())
    service.integration_reporter_names = lambda: {"osijiraocc"}  # type: ignore[method-assign]

    extracted = service.extract_requestor_identity(
        _issue(
            "Reporter Email: ignored@example.com",
            reporter={
                "displayName": "Grace Hopper",
                "accountId": "acct-grace",
                "emailAddress": "Grace.Hopper@example.com",
            },
        )
    )

    assert extracted == {
        "email": "grace.hopper@example.com",
        "source": "reporter",
        "display_name": "Grace Hopper",
        "reporter_hint": "",
    }


def test_extract_requestor_identity_parses_known_email_markers(tmp_path):
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    service = RequestorSyncService(store=store, client=FakeJiraClient())

    reporter_email = service.extract_requestor_identity(
        _issue("Reporter Name: Grace Hopper\nReporter Email: <Grace.Hopper@example.com>")
    )
    email_address = service.extract_requestor_identity(
        _issue("Full name of user: Grace Hopper\nEmail address: grace.hopper@example.com")
    )
    from_header = service.extract_requestor_identity(
        _issue("From: Grace Hopper <grace.hopper@example.com>")
    )
    occ_hint_only = service.extract_requestor_identity(
        _issue("OCC Ticket Created By: Grace Hopper | OCC Ticket ID: LIBRA-SR-1")
    )

    assert reporter_email["email"] == "grace.hopper@example.com"
    assert reporter_email["source"] == "reporter_email"
    assert email_address["source"] == "email_address"
    assert from_header["source"] == "from_header"
    assert occ_hint_only["email"] == ""
    assert occ_hint_only["reporter_hint"] == "Grace Hopper"


def test_reconcile_issue_creates_customer_and_updates_reporter(tmp_path):
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    client = FakeJiraClient()
    service = RequestorSyncService(store=store, client=client)

    service.refresh_directory_emails(
        [
            {
                "id": "user-1",
                "display_name": "Grace Hopper",
                "mail": "grace.hopper@example.com",
                "primary_mail": "grace.hopper@example.com",
                "principal_name": "grace.hopper@example.com",
                "email_aliases": [],
                "account_class": "user",
            }
        ]
    )
    issue = _issue("Reporter Email: grace.hopper@example.com")

    result = service.reconcile_issue(issue, force=True)

    assert result["updated"] is True
    assert result["requestor_identity"]["jira_status"] == "created_jira_customer"
    assert client.created_customers == [("grace.hopper@example.com", "Grace Hopper")]
    assert client.service_desk_adds == [("desk-1", ["acct-grace"])]
    assert client.reporter_updates == [("OIT-123", "acct-grace")]
    assert issue["fields"]["reporter"]["displayName"] == "Grace Hopper"
    assert issue["fields"]["reporter"]["emailAddress"] == "grace.hopper@example.com"
