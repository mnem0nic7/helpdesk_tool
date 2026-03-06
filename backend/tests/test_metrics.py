"""Tests for the metrics computation module (~34 tests)."""

from __future__ import annotations

import pytest

from metrics import (
    parse_dt,
    percentile,
    is_excluded,
    map_status_bucket,
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

    def test_empty_list(self, freeze_time):
        result = compute_headline_metrics([])
        assert result["total_tickets"] == 0
        assert result["median_ttr_hours"] is None


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
