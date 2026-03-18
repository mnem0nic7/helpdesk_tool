from __future__ import annotations

from azure_cache import AzureCache
from azure_client import AzureApiError, AzureClient


def test_list_directory_roles_omits_custom_page_size(monkeypatch):
    client = AzureClient()
    captured: dict[str, object] = {}

    def fake_paged_get(url, *, scope, params=None, headers=None):
        captured["url"] = url
        captured["scope"] = scope
        captured["params"] = params
        captured["headers"] = headers
        return []

    monkeypatch.setattr(client, "_paged_get", fake_paged_get)

    client.list_directory_roles()

    assert captured["url"] == "https://graph.microsoft.com/v1.0/directoryRoles"
    assert captured["params"] == {"$select": "id,displayName,description"}


def test_query_resources_captures_vm_size_and_sku(monkeypatch):
    client = AzureClient()

    monkeypatch.setattr(
        client,
        "_request",
        lambda method, url, *, scope, params=None, json_body=None, headers=None: {
            "data": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
                    "name": "vm-1",
                    "type": "Microsoft.Compute/virtualMachines",
                    "kind": "",
                    "location": "eastus",
                    "subscriptionId": "sub-1",
                    "resourceGroup": "rg-prod",
                    "skuName": "Standard_D4s_v5",
                    "vmSize": "Standard_D4s_v5",
                    "powerState": "PowerState/running",
                    "tags": {"env": "prod"},
                }
            ]
        },
    )

    rows = client.query_resources(["sub-1"])

    assert rows == [
        {
            "id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
            "name": "vm-1",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "parent_resource_id": "",
            "managed_by": "",
            "attached_vm_id": "",
            "network_interface_ids": [],
            "os_disk_id": "",
            "data_disk_ids": [],
            "public_ip_ids": [],
            "kind": "",
            "location": "eastus",
            "subscription_id": "sub-1",
            "resource_group": "rg-prod",
            "sku_name": "Standard_D4s_v5",
            "vm_size": "Standard_D4s_v5",
            "state": "PowerState/running",
            "tags": {"env": "prod"},
        }
    ]


def test_query_resources_extracts_vm_relationship_fields(monkeypatch):
    client = AzureClient()

    monkeypatch.setattr(
        client,
        "_request",
        lambda method, url, *, scope, params=None, json_body=None, headers=None: {
            "data": [
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
                    "name": "vm-1",
                    "type": "Microsoft.Compute/virtualMachines",
                    "kind": "",
                    "location": "eastus",
                    "subscriptionId": "sub-1",
                    "resourceGroup": "rg-prod",
                    "managedBy": "",
                    "virtualMachineId": "",
                    "networkInterfaces": [{"id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-1"}],
                    "osDiskId": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/osdisk-1",
                    "dataDisks": [{"managedDisk": {"id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/datadisk-1"}}],
                    "ipConfigurations": [],
                    "skuName": "Standard_D4s_v5",
                    "vmSize": "Standard_D4s_v5",
                    "powerState": "PowerState/running",
                    "tags": {"env": "prod"},
                },
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-1",
                    "name": "nic-1",
                    "type": "Microsoft.Network/networkInterfaces",
                    "kind": "",
                    "location": "eastus",
                    "subscriptionId": "sub-1",
                    "resourceGroup": "rg-prod",
                    "managedBy": "",
                    "virtualMachineId": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
                    "networkInterfaces": [],
                    "osDiskId": "",
                    "dataDisks": [],
                    "ipConfigurations": [
                        {
                            "properties": {
                                "publicIPAddress": {
                                    "id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/publicIPAddresses/pip-1"
                                }
                            }
                        }
                    ],
                    "skuName": "",
                    "vmSize": "",
                    "powerState": "",
                    "tags": {},
                },
                {
                    "id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/osdisk-1",
                    "name": "osdisk-1",
                    "type": "Microsoft.Compute/disks",
                    "kind": "",
                    "location": "eastus",
                    "subscriptionId": "sub-1",
                    "resourceGroup": "rg-prod",
                    "managedBy": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
                    "virtualMachineId": "",
                    "networkInterfaces": [],
                    "osDiskId": "",
                    "dataDisks": [],
                    "ipConfigurations": [],
                    "skuName": "Premium_LRS",
                    "vmSize": "",
                    "powerState": "",
                    "tags": {},
                },
            ]
        },
    )

    rows = client.query_resources(["sub-1"])

    assert rows[0]["network_interface_ids"] == [
        "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-1"
    ]
    assert rows[0]["os_disk_id"] == "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/osdisk-1"
    assert rows[0]["data_disk_ids"] == [
        "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/datadisk-1"
    ]
    assert rows[1]["attached_vm_id"] == "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1"
    assert rows[1]["public_ip_ids"] == [
        "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/publicIPAddresses/pip-1"
    ]
    assert rows[2]["managed_by"] == "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1"


