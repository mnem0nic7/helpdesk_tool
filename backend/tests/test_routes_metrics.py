"""Tests for metrics and SLA routes (~6 tests)."""

from __future__ import annotations

import pytest


class TestMetricsEndpoint:
    """GET /api/metrics"""

    def test_all_sections_present(self, test_client):
        resp = test_client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "headline" in data
        assert "weekly_volumes" in data
        assert "age_buckets" in data
        assert "ttr_distribution" in data
        assert "priority_counts" in data
        assert "assignee_stats" in data

    def test_headline_values(self, test_client):
        resp = test_client.get("/api/metrics")
        headline = resp.json()["headline"]
        assert headline["total_tickets"] == 4
        assert headline["open_backlog"] == 2
        assert headline["resolved"] == 2
        assert headline["excluded_count"] == 2

    def test_date_filtering(self, test_client):
        # Only include issues created after 2026-02-15
        resp = test_client.get("/api/metrics?date_from=2026-02-15")
        assert resp.status_code == 200
        headline = resp.json()["headline"]
        assert headline["total_tickets"] == 1
        assert headline["resolved"] == 1
        assert headline["open_backlog"] == 0
        assert headline["stale_count"] == 0
        assert headline["excluded_count"] == 0

    def test_all_dashboard_sections_exclude_oasisdev(self, test_client):
        resp = test_client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert sum(item["total"] for item in data["priority_counts"]) == 4
        assert sum(item["count"] for item in data["age_buckets"]) == 2
        assignee_totals = sum(item["resolved"] + item["open"] for item in data["assignee_stats"])
        assert assignee_totals == 4

    def test_oasisdev_host_metrics_only_include_oasisdev_tickets(self, test_client):
        resp = test_client.get("/api/metrics", headers={"host": "oasisdev.movedocs.com"})
        assert resp.status_code == 200
        headline = resp.json()["headline"]
        assert headline["total_tickets"] == 2
        assert headline["open_backlog"] == 2
        assert headline["resolved"] == 0
        assert headline["stale_count"] == 2
        assert headline["excluded_count"] == 0

    def test_forwarded_oasisdev_host_metrics_only_include_oasisdev_tickets(self, test_client):
        resp = test_client.get(
            "/api/metrics",
            headers={
                "host": "dashboard.internal",
                "x-forwarded-host": "oasisdev.movedocs.com",
            },
        )
        assert resp.status_code == 200
        headline = resp.json()["headline"]
        assert headline["total_tickets"] == 2
        assert headline["open_backlog"] == 2
        assert headline["resolved"] == 0
        assert headline["stale_count"] == 2
        assert headline["excluded_count"] == 0


class TestSLAEndpoints:
    """GET /api/sla/summary and /api/sla/breaches"""

    def test_sla_summary(self, test_client):
        resp = test_client.get("/api/sla/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "timers" in data
        assert len(data["timers"]) == 4  # 4 SLA timer types

    def test_sla_breaches(self, test_client):
        resp = test_client.get("/api/sla/breaches")
        assert resp.status_code == 200
        data = resp.json()
        assert "breaches" in data
        # OIT-200 has breached SLA first response
        keys = [b["key"] for b in data["breaches"]]
        assert "OIT-200" in keys

    def test_sla_summary_timer_names(self, test_client):
        resp = test_client.get("/api/sla/summary")
        timer_names = [t["timer_name"] for t in resp.json()["timers"]]
        assert "First Response" in timer_names
        assert "Resolution" in timer_names
