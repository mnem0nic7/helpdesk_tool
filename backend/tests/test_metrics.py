"""Tests for the metrics computation module (~34 tests)."""

from __future__ import annotations

import pytest

from metrics import (
    parse_dt,
    percentile,
    is_excluded,
    matches_libra_support_filter,
    map_status_bucket,
    _is_open,
    extract_sla_status,
    compute_headline_metrics,
    compute_monthly_volumes,
    compute_age_buckets,
    compute_ttr_distribution,
    compute_priority_counts,
    compute_assignee_stats,
    issue_to_row,
)


# ===== parse_dt =====

class TestParseDt:
    def test_valid_iso(self):
        dt = parse_dt("2026-02-20T12:00:00+00:00")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 2

    def test_z_suffix(self):
        dt = parse_dt("2026-01-15T09:30:00Z")
        assert dt is not None
        assert dt.hour == 9

    def test_none_input(self):
        assert parse_dt(None) is None

    def test_empty_string(self):
        assert parse_dt("") is None

    def test_invalid_string(self):
        assert parse_dt("not-a-date") is None


# ===== percentile =====

class TestPercentile:
    def test_empty_returns_none(self):
        assert percentile([], 50) is None

    def test_single_value(self):
        assert percentile([42.0], 50) == 42.0

    def test_median(self):
        assert percentile([10.0, 20.0, 30.0], 50) == 20.0

    def test_p90(self):
        data = list(range(1, 101))
        result = percentile([float(x) for x in data], 90)
        assert result is not None
        assert abs(result - 90.1) < 0.5


# ===== is_excluded =====

class TestIsExcluded:
    def test_excluded_by_non_tracked_key_prefix(self):
        issue = {"key": "MSD-100", "fields": {"labels": [], "summary": "Moved ticket"}}
        assert is_excluded(issue) is True

    def test_excluded_by_non_tracked_project_key(self):
        issue = {
            "key": "OIT-100",
            "fields": {"project": {"key": "MD"}, "labels": [], "summary": "Moved ticket"},
        }
        assert is_excluded(issue) is True

    def test_excluded_by_label(self):
        issue = {"fields": {"labels": ["oasisdev"], "summary": "Normal"}}
        assert is_excluded(issue) is True

    def test_excluded_case_insensitive_label(self):
        issue = {"fields": {"labels": ["OasisDev"], "summary": "Normal"}}
        assert is_excluded(issue) is True

    def test_excluded_by_summary(self):
        issue = {"fields": {"labels": [], "summary": "oasisdev test thing"}}
        assert is_excluded(issue) is True

    def test_normal_not_excluded(self):
        issue = {"fields": {"labels": ["production"], "summary": "Normal ticket"}}
        assert is_excluded(issue) is False


# ===== map_status_bucket =====

class TestMapStatusBucket:
    def test_active(self):
        assert map_status_bucket("In Progress") == "Active"

    def test_paused(self):
        assert map_status_bucket("Waiting for customer") == "Paused"

    def test_terminal(self):
        assert map_status_bucket("Resolved") == "Terminal"

    def test_fuzzy_substring(self):
        # "waiting for customer review" contains "waiting for customer"
        assert map_status_bucket("waiting for customer review") == "Paused"

    def test_none_defaults_paused(self):
        # Empty string fuzzy-matches "pending" (substring), so returns Paused
        assert map_status_bucket(None) == "Paused"

    def test_unknown_defaults_active(self):
        assert map_status_bucket("Some Random Status") == "Active"


class TestOpenDetection:
    def test_done_status_category_is_terminal_even_with_custom_name(self):
        issue = {
            "fields": {
                "status": {
                    "name": "Completed by automation",
                    "statusCategory": {"name": "Done"},
                }
            }
        }
        assert _is_open(issue) is False


# ===== extract_sla_status =====

