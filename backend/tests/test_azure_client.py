from __future__ import annotations

import threading
import time

from azure_cache import AzureCache
from azure_client import AzureApiError, AzureClient, AzureCostQueryCoordinator


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


def test_list_applications_requests_credential_and_publisher_fields(monkeypatch):
    client = AzureClient()
    captured: dict[str, object] = {}

    def fake_paged_get(url, *, scope, params=None, headers=None):
        captured["url"] = url
        captured["params"] = params
        return []

    monkeypatch.setattr(client, "_paged_get", fake_paged_get)

    client.list_applications()

    assert captured["url"] == "https://graph.microsoft.com/v1.0/applications"
    assert captured["params"] == {
        "$select": "id,appId,displayName,signInAudience,createdDateTime,publisherDomain,notes,passwordCredentials,keyCredentials,verifiedPublisher",
        "$top": "999",
    }


def test_list_application_owners_uses_graph_batch_and_tracks_errors(monkeypatch):
    client = AzureClient()
    captured: dict[str, object] = {}

    def fake_batch_request(requests_payload):
        captured["requests_payload"] = requests_payload
        return {
            "responses": [
                {
                    "id": "1",
                    "status": 200,
                    "body": {
                        "value": [
                            {
                                "id": "user-1",
                                "displayName": "Ada Lovelace",
                                "userPrincipalName": "ada@example.com",
                            }
                        ]
                    },
                },
                {
                    "id": "2",
                    "status": 403,
                    "body": {"error": {"message": "Access denied"}},
                },
            ]
        }

    monkeypatch.setattr(client, "graph_batch_request", fake_batch_request)

    result = client.list_application_owners(["app-1", "app-2"])

    assert captured["requests_payload"] == [
        {
            "id": "1",
            "method": "GET",
            "url": "/applications/app-1/owners?$select=id,displayName,userPrincipalName,mail,appId&$top=50",
        },
        {
            "id": "2",
            "method": "GET",
            "url": "/applications/app-2/owners?$select=id,displayName,userPrincipalName,mail,appId&$top=50",
        },
    ]
    assert result["app-1"]["owners"][0]["displayName"] == "Ada Lovelace"
    assert result["app-2"]["owner_lookup_error"] == "Access denied"


def test_list_directory_role_members_uses_graph_batch_and_tracks_errors(monkeypatch):
    client = AzureClient()
    captured: dict[str, object] = {}

    def fake_batch_request(requests_payload):
        captured["requests_payload"] = requests_payload
        return {
            "responses": [
                {
                    "id": "1",
                    "status": 200,
                    "body": {
                        "value": [
                            {
                                "id": "user-1",
                                "displayName": "Ada Lovelace",
                                "userPrincipalName": "ada@example.com",
                                "@odata.type": "#microsoft.graph.user",
                            }
                        ],
                        "@odata.nextLink": "https://graph.microsoft.com/v1.0/$batch/next",
                    },
                },
                {
                    "id": "2",
                    "status": 403,
                    "body": {"error": {"message": "Access denied"}},
                },
            ]
        }

    monkeypatch.setattr(client, "graph_batch_request", fake_batch_request)

    result = client.list_directory_role_members(["role-1", "role-2"])

    assert captured["requests_payload"] == [
        {
            "id": "1",
            "method": "GET",
            "url": "/directoryRoles/role-1/members?$select=id,displayName,description,mail,userPrincipalName,appId,accountEnabled,securityEnabled,userType&$top=100",
        },
        {
            "id": "2",
            "method": "GET",
            "url": "/directoryRoles/role-2/members?$select=id,displayName,description,mail,userPrincipalName,appId,accountEnabled,securityEnabled,userType&$top=100",
        },
    ]
    assert result["role-1"]["members"][0]["displayName"] == "Ada Lovelace"
    assert result["role-1"]["truncated"] is True
    assert result["role-2"]["member_lookup_error"] == "Access denied"


