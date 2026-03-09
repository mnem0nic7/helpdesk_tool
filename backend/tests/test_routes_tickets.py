"""Tests for ticket routes and the _match filter function (~19 tests)."""

from __future__ import annotations

from typing import Any

import pytest


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
) -> dict[str, Any]:
    """Build a minimal issue for _match testing."""
    assignee_obj = {"displayName": assignee} if assignee else None
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status, "statusCategory": {"name": status_category}},
            "priority": {"name": priority},
            "assignee": assignee_obj,
            "issuetype": {"name": issue_type},
            "created": created,
            "updated": updated,
            "description": None,
        },
    }


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

    def test_open_only(self):
        assert _match(_issue(status_category="To Do"), open_only=True) is True

    def test_open_only_excludes_done(self):
        assert _match(_issue(status_category="Done"), open_only=True) is False

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
            "comment": {
                "comments": [
                    {
                        "id": "17",
                        "author": {"displayName": "Tech One"},
                        "created": "2026-03-01T11:00:00+00:00",
                        "updated": "2026-03-01T11:05:00+00:00",
                        "body": _adf("Investigating now."),
                    }
                ]
            },
        },
    }


class TestTicketDetailAndActions:
    def test_get_ticket_detail_returns_full_payload(self, test_client, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "_backfill_comments", lambda issues: None)

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
        assert data["comments"][0]["body"] == "Investigating now."
        assert data["attachments"][0]["filename"] == "screenshot.png"
        assert data["issue_links"][0]["key"] == "OIT-456"

    def test_get_priorities_and_request_types(self, test_client, monkeypatch):
        import routes_tickets

        monkeypatch.setattr(
            routes_tickets._client,
            "get_priorities",
            lambda: [{"id": "1", "name": "Highest"}, {"id": "2", "name": "High"}],
        )
        monkeypatch.setattr(routes_tickets._client, "get_service_desk_id_for_project", lambda project: "7")
        monkeypatch.setattr(
            routes_tickets._client,
            "get_request_types",
            lambda service_desk_id: [{"id": "122", "name": "Business Application Support", "description": "Apps"}],
        )

        priorities = test_client.get("/api/priorities")
        request_types = test_client.get("/api/request-types")

        assert priorities.status_code == 200
        assert priorities.json() == [{"id": "1", "name": "Highest"}, {"id": "2", "name": "High"}]

        assert request_types.status_code == 200
        assert request_types.json() == [
            {"id": "122", "name": "Business Application Support", "description": "Apps"}
        ]

    def test_update_ticket_writes_supported_fields(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        issue["fields"]["summary"] = "Updated summary"
        issue["fields"]["priority"] = {"name": "Medium"}
        issue["fields"]["assignee"] = {"displayName": "Bob Builder", "accountId": "acc-bob"}
        issue["fields"]["description"] = _adf("Updated description")
        issue["fields"]["customfield_11102"]["requestType"]["name"] = "Access"

        calls: list[tuple[Any, ...]] = []
        monkeypatch.setattr(routes_tickets._client, "update_summary", lambda key, value: calls.append(("summary", key, value)))
        monkeypatch.setattr(routes_tickets._client, "update_description", lambda key, value: calls.append(("description", key, value)))
        monkeypatch.setattr(routes_tickets._client, "update_priority", lambda key, value: calls.append(("priority", key, value)))
        monkeypatch.setattr(routes_tickets._client, "assign_issue", lambda key, value: calls.append(("assignee", key, value)))
        monkeypatch.setattr(routes_tickets._client, "set_request_type", lambda key, value: calls.append(("request_type", key, value)))
        monkeypatch.setattr(
            routes_tickets._client,
            "get_users_assignable",
            lambda project: [{"accountId": "acc-bob", "displayName": "Bob Builder"}],
        )
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "_backfill_comments", lambda issues: None)

        resp = test_client.put(
            "/api/tickets/OIT-123",
            json={
                "summary": "Updated summary",
                "description": "Updated description",
                "priority": "Medium",
                "assignee_account_id": "acc-bob",
                "request_type_id": "122",
            },
        )

        assert resp.status_code == 200
        assert calls == [
            ("summary", "OIT-123", "Updated summary"),
            ("description", "OIT-123", "Updated description"),
            ("priority", "OIT-123", "Medium"),
            ("assignee", "OIT-123", "acc-bob"),
            ("request_type", "OIT-123", "122"),
        ]
        assert ("OIT-123", "summary", "Updated summary") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert ("OIT-123", "description", "Updated description") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert ("OIT-123", "priority", "Medium") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert ("OIT-123", "assignee", "Bob Builder") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert ("OIT-123", "request_type", "Access") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert resp.json()["ticket"]["summary"] == "Updated summary"
        assert resp.json()["description"] == "Updated description"

    def test_transition_ticket_updates_status(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        issue["fields"]["status"] = {"name": "In Progress", "statusCategory": {"name": "In Progress"}}
        calls: list[tuple[Any, ...]] = []

        monkeypatch.setattr(
            routes_tickets._client,
            "get_transitions",
            lambda key: [{"id": "31", "name": "Start Progress", "to": {"name": "In Progress"}}],
        )
        monkeypatch.setattr(routes_tickets._client, "transition_issue", lambda key, transition_id: calls.append((key, transition_id)))
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "_backfill_comments", lambda issues: None)

        resp = test_client.post("/api/tickets/OIT-123/transition", json={"transition_id": "31"})

        assert resp.status_code == 200
        assert calls == [("OIT-123", "31")]
        assert ("OIT-123", "status", "In Progress") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert resp.json()["ticket"]["status"] == "In Progress"

    def test_comment_ticket_updates_detail(self, test_client, mock_cache, monkeypatch):
        import routes_tickets

        issue = _detail_issue()
        calls: list[tuple[Any, ...]] = []

        monkeypatch.setattr(routes_tickets._client, "add_comment", lambda key, comment: calls.append((key, comment)))
        monkeypatch.setattr(routes_tickets._client, "get_issue", lambda key: issue)
        monkeypatch.setattr(routes_tickets._client, "_backfill_comments", lambda issues: None)

        resp = test_client.post("/api/tickets/OIT-123/comment", json={"comment": "Please retry now."})

        assert resp.status_code == 200
        assert calls == [("OIT-123", "Please retry now.")]
        assert ("OIT-123", "updated", "") in [c.args for c in mock_cache.update_cached_field.call_args_list]
        assert resp.json()["comments"][0]["body"] == "Investigating now."
