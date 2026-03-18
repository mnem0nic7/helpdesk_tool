from __future__ import annotations

from azure_cache import AzureCache
from azure_client import AzureApiError


def test_get_vm_inventory_summary_groups_virtual_machines_by_size(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "vm-1",
                    "name": "vm-1",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D4s_v5",
                    "state": "running",
                    "tags": {},
                },
                {
                    "id": "vm-2",
                    "name": "vm-2",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D4s_v5",
                    "state": "running",
                    "tags": {},
                },
                {
                    "id": "vm-3",
                    "name": "vm-3",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-2",
                    "subscription_name": "Dev",
                    "resource_group": "rg-dev",
                    "location": "westus",
                    "kind": "",
                    "sku_name": "Standard_B2ms",
                    "vm_size": "",
                    "state": "running",
                    "tags": {},
                },
                {
                    "id": "sa-1",
                    "name": "sa-1",
                    "resource_type": "Microsoft.Storage/storageAccounts",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "Standard_LRS",
                    "vm_size": "",
                    "state": "Succeeded",
                    "tags": {},
                },
            ]
        }
    )

    summary = cache.get_vm_inventory_summary()

    assert summary["total_vm_count"] == 3
    assert summary["sku_count"] == 2
    assert summary["by_sku"] == [
        {"sku": "Standard_D4s_v5", "count": 2},
        {"sku": "Standard_B2ms", "count": 1},
    ]
    assert summary["by_subscription"] == [
        {"subscription_name": "Prod", "count": 2},
        {"subscription_name": "Dev", "count": 1},
    ]


def test_get_grounding_context_includes_vm_inventory_summary(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "vm-1",
                    "name": "vm-1",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D4s_v5",
                    "state": "running",
                    "tags": {},
                }
            ]
        }
    )

    context = cache.get_grounding_context()

    assert context["vm_inventory_summary"]["total_vm_count"] == 1
    assert context["vm_inventory_summary"]["by_sku"] == [
        {"sku": "Standard_D4s_v5", "count": 1}
    ]


