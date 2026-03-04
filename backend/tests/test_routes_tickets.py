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
