"""Tests for report builder and export routes (~7 tests)."""

from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import load_workbook


def _make_workload_issue(
    *,
    key: str,
    summary: str,
    status: str,
    status_category: str,
    assignee: str,
    created: str,
    updated: str,
    resolved: str | None = None,
    priority: str = "Medium",
    request_type: str = "Business Application Support",
    components: list[str] | None = None,
    work_category: str = "Service requests",
    oasisdev: bool = True,
) -> dict:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status, "statusCategory": {"name": status_category}},
            "priority": {"name": priority},
            "assignee": {
                "displayName": assignee,
                "accountId": f"acc-{assignee.lower().replace(' ', '-')}",
            },
            "reporter": {
                "displayName": "Grant Reviewer",
                "accountId": "acc-grant-reviewer",
            },
            "issuetype": {"name": "[System] Service request"},
            "resolution": {"name": "Done"} if resolved else None,
            "created": created,
            "updated": updated,
            "resolutiondate": resolved,
            "labels": ["oasisdev"] if oasisdev else [],
            "components": [{"name": name} for name in (components or [])],
            "customfield_11239": work_category,
            "customfield_10010": {"requestType": {"name": request_type}},
            "customfield_11266": None,
            "customfield_11264": None,
            "customfield_10700": [],
            "attachment": [],
        },
    }


class TestReportPreview:
    """POST /api/report/preview"""

    def test_flat_preview(self, test_client):
        resp = test_client.post("/api/report/preview", json={
            "filters": {},
            "columns": [],
            "sort_field": "created",
            "sort_dir": "desc",
            "group_by": None,
            "include_excluded": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["grouped"] is False
        assert isinstance(data["rows"], list)
        assert data["total_count"] > 0

    def test_custom_columns(self, test_client):
        resp = test_client.post("/api/report/preview", json={
            "filters": {},
            "columns": ["key", "summary", "status"],
            "sort_field": "created",
            "sort_dir": "desc",
            "group_by": None,
            "include_excluded": False,
        })
        assert resp.status_code == 200
        rows = resp.json()["rows"]
        if rows:
            assert set(rows[0].keys()) == {"key", "summary", "status"}

    def test_grouped_preview(self, test_client):
        resp = test_client.post("/api/report/preview", json={
            "filters": {},
            "columns": [],
            "sort_field": "created",
            "sort_dir": "desc",
            "group_by": "priority",
            "include_excluded": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["grouped"] is True
        if data["rows"]:
            assert "group" in data["rows"][0]
            assert "count" in data["rows"][0]

    def test_with_filters(self, test_client):
        resp = test_client.post("/api/report/preview", json={
            "filters": {"priority": "High"},
            "columns": [],
            "sort_field": "created",
            "sort_dir": "desc",
            "group_by": None,
            "include_excluded": False,
        })
        assert resp.status_code == 200


class TestReportExport:
    """POST /api/report/export"""

    def test_returns_excel(self, test_client):
        resp = test_client.post("/api/report/export", json={
            "filters": {},
            "columns": ["key", "summary"],
            "sort_field": "created",
            "sort_dir": "desc",
            "group_by": None,
            "include_excluded": False,
        })
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers.get("content-type", "")


class TestLegacyExport:
    """GET /api/export/excel"""

    def test_returns_excel(self, test_client):
        resp = test_client.get("/api/export/excel")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers.get("content-type", "")

    def test_response_is_binary(self, test_client):
        resp = test_client.get("/api/export/excel")
        assert len(resp.content) > 0


class TestOasisDevWorkloadReport:
    def test_preview_returns_monthly_summary_for_oasisdev_host(self, test_client, mock_cache):
        mock_cache.get_all_issues.return_value = [
            _make_workload_issue(
                key="OIT-501",
                summary="oasisdev app issue",
                status="Acknowledged",
                status_category="In Progress",
                assignee="Tim Reckamp",
                created="2026-01-05T10:00:00+00:00",
                updated="2026-01-06T10:00:00+00:00",
                components=["Portal"],
            ),
            _make_workload_issue(
                key="OIT-502",
                summary="oasisdev resolved issue",
                status="Resolved",
                status_category="Done",
                assignee="Tim Reckamp",
                created="2026-02-14T10:00:00+00:00",
                updated="2026-02-20T10:00:00+00:00",
                resolved="2026-02-20T10:00:00+00:00",
                components=["VPN"],
            ),
            _make_workload_issue(
                key="OIT-503",
                summary="oasisdev march follow-up",
                status="Resolved",
                status_category="Done",
                assignee="Tim Reckamp",
                created="2026-03-02T10:00:00+00:00",
                updated="2026-03-03T10:00:00+00:00",
                resolved="2026-03-03T10:00:00+00:00",
                components=["Outlook"],
            ),
            _make_workload_issue(
                key="OIT-504",
                summary="oasisdev other technician",
                status="Open",
                status_category="To Do",
                assignee="Other Tech",
                created="2026-03-07T10:00:00+00:00",
                updated="2026-03-07T10:00:00+00:00",
            ),
            _make_workload_issue(
                key="OIT-999",
                summary="primary site ticket",
                status="Open",
                status_category="To Do",
                assignee="Tim Reckamp",
                created="2026-03-04T10:00:00+00:00",
                updated="2026-03-04T10:00:00+00:00",
                oasisdev=False,
            ),
        ]

        resp = test_client.post(
            "/api/report/oasisdev-workload",
            headers={"host": "oasisdev.movedocs.com"},
            json={
                "assignee": "Tim Reckamp",
                "report_start": "2026-01-01",
                "report_end": "2026-03-31",
                "last_report_date": "2026-03-01",
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["summary"]["assignee"] == "Tim Reckamp"
        assert payload["summary"]["tickets_created_in_window"] == 3
        assert payload["summary"]["tickets_resolved_in_window"] == 2
        assert payload["monthly_status"]["grand_total"] == [1, 1, 1]
        assert payload["since_last_report"]["created_count"] == 1
        assert payload["since_last_report"]["resolved_count"] == 1
        assert payload["since_last_report"]["tickets"][0]["application"] == "Outlook"

    def test_preview_is_hidden_on_non_oasisdev_host(self, test_client):
        resp = test_client.post("/api/report/oasisdev-workload", json={})
        assert resp.status_code == 404

    def test_export_returns_excel_workbook(self, test_client, mock_cache):
        mock_cache.get_all_issues.return_value = [
            _make_workload_issue(
                key="OIT-601",
                summary="oasisdev export row",
                status="Resolved",
                status_category="Done",
                assignee="Tim Reckamp",
                created="2026-03-08T10:00:00+00:00",
                updated="2026-03-10T10:00:00+00:00",
                resolved="2026-03-10T10:00:00+00:00",
                components=["Portal", "VPN"],
            ),
        ]

        resp = test_client.post(
            "/api/report/oasisdev-workload/export",
            headers={"host": "oasisdev.movedocs.com"},
            json={
                "assignee": "Tim Reckamp",
                "report_start": "2026-01-01",
                "report_end": "2026-03-31",
                "last_report_date": "2026-03-01",
            },
        )
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers.get("content-type", "")
        workbook = load_workbook(filename=BytesIO(resp.content))
        assert workbook.sheetnames == [
            "Monthly Status",
            "Created vs Resolved",
            "Since Last Report",
        ]
        since_last_report = workbook["Since Last Report"]
        assert since_last_report["B3"].value == 1
        assert since_last_report["J13"].value == "Portal, VPN"
