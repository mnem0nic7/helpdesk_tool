from __future__ import annotations

import security_conditional_access_tracker


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
            {"key": "conditional_access", "label": "Conditional Access", "last_refresh": "2026-04-03T02:45:00Z"},
        ],
    }


def test_build_security_conditional_access_tracker_flags_broad_policy_and_recent_changes(monkeypatch):
    snapshots = {
        "conditional_access_policies": [
            {
                "id": "policy-1",
                "display_name": "Require compliant device for all users",
                "state": "enabled",
                "created_date_time": "2026-02-01T00:00:00Z",
                "modified_date_time": "2026-04-03T01:00:00Z",
                "include_users": ["All"],
                "exclude_users": [],
                "include_groups": [],
                "exclude_groups": [],
                "include_roles": [],
                "exclude_roles": [],
                "include_guests_or_external": False,
                "exclude_guests_or_external": False,
                "include_applications": ["All"],
                "exclude_applications": [],
                "include_user_actions": [],
                "grant_controls": [],
                "custom_authentication_factors": [],
                "terms_of_use": [],
                "authentication_strength": "",
                "session_controls": ["applicationEnforcedRestrictions"],
            },
            {
                "id": "policy-2",
                "display_name": "Require MFA for admins",
                "state": "enabled",
                "created_date_time": "2026-01-01T00:00:00Z",
                "modified_date_time": "2026-04-02T20:00:00Z",
                "include_users": [],
                "exclude_users": ["user-1"],
                "include_groups": [],
                "exclude_groups": [],
                "include_roles": ["role-1"],
                "exclude_roles": [],
                "include_guests_or_external": False,
                "exclude_guests_or_external": False,
                "include_applications": ["All"],
                "exclude_applications": [],
                "include_user_actions": [],
                "grant_controls": ["mfa"],
                "custom_authentication_factors": [],
                "terms_of_use": [],
                "authentication_strength": "Multifactor authentication",
                "session_controls": [],
            },
        ],
        "conditional_access_audit_events": [
            {
                "id": "event-1",
                "activity_date_time": "2026-04-03T02:15:00Z",
                "activity_display_name": "Update conditional access policy",
                "result": "success",
                "initiated_by_display_name": "Ada Lovelace",
                "initiated_by_principal_name": "ada@example.com",
                "initiated_by_type": "user",
                "target_policy_id": "policy-1",
                "target_policy_name": "Require compliant device for all users",
                "modified_properties": ["grantControls", "state"],
            },
            {
                "id": "event-2",
                "activity_date_time": "2026-04-02T18:00:00Z",
                "activity_display_name": "Add conditional access policy",
                "result": "success",
                "initiated_by_display_name": "Automation App",
                "initiated_by_principal_name": "0000-1111",
                "initiated_by_type": "app",
                "target_policy_id": "policy-2",
                "target_policy_name": "Require MFA for admins",
                "modified_properties": ["conditions"],
            },
        ],
    }
    monkeypatch.setattr(
        security_conditional_access_tracker,
        "azure_cache",
        _StubAzureCache(snapshots, _status_payload()),
    )

    response = security_conditional_access_tracker.build_security_conditional_access_tracker(
        {"can_manage_users": True}
    )

    assert response.access_available is True
    assert response.metrics[0].value == 2
    assert response.metrics[1].value == 2
    assert response.metrics[2].value == 2
    assert response.metrics[3].value == 1

    broad_policy = next(item for item in response.policies if item.policy_id == "policy-1")
    assert broad_policy.impact_level == "critical"
    assert "all_users_scope" in broad_policy.risk_tags

    recent_change = next(item for item in response.changes if item.event_id == "event-1")
    assert recent_change.impact_level == "critical"
    assert any("broad-scope policy" in flag for flag in recent_change.flags)

    app_change = next(item for item in response.changes if item.event_id == "event-2")
    assert app_change.initiated_by_type == "app"
    assert any("application or service principal" in flag for flag in app_change.flags)
