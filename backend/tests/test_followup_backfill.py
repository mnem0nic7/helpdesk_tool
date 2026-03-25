from __future__ import annotations

from datetime import datetime, timezone

from scripts import backfill_followup_fields as script


def _issue(*, resolved: str | None = None, status_category: str = "Done") -> dict:
    return {
        "key": "OIT-900",
        "fields": {
            "status": {"name": "Resolved" if resolved else "In Progress", "statusCategory": {"name": status_category}},
            "resolutiondate": resolved,
        },
    }


def _comment(
    *,
    created: str,
    public: bool = True,
    account_id: str = "acc-agent",
) -> dict:
    return {
        "id": "1",
        "public": public,
        "created": {"iso8601": created},
        "author": {"accountId": account_id, "displayName": "Agent"},
    }


def test_compute_followup_marks_met_when_public_agent_cadence_holds():
    issue = _issue(resolved="2026-03-03T05:00:00+00:00")
    comments = [
        _comment(created="2026-03-02T09:00:00+00:00"),
        _comment(created="2026-03-02T22:00:00+00:00"),
    ]

    result = script.compute_followup_from_public_agent_comments(
        issue,
        comments,
        agent_account_ids={"acc-agent"},
        now=datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc),
    )

    assert result.status == "Met"
    assert result.touch_count == 2
    assert result.last_touch_at == "2026-03-02T22:00:00+00:00"
    assert result.breached_at == ""


def test_compute_followup_ignores_internal_and_customer_comments():
    issue = _issue(resolved="2026-03-03T05:00:00+00:00")
    comments = [
        _comment(created="2026-03-02T09:00:00+00:00", public=False),
        _comment(created="2026-03-02T10:00:00+00:00", account_id="acc-customer"),
    ]

    result = script.compute_followup_from_public_agent_comments(
        issue,
        comments,
        agent_account_ids={"acc-agent"},
        now=datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc),
    )

    assert result.status == "BREACHED"
    assert result.touch_count == 0
    assert result.last_touch_at == ""


def test_compute_followup_marks_breached_when_gap_exceeds_24_hours():
    issue = _issue(resolved="2026-03-03T14:00:00+00:00")
    comments = [
        _comment(created="2026-03-01T09:00:00+00:00"),
        _comment(created="2026-03-02T12:30:00+00:00"),
    ]

    result = script.compute_followup_from_public_agent_comments(
        issue,
        comments,
        agent_account_ids={"acc-agent"},
        now=datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc),
    )

    assert result.status == "BREACHED"
    assert result.breached_at == "2026-03-02T09:00:00+00:00"


def test_compute_followup_stays_running_for_open_ticket_inside_window():
    issue = _issue(resolved=None, status_category="In Progress")
    comments = [_comment(created="2026-03-04T08:00:00+00:00")]

    result = script.compute_followup_from_public_agent_comments(
        issue,
        comments,
        agent_account_ids={"acc-agent"},
        now=datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc),
    )

    assert result.status == "Running"
    assert result.touch_count == 1
