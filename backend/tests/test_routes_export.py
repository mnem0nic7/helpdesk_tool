"""Tests for report builder and export routes (~7 tests)."""

from __future__ import annotations

import pytest


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