def test_list_managed_devices_batches_primary_user_lookup(monkeypatch):
    client = AzureClient()
    captured: dict[str, object] = {}

    def fake_graph_paged_get(path, *, api_version="v1.0", params=None, headers=None):
        captured["path"] = path
        captured["api_version"] = api_version
        captured["params"] = params
        del headers
        return [
            {
                "id": "device-1",
                "deviceName": "Payroll Laptop",
                "operatingSystem": "Windows",
                "osVersion": "11",
                "complianceState": "noncompliant",
                "managementState": "managed",
                "ownerType": "company",
                "enrollmentType": "windowsAzureADJoin",
                "lastSyncDateTime": "2026-04-03T12:00:00Z",
                "azureADDeviceId": "aad-1",
            }
        ]

    def fake_graph_request(method, path, *, api_version="v1.0", params=None, json_body=None, headers=None):
        captured["batch_method"] = method
        captured["batch_path"] = path
        captured["batch_version"] = api_version
        captured["batch_body"] = json_body
        del params, headers
        return {
            "responses": [
                {
                    "id": "1",
                    "status": 200,
                    "body": {
                        "value": [
                            {
                                "id": "user-1",
                                "displayName": "Ada Lovelace",
                                "userPrincipalName": "ada@example.com",
                                "mail": "ada@example.com",
                            }
                        ]
                    },
                }
            ]
        }

    monkeypatch.setattr(client, "graph_paged_get", fake_graph_paged_get)
    monkeypatch.setattr(client, "graph_request", fake_graph_request)

    rows = client.list_managed_devices()

    assert captured["path"] == "deviceManagement/managedDevices"
    assert captured["batch_method"] == "POST"
    assert captured["batch_path"] == "$batch"
    assert captured["batch_version"] == "beta"
    assert rows[0]["primary_users"][0]["display_name"] == "Ada Lovelace"
    assert rows[0]["primary_users"][0]["principal_name"] == "ada@example.com"


def test_list_conditional_access_policies_normalizes_scope_and_controls(monkeypatch):
    client = AzureClient()
    captured: dict[str, object] = {}

    def fake_graph_paged_get(path, *, api_version="v1.0", params=None, headers=None):
        captured["path"] = path
        captured["api_version"] = api_version
        captured["params"] = params
        del headers
        return [
            {
                "id": "policy-1",
                "displayName": "Require MFA for admins",
                "createdDateTime": "2026-01-01T00:00:00Z",
                "modifiedDateTime": "2026-04-03T01:00:00Z",
                "state": "enabled",
                "conditions": {
                    "users": {
                        "includeUsers": [],
                        "excludeUsers": ["user-1"],
                        "includeGroups": [],
                        "excludeGroups": [],
                        "includeRoles": ["role-1", "role-2"],
                        "excludeRoles": [],
                        "includeGuestsOrExternalUsers": None,
                        "excludeGuestsOrExternalUsers": None,
                    },
                    "applications": {
                        "includeApplications": ["All"],
                        "excludeApplications": [],
                        "includeUserActions": [],
                    },
                },
                "grantControls": {
                    "builtInControls": ["mfa"],
                    "customAuthenticationFactors": [],
                    "termsOfUse": [],
                    "authenticationStrength": {"displayName": "Phishing-resistant MFA"},
                },
                "sessionControls": {"applicationEnforcedRestrictions": {"isEnabled": True}},
            }
        ]

    monkeypatch.setattr(client, "graph_paged_get", fake_graph_paged_get)

    rows = client.list_conditional_access_policies()

    assert captured["path"] == "identity/conditionalAccess/policies"
    assert rows[0]["display_name"] == "Require MFA for admins"
    assert rows[0]["include_roles"] == ["role-1", "role-2"]
    assert rows[0]["exclude_users"] == ["user-1"]
    assert rows[0]["grant_controls"] == ["mfa"]
    assert rows[0]["authentication_strength"] == "Phishing-resistant MFA"
    assert rows[0]["session_controls"] == ["applicationEnforcedRestrictions"]


def test_list_conditional_access_audit_events_filters_and_normalizes(monkeypatch):
    client = AzureClient()
    captured: dict[str, object] = {}

    def fake_graph_paged_get(path, *, api_version="v1.0", params=None, headers=None):
        captured["path"] = path
        captured["api_version"] = api_version
        captured["params"] = params
        del headers
        return [
            {
                "id": "event-1",
                "activityDateTime": "2026-04-03T02:15:00Z",
                "activityDisplayName": "Update conditional access policy",
                "category": "Policy",
                "loggedByService": "Conditional Access",
                "result": "success",
                "initiatedBy": {
                    "user": {
                        "displayName": "Ada Lovelace",
                        "userPrincipalName": "ada@example.com",
                    }
                },
                "targetResources": [
                    {
                        "id": "policy-1",
                        "displayName": "Require MFA for admins",
                        "type": "Policy",
                        "modifiedProperties": [{"displayName": "grantControls"}],
                    }
                ],
            },
            {
                "id": "event-2",
                "activityDateTime": "2026-04-03T01:15:00Z",
                "activityDisplayName": "Update application",
                "category": "ApplicationManagement",
                "loggedByService": "Microsoft Entra ID",
                "result": "success",
                "initiatedBy": {},
                "targetResources": [],
            },
        ]

    monkeypatch.setattr(client, "graph_paged_get", fake_graph_paged_get)

    rows = client.list_conditional_access_audit_events(lookback_days=14)

    assert captured["path"] == "auditLogs/directoryAudits"
    assert "activityDateTime ge" in str((captured["params"] or {}).get("$filter"))
    assert len(rows) == 1
    assert rows[0]["target_policy_name"] == "Require MFA for admins"
    assert rows[0]["initiated_by_display_name"] == "Ada Lovelace"
    assert rows[0]["modified_properties"] == ["grantControls"]


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
                    "vmInstanceId": "vm-guid-1",
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
            "vm_instance_id": "vm-guid-1",
            "state": "PowerState/running",
            "created_time": "",
            "tags": {"env": "prod"},
            "disk_size_gb": None,
            "disk_state": "",
            "access_tier": "",
            "source_resource_id": "",
            "disk_iops": None,
            "avd_assigned_user": "",
            "avd_resource_id": "",
            "avd_user_principal": "",
            "avd_create_time": "",
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