def test_get_virtual_machine_detail_returns_related_resources_and_costs(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    vm_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1"
    nic_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-1"
    os_disk_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/osdisk-1"
    data_disk_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/datadisk-1"
    public_ip_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/publicIPAddresses/pip-1"
    extension_id = f"{vm_id}/extensions/monitoring"

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": vm_id,
                    "name": "vm-1",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "parent_resource_id": "",
                    "managed_by": "",
                    "attached_vm_id": "",
                    "network_interface_ids": [nic_id],
                    "os_disk_id": os_disk_id,
                    "data_disk_ids": [data_disk_id],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D4s_v5",
                    "state": "PowerState/running",
                    "tags": {},
                },
                {
                    "id": nic_id,
                    "name": "nic-1",
                    "resource_type": "Microsoft.Network/networkInterfaces",
                    "parent_resource_id": "",
                    "managed_by": "",
                    "attached_vm_id": vm_id,
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [public_ip_id],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "",
                    "state": "Succeeded",
                    "tags": {},
                },
                {
                    "id": os_disk_id,
                    "name": "osdisk-1",
                    "resource_type": "Microsoft.Compute/disks",
                    "parent_resource_id": "",
                    "managed_by": vm_id,
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "Premium_LRS",
                    "vm_size": "",
                    "state": "Succeeded",
                    "tags": {},
                },
                {
                    "id": data_disk_id,
                    "name": "datadisk-1",
                    "resource_type": "Microsoft.Compute/disks",
                    "parent_resource_id": "",
                    "managed_by": vm_id,
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "Premium_LRS",
                    "vm_size": "",
                    "state": "Succeeded",
                    "tags": {},
                },
                {
                    "id": public_ip_id,
                    "name": "pip-1",
                    "resource_type": "Microsoft.Network/publicIPAddresses",
                    "parent_resource_id": "",
                    "managed_by": "",
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "Standard",
                    "vm_size": "",
                    "state": "Succeeded",
                    "tags": {},
                },
                {
                    "id": extension_id,
                    "name": "monitoring",
                    "resource_type": "Microsoft.Compute/virtualMachines/extensions",
                    "parent_resource_id": vm_id,
                    "managed_by": "",
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "",
                    "state": "Succeeded",
                    "tags": {},
                },
            ],
            "cost_summary": {
                "lookback_days": 30,
                "currency": "USD",
                "total_cost": 0.0,
                "top_service": "",
                "top_subscription": "",
                "top_resource_group": "",
                "recommendation_count": 0,
                "potential_monthly_savings": 0.0,
            },
            "cost_by_resource_id_status": {"available": True, "error": None, "cost_basis": "amortized"},
            "cost_by_resource_id": [
                {"label": vm_id, "amount": 82.5, "currency": "USD", "share": 0.0},
                {"label": nic_id, "amount": 3.25, "currency": "USD", "share": 0.0},
                {"label": os_disk_id, "amount": 19.0, "currency": "USD", "share": 0.0},
                {"label": data_disk_id, "amount": 6.5, "currency": "USD", "share": 0.0},
                {"label": public_ip_id, "amount": 1.75, "currency": "USD", "share": 0.0},
            ],
        }
    )

    detail = cache.get_virtual_machine_detail(vm_id)

    assert detail is not None
    assert detail["vm"]["name"] == "vm-1"
    assert detail["vm"]["size"] == "Standard_D4s_v5"
    assert detail["cost"] == {
        "lookback_days": 30,
        "currency": "USD",
        "cost_data_available": True,
        "cost_error": None,
        "total_cost": 113.0,
        "vm_cost": 82.5,
        "related_resource_cost": 30.5,
        "priced_resource_count": 5,
    }
    relationships = {item["id"]: item["relationship"] for item in detail["associated_resources"]}
    assert relationships[vm_id] == "Virtual machine"
    assert relationships[os_disk_id] == "OS disk"
    assert relationships[data_disk_id] == "Data disk"
    assert relationships[nic_id] == "Network interface"
    assert relationships[public_ip_id] == "Public IP"
    assert relationships[extension_id] == "Child resource"


def test_get_virtual_machine_detail_falls_back_to_targeted_cost_query_when_snapshot_unavailable(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    vm_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1"
    os_disk_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/osdisk-1"

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": vm_id,
                    "name": "vm-1",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "parent_resource_id": "",
                    "managed_by": "",
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": os_disk_id,
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D4s_v5",
                    "state": "PowerState/running",
                    "tags": {},
                },
                {
                    "id": os_disk_id,
                    "name": "osdisk-1",
                    "resource_type": "Microsoft.Compute/disks",
                    "parent_resource_id": "",
                    "managed_by": vm_id,
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "",
                    "state": "Succeeded",
                    "tags": {},
                },
            ],
            "cost_summary": {
                "lookback_days": 30,
                "currency": "USD",
                "total_cost": 0.0,
                "top_service": "",
                "top_subscription": "",
                "top_resource_group": "",
                "recommendation_count": 0,
                "potential_monthly_savings": 0.0,
            },
            "cost_by_resource_id_status": {
                "available": False,
                "error": "POST https://management.azure.com/subscriptions/sub-1/providers/Microsoft.CostManagement/query failed (429): Too many requests",
                "cost_basis": "amortized",
            },
            "cost_by_resource_id": [],
        }
    )

    monkeypatch.setattr(
        cache._client,
        "get_cost_by_resource_ids",
        lambda subscription_id, resource_ids, lookback_days=None, chunk_size=20, cost_type="AmortizedCost", caller="default", max_attempts=3: [
            {"label": vm_id, "amount": 82.5, "currency": "USD", "share": 0.9621},
            {"label": os_disk_id, "amount": 3.25, "currency": "USD", "share": 0.0379},
        ],
    )

    detail = cache.get_virtual_machine_detail(vm_id)

    assert detail is not None
    assert detail["cost"] == {
        "lookback_days": 30,
        "currency": "USD",
        "cost_data_available": True,
        "cost_error": None,
        "total_cost": 85.75,
        "vm_cost": 82.5,
        "related_resource_cost": 3.25,
        "priced_resource_count": 2,
    }


