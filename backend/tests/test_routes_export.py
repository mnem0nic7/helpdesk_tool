"""Tests for report builder and export routes (~7 tests)."""

from __future__ import annotations

from io import BytesIO
from datetime import date, timedelta

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

    def test_preview_includes_comment_metadata_when_requested(self, test_client, mock_cache):
        issue = {
            "key": "OIT-777",
            "fields": {
                "summary": "Comment-heavy ticket",
                "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Alex Agent", "accountId": "acc-alex-agent"},
                "reporter": {"displayName": "Riley Requester", "accountId": "acc-riley"},
                "issuetype": {"name": "[System] Service request"},
                "resolution": {"name": "Done"},
                "created": "2026-03-01T10:00:00+00:00",
                "updated": "2026-03-02T12:00:00+00:00",
                "resolutiondate": "2026-03-02T12:00:00+00:00",
                "labels": [],
                "components": [],
                "customfield_10010": None,
                "customfield_11239": "Service requests",
                "customfield_11266": None,
                "customfield_11264": None,
                "customfield_10700": [],
                "attachment": [],
                "comment": {
                    "total": 2,
                    "comments": [
                        {
                            "created": "2026-03-01T11:00:00+00:00",
                            "updated": "2026-03-01T11:00:00+00:00",
                            "author": {"displayName": "Jordan Commenter"},
                        },
                        {
                            "created": "2026-03-02T12:00:00+00:00",
                            "updated": "2026-03-02T12:00:00+00:00",
                            "author": {"displayName": "Taylor Resolver"},
                        },
                    ],
                },
            },
        }
        mock_cache.get_all_issues.return_value = [issue]
        mock_cache.get_filtered_issues.return_value = [issue]

        resp = test_client.post("/api/report/preview", json={
            "filters": {},
            "columns": ["key", "comment_count", "last_comment_author", "last_comment_date"],
            "sort_field": "comment_count",
            "sort_dir": "desc",
            "group_by": None,
            "include_excluded": False,
        })
        assert resp.status_code == 200
        row = resp.json()["rows"][0]
        assert row["comment_count"] == 2
        assert row["last_comment_author"] == "Taylor Resolver"
        assert row["last_comment_date"] == "2026-03-02T12:00:00+00:00"


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


