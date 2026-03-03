"""API routes for metrics and SLA data."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from issue_cache import cache
from metrics import (
    compute_headline_metrics,
    compute_monthly_volumes,
    compute_weekly_volumes,
    compute_age_buckets,
    compute_ttr_distribution,
    compute_priority_counts,
    compute_assignee_stats,
    compute_sla_summary,
    extract_sla_status,
    issue_to_row,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# SLA custom-field IDs
_SLA_FIELD_IDS = [
    "customfield_11266",
    "customfield_11264",
    "customfield_11267",
    "customfield_11268",
]


@router.get("/metrics")
async def get_metrics() -> dict[str, Any]:
    """Return all dashboard metrics computed from the full OIT issue set."""
    issues = cache.get_filtered_issues()
    excluded_count = cache.issue_count - cache.filtered_count
    return {
        "headline": compute_headline_metrics(issues, excluded_count),
        "weekly_volumes": compute_weekly_volumes(issues),
        "age_buckets": compute_age_buckets(issues),
        "ttr_distribution": compute_ttr_distribution(issues),
        "priority_counts": compute_priority_counts(issues),
        "assignee_stats": compute_assignee_stats(issues),
    }


@router.get("/sla/summary")
async def get_sla_summary() -> dict[str, Any]:
    """Return SLA timer summaries for all JSM SLA timers."""
    issues = cache.get_filtered_issues()
    return {"timers": compute_sla_summary(issues)}


@router.get("/sla/breaches")
async def get_sla_breaches() -> dict[str, Any]:
    """Return tickets that have any BREACHED SLA timer."""
    issues = cache.get_filtered_issues()

    breaches: list[dict[str, Any]] = []
    for issue in issues:
        fields = issue.get("fields", {})
        has_breach = False
        for field_id in _SLA_FIELD_IDS:
            sla_val = fields.get(field_id)
            status = extract_sla_status(sla_val)
            if status == "BREACHED":
                has_breach = True
                break
        if has_breach:
            breaches.append(issue_to_row(issue))

    return {"breaches": breaches}
