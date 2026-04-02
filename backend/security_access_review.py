"""Azure privileged access review helpers for the Security workspace."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any

from azure_cache import azure_cache
from models import (
    SecurityAccessReviewAssignment,
    SecurityAccessReviewBreakGlassCandidate,
    SecurityAccessReviewMetric,
    SecurityAccessReviewPrincipal,
    SecurityAccessReviewResponse,
)

logger = logging.getLogger(__name__)

_STALE_PRIVILEGED_SIGNIN_DAYS = 30
_STALE_DATA_HOURS = 4
_CRITICAL_ROLE_GUIDS = {
    "8e3af657-a8ff-443c-a75c-2fe8c4bcb635": "Owner",
    "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9": "User Access Administrator",
}
_ELEVATED_ROLE_GUIDS = {
    "b24988ac-6180-42a0-ab88-20f7382dd24c": "Contributor",
}
_LIMITED_ROLE_GUIDS = {
    "acdd72a7-3385-48ef-bd42-f606fba81ae7": "Reader",
}
_BREAK_GLASS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bbreak[\s-]?glass\b", re.IGNORECASE), "Break-glass naming"),
    (re.compile(r"\bemergency\b", re.IGNORECASE), "Emergency naming"),
    (re.compile(r"\btier[\s-]?0\b", re.IGNORECASE), "Tier 0 naming"),
    (re.compile(r"\badmin(?:istrator)?\b", re.IGNORECASE), "Admin naming"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _unique_list(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique.append(text)
    return unique


def _dataset_last_refresh(status: dict[str, Any], dataset_key: str) -> str:
    datasets = status.get("datasets") if isinstance(status.get("datasets"), list) else []
    for dataset in datasets:
        if str(dataset.get("key") or "").strip().lower() == dataset_key.lower():
            return str(dataset.get("last_refresh") or "")
    return ""


def _dataset_is_stale(value: str, *, hours: int = _STALE_DATA_HOURS) -> bool:
    parsed = _parse_datetime(value)
    if parsed is None:
        return True
    return parsed <= datetime.now(timezone.utc) - timedelta(hours=hours)


def _role_guid(role_definition_id: str) -> str:
    text = str(role_definition_id or "").strip().rstrip("/")
    if not text:
        return ""
    return text.rsplit("/", 1)[-1].lower()


def _role_name_from_fallback(role_definition_id: str) -> str:
    guid = _role_guid(role_definition_id)
    return (
        _CRITICAL_ROLE_GUIDS.get(guid)
        or _ELEVATED_ROLE_GUIDS.get(guid)
        or _LIMITED_ROLE_GUIDS.get(guid)
        or ""
    )


def _classify_privilege(role_name: str, role_definition_id: str) -> str:
    guid = _role_guid(role_definition_id)
    if guid in _CRITICAL_ROLE_GUIDS:
        return "critical"
    if guid in _ELEVATED_ROLE_GUIDS:
        return "elevated"
    if guid in _LIMITED_ROLE_GUIDS:
        return "limited"

    lowered = str(role_name or "").strip().lower()
    if not lowered:
        return "limited"
    if "reader" in lowered and not any(term in lowered for term in ("security admin", "security operator")):
        return "limited"
    critical_keywords = (
        "owner",
        "user access administrator",
        "role based access control administrator",
        "security admin",
        "privileged role administrator",
        "key vault administrator",
        "managed hsm administrator",
        "administrator",
        " admin",
    )
    if any(keyword in lowered for keyword in critical_keywords):
        return "critical"
    elevated_keywords = ("contributor", "operator", "developer", "writer", "approver", "editor")
    if any(keyword in lowered for keyword in elevated_keywords):
        return "elevated"
    return "limited"


def _subscription_scope(scope: str, subscription_id: str) -> bool:
    normalized_scope = str(scope or "").strip().rstrip("/").lower()
    normalized_subscription = str(subscription_id or "").strip().lower()
    return bool(normalized_subscription) and normalized_scope == f"/subscriptions/{normalized_subscription}"


def _build_role_name_lookup(assignments: list[dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    lookup: dict[str, str] = {}
    subscription_ids: set[str] = set()
    missing_role_names = False

    for assignment in assignments:
        role_definition_id = str(assignment.get("role_definition_id") or "").strip()
        role_name = str(assignment.get("role_name") or "").strip()
        if role_name:
            lookup[role_definition_id.lower()] = role_name
            lookup[_role_guid(role_definition_id)] = role_name
            continue
        if role_definition_id:
            missing_role_names = True
        subscription_id = str(assignment.get("subscription_id") or "").strip()
        if subscription_id:
            subscription_ids.add(subscription_id)

    warnings: list[str] = []
    if missing_role_names and subscription_ids:
        try:
            definitions = azure_cache._client.list_role_definitions(sorted(subscription_ids))
            for definition in definitions:
                role_id = str(definition.get("id") or "").strip()
                role_name = str(definition.get("role_name") or "").strip()
                role_guid = str(definition.get("role_guid") or _role_guid(role_id)).strip().lower()
                if role_id and role_name:
                    lookup.setdefault(role_id.lower(), role_name)
                if role_guid and role_name:
                    lookup.setdefault(role_guid, role_name)
        except Exception:
            logger.exception("Azure privileged access review could not refresh role definitions")
            warnings.append(
                "Azure RBAC role names could not be refreshed live. Some assignments may show raw role IDs until the next successful lookup."
            )

    unresolved = 0
    for assignment in assignments:
        role_definition_id = str(assignment.get("role_definition_id") or "").strip()
        if not role_definition_id:
            continue
        resolved = lookup.get(role_definition_id.lower()) or lookup.get(_role_guid(role_definition_id)) or _role_name_from_fallback(role_definition_id)
        if resolved:
            lookup.setdefault(role_definition_id.lower(), resolved)
            lookup.setdefault(_role_guid(role_definition_id), resolved)
        else:
            unresolved += 1

    if unresolved:
        warnings.append(
            f"{unresolved} assignment(s) still have unresolved role names. The review keeps those rows but falls back to the raw role definition ID."
        )

    return lookup, warnings


def _principal_record(snapshot_name: str) -> dict[str, dict[str, Any]]:
    rows = azure_cache._snapshot(snapshot_name) or []
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        object_id = str(row.get("id") or "").strip()
        if object_id:
            result[object_id] = row
    return result


def _principal_metadata(
    principal_id: str,
    principal_type: str,
    *,
    users: dict[str, dict[str, Any]],
    groups: dict[str, dict[str, Any]],
    service_principals: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    normalized_type = str(principal_type or "").strip().lower()
    if normalized_type == "user":
        row = users.get(principal_id) or {}
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        return {
            "object_type": "user",
            "display_name": str(row.get("display_name") or row.get("principal_name") or principal_id),
            "principal_name": str(row.get("principal_name") or row.get("mail") or principal_id),
            "enabled": row.get("enabled"),
            "user_type": str(extra.get("user_type") or ""),
            "last_successful_utc": str(extra.get("last_successful_utc") or ""),
            "account_class": str(extra.get("account_class") or ""),
        }
    if normalized_type == "serviceprincipal":
        row = service_principals.get(principal_id) or {}
        return {
            "object_type": "enterprise_app",
            "display_name": str(row.get("display_name") or row.get("app_id") or principal_id),
            "principal_name": str(row.get("app_id") or row.get("principal_name") or principal_id),
            "enabled": row.get("enabled"),
            "user_type": "",
            "last_successful_utc": "",
            "account_class": "",
        }
    if normalized_type in {"group", "foreigngroup"}:
        row = groups.get(principal_id) or {}
        default_name = f"Foreign group {principal_id[:8]}" if normalized_type == "foreigngroup" else principal_id
        return {
            "object_type": "group",
            "display_name": str(row.get("display_name") or row.get("mail") or default_name),
            "principal_name": str(row.get("mail") or row.get("principal_name") or default_name),
            "enabled": row.get("enabled"),
            "user_type": "Foreign group" if normalized_type == "foreigngroup" else "",
            "last_successful_utc": "",
            "account_class": "foreign_group" if normalized_type == "foreigngroup" else "",
        }
    return {
        "object_type": normalized_type or "unknown",
        "display_name": principal_id,
        "principal_name": principal_id,
        "enabled": None,
        "user_type": "",
        "last_successful_utc": "",
        "account_class": "",
    }


def _privileged_user_signin_flag(enabled: bool | None, last_successful_utc: str) -> str:
    if enabled is not True:
        return ""
    last_successful = _parse_datetime(last_successful_utc)
    if last_successful is None:
        return f"No successful sign-in is recorded for this privileged user in the cached directory dataset."
    if last_successful <= datetime.now(timezone.utc) - timedelta(days=_STALE_PRIVILEGED_SIGNIN_DAYS):
        return f"No successful sign-in is recorded in the last {_STALE_PRIVILEGED_SIGNIN_DAYS} days."
    return ""


def _break_glass_matches(display_name: str, principal_name: str) -> list[str]:
    haystack = f"{display_name} {principal_name}".strip()
    matches = [label for pattern, label in _BREAK_GLASS_PATTERNS if pattern.search(haystack)]
    return _unique_list(matches)


def build_security_access_review() -> SecurityAccessReviewResponse:
    status = azure_cache.status()
    inventory_last_refresh = _dataset_last_refresh(status, "inventory")
    directory_last_refresh = _dataset_last_refresh(status, "directory")

    warnings: list[str] = []
    if _dataset_is_stale(inventory_last_refresh):
        warnings.append("Azure inventory cache data is older than 4 hours, so RBAC assignments may be stale.")
    if _dataset_is_stale(directory_last_refresh):
        warnings.append("Azure directory cache data is older than 4 hours, so user posture and sign-in flags may be stale.")

    users = _principal_record("users")
    groups = _principal_record("groups")
    service_principals = _principal_record("service_principals")
    subscriptions = azure_cache._snapshot("subscriptions") or []
    subscription_names = {
        str(item.get("subscription_id") or "").strip(): str(item.get("display_name") or item.get("subscription_id") or "").strip()
        for item in subscriptions
        if str(item.get("subscription_id") or "").strip()
    }
    assignments = azure_cache._snapshot("role_assignments") or []
    role_lookup, role_warnings = _build_role_name_lookup(assignments)
    warnings.extend(role_warnings)

    review_assignments: list[SecurityAccessReviewAssignment] = []
    principal_rollup: dict[str, dict[str, Any]] = {}

    for item in assignments:
        role_definition_id = str(item.get("role_definition_id") or "").strip()
        role_guid = _role_guid(role_definition_id)
        role_name = (
            str(item.get("role_name") or "").strip()
            or role_lookup.get(role_definition_id.lower())
            or role_lookup.get(role_guid)
            or _role_name_from_fallback(role_definition_id)
            or f"Role {role_guid[:8] or 'unknown'}"
        )
        privilege_level = _classify_privilege(role_name, role_definition_id)
        if privilege_level == "limited":
            continue

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
        user_type = metadata["user_type"]
        account_class = str(metadata.get("account_class") or "")
        if str(principal_type).lower() == "user" and (user_type == "Guest" or account_class == "guest_external"):
            flags.append("Guest user holds privileged Azure RBAC access.")
        if str(principal_type).lower() == "foreigngroup":
            flags.append("External or foreign group holds privileged Azure RBAC access.")
        if metadata.get("enabled") is False and str(principal_type).lower() == "user":
            flags.append("Disabled user still has privileged Azure RBAC access.")
        signin_flag = _privileged_user_signin_flag(metadata.get("enabled"), str(metadata.get("last_successful_utc") or ""))
        if signin_flag:
            flags.append(signin_flag)
        if str(principal_type).lower() == "serviceprincipal":
            flags.append("Service principal holds privileged Azure RBAC access.")
        if str(principal_type).lower() in {"group", "foreigngroup"}:
            flags.append("Group-based privileged access needs membership review.")
        if _subscription_scope(str(item.get("scope") or ""), str(item.get("subscription_id") or "")):
            flags.append("Assignment is scoped at the subscription root.")

        assignment = SecurityAccessReviewAssignment(
            assignment_id=str(item.get("id") or ""),
            principal_id=principal_id,
            principal_type=principal_type,
            object_type=str(metadata.get("object_type") or ""),
            display_name=str(metadata.get("display_name") or principal_id),
            principal_name=str(metadata.get("principal_name") or principal_id),
            role_definition_id=role_definition_id,
            role_name=role_name,
            privilege_level=privilege_level,  # type: ignore[arg-type]
            scope=str(item.get("scope") or ""),
            subscription_id=str(item.get("subscription_id") or ""),
            subscription_name=subscription_names.get(str(item.get("subscription_id") or ""), str(item.get("subscription_id") or "")),
            enabled=metadata.get("enabled"),
            user_type=user_type,
            last_successful_utc=str(metadata.get("last_successful_utc") or ""),
            flags=_unique_list(flags),
        )
        review_assignments.append(assignment)

        rollup = principal_rollup.setdefault(
            principal_id,
            {
                "principal_id": principal_id,
                "principal_type": principal_type,
                "object_type": str(metadata.get("object_type") or ""),
                "display_name": str(metadata.get("display_name") or principal_id),
                "principal_name": str(metadata.get("principal_name") or principal_id),
                "enabled": metadata.get("enabled"),
                "user_type": user_type,
                "last_successful_utc": str(metadata.get("last_successful_utc") or ""),
                "role_names": [],
                "subscriptions": [],
                "scopes": [],
                "flags": [],
                "highest_privilege": "limited",
            },
        )
        rollup["role_names"].append(role_name)
        rollup["subscriptions"].append(assignment.subscription_name or assignment.subscription_id)
        rollup["scopes"].append(assignment.scope)
        rollup["flags"].extend(assignment.flags)
        if privilege_level == "critical" or rollup["highest_privilege"] != "critical":
            rollup["highest_privilege"] = privilege_level

    flagged_principals = [
        SecurityAccessReviewPrincipal(
            principal_id=principal_id,
            principal_type=str(item["principal_type"]),
            object_type=str(item["object_type"]),
            display_name=str(item["display_name"]),
            principal_name=str(item["principal_name"]),
            enabled=item["enabled"],
            user_type=str(item["user_type"]),
            last_successful_utc=str(item["last_successful_utc"]),
            role_names=_unique_list(list(item["role_names"])),
            assignment_count=len(list(item["role_names"])),
            scope_count=len(_unique_list(list(item["scopes"]))),
            highest_privilege=str(item["highest_privilege"]),  # type: ignore[arg-type]
            flags=_unique_list(list(item["flags"])),
            subscriptions=_unique_list(list(item["subscriptions"])),
        )
        for principal_id, item in principal_rollup.items()
    ]

    break_glass_candidates: list[SecurityAccessReviewBreakGlassCandidate] = []
    for user_id, row in users.items():
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        display_name = str(row.get("display_name") or "")
        principal_name = str(row.get("principal_name") or row.get("mail") or "")
        matched_terms = _break_glass_matches(display_name, principal_name)
        if not matched_terms:
            continue

        rollup = principal_rollup.get(user_id)
        privileged_assignment_count = len(rollup["role_names"]) if rollup else 0
        has_privileged_access = privileged_assignment_count > 0
        if "Admin naming" in matched_terms and not has_privileged_access and row.get("enabled") is not True:
            continue

        flags: list[str] = []
        if has_privileged_access:
            flags.append("Account currently holds privileged Azure RBAC access.")
        if row.get("enabled") is not True:
            flags.append("Account is disabled.")
        signin_flag = _privileged_user_signin_flag(row.get("enabled"), str(extra.get("last_successful_utc") or ""))
        if signin_flag:
            flags.append(signin_flag)

        break_glass_candidates.append(
            SecurityAccessReviewBreakGlassCandidate(
                user_id=user_id,
                display_name=display_name or principal_name or user_id,
                principal_name=principal_name or user_id,
                enabled=row.get("enabled"),
                last_successful_utc=str(extra.get("last_successful_utc") or ""),
                matched_terms=matched_terms,
                privileged_assignment_count=privileged_assignment_count,
                has_privileged_access=has_privileged_access,
                flags=_unique_list(flags),
            )
        )

    flagged_principals.sort(
        key=lambda item: (
            0 if item.highest_privilege == "critical" else 1,
            -len(item.flags),
            -item.assignment_count,
            item.display_name.lower(),
        )
    )
    review_assignments.sort(
        key=lambda item: (
            0 if item.privilege_level == "critical" else 1,
            -len(item.flags),
            item.display_name.lower(),
            item.role_name.lower(),
        )
    )
    break_glass_candidates.sort(
        key=lambda item: (
            0 if item.has_privileged_access else 1,
            0 if item.enabled is True else 1,
            -item.privileged_assignment_count,
            item.display_name.lower(),
        )
    )

    guest_or_external = [
        item
        for item in flagged_principals
        if item.user_type == "Guest" or item.principal_type.lower() == "foreigngroup"
    ]
    stale_or_disabled_users = [
        item
        for item in flagged_principals
        if item.object_type == "user"
        and any(
            "disabled user" in flag.lower() or "no successful sign-in" in flag.lower()
            for flag in item.flags
        )
    ]
    service_principal_count = len([item for item in flagged_principals if item.object_type == "enterprise_app"])

    metrics = [
        SecurityAccessReviewMetric(
            key="privileged_principals",
            label="Privileged principals",
            value=len(flagged_principals),
            detail="Unique users, groups, and service principals with elevated Azure RBAC assignments in review scope.",
            tone="sky",
        ),
        SecurityAccessReviewMetric(
            key="critical_assignments",
            label="Critical assignments",
            value=len([item for item in review_assignments if item.privilege_level == "critical"]),
            detail="Assignments with Owner, User Access Administrator, or similarly critical control-plane access.",
            tone="rose",
        ),
        SecurityAccessReviewMetric(
            key="guest_or_external",
            label="Guest or external",
            value=len(guest_or_external),
            detail="Guest users or foreign groups that still hold privileged Azure RBAC access.",
            tone="amber",
        ),
        SecurityAccessReviewMetric(
            key="stale_or_disabled_users",
            label="Stale or disabled users",
            value=len(stale_or_disabled_users),
            detail="Privileged user accounts that are disabled or have no recent successful sign-in in the cached directory data.",
            tone="amber",
        ),
        SecurityAccessReviewMetric(
            key="service_principals",
            label="Privileged service principals",
            value=service_principal_count,
            detail="Enterprise applications or service principals with elevated Azure RBAC assignments.",
            tone="slate",
        ),
        SecurityAccessReviewMetric(
            key="break_glass_candidates",
            label="Break-glass candidates",
            value=len(break_glass_candidates),
            detail="Accounts whose naming suggests emergency or administrative usage, prioritized when they also hold privileged Azure RBAC access.",
            tone="emerald",
        ),
    ]

    scope_notes = [
        "This v1 review focuses on Azure RBAC role assignments from the cached inventory dataset.",
        "User freshness, guest status, and break-glass heuristics come from the cached directory dataset.",
        "Direct Entra directory-role memberships and conditional access policy drift are still separate follow-on tools.",
    ]

    return SecurityAccessReviewResponse(
        generated_at=_utc_now(),
        inventory_last_refresh=inventory_last_refresh,
        directory_last_refresh=directory_last_refresh,
        metrics=metrics,
        flagged_principals=flagged_principals,
        assignments=review_assignments,
        break_glass_candidates=break_glass_candidates[:25],
        warnings=_unique_list(warnings),
        scope_notes=scope_notes,
    )