def test_get_virtual_machine_detail_falls_back_when_resource_cost_cache_uses_legacy_basis(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    vm_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1"

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": vm_id,
                    "name": "vm-1",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "parent_resource_id": "",
                    "managed_by": "",
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D4s_v5",
                    "state": "PowerState/running",
                    "tags": {},
                }
            ],
            "cost_summary": {
                "lookback_days": 30,
                "currency": "USD",
                "total_cost": 0.0,
                "top_service": "",
                "top_subscription": "",
                "top_resource_group": "",
                "recommendation_count": 0,
                "potential_monthly_savings": 0.0,
            },
            "cost_by_resource_id_status": {"available": True, "error": None},
            "cost_by_resource_id": [
                {"label": vm_id, "amount": 0.0, "currency": "USD", "share": 0.0},
            ],
        }
    )

    monkeypatch.setattr(
        cache._client,
        "get_cost_by_resource_ids",
        lambda subscription_id, resource_ids, lookback_days=None, chunk_size=20, cost_type="AmortizedCost", caller="default", max_attempts=3: [
            {"label": vm_id, "amount": 14.25, "currency": "USD", "share": 1.0},
        ],
    )

    detail = cache.get_virtual_machine_detail(vm_id)

    assert detail is not None
    assert detail["cost"]["cost_data_available"] is True
    assert detail["cost"]["total_cost"] == 14.25
    assert detail["cost"]["vm_cost"] == 14.25
    assert detail["cost"]["priced_resource_count"] == 1


