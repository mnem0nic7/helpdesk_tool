"""Azure break-glass account validation helpers for the Security workspace."""

from __future__ import annotations

from datetime import datetime, timezone

from azure_cache import azure_cache
from models import (
    SecurityAccessReviewMetric,
    SecurityBreakGlassValidationAccount,
    SecurityBreakGlassValidationResponse,
)
from security_access_review import (
    _break_glass_matches,
    _classify_privilege,
    _dataset_is_stale,
    _dataset_last_refresh,
    _parse_datetime,
    _utc_now,
)

_STALE_SIGNIN_DAYS = 90
_STALE_PASSWORD_DAYS = 180
_CRITICAL_PASSWORD_DAYS = 365


def _days_since(value: str) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() // 86_400))


def _bool_from_extra(value: object) -> bool | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _int_from_extra(value: object) -> int:
    try:
        return max(0, int(str(value or "").strip() or "0"))
    except ValueError:
        return 0


def _privileged_assignment_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for assignment in azure_cache._snapshot("role_assignments") or []:
        principal_type = str(assignment.get("principal_type") or "").strip().lower()
        if principal_type != "user":
            continue
        principal_id = str(assignment.get("principal_id") or "").strip()
        if not principal_id:
            continue
        role_definition_id = str(assignment.get("role_definition_id") or "").strip()
        role_name = str(assignment.get("role_name") or "").strip()
        privilege = _classify_privilege(role_name, role_definition_id)
        if privilege == "limited":
            continue
        counts[principal_id] = counts.get(principal_id, 0) + 1
    return counts


def _signin_state(enabled: bool | None, days_since_last_successful: int | None) -> tuple[str, str]:
    if enabled is not True:
        return "disabled", "Account is disabled and cannot be used during an emergency."
    if days_since_last_successful is None:
        return "none", "No successful sign-in is recorded for this account in the cached directory dataset."
    if days_since_last_successful >= _STALE_SIGNIN_DAYS:
        return "stale", f"No successful sign-in is recorded in the last {_STALE_SIGNIN_DAYS} days."
    return "recent", ""


def _password_flag(
    *,
    enabled: bool | None,
    account_class: str,
    days_since_password_change: int | None,
) -> tuple[str, str]:
    if enabled is not True or account_class != "person_cloud" or days_since_password_change is None:
        return "none", ""
    if days_since_password_change >= _CRITICAL_PASSWORD_DAYS:
        return "critical", "Cloud-managed password has not changed in over a year."
    if days_since_password_change >= _STALE_PASSWORD_DAYS:
        return "warning", f"Cloud-managed password has not changed in over {_STALE_PASSWORD_DAYS} days."
    return "healthy", ""


def _candidate_status(
    *,
    enabled: bool | None,
    has_privileged_access: bool,
    sign_in_state: str,
    on_prem_sync: bool,
    account_class: str,
    days_since_password_change: int | None,
) -> str:
    if enabled is not True:
        return "critical"
    if sign_in_state == "none":
        return "critical"
    if has_privileged_access and sign_in_state == "stale":
        return "critical"
    if account_class == "person_cloud" and days_since_password_change is not None and days_since_password_change >= _CRITICAL_PASSWORD_DAYS:
        return "critical"
    if sign_in_state == "stale":
        return "warning"
    if on_prem_sync:
        return "warning"
    if account_class == "shared_or_service":
        return "warning"
    if account_class == "person_cloud" and days_since_password_change is not None and days_since_password_change >= _STALE_PASSWORD_DAYS:
        return "warning"
    return "healthy"