class TestReportTemplates:
    def test_list_includes_seeded_primary_templates(self, test_client):
        resp = test_client.get("/api/report/templates")
        assert resp.status_code == 200
        names = {row["name"] for row in resp.json()}
        assert "First Response Time" in names
        assert "Customer Satisfaction (CSAT)" in names

    def test_create_update_and_delete_custom_template(self, test_client):
        create_resp = test_client.post(
            "/api/report/templates",
            json={
                "name": "Leadership Weekly Snapshot",
                "description": "Weekly leadership report.",
                "category": "Executive",
                "notes": "Use in Monday leadership sync.",
                "include_in_master_export": False,
                "config": {
                    "filters": {"open_only": True},
                    "columns": ["key", "summary", "priority", "status"],
                    "sort_field": "created",
                    "sort_dir": "desc",
                    "group_by": "priority",
                    "include_excluded": False,
                },
            },
        )
        assert create_resp.status_code == 200
        created = create_resp.json()
        assert created["name"] == "Leadership Weekly Snapshot"
        assert created["is_seed"] is False
        assert created["include_in_master_export"] is False
        assert created["created_by_email"] == "test@example.com"

        update_resp = test_client.put(
            f"/api/report/templates/{created['id']}",
            json={
                "name": "Leadership Weekly Snapshot",
                "description": "Updated description.",
                "category": "Executive",
                "notes": "Updated notes.",
                "include_in_master_export": True,
                "config": {
                    "filters": {"open_only": True, "stale_only": True},
                    "columns": ["key", "summary", "priority", "age_days"],
                    "sort_field": "age_days",
                    "sort_dir": "desc",
                    "group_by": "status",
                    "include_excluded": False,
                },
            },
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["description"] == "Updated description."
        assert updated["include_in_master_export"] is True
        assert updated["config"]["sort_field"] == "age_days"
        assert updated["config"]["filters"]["stale_only"] is True

        delete_resp = test_client.delete(f"/api/report/templates/{created['id']}")
        assert delete_resp.status_code == 200
        assert delete_resp.json() == {"deleted": True}

        list_resp = test_client.get("/api/report/templates")
        assert list_resp.status_code == 200
        assert all(row["id"] != created["id"] for row in list_resp.json())

    def test_seed_templates_are_read_only(self, test_client):
        list_resp = test_client.get("/api/report/templates")
        assert list_resp.status_code == 200
        seed_id = next(row["id"] for row in list_resp.json() if row["is_seed"])

        update_resp = test_client.put(
            f"/api/report/templates/{seed_id}",
            json={
                "name": "Cannot Update",
                "description": "",
                "category": "",
                "notes": "",
                "config": {
                    "filters": {},
                    "columns": ["key"],
                    "sort_field": "created",
                    "sort_dir": "desc",
                    "group_by": None,
                    "include_excluded": False,
                },
            },
        )
        assert update_resp.status_code == 403

        delete_resp = test_client.delete(f"/api/report/templates/{seed_id}")
        assert delete_resp.status_code == 403

    def test_master_workbook_export_includes_index_and_seeded_reports(self, test_client):
        resp = test_client.get("/api/report/templates/master.xlsx")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers.get("content-type", "")

        workbook = load_workbook(BytesIO(resp.content))
        assert "Report Index" in workbook.sheetnames
        assert "First Response Time" in workbook.sheetnames
        assert "Backlog Size & Aging" in workbook.sheetnames

        index_ws = workbook["Report Index"]
        headers = [index_ws.cell(row=1, column=idx).value for idx in range(1, 9)]
        assert headers == [
            "Report",
            "Sheet",
            "Category",
            "Readiness",
            "View",
            "Rows",
            "Description",
            "Notes",
        ]
        report_names = [index_ws.cell(row=row_idx, column=1).value for row_idx in range(2, index_ws.max_row + 1)]
        assert "First Response Time" in report_names

        frt_ws = workbook["First Response Time"]
        assert frt_ws["A1"].value == "Report"
        assert frt_ws["B1"].value == "First Response Time"
        assert frt_ws["A3"].value == "Readiness"
        assert frt_ws["B3"].value == "ready"

    def test_master_workbook_only_includes_templates_marked_for_export(self, test_client):
        templates_resp = test_client.get("/api/report/templates")
        assert templates_resp.status_code == 200
        first_response_template = next(
            template for template in templates_resp.json() if template["name"] == "First Response Time"
        )

        toggle_resp = test_client.post(
            f"/api/report/templates/{first_response_template['id']}/export-selection",
            json={"include_in_master_export": False},
        )
        assert toggle_resp.status_code == 200
        assert toggle_resp.json()["include_in_master_export"] is False

        workbook_resp = test_client.get("/api/report/templates/master.xlsx")
        assert workbook_resp.status_code == 200
        workbook = load_workbook(BytesIO(workbook_resp.content))
        assert "Report Index" in workbook.sheetnames
        assert "First Response Time" not in workbook.sheetnames

        index_ws = workbook["Report Index"]
        report_names = [index_ws.cell(row=row_idx, column=1).value for row_idx in range(2, index_ws.max_row + 1)]
        assert "First Response Time" not in report_names

    def test_seed_template_export_selection_can_be_toggled_without_full_edit(self, test_client):
        templates_resp = test_client.get("/api/report/templates")
        assert templates_resp.status_code == 200
        seed_template = next(template for template in templates_resp.json() if template["is_seed"])

        toggle_resp = test_client.post(
            f"/api/report/templates/{seed_template['id']}/export-selection",
            json={"include_in_master_export": False},
        )
        assert toggle_resp.status_code == 200
        payload = toggle_resp.json()
        assert payload["id"] == seed_template["id"]
        assert payload["is_seed"] is True
        assert payload["include_in_master_export"] is False

    def test_template_insights_return_7d_30d_p95_and_window_field(self, test_client, mock_cache, monkeypatch):
        monkeypatch.setattr("routes_export._today_utc", lambda: date(2026, 3, 4))

        issues = []
        for offset in range(10):
            created_day = date(2026, 3, 4) - timedelta(days=offset)
            created_iso = f"{created_day.isoformat()}T10:00:00+00:00"
            for count_idx in range(2):
                issues.append(
                    _make_workload_issue(
                        key=f"OIT-OPEN-{offset}-{count_idx}",
                        summary=f"Open report issue {offset}-{count_idx}",
                        status="Open",
                        status_category="To Do",
                        assignee="Taylor Ops",
                        created=created_iso,
                        updated=created_iso,
                        oasisdev=False,
                    )
                )

        for offset in range(5):
            resolved_day = date(2026, 3, 4) - timedelta(days=offset)
            issues.append(
                _make_workload_issue(
                    key=f"OIT-RES-{offset}",
                    summary=f"Resolved issue {offset}",
                    status="Resolved",
                    status_category="Done",
                    assignee="Taylor Ops",
                    created="2026-01-10T10:00:00+00:00",
                    updated=f"{resolved_day.isoformat()}T13:00:00+00:00",
                    resolved=f"{resolved_day.isoformat()}T13:00:00+00:00",
                    oasisdev=False,
                )
            )

        mock_cache.get_all_issues.return_value = issues

        resp = test_client.get("/api/report/templates/insights")
        assert resp.status_code == 200
        data = resp.json()

        frt = next(item for item in data if item["template_name"] == "First Response Time")
        assert frt["window_field"] == "created"
        assert frt["window_field_label"] == "Created"
        assert frt["count_7d"] == 14
        assert frt["count_30d"] == 20
        assert frt["p95_daily_count_30d"] == 2.0
        assert len(frt["trend_30d"]) == 30

        mttr = next(item for item in data if item["template_name"] == "Mean Time to Resolution")
        assert mttr["window_field"] == "resolved"
        assert mttr["window_field_label"] == "Resolved"
        assert mttr["count_7d"] == 5
        assert mttr["count_30d"] == 5


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
