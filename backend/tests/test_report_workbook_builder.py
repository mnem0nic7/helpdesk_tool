from __future__ import annotations

from datetime import date

from report_workbook_builder import ReportWorkbookBuilder


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


def test_build_data_gaps_marks_csat_as_gap():
    builder = ReportWorkbookBuilder(
        all_issues=[_make_issue(key="OIT-555")],
        site_scope="primary",
        today=date(2026, 3, 24),
        enable_changelog_fetch=False,
    )

    gaps = builder._build_data_gaps(template=None, report_name="Customer Satisfaction (CSAT)", facts=list(builder._facts_by_key.values()))

    assert any(gap.readiness == "gap" and "survey" in gap.limitation.lower() for gap in gaps)
