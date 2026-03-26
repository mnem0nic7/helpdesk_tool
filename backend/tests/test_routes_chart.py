"""Tests for chart data routes (~14 tests)."""

from __future__ import annotations

import pytest


class TestChartDataEndpoint:
    """POST /api/chart/data"""

    def test_count_by_status(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "status",
            "metric": "count",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert data["group_by"] == "status"
        assert data["metric"] == "count"

    def test_count_by_priority(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "priority",
            "metric": "count",
        })
        assert resp.status_code == 200
        labels = [d["label"] for d in resp.json()["data"]]
        assert len(labels) > 0

    def test_count_by_assignee(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "assignee",
            "metric": "count",
        })
        assert resp.status_code == 200

    def test_metric_open(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "status",
            "metric": "open",
        })
        assert resp.status_code == 200

    def test_metric_resolved(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "status",
            "metric": "resolved",
        })
        assert resp.status_code == 200

    def test_metric_avg_ttr(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "priority",
            "metric": "avg_ttr",
        })
        assert resp.status_code == 200

    def test_metric_median_ttr(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "priority",
            "metric": "median_ttr",
        })
        assert resp.status_code == 200

    def test_metric_avg_age(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "status",
            "metric": "avg_age",
        })
        assert resp.status_code == 200

    def test_with_filters(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "status",
            "metric": "count",
            "filters": {"priority": "High"},
        })
        assert resp.status_code == 200

    def test_include_excluded(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "status",
            "metric": "count",
            "include_excluded": True,
        })
        assert resp.status_code == 200

    def test_default_chart_data_excludes_oasisdev(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "status",
            "metric": "count",
        })
        assert resp.status_code == 200
        total = sum(item["value"] for item in resp.json()["data"])
        assert total == 4

        resp_including_excluded = test_client.post("/api/chart/data", json={
            "group_by": "status",
            "metric": "count",
            "include_excluded": True,
        })
        assert resp_including_excluded.status_code == 200
        total_with_excluded = sum(item["value"] for item in resp_including_excluded.json()["data"])
        assert total_with_excluded == 4

    def test_chart_data_honors_libra_support_filter(self, test_client, mock_cache):
        libra_issue = {
            "key": "OIT-900",
            "fields": {
                "summary": "Libra request",
                "status": {"name": "Open", "statusCategory": {"name": "To Do"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Agent"},
                "reporter": {"displayName": "Reporter"},
                "issuetype": {"name": "[System] Service request"},
                "created": "2026-03-01T10:00:00+00:00",
                "updated": "2026-03-02T10:00:00+00:00",
                "resolutiondate": None,
                "labels": ["Libra_Support"],
            },
        }
        normal_issue = {
            "key": "OIT-901",
            "fields": {
                "summary": "Non-libra request",
                "status": {"name": "Open", "statusCategory": {"name": "To Do"}},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Agent"},
                "reporter": {"displayName": "Reporter"},
                "issuetype": {"name": "[System] Service request"},
                "created": "2026-03-01T10:00:00+00:00",
                "updated": "2026-03-02T10:00:00+00:00",
                "resolutiondate": None,
                "labels": [],
            },
        }
        mock_cache.get_all_issues.return_value = [libra_issue, normal_issue]
        mock_cache.get_filtered_issues.return_value = [libra_issue, normal_issue]

        resp = test_client.post("/api/chart/data", json={
            "group_by": "status",
            "metric": "count",
            "filters": {"libra_support": "libra_support"},
        })
        assert resp.status_code == 200
        total = sum(item["value"] for item in resp.json()["data"])
        assert total == 1

    def test_sorted_desc(self, test_client):
        resp = test_client.post("/api/chart/data", json={
            "group_by": "priority",
            "metric": "count",
        })
        data = resp.json()["data"]
        if len(data) > 1:
            values = [d["value"] for d in data]
            assert values == sorted(values, reverse=True)


class TestChartTimeseriesEndpoint:
    """POST /api/chart/timeseries"""

    def test_weekly(self, test_client):
        resp = test_client.post("/api/chart/timeseries", json={
            "bucket": "week",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["bucket"] == "week"
        assert isinstance(data["data"], list)

    def test_monthly(self, test_client):
        resp = test_client.post("/api/chart/timeseries", json={
            "bucket": "month",
        })
        assert resp.status_code == 200
        assert resp.json()["bucket"] == "month"

    def test_with_filters(self, test_client):
        resp = test_client.post("/api/chart/timeseries", json={
            "bucket": "week",
            "filters": {"priority": "High"},
        })
        assert resp.status_code == 200
