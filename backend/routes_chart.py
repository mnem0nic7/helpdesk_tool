"""API routes for chart data (grouped and time series)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter

from issue_cache import cache
from metrics import issue_to_row, parse_dt, _is_open, _filter_issues, _hours_between, _now
from models import ChartDataRequest, ChartTimeseriesRequest
from routes_tickets import _match
from site_context import get_current_site_scope, get_scoped_issues

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_matched_rows(
    filters: dict[str, Any],
    include_excluded: bool,
) -> list[dict[str, Any]]:
    """Get issues from cache, apply filters, convert to flat rows."""
    scope = get_current_site_scope()
    issues = get_scoped_issues(
        include_excluded_on_primary=(include_excluded if scope != "primary" else False)
    )
    # Remove false booleans so _match doesn't treat them as active
    for k in ("open_only", "stale_only"):
        if not filters.get(k):
            filters.pop(k, None)
    matched = [iss for iss in issues if _match(iss, **filters)]
    return [issue_to_row(iss) for iss in matched]


def _compute_metric(
    rows: list[dict[str, Any]], metric: str
) -> float:
    """Compute a single metric value for a group of flat rows."""
    if metric == "count":
        return len(rows)
    if metric == "open":
        return sum(1 for r in rows if r.get("status_category", "") != "Done")
    if metric == "resolved":
        return sum(1 for r in rows if r.get("status_category", "") == "Done")
    if metric == "avg_ttr":
        ttrs = [r["calendar_ttr_hours"] for r in rows if r.get("calendar_ttr_hours") is not None]
        return round(statistics.mean(ttrs), 2) if ttrs else 0
    if metric == "median_ttr":
        ttrs = [r["calendar_ttr_hours"] for r in rows if r.get("calendar_ttr_hours") is not None]
        return round(statistics.median(ttrs), 2) if ttrs else 0
    if metric == "avg_age":
        ages = [r["age_days"] for r in rows if r.get("age_days") is not None]
        return round(statistics.mean(ages), 2) if ages else 0
    return len(rows)


# ---------------------------------------------------------------------------
# Grouped endpoint
# ---------------------------------------------------------------------------


@router.post("/chart/data")
async def chart_data(req: ChartDataRequest) -> dict[str, Any]:
    """Return grouped chart data for bar/pie/donut charts."""
    filters = req.filters.model_dump(exclude_none=True)
    rows = _get_matched_rows(filters, req.include_excluded)

    # Group rows by the requested field
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        val = row.get(req.group_by)
        if isinstance(val, list):
            key = ", ".join(val) if val else "(none)"
        elif isinstance(val, bool):
            key = "Yes" if val else "No"
        else:
            key = str(val) if val else "(none)"
        groups[key].append(row)

    # Compute metric for each group
    data = [
        {"label": label, "value": _compute_metric(group_rows, req.metric)}
        for label, group_rows in sorted(groups.items())
    ]

    # Sort by value descending for better chart readability
    data.sort(key=lambda d: d["value"], reverse=True)

    return {"data": data, "group_by": req.group_by, "metric": req.metric}


# ---------------------------------------------------------------------------
# Time series endpoint
# ---------------------------------------------------------------------------


def _compute_weekly_series(issues: list[dict[str, Any]], num_weeks: int = 12) -> list[dict[str, Any]]:
    """Bucket created/resolved by week (Monday start)."""
    now = _now()
    today = now.date()
    current_monday = today - timedelta(days=today.weekday())

    week_starts = [current_monday - timedelta(weeks=i) for i in range(num_weeks - 1, -1, -1)]

    weekly_created: dict[str, int] = {ws.isoformat(): 0 for ws in week_starts}
    weekly_resolved: dict[str, int] = {ws.isoformat(): 0 for ws in week_starts}

    cutoff = datetime.combine(week_starts[0], datetime.min.time()).replace(tzinfo=timezone.utc)

    for iss in issues:
        fields = iss.get("fields", {})
        created = parse_dt(fields.get("created"))
        resolved_dt = parse_dt(fields.get("resolutiondate"))

        if created and created >= cutoff:
            d = created.date()
            monday = (d - timedelta(days=d.weekday())).isoformat()
            if monday in weekly_created:
                weekly_created[monday] += 1

        if resolved_dt and resolved_dt >= cutoff and not _is_open(iss):
            d = resolved_dt.date()
            monday = (d - timedelta(days=d.weekday())).isoformat()
            if monday in weekly_resolved:
                weekly_resolved[monday] += 1

    result = []
    for ws in week_starts:
        key = ws.isoformat()
        c = weekly_created[key]
        r = weekly_resolved[key]
        result.append({"period": key, "created": c, "resolved": r, "net_flow": c - r})

    return result


def _compute_monthly_series(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bucket created/resolved by month across the full dataset."""
    monthly_created: dict[str, int] = defaultdict(int)
    monthly_resolved: dict[str, int] = defaultdict(int)

    for iss in issues:
        fields = iss.get("fields", {})
        created = parse_dt(fields.get("created"))
        resolved_dt = parse_dt(fields.get("resolutiondate"))

        if created:
            monthly_created[created.strftime("%Y-%m")] += 1

        if resolved_dt and not _is_open(iss):
            monthly_resolved[resolved_dt.strftime("%Y-%m")] += 1

    all_months = sorted(set(list(monthly_created.keys()) + list(monthly_resolved.keys())))

    result = []
    for m in all_months:
        c = monthly_created.get(m, 0)
        r = monthly_resolved.get(m, 0)
        result.append({"period": m, "created": c, "resolved": r, "net_flow": c - r})

    return result


@router.post("/chart/timeseries")
async def chart_timeseries(req: ChartTimeseriesRequest) -> dict[str, Any]:
    """Return time series data for line/area charts."""
    # Get raw issues (not rows) for time series — we need fields.created etc.
    scope = get_current_site_scope()
    issues = get_scoped_issues(
        include_excluded_on_primary=(req.include_excluded if scope != "primary" else False)
    )

    # Apply filters
    filters = req.filters.model_dump(exclude_none=True)
    for k in ("open_only", "stale_only"):
        if not filters.get(k):
            filters.pop(k, None)
    matched = [iss for iss in issues if _match(iss, **filters)]

    if req.bucket == "month":
        data = _compute_monthly_series(matched)
    else:
        data = _compute_weekly_series(matched)

    return {"data": data, "bucket": req.bucket}
