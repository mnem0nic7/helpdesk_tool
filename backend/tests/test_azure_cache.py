from __future__ import annotations

from datetime import datetime, timedelta, timezone

from azure_cache import AzureCache
from azure_client import AzureApiError


def test_normalize_user_preserves_unknown_and_explicit_license_states():
    unknown_user = AzureCache._normalize_user(
        {
            "id": "user-unknown",
            "displayName": "Unknown License",
            "userPrincipalName": "unknown@example.com",
        }
    )
    unlicensed_user = AzureCache._normalize_user(
        {
            "id": "user-unlicensed",
            "displayName": "No License",
            "userPrincipalName": "nolicense@example.com",
            "assignedLicenses": [],
        }
    )
    licensed_user = AzureCache._normalize_user(
        {
            "id": "user-licensed",
            "displayName": "Has License",
            "userPrincipalName": "licensed@example.com",
            "assignedLicenses": [{"skuId": "sku-1"}],
            "_sku_map": {"sku-1": "M365_E3"},
        }
    )

    assert unknown_user["extra"]["is_licensed"] == ""
    assert unknown_user["extra"]["license_count"] == ""
    assert unlicensed_user["extra"]["is_licensed"] == "false"
    assert unlicensed_user["extra"]["license_count"] == "0"
    assert licensed_user["extra"]["is_licensed"] == "true"
    assert licensed_user["extra"]["license_count"] == "1"


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


def test_quick_search_page_results_point_to_security_review_lanes(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))

    review_results = cache.quick_search("review")
    page_routes = {item["label"]: item["route"] for item in review_results if item["kind"] == "page"}

    assert page_routes["Identity Review"] == "/security/identity-review"
    assert page_routes["Privileged Access Review"] == "/security/access-review"
    assert page_routes["Break-glass Account Validation"] == "/security/break-glass-validation"
    assert page_routes["User Review"] == "/security/user-review"
    assert page_routes["Guest Access Review"] == "/security/guest-access-review"
    assert page_routes["DLP Findings Review"] == "/security/dlp-review"
    assert "Identity" not in page_routes
    assert "Users" not in page_routes

    account_health_results = cache.quick_search("account health")
    account_health_pages = {item["label"]: item["route"] for item in account_health_results if item["kind"] == "page"}
    assert account_health_pages["Account Health"] == "/security/account-health"

    guest_results = cache.quick_search("guest")
    guest_pages = {item["label"]: item["route"] for item in guest_results if item["kind"] == "page"}
    assert guest_pages["Guest Access Review"] == "/security/guest-access-review"

    dlp_results = cache.quick_search("dlp")
    dlp_pages = {item["label"]: item["route"] for item in dlp_results if item["kind"] == "page"}
    assert dlp_pages["DLP Findings Review"] == "/security/dlp-review"

    break_glass_results = cache.quick_search("break glass")
    break_glass_pages = {item["label"]: item["route"] for item in break_glass_results if item["kind"] == "page"}
    assert break_glass_pages["Break-glass Account Validation"] == "/security/break-glass-validation"

    directory_role_results = cache.quick_search("directory role")
    directory_role_pages = {item["label"]: item["route"] for item in directory_role_results if item["kind"] == "page"}
    assert directory_role_pages["Directory Role Membership Review"] == "/security/directory-role-review"


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


def test_build_virtual_machine_cost_export_excludes_other_vm_owned_resources_from_shared_candidates(
    tmp_path,
    monkeypatch,
):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    vm_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1"
    sibling_vm_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-2"
    os_disk_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/osdisk-1"
    sibling_disk_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/osdisk-2"
    sibling_extension_id = f"{sibling_vm_id}/extensions/monitoring"
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
                    "id": sibling_vm_id,
                    "name": "vm-2",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "parent_resource_id": "",
                    "managed_by": "",
                    "attached_vm_id": "",
                    "network_interface_ids": [],
                    "os_disk_id": sibling_disk_id,
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D2s_v5",
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
                    "id": sibling_disk_id,
                    "name": "osdisk-2",
                    "resource_type": "Microsoft.Compute/disks",
                    "parent_resource_id": "",
                    "managed_by": sibling_vm_id,
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
                    "id": sibling_extension_id,
                    "name": "monitoring",
                    "resource_type": "Microsoft.Compute/virtualMachines/extensions",
                    "parent_resource_id": sibling_vm_id,
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

    requested_ids: list[str] = []

    def fake_get_cost_by_resource_ids(
        subscription_id,
        resource_ids,
        lookback_days=None,
        chunk_size=20,
        cost_type="AmortizedCost",
        caller="default",
        max_attempts=3,
    ):
        requested_ids.extend(resource_ids)
        rows = []
        normalized = {resource_id.lower() for resource_id in resource_ids}
        if vm_id.lower() in normalized:
            rows.append({"label": vm_id, "amount": 50.0, "currency": "USD", "share": 0.5})
        if os_disk_id.lower() in normalized:
            rows.append({"label": os_disk_id, "amount": 10.0, "currency": "USD", "share": 0.1})
        if workspace_id.lower() in normalized:
            rows.append({"label": workspace_id, "amount": 25.0, "currency": "USD", "share": 0.25})
        return rows

    monkeypatch.setattr(cache._client, "get_cost_by_resource_ids", fake_get_cost_by_resource_ids)

    payload = cache.build_virtual_machine_cost_export(
        scope="filtered",
        filters={"search": "vm-1"},
        lookback_days=30,
    )

    normalized_requested_ids = {resource_id.lower() for resource_id in requested_ids}
    assert sibling_disk_id.lower() not in normalized_requested_ids
    assert sibling_extension_id.lower() not in normalized_requested_ids
    assert payload["summary_rows"][0]["shared_candidate_count"] == 1
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


