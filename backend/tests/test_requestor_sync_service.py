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

import requestor_sync_service as requestor_sync_module
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
        self.search_user_rows: list[dict] = []
        self.customer_rows: list[dict] = []

    def get_service_desk_id_for_project(self, project_key: str) -> str:
        return "desk-1"

    def search_users(self, query: str, max_results: int = 50) -> list[dict]:
        return self.search_user_rows

    def get_service_desk_customers(self, service_desk_id: str, *, query: str = "") -> list[dict]:
        return self.customer_rows

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


def test_reconcile_issue_matches_occ_creator_name_to_single_entra_user(tmp_path):
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    client = FakeJiraClient()
    service = RequestorSyncService(store=store, client=client)

    service.refresh_directory_emails(
        [
            {
                "id": "user-1",
                "display_name": "Wayne Berry",
                "mail": "wayne.berry@librasolutionsgroup.com",
                "primary_mail": "wayne.berry@librasolutionsgroup.com",
                "principal_name": "wayne.berry@librasolutionsgroup.com",
                "email_aliases": ["wayne.berry@keyhealth.net"],
                "account_class": "user",
            }
        ]
    )
    issue = _issue("OCC Ticket Created By: Wayne Berry | OCC Ticket ID: LIBRA-SR-1")

    result = service.reconcile_issue(issue, force=True)

    assert result["updated"] is True
    assert result["requestor_identity"]["match_source"] == "occ_creator_name"
    assert result["requestor_identity"]["jira_status"] == "created_jira_customer"
    assert client.created_customers == [("wayne.berry@librasolutionsgroup.com", "Wayne Berry")]
    assert client.reporter_updates == [("OIT-123", "acct-grace")]
    assert issue["fields"]["reporter"]["emailAddress"] == "wayne.berry@librasolutionsgroup.com"


def test_reconcile_issue_uses_domain_priority_for_occ_name_matches(tmp_path):
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    client = FakeJiraClient()
    service = RequestorSyncService(store=store, client=client)

    service.refresh_directory_emails(
        [
            {
                "id": "user-1",
                "display_name": "Wayne Berry",
                "mail": "wayne.berry@keyhealth.net",
                "primary_mail": "wayne.berry@keyhealth.net",
                "principal_name": "wayne.berry@keyhealth.net",
                "email_aliases": [],
                "account_class": "user",
            },
            {
                "id": "user-2",
                "display_name": "Wayne Berry",
                "mail": "wayne.berry@librasolutionsgroup.com",
                "primary_mail": "wayne.berry@librasolutionsgroup.com",
                "principal_name": "wayne.berry@librasolutionsgroup.com",
                "email_aliases": [],
                "account_class": "user",
            },
        ]
    )
    issue = _issue("OCC Ticket Created By: Wayne Berry | OCC Ticket ID: LIBRA-SR-1")

    result = service.reconcile_issue(issue, force=True)

    assert result["updated"] is True
    assert client.created_customers == [("wayne.berry@librasolutionsgroup.com", "Wayne Berry")]
    assert result["message"].startswith("Matched from OCC creator name")


def test_reconcile_issue_leaves_reporter_when_occ_name_has_no_directory_match(tmp_path):
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    service = RequestorSyncService(store=store, client=FakeJiraClient())

    issue = _issue("OCC Ticket Created By: Wayne Berry | OCC Ticket ID: LIBRA-SR-1")
    result = service.reconcile_issue(issue, force=True)

    assert result["updated"] is False
    assert result["requestor_identity"]["jira_status"] == "no_name_match"
    assert result["requestor_identity"]["match_source"] == "occ_creator_name"
    assert "left unchanged" in result["message"]


def test_reconcile_issue_leaves_reporter_when_occ_name_remains_ambiguous(tmp_path):
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    service = RequestorSyncService(store=store, client=FakeJiraClient())

    service.refresh_directory_emails(
        [
            {
                "id": "user-1",
                "display_name": "Wayne Berry",
                "mail": "wayne.berry@librasolutionsgroup.com",
                "primary_mail": "wayne.berry@librasolutionsgroup.com",
                "principal_name": "wayne.berry@librasolutionsgroup.com",
                "email_aliases": [],
                "account_class": "user",
            },
            {
                "id": "user-2",
                "display_name": "Wayne Berry",
                "mail": "wayne.alt@librasolutionsgroup.com",
                "primary_mail": "wayne.alt@librasolutionsgroup.com",
                "principal_name": "wayne.alt@librasolutionsgroup.com",
                "email_aliases": [],
                "account_class": "user",
            },
        ]
    )
    issue = _issue("OCC Ticket Created By: Wayne Berry | OCC Ticket ID: LIBRA-SR-1")

    result = service.reconcile_issue(issue, force=True)

    assert result["updated"] is False
    assert result["requestor_identity"]["jira_status"] == "ambiguous_name_match"
    assert result["requestor_identity"]["match_source"] == "occ_creator_name"
    assert "Use the reporter search" in result["message"]


