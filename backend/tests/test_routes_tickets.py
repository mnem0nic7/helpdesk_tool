"""Tests for ticket routes and the _match filter function (~19 tests)."""

from __future__ import annotations

from typing import Any

import pytest
import requests
from unittest.mock import MagicMock


# ===== Direct _match() tests =====

from routes_tickets import _match


def _issue(
    status: str = "Open",
    priority: str = "Medium",
    assignee: str | None = "Alice",
    issue_type: str = "[System] Service request",
    summary: str = "Test ticket",
    key: str = "OIT-1",
    created: str = "2026-02-15T10:00:00+00:00",
    updated: str = "2026-03-01T10:00:00+00:00",
    status_category: str = "To Do",
    labels: list[str] | None = None,
    description: str | None = None,
    request_type: str | None = None,
    work_category: str | None = None,
) -> dict[str, Any]:
    """Build a minimal issue for _match testing."""
    assignee_obj = {"displayName": assignee} if assignee else None
    issue = {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status, "statusCategory": {"name": status_category}},
            "priority": {"name": priority},
            "assignee": assignee_obj,
            "issuetype": {"name": issue_type},
            "created": created,
            "updated": updated,
            "labels": labels or [],
            "description": description,
        },
    }

    if request_type:
        issue["fields"]["customfield_10010"] = {"requestType": {"name": request_type}}
    if work_category:
        issue["fields"]["customfield_11239"] = work_category
    return issue


class TestMatch:
    def test_no_filters(self):
        assert _match(_issue()) is True

    def test_status_match(self):
        assert _match(_issue(status="Open"), status="Open") is True

    def test_status_mismatch(self):
        assert _match(_issue(status="Open"), status="Closed") is False

    def test_priority_match(self):
        assert _match(_issue(priority="High"), priority="High") is True

    def test_priority_mismatch(self):
        assert _match(_issue(priority="High"), priority="Low") is False

    def test_assignee_match(self):
        assert _match(_issue(assignee="Alice"), assignee="Alice") is True

    def test_assignee_unassigned(self):
        assert _match(_issue(assignee=None), assignee="unassigned") is True

    def test_assignee_unassigned_negative(self):
        assert _match(_issue(assignee="Alice"), assignee="unassigned") is False

    def test_issue_type_match(self):
        assert _match(_issue(issue_type="[System] Change"), issue_type="[System] Change") is True

    def test_search_summary(self):
        assert _match(_issue(summary="Network outage"), search="network") is True

    def test_search_key(self):
        assert _match(_issue(key="OIT-1234"), search="oit-1234") is True

    def test_search_case_insensitive(self):
        assert _match(_issue(summary="VPN Issue"), search="vpn") is True

    def test_label_match(self):
        assert _match(_issue(labels=["vip", "network"]), label="vip") is True

    def test_label_mismatch(self):
        assert _match(_issue(labels=["vip", "network"]), label="security") is False

    def test_libra_support_match(self):
        assert _match(_issue(labels=["Libra_Support", "vip"]), libra_support="libra_support") is True

    def test_non_libra_support_match(self):
        assert _match(_issue(labels=["vip", "network"]), libra_support="non_libra_support") is True

    def test_non_libra_support_excludes_labeled_ticket(self):
        assert _match(_issue(labels=["Libra_Support"]), libra_support="non_libra_support") is False

    def test_label_and_libra_support_combine(self):
        assert _match(
            _issue(labels=["Libra_Support", "vip"]),
            label="vip",
            libra_support="libra_support",
        ) is True
        assert _match(
            _issue(labels=["Libra_Support", "vip"]),
            label="network",
            libra_support="libra_support",
        ) is False

    def test_open_only(self):
        assert _match(_issue(status_category="To Do"), open_only=True) is True

    def test_open_only_excludes_done(self):
        assert _match(_issue(status_category="Done"), open_only=True) is False

    def test_stale_only_excludes_done(self):
        assert _match(
            _issue(
                status="Resolved",
                status_category="Done",
                updated="2026-02-01T10:00:00+00:00",
            ),
            stale_only=True,
        ) is False

    def test_stale_only_excludes_waiting_for_customer(self):
        assert _match(
            _issue(
                status="Waiting For Customer",
                status_category="In Progress",
                updated="2026-02-01T10:00:00+00:00",
            ),
            stale_only=True,
        ) is False

    def test_stale_only_excludes_pending(self):
        assert _match(
            _issue(
                status="Pending",
                status_category="In Progress",
                updated="2026-02-01T10:00:00+00:00",
            ),
            stale_only=True,
        ) is False

    def test_stale_only_excludes_onboarding_and_offboarding_categories(self):
        assert _match(
            _issue(
                status="Open",
                request_type="Onboard new employees",
                updated="2026-02-01T10:00:00+00:00",
            ),
            stale_only=True,
        ) is False
        assert _match(
            _issue(
                status="Open",
                work_category="Offboarding",
                updated="2026-02-01T10:00:00+00:00",
            ),
            stale_only=True,
        ) is False

    def test_created_after(self):
        assert _match(_issue(created="2026-02-20T10:00:00+00:00"), created_after="2026-02-15") is True

    def test_created_after_excludes(self):
        assert _match(_issue(created="2026-02-10T10:00:00+00:00"), created_after="2026-02-15") is False

    def test_created_before(self):
        assert _match(_issue(created="2026-02-10T10:00:00+00:00"), created_before="2026-02-15") is True

    def test_combined_filters(self):
        iss = _issue(status="Open", priority="High", assignee="Alice")
        assert _match(iss, status="Open", priority="High", assignee="Alice") is True
        assert _match(iss, status="Open", priority="Low") is False