def test_refresh_cost_uses_amortized_resource_level_breakdown(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    calls: list[tuple[str, str, int | None]] = []

    monkeypatch.setattr(
        cache._client,
        "list_subscriptions",
        lambda: [{"subscription_id": "sub-1", "display_name": "Prod"}],
    )
    monkeypatch.setattr(cache._client, "get_cost_trend", lambda subscriptions: [])

    def fake_breakdown(subscriptions, grouping_dimension, *, limit=20, cost_type="ActualCost", force_subscription_scope=False):
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


def test_build_virtual_machine_cost_export_continues_when_shared_candidates_time_out(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    vm_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1"
    os_disk_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/osdisk-1"
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

    def fake_fetch(
        resource_ids_by_subscription,
        *,
        lookback_days,
        progress_callback=None,
        phase_label="direct",
        deadline_monotonic=None,
    ):
        ids = resource_ids_by_subscription["sub-1"]
        if phase_label == "shared":
            raise TimeoutError("Azure Cost throttling prevented export completion within 45 minutes")
        return {
            cache._normalize_resource_id(vm_id): {"label": vm_id, "amount": 50.0, "currency": "USD", "share": 0.5},
            cache._normalize_resource_id(os_disk_id): {"label": os_disk_id, "amount": 10.0, "currency": "USD", "share": 0.1},
        }

    monkeypatch.setattr(cache, "_fetch_live_resource_cost_index", fake_fetch)

    payload = cache.build_virtual_machine_cost_export(scope="all", filters={}, lookback_days=30)

    assert payload["summary_rows"][0]["direct_total_cost"] == 60.0
    assert payload["summary_rows"][0]["shared_candidate_count"] == 0
    assert payload["summary_rows"][0]["shared_candidate_amount"] == 0.0
    assert payload["summary_rows"][0]["cost_status"] == "Direct costs complete; shared candidates unavailable"
    assert payload["shared_rows"] == []


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


def test_collect_avd_inventory_discovers_personal_host_pools_and_owner_history(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))

    monkeypatch.setattr(
        cache._client,
        "list_avd_host_pools",
        lambda subscription_ids: [
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/personal-hp",
                "name": "personal-hp",
                "subscription_id": "sub-1",
                "resource_group": "rg-avd",
                "location": "eastus",
                "host_pool_type": "Personal",
                "personal_desktop_assignment_type": "Direct",
                "friendly_name": "Personal Pool",
            },
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/pooled-hp",
                "name": "pooled-hp",
                "subscription_id": "sub-1",
                "resource_group": "rg-avd",
                "location": "eastus",
                "host_pool_type": "Pooled",
                "personal_desktop_assignment_type": "",
                "friendly_name": "Pooled Pool",
            },
        ],
    )
    monkeypatch.setattr(
        cache._client,
        "list_resource_diagnostic_settings",
        lambda resource_id: [
            {
                "id": f"{resource_id}/providers/Microsoft.Insights/diagnosticSettings/send-to-la",
                "name": "send-to-la",
                "workspace_id": "/subscriptions/sub-1/resourceGroups/rg-ops/providers/Microsoft.OperationalInsights/workspaces/la-prod",
                "logs": [{"category": "Connection", "category_group": "", "enabled": True}],
            }
        ]
        if resource_id.endswith("/personal-hp")
        else [],
    )
    monkeypatch.setattr(
        cache._client,
        "list_avd_session_hosts",
        lambda host_pool_id: [
            {
                "id": f"{host_pool_id}/sessionHosts/avd-vm-1.contoso.local",
                "name": "personal-hp/avd-vm-1.contoso.local",
                "session_host_name": "avd-vm-1.contoso.local",
                "subscription_id": "sub-1",
                "resource_group": "rg-avd",
                "location": "eastus",
                "host_pool_id": host_pool_id,
                "host_pool_name": "personal-hp",
                "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-1",
                "assigned_user": "",
                "assigned_user_principal": "",
                "status": "Available",
                "allow_new_session": True,
                "last_heartbeat_utc": "",
            }
        ],
    )
    monkeypatch.setattr(
        cache._client,
        "get_log_analytics_workspace",
        lambda workspace_resource_id: {
            "id": workspace_resource_id,
            "name": "la-prod",
            "subscription_id": "sub-1",
            "resource_group": "rg-ops",
            "location": "eastus",
            "customer_id": "workspace-guid",
        },
    )
    monkeypatch.setattr(
        cache._client,
        "query_log_analytics_workspace",
        lambda workspace_customer_id, query, *, timespan=None: [
            {
                "SessionHostAzureVmId": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-1",
                "UserName": "ada@example.com",
                "TimeGenerated": "2026-03-22T20:00:00+00:00",
            }
        ],
    )

    host_pools, session_hosts, owner_history = cache._collect_avd_inventory(["sub-1"])

    assert {item["name"] for item in host_pools} == {"personal-hp", "pooled-hp"}
    personal_pool = next(item for item in host_pools if item["name"] == "personal-hp")
    pooled_pool = next(item for item in host_pools if item["name"] == "pooled-hp")
    assert personal_pool["diagnostics_status"] == "available"
    assert personal_pool["owner_history_status"] == "available"
    assert pooled_pool["diagnostics_status"] == "missing_diagnostics"
    assert len(session_hosts) == 1
    assert session_hosts[0]["host_pool_type"] == "Personal"
    assert session_hosts[0]["vm_resource_id"] == "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-1"
    assert owner_history == [
        {
            "vm_resource_id": "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-1",
            "assigned_user": "ada@example.com",
            "observed_utc": "2026-03-22T20:00:00+00:00",
            "observed_local": AzureCache._format_local_datetime_text("2026-03-22T20:00:00+00:00"),
            "workspace_resource_id": "subscriptions/sub-1/resourcegroups/rg-ops/providers/microsoft.operationalinsights/workspaces/la-prod",
            "workspace_name": "la-prod",
        }
    ]


