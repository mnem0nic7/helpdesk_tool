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
            "cost_by_resource_id_status": {"available": True, "error": None},
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
    nic_id = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-1"

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
            },
            "cost_by_resource_id": [],
        }
    )

    monkeypatch.setattr(
        cache._client,
        "get_cost_by_resource_ids",
        lambda subscription_id, resource_ids, lookback_days=None, chunk_size=20: [
            {"label": vm_id, "amount": 82.5, "currency": "USD", "share": 0.9621},
            {"label": nic_id, "amount": 3.25, "currency": "USD", "share": 0.0379},
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

    assert payload["by_size"] == [
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