def test_list_avd_host_pools_normalizes_personal_assignment_fields(monkeypatch):
    client = AzureClient()

    monkeypatch.setattr(
        client,
        "_paged_get",
        lambda url, *, scope, params=None, headers=None: [
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/personal-hp",
                "name": "personal-hp",
                "location": "eastus",
                "properties": {
                    "hostPoolType": "Personal",
                    "personalDesktopAssignmentType": "Direct",
                    "friendlyName": "Personal Pool",
                },
            }
        ],
    )

    rows = client.list_avd_host_pools(["sub-1"])

    assert rows == [
        {
            "id": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/personal-hp",
            "name": "personal-hp",
            "subscription_id": "sub-1",
            "resource_group": "rg-avd",
            "location": "eastus",
            "host_pool_type": "Personal",
            "personal_desktop_assignment_type": "Direct",
            "friendly_name": "Personal Pool",
        }
    ]


def test_list_resource_diagnostic_settings_normalizes_workspace_logs(monkeypatch):
    client = AzureClient()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        client,
        "_paged_get",
        lambda url, *, scope, params=None, headers=None: captured.update(
            {"url": url, "scope": scope, "params": params}
        )
        or [
            {
                "id": "diag-1",
                "name": "send-to-la",
                "properties": {
                    "workspaceId": "/subscriptions/sub-1/resourceGroups/rg-ops/providers/Microsoft.OperationalInsights/workspaces/la-prod",
                    "logs": [
                        {"category": "Connection", "enabled": True},
                        {"categoryGroup": "allLogs", "enabled": False},
                    ],
                },
            }
        ],
    )

    rows = client.list_resource_diagnostic_settings(
        "subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/personal-hp"
    )

    assert (
        captured["url"]
        == "https://management.azure.com/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.DesktopVirtualization/hostPools/personal-hp/providers/Microsoft.Insights/diagnosticSettings"
    )
    assert rows == [
        {
            "id": "diag-1",
            "name": "send-to-la",
            "workspace_id": "/subscriptions/sub-1/resourceGroups/rg-ops/providers/Microsoft.OperationalInsights/workspaces/la-prod",
            "logs": [
                {"category": "Connection", "category_group": "", "enabled": True},
                {"category": "", "category_group": "allLogs", "enabled": False},
            ],
        }
    ]


def test_get_log_analytics_workspace_accepts_normalized_resource_id(monkeypatch):
    client = AzureClient()
    captured: dict[str, object] = {}

    def fake_request(method, url, *, scope, params=None, json_body=None, headers=None):
        captured["method"] = method
        captured["url"] = url
        captured["scope"] = scope
        captured["params"] = params
        return {
            "id": "/subscriptions/sub-1/resourceGroups/rg-ops/providers/Microsoft.OperationalInsights/workspaces/la-prod",
            "name": "la-prod",
            "location": "eastus",
            "properties": {"customerId": "workspace-guid"},
        }

    monkeypatch.setattr(client, "_request", fake_request)

    row = client.get_log_analytics_workspace(
        "subscriptions/sub-1/resourceGroups/rg-ops/providers/Microsoft.OperationalInsights/workspaces/la-prod"
    )

    assert captured["method"] == "GET"
    assert (
        captured["url"]
        == "https://management.azure.com/subscriptions/sub-1/resourceGroups/rg-ops/providers/Microsoft.OperationalInsights/workspaces/la-prod"
    )
    assert captured["scope"] == "https://management.azure.com/.default"
    assert captured["params"] == {"api-version": "2023-09-01"}
    assert row == {
        "id": "/subscriptions/sub-1/resourceGroups/rg-ops/providers/Microsoft.OperationalInsights/workspaces/la-prod",
        "name": "la-prod",
        "subscription_id": "sub-1",
        "resource_group": "rg-ops",
        "location": "eastus",
        "customer_id": "workspace-guid",
    }


