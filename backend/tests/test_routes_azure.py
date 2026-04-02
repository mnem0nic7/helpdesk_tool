from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

from models import AIModel, AzureCitation, AzureCostChatResponse


def test_azure_overview_prefers_export_backed_cost_context(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cost_exports = MagicMock()
    mock_finops = MagicMock()
    mock_cache.get_overview.return_value = {
        "subscriptions": 4,
        "management_groups": 2,
        "resources": 125,
        "role_assignments": 15,
        "users": 48,
        "groups": 12,
        "enterprise_apps": 9,
        "app_registrations": 6,
        "directory_roles": 3,
        "cost": {
            "lookback_days": 30,
            "total_cost": 1234.56,
            "currency": "USD",
            "top_service": "Virtual Machines",
            "top_subscription": "Prod",
            "top_resource_group": "rg-prod",
            "recommendation_count": 2,
            "potential_monthly_savings": 321.0,
        },
        "datasets": [],
        "last_refresh": "2026-03-17T18:00:00+00:00",
    }
    mock_cost_exports.status.return_value = {
        "enabled": True,
        "configured": True,
        "running": False,
        "refreshing": False,
        "health": {"delivery_count": 2, "parsed_count": 2, "quarantined_count": 0},
    }
    mock_finops.get_status.return_value = {
        "available": True,
        "record_count": 4,
        "coverage_start": "2026-03-18",
        "coverage_end": "2026-03-19",
        "field_coverage": {"tags_pct": 0.5},
        "ai_usage": {"available": False, "usage_record_count": 0},
        "recommendations": {"available": True, "row_count": 2, "last_refreshed_at": "2026-03-19T03:00:00+00:00"},
    }
    mock_finops.get_cost_summary.return_value = {
        "lookback_days": 30,
        "total_cost": 100.0,
        "total_actual_cost": 100.0,
        "total_amortized_cost": 94.0,
        "currency": "USD",
        "top_service": "Compute",
        "top_subscription": "Prod",
        "top_resource_group": "rg-app",
        "record_count": 4,
        "window_start": "2026-03-18",
        "window_end": "2026-03-19",
        "source": "exports",
        "source_label": "Export-backed local analytics",
        "export_backed": True,
    }
    monkeypatch.setattr(routes_azure, "AZURE_REPORTING_POWER_BI_URL", "https://app.powerbi.com/groups/example")
    monkeypatch.setattr(routes_azure, "AZURE_REPORTING_POWER_BI_LABEL", "FinOps Workspace")
    monkeypatch.setattr(
        routes_azure,
        "AZURE_REPORTING_COST_ANALYSIS_URL",
        "https://portal.azure.com/#blade/Microsoft_Azure_CostManagement/Menu/costanalysis",
    )
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_cost_export_service", mock_cost_exports)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    resp = test_client.get("/api/azure/overview", headers={"host": "azure.movedocs.com"})
    assert resp.status_code == 200
    assert resp.json()["subscriptions"] == 4
    assert resp.json()["cost"]["total_actual_cost"] == 100.0
    assert resp.json()["cost"]["source"] == "exports"
    assert resp.json()["cost_exports"]["health"]["delivery_count"] == 2
    assert resp.json()["reporting"]["power_bi"]["configured"] is True
    assert resp.json()["reporting"]["power_bi"]["label"] == "FinOps Workspace"
    assert resp.json()["reporting"]["sources"]["overview"]["label"] == "Cached inventory + export-backed cost"
    assert resp.json()["reporting"]["sources"]["exports"]["label"] == "Export-backed governed reporting"


def test_azure_overview_is_not_available_on_helpdesk_host(test_client):
    resp = test_client.get("/api/azure/overview")
    assert resp.status_code == 404


def test_azure_status_includes_cost_export_status(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cost_exports = MagicMock()
    mock_finops = MagicMock()
    mock_cache.status.return_value = {
        "configured": True,
        "initialized": True,
        "refreshing": False,
        "last_refresh": "2026-03-20T08:00:00+00:00",
        "datasets": [],
    }
    mock_cost_exports.status.return_value = {
        "enabled": True,
        "configured": True,
        "running": True,
        "refreshing": False,
        "last_success_at": "2026-03-20T08:05:00+00:00",
        "health": {"delivery_count": 3, "parsed_count": 2, "quarantined_count": 1},
    }
    mock_finops.get_status.return_value = {
        "available": True,
        "record_count": 4,
        "coverage_start": "2026-03-18",
        "coverage_end": "2026-03-19",
        "field_coverage": {"tags_pct": 0.5},
        "ai_usage": {"available": True, "usage_record_count": 2},
        "recommendations": {"available": True, "row_count": 1, "last_refreshed_at": "2026-03-20T08:05:00+00:00"},
    }
    mock_finops.get_cost_summary.return_value = None
    monkeypatch.setattr(routes_azure, "AZURE_REPORTING_POWER_BI_URL", "")
    monkeypatch.setattr(routes_azure, "AZURE_REPORTING_COST_ANALYSIS_URL", "")
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_cost_export_service", mock_cost_exports)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    resp = test_client.get("/api/azure/status", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["configured"] is True
    assert payload["cost_exports"]["running"] is True
    assert payload["cost_exports"]["health"]["quarantined_count"] == 1
    assert payload["reporting"]["power_bi"]["configured"] is False
    assert payload["reporting"]["cost_analysis"]["configured"] is False
    assert payload["finops"]["ai_usage"]["usage_record_count"] == 2
    assert payload["finops"]["cost_context"]["source"] == "cache"


def test_directory_users_returns_cached_payload_on_azure_host(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.list_directory_objects.return_value = [
        {
            "id": "user-1",
            "display_name": "Ada Lovelace",
            "object_type": "user",
            "principal_name": "ada@example.com",
            "mail": "ada@example.com",
            "app_id": "",
            "enabled": True,
            "extra": {"user_type": "Member"},
        }
    ]
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/directory/users", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert resp.json()[0]["display_name"] == "Ada Lovelace"
    mock_cache.list_directory_objects.assert_called_once_with("users", search="")


def test_directory_users_returns_cached_payload_on_primary_host(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.list_directory_objects.return_value = [
        {
            "id": "user-2",
            "display_name": "Grace Hopper",
            "object_type": "user",
            "principal_name": "grace@example.com",
            "mail": "grace@example.com",
            "app_id": "",
            "enabled": False,
            "extra": {"user_type": "Guest"},
        }
    ]
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/directory/users", headers={"host": "it-app.movedocs.com"})

    assert resp.status_code == 200
    assert resp.json()[0]["display_name"] == "Grace Hopper"
    mock_cache.list_directory_objects.assert_called_once_with("users", search="")


def test_directory_users_preserve_license_and_sign_in_reporting_fields(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.list_directory_objects.return_value = [
        {
            "id": "user-3",
            "display_name": "Audit User",
            "object_type": "user",
            "principal_name": "audit@example.com",
            "mail": "audit@example.com",
            "app_id": "",
            "enabled": True,
            "extra": {
                "user_type": "Member",
                "is_licensed": "true",
                "license_count": "2",
                "sku_part_numbers": "M365_BUSINESS_PREMIUM, EMS",
                "last_interactive_utc": "2026-03-10T14:00:00+00:00",
                "last_interactive_local": "2026-03-10 07:00 PT",
                "last_noninteractive_utc": "2026-03-11T14:00:00+00:00",
                "last_noninteractive_local": "2026-03-11 07:00 PT",
                "last_successful_utc": "2026-03-12T14:00:00+00:00",
                "last_successful_local": "2026-03-12 07:00 PT",
            },
        }
    ]
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/directory/users", headers={"host": "it-app.movedocs.com"})

    assert resp.status_code == 200
    payload = resp.json()[0]
    assert payload["extra"]["is_licensed"] == "true"
    assert payload["extra"]["license_count"] == "2"
    assert payload["extra"]["last_successful_local"] == "2026-03-12 07:00 PT"


def test_azure_quick_search_returns_cached_results(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.quick_search.return_value = [
        {
            "kind": "vm",
            "id": "/subscriptions/sub-1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-app-01",
            "label": "vm-app-01",
            "subtitle": "Prod / rg-app / running",
            "route": "/vms?search=vm-app-01&vmId=/subscriptions/sub-1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-app-01",
        }
    ]
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/search?search=vm-app-01", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert resp.json()["results"][0]["label"] == "vm-app-01"
    mock_cache.quick_search.assert_called_once_with("vm-app-01")


def test_azure_cost_summary_prefers_export_backed_finops_data(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.get_cost_summary.return_value = {
        "lookback_days": 30,
        "total_cost": 1234.56,
        "currency": "USD",
        "top_service": "Cached Service",
        "top_subscription": "Cached Subscription",
        "top_resource_group": "cached-rg",
        "recommendation_count": 3,
        "potential_monthly_savings": 456.0,
    }
    mock_finops.get_cost_summary.return_value = {
        "lookback_days": 30,
        "total_cost": 100.0,
        "total_actual_cost": 100.0,
        "total_amortized_cost": 90.0,
        "currency": "USD",
        "top_service": "Compute",
        "top_subscription": "Prod",
        "top_resource_group": "rg-app",
        "record_count": 4,
        "window_start": "2026-03-18",
        "window_end": "2026-03-19",
        "source": "exports",
        "source_label": "Export-backed local analytics",
        "export_backed": True,
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    resp = test_client.get("/api/azure/cost/summary", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["source"] == "exports"
    assert payload["total_actual_cost"] == 100.0
    assert payload["total_amortized_cost"] == 90.0
    assert payload["recommendation_count"] == 3
    assert payload["potential_monthly_savings"] == 456.0


def test_azure_cost_routes_fall_back_to_cache_when_no_export_data(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.get_cost_summary.return_value = {
        "lookback_days": 30,
        "total_cost": 42.0,
        "currency": "USD",
        "top_service": "Virtual Machines",
        "top_subscription": "Prod",
        "top_resource_group": "rg-prod",
        "recommendation_count": 1,
        "potential_monthly_savings": 9.0,
    }
    mock_cache.get_cost_trend.return_value = [{"date": "2026-03-20", "cost": 42.0, "currency": "USD"}]
    mock_cache.get_cost_breakdown.return_value = [
        {"label": "Virtual Machines", "amount": 42.0, "currency": "USD", "share": 1.0}
    ]
    mock_finops.get_cost_summary.return_value = None
    mock_finops.get_cost_trend.return_value = []
    mock_finops.get_cost_breakdown.return_value = []
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    summary_resp = test_client.get("/api/azure/cost/summary", headers={"host": "azure.movedocs.com"})
    trend_resp = test_client.get("/api/azure/cost/trend", headers={"host": "azure.movedocs.com"})
    breakdown_resp = test_client.get(
        "/api/azure/cost/breakdown?group_by=service",
        headers={"host": "azure.movedocs.com"},
    )

    assert summary_resp.status_code == 200
    assert summary_resp.json()["source"] == "cache"
    assert summary_resp.json()["total_actual_cost"] == 42.0
    assert summary_resp.json()["total_amortized_cost"] == 42.0

    assert trend_resp.status_code == 200
    assert trend_resp.json()[0]["source"] == "cache"
    assert trend_resp.json()[0]["actual_cost"] == 42.0
    assert trend_resp.json()[0]["amortized_cost"] == 42.0

    assert breakdown_resp.status_code == 200
    assert breakdown_resp.json()[0]["source"] == "cache"
    assert breakdown_resp.json()[0]["actual_cost"] == 42.0
    assert breakdown_resp.json()[0]["amortized_cost"] == 42.0


def test_finops_status_and_ai_cost_routes_return_local_finops_data(test_client, monkeypatch):
    import routes_azure

    mock_finops = MagicMock()
    mock_finops.get_status.return_value = {
        "available": True,
        "record_count": 4,
        "field_map": {"version": 1, "fields": {"date": {}}},
        "field_coverage": {"tags_pct": 0.5},
    }
    mock_finops.get_cost_reconciliation.return_value = {
        "available": True,
        "deltas": {"delivery_actual_cost_delta": 0.0},
    }
    mock_finops.get_validation_report.return_value = {
        "available": True,
        "overall_state": "warning",
        "overall_label": "Needs live validation follow-through",
        "signoff_ready": False,
        "check_counts": {"pass": 6, "warning": 1, "fail": 0, "unavailable": 0},
        "checks": [{"key": "scheduled_deliveries", "state": "warning"}],
    }
    mock_finops.get_ai_cost_summary.return_value = {
        "lookback_days": 30,
        "usage_record_count": 2,
        "request_count": 2,
        "input_tokens": 1200,
        "output_tokens": 600,
        "estimated_tokens": 1800,
        "estimated_cost": 0.025,
        "currency": "USD",
        "top_model": "qwen3.5:4b",
        "top_feature": "azure_cost_copilot",
        "window_start": "2026-03-20",
        "window_end": "2026-03-20",
    }
    mock_finops.get_ai_cost_trend.return_value = [
        {"date": "2026-03-20", "request_count": 2, "estimated_cost": 0.025, "currency": "USD"}
    ]
    mock_finops.get_ai_cost_breakdown.return_value = [
        {"label": "qwen3.5:4b", "request_count": 2, "estimated_cost": 0.025, "currency": "USD", "share": 1.0}
    ]
    mock_cache = MagicMock()
    mock_cache.get_cost_summary.return_value = {"total_cost": 25.5}
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    status_resp = test_client.get("/api/azure/finops/status", headers={"host": "azure.movedocs.com"})
    reconciliation_resp = test_client.get("/api/azure/finops/reconciliation", headers={"host": "azure.movedocs.com"})
    validation_resp = test_client.get("/api/azure/finops/validation", headers={"host": "azure.movedocs.com"})
    ai_summary_resp = test_client.get("/api/azure/ai-costs/summary", headers={"host": "azure.movedocs.com"})
    ai_trend_resp = test_client.get("/api/azure/ai-costs/trend", headers={"host": "azure.movedocs.com"})
    ai_breakdown_resp = test_client.get(
        "/api/azure/ai-costs/breakdown?group_by=model",
        headers={"host": "azure.movedocs.com"},
    )

    assert status_resp.status_code == 200
    assert status_resp.json()["record_count"] == 4
    assert reconciliation_resp.status_code == 200
    assert reconciliation_resp.json()["deltas"]["delivery_actual_cost_delta"] == 0.0
    assert validation_resp.status_code == 200
    assert validation_resp.json()["overall_state"] == "warning"
    assert ai_summary_resp.status_code == 200
    assert ai_summary_resp.json()["estimated_cost"] == 0.025
    assert ai_trend_resp.json()[0]["request_count"] == 2
    assert ai_breakdown_resp.json()[0]["label"] == "qwen3.5:4b"


def test_azure_ai_models_returns_active_ollama_models(test_client, monkeypatch):
    import routes_azure

    monkeypatch.setattr(
        routes_azure,
        "get_available_copilot_models",
        lambda: [
            AIModel(id="qwen3.5:4b", name="qwen3.5:4b", provider="ollama"),
            AIModel(id="nemotron-3-nano:4b", name="nemotron-3-nano:4b", provider="ollama"),
        ],
    )

    resp = test_client.get("/api/azure/ai/models", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert resp.json() == [
        {"id": "qwen3.5:4b", "name": "qwen3.5:4b", "provider": "ollama"},
        {"id": "nemotron-3-nano:4b", "name": "nemotron-3-nano:4b", "provider": "ollama"},
    ]


def test_finops_read_routes_require_authenticated_user(test_client):
    test_client.cookies.clear()

    endpoints = [
        "/api/azure/finops/status",
        "/api/azure/finops/reconciliation",
        "/api/azure/finops/validation",
        "/api/azure/allocations/policy",
        "/api/azure/allocations/status",
        "/api/azure/allocations/rules",
        "/api/azure/allocations/runs",
        "/api/azure/allocations/runs/run-1",
        "/api/azure/allocations/runs/run-1/results?dimension=team",
        "/api/azure/allocations/runs/run-1/residuals?dimension=team",
        "/api/azure/recommendations/summary",
        "/api/azure/recommendations/resource-cost-bridge",
        "/api/azure/recommendations/aks-visibility",
        "/api/azure/recommendations",
        "/api/azure/recommendations/export.csv",
        "/api/azure/recommendations/export.xlsx",
        "/api/azure/recommendations/rec-1",
        "/api/azure/recommendations/rec-1/actions",
        "/api/azure/recommendations/rec-1/history",
        "/api/azure/ai/models",
        "/api/azure/ai-costs/summary",
        "/api/azure/ai-costs/trend",
        "/api/azure/ai-costs/breakdown",
    ]

    for path in endpoints:
        resp = test_client.get(path, headers={"host": "azure.movedocs.com"})
        assert resp.status_code == 401, path

    chat_resp = test_client.post(
        "/api/azure/ai/cost-chat",
        headers={"host": "azure.movedocs.com"},
        json={"question": "Where should I start?"},
    )
    assert chat_resp.status_code == 401


def test_azure_recommendation_bridge_routes_return_finops_payload(test_client, monkeypatch):
    import routes_azure

    mock_finops = MagicMock()
    mock_cache = MagicMock()
    mock_finops.get_resource_cost_bridge_summary.return_value = {
        "available": True,
        "matched_resource_count": 5,
        "bridged_actual_cost": 195.0,
    }
    mock_finops.list_aks_cost_visibility.return_value = [
        {
            "id": "aks-visibility:cluster-1",
            "resource_name": "cluster-1",
            "current_monthly_cost": 145.0,
        }
    ]
    mock_cache._snapshot.return_value = [{"id": "resource-1"}]
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    bridge_resp = test_client.get(
        "/api/azure/recommendations/resource-cost-bridge",
        headers={"host": "azure.movedocs.com"},
    )
    aks_resp = test_client.get(
        "/api/azure/recommendations/aks-visibility",
        headers={"host": "azure.movedocs.com"},
    )

    assert bridge_resp.status_code == 200
    assert bridge_resp.json()["matched_resource_count"] == 5
    assert aks_resp.status_code == 200
    assert aks_resp.json()[0]["resource_name"] == "cluster-1"


def test_azure_allocation_routes_surface_policy_and_runs(test_client, monkeypatch):
    import routes_azure

    mock_finops = MagicMock()
    mock_finops.get_allocation_policy.return_value = {
        "version": 1,
        "target_dimensions": [{"dimension": "team", "fallback_bucket": "Unassigned Team"}],
    }
    mock_finops.get_allocation_status.return_value = {
        "available": True,
        "active_rule_count": 2,
        "run_count": 1,
    }
    mock_finops.list_allocation_rules.return_value = [
        {"rule_id": "rule-1", "rule_version": 1, "target_dimension": "team", "rule_type": "tag"}
    ]
    mock_finops.list_allocation_runs.return_value = [
        {"run_id": "run-1", "status": "completed", "target_dimensions": ["team"]}
    ]
    mock_finops.get_allocation_run.return_value = {"run_id": "run-1", "status": "completed"}
    mock_finops.list_allocation_results.return_value = [
        {"allocation_value": "Platform Team", "allocated_actual_cost": 100.0}
    ]
    mock_finops.list_allocation_residuals.return_value = [
        {"allocation_value": "Unassigned Team", "allocated_actual_cost": 50.0}
    ]
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    policy_resp = test_client.get("/api/azure/allocations/policy", headers={"host": "azure.movedocs.com"})
    status_resp = test_client.get("/api/azure/allocations/status", headers={"host": "azure.movedocs.com"})
    rules_resp = test_client.get("/api/azure/allocations/rules", headers={"host": "azure.movedocs.com"})
    runs_resp = test_client.get("/api/azure/allocations/runs", headers={"host": "azure.movedocs.com"})
    run_resp = test_client.get("/api/azure/allocations/runs/run-1", headers={"host": "azure.movedocs.com"})
    results_resp = test_client.get(
        "/api/azure/allocations/runs/run-1/results?dimension=team",
        headers={"host": "azure.movedocs.com"},
    )
    residuals_resp = test_client.get(
        "/api/azure/allocations/runs/run-1/residuals?dimension=team",
        headers={"host": "azure.movedocs.com"},
    )

    assert policy_resp.status_code == 200
    assert policy_resp.json()["target_dimensions"][0]["dimension"] == "team"
    assert status_resp.status_code == 200
    assert status_resp.json()["active_rule_count"] == 2
    assert rules_resp.status_code == 200
    assert rules_resp.json()[0]["rule_id"] == "rule-1"
    assert runs_resp.status_code == 200
    assert runs_resp.json()[0]["run_id"] == "run-1"
    assert run_resp.status_code == 200
    assert run_resp.json()["status"] == "completed"
    assert results_resp.status_code == 200
    assert results_resp.json()[0]["allocation_value"] == "Platform Team"
    assert residuals_resp.status_code == 200
    assert residuals_resp.json()[0]["allocation_value"] == "Unassigned Team"


def test_azure_allocation_mutations_require_admin(test_client, monkeypatch):
    import auth

    monkeypatch.setattr(auth, "is_admin_user", lambda email: False)

    create_rule_resp = test_client.post(
        "/api/azure/allocations/rules",
        headers={"host": "azure.movedocs.com"},
        json={
            "name": "Platform tag",
            "rule_type": "tag",
            "target_dimension": "team",
            "condition": {"tag_key": "team", "tag_value": "Platform"},
            "allocation": {"value": "Platform Team"},
        },
    )
    create_run_resp = test_client.post(
        "/api/azure/allocations/runs",
        headers={"host": "azure.movedocs.com"},
        json={"target_dimensions": ["team"]},
    )
    deactivate_resp = test_client.post(
        "/api/azure/allocations/rules/rule-1/deactivate",
        headers={"host": "azure.movedocs.com"},
    )

    assert create_rule_resp.status_code == 403
    assert create_run_resp.status_code == 403
    assert deactivate_resp.status_code == 403


def test_azure_storage_passes_search_filters_to_cache(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.get_storage_summary.return_value = {
        "storage_accounts": [],
        "managed_disks": [],
        "snapshots": [],
        "summary": {
            "total_storage_accounts": 0,
            "total_managed_disks": 0,
            "total_snapshots": 0,
            "unattached_disks": 0,
            "total_storage_cost": None,
            "total_disk_gb": 0,
            "total_snapshot_gb": 0,
            "total_provisioned_gb": 0,
            "avg_cost_per_gb": None,
        },
        "disk_by_sku": {},
        "disk_by_state": {},
        "accounts_by_kind": {},
        "accounts_by_tier": {},
        "storage_services_cost": [],
        "cost_available": False,
        "cost_basis": None,
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    mock_finops.get_cost_summary.return_value = None
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    resp = test_client.get(
        "/api/azure/storage?account_search=acct&disk_search=disk&snapshot_search=snap&disk_unattached_only=true",
        headers={"host": "azure.movedocs.com"},
    )

    assert resp.status_code == 200
    assert resp.json()["cost_context"]["source"] == "cache"
    mock_cache.get_storage_summary.assert_called_once_with(
        account_search="acct",
        disk_search="disk",
        snapshot_search="snap",
        disk_unattached_only=True,
    )


def test_azure_compute_optimization_passes_idle_vm_search_to_cache(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.get_compute_optimization.return_value = {
        "summary": {
            "total_vms": 0,
            "running_vms": 0,
            "idle_vms": 0,
            "total_running_cost": None,
            "total_advisor_savings": 0,
            "ri_gap_count": 0,
        },
        "idle_vms": [],
        "top_cost_vms": [],
        "ri_coverage_gaps": [],
        "advisor_recommendations": [],
        "cost_available": False,
        "reservation_data_available": False,
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    mock_finops.get_cost_summary.return_value = None
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    resp = test_client.get(
        "/api/azure/compute/optimization?idle_vm_search=vm-1",
        headers={"host": "azure.movedocs.com"},
    )

    assert resp.status_code == 200
    assert resp.json()["cost_context"]["source"] == "cache"
    mock_cache.get_compute_optimization.assert_called_once_with(idle_vm_search="vm-1")


def test_directory_users_is_not_available_on_oasisdev_host(test_client):
    resp = test_client.get("/api/azure/directory/users", headers={"host": "oasisdev.movedocs.com"})

    assert resp.status_code == 404


def test_azure_savings_summary_returns_cached_payload(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.get_savings_summary.return_value = {
        "currency": "USD",
        "total_opportunities": 4,
        "quantified_opportunities": 2,
        "quantified_monthly_savings": 125.0,
        "quick_win_count": 3,
        "quick_win_monthly_savings": 100.0,
        "unquantified_opportunity_count": 2,
        "by_category": [{"label": "compute", "count": 2, "estimated_monthly_savings": 75.0}],
        "by_opportunity_type": [{"label": "idle_vm_attached_cost", "count": 1, "estimated_monthly_savings": 25.0}],
        "by_effort": [{"label": "low", "count": 3}],
        "by_risk": [{"label": "low", "count": 2}],
        "by_confidence": [{"label": "high", "count": 2}],
        "top_subscriptions": [{"label": "Prod", "count": 2, "estimated_monthly_savings": 75.0}],
        "top_resource_groups": [{"label": "Prod / rg-prod", "count": 2, "estimated_monthly_savings": 75.0}],
    }
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": False}
    mock_finops.get_recommendation_summary.return_value = None
    mock_finops.get_status.return_value = {"recommendations": {"available": False, "row_count": 0, "last_refreshed_at": ""}}
    mock_finops.get_cost_summary.return_value = None
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    resp = test_client.get("/api/azure/savings/summary", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert resp.json()["quantified_monthly_savings"] == 125.0
    assert resp.json()["source"] == "cache"
    assert resp.json()["cost_context"]["source"] == "cache"


def test_azure_savings_opportunities_pass_filters_to_cache(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = [
        {
            "id": "opp-1",
            "category": "storage",
            "opportunity_type": "unattached_managed_disk",
            "source": "heuristic",
            "title": "Review unattached disk",
            "summary": "Disk is still costing money.",
            "subscription_id": "sub-1",
            "subscription_name": "Prod",
            "resource_group": "rg-prod",
            "location": "eastus",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/disk-1",
            "resource_name": "disk-1",
            "resource_type": "Microsoft.Compute/disks",
            "current_monthly_cost": 10.0,
            "estimated_monthly_savings": 10.0,
            "currency": "USD",
            "quantified": True,
            "estimate_basis": "proxy",
            "effort": "low",
            "risk": "low",
            "confidence": "high",
            "recommended_steps": ["Delete the disk if it is no longer needed."],
            "evidence": [{"label": "Disk state", "value": "Unattached"}],
            "portal_url": "https://portal.azure.com/#resource/disk-1",
            "follow_up_route": "/storage",
        }
    ]
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": False}
    mock_finops.list_recommendations.return_value = []
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    resp = test_client.get(
        "/api/azure/savings/opportunities",
        headers={"host": "azure.movedocs.com"},
        params={
            "category": "storage",
            "subscription_id": "sub-1",
            "quantified_only": "true",
        },
    )

    assert resp.status_code == 200
    assert resp.json()[0]["opportunity_type"] == "unattached_managed_disk"
    mock_finops.list_recommendations.assert_called_once_with(
        search="",
        category="storage",
        opportunity_type="",
        subscription_id="sub-1",
        resource_group="",
        effort="",
        risk="",
        confidence="",
        quantified_only=True,
    )
    assert mock_cache.list_savings_opportunities.call_count == 2
    assert mock_cache.list_savings_opportunities.call_args_list[0].kwargs == {}
    assert mock_cache.list_savings_opportunities.call_args_list[1].kwargs == {
        "search": "",
        "category": "storage",
        "opportunity_type": "",
        "subscription_id": "sub-1",
        "resource_group": "",
        "effort": "",
        "risk": "",
        "confidence": "",
        "quantified_only": True,
    }


def test_azure_savings_endpoints_are_not_available_on_primary_host(test_client):
    resp = test_client.get("/api/azure/savings/summary")
    assert resp.status_code == 404


def test_azure_savings_csv_export_returns_filtered_rows(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = [
        {
            "id": "opp-1",
            "category": "network",
            "opportunity_type": "unattached_public_ip",
            "source": "heuristic",
            "title": "Release unattached public IP",
            "summary": "Public IP is unused.",
            "subscription_id": "sub-1",
            "subscription_name": "Prod",
            "resource_group": "rg-prod",
            "location": "eastus",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/publicIPAddresses/pip-1",
            "resource_name": "pip-1",
            "resource_type": "Microsoft.Network/publicIPAddresses",
            "current_monthly_cost": 4.0,
            "estimated_monthly_savings": 4.0,
            "currency": "USD",
            "quantified": True,
            "estimate_basis": "proxy",
            "effort": "low",
            "risk": "low",
            "confidence": "high",
            "recommended_steps": ["Release the IP if it is no longer needed."],
            "evidence": [{"label": "Reference status", "value": "Unused"}],
            "portal_url": "https://portal.azure.com/#resource/pip-1",
            "follow_up_route": "/resources",
        }
    ]
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": False}
    mock_finops.list_recommendations.return_value = []
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    resp = test_client.get(
        "/api/azure/savings/export.csv",
        headers={"host": "azure.movedocs.com"},
        params={"category": "network"},
    )

    assert resp.status_code == 200
    assert "Release unattached public IP" in resp.text
    assert mock_cache.list_savings_opportunities.call_count == 2
    assert mock_cache.list_savings_opportunities.call_args_list[0].kwargs == {}
    assert mock_cache.list_savings_opportunities.call_args_list[1].kwargs == {
        "search": "",
        "category": "network",
        "opportunity_type": "",
        "subscription_id": "",
        "resource_group": "",
        "effort": "",
        "risk": "",
        "confidence": "",
        "quantified_only": False,
    }


def test_azure_savings_xlsx_export_returns_workbook(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": False}
    mock_finops.list_recommendations.return_value = []
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    resp = test_client.get("/api/azure/savings/export.xlsx", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_azure_savings_summary_prefers_finops_recommendations(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": True}
    mock_finops.get_status.return_value = {
        "recommendations": {"available": True, "row_count": 3, "last_refreshed_at": "2026-03-23T12:45:00+00:00"}
    }
    mock_finops.get_cost_summary.return_value = {
        "lookback_days": 30,
        "total_cost": 500.0,
        "total_actual_cost": 500.0,
        "total_amortized_cost": 480.0,
        "currency": "USD",
        "record_count": 24,
        "window_start": "2026-03-01",
        "window_end": "2026-03-23",
        "source": "exports",
        "source_label": "Export-backed local analytics",
        "export_backed": True,
    }
    mock_finops.get_recommendation_summary.return_value = {
        "currency": "USD",
        "total_opportunities": 3,
        "quantified_opportunities": 3,
        "quantified_monthly_savings": 227.5,
        "quick_win_count": 1,
        "quick_win_monthly_savings": 12.5,
        "unquantified_opportunity_count": 0,
        "by_category": [{"label": "commitment", "count": 2, "estimated_monthly_savings": 215.0}],
        "by_opportunity_type": [{"label": "reservation_purchase", "count": 2, "estimated_monthly_savings": 215.0}],
        "by_effort": [{"label": "medium", "count": 2}],
        "by_risk": [{"label": "low", "count": 2}],
        "by_confidence": [{"label": "high", "count": 2}],
        "top_subscriptions": [{"label": "Prod Subscription", "count": 2, "estimated_monthly_savings": 215.0}],
        "top_resource_groups": [{"label": "Prod Subscription / rg-prod", "count": 1, "estimated_monthly_savings": 12.5}],
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    resp = test_client.get("/api/azure/savings/summary", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert resp.json()["quantified_monthly_savings"] == 227.5
    assert resp.json()["total_opportunities"] == 3
    assert resp.json()["source"] == "recommendations"
    assert resp.json()["cost_context"]["source"] == "exports"
    mock_finops.get_recommendation_summary.assert_called_once()


def test_azure_recommendations_routes_return_finops_payload(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": True}
    mock_finops.get_status.return_value = {
        "recommendations": {"available": True, "row_count": 1, "last_refreshed_at": "2026-03-23T12:40:00+00:00"}
    }
    mock_finops.get_cost_summary.return_value = {
        "lookback_days": 30,
        "total_cost": 300.0,
        "total_actual_cost": 300.0,
        "total_amortized_cost": 280.0,
        "currency": "USD",
        "record_count": 12,
        "window_start": "2026-03-01",
        "window_end": "2026-03-23",
        "source": "exports",
        "source_label": "Export-backed local analytics",
        "export_backed": True,
    }
    mock_finops.get_recommendation_summary.return_value = {
        "currency": "USD",
        "total_opportunities": 1,
        "quantified_opportunities": 1,
        "quantified_monthly_savings": 120.5,
        "quick_win_count": 0,
        "quick_win_monthly_savings": 0.0,
        "unquantified_opportunity_count": 0,
        "by_category": [],
        "by_opportunity_type": [],
        "by_effort": [],
        "by_risk": [],
        "by_confidence": [],
        "top_subscriptions": [],
        "top_resource_groups": [],
    }
    mock_finops.list_recommendations.return_value = [
        {
            "id": "reservation-export:run:1",
            "category": "commitment",
            "opportunity_type": "reservation_purchase",
            "source": "heuristic",
            "title": "Purchase reservation",
            "summary": "Buy a reservation.",
            "subscription_id": "sub-prod",
            "subscription_name": "Prod Subscription",
            "resource_group": "",
            "location": "eastus",
            "resource_id": "",
            "resource_name": "Standard_D2s_v5",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "current_monthly_cost": 300.0,
            "estimated_monthly_savings": 120.5,
            "currency": "USD",
            "quantified": True,
            "estimate_basis": "Azure Cost Management reservation recommendations export.",
            "effort": "medium",
            "risk": "low",
            "confidence": "high",
            "recommended_steps": ["Validate baseline usage."],
            "evidence": [{"label": "Term", "value": "1 Year"}],
            "portal_url": "https://portal.azure.com/",
            "follow_up_route": "/azure/savings",
            "lifecycle_status": "open",
            "action_state": "none",
            "dismissed_reason": "",
        }
    ]
    mock_finops.get_recommendation.return_value = mock_finops.list_recommendations.return_value[0]
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    summary_resp = test_client.get("/api/azure/recommendations/summary", headers={"host": "azure.movedocs.com"})
    list_resp = test_client.get("/api/azure/recommendations", headers={"host": "azure.movedocs.com"})
    detail_resp = test_client.get(
        "/api/azure/recommendations/reservation-export:run:1",
        headers={"host": "azure.movedocs.com"},
    )

    assert summary_resp.status_code == 200
    assert summary_resp.json()["quantified_monthly_savings"] == 120.5
    assert summary_resp.json()["source"] == "recommendations"
    assert summary_resp.json()["cost_context"]["source"] == "exports"
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["opportunity_type"] == "reservation_purchase"
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == "reservation-export:run:1"


def test_azure_recommendation_export_and_history_routes_use_finops_payload(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": True}
    mock_finops.list_recommendations.return_value = [
        {
            "id": "rec-1",
            "category": "storage",
            "opportunity_type": "unattached_managed_disk",
            "source": "heuristic",
            "title": "Delete unattached disk",
            "summary": "Disk is no longer attached.",
            "subscription_id": "sub-prod",
            "subscription_name": "Prod Subscription",
            "resource_group": "rg-prod",
            "location": "eastus",
            "resource_id": "/subscriptions/sub-prod/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/disk-1",
            "resource_name": "disk-1",
            "resource_type": "Microsoft.Compute/disks",
            "current_monthly_cost": 12.5,
            "estimated_monthly_savings": 12.5,
            "currency": "USD",
            "quantified": True,
            "estimate_basis": "Proxy",
            "effort": "low",
            "risk": "low",
            "confidence": "high",
            "recommended_steps": ["Delete the disk."],
            "evidence": [{"label": "State", "value": "Unattached"}],
            "portal_url": "https://portal.azure.com/",
            "follow_up_route": "/azure/storage",
        }
    ]
    mock_finops.get_recommendation.return_value = {"id": "rec-1"}
    mock_finops.get_recommendation_action_contract.return_value = {
        "recommendation_id": "rec-1",
        "lifecycle_status": "open",
        "current_action_state": "none",
        "generated_at": "2026-03-23T12:35:00+00:00",
        "actions": [
            {
                "action_type": "create_ticket",
                "label": "Create Jira ticket",
                "description": "Create a Jira follow-up for the recommendation.",
                "category": "jira",
                "status": "available",
                "can_execute": True,
                "requires_admin": True,
                "repeatable": False,
                "pending_action_state": "ticket_pending",
                "completed_action_state": "ticket_created",
                "current_action_state": "none",
                "blocked_reason": "",
                "note_placeholder": "Add an operator note for the Jira follow-up.",
                "metadata_fields": [],
                "latest_event": {},
            }
        ],
    }
    mock_finops.list_recommendation_action_history.return_value = [
        {
            "event_id": "evt-1",
            "recommendation_id": "rec-1",
            "action_type": "dismiss",
            "action_status": "completed",
            "actor_type": "user",
            "actor_id": "admin@example.com",
            "note": "Not now",
            "metadata": {"dismissed_reason": "Not now"},
            "created_at": "2026-03-23T12:30:00+00:00",
        }
    ]
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)

    csv_resp = test_client.get("/api/azure/recommendations/export.csv", headers={"host": "azure.movedocs.com"})
    xlsx_resp = test_client.get("/api/azure/recommendations/export.xlsx", headers={"host": "azure.movedocs.com"})
    actions_resp = test_client.get("/api/azure/recommendations/rec-1/actions", headers={"host": "azure.movedocs.com"})
    history_resp = test_client.get("/api/azure/recommendations/rec-1/history", headers={"host": "azure.movedocs.com"})

    assert csv_resp.status_code == 200
    assert "Delete unattached disk" in csv_resp.text
    assert xlsx_resp.status_code == 200
    assert xlsx_resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert actions_resp.status_code == 200
    assert actions_resp.json()["actions"][0]["action_type"] == "create_ticket"
    assert history_resp.status_code == 200
    assert history_resp.json()[0]["action_type"] == "dismiss"


def test_azure_recommendation_mutation_routes_require_admin_and_update_state(test_client, monkeypatch):
    import auth
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": True}
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: True)

    mock_finops.dismiss_recommendation.return_value = {
        "id": "rec-1",
        "lifecycle_status": "dismissed",
        "dismissed_reason": "Already planned",
        "action_state": "none",
    }
    mock_finops.reopen_recommendation.return_value = {
        "id": "rec-1",
        "lifecycle_status": "open",
        "dismissed_reason": "",
        "action_state": "none",
    }
    mock_finops.update_recommendation_action_state.return_value = {
        "id": "rec-1",
        "lifecycle_status": "open",
        "dismissed_reason": "",
        "action_state": "ticket_created",
    }

    dismiss_resp = test_client.post(
        "/api/azure/recommendations/rec-1/dismiss",
        headers={"host": "azure.movedocs.com"},
        json={"reason": "Already planned"},
    )
    reopen_resp = test_client.post(
        "/api/azure/recommendations/rec-1/reopen",
        headers={"host": "azure.movedocs.com"},
        json={"note": "Reopened after review"},
    )
    action_resp = test_client.post(
        "/api/azure/recommendations/rec-1/action-state",
        headers={"host": "azure.movedocs.com"},
        json={"action_state": "ticket_created", "action_type": "create_ticket", "note": "Created follow-up"},
    )

    assert dismiss_resp.status_code == 200
    assert dismiss_resp.json()["lifecycle_status"] == "dismissed"
    assert reopen_resp.status_code == 200
    assert reopen_resp.json()["lifecycle_status"] == "open"
    assert action_resp.status_code == 200
    assert action_resp.json()["action_state"] == "ticket_created"

    dismiss_kwargs = mock_finops.dismiss_recommendation.call_args.kwargs
    assert dismiss_kwargs["reason"] == "Already planned"
    assert dismiss_kwargs["actor_type"] == "user"
    reopen_kwargs = mock_finops.reopen_recommendation.call_args.kwargs
    assert reopen_kwargs["note"] == "Reopened after review"
    action_kwargs = mock_finops.update_recommendation_action_state.call_args.kwargs
    assert action_kwargs["action_state"] == "ticket_created"
    assert action_kwargs["action_type"] == "create_ticket"


def test_azure_recommendation_create_ticket_creates_jira_issue_and_persists_linkage(test_client, monkeypatch):
    import auth
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_jira = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": True}
    mock_finops.get_recommendation.return_value = {
        "id": "rec-1",
        "title": "Right-size VM vm-1",
        "summary": "VM appears oversized for current utilization.",
        "category": "compute",
        "opportunity_type": "rightsizing",
        "currency": "USD",
        "estimated_monthly_savings": 42.5,
        "current_monthly_cost": 90.0,
        "subscription_name": "Prod",
        "resource_group": "rg-prod",
        "resource_name": "vm-1",
        "resource_id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
        "portal_url": "https://portal.azure.com/#resource/vm-1",
        "follow_up_route": "/compute",
        "recommended_steps": ["Review current CPU usage.", "Resize to Standard_D4s_v5."],
        "evidence": [{"label": "CPU", "value": "6% average"}],
    }
    mock_finops.get_recommendation_action_contract.return_value = {
        "recommendation_id": "rec-1",
        "actions": [
            {
                "action_type": "create_ticket",
                "can_execute": True,
                "blocked_reason": "",
            }
        ],
    }
    mock_jira.create_issue.return_value = {"id": "10001", "key": "OIT-123"}
    mock_finops.update_recommendation_action_state.return_value = {
        "id": "rec-1",
        "action_state": "ticket_created",
    }

    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(routes_azure, "_jira_client", mock_jira)
    monkeypatch.setattr(routes_azure, "JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setattr(routes_azure, "AZURE_APP_HOST", "azure.movedocs.com")
    monkeypatch.setattr(routes_azure, "AZURE_FINOPS_RECOMMENDATION_JIRA_PROJECT", "FINOPS")
    monkeypatch.setattr(routes_azure, "AZURE_FINOPS_RECOMMENDATION_JIRA_ISSUE_TYPE", "Task")
    monkeypatch.setattr(auth, "is_admin_user", lambda email: True)

    resp = test_client.post(
        "/api/azure/recommendations/rec-1/actions/create-ticket",
        headers={"host": "azure.movedocs.com"},
        json={"note": "Please route to the platform owner."},
    )

    assert resp.status_code == 200
    assert resp.json()["ticket_key"] == "OIT-123"
    assert resp.json()["project_key"] == "FINOPS"
    jira_kwargs = mock_jira.create_issue.call_args.kwargs
    assert jira_kwargs["project_key"] == "FINOPS"
    assert jira_kwargs["issue_type"] == "Task"
    assert jira_kwargs["summary"] == "[FinOps] Right-size VM vm-1"
    assert "Please route to the platform owner." in jira_kwargs["description"]
    state_kwargs = mock_finops.update_recommendation_action_state.call_args.kwargs
    assert state_kwargs["action_state"] == "ticket_created"
    assert state_kwargs["metadata"]["ticket_key"] == "OIT-123"
    assert state_kwargs["metadata"]["ticket_url"] == "https://example.atlassian.net/browse/OIT-123"


def test_azure_recommendation_create_ticket_records_failed_event_on_jira_error(test_client, monkeypatch):
    import auth
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_jira = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": True}
    mock_finops.get_recommendation.return_value = {
        "id": "rec-1",
        "title": "Release unattached public IP pip-1",
        "summary": "The public IP is not attached.",
        "category": "network",
        "opportunity_type": "unattached_public_ip",
        "currency": "USD",
        "estimated_monthly_savings": 5.0,
        "current_monthly_cost": 5.0,
        "recommended_steps": [],
        "evidence": [],
    }
    mock_finops.get_recommendation_action_contract.return_value = {
        "recommendation_id": "rec-1",
        "actions": [
            {
                "action_type": "create_ticket",
                "can_execute": True,
                "blocked_reason": "",
            }
        ],
    }
    mock_jira.create_issue.side_effect = RuntimeError("jira unavailable")

    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(routes_azure, "_jira_client", mock_jira)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: True)

    resp = test_client.post(
        "/api/azure/recommendations/rec-1/actions/create-ticket",
        headers={"host": "azure.movedocs.com"},
        json={},
    )

    assert resp.status_code == 502
    assert "Could not create Jira ticket" in resp.json()["detail"]
    event_kwargs = mock_finops.record_recommendation_action_event.call_args.kwargs
    assert event_kwargs["action_type"] == "create_ticket"
    assert event_kwargs["action_status"] == "failed"
    assert "jira unavailable" in event_kwargs["metadata"]["error"]


def test_azure_recommendation_send_alert_delivers_teams_notification(test_client, monkeypatch):
    import auth
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": True}
    mock_finops.get_recommendation.return_value = {
        "id": "rec-1",
        "title": "Release unattached public IP pip-1",
        "summary": "The address is not attached.",
        "category": "network",
        "opportunity_type": "unattached_public_ip",
    }
    mock_finops.get_recommendation_action_contract.return_value = {
        "recommendation_id": "rec-1",
        "actions": [
            {
                "action_type": "send_alert",
                "can_execute": True,
                "blocked_reason": "",
            }
        ],
    }
    mock_finops.update_recommendation_action_state.return_value = {
        "id": "rec-1",
        "action_state": "alert_sent",
    }
    send_calls: list[dict[str, str]] = []

    async def _fake_send(webhook_url: str, recommendation: dict[str, str], *, site_origin: str, channel_label: str = "", operator_note: str = "") -> bool:
        send_calls.append(
            {
                "webhook_url": webhook_url,
                "site_origin": site_origin,
                "channel_label": channel_label,
                "operator_note": operator_note,
                "recommendation_id": recommendation["id"],
            }
        )
        return True

    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(routes_azure, "send_recommendation_teams_alert", _fake_send)
    monkeypatch.setattr(routes_azure, "AZURE_FINOPS_RECOMMENDATION_TEAMS_WEBHOOK_URL", "https://hooks.example.test/finops")
    monkeypatch.setattr(routes_azure, "AZURE_FINOPS_RECOMMENDATION_TEAMS_CHANNEL_LABEL", "FinOps Watch")
    monkeypatch.setattr(routes_azure, "AZURE_APP_HOST", "azure.movedocs.com")
    monkeypatch.setattr(auth, "is_admin_user", lambda email: True)

    resp = test_client.post(
        "/api/azure/recommendations/rec-1/actions/send-alert",
        headers={"host": "azure.movedocs.com"},
        json={"note": "Please review in standup."},
    )

    assert resp.status_code == 200
    assert resp.json()["alert_status"] == "sent"
    assert resp.json()["delivery_channel"] == "FinOps Watch"
    assert send_calls[0]["webhook_url"] == "https://hooks.example.test/finops"
    assert send_calls[0]["site_origin"] == "https://azure.movedocs.com"
    assert send_calls[0]["channel_label"] == "FinOps Watch"
    action_kwargs = mock_finops.update_recommendation_action_state.call_args.kwargs
    assert action_kwargs["action_state"] == "alert_sent"
    assert action_kwargs["action_type"] == "send_alert"
    assert action_kwargs["metadata"]["channel"] == "FinOps Watch"


def test_azure_recommendation_send_alert_records_failed_event(test_client, monkeypatch):
    import auth
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": True}
    mock_finops.get_recommendation.return_value = {
        "id": "rec-1",
        "title": "Release unattached public IP pip-1",
        "summary": "The address is not attached.",
        "category": "network",
        "opportunity_type": "unattached_public_ip",
    }
    mock_finops.get_recommendation_action_contract.return_value = {
        "recommendation_id": "rec-1",
        "actions": [
            {
                "action_type": "send_alert",
                "can_execute": True,
                "blocked_reason": "",
            }
        ],
    }

    async def _failing_send(*args, **kwargs):
        raise RuntimeError("teams unavailable")

    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(routes_azure, "send_recommendation_teams_alert", _failing_send)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: True)

    resp = test_client.post(
        "/api/azure/recommendations/rec-1/actions/send-alert",
        headers={"host": "azure.movedocs.com"},
        json={"teams_webhook_url": "https://hooks.example.test/finops", "channel": "FinOps Watch"},
    )

    assert resp.status_code == 502
    assert "Could not send Teams alert" in resp.json()["detail"]
    event_kwargs = mock_finops.record_recommendation_action_event.call_args.kwargs
    assert event_kwargs["action_type"] == "send_alert"
    assert event_kwargs["action_status"] == "failed"
    assert event_kwargs["metadata"]["channel"] == "FinOps Watch"
    assert "teams unavailable" in event_kwargs["metadata"]["error"]


def test_azure_recommendation_run_safe_script_executes_hook_and_persists_history(test_client, monkeypatch):
    import auth
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": True}
    mock_finops.get_recommendation.return_value = {
        "id": "rec-1",
        "title": "Right-size VM vm-1",
        "summary": "VM appears oversized for current utilization.",
        "category": "compute",
        "opportunity_type": "rightsizing",
    }
    mock_finops.get_recommendation_action_contract.return_value = {
        "recommendation_id": "rec-1",
        "actions": [
            {
                "action_type": "run_safe_script",
                "can_execute": True,
                "blocked_reason": "",
                "options": [{"key": "vm_echo", "label": "VM Echo", "default_dry_run": True, "allow_apply": False}],
            }
        ],
    }
    mock_finops.run_recommendation_safe_hook.return_value = {
        "recommendation": {"id": "rec-1", "action_state": "none"},
        "hook_key": "vm_echo",
        "hook_label": "VM Echo",
        "action_status": "dry_run",
        "dry_run": True,
        "started_at": "2026-03-23T16:00:00+00:00",
        "completed_at": "2026-03-23T16:00:01+00:00",
        "duration_ms": 1000,
        "exit_code": 0,
        "output_excerpt": "VM Echo completed in dry run mode for vm-1.",
    }

    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: True)

    resp = test_client.post(
        "/api/azure/recommendations/rec-1/actions/run-safe-script",
        headers={"host": "azure.movedocs.com"},
        json={"hook_key": "vm_echo", "dry_run": True, "note": "Preview cleanup"},
    )

    assert resp.status_code == 200
    assert resp.json()["hook_key"] == "vm_echo"
    assert resp.json()["action_status"] == "dry_run"
    run_kwargs = mock_finops.run_recommendation_safe_hook.call_args.kwargs
    assert run_kwargs["hook_key"] == "vm_echo"
    assert run_kwargs["dry_run"] is True
    assert run_kwargs["note"] == "Preview cleanup"


def test_azure_recommendation_run_safe_script_returns_502_on_hook_failure(test_client, monkeypatch):
    import auth
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": True}
    mock_finops.get_recommendation.return_value = {
        "id": "rec-1",
        "title": "Right-size VM vm-1",
        "summary": "VM appears oversized for current utilization.",
        "category": "compute",
        "opportunity_type": "rightsizing",
    }
    mock_finops.get_recommendation_action_contract.return_value = {
        "recommendation_id": "rec-1",
        "actions": [
            {
                "action_type": "run_safe_script",
                "can_execute": True,
                "blocked_reason": "",
                "options": [{"key": "vm_echo", "label": "VM Echo", "default_dry_run": True, "allow_apply": False}],
            }
        ],
    }
    mock_finops.run_recommendation_safe_hook.side_effect = RuntimeError("Safe remediation hook failed.")

    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: True)

    resp = test_client.post(
        "/api/azure/recommendations/rec-1/actions/run-safe-script",
        headers={"host": "azure.movedocs.com"},
        json={"hook_key": "vm_echo"},
    )

    assert resp.status_code == 502
    assert "Safe remediation hook failed" in resp.json()["detail"]


def test_azure_recommendation_direct_actions_require_admin(test_client, monkeypatch):
    import auth

    monkeypatch.setattr(auth, "is_admin_user", lambda email: False)

    create_ticket_resp = test_client.post(
        "/api/azure/recommendations/rec-1/actions/create-ticket",
        headers={"host": "azure.movedocs.com"},
        json={},
    )
    send_alert_resp = test_client.post(
        "/api/azure/recommendations/rec-1/actions/send-alert",
        headers={"host": "azure.movedocs.com"},
        json={},
    )
    run_safe_script_resp = test_client.post(
        "/api/azure/recommendations/rec-1/actions/run-safe-script",
        headers={"host": "azure.movedocs.com"},
        json={},
    )

    assert create_ticket_resp.status_code == 403
    assert send_alert_resp.status_code == 403
    assert run_safe_script_resp.status_code == 403


def test_azure_recommendation_action_state_rejects_invalid_state(test_client, monkeypatch):
    import auth
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    mock_cache.status.return_value = {"last_refresh": "2026-03-23T12:00:00+00:00"}
    mock_finops.refresh_recommendations_snapshot.return_value = {"available": True}
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: True)
    mock_finops.update_recommendation_action_state.side_effect = ValueError(
        "Unsupported recommendation action state: invalid"
    )

    resp = test_client.post(
        "/api/azure/recommendations/rec-1/action-state",
        headers={"host": "azure.movedocs.com"},
        json={"action_state": "invalid"},
    )

    assert resp.status_code == 400
    assert "Unsupported recommendation action state" in resp.json()["detail"]


def test_azure_refresh_requires_admin(test_client, monkeypatch):
    import auth

    monkeypatch.setattr(auth, "is_admin_user", lambda email: False)
    resp = test_client.post("/api/azure/refresh", headers={"host": "azure.movedocs.com"})
    assert resp.status_code == 403


def test_azure_cost_chat_returns_grounded_answer(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.get_grounding_context.return_value = {
        "cost_summary": {"lookback_days": 30, "total_cost": 200.0},
        "cost_trend": [],
        "cost_by_service": [],
        "vm_inventory_summary": {"total_vm_count": 3, "by_sku": [{"sku": "Standard_D4s_v5", "count": 2}]},
        "advisor": [],
    }
    mock_finops.get_cost_summary.return_value = None
    mock_finops.get_status.return_value = {"available": False}
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(
        routes_azure,
        "get_available_copilot_models",
        lambda: [AIModel(id="qwen3.5:4b", name="qwen3.5:4b", provider="ollama")],
    )
    monkeypatch.setattr(routes_azure, "get_default_copilot_model_id", lambda models: models[0].id)
    monkeypatch.setattr(
        routes_azure,
        "answer_azure_cost_question",
        lambda question, context, model_id, **kwargs: AzureCostChatResponse(
            answer=f"Answer for {question}",
            model_used=model_id,
            generated_at="2026-03-17T18:00:00+00:00",
            citations=[AzureCitation(source_type="summary", label="Cost summary", detail="30 days")],
        ),
    )

    resp = test_client.post(
        "/api/azure/ai/cost-chat",
        headers={"host": "azure.movedocs.com"},
        json={"question": "Where can we save money?"},
    )
    assert resp.status_code == 200
    assert resp.json()["model_used"] == "qwen3.5:4b"
    assert "save money" in resp.json()["answer"]


def test_azure_cost_chat_uses_preferred_default_model(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_finops = MagicMock()
    mock_cache.get_grounding_context.return_value = {
        "cost_summary": {"lookback_days": 30, "total_cost": 200.0},
        "cost_trend": [],
        "cost_by_service": [],
        "vm_inventory_summary": {"total_vm_count": 3, "by_sku": [{"sku": "Standard_D4s_v5", "count": 2}]},
        "advisor": [],
    }
    mock_finops.get_cost_summary.return_value = None
    mock_finops.get_status.return_value = {"available": False}
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_finops_service", mock_finops)
    monkeypatch.setattr(
        routes_azure,
        "get_available_copilot_models",
        lambda: [
            AIModel(id="nemotron-3-nano:4b", name="nemotron-3-nano:4b", provider="ollama"),
            AIModel(id="qwen3.5:4b", name="qwen3.5:4b", provider="ollama"),
        ],
    )
    monkeypatch.setattr(routes_azure, "get_default_copilot_model_id", lambda models: "qwen3.5:4b")

    seen: dict[str, str] = {}

    def fake_answer(question, context, model_id, **kwargs):
        seen["model_id"] = model_id
        return AzureCostChatResponse(
            answer=f"Answer for {question}",
            model_used=model_id,
            generated_at="2026-03-17T18:00:00+00:00",
            citations=[AzureCitation(source_type="summary", label="Cost summary", detail="30 days")],
        )

    monkeypatch.setattr(routes_azure, "answer_azure_cost_question", fake_answer)

    resp = test_client.post(
        "/api/azure/ai/cost-chat",
        headers={"host": "azure.movedocs.com"},
        json={"question": "Where can we save money?"},
    )

    assert resp.status_code == 200
    assert seen["model_id"] == "qwen3.5:4b"


def test_azure_vms_returns_cached_vm_inventory(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.list_virtual_machines.return_value = {
        "vms": [
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
                "name": "vm-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "subscription_id": "sub-1",
                "subscription_name": "Prod",
                "resource_group": "rg-prod",
                "location": "eastus",
                "kind": "",
                "sku_name": "",
                "vm_size": "Standard_D4s_v5",
                "state": "PowerState/running",
                "tags": {},
                "size": "Standard_D4s_v5",
                "power_state": "Running",
            }
        ],
        "matched_count": 1,
        "total_count": 2,
        "summary": {
            "total_vms": 2,
            "running_vms": 1,
            "deallocated_vms": 1,
            "distinct_sizes": 2,
        },
        "by_size": [
            {
                "label": "Standard_D4s_v5",
                "region": "eastus",
                "vm_count": 1,
                "reserved_instance_count": 1,
                "delta": 0,
                "coverage_status": "balanced",
            }
        ],
        "by_state": [{"label": "Running", "count": 1}, {"label": "Deallocated", "count": 1}],
        "reservation_data_available": True,
        "reservation_error": None,
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/vms", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total_vms"] == 2
    assert body["vms"][0]["size"] == "Standard_D4s_v5"
    assert body["by_size"][0]["reserved_instance_count"] == 1
    assert body["by_size"][0]["region"] == "eastus"


def test_azure_virtual_desktop_removal_candidates_returns_cached_payload(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.list_virtual_desktop_removal_candidates.return_value = {
        "desktops": [
            {
                "id": "vm-1",
                "name": "avd-vm-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "subscription_id": "sub-1",
                "subscription_name": "Prod",
                "resource_group": "rg-avd",
                "location": "eastus",
                "kind": "",
                "sku_name": "",
                "vm_size": "Standard_D4s_v5",
                "state": "PowerState/deallocated",
                "tags": {},
                "size": "Standard_D4s_v5",
                "power_state": "Deallocated",
                "assigned_user_display_name": "Ada Lovelace",
                "assigned_user_principal_name": "ada@example.com",
                "assigned_user_enabled": False,
                "assigned_user_licensed": True,
                "assigned_user_last_successful_utc": "2026-02-18T00:00:00+00:00",
                "assigned_user_last_successful_local": "2026-02-17 04:00 PM PST",
                "assignment_source": "avd:assigned-user",
                "assignment_status": "resolved",
                "assigned_user_source": "avd_assigned",
                "assigned_user_source_label": "AVD assigned user",
                "assigned_user_observed_utc": "",
                "assigned_user_observed_local": "",
                "owner_history_status": "available",
                "host_pool_name": "hostpool-1",
                "session_host_name": "hostpool-1/avd-vm-1.contoso.local",
                "last_power_signal_utc": "2026-02-20T00:00:00+00:00",
                "last_power_signal_local": "2026-02-19 04:00 PM PST",
                "days_since_power_signal": 32,
                "days_since_assigned_user_login": 34,
                "power_signal_stale": True,
                "power_signal_pending": False,
                "user_signin_stale": True,
                "mark_for_removal": True,
                "mark_account_for_follow_up": True,
                "account_action": "Already disabled",
                "removal_reasons": [
                    "No running signal in 14+ days",
                    "Assigned user is disabled",
                ],
                "utilization_status": "under_utilized",
                "under_utilized": True,
                "over_utilized": False,
                "utilization_data_available": True,
                "utilization_fully_evaluable": True,
                "cpu_data_available": True,
                "memory_data_available": True,
                "cpu_max_percent_7d": 41.0,
                "cpu_time_at_full_percent_7d": 0.0,
                "memory_max_percent_7d": 32.5,
                "memory_time_at_full_percent_7d": 0.0,
                "utilization_reasons": [
                    "Peak CPU over the last 7 days was 41.0%, below the 50% under-utilization threshold.",
                ],
                "utilization_error": "",
            }
        ],
        "matched_count": 1,
        "total_count": 1,
        "summary": {
            "threshold_days": 14,
            "tracked_desktops": 1,
            "removal_candidates": 1,
            "stale_power_signals": 1,
            "disabled_or_unlicensed_assignments": 1,
            "stale_assigned_user_signins": 1,
            "assignment_review_required": 0,
            "power_signal_pending": 0,
            "account_follow_up_count": 1,
            "explicit_avd_assignments": 1,
            "fallback_session_history_assignments": 0,
            "under_utilized": 1,
            "over_utilized": 0,
            "utilization_unavailable": 0,
            "owner_history_unavailable": 0,
        },
        "generated_at": "2026-03-23T00:00:00+00:00",
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get(
        "/api/azure/virtual-desktops/removal-candidates",
        headers={"host": "azure.movedocs.com"},
        params={
            "search": "ada",
            "removal_only": "true",
            "under_utilized_only": "true",
            "over_utilized_only": "false",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["removal_candidates"] == 1
    assert body["summary"]["under_utilized"] == 1
    assert body["desktops"][0]["assigned_user_source"] == "avd_assigned"
    mock_cache.list_virtual_desktop_removal_candidates.assert_called_once_with(
        search="ada",
        removal_only=True,
        under_utilized_only=True,
        over_utilized_only=False,
    )


def test_azure_virtual_desktop_detail_returns_cached_payload(test_client, monkeypatch):
    import routes_azure

    desktop_id = "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-1"

    mock_cache = MagicMock()
    mock_cache.get_virtual_desktop_detail.return_value = {
        "desktop": {
            "id": desktop_id,
            "name": "avd-vm-1",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "subscription_id": "sub-1",
            "subscription_name": "Prod",
            "resource_group": "rg-avd",
            "location": "eastus",
            "kind": "",
            "sku_name": "",
            "vm_size": "Standard_D4s_v5",
            "state": "PowerState/running",
            "tags": {},
            "size": "Standard_D4s_v5",
            "power_state": "Running",
            "assigned_user_display_name": "Ada Lovelace",
            "assigned_user_principal_name": "ada@example.com",
            "assigned_user_enabled": True,
            "assigned_user_licensed": True,
            "assigned_user_last_successful_utc": "2026-03-23T00:00:00+00:00",
            "assigned_user_last_successful_local": "2026-03-22 05:00 PM PDT",
            "assignment_source": "avd:assigned-user",
            "assignment_status": "resolved",
            "assigned_user_source": "avd_assigned",
            "assigned_user_source_label": "AVD assigned user",
            "assigned_user_observed_utc": "",
            "assigned_user_observed_local": "",
            "owner_history_status": "available",
            "host_pool_name": "hostpool-1",
            "session_host_name": "hostpool-1/avd-vm-1.contoso.local",
            "last_power_signal_utc": "2026-03-23T00:00:00+00:00",
            "last_power_signal_local": "2026-03-22 05:00 PM PDT",
            "days_since_power_signal": 0,
            "days_since_assigned_user_login": 0,
            "power_signal_stale": False,
            "power_signal_pending": False,
            "user_signin_stale": False,
            "mark_for_removal": False,
            "mark_account_for_follow_up": False,
            "account_action": "",
            "removal_reasons": [],
            "utilization_status": "over_utilized",
            "under_utilized": False,
            "over_utilized": True,
            "utilization_data_available": True,
            "utilization_fully_evaluable": True,
            "cpu_data_available": True,
            "memory_data_available": True,
            "cpu_max_percent_7d": 100.0,
            "cpu_time_at_full_percent_7d": 12.5,
            "memory_max_percent_7d": 76.0,
            "memory_time_at_full_percent_7d": 0.0,
            "utilization_reasons": ["CPU hit 100% utilization and stayed there for 12.5% of sampled time."],
            "utilization_error": "",
        },
        "utilization": {
            "lookback_days": 7,
            "under_threshold_percent": 50.0,
            "over_threshold_percent": 100.0,
            "interval": "PT1M",
            "status": "over_utilized",
            "under_utilized": False,
            "over_utilized": True,
            "utilization_data_available": True,
            "utilization_fully_evaluable": True,
            "cpu_data_available": True,
            "memory_data_available": True,
            "cpu_max_percent": 100.0,
            "cpu_points_at_full": 42,
            "cpu_total_points": 336,
            "cpu_time_at_full_percent": 12.5,
            "memory_max_percent": 76.0,
            "memory_points_at_full": 0,
            "memory_total_points": 336,
            "memory_time_at_full_percent": 0.0,
            "reasoning": ["CPU hit 100% utilization and stayed there for 12.5% of sampled time."],
            "error": "",
            "cpu_series": [{"timestamp": "2026-03-23T00:00:00+00:00", "label": "2026-03-22 05:00 PM PDT", "value": 100.0}],
            "memory_series": [{"timestamp": "2026-03-23T00:00:00+00:00", "label": "2026-03-22 05:00 PM PDT", "value": 76.0}],
        },
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get(
        "/api/azure/virtual-desktops/detail",
        headers={"host": "azure.movedocs.com"},
        params={"resource_id": desktop_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["desktop"]["id"] == desktop_id
    assert body["utilization"]["over_utilized"] is True
    assert body["utilization"]["cpu_series"][0]["value"] == 100.0
    mock_cache.get_virtual_desktop_detail.assert_called_once_with(desktop_id)


def test_azure_vm_detail_returns_cached_vm_drilldown(test_client, monkeypatch):
    import routes_azure

    vm_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1"

    mock_cache = MagicMock()
    mock_cache.get_virtual_machine_detail.return_value = {
        "vm": {
            "id": vm_id,
            "name": "vm-1",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "subscription_id": "sub-1",
            "subscription_name": "Prod",
            "resource_group": "rg-prod",
            "location": "eastus",
            "kind": "",
            "sku_name": "",
            "vm_size": "Standard_D4s_v5",
            "state": "PowerState/running",
            "tags": {},
            "size": "Standard_D4s_v5",
            "power_state": "Running",
        },
        "associated_resources": [
            {
                "id": vm_id,
                "name": "vm-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "relationship": "Virtual machine",
                "subscription_id": "sub-1",
                "subscription_name": "Prod",
                "resource_group": "rg-prod",
                "location": "eastus",
                "state": "PowerState/running",
                "cost": 82.5,
                "currency": "USD",
            }
        ],
        "cost": {
            "lookback_days": 30,
            "currency": "USD",
            "cost_data_available": True,
            "cost_error": None,
            "total_cost": 82.5,
            "vm_cost": 82.5,
            "related_resource_cost": 0.0,
            "priced_resource_count": 1,
        },
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get(
        "/api/azure/vms/detail",
        headers={"host": "azure.movedocs.com"},
        params={"resource_id": vm_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["vm"]["name"] == "vm-1"
    assert body["cost"]["total_cost"] == 82.5
    assert body["associated_resources"][0]["relationship"] == "Virtual machine"


def test_create_azure_vm_cost_export_job(test_client, monkeypatch):
    import routes_azure

    mock_jobs = MagicMock()
    mock_jobs.create_job.return_value = {
        "job_id": "job-123",
        "status": "queued",
        "recipient_email": "test@example.com",
        "scope": "filtered",
        "lookback_days": 30,
        "filters": {"search": "wvd", "subscription_id": "sub-1", "location": "", "state": "Running", "size": ""},
        "requested_at": "2026-03-18T00:00:00+00:00",
        "started_at": None,
        "completed_at": None,
        "progress_current": 0,
        "progress_total": 0,
        "progress_message": "Queued",
        "file_name": None,
        "file_ready": False,
        "error": None,
    }
    monkeypatch.setattr(routes_azure, "azure_vm_export_jobs", mock_jobs)

    resp = test_client.post(
        "/api/azure/vms/cost-export-jobs",
        headers={"host": "azure.movedocs.com"},
        json={
            "scope": "filtered",
            "lookback_days": 30,
            "filters": {
                "search": "wvd",
                "subscription_id": "sub-1",
                "state": "Running",
            },
        },
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"] == "job-123"
    assert body["scope"] == "filtered"
    assert body["recipient_email"] == "test@example.com"


def test_get_azure_vm_cost_export_job_status(test_client, monkeypatch):
    import routes_azure

    mock_jobs = MagicMock()
    mock_jobs.get_job.return_value = {
        "job_id": "job-123",
        "status": "running",
        "recipient_email": "test@example.com",
        "scope": "all",
        "lookback_days": 90,
        "filters": {},
        "requested_at": "2026-03-18T00:00:00+00:00",
        "started_at": "2026-03-18T00:01:00+00:00",
        "completed_at": None,
        "progress_current": 3,
        "progress_total": 8,
        "progress_message": "Querying live direct Azure cost data",
        "file_name": None,
        "file_ready": False,
        "error": None,
    }
    mock_jobs.job_belongs_to.return_value = True
    monkeypatch.setattr(routes_azure, "azure_vm_export_jobs", mock_jobs)

    resp = test_client.get("/api/azure/vms/cost-export-jobs/job-123", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert resp.json()["progress_message"] == "Querying live direct Azure cost data"


def test_download_azure_vm_cost_export_job(test_client, monkeypatch):
    import routes_azure

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    try:
        tmp.write(b"excel")
        tmp.close()

        mock_jobs = MagicMock()
        mock_jobs.get_job.return_value = {
            "job_id": "job-123",
            "status": "completed",
            "recipient_email": "test@example.com",
            "scope": "all",
            "lookback_days": 30,
            "filters": {},
            "requested_at": "2026-03-18T00:00:00+00:00",
            "started_at": "2026-03-18T00:01:00+00:00",
            "completed_at": "2026-03-18T00:03:00+00:00",
            "progress_current": 10,
            "progress_total": 10,
            "progress_message": "Export ready",
            "file_name": "azure_vm_costs.xlsx",
            "file_ready": True,
            "file_path": tmp.name,
            "error": None,
        }
        mock_jobs.job_belongs_to.return_value = True
        monkeypatch.setattr(routes_azure, "azure_vm_export_jobs", mock_jobs)

        resp = test_client.get("/api/azure/vms/cost-export-jobs/job-123/download", headers={"host": "azure.movedocs.com"})

        assert resp.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp.headers["content-type"]
        assert "attachment; filename=" in resp.headers["content-disposition"]
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


def test_azure_vm_coverage_csv_export(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.list_virtual_machines.return_value = {
        "by_size": [
            {
                "label": "Standard_E4as_v4",
                "region": "westus",
                "vm_count": 42,
                "reserved_instance_count": 37,
                "delta": 5,
                "coverage_status": "needed",
            }
        ]
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/vms/coverage/export.csv", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment; filename=" in resp.headers["content-disposition"]
    assert "Standard_E4as_v4" in resp.text
    assert "westus" in resp.text


def test_azure_vm_coverage_excel_export(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.list_virtual_machines.return_value = {
        "by_size": [
            {
                "label": "Standard_E4as_v4",
                "region": "westus",
                "vm_count": 42,
                "reserved_instance_count": 37,
                "delta": 5,
                "coverage_status": "needed",
            }
        ]
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/vms/coverage/export.xlsx", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp.headers["content-type"]
    assert "attachment; filename=" in resp.headers["content-disposition"]


def test_azure_vm_excess_csv_export(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.get_vm_excess_reservation_report.return_value = [
        {
            "label": "Standard_E4as_v4",
            "region": "westus",
            "vm_count": 1,
            "reserved_instance_count": 5,
            "excess_count": 4,
            "active_reservation_names": ["Westus E4 RI 1", "Westus E4 RI 2"],
        }
    ]
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/vms/excess/export.csv", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment; filename=" in resp.headers["content-disposition"]
    assert "Standard_E4as_v4" in resp.text
    assert "Westus E4 RI 1; Westus E4 RI 2" in resp.text


def test_azure_vm_excess_excel_export(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.get_vm_excess_reservation_report.return_value = [
        {
            "label": "Standard_E4as_v4",
            "region": "westus",
            "vm_count": 1,
            "reserved_instance_count": 5,
            "excess_count": 4,
            "active_reservation_names": ["Westus E4 RI 1", "Westus E4 RI 2"],
        }
    ]
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/vms/excess/export.xlsx", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp.headers["content-type"]
    assert "attachment; filename=" in resp.headers["content-disposition"]
