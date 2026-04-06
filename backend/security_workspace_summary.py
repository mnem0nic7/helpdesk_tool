"""Azure security workspace summary helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from auth import session_can_manage_users
from azure_cache import azure_cache
from models import SecurityWorkspaceLaneSummary, SecurityWorkspaceSummaryResponse
from security_finding_exception_store import security_finding_exception_store
from security_access_review import (
    _break_glass_matches,
    _classify_privilege,
    _dataset_is_stale,
    _dataset_last_refresh,
    _parse_datetime,
    _principal_metadata,
    _principal_record,
    _privileged_user_signin_flag,
    _role_guid,
    _role_name_from_fallback,
    _subscription_scope,
    _utc_now,
)
from security_application_hygiene import (
    _EXPIRING_SOON_DAYS,
    _fallback_application_security_rows,
    _owner_names,
)
from security_break_glass_validation import _bool_from_extra, _candidate_status, _privileged_assignment_counts, _signin_state
from security_conditional_access_tracker import _change_impact, _policy_impact, _policy_risk_tags
from security_device_compliance import (
    _STALE_DEVICE_HOURS,
    _normalize_primary_users,
    _recommendations,
)

_PRIORITY_THRESHOLD = 60
_PRIORITY_CRITICAL_THRESHOLD = 80
_GUEST_AGE_THRESHOLD_DAYS = 180
_GUEST_SIGNIN_THRESHOLD_DAYS = 90
_ACCOUNT_HEALTH_PASSWORD_THRESHOLD_DAYS = 90
_ACCOUNT_HEALTH_GUEST_THRESHOLD_DAYS = 180
_DIRECTORY_USER_EXCEPTION_SCOPE = "directory_user"
_PRIVILEGE_CRITICAL_FLAG_MARKERS = (
    "guest user holds privileged azure rbac access",
    "external or foreign group holds privileged azure rbac access",
    "disabled user still has privileged azure rbac access",
    "no successful sign-in",
    "subscription root",
    "service principal holds privileged azure rbac access",
)

logger = logging.getLogger(__name__)


def _dataset_row(status: dict[str, Any], dataset_key: str) -> dict[str, Any]:
    datasets = status.get("datasets") if isinstance(status.get("datasets"), list) else []
    for dataset in datasets:
        if str(dataset.get("key") or "").strip().lower() == dataset_key.lower():
            return dataset
    return {}


def _dataset_warning_count(status: dict[str, Any], specs: list[tuple[str, int]]) -> tuple[int, str]:
    warning_count = 0
    refresh_values: list[str] = []
    for dataset_key, hours in specs:
        dataset = _dataset_row(status, dataset_key)
        refresh_at = _dataset_last_refresh(status, dataset_key)
        if refresh_at:
            refresh_values.append(refresh_at)
        if _dataset_is_stale(refresh_at, hours=hours):
            warning_count += 1
        if str(dataset.get("error") or "").strip():
            warning_count += 1
    return warning_count, _latest_timestamp(refresh_values)


def _latest_timestamp(values: list[str]) -> str:
    latest_value = ""
    latest_dt: datetime | None = None
    for value in values:
        parsed = _parse_datetime(value)
        if parsed is None:
            continue
        if latest_dt is None or parsed > latest_dt:
            latest_dt = parsed
            latest_value = value
    return latest_value


def _summary_score(status: str, attention_count: int, warning_count: int, summary_mode: str) -> int:
    base = {
        "unavailable": 720,
        "critical": 520,
        "warning": 300,
        "healthy": 120,
        "info": 80,
    }.get(status, 0)
    score = base + min(attention_count, 99) * 4 + warning_count * 18
    if summary_mode == "manual" and status != "unavailable":
        return min(score, 96 if status == "warning" else 40)
    if summary_mode == "availability" and status != "unavailable":
        return min(score, 84 if status == "warning" else 28)
    return score


def _make_lane(
    *,
    lane_key: str,
    status: str,
    attention_count: int,
    attention_label: str,
    secondary_label: str,
    refresh_at: str,
    warning_count: int,
    summary_mode: str,
    access_available: bool = True,
    access_message: str = "",
) -> SecurityWorkspaceLaneSummary:
    return SecurityWorkspaceLaneSummary(
        lane_key=lane_key,
        status=status,  # type: ignore[arg-type]
        attention_score=_summary_score(status, attention_count, warning_count, summary_mode),
        attention_count=attention_count,
        attention_label=attention_label,
        secondary_label=secondary_label,
        refresh_at=refresh_at,
        access_available=access_available,
        access_message=access_message,
        warning_count=warning_count,
        summary_mode=summary_mode,  # type: ignore[arg-type]
    )


def _pluralize(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return f"{count} {singular}"
    return f"{count} {plural or singular + 's'}"


def _extra(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("extra") if isinstance(row.get("extra"), dict) else {}


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _days_since(value: str) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() // 86_400))


def _days_until(value: str) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return int((parsed - datetime.now(timezone.utc)).total_seconds() // 86_400)


def _last_successful_utc(user: dict[str, Any]) -> str:
    return str(_extra(user).get("last_successful_utc") or "")


def _has_no_successful_signin(user: dict[str, Any], days: int) -> bool:
    if user.get("enabled") is not True:
        return False
    last_successful = _last_successful_utc(user)
    if not last_successful:
        return True
    parsed = _parse_datetime(last_successful)
    if parsed is None:
        return True
    return parsed <= datetime.now(timezone.utc) - timedelta(days=days)


def _is_guest_user(user: dict[str, Any]) -> bool:
    if str(user.get("object_type") or "").strip() not in {"", "user"}:
        return False
    extra = _extra(user)
    return str(extra.get("user_type") or "") == "Guest" or str(extra.get("account_class") or "") == "guest_external"


def _is_licensed_user(user: dict[str, Any]) -> bool:
    return str(_extra(user).get("is_licensed") or "").strip().lower() == "true"


def _is_on_prem_synced(user: dict[str, Any]) -> bool:
    return str(_extra(user).get("on_prem_sync") or "").strip().lower() == "true"


def _is_shared_or_service(user: dict[str, Any]) -> bool:
    return str(_extra(user).get("account_class") or "") == "shared_or_service"


def _active_directory_user_exception_ids() -> set[str]:
    try:
        return security_finding_exception_store.get_active_entity_ids(_DIRECTORY_USER_EXCEPTION_SCOPE)
    except Exception:
        logger.exception("Failed to load active security finding exceptions for workspace summary")
        return set()


def _security_copilot_summary(status: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("alerts", 4), ("directory", 4)])
    lane_status = "warning" if warning_count else "info"
    secondary_label = (
        "Alert or directory cache context is partially stale."
        if warning_count
        else "Guided investigation across Azure and local sources."
    )
    return _make_lane(
        lane_key="security-copilot",
        status=lane_status,
        attention_count=0,
        attention_label="Ready for investigation",
        secondary_label=secondary_label,
        refresh_at=refresh_at or str(status.get("last_refresh") or ""),
        warning_count=warning_count,
        summary_mode="manual",
        access_message="Open Security Copilot to start guided incident intake.",
    )


def _dlp_review_summary(status: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("directory", 4)])
    lane_status = "warning" if warning_count else "info"
    secondary_label = (
        "Directory cache context is partially stale."
        if warning_count
        else "Paste a finding to start normalized DLP review."
    )
    return _make_lane(
        lane_key="dlp-review",
        status=lane_status,
        attention_count=0,
        attention_label="Ready for pasted findings",
        secondary_label=secondary_label,
        refresh_at=refresh_at or str(status.get("last_refresh") or ""),
        warning_count=warning_count,
        summary_mode="manual",
        access_message="Open DLP Findings Review to normalize a pasted Purview-style finding.",
    )


def _access_review_summary(status: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("inventory", 4), ("directory", 4)])
    users = _principal_record("users")
    groups = _principal_record("groups")
    service_principals = _principal_record("service_principals")
    privileged_assignments = 0
    rollup: dict[str, dict[str, Any]] = {}

    for item in azure_cache._snapshot("role_assignments") or []:
        role_definition_id = str(item.get("role_definition_id") or "").strip()
        role_name = str(item.get("role_name") or "").strip() or _role_name_from_fallback(role_definition_id)
        if not role_name:
            role_name = f"Role {_role_guid(role_definition_id)[:8] or 'unknown'}"
        privilege_level = _classify_privilege(role_name, role_definition_id)
        if privilege_level == "limited":
            continue

        privileged_assignments += 1
        principal_id = str(item.get("principal_id") or "").strip()
        principal_type = str(item.get("principal_type") or "").strip() or "Unknown"
        metadata = _principal_metadata(
            principal_id,
            principal_type,
            users=users,
            groups=groups,
            service_principals=service_principals,
        )
        flags: list[str] = []
        user_type = str(metadata.get("user_type") or "")
        account_class = str(metadata.get("account_class") or "")
        normalized_type = principal_type.lower()
        if normalized_type == "user" and (user_type == "Guest" or account_class == "guest_external"):
            flags.append("Guest user holds privileged Azure RBAC access.")
        if normalized_type == "foreigngroup":
            flags.append("External or foreign group holds privileged Azure RBAC access.")
        if normalized_type == "user" and metadata.get("enabled") is False:
            flags.append("Disabled user still has privileged Azure RBAC access.")
        signin_flag = _privileged_user_signin_flag(metadata.get("enabled"), str(metadata.get("last_successful_utc") or ""))
        if signin_flag:
            flags.append(signin_flag)
        if normalized_type == "serviceprincipal":
            flags.append("Service principal holds privileged Azure RBAC access.")
        if normalized_type in {"group", "foreigngroup"}:
            flags.append("Group-based privileged access needs membership review.")
        if _subscription_scope(str(item.get("scope") or ""), str(item.get("subscription_id") or "")):
            flags.append("Assignment is scoped at the subscription root.")

        current = rollup.setdefault(
            principal_id,
            {
                "highest_privilege": "limited",
                "flags": [],
            },
        )
        current["flags"].extend(flags)
        if privilege_level == "critical" or current["highest_privilege"] != "critical":
            current["highest_privilege"] = privilege_level

    critical_principals = 0
    review_principals = 0
    for item in rollup.values():
        flags = [str(flag).lower() for flag in item["flags"]]
        if flags or str(item["highest_privilege"]) in {"critical", "elevated"}:
            review_principals += 1
        if str(item["highest_privilege"]) == "critical" and (
            flags or any(any(marker in flag for marker in _PRIVILEGE_CRITICAL_FLAG_MARKERS) for flag in flags)
        ):
            critical_principals += 1
        elif any(any(marker in flag for marker in _PRIVILEGE_CRITICAL_FLAG_MARKERS) for flag in flags):
            critical_principals += 1

    if critical_principals:
        lane_status = "critical"
        attention_count = critical_principals
        attention_label = f"{_pluralize(critical_principals, 'critical principal')} need review"
    elif review_principals:
        lane_status = "warning"
        attention_count = review_principals
        attention_label = f"{_pluralize(review_principals, 'privileged principal')} in review scope"
    elif warning_count:
        lane_status = "warning"
        attention_count = 0
        attention_label = "Cache freshness needs attention"
    else:
        lane_status = "healthy"
        attention_count = 0
        attention_label = "No elevated RBAC findings in cache"

    secondary_label = (
        f"{_pluralize(privileged_assignments, 'privileged assignment')} cached across {_pluralize(len(rollup), 'principal')}."
        if privileged_assignments
        else "No elevated RBAC assignments are currently cached."
    )
    return _make_lane(
        lane_key="access-review",
        status=lane_status,
        attention_count=attention_count,
        attention_label=attention_label,
        secondary_label=secondary_label,
        refresh_at=refresh_at,
        warning_count=warning_count,
        summary_mode="count",
    )


def _break_glass_summary(status: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("inventory", 4), ("directory", 4)])
    privileged_assignment_counts = _privileged_assignment_counts()
    matched_accounts = 0
    critical_accounts = 0
    warning_accounts = 0
    privileged_candidates = 0

    for row in azure_cache._snapshot("users") or []:
        display_name = str(row.get("display_name") or "")
        principal_name = str(row.get("principal_name") or row.get("mail") or "")
        if not _break_glass_matches(display_name, principal_name):
            continue

        matched_accounts += 1
        extra = _extra(row)
        user_id = str(row.get("id") or "")
        enabled = row.get("enabled")
        account_class = str(extra.get("account_class") or "")
        on_prem_sync = _bool_from_extra(extra.get("on_prem_sync")) is True
        days_since_last_successful = _days_since(str(extra.get("last_successful_utc") or ""))
        days_since_password_change = _days_since(str(extra.get("last_password_change") or ""))
        privileged_assignment_count = privileged_assignment_counts.get(user_id, 0)
        has_privileged_access = privileged_assignment_count > 0
        if has_privileged_access:
            privileged_candidates += 1
        sign_in_state, _ = _signin_state(enabled, days_since_last_successful)
        candidate_status = _candidate_status(
            enabled=enabled,
            has_privileged_access=has_privileged_access,
            sign_in_state=sign_in_state,
            on_prem_sync=on_prem_sync,
            account_class=account_class,
            days_since_password_change=days_since_password_change,
        )
        if candidate_status == "critical":
            critical_accounts += 1
        elif candidate_status == "warning":
            warning_accounts += 1

    if critical_accounts:
        lane_status = "critical"
        attention_count = critical_accounts
        attention_label = f"{_pluralize(critical_accounts, 'break-glass account')} need validation"
    elif warning_accounts:
        lane_status = "warning"
        attention_count = warning_accounts
        attention_label = f"{_pluralize(warning_accounts, 'break-glass account')} need validation"
    elif warning_count:
        lane_status = "warning"
        attention_count = 0
        attention_label = "Cache freshness needs attention"
    elif matched_accounts:
        lane_status = "healthy"
        attention_count = 0
        attention_label = "Matched break-glass accounts look healthy"
    else:
        lane_status = "info"
        attention_count = 0
        attention_label = "No break-glass candidates matched"

    secondary_label = (
        f"{_pluralize(matched_accounts, 'matched account')}, {_pluralize(privileged_candidates, 'privileged candidate')}."
        if matched_accounts
        else "Naming heuristics did not match any emergency-style accounts."
    )
    return _make_lane(
        lane_key="break-glass-validation",
        status=lane_status,
        attention_count=attention_count,
        attention_label=attention_label,
        secondary_label=secondary_label,
        refresh_at=refresh_at,
        warning_count=warning_count,
        summary_mode="count",
    )


def _identity_review_summary(status: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("directory", 4)])
    groups = azure_cache._snapshot("groups") or []
    app_registrations = azure_cache._snapshot("applications") or []
    directory_roles = azure_cache._snapshot("directory_roles") or []
    flagged_apps = 0
    critical_apps = 0
    collaboration_groups = 0

    for group in groups:
        extra = _extra(group)
        group_types = str(extra.get("group_types") or "")
        if "Unified" in group_types or bool(group.get("mail")):
            collaboration_groups += 1

    for app in app_registrations:
        extra = _extra(app)
        owner_count = _int_value(extra.get("owner_count"))
        owner_gap = owner_count == 0 or bool(extra.get("owner_lookup_error"))
        audience = str(extra.get("sign_in_audience") or "")
        external_audience = bool(audience and audience != "AzureADMyOrg")
        expiry_days = _days_until(str(extra.get("next_credential_expiry") or ""))
        credential_flag = expiry_days is not None and expiry_days <= 30
        if owner_gap or external_audience or credential_flag:
            flagged_apps += 1
        if (expiry_days is not None and expiry_days < 0) or (owner_gap and external_audience):
            critical_apps += 1

    if critical_apps:
        lane_status = "critical"
        attention_count = critical_apps
        attention_label = f"{_pluralize(critical_apps, 'app registration')} need immediate review"
    elif flagged_apps:
        lane_status = "warning"
        attention_count = flagged_apps
        attention_label = f"{_pluralize(flagged_apps, 'app registration')} need review"
    elif warning_count:
        lane_status = "warning"
        attention_count = 0
        attention_label = "Cache freshness needs attention"
    elif app_registrations or groups or directory_roles:
        lane_status = "healthy"
        attention_count = 0
        attention_label = "No identity-review hotspots surfaced"
    else:
        lane_status = "info"
        attention_count = 0
        attention_label = "Identity cache is still warming up"

    secondary_label = (
        f"{_pluralize(collaboration_groups, 'collaboration group')}, {_pluralize(len(directory_roles), 'directory role')} cached."
    )
    return _make_lane(
        lane_key="identity-review",
        status=lane_status,
        attention_count=attention_count,
        attention_label=attention_label,
        secondary_label=secondary_label,
        refresh_at=refresh_at,
        warning_count=warning_count,
        summary_mode="count",
    )


def _directory_role_review_summary(status: dict[str, Any], session: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("directory", 4)])
    access_available = session_can_manage_users(session)
    access_message = (
        "User administration access is required to review direct Entra directory-role memberships on this tenant."
    )
    cached_roles = azure_cache._snapshot("directory_roles") or []

    if not access_available:
        return _make_lane(
            lane_key="directory-role-review",
            status="unavailable",
            attention_count=0,
            attention_label="Access limited",
            secondary_label=f"{_pluralize(len(cached_roles), 'directory role')} cached for later review.",
            refresh_at=refresh_at,
            warning_count=warning_count,
            summary_mode="availability",
            access_available=False,
            access_message=access_message,
        )

    if warning_count:
        lane_status = "warning"
        attention_label = "Live review available with stale cache context"
    elif cached_roles:
        lane_status = "healthy"
        attention_label = "Live review available"
    else:
        lane_status = "info"
        attention_label = "No directory roles cached yet"

    return _make_lane(
        lane_key="directory-role-review",
        status=lane_status,
        attention_count=0,
        attention_label=attention_label,
        secondary_label=f"{_pluralize(len(cached_roles), 'directory role')} cached.",
        refresh_at=refresh_at,
        warning_count=warning_count,
        summary_mode="availability",
        access_message="Live directory-role membership lookup is available when you open the lane.",
    )


def _conditional_access_summary(status: dict[str, Any], session: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("conditional_access", 4)])
    access_available = session_can_manage_users(session)
    access_message = "User administration access is required to review Conditional Access policy drift on this tenant."
    if not access_available:
        return _make_lane(
            lane_key="conditional-access-tracker",
            status="unavailable",
            attention_count=0,
            attention_label="Access limited",
            secondary_label="Conditional Access drift review needs elevated access.",
            refresh_at=refresh_at,
            warning_count=warning_count,
            summary_mode="count",
            access_available=False,
            access_message=access_message,
        )

    policies = azure_cache._snapshot("conditional_access_policies") or []
    changes = azure_cache._snapshot("conditional_access_audit_events") or []
    policy_lookup = {
        str(item.get("id") or ""): item
        for item in policies
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }

    critical_policies = 0
    warning_policies = 0
    for item in policies:
        tags = _policy_risk_tags(item)
        impact = _policy_impact(item, tags)
        if impact == "critical":
            critical_policies += 1
        elif impact == "warning":
            warning_policies += 1

    critical_changes = 0
    warning_changes = 0
    for item in changes:
        impact, _, _ = _change_impact(item, policy_lookup)
        if impact == "critical":
            critical_changes += 1
        elif impact == "warning":
            warning_changes += 1

    critical_total = critical_policies + critical_changes
    warning_total = warning_policies + warning_changes

    if critical_total:
        lane_status = "critical"
        attention_count = critical_total
        attention_label = f"{_pluralize(critical_total, 'critical drift signal')} detected"
    elif warning_total:
        lane_status = "warning"
        attention_count = warning_total
        attention_label = f"{_pluralize(warning_total, 'policy or change')} need review"
    elif warning_count:
        lane_status = "warning"
        attention_count = 0
        attention_label = "Cache freshness needs attention"
    elif policies or changes:
        lane_status = "healthy"
        attention_count = 0
        attention_label = "No broad-scope policy drift surfaced"
    else:
        lane_status = "info"
        attention_count = 0
        attention_label = "Conditional Access cache is still warming up"

    secondary_label = f"{_pluralize(len(policies), 'policy')} and {_pluralize(len(changes), 'recent change')} cached."
    return _make_lane(
        lane_key="conditional-access-tracker",
        status=lane_status,
        attention_count=attention_count,
        attention_label=attention_label,
        secondary_label=secondary_label,
        refresh_at=refresh_at,
        warning_count=warning_count,
        summary_mode="count",
        access_message="Conditional Access drift review is available.",
    )


def _user_review_summary(status: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("directory", 4)])
    exception_ids = _active_directory_user_exception_ids()
    users = [
        user
        for user in (azure_cache._snapshot("users") or [])
        if str(user.get("id") or "").strip() not in exception_ids
    ]
    priority_count = 0
    critical_priority_count = 0
    disabled_licensed_count = 0
    stale_signin_count = 0

    for user in users:
        extra = _extra(user)
        priority_score = _int_value(extra.get("priority_score"))
        priority_band = str(extra.get("priority_band") or "").strip().lower()
        if priority_score >= _PRIORITY_THRESHOLD:
            priority_count += 1
        if priority_score >= _PRIORITY_CRITICAL_THRESHOLD or priority_band == "critical":
            critical_priority_count += 1
        if user.get("enabled") is False and _is_licensed_user(user):
            disabled_licensed_count += 1
        if _has_no_successful_signin(user, 30):
            stale_signin_count += 1

    if critical_priority_count:
        lane_status = "critical"
        attention_count = critical_priority_count
        attention_label = f"{_pluralize(critical_priority_count, 'high-risk user')} surfaced"
    elif priority_count:
        lane_status = "warning"
        attention_count = priority_count
        attention_label = f"{_pluralize(priority_count, 'priority user')} in queue"
    elif warning_count:
        lane_status = "warning"
        attention_count = 0
        attention_label = "Cache freshness needs attention"
    elif users:
        lane_status = "healthy"
        attention_count = 0
        attention_label = "No priority users surfaced"
    else:
        lane_status = "info"
        attention_count = 0
        attention_label = "User cache is still warming up"

    secondary_label = (
        f"{_pluralize(stale_signin_count, 'stale sign-in')} and {_pluralize(disabled_licensed_count, 'disabled licensed account')}."
    )
    return _make_lane(
        lane_key="user-review",
        status=lane_status,
        attention_count=attention_count,
        attention_label=attention_label,
        secondary_label=secondary_label,
        refresh_at=refresh_at,
        warning_count=warning_count,
        summary_mode="count",
    )


def _guest_access_summary(status: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("directory", 4)])
    exception_ids = _active_directory_user_exception_ids()
    users = [
        user
        for user in (azure_cache._snapshot("users") or [])
        if str(user.get("id") or "").strip() not in exception_ids
    ]
    groups = azure_cache._snapshot("groups") or []
    app_registrations = azure_cache._snapshot("applications") or []
    priority_guest_count = 0
    critical_guest_count = 0
    collaboration_groups = 0
    external_audience_apps = 0

    for group in groups:
        extra = _extra(group)
        group_types = str(extra.get("group_types") or "")
        if "Unified" in group_types or bool(group.get("mail")):
            collaboration_groups += 1

    for app in app_registrations:
        audience = str(_extra(app).get("sign_in_audience") or "")
        if audience and audience != "AzureADMyOrg":
            external_audience_apps += 1

    for user in users:
        if not _is_guest_user(user):
            continue
        extra = _extra(user)
        created_days = _days_since(str(extra.get("created_datetime") or ""))
        old_guest = created_days is not None and created_days >= _GUEST_AGE_THRESHOLD_DAYS
        stale_signin = _has_no_successful_signin(user, _GUEST_SIGNIN_THRESHOLD_DAYS)
        disabled_guest = user.get("enabled") is False
        licensed_guest = _is_licensed_user(user)
        if old_guest or stale_signin or disabled_guest or licensed_guest:
            priority_guest_count += 1
        if disabled_guest or licensed_guest:
            critical_guest_count += 1

    if critical_guest_count:
        lane_status = "critical"
        attention_count = critical_guest_count
        attention_label = f"{_pluralize(critical_guest_count, 'guest account')} need immediate review"
    elif priority_guest_count:
        lane_status = "warning"
        attention_count = priority_guest_count
        attention_label = f"{_pluralize(priority_guest_count, 'guest account')} in priority review"
    elif warning_count:
        lane_status = "warning"
        attention_count = 0
        attention_label = "Cache freshness needs attention"
    elif users or groups or app_registrations:
        lane_status = "healthy"
        attention_count = 0
        attention_label = "No priority guest findings surfaced"
    else:
        lane_status = "info"
        attention_count = 0
        attention_label = "Guest access cache is still warming up"

    secondary_label = (
        f"{_pluralize(external_audience_apps, 'external-audience app')} and {_pluralize(collaboration_groups, 'collaboration group')} widen reach."
    )
    return _make_lane(
        lane_key="guest-access-review",
        status=lane_status,
        attention_count=attention_count,
        attention_label=attention_label,
        secondary_label=secondary_label,
        refresh_at=refresh_at,
        warning_count=warning_count,
        summary_mode="count",
    )


def _account_health_summary(status: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("directory", 4)])
    exception_ids = _active_directory_user_exception_ids()
    users = [
        user
        for user in (azure_cache._snapshot("users") or [])
        if str(user.get("id") or "").strip() not in exception_ids
    ]
    issue_user_ids: set[str] = set()
    stale_password_count = 0
    disabled_count = 0
    old_guest_count = 0
    incomplete_count = 0

    for user in users:
        extra = _extra(user)
        user_id = str(user.get("id") or "")
        if user.get("enabled") is False and not _is_shared_or_service(user):
            disabled_count += 1
            issue_user_ids.add(user_id)

        if _is_guest_user(user):
            created_days = _days_since(str(extra.get("created_datetime") or ""))
            if created_days is not None and created_days >= _ACCOUNT_HEALTH_GUEST_THRESHOLD_DAYS:
                old_guest_count += 1
                issue_user_ids.add(user_id)
            continue

        if _is_shared_or_service(user):
            continue

        if user.get("enabled") is True and not _is_on_prem_synced(user):
            password_days = _days_since(str(extra.get("last_password_change") or ""))
            if password_days is not None and password_days >= _ACCOUNT_HEALTH_PASSWORD_THRESHOLD_DAYS:
                stale_password_count += 1
                issue_user_ids.add(user_id)

        if user.get("enabled") is True and (not str(extra.get("department") or "").strip() or not str(extra.get("job_title") or "").strip()):
            incomplete_count += 1
            issue_user_ids.add(user_id)

    if stale_password_count:
        lane_status = "critical"
        attention_count = len(issue_user_ids)
        attention_label = f"{_pluralize(attention_count, 'account')} need hygiene review"
    elif issue_user_ids:
        lane_status = "warning"
        attention_count = len(issue_user_ids)
        attention_label = f"{_pluralize(attention_count, 'account')} need hygiene review"
    elif warning_count:
        lane_status = "warning"
        attention_count = 0
        attention_label = "Cache freshness needs attention"
    elif users:
        lane_status = "healthy"
        attention_count = 0
        attention_label = "No account-health hotspots surfaced"
    else:
        lane_status = "info"
        attention_count = 0
        attention_label = "Account cache is still warming up"

    secondary_label = (
        f"{_pluralize(stale_password_count, 'stale password')}, {_pluralize(disabled_count, 'disabled account')}, "
        f"{_pluralize(old_guest_count, 'old guest')}, {_pluralize(incomplete_count, 'incomplete profile')}."
    )
    return _make_lane(
        lane_key="account-health",
        status=lane_status,
        attention_count=attention_count,
        attention_label=attention_label,
        secondary_label=secondary_label,
        refresh_at=refresh_at,
        warning_count=warning_count,
        summary_mode="count",
    )


def _application_hygiene_summary(status: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("directory", 4)])
    raw_rows = azure_cache._snapshot("application_security") or []
    if not raw_rows:
        raw_rows = _fallback_application_security_rows()

    flagged_apps = 0
    critical_apps = 0
    expired_credentials = 0

    for row in raw_rows:
        owner_names = _owner_names(row)
        owner_lookup_error = str(row.get("owner_lookup_error") or "").strip()
        owner_gap = not owner_names and not owner_lookup_error
        audience = str(row.get("sign_in_audience") or "")
        external_audience = bool(audience and audience != "AzureADMyOrg")

        credentials = row.get("credentials") if isinstance(row.get("credentials"), list) else []
        expired_count = 0
        expiring_soon_count = 0
        if credentials:
            for credential in credentials:
                if not isinstance(credential, dict):
                    continue
                expiry_days = _days_until(str(credential.get("end_date_time") or ""))
                if expiry_days is None:
                    continue
                if expiry_days < 0:
                    expired_count += 1
                elif expiry_days <= _EXPIRING_SOON_DAYS:
                    expiring_soon_count += 1
        else:
            expired_count = _int_value(row.get("expired_credential_count"))
            expiring_soon_count = _int_value(row.get("expiring_30d_count"))
            if expired_count == 0 and expiring_soon_count == 0:
                expiry_days = _days_until(str(row.get("next_credential_expiry") or ""))
                if expiry_days is not None:
                    if expiry_days < 0:
                        expired_count = 1
                    elif expiry_days <= _EXPIRING_SOON_DAYS:
                        expiring_soon_count = 1

        expired_credentials += expired_count
        if expired_count or expiring_soon_count or owner_gap or owner_lookup_error or external_audience:
            flagged_apps += 1
        if expired_count or (owner_gap and external_audience):
            critical_apps += 1

    if critical_apps:
        lane_status = "critical"
        attention_count = critical_apps
        attention_label = f"{_pluralize(critical_apps, 'app registration')} need immediate review"
    elif flagged_apps:
        lane_status = "warning"
        attention_count = flagged_apps
        attention_label = f"{_pluralize(flagged_apps, 'app registration')} need hygiene review"
    elif warning_count:
        lane_status = "warning"
        attention_count = 0
        attention_label = "Cache freshness needs attention"
    elif raw_rows:
        lane_status = "healthy"
        attention_count = 0
        attention_label = "No application hygiene hotspots surfaced"
    else:
        lane_status = "info"
        attention_count = 0
        attention_label = "Application cache is still warming up"

    secondary_label = (
        f"{_pluralize(expired_credentials, 'expired credential')} across {_pluralize(len(raw_rows), 'app registration')}."
    )
    return _make_lane(
        lane_key="app-hygiene",
        status=lane_status,
        attention_count=attention_count,
        attention_label=attention_label,
        secondary_label=secondary_label,
        refresh_at=refresh_at,
        warning_count=warning_count,
        summary_mode="count",
    )


def _device_compliance_summary(status: dict[str, Any], session: dict[str, Any]) -> SecurityWorkspaceLaneSummary:
    warning_count, refresh_at = _dataset_warning_count(status, [("device_compliance", _STALE_DEVICE_HOURS)])
    access_available = session_can_manage_users(session)
    access_message = "User administration access is required to review device posture and run device actions."
    if not access_available:
        return _make_lane(
            lane_key="device-compliance",
            status="unavailable",
            attention_count=0,
            attention_label="Access limited",
            secondary_label="Device posture review needs elevated access.",
            refresh_at=refresh_at,
            warning_count=warning_count,
            summary_mode="count",
            access_available=False,
            access_message=access_message,
        )

    critical_devices = 0
    high_devices = 0
    medium_devices = 0
    action_ready_devices = 0
    rows = azure_cache._snapshot("managed_devices") or []
    for row in rows:
        last_sync_age_days = _days_since(str(row.get("last_sync_date_time") or ""))
        primary_users = _normalize_primary_users(row.get("primary_users"))
        risk, _, _, action_ready, _, _, _, _, _ = _recommendations(
            compliance_state=str(row.get("compliance_state") or ""),
            management_state=str(row.get("management_state") or ""),
            owner_type=str(row.get("owner_type") or ""),
            last_sync_age_days=last_sync_age_days,
            primary_users=primary_users,
        )
        if action_ready:
            action_ready_devices += 1
        if risk == "critical":
            critical_devices += 1
        elif risk == "high":
            high_devices += 1
        elif risk == "medium":
            medium_devices += 1

    review_count = critical_devices or (high_devices + medium_devices)
    if critical_devices:
        lane_status = "critical"
        attention_label = f"{_pluralize(critical_devices, 'device')} need immediate remediation"
    elif high_devices or medium_devices:
        lane_status = "warning"
        attention_label = f"{_pluralize(high_devices + medium_devices, 'device')} need posture review"
    elif warning_count:
        lane_status = "warning"
        attention_label = "Cache freshness needs attention"
    elif rows:
        lane_status = "healthy"
        attention_label = "No urgent device posture hotspots surfaced"
    else:
        lane_status = "info"
        attention_label = "Device compliance cache is still warming up"

    secondary_label = f"{_pluralize(action_ready_devices, 'device')} are action-ready from cached posture."
    return _make_lane(
        lane_key="device-compliance",
        status=lane_status,
        attention_count=review_count,
        attention_label=attention_label,
        secondary_label=secondary_label,
        refresh_at=refresh_at,
        warning_count=warning_count,
        summary_mode="count",
        access_message="Tenant-wide device compliance review is available.",
    )


def build_security_workspace_summary(session: dict[str, Any]) -> SecurityWorkspaceSummaryResponse:
    status = azure_cache.status()
    lanes = [
        _security_copilot_summary(status),
        _dlp_review_summary(status),
        _access_review_summary(status),
        _conditional_access_summary(status, session),
        _break_glass_summary(status),
        _identity_review_summary(status),
        _directory_role_review_summary(status, session),
        _application_hygiene_summary(status),
        _user_review_summary(status),
        _guest_access_summary(status),
        _account_health_summary(status),
        _device_compliance_summary(status, session),
    ]
    return SecurityWorkspaceSummaryResponse(
        generated_at=_utc_now(),
        workspace_last_refresh=str(status.get("last_refresh") or ""),
        lanes=lanes,
    )