def test_reconcile_issue_prefers_extracted_email_over_occ_creator_name(tmp_path):
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
            },
            {
                "id": "user-2",
                "display_name": "Wayne Berry",
                "mail": "wayne.berry@librasolutionsgroup.com",
                "primary_mail": "wayne.berry@librasolutionsgroup.com",
                "principal_name": "wayne.berry@librasolutionsgroup.com",
                "email_aliases": [],
                "account_class": "user",
            },
        ]
    )
    issue = _issue(
        "Reporter Email: grace.hopper@example.com | OCC Ticket Created By: Wayne Berry | OCC Ticket ID: LIBRA-SR-1"
    )

    result = service.reconcile_issue(issue, force=True)

    assert result["updated"] is True
    assert result["requestor_identity"]["match_source"] == "reporter_email"
    assert client.created_customers == [("grace.hopper@example.com", "Grace Hopper")]


def test_reconcile_issue_reuses_existing_jira_customer_without_creating_duplicate(tmp_path):
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
    client.customer_rows = [
        {
            "accountId": "acct-existing",
            "displayName": "Grace Hopper",
            "emailAddress": "grace.hopper@example.com",
        }
    ]
    issue = _issue("Reporter Email: grace.hopper@example.com")

    result = service.reconcile_issue(issue, force=True)

    assert result["updated"] is True
    assert result["requestor_identity"]["jira_status"] == "updated_reporter"
    assert client.created_customers == []
    assert client.service_desk_adds == [("desk-1", ["acct-existing"])]
    assert client.reporter_updates == [("OIT-123", "acct-existing")]
    assert issue["fields"]["reporter"]["emailAddress"] == "grace.hopper@example.com"


def test_reconcile_issue_ignores_blocklisted_extracted_email(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requestor_sync_module,
        "REQUESTOR_IGNORED_EMAILS",
        [" MailTo:EmailQuarantine@LibraSolutionsGroup.com "],
    )
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    client = FakeJiraClient()
    service = RequestorSyncService(store=store, client=client)

    issue = _issue("Reporter Email: <EmailQuarantine@LibraSolutionsGroup.com>")

    result = service.reconcile_issue(issue, force=True)

    assert result["updated"] is False
    assert result["requestor_identity"]["jira_status"] == "ignored_requestor_email"
    assert result["requestor_identity"]["extracted_email"] == "emailquarantine@librasolutionsgroup.com"
    assert result["requestor_identity"]["directory_match"] is False
    assert client.created_customers == []
    assert client.service_desk_adds == []
    assert client.reporter_updates == []
    assert "ignored requestor list" in result["message"]


def test_get_requestor_identity_marks_ignored_email_without_syncing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requestor_sync_module,
        "REQUESTOR_IGNORED_EMAILS",
        ["emailquarantine@librasolutionsgroup.com"],
    )
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    service = RequestorSyncService(store=store, client=FakeJiraClient())

    identity = service.get_requestor_identity(
        _issue("Reporter Email: emailquarantine@librasolutionsgroup.com")
    )

    assert identity["jira_status"] == "ignored_requestor_email"
    assert identity["directory_match"] is False
    assert "ignored requestor list" in identity["message"]


def test_get_requestor_identity_prefers_ignored_email_status_over_old_synced_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requestor_sync_module,
        "REQUESTOR_IGNORED_EMAILS",
        ["emailquarantine@librasolutionsgroup.com"],
    )
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    service = RequestorSyncService(store=store, client=FakeJiraClient())
    store.upsert_requestor_link(
        email_key="emailquarantine@librasolutionsgroup.com",
        ticket_key="OIT-123",
        extracted_email="emailquarantine@librasolutionsgroup.com",
        canonical_email="emailquarantine@librasolutionsgroup.com",
        jira_account_id="acct-old",
        jira_display_name="Email Quarantine",
        match_source="reporter_email",
        sync_status="updated_reporter",
        message="Reporter synced to Email Quarantine.",
    )

    identity = service.get_requestor_identity(
        _issue("Reporter Email: emailquarantine@librasolutionsgroup.com")
    )

    assert identity["jira_status"] == "ignored_requestor_email"
    assert identity["jira_account_id"] == ""
    assert "ignored requestor list" in identity["message"]