def test_list_virtual_desktop_removal_candidates_prefers_explicit_avd_assignment(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    now = datetime.now(timezone.utc)
    stale_power = (now - timedelta(days=21)).isoformat()
    stale_login = (now - timedelta(days=30)).isoformat()

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-1",
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
                }
            ],
            "users": [
                {
                    "id": "user-1",
                    "display_name": "Ada Lovelace",
                    "object_type": "user",
                    "principal_name": "ada@example.com",
                    "mail": "ada@example.com",
                    "enabled": False,
                    "app_id": "",
                    "extra": {
                        "is_licensed": "true",
                        "last_interactive_utc": stale_login,
                        "last_interactive_local": "stale interactive",
                        "last_successful_utc": stale_login,
                        "last_successful_local": "stale",
                        "on_prem_sam_account_name": "ada",
                    },
                },
                {
                    "id": "user-2",
                    "display_name": "Linus Example",
                    "object_type": "user",
                    "principal_name": "linus@example.com",
                    "mail": "linus@example.com",
                    "enabled": True,
                    "app_id": "",
                    "extra": {
                        "is_licensed": "true",
                        "last_interactive_utc": (now - timedelta(days=1)).isoformat(),
                        "last_interactive_local": "recent interactive",
                        "last_successful_utc": (now - timedelta(days=1)).isoformat(),
                        "last_successful_local": "recent",
                        "on_prem_sam_account_name": "linus",
                    },
                },
            ],
            "vm_run_observations": {
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-1": stale_power,
            },
            "avd_host_pools": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-1",
                    "name": "hostpool-1",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Direct",
                    "owner_history_status": "available",
                }
            ],
            "avd_session_hosts": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-1/sessionHosts/avd-vm-1.contoso.local",
                    "name": "hostpool-1/avd-vm-1.contoso.local",
                    "session_host_name": "avd-vm-1.contoso.local",
                    "host_pool_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-1",
                    "host_pool_name": "hostpool-1",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Direct",
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-1",
                    "assigned_user": "ada@example.com",
                }
            ],
            "avd_owner_history": [
                {
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-1",
                    "assigned_user": "linus@example.com",
                    "observed_utc": (now - timedelta(days=2)).isoformat(),
                    "observed_local": "recent",
                    "workspace_resource_id": "/subscriptions/sub-1/resourceGroups/rg-ops/providers/Microsoft.OperationalInsights/workspaces/la-prod",
                    "workspace_name": "la-prod",
                }
            ],
        }
    )

    payload = cache.list_virtual_desktop_removal_candidates()

    assert payload["summary"]["tracked_desktops"] == 1
    assert payload["summary"]["removal_candidates"] == 1
    assert payload["summary"]["explicit_avd_assignments"] == 1
    assert payload["summary"]["fallback_session_history_assignments"] == 0

    row = payload["desktops"][0]
    assert row["assigned_user_display_name"] == "Ada Lovelace"
    assert row["assigned_user_source"] == "avd_assigned"
    assert row["assigned_user_source_label"] == "AVD assigned user"
    assert row["assignment_source"] == "avd:assigned-user"
    assert row["host_pool_name"] == "hostpool-1"
    assert row["owner_history_status"] == "available"
    assert row["mark_for_removal"] is True
    assert "Assigned user is disabled" in row["removal_reasons"]
    assert any("No running signal" in reason for reason in row["removal_reasons"])


def test_list_virtual_desktop_removal_candidates_falls_back_to_last_avd_session_user(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    now = datetime.now(timezone.utc)
    recent_power = (now - timedelta(days=1)).isoformat()
    recent_login = (now - timedelta(days=1)).isoformat()
    observed_utc = (now - timedelta(hours=8)).isoformat()

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-2",
                    "name": "avd-vm-2",
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
                }
            ],
            "users": [
                {
                    "id": "user-2",
                    "display_name": "Linus Example",
                    "object_type": "user",
                    "principal_name": "linus@example.com",
                    "mail": "linus@example.com",
                    "enabled": True,
                    "app_id": "",
                    "extra": {
                        "is_licensed": "true",
                        "last_interactive_utc": recent_login,
                        "last_interactive_local": "recent interactive login",
                        "last_successful_utc": recent_login,
                        "last_successful_local": "recent login",
                        "on_prem_sam_account_name": "linus",
                    },
                }
            ],
            "vm_run_observations": {
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-2": recent_power,
            },
            "avd_host_pools": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-2",
                    "name": "hostpool-2",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Automatic",
                    "owner_history_status": "available",
                }
            ],
            "avd_session_hosts": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-2/sessionHosts/avd-vm-2.contoso.local",
                    "name": "hostpool-2/avd-vm-2.contoso.local",
                    "session_host_name": "avd-vm-2.contoso.local",
                    "host_pool_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-2",
                    "host_pool_name": "hostpool-2",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Automatic",
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-2",
                    "assigned_user": "",
                }
            ],
            "avd_owner_history": [
                {
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-2",
                    "assigned_user": "linus@example.com",
                    "observed_utc": observed_utc,
                    "observed_local": "2026-03-23 04:00 AM PDT",
                    "workspace_resource_id": "/subscriptions/sub-1/resourceGroups/rg-ops/providers/Microsoft.OperationalInsights/workspaces/la-prod",
                    "workspace_name": "la-prod",
                }
            ],
        }
    )

    payload = cache.list_virtual_desktop_removal_candidates()

    assert payload["summary"]["tracked_desktops"] == 1
    assert payload["summary"]["removal_candidates"] == 0
    assert payload["summary"]["explicit_avd_assignments"] == 0
    assert payload["summary"]["fallback_session_history_assignments"] == 1

    row = payload["desktops"][0]
    assert row["assigned_user_display_name"] == "Linus Example"
    assert row["assigned_user_source"] == "avd_last_session"
    assert row["assigned_user_source_label"] == "Last AVD session user"
    assert row["assigned_user_observed_utc"] == observed_utc
    assert row["assigned_user_observed_local"] == "2026-03-23 04:00 AM PDT"
    assert row["owner_history_status"] == "available"
    assert row["assignment_status"] == "resolved"
    assert row["mark_for_removal"] is False


