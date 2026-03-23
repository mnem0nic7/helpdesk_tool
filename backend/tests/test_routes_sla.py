from __future__ import annotations

def test_sla_metrics_passes_search_to_engine(test_client, monkeypatch):
    import routes_sla

    captured: dict[str, object] = {}

    def fake_compute(issues, **kwargs):
        captured["issues"] = issues
        captured["kwargs"] = kwargs
        return {
            "summary": {
                "first_response": {
                    "total": 0,
                    "met": 0,
                    "breached": 0,
                    "running": 0,
                    "compliance_pct": 0.0,
                    "avg_elapsed_minutes": 0.0,
                    "p95_elapsed_minutes": 0.0,
                    "distribution": [],
                },
                "resolution": {
                    "total": 0,
                    "met": 0,
                    "breached": 0,
                    "running": 0,
                    "compliance_pct": 0.0,
                    "avg_elapsed_minutes": 0.0,
                    "p95_elapsed_minutes": 0.0,
                    "distribution": [],
                },
            },
            "tickets": [],
            "settings": {},
            "targets": [],
        }

    monkeypatch.setattr(routes_sla, "get_scoped_issues", lambda: [{"key": "OIT-1", "fields": {"created": "2026-03-01T00:00:00+00:00"}}])
    monkeypatch.setattr(routes_sla, "compute_sla_for_issues", fake_compute)

    resp = test_client.get("/api/sla/metrics?search=printer")

    assert resp.status_code == 200
    assert captured["kwargs"] == {
        "date_from": None,
        "date_to": None,
        "search": "printer",
    }
