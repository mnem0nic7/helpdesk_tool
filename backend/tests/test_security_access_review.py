from __future__ import annotations

import security_access_review


class _StubRoleClient:
    def __init__(self, definitions=None, *, explode: bool = False):
        self._definitions = definitions or []
        self._explode = explode

    def list_role_definitions(self, subscription_ids):
        if self._explode:
            raise RuntimeError("role definition lookup failed")
        return list(self._definitions)


class _StubAzureCache:
    def __init__(self, snapshots, status_payload, client):
        self._snapshots = snapshots
        self._status_payload = status_payload
        self._client = client

    def _snapshot(self, key):
        return self._snapshots.get(key, [])

    def status(self):
        return self._status_payload


def _status_payload():
    return {
        "configured": True,
        "initialized": True,
        "refreshing": False,
        "datasets": [
            {"key": "inventory", "label": "Inventory", "last_refresh": "2026-04-02T01:00:00Z"},
            {"key": "directory", "label": "Identity", "last_refresh": "2026-04-02T01:00:00Z"},
        ],
    }


def test_build_security_access_review_resolves_role_names_and_flags(monkeypatch):
    snapshots = {
        "users": [
            {
                "id": "guest-1",
                "display_name": "Consultant Guest",
                "object_type": "user",
                "principal_name": "consultant@example.com",
                "mail": "consultant@example.com",
                "enabled": True,
                "app_id": "",
                "extra": {
                    "user_type": "Guest",
                    "account_class": "guest_external",
                    "last_successful_utc": "",
                },
            },
            {
                "id": "break-1",
                "display_name": "Emergency Admin",
                "object_type": "user",
                "principal_name": "emergency-admin@example.com",
                "mail": "emergency-admin@example.com",
                "enabled": True,
                "app_id": "",
                "extra": {
                    "user_type": "Member",
                    "account_class": "person_cloud",
                    "last_successful_utc": "2020-01-01T00:00:00Z",
                },
            },
        ],
        "groups": [],
        "service_principals": [
            {
                "id": "sp-1",
                "display_name": "Automation SP",
                "object_type": "enterprise_app",
                "principal_name": "",
                "mail": "",
                "enabled": True,
                "app_id": "11111111-2222-3333-4444-555555555555",
                "extra": {},
            }
        ],
        "subscriptions": [{"subscription_id": "sub-1", "display_name": "Prod"}],
        "role_assignments": [
            {
                "id": "assignment-1",
                "scope": "/subscriptions/sub-1",
                "subscription_id": "sub-1",
                "principal_id": "guest-1",
                "principal_type": "User",
                "role_definition_id": "/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
                "role_name": "",
            },
            {
                "id": "assignment-2",
                "scope": "/subscriptions/sub-1/resourceGroups/rg-ops",
                "subscription_id": "sub-1",
                "principal_id": "sp-1",
                "principal_type": "ServicePrincipal",
                "role_definition_id": "/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c",
                "role_name": "",
            },
            {
                "id": "assignment-3",
                "scope": "/subscriptions/sub-1",
                "subscription_id": "sub-1",
                "principal_id": "break-1",
                "principal_type": "User",
                "role_definition_id": "/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/18d7d88d-d35e-4fb5-a5c3-7773c20a72d9",
                "role_name": "",
            },
        ],
    }
    client = _StubRoleClient(
        [
            {
                "id": "/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
                "role_guid": "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
                "role_name": "Owner",
            },
            {
                "id": "/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c",
                "role_guid": "b24988ac-6180-42a0-ab88-20f7382dd24c",
                "role_name": "Contributor",
            },
            {
                "id": "/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/18d7d88d-d35e-4fb5-a5c3-7773c20a72d9",
                "role_guid": "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9",
                "role_name": "User Access Administrator",
            },
        ]
    )
    monkeypatch.setattr(security_access_review, "azure_cache", _StubAzureCache(snapshots, _status_payload(), client))

    response = security_access_review.build_security_access_review()

    assert response.metrics[0].value == 3
    assert response.metrics[1].value == 2
    assert response.metrics[4].value == 1
    assert any(item.role_name == "Owner" for item in response.assignments)
    assert any(item.role_name == "User Access Administrator" for item in response.assignments)
    guest_principal = next(item for item in response.flagged_principals if item.principal_id == "guest-1")
    assert guest_principal.highest_privilege == "critical"
    assert any("Guest user" in flag for flag in guest_principal.flags)
    assert any("subscription root" in flag.lower() for flag in guest_principal.flags)
    break_glass = next(item for item in response.break_glass_candidates if item.user_id == "break-1")
    assert break_glass.has_privileged_access is True
    assert "Emergency naming" in break_glass.matched_terms


def test_build_security_access_review_falls_back_to_known_role_ids_when_live_lookup_fails(monkeypatch):
    snapshots = {
        "users": [
            {
                "id": "user-1",
                "display_name": "Owner User",
                "object_type": "user",
                "principal_name": "owner@example.com",
                "mail": "owner@example.com",
                "enabled": True,
                "app_id": "",
                "extra": {"user_type": "Member", "account_class": "person_cloud", "last_successful_utc": "2026-04-01T10:00:00Z"},
            }
        ],
        "groups": [],
        "service_principals": [],
        "subscriptions": [{"subscription_id": "sub-1", "display_name": "Prod"}],
        "role_assignments": [
            {
                "id": "assignment-1",
                "scope": "/subscriptions/sub-1",
                "subscription_id": "sub-1",
                "principal_id": "user-1",
                "principal_type": "User",
                "role_definition_id": "/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
                "role_name": "",
            }
        ],
    }
    monkeypatch.setattr(
        security_access_review,
        "azure_cache",
        _StubAzureCache(snapshots, _status_payload(), _StubRoleClient(explode=True)),
    )

    response = security_access_review.build_security_access_review()

    assert response.assignments[0].role_name == "Owner"
    assert any("could not be refreshed live" in warning for warning in response.warnings)