def test_list_virtual_desktop_removal_candidates_uses_interactive_signin_only(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    now = datetime.now(timezone.utc)
    recent_power = (now - timedelta(days=1)).isoformat()
    stale_interactive = (now - timedelta(days=30)).isoformat()
    recent_successful = (now - timedelta(hours=6)).isoformat()

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-interactive-only",
                    "name": "avd-vm-interactive-only",
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
                }
            ],
            "users": [
                {
                    "id": "user-interactive-only",
                    "display_name": "Interactive Example",
                    "object_type": "user",
                    "principal_name": "interactive@example.com",
                    "mail": "interactive@example.com",
                    "enabled": True,
                    "app_id": "",
                    "extra": {
                        "is_licensed": "true",
                        "last_interactive_utc": stale_interactive,
                        "last_interactive_local": "stale interactive login",
                        "last_successful_utc": recent_successful,
                        "last_successful_local": "recent successful login",
                        "on_prem_sam_account_name": "interactive",
                    },
                }
            ],
            "vm_run_observations": {
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-interactive-only": recent_power,
            },
            "avd_host_pools": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-interactive",
                    "name": "hostpool-interactive",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Direct",
                    "owner_history_status": "available",
                }
            ],
            "avd_session_hosts": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-interactive/sessionHosts/avd-vm-interactive-only.contoso.local",
                    "name": "hostpool-interactive/avd-vm-interactive-only.contoso.local",
                    "session_host_name": "avd-vm-interactive-only.contoso.local",
                    "host_pool_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-interactive",
                    "host_pool_name": "hostpool-interactive",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Direct",
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-interactive-only",
                    "assigned_user": "interactive@example.com",
                }
            ],
            "avd_owner_history": [],
        }
    )

    payload = cache.list_virtual_desktop_removal_candidates()

    row = payload["desktops"][0]
    assert row["assigned_user_last_successful_utc"] == stale_interactive
    assert row["assigned_user_last_successful_local"] == "stale interactive login"
    assert row["user_signin_stale"] is True
    assert "Assigned user has no interactive Entra sign-in in 14+ days" in row["removal_reasons"]
    assert row["mark_for_removal"] is True


def test_list_virtual_desktop_removal_candidates_keeps_unknown_license_state_unknown(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    now = datetime.now(timezone.utc)
    recent_power = (now - timedelta(days=1)).isoformat()
    recent_login = (now - timedelta(hours=4)).isoformat()

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-unknown-license",
                    "name": "avd-vm-unknown-license",
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
                }
            ],
            "users": [
                {
                    "id": "user-unknown",
                    "display_name": "Pat Example",
                    "object_type": "user",
                    "principal_name": "pat@example.com",
                    "mail": "pat@example.com",
                    "enabled": True,
                    "app_id": "",
                    "extra": {
                        "is_licensed": "",
                        "last_interactive_utc": recent_login,
                        "last_interactive_local": "recent interactive login",
                        "last_successful_utc": recent_login,
                        "last_successful_local": "recent login",
                        "on_prem_sam_account_name": "pat",
                    },
                }
            ],
            "vm_run_observations": {
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-unknown-license": recent_power,
            },
            "avd_host_pools": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-unknown",
                    "name": "hostpool-unknown",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Direct",
                    "owner_history_status": "available",
                }
            ],
            "avd_session_hosts": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-unknown/sessionHosts/avd-vm-unknown-license.contoso.local",
                    "name": "hostpool-unknown/avd-vm-unknown-license.contoso.local",
                    "session_host_name": "avd-vm-unknown-license.contoso.local",
                    "host_pool_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-unknown",
                    "host_pool_name": "hostpool-unknown",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Direct",
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-unknown-license",
                    "assigned_user": "pat@example.com",
                }
            ],
            "avd_owner_history": [],
        }
    )

    payload = cache.list_virtual_desktop_removal_candidates()

    row = payload["desktops"][0]
    assert row["assigned_user_licensed"] is None
    assert "Assigned user is unlicensed" not in row["removal_reasons"]
    assert row["account_action"] == ""
    assert row["mark_for_removal"] is False


def test_list_virtual_desktop_removal_candidates_maps_owner_history_vm_instance_guid(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    now = datetime.now(timezone.utc)
    recent_power = (now - timedelta(days=1)).isoformat()
    recent_login = (now - timedelta(hours=4)).isoformat()
    observed_utc = (now - timedelta(hours=2)).isoformat()

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-guid",
                    "name": "avd-vm-guid",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-avd",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D4s_v5",
                    "vm_instance_id": "vm-guid-123",
                    "state": "PowerState/running",
                    "tags": {},
                }
            ],
            "users": [
                {
                    "id": "user-3",
                    "display_name": "Grace Hopper",
                    "object_type": "user",
                    "principal_name": "grace@example.com",
                    "mail": "grace@example.com",
                    "enabled": True,
                    "app_id": "",
                    "extra": {
                        "is_licensed": "true",
                        "last_interactive_utc": recent_login,
                        "last_interactive_local": "recent interactive login",
                        "last_successful_utc": recent_login,
                        "last_successful_local": "recent login",
                        "on_prem_sam_account_name": "grace",
                    },
                }
            ],
            "vm_run_observations": {
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-guid": recent_power,
            },
            "avd_host_pools": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-guid",
                    "name": "hostpool-guid",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Automatic",
                    "owner_history_status": "available",
                }
            ],
            "avd_session_hosts": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-guid/sessionHosts/avd-vm-guid.contoso.local",
                    "name": "hostpool-guid/avd-vm-guid.contoso.local",
                    "session_host_name": "avd-vm-guid.contoso.local",
                    "host_pool_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-guid",
                    "host_pool_name": "hostpool-guid",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Automatic",
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-guid",
                    "assigned_user": "",
                }
            ],
            "avd_owner_history": [
                {
                    "vm_resource_id": "vm-guid-123",
                    "assigned_user": "grace@example.com",
                    "observed_utc": observed_utc,
                    "observed_local": "2026-03-23 10:00 AM PDT",
                    "workspace_resource_id": "/subscriptions/sub-1/resourceGroups/rg-ops/providers/Microsoft.OperationalInsights/workspaces/la-prod",
                    "workspace_name": "la-prod",
                }
            ],
        }
    )

    payload = cache.list_virtual_desktop_removal_candidates()

    assert payload["summary"]["tracked_desktops"] == 1
    assert payload["summary"]["fallback_session_history_assignments"] == 1

    row = payload["desktops"][0]
    assert row["assigned_user_display_name"] == "Grace Hopper"
    assert row["assigned_user_principal_name"] == "grace@example.com"
    assert row["assigned_user_source"] == "avd_last_session"
    assert row["assigned_user_observed_utc"] == observed_utc
    assert row["owner_history_status"] == "available"