class TestExtractSlaStatus:
    def test_met(self):
        sla = {"completedCycles": [{"breached": False}]}
        assert extract_sla_status(sla) == "Met"

    def test_breached(self):
        sla = {"completedCycles": [{"breached": True}]}
        assert extract_sla_status(sla) == "BREACHED"

    def test_running(self):
        sla = {"ongoingCycle": {"breached": False, "paused": False}}
        assert extract_sla_status(sla) == "Running"

    def test_paused(self):
        sla = {"ongoingCycle": {"breached": False, "paused": True}}
        assert extract_sla_status(sla) == "Paused"

    def test_empty(self):
        assert extract_sla_status(None) == ""
        assert extract_sla_status({}) == ""


# ===== compute_headline_metrics =====

class TestComputeHeadlineMetrics:
    def test_basic_counts(self, filtered_issues, freeze_time):
        result = compute_headline_metrics(filtered_issues, excluded_count=2)
        assert result["total_tickets"] == 4
        assert result["open_backlog"] == 2  # OIT-100, OIT-200
        assert result["resolved"] == 2  # OIT-300, OIT-400
        assert result["excluded_count"] == 2

    def test_resolution_rate(self, filtered_issues, freeze_time):
        result = compute_headline_metrics(filtered_issues)
        assert result["resolution_rate"] == 50.0

    def test_ttr_percentiles(self, filtered_issues, freeze_time):
        result = compute_headline_metrics(filtered_issues)
        # Two resolved issues: 72h TTR and 240h TTR
        assert result["median_ttr_hours"] is not None
        assert result["p90_ttr_hours"] is not None

    def test_stale_count(self, filtered_issues, freeze_time):
        result = compute_headline_metrics(filtered_issues)
        # _STALE_DAYS = 1 (tickets need daily updates)
        # OIT-200 updated 2026-02-15, frozen now 2026-03-04 => ~17 days >= 1 => stale
        # OIT-100 updated 2026-03-03T10:00, frozen 2026-03-04T12:00 => ~1.08 days >= 1 => stale
        assert result["stale_count"] == 2

    def test_raw_issue_list_excludes_oasisdev(self, sample_issues, freeze_time):
        result = compute_headline_metrics(sample_issues)
        assert result["total_tickets"] == 4
        assert result["open_backlog"] == 2
        assert result["resolved"] == 2
        assert result["excluded_count"] == 2

    def test_done_category_custom_status_not_counted_as_stale(self, freeze_time):
        issue = {
            "key": "OIT-999",
            "fields": {
                "summary": "Recently completed but custom-done name",
                "status": {
                    "name": "Completed by automation",
                    "statusCategory": {"name": "Done"},
                },
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Agent"},
                "reporter": {"displayName": "Reporter"},
                "issuetype": {"name": "Incident"},
                "created": "2026-02-01T10:00:00+00:00",
                "updated": "2026-02-01T12:00:00+00:00",
                "resolutiondate": "2026-02-01T12:00:00+00:00",
                "labels": [],
            },
        }
        result = compute_headline_metrics([issue])
        assert result["open_backlog"] == 0
        assert result["resolved"] == 1
        assert result["stale_count"] == 0

    def test_empty_list(self, freeze_time):
        result = compute_headline_metrics([])
        assert result["total_tickets"] == 0
        assert result["median_ttr_hours"] is None

    def test_stale_count_excludes_waiting_for_customer_and_pending_on_primary(self, freeze_time):
        waiting = {
            "key": "OIT-701",
            "fields": {
                "summary": "Waiting on requester",
                "status": {"name": "Waiting For Customer", "statusCategory": {"name": "In Progress"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Agent"},
                "reporter": {"displayName": "Reporter"},
                "issuetype": {"name": "Incident"},
                "created": "2026-02-01T10:00:00+00:00",
                "updated": "2026-02-20T10:00:00+00:00",
                "resolutiondate": None,
                "labels": [],
            },
        }
        pending = {
            "key": "OIT-702",
            "fields": {
                "summary": "Pending vendor action",
                "status": {"name": "Pending", "statusCategory": {"name": "In Progress"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Agent"},
                "reporter": {"displayName": "Reporter"},
                "issuetype": {"name": "Incident"},
                "created": "2026-02-01T10:00:00+00:00",
                "updated": "2026-02-20T10:00:00+00:00",
                "resolutiondate": None,
                "labels": [],
            },
        }
        result = compute_headline_metrics([waiting, pending], scope="primary")
        assert result["open_backlog"] == 2
        assert result["stale_count"] == 0

    def test_stale_count_keeps_waiting_for_customer_on_oasisdev_scope(self, freeze_time):
        waiting = {
            "key": "OIT-708",
            "fields": {
                "summary": "Waiting on requester",
                "status": {"name": "Waiting For Customer", "statusCategory": {"name": "In Progress"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Agent"},
                "reporter": {"displayName": "Reporter"},
                "issuetype": {"name": "Incident"},
                "created": "2026-02-01T10:00:00+00:00",
                "updated": "2026-02-20T10:00:00+00:00",
                "resolutiondate": None,
                "labels": ["oasisdev"],
            },
        }
        result = compute_headline_metrics([waiting], scope="oasisdev")
        assert result["open_backlog"] == 1
        assert result["stale_count"] == 1

    def test_stale_count_excludes_onboarding_and_offboarding_categories_on_primary(self, freeze_time):
        onboarding = {
            "key": "OIT-703",
            "fields": {
                "summary": "New hire laptop setup",
                "status": {"name": "Open", "statusCategory": {"name": "To Do"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Agent"},
                "reporter": {"displayName": "Reporter"},
                "issuetype": {"name": "Incident"},
                "created": "2026-02-01T10:00:00+00:00",
                "updated": "2026-02-20T10:00:00+00:00",
                "resolutiondate": None,
                "labels": [],
                "customfield_10010": {"requestType": {"name": "Onboard new employees"}},
            },
        }
        offboarding = {
            "key": "OIT-704",
            "fields": {
                "summary": "Disable terminated user",
                "status": {"name": "Open", "statusCategory": {"name": "To Do"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Agent"},
                "reporter": {"displayName": "Reporter"},
                "issuetype": {"name": "Incident"},
                "created": "2026-02-01T10:00:00+00:00",
                "updated": "2026-02-20T10:00:00+00:00",
                "resolutiondate": None,
                "labels": [],
                "customfield_11239": "Offboarding",
            },
        }
        result = compute_headline_metrics([onboarding, offboarding], scope="primary")
        assert result["open_backlog"] == 2
        assert result["stale_count"] == 0


# ===== compute_monthly_volumes =====

class TestComputeMonthlyVolumes:
    def test_month_keys(self, sample_issues, freeze_time):
        result = compute_monthly_volumes(sample_issues)
        months = [r["month"] for r in result]
        # Should contain months from our issue dates
        assert "2026-02" in months

    def test_net_flow(self, sample_issues, freeze_time):
        result = compute_monthly_volumes(sample_issues)
        for row in result:
            assert row["net_flow"] == row["created"] - row["resolved"]


# ===== compute_age_buckets =====

class TestComputeAgeBuckets:
    def test_bucket_assignment(self, sample_issues, freeze_time):
        result = compute_age_buckets(sample_issues)
        buckets = {r["bucket"]: r["count"] for r in result}
        # OIT-100 open, created 2026-02-01, age ~31 days => 30+d
        # OIT-200 open, created 2026-01-10, age ~53 days => 30+d
        # (Excluded issues are filtered out by _filter_issues inside compute_age_buckets)
        total_open = sum(r["count"] for r in result)
        assert total_open == 2
        assert buckets.get("30+d", 0) == 2

    def test_age_buckets_exclude_oasisdev_but_keep_libra_support_on_primary(self, freeze_time):
        libra_issue = {
            "key": "OIT-705",
            "fields": {
                "summary": "Libra inbound support ticket",
                "status": {"name": "Open", "statusCategory": {"name": "To Do"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Agent"},
                "reporter": {"displayName": "Reporter"},
                "issuetype": {"name": "Incident"},
                "created": "2026-02-01T10:00:00+00:00",
                "updated": "2026-02-20T10:00:00+00:00",
                "resolutiondate": None,
                "labels": ["Libra_Support"],
            },
        }
        oasisdev_issue = {
            "key": "OIT-706",
            "fields": {
                "summary": "oasisdev test ticket",
                "status": {"name": "Open", "statusCategory": {"name": "To Do"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Agent"},
                "reporter": {"displayName": "Reporter"},
                "issuetype": {"name": "Incident"},
                "created": "2026-02-01T10:00:00+00:00",
                "updated": "2026-02-20T10:00:00+00:00",
                "resolutiondate": None,
                "labels": ["oasisdev"],
            },
        }
        normal_issue = {
            "key": "OIT-707",
            "fields": {
                "summary": "Normal production ticket",
                "status": {"name": "Open", "statusCategory": {"name": "To Do"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Agent"},
                "reporter": {"displayName": "Reporter"},
                "issuetype": {"name": "Incident"},
                "created": "2026-02-01T10:00:00+00:00",
                "updated": "2026-02-20T10:00:00+00:00",
                "resolutiondate": None,
                "labels": [],
            },
        }
        result = compute_age_buckets([libra_issue, oasisdev_issue, normal_issue], scope="primary")
        assert sum(row["count"] for row in result) == 2

    def test_matches_libra_support_filter(self):
        libra_issue = {"fields": {"labels": ["Libra_Support", "vip"]}}
        normal_issue = {"fields": {"labels": ["vip"]}}
        unlabeled_issue = {"fields": {"labels": []}}

        assert matches_libra_support_filter(libra_issue, None) is True
        assert matches_libra_support_filter(libra_issue, "all") is True
        assert matches_libra_support_filter(libra_issue, "libra_support") is True
        assert matches_libra_support_filter(libra_issue, "non_libra_support") is False
        assert matches_libra_support_filter(normal_issue, "libra_support") is False
        assert matches_libra_support_filter(normal_issue, "non_libra_support") is True
        assert matches_libra_support_filter(unlabeled_issue, "non_libra_support") is True


# ===== compute_ttr_distribution =====

class TestComputeTtrDistribution:
    def test_bucket_assignment(self, sample_issues, freeze_time):
        result = compute_ttr_distribution(sample_issues)
        # OIT-300: 72h TTR exactly; boundary is < 72 for "1-3d", so 72h falls into "3-7d"
        # OIT-400: 240h TTR => "7-14d" bucket (240h = 10d)
        buckets = {r["bucket"]: r["count"] for r in result}
        assert buckets.get("3-7d", 0) == 1
        assert buckets.get("7-14d", 0) == 1


# ===== compute_priority_counts =====

class TestComputePriorityCounts:
    def test_order_highest_first(self, sample_issues, freeze_time):
        result = compute_priority_counts(sample_issues)
        priorities = [r["priority"] for r in result]
        # High should come before Medium, Medium before Low
        assert priorities.index("High") < priorities.index("Medium")
        assert priorities.index("Medium") < priorities.index("Low")

    def test_counts_match(self, sample_issues, freeze_time):
        result = compute_priority_counts(sample_issues)
        priority_map = {r["priority"]: r["total"] for r in result}
        # After filtering excluded: OIT-100(High), OIT-200(Medium), OIT-300(High), OIT-400(Low)
        assert priority_map.get("High", 0) == 2
        assert priority_map.get("Medium", 0) == 1
        assert priority_map.get("Low", 0) == 1


# ===== compute_assignee_stats =====

class TestComputeAssigneeStats:
    def test_per_assignee(self, sample_issues, freeze_time):
        result = compute_assignee_stats(sample_issues)
        names = {r["name"] for r in result}
        assert "Alice Admin" in names
        assert "Bob Builder" in names

    def test_resolved_count(self, sample_issues, freeze_time):
        result = compute_assignee_stats(sample_issues)
        alice = next(r for r in result if r["name"] == "Alice Admin")
        # Alice: OIT-100 (open), OIT-300 (resolved) => resolved=1, open=1
        assert alice["resolved"] == 1
        assert alice["open"] == 1

    def test_median_ttr(self, sample_issues, freeze_time):
        result = compute_assignee_stats(sample_issues)
        alice = next(r for r in result if r["name"] == "Alice Admin")
        # Alice has 1 resolved ticket with 72h TTR
        assert alice["median_ttr"] == 72.0


# ===== issue_to_row =====

class TestIssueToRow:
    def test_complete_issue(self, sample_issues, freeze_time):
        row = issue_to_row(sample_issues[0])  # OIT-100
        assert row["key"] == "OIT-100"
        assert row["summary"] == "Active open ticket"
        assert row["status"] == "In Progress"
        assert row["priority"] == "High"
        assert row["assignee"] == "Alice Admin"
        assert row["excluded"] is False
        assert row["age_days"] is not None  # open ticket should have age

    def test_minimal_issue(self, freeze_time):
        issue = {"key": "OIT-999", "fields": {}}
        row = issue_to_row(issue)
        assert row["key"] == "OIT-999"
        assert row["summary"] == ""
        assert row["status"] == ""
        assert row["assignee"] == ""
        assert row["calendar_ttr_hours"] is None

    def test_request_type_from_customfield_11102(self, freeze_time):
        issue = {
            "key": "OIT-555",
            "fields": {
                "customfield_10010": None,
                "customfield_11102": {
                    "requestType": {"id": "123", "name": "Business Application Support"}
                },
            },
        }
        row = issue_to_row(issue)
        assert row["request_type"] == "Business Application Support"
        assert row["request_type_id"] == "123"

    def test_extracts_occ_ticket_id_from_description(self, freeze_time):
        issue = {
            "key": "OIT-556",
            "fields": {
                "description": "OCC Ticket Created By: Libra PhishER | OCC Ticket ID: LIBRA-SR-075203",
            },
        }
        row = issue_to_row(issue)
        assert row["occ_ticket_id"] == "LIBRA-SR-075203"

    def test_response_followup_marks_ticket_met_when_response_and_cadence_hold(self, freeze_time):
        issue = {
            "key": "OIT-701",
            "fields": {
                "summary": "Cadence met",
                "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                "reporter": {"displayName": "Riley Requester", "accountId": "acc-riley"},
                "issuetype": {"name": "Incident"},
                "created": "2026-03-02T08:00:00+00:00",
                "updated": "2026-03-03T05:00:00+00:00",
                "resolutiondate": "2026-03-03T05:00:00+00:00",
                "customfield_11266": {"completedCycles": [{"breached": False}]},
                "comment": {
                    "total": 3,
                    "comments": [
                        {
                            "created": "2026-03-02T08:30:00+00:00",
                            "updated": "2026-03-02T08:30:00+00:00",
                            "author": {"displayName": "Riley Requester", "accountId": "acc-riley"},
                        },
                        {
                            "created": "2026-03-02T09:00:00+00:00",
                            "updated": "2026-03-02T09:00:00+00:00",
                            "author": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                        },
                        {
                            "created": "2026-03-02T22:00:00+00:00",
                            "updated": "2026-03-02T22:00:00+00:00",
                            "author": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                        },
                    ],
                },
            },
        }

        row = issue_to_row(issue)

        assert row["response_followup_status"] == "Met"
        assert row["first_response_2h_status"] == "Met"
        assert row["daily_followup_status"] == "Met"
        assert row["last_support_touch_date"] == "2026-03-02T22:00:00+00:00"
        assert row["support_touch_count"] == 2

    def test_response_followup_breaches_when_first_response_misses_two_hours(self, freeze_time):
        issue = {
            "key": "OIT-702",
            "fields": {
                "summary": "Late first response",
                "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
                "priority": {"name": "High"},
                "assignee": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                "reporter": {"displayName": "Riley Requester", "accountId": "acc-riley"},
                "issuetype": {"name": "Incident"},
                "created": "2026-03-02T08:00:00+00:00",
                "updated": "2026-03-02T14:00:00+00:00",
                "resolutiondate": "2026-03-02T14:00:00+00:00",
                "comment": {
                    "total": 1,
                    "comments": [
                        {
                            "created": "2026-03-02T11:30:00+00:00",
                            "updated": "2026-03-02T11:30:00+00:00",
                            "author": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                        },
                    ],
                },
            },
        }

        row = issue_to_row(issue)

        assert row["first_response_2h_status"] == "BREACHED"
        assert row["daily_followup_status"] == "Met"
        assert row["response_followup_status"] == "BREACHED"

    def test_response_followup_breaches_when_daily_touch_gap_exceeds_24_hours(self, freeze_time):
        issue = {
            "key": "OIT-703",
            "fields": {
                "summary": "Follow-up gap",
                "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                "reporter": {"displayName": "Riley Requester", "accountId": "acc-riley"},
                "issuetype": {"name": "Incident"},
                "created": "2026-03-01T08:00:00+00:00",
                "updated": "2026-03-03T14:00:00+00:00",
                "resolutiondate": "2026-03-03T14:00:00+00:00",
                "customfield_11266": {"completedCycles": [{"breached": False}]},
                "comment": {
                    "total": 2,
                    "comments": [
                        {
                            "created": "2026-03-01T09:00:00+00:00",
                            "updated": "2026-03-01T09:00:00+00:00",
                            "author": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                        },
                        {
                            "created": "2026-03-02T12:30:00+00:00",
                            "updated": "2026-03-02T12:30:00+00:00",
                            "author": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                        },
                    ],
                },
            },
        }

        row = issue_to_row(issue)

        assert row["first_response_2h_status"] == "Met"
        assert row["daily_followup_status"] == "BREACHED"
        assert row["response_followup_status"] == "BREACHED"

    def test_response_followup_stays_running_for_open_ticket_inside_response_window(self, freeze_time):
        issue = {
            "key": "OIT-704",
            "fields": {
                "summary": "Awaiting first touch",
                "status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                "reporter": {"displayName": "Riley Requester", "accountId": "acc-riley"},
                "issuetype": {"name": "Incident"},
                "created": "2026-03-04T11:15:00+00:00",
                "updated": "2026-03-04T11:15:00+00:00",
                "resolutiondate": None,
                "comment": {"total": 0, "comments": []},
            },
        }

        row = issue_to_row(issue)

        assert row["first_response_2h_status"] == "Running"
        assert row["daily_followup_status"] == "Running"
        assert row["response_followup_status"] == "Running"
        assert row["support_touch_count"] == 0

    def test_response_followup_ignores_internal_movedocs_fallback_audit_notes(self, freeze_time):
        issue = {
            "key": "OIT-704A",
            "fields": {
                "summary": "Audit note should not count",
                "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                "reporter": {"displayName": "Riley Requester", "accountId": "acc-riley"},
                "issuetype": {"name": "Incident"},
                "created": "2026-03-02T08:00:00+00:00",
                "updated": "2026-03-03T05:00:00+00:00",
                "resolutiondate": "2026-03-03T05:00:00+00:00",
                "customfield_11266": {"completedCycles": [{"breached": False}]},
                "comment": {
                    "total": 1,
                    "comments": [
                        {
                            "created": "2026-03-02T09:00:00+00:00",
                            "updated": "2026-03-02T09:00:00+00:00",
                            "author": {"displayName": "it-app", "accountId": "acc-it-app"},
                            "body": "[MoveDocs fallback audit]\n[MoveDocs fallback actor: Test User <test@example.com>]\n\nAction: updated priority",
                        },
                    ],
                },
            },
        }

        row = issue_to_row(issue)

        assert row["support_touch_count"] == 0
        assert row["daily_followup_status"] == "BREACHED"

    def test_response_followup_prefers_authoritative_followup_fields_when_present(self, freeze_time, monkeypatch):
        import metrics

        monkeypatch.setattr(metrics, "JIRA_FOLLOWUP_STATUS_FIELD_ID", "customfield_20001")
        monkeypatch.setattr(metrics, "JIRA_FOLLOWUP_LAST_PUBLIC_AGENT_TOUCH_FIELD_ID", "customfield_20002")
        monkeypatch.setattr(metrics, "JIRA_FOLLOWUP_PUBLIC_AGENT_TOUCH_COUNT_FIELD_ID", "customfield_20003")

        issue = {
            "key": "OIT-705",
            "fields": {
                "summary": "Authoritative public touch fields",
                "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                "reporter": {"displayName": "Riley Requester", "accountId": "acc-riley"},
                "issuetype": {"name": "Incident"},
                "created": "2026-03-02T08:00:00+00:00",
                "updated": "2026-03-03T05:00:00+00:00",
                "resolutiondate": "2026-03-03T05:00:00+00:00",
                "customfield_11266": {"completedCycles": [{"breached": False}]},
                "customfield_20001": {"value": "Met"},
                "customfield_20002": "2026-03-02T22:00:00+00:00",
                "customfield_20003": 2,
                "comment": {
                    "total": 0,
                    "comments": [],
                },
            },
        }

        row = issue_to_row(issue)

        assert row["first_response_2h_status"] == "Met"
        assert row["daily_followup_status"] == "Met"
        assert row["response_followup_status"] == "Met"
        assert row["last_support_touch_date"] == "2026-03-02T22:00:00+00:00"
        assert row["support_touch_count"] == 2
        assert row["first_response_authoritative"] is True
        assert row["followup_authoritative"] is True

    def test_response_followup_prefers_local_authoritative_followup_cache_when_present(self, freeze_time):
        issue = {
            "key": "OIT-706",
            "fields": {
                "summary": "Local authoritative public touch cache",
                "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                "reporter": {"displayName": "Riley Requester", "accountId": "acc-riley"},
                "issuetype": {"name": "Incident"},
                "created": "2026-03-02T08:00:00+00:00",
                "updated": "2026-03-03T05:00:00+00:00",
                "resolutiondate": "2026-03-03T05:00:00+00:00",
                "customfield_11266": {"completedCycles": [{"breached": False}]},
                "_movedocs_followup_status": "Met",
                "_movedocs_followup_last_touch_at": "2026-03-02T22:00:00+00:00",
                "_movedocs_followup_touch_count": 2,
                "comment": {
                    "total": 0,
                    "comments": [],
                },
            },
        }

        row = issue_to_row(issue)

        assert row["first_response_2h_status"] == "Met"
        assert row["daily_followup_status"] == "Met"
        assert row["response_followup_status"] == "Met"
        assert row["last_support_touch_date"] == "2026-03-02T22:00:00+00:00"
        assert row["support_touch_count"] == 2
        assert row["first_response_authoritative"] is True
        assert row["followup_authoritative"] is True

    def test_response_followup_uses_public_comment_timeline_when_first_response_sla_is_blank(self, freeze_time):
        issue = {
            "key": "MSD-10117",
            "fields": {
                "summary": "Authoritative public reply with blank SLA timer",
                "status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                "reporter": {"displayName": "Riley Requester", "accountId": "acc-riley"},
                "issuetype": {"name": "[System] Service request"},
                "created": "2026-03-02T08:00:00+00:00",
                "updated": "2026-03-02T12:00:00+00:00",
                "resolutiondate": None,
                "customfield_11266": {
                    "id": "2",
                    "name": "Time to first response",
                    "_links": {"self": "https://keyjira.atlassian.net/rest/servicedeskapi/request/123/sla/2"},
                    "completedCycles": [],
                    "slaDisplayFormat": "NEW_SLA_FORMAT",
                },
                "_movedocs_followup_status": "Running",
                "_movedocs_followup_last_touch_at": "2026-03-02T08:45:00+00:00",
                "_movedocs_followup_touch_count": 1,
                "comment": {
                    "total": 2,
                    "comments": [
                        {
                            "created": "2026-03-02T08:45:00+00:00",
                            "updated": "2026-03-02T08:45:00+00:00",
                            "author": {"displayName": "OSIJIRAOCC", "accountId": "acc-occ"},
                            "jsdPublic": True,
                            "body": "Initial public response",
                        },
                        {
                            "created": "2026-03-02T09:30:00+00:00",
                            "updated": "2026-03-02T09:30:00+00:00",
                            "author": {"displayName": "Alex Agent", "accountId": "acc-alex"},
                            "jsdPublic": False,
                            "body": "Internal note",
                        },
                    ],
                },
            },
        }

        row = issue_to_row(issue)

        assert row["first_response_2h_status"] == "Met"
        assert row["first_response_authoritative"] is True
        assert row["daily_followup_status"] == "Running"
        assert row["followup_authoritative"] is True
