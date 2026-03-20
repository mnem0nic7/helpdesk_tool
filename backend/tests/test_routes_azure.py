from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

from models import AIModel, AzureCitation, AzureCostChatResponse


def test_azure_overview_returns_cached_payload(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cost_exports = MagicMock()
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
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_cost_export_service", mock_cost_exports)

    resp = test_client.get("/api/azure/overview", headers={"host": "azure.movedocs.com"})
    assert resp.status_code == 200
    assert resp.json()["subscriptions"] == 4
    assert resp.json()["cost"]["total_cost"] == 1234.56
    assert resp.json()["cost_exports"]["health"]["delivery_count"] == 2


def test_azure_overview_is_not_available_on_helpdesk_host(test_client):
    resp = test_client.get("/api/azure/overview")
    assert resp.status_code == 404


def test_azure_status_includes_cost_export_status(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cost_exports = MagicMock()
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
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(routes_azure, "azure_cost_export_service", mock_cost_exports)

    resp = test_client.get("/api/azure/status", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["configured"] is True
    assert payload["cost_exports"]["running"] is True
    assert payload["cost_exports"]["health"]["quarantined_count"] == 1


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


def test_directory_users_is_not_available_on_oasisdev_host(test_client):
    resp = test_client.get("/api/azure/directory/users", headers={"host": "oasisdev.movedocs.com"})

    assert resp.status_code == 404


def test_azure_savings_summary_returns_cached_payload(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
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
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/savings/summary", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert resp.json()["quantified_monthly_savings"] == 125.0


def test_azure_savings_opportunities_pass_filters_to_cache(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
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
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

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
    mock_cache.list_savings_opportunities.assert_called_once_with(
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


def test_azure_savings_endpoints_are_not_available_on_primary_host(test_client):
    resp = test_client.get("/api/azure/savings/summary")
    assert resp.status_code == 404


def test_azure_savings_csv_export_returns_filtered_rows(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
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
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get(
        "/api/azure/savings/export.csv",
        headers={"host": "azure.movedocs.com"},
        params={"category": "network"},
    )

    assert resp.status_code == 200
    assert "Release unattached public IP" in resp.text
    mock_cache.list_savings_opportunities.assert_called_once()


def test_azure_savings_xlsx_export_returns_workbook(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.list_savings_opportunities.return_value = []
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/savings/export.xlsx", headers={"host": "azure.movedocs.com"})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_azure_refresh_requires_admin(test_client, monkeypatch):
    import auth

    monkeypatch.setattr(auth, "is_admin_user", lambda email: False)
    resp = test_client.post("/api/azure/refresh", headers={"host": "azure.movedocs.com"})
    assert resp.status_code == 403


def test_azure_cost_chat_returns_grounded_answer(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.get_grounding_context.return_value = {
        "cost_summary": {"lookback_days": 30, "total_cost": 200.0},
        "cost_trend": [],
        "cost_by_service": [],
        "vm_inventory_summary": {"total_vm_count": 3, "by_sku": [{"sku": "Standard_D4s_v5", "count": 2}]},
        "advisor": [],
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(
        routes_azure,
        "get_available_copilot_models",
        lambda: [AIModel(id="gpt-4o-mini", name="GPT-4o Mini", provider="openai")],
    )
    monkeypatch.setattr(routes_azure, "get_default_copilot_model_id", lambda models: models[0].id)
    monkeypatch.setattr(
        routes_azure,
        "answer_azure_cost_question",
        lambda question, context, model_id: AzureCostChatResponse(
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
    assert resp.json()["model_used"] == "gpt-4o-mini"
    assert "save money" in resp.json()["answer"]


def test_azure_cost_chat_uses_preferred_default_model(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
    mock_cache.get_grounding_context.return_value = {
        "cost_summary": {"lookback_days": 30, "total_cost": 200.0},
        "cost_trend": [],
        "cost_by_service": [],
        "vm_inventory_summary": {"total_vm_count": 3, "by_sku": [{"sku": "Standard_D4s_v5", "count": 2}]},
        "advisor": [],
    }
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)
    monkeypatch.setattr(
        routes_azure,
        "get_available_copilot_models",
        lambda: [
            AIModel(id="gpt-3.5-turbo", name="gpt-3.5-turbo", provider="openai"),
            AIModel(id="gpt-5.4-mini", name="gpt-5.4-mini", provider="openai"),
        ],
    )
    monkeypatch.setattr(routes_azure, "get_default_copilot_model_id", lambda models: "gpt-5.4-mini")

    seen: dict[str, str] = {}

    def fake_answer(question, context, model_id):
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
    assert seen["model_id"] == "gpt-5.4-mini"


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