def test_list_virtual_desktop_removal_candidates_surfaces_missing_diagnostics_without_guessing_owner(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    recent_power = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-3",
                    "name": "avd-vm-3",
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
                }
            ],
            "users": [],
            "vm_run_observations": {
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-3": recent_power,
            },
            "avd_host_pools": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-3",
                    "name": "hostpool-3",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Automatic",
                    "owner_history_status": "missing_diagnostics",
                }
            ],
            "avd_session_hosts": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-3/sessionHosts/avd-vm-3.contoso.local",
                    "name": "hostpool-3/avd-vm-3.contoso.local",
                    "session_host_name": "avd-vm-3.contoso.local",
                    "host_pool_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-3",
                    "host_pool_name": "hostpool-3",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Automatic",
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-3",
                    "assigned_user": "",
                }
            ],
            "avd_owner_history": [],
        }
    )

    payload = cache.list_virtual_desktop_removal_candidates()

    assert payload["summary"]["tracked_desktops"] == 1
    assert payload["summary"]["owner_history_unavailable"] == 1

    row = payload["desktops"][0]
    assert row["assigned_user_display_name"] == "Unassigned"
    assert row["assigned_user_source"] == "unassigned"
    assert row["assignment_status"] == "missing"
    assert row["owner_history_status"] == "missing_diagnostics"
    assert row["mark_for_removal"] is False


def test_list_virtual_desktop_removal_candidates_surfaces_owner_history_query_failure(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    recent_power = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-4",
                    "name": "avd-vm-4",
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
                }
            ],
            "users": [],
            "vm_run_observations": {
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-4": recent_power,
            },
            "avd_host_pools": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-4",
                    "name": "hostpool-4",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Automatic",
                    "owner_history_status": "query_failed",
                }
            ],
            "avd_session_hosts": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-4/sessionHosts/avd-vm-4.contoso.local",
                    "name": "hostpool-4/avd-vm-4.contoso.local",
                    "session_host_name": "avd-vm-4.contoso.local",
                    "host_pool_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-4",
                    "host_pool_name": "hostpool-4",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Automatic",
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-4",
                    "assigned_user": "",
                }
            ],
            "avd_owner_history": [],
        }
    )

    payload = cache.list_virtual_desktop_removal_candidates()

    assert payload["summary"]["tracked_desktops"] == 1
    assert payload["summary"]["owner_history_unavailable"] == 1
    assert payload["desktops"][0]["owner_history_status"] == "query_failed"


def test_list_virtual_desktop_removal_candidates_excludes_pooled_host_pools(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    recent_power = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/pooled-vm-1",
                    "name": "pooled-vm-1",
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
                }
            ],
            "users": [],
            "vm_run_observations": {
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/pooled-vm-1": recent_power,
            },
            "avd_host_pools": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/pooled-hp",
                    "name": "pooled-hp",
                    "host_pool_type": "Pooled",
                    "personal_desktop_assignment_type": "",
                    "owner_history_status": "available",
                }
            ],
            "avd_session_hosts": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/pooled-hp/sessionHosts/pooled-vm-1.contoso.local",
                    "name": "pooled-hp/pooled-vm-1.contoso.local",
                    "session_host_name": "pooled-vm-1.contoso.local",
                    "host_pool_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/pooled-hp",
                    "host_pool_name": "pooled-hp",
                    "host_pool_type": "Pooled",
                    "personal_desktop_assignment_type": "",
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/pooled-vm-1",
                    "assigned_user": "someone@example.com",
                }
            ],
            "avd_owner_history": [],
        }
    )

    payload = cache.list_virtual_desktop_removal_candidates()

    assert payload["summary"]["tracked_desktops"] == 0
    assert payload["desktops"] == []


def test_fetch_virtual_desktop_utilization_applies_threshold_rules(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    sample_points = [
        "2026-03-20T00:00:00+00:00",
        "2026-03-20T01:00:00+00:00",
    ]

    def fake_metrics(resource_id, metric_names, *, start_time, end_time, interval):
        assert interval == "PT1M"
        metric_name = metric_names[0]
        if resource_id.endswith("avd-vm-under"):
            if metric_name == "Percentage CPU":
                return {
                    "Percentage CPU": [
                        {"timestamp": sample_points[0], "value": 42.0},
                        {"timestamp": sample_points[1], "value": 18.0},
                    ]
                }
            return {
                "Available Memory Percentage": [
                    {"timestamp": sample_points[0], "value": 70.0},
                    {"timestamp": sample_points[1], "value": 55.0},
                ]
            }
        if metric_name == "Percentage CPU":
            return {
                "Percentage CPU": [
                    {"timestamp": sample_points[0], "value": 100.0},
                    {"timestamp": sample_points[1], "value": 72.0},
                ]
            }
        return {
            "Available Memory Percentage": [
                {"timestamp": sample_points[0], "value": 0.0},
                {"timestamp": sample_points[1], "value": 25.0},
            ]
        }

    cache._client.list_resource_metrics = fake_metrics

    under = cache._fetch_virtual_desktop_utilization(
        "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-under"
    )
    over = cache._fetch_virtual_desktop_utilization(
        "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-over"
    )

    assert under["status"] == "under_utilized"
    assert under["under_utilized"] is True
    assert under["over_utilized"] is False
    assert under["cpu_max_percent"] == 42.0
    assert under["memory_max_percent"] == 45.0
    assert any("below the 50% under-utilization threshold" in reason for reason in under["reasoning"])

    assert over["status"] == "over_utilized"
    assert over["under_utilized"] is False
    assert over["over_utilized"] is True
    assert over["cpu_time_at_full_percent"] == 50.0
    assert over["memory_time_at_full_percent"] == 50.0
    assert any("CPU hit 100% utilization" in reason for reason in over["reasoning"])


def test_list_virtual_desktop_removal_candidates_filters_under_and_over_utilized(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    now = datetime.now(timezone.utc)
    recent_power = (now - timedelta(days=1)).isoformat()
    recent_login = (now - timedelta(days=1)).isoformat()

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-under",
                    "name": "avd-vm-under",
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
                },
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-over",
                    "name": "avd-vm-over",
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
                },
            ],
            "users": [
                {
                    "id": "user-1",
                    "display_name": "Ada Lovelace",
                    "object_type": "user",
                    "principal_name": "ada@example.com",
                    "mail": "ada@example.com",
                    "enabled": True,
                    "app_id": "",
                    "extra": {
                        "is_licensed": "true",
                        "last_interactive_utc": recent_login,
                        "last_interactive_local": "recent login",
                        "last_successful_utc": recent_login,
                        "last_successful_local": "recent login",
                    },
                }
            ],
            "vm_run_observations": {
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-under": recent_power,
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-over": recent_power,
            },
            "avd_host_pools": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-1",
                    "name": "hostpool-1",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Direct",
                    "owner_history_status": "available",
                }
            ],
            "avd_session_hosts": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-1/sessionHosts/avd-vm-under.contoso.local",
                    "name": "hostpool-1/avd-vm-under.contoso.local",
                    "session_host_name": "avd-vm-under.contoso.local",
                    "host_pool_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-1",
                    "host_pool_name": "hostpool-1",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Direct",
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-under",
                    "assigned_user": "ada@example.com",
                },
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-1/sessionHosts/avd-vm-over.contoso.local",
                    "name": "hostpool-1/avd-vm-over.contoso.local",
                    "session_host_name": "avd-vm-over.contoso.local",
                    "host_pool_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-1",
                    "host_pool_name": "hostpool-1",
                    "host_pool_type": "Personal",
                    "personal_desktop_assignment_type": "Direct",
                    "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-over",
                    "assigned_user": "ada@example.com",
                },
            ],
            "avd_owner_history": [],
            "avd_utilization_summaries": {
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-under": {
                    "status": "under_utilized",
                    "under_utilized": True,
                    "over_utilized": False,
                    "utilization_data_available": True,
                    "utilization_fully_evaluable": True,
                    "cpu_data_available": True,
                    "memory_data_available": True,
                    "cpu_max_percent": 38.0,
                    "cpu_time_at_full_percent": 0.0,
                    "memory_max_percent": 35.0,
                    "memory_time_at_full_percent": 0.0,
                    "reasoning": ["Peak CPU over the last 7 days was 38.0%, below the 50% under-utilization threshold."],
                    "error": "",
                },
                "subscriptions/sub-1/resourcegroups/rg-avd/providers/microsoft.compute/virtualmachines/avd-vm-over": {
                    "status": "over_utilized",
                    "under_utilized": False,
                    "over_utilized": True,
                    "utilization_data_available": True,
                    "utilization_fully_evaluable": True,
                    "cpu_data_available": True,
                    "memory_data_available": True,
                    "cpu_max_percent": 100.0,
                    "cpu_time_at_full_percent": 25.0,
                    "memory_max_percent": 92.0,
                    "memory_time_at_full_percent": 0.0,
                    "reasoning": ["CPU hit 100% utilization and stayed there for 25.0% of sampled time."],
                    "error": "",
                },
            },
        }
    )

    under_only = cache.list_virtual_desktop_removal_candidates(under_utilized_only=True)
    over_only = cache.list_virtual_desktop_removal_candidates(over_utilized_only=True)

    assert under_only["summary"]["under_utilized"] == 1
    assert under_only["summary"]["over_utilized"] == 1
    assert [item["name"] for item in under_only["desktops"]] == ["avd-vm-under"]
    assert [item["name"] for item in over_only["desktops"]] == ["avd-vm-over"]