def test_list_reservations_normalizes_active_vm_reservations(monkeypatch):
    client = AzureClient()

    monkeypatch.setattr(
        client,
        "_paged_get",
        lambda url, *, scope, params=None, headers=None: [
            {
                "id": "/providers/Microsoft.Capacity/reservationOrders/order-1/reservations/res-1",
                "name": "res-1",
                "location": "eastus",
                "sku": {"name": "Standard_E4as_v4"},
                "properties": {
                    "displayName": "Prod E4 RI",
                    "quantity": 12,
                    "reservedResourceType": "VirtualMachines",
                    "appliedScopeType": "Shared",
                    "displayProvisioningState": "Succeeded",
                    "provisioningState": "Succeeded",
                    "term": "P1Y",
                    "expiryDateTime": "2027-03-17T00:00:00Z",
                    "renew": True,
                    "reservedResourceProperties": {
                        "instanceFlexibility": "On",
                    },
                },
            },
            {
                "id": "/providers/Microsoft.Capacity/reservationOrders/order-1/reservations/res-2",
                "name": "res-2",
                "sku": {"name": "Standard_D4s_v5"},
                "properties": {
                    "quantity": 3,
                    "reservedResourceType": "SqlDatabases",
                    "provisioningState": "Succeeded",
                },
            },
        ],
    )

    rows = client.list_reservations()

    assert rows == [
        {
            "id": "/providers/Microsoft.Capacity/reservationOrders/order-1/reservations/res-1",
            "name": "res-1",
            "display_name": "Prod E4 RI",
            "sku": "Standard_E4as_v4",
            "quantity": 12,
            "location": "eastus",
            "reserved_resource_type": "VirtualMachines",
            "applied_scope_type": "Shared",
            "display_provisioning_state": "Succeeded",
            "provisioning_state": "Succeeded",
            "term": "P1Y",
            "renew": True,
            "expiry_date_time": "2027-03-17T00:00:00+00:00",
            "instance_flexibility": "On",
            "applied_scopes": [],
        }
    ]


def test_get_cost_by_resource_ids_uses_resourceid_filter(monkeypatch):
    client = AzureClient()
    captured_calls: list[dict[str, object]] = []

    def fake_request(method, url, *, scope, params=None, json_body=None, headers=None):
        captured_calls.append(
            {
                "method": method,
                "url": url,
                "scope": scope,
                "params": params,
                "json_body": json_body,
            }
        )
        return {
            "properties": {
                "columns": [
                    {"name": "PreTaxCost"},
                    {"name": "ResourceId"},
                ],
                "rows": [
                    [12.5, "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1"],
                    [3.75, "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-1"],
                ],
            }
        }

    monkeypatch.setattr(client, "_request", fake_request)

    rows = client.get_cost_by_resource_ids(
        "sub-1",
        [
            "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
            "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-1",
        ],
    )

    assert captured_calls[0]["method"] == "POST"
    assert captured_calls[0]["url"] == (
        "https://management.azure.com/subscriptions/sub-1/providers/Microsoft.CostManagement/query"
    )
    payload = captured_calls[0]["json_body"]
    assert payload["type"] == "ActualCost"
    assert payload["timeframe"] == "Custom"
    assert payload["dataset"]["granularity"] == "None"
    assert payload["dataset"]["grouping"] == [{"type": "Dimension", "name": "ResourceId"}]
    assert payload["dataset"]["filter"] == {
        "dimensions": {
            "name": "ResourceId",
            "operator": "In",
            "values": [
                "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
                "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-1",
            ],
        }
    }
    assert payload["timePeriod"]["from"]
    assert payload["timePeriod"]["to"]
    assert rows == [
        {
            "label": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
            "amount": 12.5,
            "currency": "USD",
            "share": 0.7692,
        },
        {
            "label": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/networkInterfaces/nic-1",
            "amount": 3.75,
            "currency": "USD",
            "share": 0.2308,
        },
    ]


def test_inventory_refresh_continues_when_management_groups_are_unauthorized(tmp_path, monkeypatch):
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
    monkeypatch.setattr(
        cache._client,
        "list_management_groups",
        lambda: (_ for _ in ()).throw(
            AzureApiError("GET https://management.azure.com/... failed (403): AuthorizationFailed managementGroups/read")
        ),
    )
    monkeypatch.setattr(
        cache._client,
        "query_resources",
        lambda subscription_ids: [
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
                "name": "vm-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "kind": "",
                "location": "eastus",
                "subscription_id": "sub-1",
                "resource_group": "rg-prod",
                "state": "running",
                "tags": {},
            }
        ],
    )
    monkeypatch.setattr(
        cache._client,
        "list_role_assignments",
        lambda subscription_ids: [],
    )

    cache._refresh_inventory()

    status = cache.status()
    inventory = next(dataset for dataset in status["datasets"] if dataset["key"] == "inventory")

    assert inventory["error"] is None
    assert inventory["item_count"] == 2
    assert inventory["last_refresh"] is not None
    assert cache._snapshot("management_groups") == []
    assert cache._snapshot("resources")[0]["subscription_name"] == "Prod"
