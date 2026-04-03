"""Azure device-compliance review helpers for the Security workspace."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from auth import session_can_manage_users
from azure_cache import azure_cache
from models import (
    SecurityAccessReviewMetric,
    SecurityDeviceActionType,
    SecurityDeviceComplianceDevice,
    SecurityDeviceComplianceResponse,
    SecurityDeviceFixPlanDevice,
    SecurityDeviceFixPlanGroup,
    SecurityDeviceFixPlanResponse,
    UserAdminReference,
)
from security_access_review import _dataset_is_stale, _dataset_last_refresh, _parse_datetime, _utc_now

_STALE_DEVICE_HOURS = 2
_STALE_SYNC_DAYS = 7
_INACTIVE_SYNC_DAYS = 30
_ACTIONABLE_ACTIONS = [
    "device_sync",
    "device_remote_lock",
    "device_retire",
    "device_wipe",
    "device_reassign_primary_user",
]
_DESTRUCTIVE_ACTIONS = {"device_retire", "device_wipe"}
_ACTION_LABELS: dict[str, str] = {
    "device_sync": "Device sync",
    "device_remote_lock": "Remote lock",
    "device_retire": "Retire device",
    "device_wipe": "Wipe device",
    "device_reassign_primary_user": "Assign primary user",
}


def _days_since(value: str) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() // 86_400))


def _unique_list(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(text)
    return result


def _normalize_primary_users(raw_users: Any) -> list[UserAdminReference]:
    users: list[UserAdminReference] = []
    for item in raw_users or []:
        if not isinstance(item, dict):
            continue
        users.append(
            UserAdminReference(
                id=str(item.get("id") or ""),
                display_name=str(item.get("display_name") or item.get("displayName") or item.get("principal_name") or item.get("userPrincipalName") or item.get("mail") or ""),
                principal_name=str(item.get("principal_name") or item.get("userPrincipalName") or item.get("mail") or ""),
                mail=str(item.get("mail") or ""),
            )
        )
    return users


def _action_label(action_type: SecurityDeviceActionType | None) -> str:
    if not action_type:
        return ""
    return _ACTION_LABELS.get(action_type, str(action_type))


def _default_fix_for_device(
    *,
    finding_tags: list[str],
    action_ready: bool,
    supported_actions: list[SecurityDeviceActionType],
) -> tuple[SecurityDeviceActionType | None, str, bool]:
    if not action_ready:
        return None, "", False
    tags = set(finding_tags)
    supported = set(supported_actions)
    if "no_primary_user" in tags and "device_reassign_primary_user" in supported:
        return (
            "device_reassign_primary_user",
            "Assign a primary user before broader remediation because the device currently has no resolved owner.",
            True,
        )
    if ("inactive_or_unmanaged" in tags or "personal_risky_device" in tags) and "device_retire" in supported:
        return (
            "device_retire",
            "Retire the device because cached posture shows a lifecycle, ownership, or management risk that is better handled through cleanup.",
            False,
        )
    if (
        {"stale_sync", "unknown_or_not_evaluated", "noncompliant_or_grace"} & tags
        and "device_sync" in supported
    ):
        return (
            "device_sync",
            "Run an Intune sync first so compliance state and policy evaluation refresh before deeper escalation.",
            False,
        )
    return None, "", False


def _recommendations(
    *,
    compliance_state: str,
    management_state: str,
    owner_type: str,
    last_sync_age_days: int | None,
    primary_users: list[UserAdminReference],
) -> tuple[str, list[str], list[str], bool, list[str], list[str], SecurityDeviceActionType | None, str, bool]:
    normalized_compliance = compliance_state.strip().lower()
    normalized_management = management_state.strip().lower()
    normalized_owner = owner_type.strip().lower()
    tags: list[str] = []
    recommendations: list[str] = []
    blockers: list[str] = []
    risk = "low"

    if normalized_compliance in {"noncompliant", "ingraceperiod", "error", "conflict", "configmanager"}:
        tags.append("noncompliant_or_grace")
        recommendations.append("Run an Intune device sync and review the device's failing compliance policies.")
        risk = "critical" if normalized_compliance == "noncompliant" else "high"

    if normalized_compliance in {"unknown", "notevaluated", "not_evaluated", ""}:
        tags.append("unknown_or_not_evaluated")
        recommendations.append("Verify the device is still checking in to Intune and review enrollment or policy-evaluation gaps.")
        if risk == "low":
            risk = "medium"

    if last_sync_age_days is None or last_sync_age_days > _STALE_SYNC_DAYS:
        tags.append("stale_sync")
        recommendations.append("Force a device sync and validate network reachability before trusting the current compliance state.")
        if risk in {"low", "medium"}:
            risk = "high" if last_sync_age_days is None or last_sync_age_days > _INACTIVE_SYNC_DAYS else "medium"

    if not primary_users:
        tags.append("no_primary_user")
        recommendations.append("Review device ownership and assign a primary user before leaving the device in production scope.")
        if risk == "low":
            risk = "medium"

    if normalized_owner == "personal" and tags:
        tags.append("personal_risky_device")
        recommendations.append("Personally owned device risk should be reviewed against BYOD policy and consider retire instead of broad trust.")
        if risk in {"low", "medium"}:
            risk = "high"

    if normalized_management in {"retirepending", "wipepending", "retired", "deletepending", "unmanaged"} or (
        last_sync_age_days is not None and last_sync_age_days > _INACTIVE_SYNC_DAYS
    ):
        tags.append("inactive_or_unmanaged")
        recommendations.append("Treat this device as a cleanup candidate if the current owner no longer needs it or Intune management has lapsed.")
        if risk in {"low", "medium"}:
            risk = "high"

    action_ready = True
    if normalized_management in {"retired", "deletepending"}:
        blockers.append("Device is already retired or pending deletion in Intune.")
        action_ready = False
    if not compliance_state and not management_state and last_sync_age_days is None:
        blockers.append("Cached Intune posture is incomplete for this device.")
        action_ready = False

    supported_actions = list(_ACTIONABLE_ACTIONS) if action_ready else []

    if not recommendations:
        recommendations.append("No urgent remediation is recommended from the current cached Intune posture.")

    unique_tags = _unique_list(tags)
    unique_recommendations = _unique_list(recommendations)
    unique_blockers = _unique_list(blockers)
    recommended_fix_action, recommended_fix_reason, recommended_fix_requires_user_picker = _default_fix_for_device(
        finding_tags=unique_tags,
        action_ready=action_ready,
        supported_actions=supported_actions,  # type: ignore[arg-type]
    )

    return (
        risk,
        unique_tags,
        unique_recommendations,
        action_ready,
        supported_actions,
        unique_blockers,
        recommended_fix_action,
        recommended_fix_reason,
        recommended_fix_requires_user_picker,
    )


def build_security_device_compliance_review(session: dict[str, Any]) -> SecurityDeviceComplianceResponse:
    status = azure_cache.status()
    device_last_refresh = _dataset_last_refresh(status, "device_compliance")
    warnings: list[str] = []

    if _dataset_is_stale(device_last_refresh, hours=_STALE_DEVICE_HOURS):
        warnings.append("Device compliance cache data is older than 2 hours, so Intune posture may be stale.")

    device_dataset_error = ""
    for dataset in status.get("datasets") if isinstance(status.get("datasets"), list) else []:
        if str(dataset.get("key") or "").strip().lower() == "device_compliance":
            device_dataset_error = str(dataset.get("error") or "").strip()
            break
    if device_dataset_error:
        warnings.append(f"Device compliance refresh warning: {device_dataset_error}")

    scope_notes = [
        "This lane reviews cached Intune managed-device posture across the tenant instead of making operators inspect one user at a time.",
        "Recommendations are deterministic and rule-based. They do not rely on AI synthesis.",
        "Bulk actions queue Azure-host device jobs that call the existing Intune device-management provider.",
    ]

    if not session_can_manage_users(session):
        return SecurityDeviceComplianceResponse(
            generated_at=_utc_now(),
            device_last_refresh=device_last_refresh,
            access_available=False,
            access_message="User administration access is required to review and remediate Intune device compliance on this tenant.",
            metrics=[],
            devices=[],
            warnings=warnings,
            scope_notes=scope_notes,
        )

    rows = azure_cache._snapshot("managed_devices") or []
    devices: list[SecurityDeviceComplianceDevice] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        primary_users = _normalize_primary_users(row.get("primary_users"))
        lookup_error = str(row.get("primary_user_lookup_error") or "").strip()
        if lookup_error:
            warnings.append(f"Primary-user lookup warning for {row.get('device_name') or row.get('id') or 'a managed device'}: {lookup_error}")

        last_sync_date_time = str(row.get("last_sync_date_time") or "")
        last_sync_age_days = _days_since(last_sync_date_time)
        (
            risk_level,
            finding_tags,
            recommended_actions,
            action_ready,
            supported_actions,
            action_blockers,
            recommended_fix_action,
            recommended_fix_reason,
            recommended_fix_requires_user_picker,
        ) = _recommendations(
            compliance_state=str(row.get("compliance_state") or ""),
            management_state=str(row.get("management_state") or ""),
            owner_type=str(row.get("owner_type") or ""),
            last_sync_age_days=last_sync_age_days,
            primary_users=primary_users,
        )

        devices.append(
            SecurityDeviceComplianceDevice(
                id=str(row.get("id") or ""),
                device_name=str(row.get("device_name") or row.get("id") or "Unknown device"),
                operating_system=str(row.get("operating_system") or ""),
                operating_system_version=str(row.get("operating_system_version") or ""),
                compliance_state=str(row.get("compliance_state") or ""),
                management_state=str(row.get("management_state") or ""),
                owner_type=str(row.get("owner_type") or ""),
                enrollment_type=str(row.get("enrollment_type") or ""),
                last_sync_date_time=last_sync_date_time,
                last_sync_age_days=last_sync_age_days,
                azure_ad_device_id=str(row.get("azure_ad_device_id") or ""),
                primary_users=primary_users,
                risk_level=risk_level,  # type: ignore[arg-type]
                finding_tags=finding_tags,
                recommended_actions=recommended_actions,
                recommended_fix_action=recommended_fix_action,
                recommended_fix_label=_action_label(recommended_fix_action),
                recommended_fix_reason=recommended_fix_reason,
                recommended_fix_requires_user_picker=recommended_fix_requires_user_picker,
                action_ready=action_ready,
                supported_actions=supported_actions,  # type: ignore[arg-type]
                action_blockers=action_blockers,
            )
        )

    risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    devices.sort(
        key=lambda item: (
            risk_order.get(item.risk_level, 4),
            -(len(item.finding_tags)),
            str(item.device_name or "").lower(),
        )
    )

    metrics = [
        SecurityAccessReviewMetric(
            key="managed_devices",
            label="Managed devices",
            value=len(devices),
            detail="Total Intune managed-device records in the cached tenant-wide review.",
            tone="sky",
        ),
        SecurityAccessReviewMetric(
            key="noncompliant_or_grace",
            label="Noncompliant / grace",
            value=sum(1 for item in devices if "noncompliant_or_grace" in item.finding_tags),
            detail="Devices already noncompliant or still in the compliance grace window.",
            tone="rose",
        ),
        SecurityAccessReviewMetric(
            key="unknown_or_not_evaluated",
            label="Unknown posture",
            value=sum(1 for item in devices if "unknown_or_not_evaluated" in item.finding_tags),
            detail="Devices with unknown or not-yet-evaluated compliance state.",
            tone="amber",
        ),
        SecurityAccessReviewMetric(
            key="stale_sync",
            label="Stale sync",
            value=sum(1 for item in devices if "stale_sync" in item.finding_tags),
            detail="Devices that have not checked in within the last 7 days.",
            tone="amber",
        ),
        SecurityAccessReviewMetric(
            key="no_primary_user",
            label="No primary user",
            value=sum(1 for item in devices if "no_primary_user" in item.finding_tags),
            detail="Managed devices that do not currently resolve to a primary user.",
            tone="violet",
        ),
        SecurityAccessReviewMetric(
            key="personal_risky_devices",
            label="Personal risky devices",
            value=sum(1 for item in devices if "personal_risky_device" in item.finding_tags),
            detail="Personally owned devices that also carry one or more compliance or lifecycle risks.",
            tone="rose",
        ),
        SecurityAccessReviewMetric(
            key="inactive_or_unmanaged",
            label="Inactive / unmanaged",
            value=sum(1 for item in devices if "inactive_or_unmanaged" in item.finding_tags),
            detail="Cleanup candidates that appear stale, unmanaged, or already moving through retirement.",
            tone="slate",
        ),
    ]

    return SecurityDeviceComplianceResponse(
        generated_at=_utc_now(),
        device_last_refresh=device_last_refresh,
        access_available=True,
        access_message="Tenant-wide device compliance review is available.",
        metrics=metrics,
        devices=devices,
        warnings=_unique_list(warnings),
        scope_notes=scope_notes,
    )


def _fix_plan_item_for_device(device: SecurityDeviceComplianceDevice) -> SecurityDeviceFixPlanDevice:
    if not device.action_ready:
        return SecurityDeviceFixPlanDevice(
            device_id=device.id,
            device_name=device.device_name,
            risk_level=device.risk_level,
            finding_tags=device.finding_tags,
            action_type=None,
            action_label="",
            action_reason="",
            requires_primary_user=False,
            primary_users=device.primary_users,
            skip_reason=(device.action_blockers[0] if device.action_blockers else "This device is review-only in the current cache."),
        )
    if device.recommended_fix_action == "device_reassign_primary_user":
        return SecurityDeviceFixPlanDevice(
            device_id=device.id,
            device_name=device.device_name,
            risk_level=device.risk_level,
            finding_tags=device.finding_tags,
            action_type="device_reassign_primary_user",
            action_label=_action_label("device_reassign_primary_user"),
            action_reason=device.recommended_fix_reason,
            requires_primary_user=True,
            primary_users=device.primary_users,
            skip_reason="",
        )
    if device.recommended_fix_action in {"device_sync", "device_retire"}:
        action_type = device.recommended_fix_action
        return SecurityDeviceFixPlanDevice(
            device_id=device.id,
            device_name=device.device_name,
            risk_level=device.risk_level,
            finding_tags=device.finding_tags,
            action_type=action_type,
            action_label=_action_label(action_type),
            action_reason=device.recommended_fix_reason,
            requires_primary_user=False,
            primary_users=device.primary_users,
            skip_reason="",
        )
    return SecurityDeviceFixPlanDevice(
        device_id=device.id,
        device_name=device.device_name,
        risk_level=device.risk_level,
        finding_tags=device.finding_tags,
        action_type=None,
        action_label="",
        action_reason="",
        requires_primary_user=False,
        primary_users=device.primary_users,
        skip_reason="No default smart remediation was selected from the current device findings.",
    )


def build_security_device_fix_plan(session: dict[str, Any], device_ids: list[str]) -> SecurityDeviceFixPlanResponse:
    review = build_security_device_compliance_review(session)
    device_by_id = {device.id: device for device in review.devices}

    cleaned_ids: list[str] = []
    seen: set[str] = set()
    for value in device_ids:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned_ids.append(text)

    items: list[SecurityDeviceFixPlanDevice] = []
    groups_map: dict[str, list[SecurityDeviceFixPlanDevice]] = {}
    devices_requiring_primary_user: list[SecurityDeviceFixPlanDevice] = []
    skipped_devices: list[SecurityDeviceFixPlanDevice] = []
    warnings = list(review.warnings)

    for device_id in cleaned_ids:
        device = device_by_id.get(device_id)
        if not device:
            skipped = SecurityDeviceFixPlanDevice(
                device_id=device_id,
                device_name=device_id,
                risk_level="low",
                finding_tags=[],
                action_type=None,
                action_label="",
                action_reason="",
                requires_primary_user=False,
                primary_users=[],
                skip_reason="The current device compliance cache does not contain this device.",
            )
            items.append(skipped)
            skipped_devices.append(skipped)
            continue

        plan_item = _fix_plan_item_for_device(device)
        items.append(plan_item)
        if plan_item.requires_primary_user:
            devices_requiring_primary_user.append(plan_item)
        elif plan_item.action_type:
            groups_map.setdefault(plan_item.action_type, []).append(plan_item)
        else:
            skipped_devices.append(plan_item)

    groups = [
        SecurityDeviceFixPlanGroup(
            action_type=action_type,  # type: ignore[arg-type]
            action_label=_action_label(action_type),  # type: ignore[arg-type]
            device_count=len(group_items),
            device_ids=[item.device_id for item in group_items],
            device_names=sorted([item.device_name for item in group_items], key=str.lower),
            requires_confirmation=action_type in _DESTRUCTIVE_ACTIONS,
        )
        for action_type, group_items in sorted(groups_map.items(), key=lambda item: _action_label(item[0]).lower())
    ]

    destructive_device_names = sorted(
        [
            item.device_name
            for group in groups
            if group.action_type in _DESTRUCTIVE_ACTIONS
            for item in groups_map.get(group.action_type, [])
        ],
        key=str.lower,
    )

    return SecurityDeviceFixPlanResponse(
        generated_at=_utc_now(),
        device_ids=cleaned_ids,
        items=items,
        groups=groups,
        devices_requiring_primary_user=devices_requiring_primary_user,
        skipped_devices=skipped_devices,
        destructive_device_count=len(destructive_device_names),
        destructive_device_names=destructive_device_names,
        requires_destructive_confirmation=bool(destructive_device_names),
        warnings=_unique_list(warnings),
    )