def test_build_virtual_machine_cost_export_returns_summary_detail_and_shared_rows(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    vm_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1"
    os_disk_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/osdisk-1"
    extension_id = f"{vm_id}/extensions/monitoring"
    workspace_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.OperationalInsights/workspaces/la-prod"

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": vm_id,
                    "name": "vm-1",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "parent_resource_id": "",
                    "managed_by": "",
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": os_disk_id,
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D4s_v5",
                    "state": "PowerState/running",
                    "tags": {},
                },
                {
                    "id": os_disk_id,
                    "name": "osdisk-1",
                    "resource_type": "Microsoft.Compute/disks",
                    "parent_resource_id": "",
                    "managed_by": vm_id,
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "Premium_LRS",
                    "vm_size": "",
                    "state": "Succeeded",
                    "tags": {},
                },
                {
                    "id": extension_id,
                    "name": "monitoring",
                    "resource_type": "Microsoft.Compute/virtualMachines/extensions",
                    "parent_resource_id": vm_id,
                    "managed_by": "",
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "",
                    "state": "Succeeded",
                    "tags": {},
                },
                {
                    "id": workspace_id,
                    "name": "la-prod",
                    "resource_type": "Microsoft.OperationalInsights/workspaces",
                    "parent_resource_id": "",
                    "managed_by": "",
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "",
                    "state": "Succeeded",
                    "tags": {},
                },
            ],
            "cost_summary": {
                "lookback_days": 30,
                "currency": "USD",
                "total_cost": 0.0,
                "top_service": "",
                "top_subscription": "",
                "top_resource_group": "",
                "recommendation_count": 0,
                "potential_monthly_savings": 0.0,
            },
        }
    )

    def fake_get_cost_by_resource_ids(
        subscription_id,
        resource_ids,
        lookback_days=None,
        chunk_size=20,
        cost_type="AmortizedCost",
        caller="default",
        max_attempts=3,
    ):
        assert subscription_id == "sub-1"
        assert lookback_days == 30
        assert caller == "export"
        assert max_attempts == 1
        normalized = {resource_id.lower() for resource_id in resource_ids}
        rows = []
        if vm_id.lower() in normalized:
            rows.append({"label": vm_id, "amount": 50.0, "currency": "USD", "share": 0.5})
        if os_disk_id.lower() in normalized:
            rows.append({"label": os_disk_id, "amount": 10.0, "currency": "USD", "share": 0.1})
        if workspace_id.lower() in normalized:
            rows.append({"label": workspace_id, "amount": 25.0, "currency": "USD", "share": 0.25})
        return rows

    monkeypatch.setattr(cache._client, "get_cost_by_resource_ids", fake_get_cost_by_resource_ids)

    payload = cache.build_virtual_machine_cost_export(scope="all", filters={}, lookback_days=30)

    assert payload["vm_count"] == 1
    assert payload["summary_rows"][0]["vm_name"] == "vm-1"
    assert payload["summary_rows"][0]["vm_only_cost"] == 50.0
    assert payload["summary_rows"][0]["direct_attached_resource_cost"] == 10.0
    assert payload["summary_rows"][0]["direct_total_cost"] == 60.0
    assert payload["summary_rows"][0]["shared_candidate_count"] == 1
    assert payload["summary_rows"][0]["shared_candidate_amount"] == 25.0
    assert payload["summary_rows"][0]["cost_status"] == "Direct costs complete"

    detail_rows = payload["detail_rows"]
    assert {row["relationship"] for row in detail_rows} == {"Virtual machine", "OS disk", "Child resource"}
    assert next(row for row in detail_rows if row["relationship"] == "Virtual machine")["pricing_status"] == "priced"
    assert next(row for row in detail_rows if row["relationship"] == "OS disk")["cost"] == 10.0
    assert next(row for row in detail_rows if row["relationship"] == "Child resource")["pricing_status"] == "not_applicable"

    assert payload["shared_rows"] == [
        {
            "resource_name": "la-prod",
            "resource_id": workspace_id,
            "resource_type": "Microsoft.OperationalInsights/workspaces",
            "subscription": "Prod",
            "resource_group": "rg-prod",
            "region": "eastus",
            "cost": 25.0,
            "currency": "USD",
            "candidate_vm_count": 1,
            "candidate_vm_names": "vm-1",
            "reason": "same resource group as selected VM(s)",
        }
    ]


def test_build_virtual_machine_cost_export_respects_filtered_scope(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "vm-east",
                    "name": "vm-east",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-east",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D4s_v5",
                    "state": "PowerState/running",
                    "tags": {},
                },
                {
                    "id": "vm-west",
                    "name": "vm-west",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-west",
                    "location": "westus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D2as_v5",
                    "state": "PowerState/deallocated",
                    "tags": {},
                },
            ],
            "cost_summary": {
                "lookback_days": 30,
                "currency": "USD",
                "total_cost": 0.0,
                "top_service": "",
                "top_subscription": "",
                "top_resource_group": "",
                "recommendation_count": 0,
                "potential_monthly_savings": 0.0,
            },
        }
    )
    calls: list[int | None] = []

    def fake_get_cost_by_resource_ids(
        subscription_id,
        resource_ids,
        lookback_days=None,
        chunk_size=20,
        cost_type="AmortizedCost",
        caller="default",
        max_attempts=3,
    ):
        calls.append(lookback_days)
        assert caller == "export"
        assert max_attempts == 1
        return [{"label": "vm-east", "amount": 15.0, "currency": "USD", "share": 1.0}]

    monkeypatch.setattr(cache._client, "get_cost_by_resource_ids", fake_get_cost_by_resource_ids)

    payload = cache.build_virtual_machine_cost_export(
        scope="filtered",
        filters={"search": "vm-east"},
        lookback_days=7,
    )

    assert payload["vm_count"] == 1
    assert payload["summary_rows"][0]["vm_name"] == "vm-east"
    assert calls == [7]


