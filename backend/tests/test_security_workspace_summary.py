from __future__ import annotations

from datetime import datetime, timedelta, timezone

import security_workspace_summary


def _iso(*, hours_ago: int = 0, days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago, days=days_ago)).isoformat()


def _status(*, stale_directory: bool = False) -> dict[str, object]:
    directory_refresh = _iso(hours_ago=6) if stale_directory else _iso(hours_ago=1)
    return {
        "last_refresh": _iso(hours_ago=1),
        "datasets": [
            {"key": "alerts", "last_refresh": _iso(hours_ago=1), "error": ""},
            {"key": "inventory", "last_refresh": _iso(hours_ago=1), "error": ""},
            {"key": "directory", "last_refresh": directory_refresh, "error": ""},
            {"key": "conditional_access", "last_refresh": _iso(hours_ago=1), "error": ""},
            {"key": "device_compliance", "last_refresh": _iso(hours_ago=1), "error": ""},
        ],
    }


def _lane(summary, lane_key: str):
    return next(item for item in summary.lanes if item.lane_key == lane_key)


def test_workspace_summary_flags_account_health_as_critical_for_stale_passwords(monkeypatch):
    monkeypatch.setattr(security_workspace_summary.azure_cache, "status", lambda: _status())
    monkeypatch.setattr(
        security_workspace_summary.azure_cache,
        "_snapshot",
        lambda name: {
            "users": [
                {
                    "id": "user-1",
                    "display_name": "Ada Admin",
                    "enabled": True,
                    "extra": {
                        "user_type": "Member",
                        "account_class": "person_cloud",
                        "on_prem_sync": "",
                        "last_password_change": _iso(days_ago=120),
                        "department": "Security",
                        "job_title": "Admin",
                        "priority_score": "45",
                        "priority_band": "medium",
                    },
                }
            ],
        }.get(name, []),
    )

    summary = security_workspace_summary.build_security_workspace_summary({"email": "test@example.com"})

    lane = _lane(summary, "account-health")
    assert lane.status == "critical"
    assert lane.attention_count == 1
    assert lane.summary_mode == "count"


def test_workspace_summary_marks_user_review_as_warning_for_priority_queue(monkeypatch):
    monkeypatch.setattr(security_workspace_summary.azure_cache, "status", lambda: _status())
    monkeypatch.setattr(
        security_workspace_summary.azure_cache,
        "_snapshot",
        lambda name: {
            "users": [
                {
                    "id": "user-1",
                    "display_name": "Queue User",
                    "enabled": True,
                    "extra": {
                        "user_type": "Member",
                        "account_class": "person_cloud",
                        "priority_score": "65",
                        "priority_band": "high",
                        "last_successful_utc": _iso(days_ago=5),
                    },
                }
            ],
        }.get(name, []),
    )

    summary = security_workspace_summary.build_security_workspace_summary({"email": "test@example.com"})

    lane = _lane(summary, "user-review")
    assert lane.status == "warning"
    assert lane.attention_count == 1


def test_workspace_summary_marks_access_gated_lanes_unavailable(monkeypatch):
    monkeypatch.setattr(security_workspace_summary.azure_cache, "status", lambda: _status())
    monkeypatch.setattr(security_workspace_summary.azure_cache, "_snapshot", lambda name: [])
    monkeypatch.setattr(security_workspace_summary, "session_can_manage_users", lambda session: False)

    summary = security_workspace_summary.build_security_workspace_summary({"email": "test@example.com"})

    lane = _lane(summary, "device-compliance")
    assert lane.status == "unavailable"
    assert lane.access_available is False
    assert "required" in lane.access_message.lower()


def test_workspace_summary_surfaces_stale_directory_context(monkeypatch):
    monkeypatch.setattr(security_workspace_summary.azure_cache, "status", lambda: _status(stale_directory=True))
    monkeypatch.setattr(security_workspace_summary.azure_cache, "_snapshot", lambda name: [])

    summary = security_workspace_summary.build_security_workspace_summary({"email": "test@example.com"})

    lane = _lane(summary, "identity-review")
    assert lane.status == "warning"
    assert lane.warning_count >= 1
    assert lane.attention_count == 0


def test_workspace_summary_keeps_manual_lane_non_counted(monkeypatch):
    monkeypatch.setattr(security_workspace_summary.azure_cache, "status", lambda: _status())
    monkeypatch.setattr(security_workspace_summary.azure_cache, "_snapshot", lambda name: [])

    summary = security_workspace_summary.build_security_workspace_summary({"email": "test@example.com"})

    lane = _lane(summary, "security-copilot")
    assert lane.summary_mode == "manual"
    assert lane.status == "info"
    assert lane.attention_count == 0
    assert "Ready" in lane.attention_label


def test_workspace_summary_uses_availability_mode_for_directory_role_review_without_live_lookup(monkeypatch):
    monkeypatch.setattr(security_workspace_summary.azure_cache, "status", lambda: _status())
    monkeypatch.setattr(
        security_workspace_summary.azure_cache,
        "_snapshot",
        lambda name: [{"id": "role-1"}] if name == "directory_roles" else [],
    )
    monkeypatch.setattr(security_workspace_summary, "session_can_manage_users", lambda session: True)

    class _Client:
        def list_directory_role_members(self, *_args, **_kwargs):
            raise AssertionError("workspace summary should not perform live directory role lookups")

    monkeypatch.setattr(security_workspace_summary.azure_cache, "_client", _Client())

    summary = security_workspace_summary.build_security_workspace_summary({"email": "test@example.com"})

    lane = _lane(summary, "directory-role-review")
    assert lane.summary_mode == "availability"
    assert lane.attention_count == 0
    assert lane.status == "healthy"
