from __future__ import annotations

import security_device_compliance


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
            {"key": "device_compliance", "label": "Device Compliance", "last_refresh": "2026-04-03T12:00:00Z", "error": ""},
        ],
    }


def test_build_security_device_compliance_review_flags_risky_devices(monkeypatch):
    snapshots = {
        "managed_devices": [
            {
                "id": "device-1",
                "device_name": "Payroll Laptop",
                "operating_system": "Windows",
                "operating_system_version": "11",
                "compliance_state": "noncompliant",
                "management_state": "managed",
                "owner_type": "company",
                "enrollment_type": "windowsAzureADJoin",
                "last_sync_date_time": "2026-04-03T10:00:00Z",
                "azure_ad_device_id": "aad-1",
                "primary_users": [
                    {
                        "id": "user-1",
                        "display_name": "Ada Lovelace",
                        "principal_name": "ada@example.com",
                        "mail": "ada@example.com",
                    }
                ],
            },
            {
                "id": "device-2",
                "device_name": "BYOD Phone",
                "operating_system": "iOS",
                "operating_system_version": "18",
                "compliance_state": "unknown",
                "management_state": "managed",
                "owner_type": "personal",
                "enrollment_type": "appleUserEnrollment",
                "last_sync_date_time": "2026-03-20T10:00:00Z",
                "azure_ad_device_id": "aad-2",
                "primary_users": [],
            },
            {
                "id": "device-3",
                "device_name": "Retired Kiosk",
                "operating_system": "Windows",
                "operating_system_version": "10",
                "compliance_state": "",
                "management_state": "retired",
                "owner_type": "company",
                "enrollment_type": "windowsAzureADJoin",
                "last_sync_date_time": "",
                "azure_ad_device_id": "aad-3",
                "primary_users": [],
            },
        ]
    }
    monkeypatch.setattr(
        security_device_compliance,
        "azure_cache",
        _StubAzureCache(snapshots, _status_payload()),
    )

    response = security_device_compliance.build_security_device_compliance_review({"email": "tech@example.com"})

    assert response.access_available is True
    assert response.metrics[0].value == 3
    assert response.metrics[1].value == 1
    assert response.metrics[2].value == 2
    assert response.metrics[3].value == 2
    assert response.metrics[4].value == 2
    assert response.metrics[5].value == 1
    assert response.metrics[6].value == 1

    critical = next(item for item in response.devices if item.id == "device-1")
    assert critical.risk_level == "critical"
    assert "noncompliant_or_grace" in critical.finding_tags
    assert critical.action_ready is True
    assert critical.recommended_fix_action == "device_sync"

    personal = next(item for item in response.devices if item.id == "device-2")
    assert personal.risk_level == "high"
    assert "personal_risky_device" in personal.finding_tags
    assert any("BYOD" in action or "Personally owned" in action for action in personal.recommended_actions)
    assert personal.recommended_fix_action == "device_reassign_primary_user"
    assert personal.recommended_fix_requires_user_picker is True

    retired = next(item for item in response.devices if item.id == "device-3")
    assert retired.action_ready is False
    assert any("retired" in blocker.lower() for blocker in retired.action_blockers)
    assert retired.recommended_fix_action is None


def test_build_security_device_compliance_review_hides_data_for_unauthorized_users(monkeypatch):
    monkeypatch.setattr(
        security_device_compliance,
        "azure_cache",
        _StubAzureCache({"managed_devices": []}, _status_payload()),
    )
    monkeypatch.setattr(security_device_compliance, "session_can_manage_users", lambda session: False)

    response = security_device_compliance.build_security_device_compliance_review({"email": "viewer@example.com"})

    assert response.access_available is False
    assert response.devices == []
    assert "required" in response.access_message.lower()


def test_build_security_device_fix_plan_groups_actions_and_skips(monkeypatch):
    snapshots = {
        "managed_devices": [
            {
                "id": "device-1",
                "device_name": "Payroll Laptop",
                "operating_system": "Windows",
                "operating_system_version": "11",
                "compliance_state": "noncompliant",
                "management_state": "managed",
                "owner_type": "company",
                "enrollment_type": "windowsAzureADJoin",
                "last_sync_date_time": "2026-04-03T10:00:00Z",
                "azure_ad_device_id": "aad-1",
                "primary_users": [
                    {
                        "id": "user-1",
                        "display_name": "Ada Lovelace",
                        "principal_name": "ada@example.com",
                        "mail": "ada@example.com",
                    }
                ],
            },
            {
                "id": "device-2",
                "device_name": "BYOD Phone",
                "operating_system": "iOS",
                "operating_system_version": "18",
                "compliance_state": "unknown",
                "management_state": "managed",
                "owner_type": "personal",
                "enrollment_type": "appleUserEnrollment",
                "last_sync_date_time": "2026-03-20T10:00:00Z",
                "azure_ad_device_id": "aad-2",
                "primary_users": [],
            },
            {
                "id": "device-3",
                "device_name": "Retired Kiosk",
                "operating_system": "Windows",
                "operating_system_version": "10",
                "compliance_state": "",
                "management_state": "retired",
                "owner_type": "company",
                "enrollment_type": "windowsAzureADJoin",
                "last_sync_date_time": "",
                "azure_ad_device_id": "aad-3",
                "primary_users": [],
            },
        ]
    }
    monkeypatch.setattr(
        security_device_compliance,
        "azure_cache",
        _StubAzureCache(snapshots, _status_payload()),
    )

    plan = security_device_compliance.build_security_device_fix_plan(
        {"email": "tech@example.com"},
        ["device-1", "device-2", "device-3", "device-missing"],
    )

    assert plan.device_ids == ["device-1", "device-2", "device-3", "device-missing"]
    assert len(plan.groups) == 1
    assert plan.groups[0].action_type == "device_sync"
    assert plan.groups[0].device_names == ["Payroll Laptop"]
    assert len(plan.devices_requiring_primary_user) == 1
    assert plan.devices_requiring_primary_user[0].device_id == "device-2"
    skipped_ids = {item.device_id for item in plan.skipped_devices}
    assert skipped_ids == {"device-3", "device-missing"}
    assert plan.requires_destructive_confirmation is False