def test_refresh_cost_uses_amortized_resource_level_breakdown(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    calls: list[tuple[str, str, int | None]] = []

    monkeypatch.setattr(
        cache._client,
        "list_subscriptions",
        lambda: [{"subscription_id": "sub-1", "display_name": "Prod"}],
    )
    monkeypatch.setattr(cache._client, "get_cost_trend", lambda subscriptions: [])

    def fake_breakdown(subscriptions, grouping_dimension, *, limit=20, cost_type="ActualCost"):
        calls.append((grouping_dimension, cost_type, limit))
        return []

    monkeypatch.setattr(cache._client, "get_cost_breakdown", fake_breakdown)
    monkeypatch.setattr(cache._client, "list_advisor_recommendations", lambda subscriptions: [])

    cache._refresh_cost()

    assert ("ServiceName", "ActualCost", 20) in calls
    assert ("SubscriptionName", "ActualCost", 20) in calls
    assert ("ResourceGroupName", "ActualCost", 20) in calls
    assert ("ResourceId", "AmortizedCost", None) in calls
    assert cache._snapshot("cost_by_resource_id_status") == {
        "available": True,
        "error": None,
        "cost_basis": "amortized",
    }


def test_refresh_cost_skips_resourceid_breakdown_while_export_is_running(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    calls: list[tuple[str, str, int | None]] = []
    previous_rows = [{"label": "vm-1", "amount": 12.0, "currency": "USD", "share": 1.0}]
    previous_status = {"available": True, "error": None, "cost_basis": "amortized"}

    cache._update_snapshots(
        {
            "cost_by_resource_id": previous_rows,
            "cost_by_resource_id_status": previous_status,
        }
    )

    monkeypatch.setattr(
        cache._client,
        "list_subscriptions",
        lambda: [{"subscription_id": "sub-1", "display_name": "Prod"}],
    )
    monkeypatch.setattr(cache._client, "get_cost_trend", lambda subscriptions: [])

    def fake_breakdown(subscriptions, grouping_dimension, *, limit=20, cost_type="ActualCost"):
        calls.append((grouping_dimension, cost_type, limit))
        if grouping_dimension == "ResourceId":
            raise AssertionError("ResourceId breakdown should be skipped while an export is active")
        return []

    monkeypatch.setattr(cache._client, "get_cost_breakdown", fake_breakdown)
    monkeypatch.setattr(cache._client, "list_advisor_recommendations", lambda subscriptions: [])

    with cache._client.cost_query_coordinator.export_job():
        cache._refresh_cost()

    assert ("ServiceName", "ActualCost", 20) in calls
    assert ("SubscriptionName", "ActualCost", 20) in calls
    assert ("ResourceGroupName", "ActualCost", 20) in calls
    assert cache._snapshot("cost_by_resource_id") == previous_rows
    assert cache._snapshot("cost_by_resource_id_status") == previous_status


def test_fetch_live_resource_cost_index_retries_throttled_chunks_without_requerying_successes(
    tmp_path,
    monkeypatch,
):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    calls: list[list[str]] = []
    sleep_calls: list[float] = []
    vm_ids = [f"/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-{index}" for index in range(1, 7)]

    def fake_get_cost_by_resource_ids(
        subscription_id,
        resource_ids,
        lookback_days=None,
        chunk_size=20,
        cost_type="AmortizedCost",
        caller="default",
        max_attempts=3,
    ):
        calls.append(list(resource_ids))
        assert caller == "export"
        assert max_attempts == 1
        if len(resource_ids) == 5:
            raise AzureApiError(
                "POST https://management.azure.com/... failed (429): throttled",
                status_code=429,
                headers={"retry-after": "3"},
            )
        return [
            {"label": resource_id, "amount": 10.0, "currency": "USD", "share": 1.0}
            for resource_id in resource_ids
        ]

    monkeypatch.setattr(cache._client, "get_cost_by_resource_ids", fake_get_cost_by_resource_ids)
    monkeypatch.setattr("azure_cache.time.sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr("azure_cache.time.monotonic", lambda: 0.0)

    rows = cache._fetch_live_resource_cost_index(
        {"sub-1": vm_ids},
        lookback_days=30,
        deadline_monotonic=10_000.0,
    )

    assert len(rows) == 6
    assert calls == [vm_ids[:5], vm_ids[:2], vm_ids[2:4], vm_ids[4:6]]
    assert sleep_calls == [5, 2.0, 2.0]


def test_fetch_live_resource_cost_index_fails_after_runtime_budget_is_exhausted(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    vm_ids = [f"/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-{index}" for index in range(1, 3)]
    timeline = iter([100.0, 102.0])
    sleep_calls: list[float] = []

    monkeypatch.setattr(
        cache._client,
        "get_cost_by_resource_ids",
        lambda subscription_id, resource_ids, lookback_days=None, chunk_size=20, cost_type="AmortizedCost", caller="default", max_attempts=3: (_ for _ in ()).throw(
            AzureApiError(
                "POST https://management.azure.com/... failed (429): throttled",
                status_code=429,
                headers={"retry-after": "1"},
            )
        ),
    )
    monkeypatch.setattr("azure_cache.time.sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr("azure_cache.time.monotonic", lambda: next(timeline))

    try:
        cache._fetch_live_resource_cost_index(
            {"sub-1": vm_ids},
            lookback_days=30,
            deadline_monotonic=101.5,
        )
    except TimeoutError as exc:
        assert "Azure Cost throttling prevented export completion" in str(exc)
    else:
        raise AssertionError("Expected export cost collection to fail once the runtime budget was exhausted")

    assert sleep_calls == [3]


def test_list_virtual_machines_returns_vm_summary_and_filtered_rows(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "vm-1",
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
                    "tags": {"env": "prod"},
                },
                {
                    "id": "vm-2",
                    "name": "vm-2",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D2as_v5",
                    "state": "PowerState/deallocated",
                    "tags": {},
                },
                {
                    "id": "sa-1",
                    "name": "sa-1",
                    "resource_type": "Microsoft.Storage/storageAccounts",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "",
                    "state": "Succeeded",
                    "tags": {},
                },
            ]
        }
    )

    payload = cache.list_virtual_machines(state="Running")

    assert payload["summary"] == {
        "total_vms": 2,
        "running_vms": 1,
        "deallocated_vms": 1,
        "distinct_sizes": 2,
    }
    assert payload["matched_count"] == 1
    assert payload["total_count"] == 2
    assert payload["vms"][0]["size"] == "Standard_D4s_v5"
    assert payload["vms"][0]["power_state"] == "Running"


def test_list_virtual_machines_includes_reservation_gap_and_excess_rows(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "vm-1",
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
                },
                {
                    "id": "vm-2",
                    "name": "vm-2",
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
                },
            ],
            "reservations": [
                {"sku": "Standard_D4s_v5", "location": "eastus", "quantity": 1},
                {"sku": "Standard_E4as_v4", "location": "westus", "quantity": 3},
            ],
            "reservation_status": {"available": True, "error": None},
        }
    )

    payload = cache.list_virtual_machines()

    assert payload["reservation_data_available"] is True
    assert payload["by_size"][:2] == [
        {
            "label": "Standard_E4as_v4",
            "region": "westus",
            "vm_count": 0,
            "reserved_instance_count": 3,
            "delta": -3,
            "coverage_status": "excess",
        },
        {
            "label": "Standard_D4s_v5",
            "region": "eastus",
            "vm_count": 2,
            "reserved_instance_count": 1,
            "delta": 1,
            "coverage_status": "needed",
        },
    ]