def test_get_storage_summary_filters_tab_searches_server_side(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "sa-1",
                    "name": "acct-prod",
                    "resource_type": "Microsoft.Storage/storageAccounts",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "StorageV2",
                    "sku_name": "Standard_LRS",
                    "access_tier": "Hot",
                    "state": "Succeeded",
                    "tags": {},
                },
                {
                    "id": "disk-1",
                    "name": "disk-prod",
                    "resource_type": "Microsoft.Compute/disks",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "sku_name": "Premium_LRS",
                    "disk_state": "Unattached",
                    "managed_by": "",
                    "disk_size_gb": 128,
                    "tags": {},
                },
                {
                    "id": "snap-1",
                    "name": "snapshot-keep",
                    "resource_type": "Microsoft.Compute/snapshots",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "sku_name": "Standard_LRS",
                    "source_resource_id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/disk-prod",
                    "disk_size_gb": 64,
                    "tags": {},
                },
            ]
        }
    )

    payload = cache.get_storage_summary(
        account_search="acct",
        disk_search="disk-prod",
        snapshot_search="snapshot",
        disk_unattached_only=True,
    )

    assert [item["name"] for item in payload["storage_accounts"]] == ["acct-prod"]
    assert [item["name"] for item in payload["managed_disks"]] == ["disk-prod"]
    assert [item["name"] for item in payload["snapshots"]] == ["snapshot-keep"]


def test_get_compute_optimization_filters_idle_vm_search_server_side(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "vm-1",
                    "name": "vm-keep",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "vm_size": "Standard_D4s_v5",
                    "state": "PowerState/deallocated",
                    "tags": {},
                },
                {
                    "id": "vm-2",
                    "name": "vm-skip",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-dev",
                    "location": "westus",
                    "vm_size": "Standard_D2s_v5",
                    "state": "PowerState/stopped",
                    "tags": {},
                },
            ],
            "advisor": [],
            "reservation_status": {"available": False, "error": None},
        }
    )

    payload = cache.get_compute_optimization(idle_vm_search="rg-prod")

    assert [item["name"] for item in payload["idle_vms"]] == ["vm-keep"]
    assert payload["summary"]["idle_vms"] == 2


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


