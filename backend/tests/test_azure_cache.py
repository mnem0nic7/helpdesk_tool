from __future__ import annotations

from azure_cache import AzureCache


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