def test_list_virtual_machines_matches_reservations_by_sku_and_region(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "vm-east-1",
                    "name": "vm-east-1",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-east",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_E4as_v4",
                    "state": "PowerState/running",
                    "tags": {},
                },
                {
                    "id": "vm-west-1",
                    "name": "vm-west-1",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-west",
                    "location": "westus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_E4as_v4",
                    "state": "PowerState/running",
                    "tags": {},
                },
            ],
            "reservations": [
                {"sku": "Standard_E4as_v4", "location": "westus", "quantity": 2},
            ],
            "reservation_status": {"available": True, "error": None},
        }
    )

    payload = cache.list_virtual_machines()

    assert sorted(payload["by_size"], key=lambda item: item["region"]) == [
        {
            "label": "Standard_E4as_v4",
            "region": "eastus",
            "vm_count": 1,
            "reserved_instance_count": 0,
            "delta": 1,
            "coverage_status": "needed",
        },
        {
            "label": "Standard_E4as_v4",
            "region": "westus",
            "vm_count": 1,
            "reserved_instance_count": 2,
            "delta": -1,
            "coverage_status": "excess",
        },
    ]


def test_get_vm_excess_reservation_report_includes_all_active_reservation_names(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "vm-west-1",
                    "name": "vm-west-1",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-west",
                    "location": "westus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_E4as_v4",
                    "state": "PowerState/running",
                    "tags": {},
                }
            ],
            "reservations": [
                {
                    "sku": "Standard_E4as_v4",
                    "location": "westus",
                    "quantity": 2,
                    "display_name": "Westus E4 RI 1",
                },
                {
                    "sku": "Standard_E4as_v4",
                    "location": "westus",
                    "quantity": 3,
                    "display_name": "Westus E4 RI 2",
                },
                {
                    "sku": "Standard_E4as_v4",
                    "location": "eastus",
                    "quantity": 4,
                    "display_name": "Eastus E4 RI",
                },
            ],
            "reservation_status": {"available": True, "error": None},
        }
    )

    payload = cache.get_vm_excess_reservation_report()

    assert payload == [
        {
            "label": "Standard_E4as_v4",
            "region": "westus",
            "vm_count": 1,
            "reserved_instance_count": 5,
            "excess_count": 4,
            "active_reservation_names": ["Westus E4 RI 1", "Westus E4 RI 2"],
        },
        {
            "label": "Standard_E4as_v4",
            "region": "eastus",
            "vm_count": 0,
            "reserved_instance_count": 4,
            "excess_count": 4,
            "active_reservation_names": ["Eastus E4 RI"],
        },
    ]


