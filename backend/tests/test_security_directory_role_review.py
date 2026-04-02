from __future__ import annotations

import security_directory_role_review


class _StubAzureClient:
    def __init__(self, members_by_role):
        self.members_by_role = members_by_role
        self.seen_role_ids: list[str] = []

    def list_directory_role_members(self, role_ids):
        self.seen_role_ids = list(role_ids)
        return self.members_by_role


class _StubAzureCache:
    def __init__(self, snapshots, status_payload, members_by_role):
        self._snapshots = snapshots
        self._status_payload = status_payload
        self._client = _StubAzureClient(members_by_role)

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
            {"key": "directory", "label": "Directory", "last_refresh": "2099-04-02T01:00:00Z"},
        ],
    }


def test_build_security_directory_role_review_requires_user_admin_access(monkeypatch):
    snapshots = {
        "directory_roles": [
            {
                "id": "role-1",
                "display_name": "Global Administrator",
                "extra": {"description": "Full tenant access."},
            }
        ]
    }
    cache = _StubAzureCache(snapshots, _status_payload(), {"role-1": {"members": [], "member_lookup_error": "", "truncated": False}})
    monkeypatch.setattr(security_directory_role_review, "azure_cache", cache)
    monkeypatch.setattr(security_directory_role_review, "session_can_manage_users", lambda session: False)

    response = security_directory_role_review.build_security_directory_role_review({"email": "reader@example.com"})

    assert response.access_available is False
    assert "User administration access is required" in response.access_message
    assert response.roles == []
    assert response.memberships == []
    assert cache._client.seen_role_ids == []


def test_build_security_directory_role_review_flags_high_risk_memberships(monkeypatch):
    snapshots = {
        "directory_roles": [
            {
                "id": "role-1",
                "display_name": "Global Administrator",
                "extra": {"description": "Full tenant access."},
            },
            {
                "id": "role-2",
                "display_name": "User Administrator",
                "extra": {"description": "Can manage users."},
            },
        ],
        "users": [
            {
                "id": "user-1",
                "display_name": "Ada Guest",
                "principal_name": "ada.guest@example.com",
                "enabled": True,
                "extra": {
                    "user_type": "Guest",
                    "last_successful_utc": "2026-01-15T00:00:00Z",
                },
            },
            {
                "id": "user-2",
                "display_name": "Disabled Admin",
                "principal_name": "disabled.admin@example.com",
                "enabled": False,
                "extra": {
                    "user_type": "Member",
                    "last_successful_utc": "",
                },
            },
        ],
        "groups": [
            {
                "id": "group-1",
                "display_name": "Privileged Operators",
                "mail": "privileged.operators@example.com",
                "enabled": True,
            }
        ],
        "service_principals": [
            {
                "id": "sp-1",
                "display_name": "Payroll Automator",
                "app_id": "11111111-2222-3333-4444-555555555555",
                "enabled": True,
            }
        ],
    }
    members_by_role = {
        "role-1": {
            "members": [
                {
                    "id": "user-1",
                    "@odata.type": "#microsoft.graph.user",
                    "displayName": "Ada Guest",
                    "userPrincipalName": "ada.guest@example.com",
                    "accountEnabled": True,
                    "userType": "Guest",
                },
                {
                    "id": "group-1",
                    "@odata.type": "#microsoft.graph.group",
                    "displayName": "Privileged Operators",
                    "mail": "privileged.operators@example.com",
                    "securityEnabled": True,
                },
                {
                    "id": "sp-1",
                    "@odata.type": "#microsoft.graph.servicePrincipal",
                    "displayName": "Payroll Automator",
                    "appId": "11111111-2222-3333-4444-555555555555",
                    "accountEnabled": True,
                },
            ],
            "member_lookup_error": "",
            "truncated": False,
        },
        "role-2": {
            "members": [
                {
                    "id": "user-2",
                    "@odata.type": "#microsoft.graph.user",
                    "displayName": "Disabled Admin",
                    "userPrincipalName": "disabled.admin@example.com",
                    "accountEnabled": False,
                    "userType": "Member",
                }
            ],
            "member_lookup_error": "Read timeout from Microsoft Graph.",
            "truncated": True,
        },
    }
    cache = _StubAzureCache(snapshots, _status_payload(), members_by_role)
    monkeypatch.setattr(security_directory_role_review, "azure_cache", cache)
    monkeypatch.setattr(security_directory_role_review, "session_can_manage_users", lambda session: True)

    response = security_directory_role_review.build_security_directory_role_review({"email": "admin@example.com"})

    assert response.access_available is True
    assert cache._client.seen_role_ids == ["role-1", "role-2"]
    assert response.metrics[0].value == 2
    assert response.metrics[1].value == 4
    assert response.metrics[2].value == 4
    assert response.metrics[3].value == 1
    assert response.metrics[4].value == 1
    assert response.metrics[5].value == 1

    assert response.roles[0].display_name == "Global Administrator"
    assert response.roles[0].member_count == 3
    assert response.roles[0].flagged_member_count == 3

    user_membership = next(item for item in response.memberships if item.principal_id == "user-1")
    assert user_membership.status == "critical"
    assert any("Guest user holds a direct Entra directory role." in flag for flag in user_membership.flags)
    assert any("last 30 days" in flag for flag in user_membership.flags)

    group_membership = next(item for item in response.memberships if item.principal_id == "group-1")
    assert group_membership.status == "warning"
    assert any("Group-based direct directory role membership" in flag for flag in group_membership.flags)

    service_principal_membership = next(item for item in response.memberships if item.principal_id == "sp-1")
    assert service_principal_membership.status == "critical"
    assert any("Service principal holds a direct Entra directory role." in flag for flag in service_principal_membership.flags)

    disabled_user = next(item for item in response.memberships if item.principal_id == "user-2")
    assert disabled_user.status == "critical"
    assert any("disabled user" in flag.lower() for flag in disabled_user.flags)
    assert any("No successful sign-in is recorded" in flag for flag in disabled_user.flags)

    assert "Read timeout from Microsoft Graph." in response.warnings
    assert "Membership list was truncated to the first 100 results." in response.warnings