def test_get_requestor_identity_marks_occ_name_as_ignored_when_only_ignored_candidates_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requestor_sync_module,
        "REQUESTOR_IGNORED_EMAILS",
        ["emailquarantine@librasolutionsgroup.com"],
    )
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    service = RequestorSyncService(store=store, client=FakeJiraClient())
    service.refresh_directory_emails(
        [
            {
                "id": "user-1",
                "display_name": "Email Quarantine",
                "mail": "emailquarantine@librasolutionsgroup.com",
                "primary_mail": "emailquarantine@librasolutionsgroup.com",
                "principal_name": "emailquarantine@librasolutionsgroup.com",
                "email_aliases": [],
                "account_class": "shared_mailbox",
            }
        ]
    )

    identity = service.get_requestor_identity(
        _issue("OCC Ticket Created By: Email Quarantine | OCC Ticket ID: LIBRA-SR-1")
    )

    assert identity["jira_status"] == "ignored_requestor_email"
    assert identity["match_source"] == "occ_creator_name"
    assert identity["directory_match"] is False
    assert "ignored requestor list" in identity["message"]


def test_reconcile_issue_occ_name_skips_ignored_candidate_and_uses_valid_match(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requestor_sync_module,
        "REQUESTOR_IGNORED_EMAILS",
        ["emailquarantine@librasolutionsgroup.com"],
    )
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    client = FakeJiraClient()
    service = RequestorSyncService(store=store, client=client)

    service.refresh_directory_emails(
        [
            {
                "id": "user-1",
                "display_name": "Email Quarantine",
                "mail": "emailquarantine@librasolutionsgroup.com",
                "primary_mail": "emailquarantine@librasolutionsgroup.com",
                "principal_name": "emailquarantine@librasolutionsgroup.com",
                "email_aliases": [],
                "account_class": "shared_mailbox",
            },
            {
                "id": "user-2",
                "display_name": "Email Quarantine",
                "mail": "emailquarantine@keyhealth.net",
                "primary_mail": "emailquarantine@keyhealth.net",
                "principal_name": "emailquarantine@keyhealth.net",
                "email_aliases": [],
                "account_class": "shared_mailbox",
            },
        ]
    )
    issue = _issue("OCC Ticket Created By: Email Quarantine | OCC Ticket ID: LIBRA-SR-1")

    result = service.reconcile_issue(issue, force=True)

    assert result["updated"] is True
    assert result["requestor_identity"]["match_source"] == "occ_creator_name"
    assert client.created_customers == [("emailquarantine@keyhealth.net", "Email Quarantine")]


def test_reconcile_issue_occ_name_marks_ignored_when_only_ignored_candidates_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requestor_sync_module,
        "REQUESTOR_IGNORED_EMAILS",
        ["emailquarantine@librasolutionsgroup.com"],
    )
    store = RequestorSyncStore(str(tmp_path / "requestor_sync.db"))
    client = FakeJiraClient()
    service = RequestorSyncService(store=store, client=client)

    service.refresh_directory_emails(
        [
            {
                "id": "user-1",
                "display_name": "Email Quarantine",
                "mail": "emailquarantine@librasolutionsgroup.com",
                "primary_mail": "emailquarantine@librasolutionsgroup.com",
                "principal_name": "emailquarantine@librasolutionsgroup.com",
                "email_aliases": [],
                "account_class": "shared_mailbox",
            }
        ]
    )
    issue = _issue("OCC Ticket Created By: Email Quarantine | OCC Ticket ID: LIBRA-SR-1")

    result = service.reconcile_issue(issue, force=True)

    assert result["updated"] is False
    assert result["requestor_identity"]["jira_status"] == "ignored_requestor_email"
    assert result["requestor_identity"]["match_source"] == "occ_creator_name"
    assert client.created_customers == []
    assert client.reporter_updates == []
    assert "ignored requestor list" in result["message"]
