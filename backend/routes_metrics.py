"""API routes for metrics and SLA data."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Query

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
from site_context import get_current_site_scope, get_scoped_issues

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# SLA custom-field IDs
_SLA_FIELD_IDS = [
    "customfield_11266",
    "customfield_11264",
    "customfield_11267",
    "customfield_11268",
]


def _filter_by_date(
    issues: list[dict[str, Any]],
    date_from: Optional[date],
    date_to: Optional[date],
) -> list[dict[str, Any]]:
    """Filter issues by their created date."""
    if not date_from and not date_to:
        return issues
    result = []
    for issue in issues:
        created_str = issue.get("fields", {}).get("created", "")
        if not created_str:
            continue
        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            continue
        if date_from and created < date_from:
            continue
        if date_to and created > date_to:
            continue
        result.append(issue)
    return result


@router.get("/metrics")
async def get_metrics(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> dict[str, Any]:
    """Return all dashboard metrics computed from the full OIT issue set."""
    scope = get_current_site_scope()
    issues = cache.get_all_issues()

    # Parse and apply date range filter
    try:
        df = date.fromisoformat(date_from) if date_from else None
        dt = date.fromisoformat(date_to) if date_to else None
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    issues = _filter_by_date(issues, df, dt)

    # Compute span in days for adaptive chart grouping
    span_days: int | None = None
    if df:
        end = dt or date.today()
        span_days = (end - df).days

    return {
        "headline": compute_headline_metrics(issues, scope=scope),
        "weekly_volumes": compute_weekly_volumes(issues, span_days=span_days, scope=scope),
        "age_buckets": compute_age_buckets(issues, span_days=span_days, scope=scope),
        "ttr_distribution": compute_ttr_distribution(issues, span_days=span_days, scope=scope),
        "priority_counts": compute_priority_counts(issues, scope=scope),
        "assignee_stats": compute_assignee_stats(issues, scope=scope),
    }


@router.get("/sla/summary")
async def get_sla_summary() -> dict[str, Any]:
    """Return SLA timer summaries for all JSM SLA timers."""
    issues = cache.get_all_issues()
    return {"timers": compute_sla_summary(issues, scope=get_current_site_scope())}


@router.get("/sla/breaches")
async def get_sla_breaches() -> dict[str, Any]:
    """Return tickets that have any BREACHED SLA timer."""
    issues = get_scoped_issues()

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
