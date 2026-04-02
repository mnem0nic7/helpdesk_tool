from __future__ import annotations

import security_break_glass_validation


class _StubAzureCache:
    def __init__(self, snapshots, status_payload):
        self._snapshots = snapshots
        self._status_payload = status_payload

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


def test_build_security_break_glass_validation_flags_unvalidated_accounts(monkeypatch):
    snapshots = {
        "users": [
            {
                "id": "bg-1",
                "display_name": "Emergency Admin",
                "principal_name": "emergency-admin@example.com",
                "mail": "emergency-admin@example.com",
                "enabled": True,
                "extra": {
                    "user_type": "Member",
                    "account_class": "person_cloud",
                    "last_successful_utc": "2026-04-01T03:00:00Z",
                    "last_password_change": "2026-03-01T00:00:00Z",
                    "is_licensed": "false",
                    "license_count": "0",
                    "on_prem_sync": "",
                },
            },
            {
                "id": "bg-2",
                "display_name": "Break Glass Backup",
                "principal_name": "break-glass-backup@example.com",
                "mail": "break-glass-backup@example.com",
                "enabled": True,
                "extra": {
                    "user_type": "Member",
                    "account_class": "person_cloud",
                    "last_successful_utc": "",
                    "last_password_change": "2025-01-01T00:00:00Z",
                    "is_licensed": "true",
                    "license_count": "1",
                    "on_prem_sync": "",
                },
            },
            {
                "id": "bg-3",
                "display_name": "Tier0 Admin",
                "principal_name": "tier0-admin@example.com",
                "mail": "tier0-admin@example.com",
                "enabled": True,
                "extra": {
                    "user_type": "Member",
                    "account_class": "person_synced",
                    "last_successful_utc": "2025-10-01T00:00:00Z",
                    "last_password_change": "2025-09-01T00:00:00Z",
                    "is_licensed": "false",
                    "license_count": "0",
                    "on_prem_sync": "true",
                },
            },
        ],
        "role_assignments": [
            {
                "id": "assignment-1",
                "principal_id": "bg-1",
                "principal_type": "User",
                "role_definition_id": "/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
                "role_name": "Owner",
            },
            {
                "id": "assignment-2",
                "principal_id": "bg-3",
                "principal_type": "User",
                "role_definition_id": "/subscriptions/sub-1/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c",
                "role_name": "Contributor",
            },
        ],
    }
    monkeypatch.setattr(
        security_break_glass_validation,
        "azure_cache",
        _StubAzureCache(snapshots, _status_payload()),
    )

    response = security_break_glass_validation.build_security_break_glass_validation()

    assert response.metrics[0].value == 3
    assert response.metrics[1].value == 2
    assert response.metrics[2].value == 2
    assert response.metrics[3].value == 2
    assert response.metrics[4].value == 1
    assert response.metrics[5].value == 1
    assert any("MFA registration posture" in warning for warning in response.warnings)

    healthy = next(item for item in response.accounts if item.user_id == "bg-1")
    assert healthy.status == "healthy"
    assert healthy.has_privileged_access is True

    missing_sign_in = next(item for item in response.accounts if item.user_id == "bg-2")
    assert missing_sign_in.status == "critical"
    assert any("No successful sign-in" in flag for flag in missing_sign_in.flags)
    assert any("license" in flag.lower() for flag in missing_sign_in.flags)

    synced = next(item for item in response.accounts if item.user_id == "bg-3")
    assert synced.status == "critical"
    assert synced.on_prem_sync is True
    assert any("source directory" in flag.lower() for flag in synced.flags)