def test_inventory_refresh_preserves_previous_avd_snapshots_when_refresh_returns_empty(tmp_path, monkeypatch):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))

    previous_host_pools = [
        {
            "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-1",
            "name": "hostpool-1",
            "host_pool_type": "Personal",
            "personal_desktop_assignment_type": "Direct",
            "owner_history_status": "available",
        }
    ]
    previous_session_hosts = [
        {
            "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-1/sessionHosts/KHMUSRWVD-101.contoso.local",
            "name": "hostpool-1/KHMUSRWVD-101.contoso.local",
            "session_host_name": "KHMUSRWVD-101.contoso.local",
            "host_pool_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/hostpool-1",
            "host_pool_name": "hostpool-1",
            "host_pool_type": "Personal",
            "personal_desktop_assignment_type": "Direct",
            "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/KHMUSRWVD-101",
            "assigned_user": "billing19@example.com",
        }
    ]
    previous_owner_history = [
        {
            "vm_resource_id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/KHMUSRWVD-101",
            "assigned_user": "billing19@example.com",
            "observed_utc": "2026-03-23T17:00:00+00:00",
            "observed_local": "2026-03-23 10:00 AM PDT",
            "workspace_resource_id": "/subscriptions/sub-1/resourceGroups/rg-ops/providers/Microsoft.OperationalInsights/workspaces/la-prod",
            "workspace_name": "la-prod",
        }
    ]

    cache._update_snapshots(
        {
            "avd_host_pools": previous_host_pools,
            "avd_session_hosts": previous_session_hosts,
            "avd_owner_history": previous_owner_history,
        }
    )

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
                "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/KHMUSRWVD-101",
                "name": "KHMUSRWVD-101",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "subscription_id": "sub-1",
                "subscription_name": "",
                "resource_group": "rg-avd",
                "location": "eastus",
                "kind": "",
                "sku_name": "",
                "vm_size": "Standard_D4s_v5",
                "state": "PowerState/running",
                "tags": {},
            }
        ],
    )
    monkeypatch.setattr(cache._client, "list_role_assignments", lambda subscription_ids: [])
    monkeypatch.setattr(cache._client, "list_reservations", lambda: [])
    monkeypatch.setattr(cache, "_collect_avd_inventory", lambda subscription_ids: ([], [], []))

    cache._refresh_inventory()

    assert cache._snapshot("avd_host_pools") == previous_host_pools
    assert cache._snapshot("avd_session_hosts") == previous_session_hosts
    assert cache._snapshot("avd_owner_history") == previous_owner_history


def test_savings_opportunities_include_idle_vm_attached_cost(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    vm_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1"
    nic_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-1"
    disk_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/disk-1"
    pip_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/publicIPAddresses/pip-1"

    cache._update_snapshots(
        {
            "resources": [
                {
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
                    "state": "PowerState/deallocated",
                    "created_time": "",
                    "network_interface_ids": [nic_id],
                    "os_disk_id": disk_id,
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "managed_by": "",
                    "attached_vm_id": "",
                    "tags": {},
                },
                {
                    "id": nic_id,
                    "name": "nic-1",
                    "resource_type": "Microsoft.Network/networkInterfaces",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "",
                    "state": "Succeeded",
                    "created_time": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [pip_id],
                    "managed_by": "",
                    "attached_vm_id": vm_id,
                    "tags": {},
                },
                {
                    "id": disk_id,
                    "name": "disk-1",
                    "resource_type": "Microsoft.Compute/disks",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "Premium_LRS",
                    "vm_size": "",
                    "state": "Succeeded",
                    "created_time": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "managed_by": vm_id,
                    "attached_vm_id": "",
                    "disk_state": "Attached",
                    "tags": {},
                },
                {
                    "id": pip_id,
                    "name": "pip-1",
                    "resource_type": "Microsoft.Network/publicIPAddresses",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "Standard",
                    "vm_size": "",
                    "state": "Succeeded",
                    "created_time": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "managed_by": "",
                    "attached_vm_id": "",
                    "tags": {},
                },
            ],
            "cost_summary": {
                "lookback_days": 30,
                "total_cost": 0.0,
                "currency": "USD",
                "top_service": "",
                "top_subscription": "",
                "top_resource_group": "",
                "recommendation_count": 0,
                "potential_monthly_savings": 0.0,
            },
            "cost_by_resource_id_status": {"available": True, "error": None, "cost_basis": "amortized"},
            "cost_by_resource_id": [
                {"label": disk_id, "amount": 14.0, "currency": "USD"},
                {"label": pip_id, "amount": 6.0, "currency": "USD"},
            ],
            "advisor": [],
            "reservations": [],
            "reservation_status": {"available": False, "error": None},
        }
    )

    cache._rebuild_savings_snapshots()

    rows = cache.list_savings_opportunities(opportunity_type="idle_vm_attached_cost")

    assert len(rows) == 1
    assert rows[0]["resource_name"] == "vm-1"
    assert rows[0]["estimated_monthly_savings"] == 20.0
    assert rows[0]["quantified"] is True


def test_savings_opportunities_include_unattached_disks_stale_snapshots_and_public_ips(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    stale_created = (datetime.now(timezone.utc) - timedelta(days=75)).isoformat()
    disk_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/disk-2"
    snapshot_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/snapshots/snap-1"
    pip_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/publicIPAddresses/pip-2"

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": disk_id,
                    "name": "disk-2",
                    "resource_type": "Microsoft.Compute/disks",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "Premium_LRS",
                    "vm_size": "",
                    "state": "Succeeded",
                    "created_time": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "managed_by": "",
                    "attached_vm_id": "",
                    "disk_state": "Unattached",
                    "disk_size_gb": 128,
                    "tags": {},
                },
                {
                    "id": snapshot_id,
                    "name": "snap-1",
                    "resource_type": "Microsoft.Compute/snapshots",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "Standard_LRS",
                    "vm_size": "",
                    "state": "Succeeded",
                    "created_time": stale_created,
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "managed_by": "",
                    "attached_vm_id": "",
                    "source_resource_id": disk_id,
                    "tags": {},
                },
                {
                    "id": pip_id,
                    "name": "pip-2",
                    "resource_type": "Microsoft.Network/publicIPAddresses",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "Standard",
                    "vm_size": "",
                    "state": "Succeeded",
                    "created_time": "",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "managed_by": "",
                    "attached_vm_id": "",
                    "tags": {},
                },
            ],
            "cost_summary": {
                "lookback_days": 30,
                "total_cost": 0.0,
                "currency": "USD",
                "top_service": "",
                "top_subscription": "",
                "top_resource_group": "",
                "recommendation_count": 0,
                "potential_monthly_savings": 0.0,
            },
            "cost_by_resource_id_status": {"available": True, "error": None, "cost_basis": "amortized"},
            "cost_by_resource_id": [
                {"label": disk_id, "amount": 12.0, "currency": "USD"},
                {"label": snapshot_id, "amount": 3.5, "currency": "USD"},
                {"label": pip_id, "amount": 4.0, "currency": "USD"},
            ],
            "advisor": [],
            "reservations": [],
            "reservation_status": {"available": False, "error": None},
        }
    )

    cache._rebuild_savings_snapshots()

    types = [row["opportunity_type"] for row in cache.list_savings_opportunities()]

    assert "unattached_managed_disk" in types
    assert "stale_snapshot" in types
    assert "unattached_public_ip" in types


