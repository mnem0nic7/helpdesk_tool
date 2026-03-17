from __future__ import annotations

from unittest.mock import MagicMock

from models import AIModel, AzureCitation, AzureCostChatResponse


def test_azure_overview_returns_cached_payload(test_client, monkeypatch):
    import routes_azure

    mock_cache = MagicMock()
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
    monkeypatch.setattr(routes_azure, "azure_cache", mock_cache)

    resp = test_client.get("/api/azure/overview", headers={"host": "azure.movedocs.com"})
    assert resp.status_code == 200
    assert resp.json()["subscriptions"] == 4
    assert resp.json()["cost"]["total_cost"] == 1234.56


def test_azure_overview_is_not_available_on_helpdesk_host(test_client):
    resp = test_client.get("/api/azure/overview")
    assert resp.status_code == 404


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
