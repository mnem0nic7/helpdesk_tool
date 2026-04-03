"""Azure conditional access change-tracker helpers for the Security workspace."""

from __future__ import annotations

from typing import Any

from auth import session_can_manage_users
from azure_cache import azure_cache
from models import (
    SecurityAccessReviewMetric,
    SecurityConditionalAccessChange,
    SecurityConditionalAccessPolicy,
    SecurityConditionalAccessTrackerResponse,
)
from security_access_review import _dataset_is_stale, _dataset_last_refresh, _parse_datetime, _utc_now

_BROAD_POLICY_WINDOW_DAYS = 14


def _humanize(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        result.append(" ".join(part.capitalize() for part in text.replace("_", " ").replace("-", " ").split()))
    return result


def _scope_summary(policy: dict[str, Any]) -> str:
    include_users = [str(item) for item in policy.get("include_users") or []]
    include_groups = [str(item) for item in policy.get("include_groups") or []]
    include_roles = [str(item) for item in policy.get("include_roles") or []]
    exclude_count = sum(
        len(policy.get(key) or [])
        for key in ("exclude_users", "exclude_groups", "exclude_roles", "exclude_applications")
    )
    if policy.get("exclude_guests_or_external"):
        exclude_count += 1

    targeted: list[str] = []
    if "All" in include_users:
        targeted.append("All users")
    elif include_roles:
        targeted.append(f"{len(include_roles)} role target(s)")
    elif include_groups:
        targeted.append(f"{len(include_groups)} group target(s)")
    elif include_users:
        targeted.append(f"{len(include_users)} named user(s)")
    if policy.get("include_guests_or_external"):
        targeted.append("Guests / external users")
    if not targeted:
        targeted.append("Scoped identities")
    if exclude_count:
        targeted.append(f"{exclude_count} exception(s)")
    return " - ".join(targeted)


def _application_scope_summary(policy: dict[str, Any]) -> str:
    include_applications = [str(item) for item in policy.get("include_applications") or []]
    include_user_actions = [str(item) for item in policy.get("include_user_actions") or []]
    exclude_applications = [str(item) for item in policy.get("exclude_applications") or []]

    parts: list[str] = []
    if "All" in include_applications:
        parts.append("All cloud apps")
    elif include_applications:
        parts.append(f"{len(include_applications)} app target(s)")
    if include_user_actions:
        parts.append(f"{len(include_user_actions)} user action target(s)")
    if exclude_applications:
        parts.append(f"{len(exclude_applications)} excluded app(s)")
    if not parts:
        parts.append("Scoped app coverage")
    return " - ".join(parts)


def _policy_risk_tags(policy: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    include_users = [str(item) for item in policy.get("include_users") or []]
    include_roles = [str(item) for item in policy.get("include_roles") or []]
    exclude_count = sum(
        len(policy.get(key) or [])
        for key in ("exclude_users", "exclude_groups", "exclude_roles", "exclude_applications")
    )
    if "All" in include_users:
        tags.append("all_users_scope")
    if include_roles:
        tags.append("role_targeted")
    if policy.get("include_guests_or_external"):
        tags.append("guest_or_external_scope")
    if exclude_count or policy.get("exclude_guests_or_external"):
        tags.append("exception_surface")
    if str(policy.get("state") or "").lower() == "reportonly":
        tags.append("report_only")
    if str(policy.get("state") or "").lower() == "disabled":
        tags.append("disabled")
    if policy.get("session_controls"):
        tags.append("session_controls")
    if policy.get("grant_controls") or str(policy.get("authentication_strength") or "").strip():
        tags.append("grant_controls")
    else:
        tags.append("no_grant_controls")
    return tags


def _days_since(value: str) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    from datetime import datetime, timezone

    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() // 86_400))


def _policy_impact(policy: dict[str, Any], tags: list[str]) -> str:
    state = str(policy.get("state") or "").lower()
    broad = "all_users_scope" in tags or "role_targeted" in tags or "guest_or_external_scope" in tags
    if state == "disabled":
        return "info"
    if broad and "no_grant_controls" in tags:
        return "critical"
    if broad and "exception_surface" in tags:
        return "warning"
    if broad:
        return "warning"
    if "session_controls" in tags or "exception_surface" in tags:
        return "warning"
    return "healthy"


def _change_impact(change: dict[str, Any], policy_lookup: dict[str, dict[str, Any]]) -> tuple[str, list[str], str]:
    activity = str(change.get("activity_display_name") or "")
    modified_properties = [str(item) for item in change.get("modified_properties") or []]
    flags: list[str] = []
    summary_parts: list[str] = [activity or "Policy change"]
    policy_name = str(change.get("target_policy_name") or "")
    if policy_name:
        summary_parts.append(f"for {policy_name}")

    initiated_name = str(change.get("initiated_by_display_name") or "")
    if initiated_name:
        summary_parts.append(f"by {initiated_name}")

    impact = "info"
    lowered_activity = activity.lower()
    if "delete" in lowered_activity:
        impact = "critical"
        flags.append("Policy deletion can remove a control path outright.")
    elif "add" in lowered_activity or "create" in lowered_activity:
        impact = "warning"
        flags.append("New policy should be reviewed for tenant-wide scope and control intent.")

    changed_security_controls = {
        "state",
        "conditions",
        "grantcontrols",
        "sessioncontrols",
        "authenticationstrength",
    }
    touched_security_controls = [
        item
        for item in modified_properties
        if item.replace(" ", "").replace("-", "").replace("_", "").lower() in changed_security_controls
    ]
    if touched_security_controls:
        if impact != "critical":
            impact = "warning"
        flags.append("Change touched policy scope or enforcement controls.")

    if str(change.get("initiated_by_type") or "") == "app":
        if impact == "info":
            impact = "warning"
        flags.append("Change was initiated by an application or service principal.")

    policy = policy_lookup.get(str(change.get("target_policy_id") or "")) or {}
    policy_tags = _policy_risk_tags(policy) if policy else []
    if impact != "critical" and ("all_users_scope" in policy_tags or "role_targeted" in policy_tags):
        impact = "warning"
        flags.append("Affected policy appears to be broad in scope.")
    if "exception_surface" in policy_tags:
        flags.append("Affected policy currently has exclusion-based exception surface.")

    changed_days = _days_since(str(change.get("activity_date_time") or ""))
    if impact == "warning" and changed_days is not None and changed_days <= _BROAD_POLICY_WINDOW_DAYS and "all_users_scope" in policy_tags:
        impact = "critical"
        flags.append("Recent change touched a broad-scope policy and should be validated quickly.")

    if str(change.get("result") or "").lower() not in {"success", ""}:
        flags.append(f"Directory audit recorded result: {change.get('result')}.")

    return impact, flags, " ".join(summary_parts)


def build_security_conditional_access_tracker(session: dict[str, Any]) -> SecurityConditionalAccessTrackerResponse:
    status = azure_cache.status()
    conditional_access_last_refresh = _dataset_last_refresh(status, "conditional_access")

    warnings: list[str] = []
    if _dataset_is_stale(conditional_access_last_refresh):
        warnings.append("Conditional Access cache data is older than 4 hours, so recent policy drift may be missing.")

    scope_notes = [
        "This lane tracks cached Microsoft Entra Conditional Access policies and recent directory audit events tagged to policy activity.",
        "Current policy scope and control posture are summarized alongside recent add, update, and delete operations.",
        "This is a drift and review lane only; it does not edit Conditional Access policies from this workspace.",
    ]

    if not session_can_manage_users(session):
        return SecurityConditionalAccessTrackerResponse(
            generated_at=_utc_now(),
            conditional_access_last_refresh=conditional_access_last_refresh,
            access_available=False,
            access_message="User administration access is required to review Conditional Access policy drift on this tenant.",
            metrics=[],
            policies=[],
            changes=[],
            warnings=warnings,
            scope_notes=scope_notes,
        )

    raw_policies = azure_cache._snapshot("conditional_access_policies") or []
    raw_changes = azure_cache._snapshot("conditional_access_audit_events") or []

    policy_lookup: dict[str, dict[str, Any]] = {
        str(item.get("id") or ""): item
        for item in raw_policies
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }

    policies: list[SecurityConditionalAccessPolicy] = []
    for item in raw_policies:
        if not isinstance(item, dict):
            continue
        risk_tags = _policy_risk_tags(item)
        policies.append(
            SecurityConditionalAccessPolicy(
                policy_id=str(item.get("id") or ""),
                display_name=str(item.get("display_name") or item.get("id") or ""),
                state=str(item.get("state") or ""),
                created_date_time=str(item.get("created_date_time") or ""),
                modified_date_time=str(item.get("modified_date_time") or ""),
                user_scope_summary=_scope_summary(item),
                application_scope_summary=_application_scope_summary(item),
                grant_controls=_humanize(
                    [
                        *(item.get("grant_controls") or []),
                        *(item.get("custom_authentication_factors") or []),
                        *(item.get("terms_of_use") or []),
                        str(item.get("authentication_strength") or ""),
                    ]
                ),
                session_controls=_humanize(item.get("session_controls") or []),
                impact_level=_policy_impact(item, risk_tags),  # type: ignore[arg-type]
                risk_tags=risk_tags,
            )
        )

    changes: list[SecurityConditionalAccessChange] = []
    for item in raw_changes:
        if not isinstance(item, dict):
            continue
        impact_level, flags, change_summary = _change_impact(item, policy_lookup)
        changes.append(
            SecurityConditionalAccessChange(
                event_id=str(item.get("id") or ""),
                activity_date_time=str(item.get("activity_date_time") or ""),
                activity_display_name=str(item.get("activity_display_name") or ""),
                result=str(item.get("result") or ""),
                initiated_by_display_name=str(item.get("initiated_by_display_name") or ""),
                initiated_by_principal_name=str(item.get("initiated_by_principal_name") or ""),
                initiated_by_type=str(item.get("initiated_by_type") or "unknown"),  # type: ignore[arg-type]
                target_policy_id=str(item.get("target_policy_id") or ""),
                target_policy_name=str(item.get("target_policy_name") or ""),
                impact_level=impact_level,  # type: ignore[arg-type]
                change_summary=change_summary,
                modified_properties=[str(value) for value in item.get("modified_properties") or []],
                flags=flags,
            )
        )

    policies.sort(
        key=lambda item: (
            0 if item.impact_level == "critical" else 1 if item.impact_level == "warning" else 2 if item.impact_level == "healthy" else 3,
            -(1 if item.state.lower() == "enabled" else 0),
            item.display_name.lower(),
        )
    )
    changes.sort(
        key=lambda item: (
            0 if item.impact_level == "critical" else 1 if item.impact_level == "warning" else 2,
            item.activity_date_time,
        ),
        reverse=True,
    )

    if not policies:
        warnings.append("No Conditional Access policies are cached yet, so current policy posture cannot be reviewed.")
    if not changes:
        warnings.append("No recent Conditional Access change events were found in the cached audit window.")

    metrics = [
        SecurityAccessReviewMetric(
            key="tracked_policies",
            label="Tracked policies",
            value=len(policies),
            detail="Conditional Access policies currently cached for this tenant.",
            tone="sky",
        ),
        SecurityAccessReviewMetric(
            key="broad_enabled_policies",
            label="Broad enabled policies",
            value=len(
                [
                    item
                    for item in policies
                    if item.state.lower() == "enabled"
                    and any(tag in item.risk_tags for tag in ("all_users_scope", "role_targeted", "guest_or_external_scope"))
                ]
            ),
            detail="Enabled policies with broad identity scope that deserve the fastest drift review.",
            tone="rose",
        ),
        SecurityAccessReviewMetric(
            key="recent_changes",
            label="Recent changes",
            value=len(changes),
            detail="Recent Conditional Access change events from the cached directory-audit window.",
            tone="amber",
        ),
        SecurityAccessReviewMetric(
            key="high_impact_changes",
            label="High-impact changes",
            value=len([item for item in changes if item.impact_level == "critical"]),
            detail="Recent changes that touched broad-scope policies or core enforcement controls.",
            tone="violet",
        ),
        SecurityAccessReviewMetric(
            key="exception_surface",
            label="Exception surfaces",
            value=len([item for item in policies if "exception_surface" in item.risk_tags]),
            detail="Policies that currently rely on exclusions and need explicit review.",
            tone="amber",
        ),
    ]

    return SecurityConditionalAccessTrackerResponse(
        generated_at=_utc_now(),
        conditional_access_last_refresh=conditional_access_last_refresh,
        access_available=True,
        access_message="Conditional Access policy drift review is available.",
        metrics=metrics,
        policies=policies,
        changes=changes,
        warnings=warnings,
        scope_notes=scope_notes,
    )
