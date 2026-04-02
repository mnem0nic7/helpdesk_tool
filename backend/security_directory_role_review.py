"""Azure direct directory-role review helpers for the Security workspace."""

from __future__ import annotations

import logging
from typing import Any

from auth import session_can_manage_users
from azure_cache import azure_cache
from models import (
    SecurityAccessReviewMetric,
    SecurityDirectoryRoleReviewMembership,
    SecurityDirectoryRoleReviewResponse,
    SecurityDirectoryRoleReviewRole,
)
from security_access_review import (
    _classify_privilege,
    _dataset_is_stale,
    _dataset_last_refresh,
    _parse_datetime,
    _utc_now,
)

logger = logging.getLogger(__name__)

_STALE_SIGNIN_DAYS = 30


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


def _days_since(value: str) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    from datetime import datetime, timezone

    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() // 86_400))


def _snapshot_by_id(snapshot_name: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in azure_cache._snapshot(snapshot_name) or []:
        object_id = str(row.get("id") or "").strip()
        if object_id:
            result[object_id] = row
    return result


def _principal_metadata(
    member: dict[str, Any],
    *,
    users: dict[str, dict[str, Any]],
    groups: dict[str, dict[str, Any]],
    service_principals: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    principal_id = str(member.get("id") or "").strip()
    odata_type = str(member.get("@odata.type") or "").strip().lower()
    if odata_type.endswith("user"):
        cached = users.get(principal_id) or {}
        extra = cached.get("extra") if isinstance(cached.get("extra"), dict) else {}
        return {
            "principal_type": "User",
            "object_type": "user",
            "display_name": str(cached.get("display_name") or member.get("displayName") or principal_id),
            "principal_name": str(cached.get("principal_name") or member.get("userPrincipalName") or member.get("mail") or principal_id),
            "enabled": cached.get("enabled") if cached else member.get("accountEnabled"),
            "user_type": str(extra.get("user_type") or member.get("userType") or ""),
            "last_successful_utc": str(extra.get("last_successful_utc") or ""),
        }
    if odata_type.endswith("serviceprincipal"):
        cached = service_principals.get(principal_id) or {}
        return {
            "principal_type": "ServicePrincipal",
            "object_type": "enterprise_app",
            "display_name": str(cached.get("display_name") or member.get("displayName") or principal_id),
            "principal_name": str(cached.get("app_id") or member.get("appId") or principal_id),
            "enabled": cached.get("enabled") if cached else member.get("accountEnabled"),
            "user_type": "",
            "last_successful_utc": "",
        }
    if odata_type.endswith("group"):
        cached = groups.get(principal_id) or {}
        return {
            "principal_type": "Group",
            "object_type": "group",
            "display_name": str(cached.get("display_name") or member.get("displayName") or principal_id),
            "principal_name": str(cached.get("mail") or member.get("mail") or principal_id),
            "enabled": cached.get("enabled") if cached else member.get("securityEnabled"),
            "user_type": "",
            "last_successful_utc": "",
        }
    return {
        "principal_type": odata_type.rsplit(".", 1)[-1] or "DirectoryObject",
        "object_type": "unknown",
        "display_name": str(member.get("displayName") or principal_id),
        "principal_name": str(member.get("userPrincipalName") or member.get("mail") or member.get("appId") or principal_id),
        "enabled": member.get("accountEnabled"),
        "user_type": str(member.get("userType") or ""),
        "last_successful_utc": "",
    }


def _membership_status(membership: SecurityDirectoryRoleReviewMembership) -> str:
    if membership.privilege_level == "critical":
        if membership.object_type == "user" and membership.enabled is not True:
            return "critical"
        if membership.object_type == "user":
            stale_days = _days_since(membership.last_successful_utc)
            if stale_days is None or stale_days >= _STALE_SIGNIN_DAYS:
                return "critical"
        if membership.object_type == "enterprise_app":
            return "critical"
    if membership.object_type == "group":
        return "warning"
    if membership.object_type == "user" and membership.enabled is not True:
        return "warning"
    if membership.object_type == "user":
        stale_days = _days_since(membership.last_successful_utc)
        if stale_days is None or stale_days >= _STALE_SIGNIN_DAYS:
            return "warning"
    if membership.object_type == "enterprise_app":
        return "warning"
    return "healthy"


def build_security_directory_role_review(session: dict[str, Any]) -> SecurityDirectoryRoleReviewResponse:
    status = azure_cache.status()
    directory_last_refresh = _dataset_last_refresh(status, "directory")

    warnings: list[str] = []
    if _dataset_is_stale(directory_last_refresh):
        warnings.append("Azure directory cache data is older than 4 hours, so user posture and sign-in freshness may be stale.")

    scope_notes = [
        "This lane reviews direct Microsoft Entra directory-role memberships with live Graph membership lookup per role.",
        "User freshness and account posture come from the cached Azure directory dataset, while membership itself is fetched live.",
        "Nested group expansion and conditional access policy posture are still separate follow-on tools.",
    ]

    if not session_can_manage_users(session):
        return SecurityDirectoryRoleReviewResponse(
            generated_at=_utc_now(),
            directory_last_refresh=directory_last_refresh,
            access_available=False,
            access_message="User administration access is required to review direct Entra directory-role memberships on this tenant.",
            metrics=[],
            roles=[],
            memberships=[],
            warnings=warnings,
            scope_notes=scope_notes,
        )

    directory_roles = azure_cache._snapshot("directory_roles") or []
    if not directory_roles:
        warnings.append("No directory roles are cached yet, so there is nothing to review.")
        return SecurityDirectoryRoleReviewResponse(
            generated_at=_utc_now(),
            directory_last_refresh=directory_last_refresh,
            access_available=True,
            access_message="Live direct role review is available.",
            metrics=[],
            roles=[],
            memberships=[],
            warnings=warnings,
            scope_notes=scope_notes,
        )

    try:
        members_by_role = azure_cache._client.list_directory_role_members([str(item.get("id") or "") for item in directory_roles])
    except Exception:
        logger.exception("Azure security directory role review failed to load live role memberships")
        warnings.append("Live directory-role membership lookup failed. Try again after Microsoft Graph recovers.")
        return SecurityDirectoryRoleReviewResponse(
            generated_at=_utc_now(),
            directory_last_refresh=directory_last_refresh,
            access_available=True,
            access_message="Live direct role review is available.",
            metrics=[],
            roles=[],
            memberships=[],
            warnings=warnings,
            scope_notes=scope_notes,
        )

    users = _snapshot_by_id("users")
    groups = _snapshot_by_id("groups")
    service_principals = _snapshot_by_id("service_principals")

    roles: list[SecurityDirectoryRoleReviewRole] = []
    memberships: list[SecurityDirectoryRoleReviewMembership] = []

    for role in directory_roles:
        role_id = str(role.get("id") or "").strip()
        role_name = str(role.get("display_name") or "")
        role_description = str((role.get("extra") or {}).get("description") or "")
        privilege_level = _classify_privilege(role_name, role_id)
        lookup = members_by_role.get(role_id) if isinstance(members_by_role.get(role_id), dict) else {}
        member_rows = lookup.get("members") if isinstance(lookup.get("members"), list) else []
        role_flags: list[str] = []
        if str(lookup.get("member_lookup_error") or "").strip():
            role_flags.append(str(lookup.get("member_lookup_error") or "").strip())
        if lookup.get("truncated"):
            role_flags.append("Membership list was truncated to the first 100 results.")

        role_memberships: list[SecurityDirectoryRoleReviewMembership] = []
        for member in member_rows:
            if not isinstance(member, dict):
                continue
            principal_id = str(member.get("id") or "").strip()
            if not principal_id:
                continue
            metadata = _principal_metadata(member, users=users, groups=groups, service_principals=service_principals)
            flags: list[str] = []
            if metadata["object_type"] == "user" and metadata["enabled"] is not True:
                flags.append("Direct directory role is assigned to a disabled user.")
            if metadata["object_type"] == "user":
                stale_days = _days_since(str(metadata.get("last_successful_utc") or ""))
                if stale_days is None:
                    flags.append("No successful sign-in is recorded for this user in the cached directory dataset.")
                elif stale_days >= _STALE_SIGNIN_DAYS:
                    flags.append(f"No successful sign-in is recorded in the last {_STALE_SIGNIN_DAYS} days.")
                if str(metadata.get("user_type") or "") == "Guest":
                    flags.append("Guest user holds a direct Entra directory role.")
            if metadata["object_type"] == "group":
                flags.append("Group-based direct directory role membership needs separate member review.")
            if metadata["object_type"] == "enterprise_app":
                flags.append("Service principal holds a direct Entra directory role.")

            membership = SecurityDirectoryRoleReviewMembership(
                role_id=role_id,
                role_name=role_name or role_id,
                role_description=role_description,
                privilege_level=privilege_level,  # type: ignore[arg-type]
                principal_id=principal_id,
                principal_type=str(metadata.get("principal_type") or ""),
                object_type=str(metadata.get("object_type") or ""),
                display_name=str(metadata.get("display_name") or principal_id),
                principal_name=str(metadata.get("principal_name") or principal_id),
                enabled=metadata.get("enabled"),
                user_type=str(metadata.get("user_type") or ""),
                last_successful_utc=str(metadata.get("last_successful_utc") or ""),
                assignment_type="direct",
                status="healthy",
                flags=_unique_list(flags),
            )
            membership.status = _membership_status(membership)  # type: ignore[assignment]
            role_memberships.append(membership)
            memberships.append(membership)

        roles.append(
            SecurityDirectoryRoleReviewRole(
                role_id=role_id,
                display_name=role_name or role_id,
                description=role_description,
                privilege_level=privilege_level,  # type: ignore[arg-type]
                member_count=len(role_memberships),
                flagged_member_count=len([item for item in role_memberships if item.status != "healthy" or item.flags]),
                flags=_unique_list(role_flags),
            )
        )

    roles.sort(
        key=lambda item: (
            0 if item.privilege_level == "critical" else 1 if item.privilege_level == "elevated" else 2,
            -item.flagged_member_count,
            -item.member_count,
            item.display_name.lower(),
        )
    )
    memberships.sort(
        key=lambda item: (
            0 if item.status == "critical" else 1 if item.status == "warning" else 2,
            0 if item.privilege_level == "critical" else 1 if item.privilege_level == "elevated" else 2,
            item.role_name.lower(),
            item.display_name.lower(),
        )
    )

    metrics = [
        SecurityAccessReviewMetric(
            key="roles_with_members",
            label="Roles with direct members",
            value=len([item for item in roles if item.member_count > 0]),
            detail="Directory roles that currently have one or more direct members.",
            tone="sky",
        ),
        SecurityAccessReviewMetric(
            key="critical_memberships",
            label="Critical memberships",
            value=len([item for item in memberships if item.privilege_level == "critical"]),
            detail="Direct memberships in highly privileged Entra roles such as global or privileged administrators.",
            tone="rose",
        ),
        SecurityAccessReviewMetric(
            key="flagged_memberships",
            label="Flagged memberships",
            value=len([item for item in memberships if item.status != "healthy" or item.flags]),
            detail="Direct memberships needing follow-up because of stale sign-in, disabled state, guest status, or principal type.",
            tone="amber",
        ),
        SecurityAccessReviewMetric(
            key="guest_memberships",
            label="Guest memberships",
            value=len([item for item in memberships if item.user_type == "Guest"]),
            detail="Guest users that hold a direct Entra directory role.",
            tone="amber",
        ),
        SecurityAccessReviewMetric(
            key="service_principal_memberships",
            label="Service principal memberships",
            value=len([item for item in memberships if item.object_type == "enterprise_app"]),
            detail="Service principals or enterprise apps with direct Entra directory-role membership.",
            tone="violet",
        ),
        SecurityAccessReviewMetric(
            key="group_memberships",
            label="Group memberships",
            value=len([item for item in memberships if item.object_type == "group"]),
            detail="Groups with direct Entra directory-role membership that need separate member expansion review.",
            tone="slate",
        ),
    ]

    for role in roles:
        if role.flags:
            warnings.extend(role.flags)

    return SecurityDirectoryRoleReviewResponse(
        generated_at=_utc_now(),
        directory_last_refresh=directory_last_refresh,
        access_available=True,
        access_message="Live direct role review is available.",
        metrics=metrics,
        roles=roles,
        memberships=memberships[:200],
        warnings=_unique_list(warnings),
        scope_notes=scope_notes,
    )