def test_inventory_refresh_continues_when_reservations_are_unauthorized(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))

    monkeypatch.setattr(
        cache._client,
        "list_subscriptions",
        lambda: [
            {
                "subscription_id": "sub-1",
                "display_name": "Prod",
                "state": "Enabled",
                "tenant_id": "tenant-1",
                "authorization_source": "RoleBased",
            }
        ],
    )
    monkeypatch.setattr(cache._client, "list_management_groups", lambda: [])
    monkeypatch.setattr(
        cache._client,
        "query_resources",
        lambda subscription_ids: [
            {
                "id": "vm-1",
                "name": "vm-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "subscription_id": "sub-1",
                "subscription_name": "",
                "resource_group": "rg-prod",
                "location": "eastus",
                "kind": "",
                "sku_name": "",
                "vm_size": "Standard_D4s_v5",
                "state": "running",
                "tags": {},
            }
        ],
    )
    monkeypatch.setattr(cache._client, "list_role_assignments", lambda subscription_ids: [])
    monkeypatch.setattr(
        cache._client,
        "list_reservations",
        lambda: (_ for _ in ()).throw(
            AzureApiError("GET https://management.azure.com/providers/Microsoft.Capacity/reservations failed (403)")
        ),
    )

    cache._refresh_inventory()

    status = cache.status()
    inventory = next(dataset for dataset in status["datasets"] if dataset["key"] == "inventory")

    assert inventory["error"] is None
    assert cache._snapshot("reservations") == []
    assert cache._snapshot("reservation_status") == {
        "available": False,
        "error": "GET https://management.azure.com/providers/Microsoft.Capacity/reservations failed (403)",
    }