def test_query_log_analytics_workspace_returns_table_rows(monkeypatch):
    client = AzureClient()
    captured: dict[str, object] = {}

    def fake_request(method, url, *, scope, params=None, json_body=None, headers=None):
        captured["method"] = method
        captured["url"] = url
        captured["scope"] = scope
        captured["json_body"] = json_body
        return {
            "tables": [
                {
                    "name": "PrimaryResult",
                    "columns": [
                        {"name": "SessionHostAzureVmId", "type": "string"},
                        {"name": "UserName", "type": "string"},
                        {"name": "TimeGenerated", "type": "datetime"},
                    ],
                    "rows": [
                        [
                            "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-1",
                            "ada@example.com",
                            "2026-03-22T18:30:00Z",
                        ]
                    ],
                }
            ]
        }

    monkeypatch.setattr(client, "_request", fake_request)

    rows = client.query_log_analytics_workspace(
        "workspace-customer-id",
        "WVDConnections | take 1",
        timespan="P14D",
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.loganalytics.azure.com/v1/workspaces/workspace-customer-id/query"
    assert captured["scope"] == "https://api.loganalytics.io/.default"
    assert captured["json_body"] == {"query": "WVDConnections | take 1", "timespan": "P14D"}
    assert rows == [
        {
            "SessionHostAzureVmId": "/subscriptions/sub-1/resourceGroups/rg-avd/providers/Microsoft.Compute/virtualMachines/avd-vm-1",
            "UserName": "ada@example.com",
            "TimeGenerated": "2026-03-22T18:30:00Z",
        }
    ]


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
    assert payload["type"] == "AmortizedCost"
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


def test_cost_query_coordinator_serializes_queries():
    coordinator = AzureCostQueryCoordinator()
    events: list[str] = []

    def worker(name: str, hold_seconds: float) -> None:
        with coordinator.claim(name):
            events.append(f"start:{name}")
            time.sleep(hold_seconds)
            events.append(f"end:{name}")

    first = threading.Thread(target=worker, args=("detail", 0.05))
    second = threading.Thread(target=worker, args=("detail-2", 0.0))
    first.start()
    time.sleep(0.01)
    second.start()
    first.join()
    second.join()

    assert events == ["start:detail", "end:detail", "start:detail-2", "end:detail-2"]


def test_cost_query_coordinator_prioritizes_waiting_export_queries():
    coordinator = AzureCostQueryCoordinator()
    events: list[str] = []
    first_started = threading.Event()

    def default_worker() -> None:
        with coordinator.claim("detail"):
            events.append("start:detail")
            first_started.set()
            time.sleep(0.05)
            events.append("end:detail")

    def export_worker() -> None:
        with coordinator.claim("export"):
            events.append("start:export")
            events.append("end:export")

    def background_worker() -> None:
        with coordinator.claim("background"):
            events.append("start:background")
            events.append("end:background")

    first = threading.Thread(target=default_worker)
    background = threading.Thread(target=background_worker)
    export = threading.Thread(target=export_worker)

    first.start()
    assert first_started.wait(timeout=1)
    background.start()
    time.sleep(0.01)
    export.start()

    first.join()
    background.join()
    export.join()

    assert events[:4] == ["start:detail", "end:detail", "start:export", "end:export"]
    assert events[4:] == ["start:background", "end:background"]


def test_cost_query_coordinator_tracks_active_export_jobs():
    coordinator = AzureCostQueryCoordinator()

    assert coordinator.has_active_export_job() is False
    with coordinator.export_job():
        assert coordinator.has_active_export_job() is True
    assert coordinator.has_active_export_job() is False


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
    monkeypatch.setattr(cache._client, "list_reservations", lambda: [])

    cache._refresh_inventory()

    status = cache.status()
    inventory = next(dataset for dataset in status["datasets"] if dataset["key"] == "inventory")

    assert inventory["error"] is None
    assert inventory["item_count"] == 2
    assert inventory["last_refresh"] is not None
    assert cache._snapshot("management_groups") == []
    assert cache._snapshot("resources")[0]["subscription_name"] == "Prod"