# ===== Endpoint tests =====

class TestTicketsEndpoint:
    def test_list_no_filters(self, test_client):
        resp = test_client.get("/api/tickets")
        assert resp.status_code == 200
        data = resp.json()
        assert "tickets" in data
        assert isinstance(data["tickets"], list)

    def test_list_with_status_filter(self, test_client):
        resp = test_client.get("/api/tickets?status=In+Progress")
        assert resp.status_code == 200
        tickets = resp.json()["tickets"]
        for t in tickets:
            assert t["status"] == "In Progress"

    def test_list_with_priority_filter(self, test_client):
        resp = test_client.get("/api/tickets?priority=High")
        assert resp.status_code == 200
        tickets = resp.json()["tickets"]
        for t in tickets:
            assert t["priority"] == "High"

    def test_response_shape(self, test_client):
        resp = test_client.get("/api/tickets")
        assert resp.status_code == 200
        tickets = resp.json()["tickets"]
        if tickets:
            t = tickets[0]
            assert "key" in t
            assert "summary" in t
            assert "status" in t
            assert "priority" in t

    def test_list_with_label_filter(self, test_client):
        resp = test_client.get("/api/tickets?label=vip")
        assert resp.status_code == 200
        tickets = resp.json()["tickets"]
        assert len(tickets) == 0  # sample cache data has no non-excluded vip labels

    def test_list_with_libra_support_filter(self, test_client, mock_cache):
        libra_issue = _issue(key="OIT-L1", labels=["Libra_Support"])
        normal_issue = _issue(key="OIT-N1", labels=["vip"])
        mock_cache.get_all_issues.return_value = [libra_issue, normal_issue]
        mock_cache.get_filtered_issues.return_value = [libra_issue, normal_issue]

        resp = test_client.get("/api/tickets?libra_support=libra_support")
        assert resp.status_code == 200
        tickets = resp.json()["tickets"]
        assert [ticket["key"] for ticket in tickets] == ["OIT-L1"]

    def test_filter_options_include_labels(self, test_client, monkeypatch):
        import issue_cache
        import routes_tickets

        cache_stub = type(
            "CacheStub",
            (),
            {
                "get_all_issues": staticmethod(
                    lambda: [
                        _issue(labels=["vip", "network"]),
                        _issue(key="OIT-2", labels=["security"]),
                        {
                            "key": "OIT-3",
                            "fields": {
                                "summary": "Portal outage",
                                "status": {"name": "Open"},
                                "priority": {"name": "High"},
                                "issuetype": {"name": "[System] Service request"},
                                "labels": [],
                                "components": [{"name": "Portal"}],
                                "customfield_11239": "Identity",
                            },
                        },
                    ]
                ),
                "get_filtered_issues": staticmethod(
                    lambda: [
                        _issue(labels=["vip", "network"]),
                        _issue(key="OIT-2", labels=["security"]),
                        {
                            "key": "OIT-3",
                            "fields": {
                                "summary": "Portal outage",
                                "status": {"name": "Open"},
                                "priority": {"name": "High"},
                                "issuetype": {"name": "[System] Service request"},
                                "labels": [],
                                "components": [{"name": "Portal"}],
                                "customfield_11239": "Identity",
                            },
                        },
                    ]
                ),
            },
        )()
        monkeypatch.setattr(
            routes_tickets,
            "cache",
            cache_stub,
        )
        monkeypatch.setattr(issue_cache, "cache", cache_stub)

        resp = test_client.get("/api/filter-options")
        assert resp.status_code == 200
        assert resp.json()["labels"] == ["network", "security", "vip"]
        assert resp.json()["components"] == ["Portal"]
        assert resp.json()["work_categories"] == ["Identity"]

    def test_oasisdev_host_lists_only_oasisdev_tickets(self, test_client):
        resp = test_client.get("/api/tickets", headers={"host": "oasisdev.movedocs.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["matched_count"] == 2
        assert data["total_count"] == 2
        assert [ticket["key"] for ticket in data["tickets"]] == ["OIT-600", "OIT-500"]

    def test_refresh_visible_tickets_refreshes_current_keys(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        mock_cache.refresh_issue_keys.return_value = [issue]
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: key == "OIT-123")

        resp = test_client.post(
            "/api/tickets/refresh-visible",
            json={"keys": ["oit-123", "OIT-123", "OIT-404"]},
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "requested_count": 2,
            "visible_count": 1,
            "refreshed_count": 1,
            "refreshed_keys": ["OIT-123"],
            "skipped_keys": ["OIT-404"],
            "missing_keys": [],
        }
        mock_cache.refresh_issue_keys.assert_called_once_with(["OIT-123"])

    def test_refresh_visible_tickets_runs_requestor_reconciliation(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        mock_cache.refresh_issue_keys.return_value = [issue]
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        seen_keys: list[str] = []
        monkeypatch.setattr(
            routes_tickets.requestor_sync_service,
            "maybe_reconcile_issue",
            lambda refreshed_issue: seen_keys.append(refreshed_issue["key"]) or {
                "updated": True,
                "message": "Matched from OCC creator name and synced reporter to Raza Abidi.",
                "requestor_identity": {
                    "extracted_email": "raza@example.com",
                    "directory_match": True,
                    "jira_account_id": "acct-raza",
                    "jira_status": "updated_reporter",
                    "message": "Matched from OCC creator name and synced reporter to Raza Abidi.",
                    "match_source": "occ_creator_name",
                },
            },
        )

        resp = test_client.post("/api/tickets/refresh-visible", json={"keys": ["OIT-123"]})

        assert resp.status_code == 200
        assert seen_keys == ["OIT-123"]
        mock_cache.upsert_issue.assert_called_once_with(issue)

    def test_refresh_visible_tickets_rejects_invalid_keys(self, test_client):
        resp = test_client.post("/api/tickets/refresh-visible", json={"keys": ["not-a-jira-key"]})
        assert resp.status_code == 400
        assert "Invalid Jira key format" in resp.json()["detail"]

    def test_refresh_visible_tickets_returns_502_on_jira_failure(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        mock_cache.refresh_issue_keys.side_effect = RuntimeError("jira blew up")
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)

        resp = test_client.post("/api/tickets/refresh-visible", json={"keys": ["OIT-123"]})

        assert resp.status_code == 502
        assert resp.json()["detail"] == "Jira refresh failed. Please try again in a moment."


def _adf(text: str) -> dict[str, Any]:
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _detail_issue() -> dict[str, Any]:
    return {
        "key": "OIT-123",
        "fields": {
            "summary": "VPN login failure",
            "status": {"name": "Open", "statusCategory": {"name": "To Do"}},
            "priority": {"name": "High"},
            "assignee": {"displayName": "Alice Admin", "accountId": "acc-alice"},
            "reporter": {"displayName": "Reporter One"},
            "issuetype": {"name": "[System] Service request"},
            "resolution": None,
            "created": "2026-02-15T10:00:00+00:00",
            "updated": "2026-03-01T10:00:00+00:00",
            "resolutiondate": "",
            "description": _adf("User cannot sign in."),
            "customfield_11121": "1. Open portal\n2. Attempt login",
            "customfield_11102": {
                "requestType": {"name": "Business Application Support"},
                "_links": {
                    "agent": "https://example.atlassian.net/browse/OIT-123",
                    "web": "https://example.atlassian.net/servicedesk/customer/portal/1/OIT-123",
                },
            },
            "customfield_11239": "Identity",
            "labels": ["vip"],
            "components": [{"name": "Portal"}],
            "customfield_10700": [{"name": "Org One"}],
            "attachment": [
                {
                    "id": "9001",
                    "filename": "screenshot.png",
                    "mimeType": "image/png",
                    "size": 2048,
                    "created": "2026-03-01T09:00:00+00:00",
                    "author": {"displayName": "Alice Admin"},
                    "content": "https://example.atlassian.net/file/9001",
                    "thumbnail": "https://example.atlassian.net/thumb/9001",
                }
            ],
            "issuelinks": [
                {
                    "type": {"name": "Blocks", "outward": "blocks", "inward": "is blocked by"},
                    "outwardIssue": {
                        "key": "OIT-456",
                        "fields": {
                            "summary": "Downstream identity outage",
                            "status": {"name": "In Progress"},
                        },
                    },
                }
            ],
        },
    }


def _request_comments() -> list[dict[str, Any]]:
    return [
        {
            "id": "17",
            "author": {"displayName": "Tech One"},
            "created": {"iso8601": "2026-03-01T11:00:00+00:00"},
            "updated": {"iso8601": "2026-03-01T11:05:00+00:00"},
            "body": "Investigating now.",
            "public": False,
        }
    ]


class TestTicketDetailAndActions:
    def test_create_ticket_creates_issue_updates_fields_and_returns_detail(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        issue["key"] = "OIT-999"
        issue["fields"]["summary"] = "New laptop request"
        issue["fields"]["priority"] = {"name": "Medium"}
        issue["fields"]["customfield_11102"]["requestType"]["name"] = "Laptop"

        calls: list[tuple[Any, ...]] = []
        monkeypatch.setattr(
            routes_tickets._client,
            "create_issue",
            lambda **kwargs: calls.append(("create_issue", kwargs)) or {"id": "100999", "key": "OIT-999"},
        )
        monkeypatch.setattr(
            routes_tickets._client,
            "update_priority",
            lambda key, value: calls.append(("priority", key, value)),
        )
        monkeypatch.setattr(
            routes_tickets._client,
            "set_request_type",
            lambda key, value: calls.append(("request_type", key, value)),
        )
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "get_request_comments", lambda key: _request_comments())
        monkeypatch.setattr(
            routes_tickets.requestor_sync_service,
            "maybe_reconcile_issue",
            lambda issue: {
                "updated": False,
                "message": "",
                "requestor_identity": {
                    "extracted_email": "",
                    "directory_match": False,
                    "jira_account_id": "",
                    "jira_status": "unmatched",
                    "message": "",
                },
            },
        )
        monkeypatch.setattr(routes_tickets, "add_fallback_internal_audit_note", lambda *args, **kwargs: None)

        resp = test_client.post(
            "/api/tickets",
            json={
                "summary": "New laptop request",
                "description": "Please create a laptop ticket.",
                "priority": "Medium",
                "request_type_id": "122",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["created_key"] == "OIT-999"
        assert data["created_id"] == "100999"
        assert data["detail"]["ticket"]["key"] == "OIT-999"
        assert calls == [
            (
                "create_issue",
                {
                    "project_key": "OIT",
                    "issue_type": "[System] Service request",
                    "summary": "New laptop request",
                    "description": "Please create a laptop ticket.",
                },
            ),
            ("priority", "OIT-999", "Medium"),
            ("request_type", "OIT-999", "122"),
        ]
        assert issue in [call.args[0] for call in mock_cache.upsert_issue.call_args_list]

    def test_create_ticket_rejects_missing_required_fields(self, test_client):
        missing_summary = test_client.post(
            "/api/tickets",
            json={
                "summary": "   ",
                "description": "",
                "priority": "",
                "request_type_id": "",
            },
        )
        missing_priority = test_client.post(
            "/api/tickets",
            json={
                "summary": "Need VPN access",
                "description": "",
                "priority": "",
                "request_type_id": "122",
            },
        )
        missing_request_type = test_client.post(
            "/api/tickets",
            json={
                "summary": "Need VPN access",
                "description": "",
                "priority": "High",
                "request_type_id": "",
            },
        )

        assert missing_summary.status_code == 400
        assert missing_summary.json()["detail"] == "summary cannot be empty"
        assert missing_priority.status_code == 400
        assert missing_priority.json()["detail"] == "priority cannot be empty"
        assert missing_request_type.status_code == 400
        assert missing_request_type.json()["detail"] == "request_type_id cannot be empty"

    def test_create_ticket_is_primary_only(self, test_client):
        resp = test_client.post(
            "/api/tickets",
            headers={"host": "oasisdev.movedocs.com"},
            json={
                "summary": "VPN access",
                "description": "",
                "priority": "High",
                "request_type_id": "122",
            },
        )

        assert resp.status_code == 404

    def test_create_ticket_requires_admin(self, test_client, monkeypatch):
        import auth

        monkeypatch.setattr(auth, "is_admin_user", lambda email: False)

        resp = test_client.post(
            "/api/tickets",
            json={
                "summary": "VPN access",
                "description": "",
                "priority": "High",
                "request_type_id": "122",
            },
        )

        assert resp.status_code == 403

    def test_get_ticket_detail_returns_full_payload(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "get_request_comments", lambda key: _request_comments())
        monkeypatch.setattr(
            routes_tickets.requestor_sync_service,
            "maybe_reconcile_issue",
            lambda issue: {
                "updated": False,
                "message": "",
                "requestor_identity": {
                    "extracted_email": "reporter@example.com",
                    "directory_match": True,
                    "jira_account_id": "acct-reporter",
                    "jira_status": "already_synced",
                    "message": "Reporter already matched Reporter One.",
                },
            },
        )

        resp = test_client.get("/api/tickets/OIT-123")
        assert resp.status_code == 200

        data = resp.json()
        assert data["ticket"]["key"] == "OIT-123"
        assert data["description"] == "User cannot sign in."
        assert data["steps_to_recreate"] == "1. Open portal\n2. Attempt login"
        assert data["request_type"] == "Business Application Support"
        assert data["work_category"] == "Identity"
        assert data["jira_url"].endswith("/browse/OIT-123")
        assert data["portal_url"].endswith("/portal/1/OIT-123")
        assert data["requestor_identity"] == {
            "extracted_email": "reporter@example.com",
            "directory_match": True,
            "jira_account_id": "acct-reporter",
            "jira_status": "already_synced",
            "message": "Reporter already matched Reporter One.",
        }
        assert data["comments"][0]["body"] == "Investigating now."
        assert data["comments"][0]["public"] is False
        assert data["attachments"][0]["filename"] == "screenshot.png"
        assert data["attachments"][0]["display_name"] == "screenshot.png"
        assert data["attachments"][0]["download_url"].endswith("/api/tickets/OIT-123/attachments/9001/download")
        assert data["attachments"][0]["preview_url"].endswith("/api/tickets/OIT-123/attachments/9001/preview")
        assert data["issue_links"][0]["key"] == "OIT-456"
        mock_cache.upsert_issue.assert_called_once_with(issue)

    def test_get_ticket_detail_persists_occ_ticket_id_from_request_comments(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        issue["fields"]["description"] = _adf("Imported alert without OCC id in the body.")
        occ_comments = _request_comments()
        occ_comments[0]["body"] = "Successfully OCC ticket Created with Ticket Id: LIBRA-SR-075206"
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "get_request_comments", lambda key: occ_comments)
        monkeypatch.setattr(
            routes_tickets.requestor_sync_service,
            "maybe_reconcile_issue",
            lambda issue: {
                "updated": False,
                "message": "",
                "requestor_identity": {
                    "extracted_email": "",
                    "directory_match": False,
                    "jira_account_id": "",
                    "jira_status": "unmatched",
                    "message": "",
                },
            },
        )

        resp = test_client.get("/api/tickets/OIT-123")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ticket"]["occ_ticket_id"] == "LIBRA-SR-075206"
        assert issue["fields"]["_movedocs_occ_ticket_id"] == "LIBRA-SR-075206"
        assert issue["fields"]["comment"]["total"] == len(occ_comments)
        mock_cache.upsert_issue.assert_called_once_with(issue)

    def test_get_ticket_detail_aliases_generated_attachment_names(self, test_client, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        issue["fields"]["attachment"].append(
            {
                "id": "9002",
                "filename": "10875238511763560924.xls",
                "mimeType": "application/vnd.ms-excel",
                "size": 65000,
                "created": "2026-03-01T10:00:00+00:00",
                "author": {"displayName": "Alice Admin"},
                "content": "https://example.atlassian.net/file/9002",
                "thumbnail": "",
            }
        )
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "get_request_comments", lambda key: _request_comments())

        resp = test_client.get("/api/tickets/OIT-123")

        assert resp.status_code == 200
        attachments = resp.json()["attachments"]
        generated = next(item for item in attachments if item["id"] == "9002")
        assert generated["raw_filename"] == "10875238511763560924.xls"
        assert generated["display_name"] == "OIT-123 - Office Document - 2026-03-01 10-00.xls"
        assert generated["preview_kind"] == "office"
        assert generated["preview_url"].endswith("/api/tickets/OIT-123/attachments/9002/preview-converted")

    def test_get_assignable_display_name_logs_and_falls_back_when_lookup_fails(self, monkeypatch, caplog):
        import routes_tickets

        monkeypatch.setattr(
            routes_tickets._client,
            "get_users_assignable",
            lambda project: (_ for _ in ()).throw(RuntimeError("jira unavailable")),
        )
        monkeypatch.setattr(
            routes_tickets._client,
            "get_user",
            lambda account_id: {"displayName": "Fallback User"},
        )

        with caplog.at_level("ERROR"):
            result = routes_tickets._get_user_display_name("acct-123")

        assert result == "Fallback User"
        assert any(
            "Failed to resolve Jira display name from assignable users for account acct-123" in record.getMessage()
            for record in caplog.records
        )

    def test_get_user_display_name_logs_and_falls_back_when_direct_lookup_fails(self, monkeypatch, caplog):
        import routes_tickets

        monkeypatch.setattr(routes_tickets._client, "get_users_assignable", lambda project: [])
        monkeypatch.setattr(
            routes_tickets._client,
            "get_user",
            lambda account_id: (_ for _ in ()).throw(RuntimeError("jira unavailable")),
        )

        with caplog.at_level("ERROR"):
            result = routes_tickets._get_user_display_name("acct-456")

        assert result == ""
        assert any(
            "Failed to resolve Jira display name for account acct-456" in record.getMessage()
            for record in caplog.records
        )

    def test_get_statuses_logs_ticket_transition_lookup_failures(self, test_client, monkeypatch, caplog):
        import routes_tickets

        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(routes_tickets._client, "get_transitions", lambda key: (_ for _ in ()).throw(RuntimeError("jira unavailable")))

        with caplog.at_level("ERROR"):
            resp = test_client.get("/api/statuses/OIT-123")

        assert resp.status_code == 404
        assert resp.json() == {"detail": "Could not get transitions for OIT-123"}
        assert any(
            "Failed to load transitions for ticket OIT-123" in record.getMessage()
            for record in caplog.records
        )

    def test_get_ticket_logs_detail_load_failures(self, test_client, monkeypatch, caplog):
        import routes_tickets

        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: (_ for _ in ()).throw(RuntimeError("jira unavailable")))

        with caplog.at_level("ERROR"):
            resp = test_client.get("/api/tickets/OIT-123")

        assert resp.status_code == 404
        assert resp.json() == {"detail": "Issue OIT-123 not found"}
        assert any(
            "Failed to load ticket detail for OIT-123" in record.getMessage()
            for record in caplog.records
        )

    def test_get_priorities_and_request_types(self, test_client, monkeypatch):
        import routes_tickets

        monkeypatch.setattr(
            routes_tickets._client,
            "get_priorities",
            lambda: [{"id": "1", "name": "Highest"}, {"id": "2", "name": "High"}],
        )
        issue = _detail_issue()
        issue["fields"]["customfield_10010"] = {
            "requestType": {
                "id": "122",
                "name": "Business Application Support",
                "description": "Apps",
            }
        }
        monkeypatch.setattr(routes_tickets, "get_scoped_issues", lambda: [issue])

        priorities = test_client.get("/api/priorities")
        request_types = test_client.get("/api/request-types")

        assert priorities.status_code == 200
        assert priorities.json() == [{"id": "1", "name": "Highest"}, {"id": "2", "name": "High"}]

        assert request_types.status_code == 200
        assert request_types.json() == [
            {"id": "122", "name": "Business Application Support", "description": "Apps"}
        ]

    def test_search_users_returns_sorted_jira_matches(self, test_client, monkeypatch):
        import routes_tickets

        monkeypatch.setattr(
            routes_tickets._client,
            "search_users",
            lambda query: [
                {"accountId": "acct-2", "displayName": "Raza Abidi", "emailAddress": "raza@example.com", "active": True},
                {"accountId": "acct-1", "displayName": "Alan Turing", "emailAddress": "alan@example.com", "active": True},
                {"accountId": "acct-3", "displayName": "Disabled User", "emailAddress": "disabled@example.com", "active": False},
            ],
        )

        resp = test_client.get("/api/users/search?q=ra")

        assert resp.status_code == 200
        assert resp.json() == [
            {"account_id": "acct-1", "display_name": "Alan Turing", "email_address": "alan@example.com"},
            {"account_id": "acct-2", "display_name": "Raza Abidi", "email_address": "raza@example.com"},
        ]

    def test_list_users_returns_sorted_assignable_users(self, test_client, monkeypatch):
        import routes_tickets

        monkeypatch.setattr(
            routes_tickets._client,
            "get_users_assignable",
            lambda project: [
                {"accountId": "acct-2", "displayName": "Raza Abidi", "emailAddress": "raza@example.com", "active": True},
                {"accountId": "acct-1", "displayName": "Alan Turing", "emailAddress": "alan@example.com", "active": True},
                {"accountId": "acct-3", "displayName": "Disabled User", "emailAddress": "disabled@example.com", "active": False},
                {"accountId": "acct-1", "displayName": "Alan Turing", "emailAddress": "alan@example.com", "active": True},
            ],
        )

        resp = test_client.get("/api/users")

        assert resp.status_code == 200
        assert resp.json() == [
            {"account_id": "acct-1", "display_name": "Alan Turing", "email_address": "alan@example.com"},
            {"account_id": "acct-2", "display_name": "Raza Abidi", "email_address": "raza@example.com"},
        ]

    def test_sync_ticket_reporter_delegates_to_unified_requestor_sync(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue_before = _detail_issue()
        issue_before["fields"]["reporter"] = {"displayName": "OSIJIRAOCC", "accountId": "acct-occ"}
        issue_before["fields"]["description"] = _adf(
            "OCC Ticket Created By: Raza Abidi | OCC Ticket ID: LIBRA-SR-074744"
        )
        issue_after = _detail_issue()
        issue_after["fields"]["reporter"] = {"displayName": "Raza Abidi", "accountId": "acct-raza"}
        issue_after["fields"]["description"] = issue_before["fields"]["description"]

        issues = [issue_before, issue_after]

        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issues.pop(0))
        monkeypatch.setattr(routes_tickets._client, "get_request_comments", lambda key: _request_comments())
        monkeypatch.setattr(
            routes_tickets.requestor_sync_service,
            "reconcile_issue",
            lambda issue, force=False: (
                issue["fields"].__setitem__("reporter", {"displayName": "Raza Abidi", "accountId": "acct-raza"}),
                {
                    "updated": True,
                    "message": "Matched from OCC creator name and synced reporter to Raza Abidi.",
                    "requestor_identity": {
                        "extracted_email": "raza@librasolutionsgroup.com",
                        "directory_match": True,
                        "jira_account_id": "acct-raza",
                        "jira_status": "updated_reporter",
                        "message": "Matched from OCC creator name and synced reporter to Raza Abidi.",
                        "match_source": "occ_creator_name",
                    },
                },
            )[1],
        )

        resp = test_client.post("/api/tickets/OIT-123/sync-reporter")

        assert resp.status_code == 200
        assert resp.json()["updated"] is True
        assert resp.json()["message"] == "Matched from OCC creator name and synced reporter to Raza Abidi."
        assert resp.json()["detail"]["ticket"]["reporter"] == "Raza Abidi"
        cached_issue = mock_cache.upsert_issue.call_args.args[0]
        assert cached_issue["fields"]["reporter"] == {"displayName": "Raza Abidi", "accountId": "acct-raza"}
        assert cached_issue["fields"]["comment"]["total"] == 1
        assert cached_issue["fields"]["_movedocs_occ_ticket_id"] == "LIBRA-SR-074744"

    def test_sync_ticket_reporter_uses_requestor_sync_when_email_path_exists(self, test_client, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        issue["fields"]["reporter"] = {"displayName": "OSIJIRAOCC", "accountId": "acct-occ"}
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "get_request_comments", lambda key: _request_comments())
        monkeypatch.setattr(
            routes_tickets.requestor_sync_service,
            "reconcile_issue",
            lambda issue, force=False: {
                "updated": True,
                "message": "Reporter synced to Grace Hopper.",
                "requestor_identity": {
                    "extracted_email": "grace.hopper@example.com",
                    "directory_match": True,
                    "jira_account_id": "acct-grace",
                    "jira_status": "updated_reporter",
                    "message": "Reporter synced to Grace Hopper.",
                    "match_source": "reporter_email",
                },
            },
        )
        monkeypatch.setattr(
            routes_tickets.requestor_sync_service,
            "maybe_reconcile_issue",
            lambda issue: {
                "updated": False,
                "message": "",
                "requestor_identity": {
                    "extracted_email": "grace.hopper@example.com",
                    "directory_match": True,
                    "jira_account_id": "acct-grace",
                    "jira_status": "updated_reporter",
                    "message": "Reporter synced to Grace Hopper.",
                    "match_source": "reporter_email",
                },
            },
        )

        resp = test_client.post("/api/tickets/OIT-123/sync-reporter")

        assert resp.status_code == 200
        assert resp.json()["updated"] is True
        assert resp.json()["message"] == "Reporter synced to Grace Hopper."
        assert resp.json()["detail"]["requestor_identity"]["jira_account_id"] == "acct-grace"

    def test_sync_ticket_requestor_returns_reconciled_detail(self, test_client, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "get_request_comments", lambda key: _request_comments())
        monkeypatch.setattr(
            routes_tickets.requestor_sync_service,
            "reconcile_issue",
            lambda issue, force=False: {
                "updated": True,
                "message": "Created Jira customer and synced reporter to Grace Hopper.",
                "requestor_identity": {
                    "extracted_email": "grace.hopper@example.com",
                    "directory_match": True,
                    "jira_account_id": "acct-grace",
                    "jira_status": "created_jira_customer",
                    "message": "Created Jira customer and synced reporter to Grace Hopper.",
                    "match_source": "reporter_email",
                },
            },
        )
        monkeypatch.setattr(
            routes_tickets.requestor_sync_service,
            "maybe_reconcile_issue",
            lambda issue: {
                "updated": False,
                "message": "",
                "requestor_identity": {
                    "extracted_email": "grace.hopper@example.com",
                    "directory_match": True,
                    "jira_account_id": "acct-grace",
                    "jira_status": "created_jira_customer",
                    "message": "Created Jira customer and synced reporter to Grace Hopper.",
                    "match_source": "reporter_email",
                },
            },
        )

        resp = test_client.post("/api/tickets/OIT-123/sync-requestor")

        assert resp.status_code == 200
        assert resp.json()["updated"] is True
        assert resp.json()["message"] == "Created Jira customer and synced reporter to Grace Hopper."
        assert resp.json()["detail"]["requestor_identity"]["jira_status"] == "created_jira_customer"

    def test_sync_ticket_requestor_preserves_upstream_http_status(self, test_client, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)

        response = MagicMock()
        response.status_code = 412
        error = requests.HTTPError("412 Precondition Failed — Jira error: experimental endpoint", response=response)

        def _raise(issue, force=False):
            raise error

        monkeypatch.setattr(routes_tickets.requestor_sync_service, "reconcile_issue", _raise)

        resp = test_client.post("/api/tickets/OIT-123/sync-requestor")

        assert resp.status_code == 412
        assert "412 Precondition Failed" in resp.json()["detail"]

    def test_get_requestor_sync_status_returns_recent_rows(self, test_client, monkeypatch):
        import routes_tickets

        monkeypatch.setattr(
            routes_tickets.requestor_sync_service,
            "list_recent_status",
            lambda limit=100, failures_only=False: [
                {
                    "ticket_key": "OIT-123",
                    "email_key": "grace.hopper@example.com",
                    "sync_status": "created_jira_customer",
                    "message": "Created Jira customer and synced reporter to Grace Hopper.",
                }
            ],
        )

        resp = test_client.get("/api/requestor-sync/status?limit=10")

        assert resp.status_code == 200
        assert resp.json() == {
            "items": [
                {
                    "ticket_key": "OIT-123",
                    "email_key": "grace.hopper@example.com",
                    "sync_status": "created_jira_customer",
                    "message": "Created Jira customer and synced reporter to Grace Hopper.",
                }
            ]
        }

    def test_update_ticket_writes_supported_fields(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        issue["fields"]["summary"] = "Updated summary"
        issue["fields"]["priority"] = {"name": "Medium"}
        issue["fields"]["assignee"] = {"displayName": "Bob Builder", "accountId": "acc-bob"}
        issue["fields"]["reporter"] = {"displayName": "Raza Abidi", "accountId": "acct-raza"}
        issue["fields"]["description"] = _adf("Updated description")
        issue["fields"]["customfield_11102"]["requestType"]["name"] = "Access"
        issue["fields"]["components"] = [{"name": "Portal"}, {"name": "VPN"}]
        issue["fields"]["customfield_11239"] = "Operations"

        calls: list[tuple[Any, ...]] = []
        monkeypatch.setattr(routes_tickets._client, "update_summary", lambda key, value: calls.append(("summary", key, value)))
        monkeypatch.setattr(routes_tickets._client, "update_description", lambda key, value: calls.append(("description", key, value)))
        monkeypatch.setattr(routes_tickets._client, "update_priority", lambda key, value: calls.append(("priority", key, value)))
        monkeypatch.setattr(routes_tickets._client, "assign_issue", lambda key, value: calls.append(("assignee", key, value)))
        monkeypatch.setattr(routes_tickets._client, "update_reporter", lambda key, value: calls.append(("reporter", key, value)))
        monkeypatch.setattr(routes_tickets._client, "set_request_type", lambda key, value: calls.append(("request_type", key, value)))
        monkeypatch.setattr(
            routes_tickets._client,
            "get_editable_components",
            lambda key: [{"id": "200", "name": "Portal"}, {"id": "201", "name": "VPN"}],
        )
        monkeypatch.setattr(
            routes_tickets._client,
            "update_components_by_id",
            lambda key, value: calls.append(("components", key, value)),
        )
        monkeypatch.setattr(routes_tickets._client, "update_work_category", lambda key, value: calls.append(("work_category", key, value)))
        monkeypatch.setattr(
            routes_tickets._client,
            "get_users_assignable",
            lambda project: [{"accountId": "acc-bob", "displayName": "Bob Builder"}],
        )
        monkeypatch.setattr(
            routes_tickets._client,
            "get_user",
            lambda account_id: {"accountId": account_id, "displayName": "Raza Abidi"},
        )
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "get_request_comments", lambda key: _request_comments())

        resp = test_client.put(
            "/api/tickets/OIT-123",
            json={
                "summary": "Updated summary",
                "description": "Updated description",
                "priority": "Medium",
                "assignee_account_id": "acc-bob",
                "reporter_account_id": "acct-raza",
                "reporter_display_name": "Raza Abidi",
                "request_type_id": "122",
                "components": ["Portal", "VPN"],
                "work_category": "Operations",
            },
        )

        assert resp.status_code == 200
        assert calls == [
            ("summary", "OIT-123", "Updated summary"),
            ("description", "OIT-123", "Updated description"),
            ("priority", "OIT-123", "Medium"),
            ("assignee", "OIT-123", "acc-bob"),
            ("reporter", "OIT-123", "acct-raza"),
            ("request_type", "OIT-123", "122"),
            ("components", "OIT-123", ["200", "201"]),
            ("work_category", "OIT-123", "Operations"),
        ]
        assert ("OIT-123", "summary", "Updated summary") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert ("OIT-123", "description", "Updated description") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert ("OIT-123", "priority", "Medium") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert (
            "OIT-123",
            "assignee",
            {"displayName": "Bob Builder", "accountId": "acc-bob"},
        ) in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert (
            "OIT-123",
            "reporter",
            {"displayName": "Raza Abidi", "accountId": "acct-raza"},
        ) in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert ("OIT-123", "request_type", "Access") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        mock_cache.upsert_issue.assert_called_once_with(issue)
        assert resp.json()["ticket"]["summary"] == "Updated summary"
        assert resp.json()["ticket"]["components"] == ["Portal", "VPN"]
        assert resp.json()["work_category"] == "Operations"
        assert resp.json()["description"] == "Updated description"

    def test_update_ticket_rejects_unknown_component_names(self, test_client, monkeypatch):
        import routes_tickets

        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(
            routes_tickets._client,
            "get_editable_components",
            lambda key: [{"id": "200", "name": "Portal"}, {"id": "201", "name": "VPN"}],
        )
        update_components_by_id = MagicMock()
        monkeypatch.setattr(routes_tickets._client, "update_components_by_id", update_components_by_id)

        resp = test_client.put(
            "/api/tickets/OIT-123",
            json={
                "components": ["Portal", "Made Up Component"],
            },
        )

        assert resp.status_code == 400
        assert (
            resp.json()["detail"]
            == "Component changes must use an existing Jira component for this project. Unknown component(s): Made Up Component."
        )
        update_components_by_id.assert_not_called()

    def test_transition_ticket_updates_status(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        issue["fields"]["status"] = {"name": "In Progress", "statusCategory": {"name": "In Progress"}}
        calls: list[tuple[Any, ...]] = []

        monkeypatch.setattr(
            routes_tickets._client,
            "get_transitions",
            lambda key: [{"id": "31", "name": "Start Progress", "to": {"name": "In Progress"}}],
        )
        monkeypatch.setattr(routes_tickets._client, "transition_issue", lambda key, transition_id: calls.append((key, transition_id)))
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "get_request_comments", lambda key: _request_comments())

        resp = test_client.post("/api/tickets/OIT-123/transition", json={"transition_id": "31"})

        assert resp.status_code == 200
        assert calls == [("OIT-123", "31")]
        assert ("OIT-123", "status", "In Progress") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        mock_cache.upsert_issue.assert_called_once_with(issue)
        assert resp.json()["ticket"]["status"] == "In Progress"

    def test_comment_ticket_updates_detail(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        calls: list[tuple[Any, ...]] = []

        monkeypatch.setattr(
            routes_tickets._client,
            "add_request_comment",
            lambda key, comment, public=False: calls.append((key, comment, public)),
        )
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(
            routes_tickets._client,
            "get_request_comments",
            lambda key: _request_comments() + [{
                "id": "18",
                "author": {"displayName": "Agent Two"},
                "created": {"iso8601": "2026-03-01T12:00:00+00:00"},
                "updated": {"iso8601": "2026-03-01T12:00:00+00:00"},
                "body": "Please retry now.",
                "public": True,
            }],
        )

        resp = test_client.post(
            "/api/tickets/OIT-123/comment",
            json={"comment": "Please retry now.", "public": True},
        )

        assert resp.status_code == 200
        assert calls == [
            (
                "OIT-123",
                "[MoveDocs fallback actor: Test User <test@example.com>]\n\nPlease retry now.",
                True,
            )
        ]
        assert ("OIT-123", "updated", "") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        mock_cache.upsert_issue.assert_called_once_with(issue)
        assert resp.json()["comments"][-1]["body"] == "Please retry now."
        assert resp.json()["comments"][-1]["public"] is True

    def test_attachment_download_returns_original_bytes(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        mock_cache.get_all_issues.return_value = [issue]
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(
            routes_tickets,
            "fetch_attachment_content",
            lambda client, attachment: (b"file-bytes", "image/png"),
        )

        resp = test_client.get("/api/tickets/OIT-123/attachments/9001/download")

        assert resp.status_code == 200
        assert resp.content == b"file-bytes"
        assert resp.headers["content-disposition"].startswith("attachment;")
        assert resp.headers["content-type"].startswith("image/png")

    def test_attachment_preview_returns_original_image(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        mock_cache.get_all_issues.return_value = [issue]
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(
            routes_tickets,
            "fetch_attachment_content",
            lambda client, attachment: (b"image-bytes", "image/png"),
        )

        resp = test_client.get("/api/tickets/OIT-123/attachments/9001/preview")

        assert resp.status_code == 200
        assert resp.content == b"image-bytes"
        assert resp.headers["content-disposition"].startswith("inline;")

    def test_attachment_converted_preview_returns_pdf(self, test_client, mock_cache, monkeypatch, tmp_path):
        import routes_tickets

        issue = _detail_issue()
        issue["fields"]["attachment"] = [
            {
                "id": "9002",
                "filename": "10875238511763560924.xlsx",
                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "size": 4096,
                "created": "2026-03-01T10:00:00+00:00",
                "author": {"displayName": "Alice Admin"},
                "content": "https://example.atlassian.net/file/9002",
                "thumbnail": "",
            }
        ]
        pdf_path = tmp_path / "preview.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\npreview")
        mock_cache.get_all_issues.return_value = [issue]
        monkeypatch.setattr(routes_tickets, "key_is_visible_in_scope", lambda key: True)
        monkeypatch.setattr(routes_tickets, "ensure_office_preview_pdf", lambda client, attachment: pdf_path)

        resp = test_client.get("/api/tickets/OIT-123/attachments/9002/preview-converted")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/pdf")
        assert resp.content.startswith(b"%PDF-1.4")
