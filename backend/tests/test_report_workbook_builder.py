from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from models import ReportConfig, ReportTemplate
from report_workbook_builder import ReportWorkbookBuilder, _template_readiness


def _make_issue(
    *,
    key: str = "OIT-123",
    priority: str = "Low",
    status: str = "Open",
    status_category: str = "To Do",
    created: str = "2026-03-10T00:00:00+00:00",
    updated: str = "2026-03-10T00:00:00+00:00",
    resolved: str | None = None,
    labels: list[str] | None = None,
    components: list[str] | None = None,
) -> dict:
    return {
        "key": key,
        "fields": {
            "summary": "Example issue",
            "status": {"name": status, "statusCategory": {"name": status_category}},
            "priority": {"name": priority},
            "assignee": {"displayName": "Taylor Ops", "accountId": "acc-taylor"},
            "reporter": {"displayName": "Riley Requester", "accountId": "acc-riley"},
            "issuetype": {"name": "Service request"},
            "resolution": {"name": "Done"} if resolved else None,
            "created": created,
            "updated": updated,
            "resolutiondate": resolved,
            "labels": labels or [],
            "components": [{"name": value} for value in (components or [])],
            "customfield_11266": None,
            "customfield_11264": None,
            "customfield_11239": "Service requests",
            "customfield_10010": {"requestType": {"name": "Business Application Support"}},
            "customfield_10700": [],
            "attachment": [],
            "comment": {"total": 2, "comments": []},
        },
    }


def test_apply_changelog_tracks_reopens_priority_increases_and_assignee_changes():
    builder = ReportWorkbookBuilder(
        all_issues=[_make_issue()],
        site_scope="primary",
        today=date(2026, 3, 24),
        enable_changelog_fetch=False,
    )
    fact = builder._facts_by_key["OIT-123"]

    builder._apply_changelog(
        fact,
        [
            {
                "created": "2026-03-10T01:00:00+00:00",
                "items": [{"field": "assignee", "fromString": "Taylor Ops", "toString": "Jordan Tech"}],
            },
            {
                "created": "2026-03-10T02:00:00+00:00",
                "items": [{"field": "priority", "fromString": "Low", "toString": "High"}],
            },
            {
                "created": "2026-03-10T03:00:00+00:00",
                "items": [{"field": "status", "fromString": "Open", "toString": "Resolved"}],
            },
            {
                "created": "2026-03-10T04:00:00+00:00",
                "items": [{"field": "status", "fromString": "Resolved", "toString": "In Progress"}],
            },
            {
                "created": "2026-03-10T05:00:00+00:00",
                "items": [{"field": "assignee", "fromString": "Jordan Tech", "toString": "Morgan Lead"}],
            },
        ],
    )

    assert fact.assignee_change_count == 2
    assert fact.priority_increase_count == 1
    assert fact.reopen_count == 1
    assert fact.first_resolved_dt is not None
    assert fact.is_escalated is True
    assert "Reassigned more than once" in fact.escalation_reasons
    assert "Priority increased" in fact.escalation_reasons
    assert date(2026, 3, 10) in fact.escalation_event_dates


def test_build_data_gaps_marks_csat_as_gap():
    builder = ReportWorkbookBuilder(
        all_issues=[_make_issue(key="OIT-555")],
        site_scope="primary",
        today=date(2026, 3, 24),
        enable_changelog_fetch=False,
    )

    gaps = builder._build_data_gaps(template=None, report_name="Customer Satisfaction (CSAT)", facts=list(builder._facts_by_key.values()))

    assert any(gap.readiness == "gap" and "survey" in gap.limitation.lower() for gap in gaps)


def test_trend_rows_count_escalations_by_event_day_not_last_update_day():
    builder = ReportWorkbookBuilder(
        all_issues=[
            _make_issue(
                key="OIT-201",
                created="2026-03-01T00:00:00+00:00",
                updated="2026-03-06T00:00:00+00:00",
                resolved="2026-03-06T00:00:00+00:00",
                status="Resolved",
                status_category="Done",
            )
        ],
        site_scope="primary",
        today=date(2026, 3, 24),
        enable_changelog_fetch=False,
    )
    fact = builder._facts_by_key["OIT-201"]
    builder._apply_changelog(
        fact,
        [
            {
                "created": "2026-03-03T01:00:00+00:00",
                "items": [{"field": "assignee", "fromString": "Taylor Ops", "toString": "Jordan Tech"}],
            },
            {
                "created": "2026-03-05T02:00:00+00:00",
                "items": [{"field": "assignee", "fromString": "Jordan Tech", "toString": "Morgan Lead"}],
            },
        ],
    )

    trend_rows = {row["date"]: row for row in builder._build_trend_rows(list(builder._facts_by_key.values()))}

    assert trend_rows["2026-03-05"]["escalation_count"] == 1
    assert trend_rows["2026-03-06"]["escalation_count"] == 0


def test_template_readiness_marks_first_response_as_proxy_when_elapsed_is_missing():
    builder = ReportWorkbookBuilder(
        all_issues=[_make_issue(key="OIT-301", created="2026-03-20T00:00:00+00:00")],
        site_scope="primary",
        today=date(2026, 3, 24),
        enable_changelog_fetch=False,
    )
    template = ReportTemplate(
        id="tpl-fr",
        site_scope="primary",
        name="First Response Time",
        description="",
        category="Operational",
        notes="Ready when Jira response timers are present.",
        readiness="ready",
        is_seed=True,
        include_in_master_export=True,
        created_at="2026-03-24T00:00:00+00:00",
        updated_at="2026-03-24T00:00:00+00:00",
        created_by_email="",
        created_by_name="",
        updated_by_email="",
        updated_by_name="",
        config=ReportConfig(group_by="sla_first_response_status"),
    )

    assert _template_readiness(template, facts=list(builder._facts_by_key.values())) == "proxy"


def test_master_workbook_hides_dashboard_helper_columns_and_aligns_first_response_gap(tmp_path: Path):
    builder = ReportWorkbookBuilder(
        all_issues=[_make_issue(key="OIT-401", created="2026-03-20T00:00:00+00:00")],
        site_scope="primary",
        today=date(2026, 3, 24),
        enable_changelog_fetch=False,
    )
    template = ReportTemplate(
        id="tpl-fr",
        site_scope="primary",
        name="First Response Time",
        description="",
        category="Operational",
        notes="Ready when Jira response timers are present.",
        readiness="ready",
        is_seed=True,
        include_in_master_export=True,
        created_at="2026-03-24T00:00:00+00:00",
        updated_at="2026-03-24T00:00:00+00:00",
        created_by_email="",
        created_by_name="",
        updated_by_email="",
        updated_by_name="",
        config=ReportConfig(group_by="sla_first_response_status"),
    )
    path = tmp_path / "master.xlsx"

    builder.build_master_report(path=str(path), templates=[template])

    workbook = load_workbook(path)
    dashboard = workbook["Executive Dashboard"]
    report_index = workbook["Report Index"]
    data_gaps = workbook["Data Gaps"]
    helper_sheet = workbook["Executive Dashboard Data"]

    assert dashboard["I1"].value is None
    assert dashboard["M1"].value is None
    assert helper_sheet.sheet_state == "hidden"
    assert report_index["H2"].value == "proxy"
    assert data_gaps["C4"].value == "proxy"