def build_security_break_glass_validation() -> SecurityBreakGlassValidationResponse:
    status = azure_cache.status()
    inventory_last_refresh = _dataset_last_refresh(status, "inventory")
    directory_last_refresh = _dataset_last_refresh(status, "directory")

    warnings: list[str] = []
    if _dataset_is_stale(inventory_last_refresh):
        warnings.append("Azure inventory cache data is older than 4 hours, so privileged-assignment counts may be stale.")
    if _dataset_is_stale(directory_last_refresh):
        warnings.append("Azure directory cache data is older than 4 hours, so sign-in and account-health flags may be stale.")
    warnings.append(
        "MFA registration posture is not cached in this workspace yet, so this lane cannot confirm MFA enrollment or method strength today."
    )

    privileged_assignment_counts = _privileged_assignment_counts()
    accounts: list[SecurityBreakGlassValidationAccount] = []

    for row in azure_cache._snapshot("users") or []:
        display_name = str(row.get("display_name") or "")
        principal_name = str(row.get("principal_name") or row.get("mail") or "")
        matched_terms = _break_glass_matches(display_name, principal_name)
        if not matched_terms:
            continue

        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        enabled = row.get("enabled")
        user_id = str(row.get("id") or "")
        account_class = str(extra.get("account_class") or "")
        on_prem_sync = _bool_from_extra(extra.get("on_prem_sync")) is True
        license_count = _int_from_extra(extra.get("license_count"))
        is_licensed = _bool_from_extra(extra.get("is_licensed"))
        last_successful_utc = str(extra.get("last_successful_utc") or "")
        last_password_change = str(extra.get("last_password_change") or "")
        days_since_last_successful = _days_since(last_successful_utc)
        days_since_password_change = _days_since(last_password_change)
        privileged_assignment_count = privileged_assignment_counts.get(user_id, 0)
        has_privileged_access = privileged_assignment_count > 0
        sign_in_state, sign_in_flag = _signin_state(enabled, days_since_last_successful)
        _, password_flag = _password_flag(
            enabled=enabled,
            account_class=account_class,
            days_since_password_change=days_since_password_change,
        )

        flags: list[str] = []
        if has_privileged_access:
            assignment_label = "assignment" if privileged_assignment_count == 1 else "assignments"
            flags.append(f"Account currently holds {privileged_assignment_count} privileged Azure RBAC {assignment_label}.")
        if sign_in_flag:
            flags.append(sign_in_flag)
        if enabled is not True:
            flags.append("Account is disabled and would not be usable during an emergency.")
        if on_prem_sync:
            flags.append("Account is synced from on-premises AD, so emergency access depends on the source directory.")
        if account_class == "shared_or_service":
            flags.append("Account is classified as shared or service-style, which may not meet named-owner expectations.")
        if password_flag:
            flags.append(password_flag)
        if is_licensed:
            license_label = "license" if license_count == 1 else "licenses"
            flags.append(f"Account still has {license_count} active {license_label} assigned.")

        candidate_status = _candidate_status(
            enabled=enabled,
            has_privileged_access=has_privileged_access,
            sign_in_state=sign_in_state,
            on_prem_sync=on_prem_sync,
            account_class=account_class,
            days_since_password_change=days_since_password_change,
        )

        accounts.append(
            SecurityBreakGlassValidationAccount(
                user_id=user_id,
                display_name=display_name or principal_name or user_id,
                principal_name=principal_name or user_id,
                enabled=enabled,
                user_type=str(extra.get("user_type") or ""),
                account_class=account_class,
                matched_terms=matched_terms,
                has_privileged_access=has_privileged_access,
                privileged_assignment_count=privileged_assignment_count,
                last_successful_utc=last_successful_utc,
                days_since_last_successful=days_since_last_successful,
                last_password_change=last_password_change,
                days_since_password_change=days_since_password_change,
                is_licensed=is_licensed,
                license_count=license_count,
                on_prem_sync=on_prem_sync,
                status=candidate_status,  # type: ignore[arg-type]
                flags=flags,
            )
        )

    accounts.sort(
        key=lambda item: (
            0 if item.status == "critical" else 1 if item.status == "warning" else 2,
            0 if item.has_privileged_access else 1,
            0 if item.enabled is not True else 1,
            0 if item.days_since_last_successful is None else 1,
            -(item.days_since_last_successful or 0),
            item.display_name.lower(),
        ),
        reverse=False,
    )

    validation_due = [item for item in accounts if item.status != "healthy"]
    no_recent_sign_in = [
        item
        for item in accounts
        if item.enabled is True and (item.days_since_last_successful is None or item.days_since_last_successful >= _STALE_SIGNIN_DAYS)
    ]
    stale_passwords = [
        item
        for item in accounts
        if item.enabled is True
        and item.account_class == "person_cloud"
        and item.days_since_password_change is not None
        and item.days_since_password_change >= _STALE_PASSWORD_DAYS
    ]
    on_prem_synced = [item for item in accounts if item.on_prem_sync]

    metrics = [
        SecurityAccessReviewMetric(
            key="matched_accounts",
            label="Matched accounts",
            value=len(accounts),
            detail="Accounts whose naming suggests emergency, break-glass, tier-0, or admin usage.",
            tone="sky",
        ),
        SecurityAccessReviewMetric(
            key="privileged_candidates",
            label="Privileged candidates",
            value=len([item for item in accounts if item.has_privileged_access]),
            detail="Break-glass candidates that currently hold elevated Azure RBAC access and should be validated first.",
            tone="rose",
        ),
        SecurityAccessReviewMetric(
            key="validation_due",
            label="Validation due",
            value=len(validation_due),
            detail="Accounts that are disabled, have stale or missing sign-in evidence, or otherwise need follow-up review.",
            tone="amber",
        ),
        SecurityAccessReviewMetric(
            key="no_recent_sign_in",
            label="No recent sign-in",
            value=len(no_recent_sign_in),
            detail=f"Enabled candidates with no successful sign-in recorded in the last {_STALE_SIGNIN_DAYS} days.",
            tone="amber",
        ),
        SecurityAccessReviewMetric(
            key="stale_passwords",
            label="Stale passwords",
            value=len(stale_passwords),
            detail=f"Cloud-managed candidates whose passwords are {_STALE_PASSWORD_DAYS}+ days old in the cached directory dataset.",
            tone="amber",
        ),
        SecurityAccessReviewMetric(
            key="on_prem_synced",
            label="On-prem synced",
            value=len(on_prem_synced),
            detail="Candidates sourced from on-prem AD that need source-directory validation rather than cloud-only cleanup.",
            tone="violet",
        ),
    ]

    scope_notes = [
        "This lane reuses the same break-glass naming heuristics as the Privileged Access Review lane.",
        "Sign-in freshness, password age, licensing, and sync-source posture come from the cached Azure directory dataset.",
        "Privileged-assignment counts come from the cached Azure RBAC role-assignment snapshot and are meant to guide review priority.",
    ]

    return SecurityBreakGlassValidationResponse(
        generated_at=_utc_now(),
        inventory_last_refresh=inventory_last_refresh,
        directory_last_refresh=directory_last_refresh,
        metrics=metrics,
        accounts=accounts[:50],
        warnings=warnings,
        scope_notes=scope_notes,
    )