def test_savings_opportunities_include_reservation_gap_and_excess(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": "vm-gap-1",
                    "name": "vm-gap-1",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "",
                    "vm_size": "Standard_D4s_v5",
                    "state": "PowerState/running",
                    "created_time": "",
                    "tags": {},
                }
            ],
            "reservations": [
                {
                    "sku": "Standard_D4s_v5",
                    "location": "eastus",
                    "quantity": 0,
                    "display_name": "Prod gap",
                },
                {
                    "sku": "Standard_E4as_v4",
                    "location": "westus",
                    "quantity": 2,
                    "display_name": "West excess",
                },
            ],
            "reservation_status": {"available": True, "error": None},
            "cost_summary": {
                "lookback_days": 30,
                "total_cost": 0.0,
                "currency": "USD",
                "top_service": "",
                "top_subscription": "",
                "top_resource_group": "",
                "recommendation_count": 0,
                "potential_monthly_savings": 0.0,
            },
            "cost_by_resource_id_status": {"available": False, "error": None, "cost_basis": "amortized"},
            "cost_by_resource_id": [],
            "advisor": [],
        }
    )

    cache._rebuild_savings_snapshots()

    types = [row["opportunity_type"] for row in cache.list_savings_opportunities(category="commitment")]

    assert "reservation_coverage_gap" in types
    assert "reservation_excess" in types


def test_savings_opportunities_dedupe_duplicate_advisor_rows(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    vm_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-2"

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": vm_id,
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
                    "created_time": "",
                    "tags": {},
                }
            ],
            "cost_summary": {
                "lookback_days": 30,
                "total_cost": 0.0,
                "currency": "USD",
                "top_service": "",
                "top_subscription": "",
                "top_resource_group": "",
                "recommendation_count": 2,
                "potential_monthly_savings": 0.0,
            },
            "cost_by_resource_id_status": {"available": False, "error": None, "cost_basis": "amortized"},
            "cost_by_resource_id": [],
            "advisor": [
                {
                    "id": "advisor-1",
                    "category": "Cost",
                    "impact": "Medium",
                    "recommendation_type": "RightSizeVirtualMachine",
                    "title": "Right-size this VM",
                    "description": "VM appears overprovisioned.",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_id": vm_id,
                    "annual_savings": 120.0,
                    "monthly_savings": 10.0,
                    "currency": "USD",
                },
                {
                    "id": "advisor-2",
                    "category": "Cost",
                    "impact": "High",
                    "recommendation_type": "RightSizeVirtualMachine",
                    "title": "Right-size this VM",
                    "description": "Duplicate recommendation with higher savings.",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_id": vm_id,
                    "annual_savings": 180.0,
                    "monthly_savings": 15.0,
                    "currency": "USD",
                },
            ],
            "reservations": [],
            "reservation_status": {"available": False, "error": None},
        }
    )

    cache._rebuild_savings_snapshots()

    rows = cache.list_savings_opportunities(opportunity_type="advisor_compute_rightsize")

    assert len(rows) == 1
    assert rows[0]["estimated_monthly_savings"] == 15.0


def test_savings_summary_excludes_unquantified_commitment_items_from_totals(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    disk_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/disk-3"

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": disk_id,
                    "name": "disk-3",
                    "resource_type": "Microsoft.Compute/disks",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "StandardSSD_LRS",
                    "vm_size": "",
                    "state": "Succeeded",
                    "created_time": "",
                    "managed_by": "",
                    "attached_vm_id": "",
                    "disk_state": "Unattached",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "tags": {},
                }
            ],
            "reservations": [
                {
                    "sku": "Standard_D4s_v5",
                    "location": "eastus",
                    "quantity": 2,
                    "display_name": "Prod excess",
                }
            ],
            "reservation_status": {"available": True, "error": None},
            "cost_summary": {
                "lookback_days": 30,
                "total_cost": 0.0,
                "currency": "USD",
                "top_service": "",
                "top_subscription": "",
                "top_resource_group": "",
                "recommendation_count": 0,
                "potential_monthly_savings": 0.0,
            },
            "cost_by_resource_id_status": {"available": True, "error": None, "cost_basis": "amortized"},
            "cost_by_resource_id": [{"label": disk_id, "amount": 11.5, "currency": "USD"}],
            "advisor": [],
        }
    )

    cache._rebuild_savings_snapshots()

    summary = cache.get_savings_summary()

    assert summary["quantified_monthly_savings"] == 11.5
    assert summary["unquantified_opportunity_count"] == 1


def test_savings_monthly_proxy_normalizes_non_30_day_lookback(tmp_path):
    cache = AzureCache(db_path=str(tmp_path / "azure_cache.db"))
    disk_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/disk-4"

    cache._update_snapshots(
        {
            "resources": [
                {
                    "id": disk_id,
                    "name": "disk-4",
                    "resource_type": "Microsoft.Compute/disks",
                    "subscription_id": "sub-1",
                    "subscription_name": "Prod",
                    "resource_group": "rg-prod",
                    "location": "eastus",
                    "kind": "",
                    "sku_name": "StandardSSD_LRS",
                    "vm_size": "",
                    "state": "Succeeded",
                    "created_time": "",
                    "managed_by": "",
                    "attached_vm_id": "",
                    "disk_state": "Unattached",
                    "network_interface_ids": [],
                    "os_disk_id": "",
                    "data_disk_ids": [],
                    "public_ip_ids": [],
                    "tags": {},
                }
            ],
            "cost_summary": {
                "lookback_days": 7,
                "total_cost": 0.0,
                "currency": "USD",
                "top_service": "",
                "top_subscription": "",
                "top_resource_group": "",
                "recommendation_count": 0,
                "potential_monthly_savings": 0.0,
            },
            "cost_by_resource_id_status": {"available": True, "error": None, "cost_basis": "amortized"},
            "cost_by_resource_id": [{"label": disk_id, "amount": 7.0, "currency": "USD"}],
            "advisor": [],
            "reservations": [],
            "reservation_status": {"available": False, "error": None},
        }
    )

    cache._rebuild_savings_snapshots()

    rows = cache.list_savings_opportunities(opportunity_type="unattached_managed_disk")

    assert len(rows) == 1
    assert rows[0]["estimated_monthly_savings"] == 30.0
