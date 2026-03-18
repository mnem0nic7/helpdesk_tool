"""Metrics computation helpers for the OIT Helpdesk Dashboard.

All ``compute_*`` functions accept a list of raw Jira issue dicts (as returned
by the REST API) and filter out excluded tickets internally before computing.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from request_type import extract_request_type_id_from_fields, extract_request_type_name_from_fields


# ---------------------------------------------------------------------------
# Status-mapping constants
# ---------------------------------------------------------------------------

ACTIVE_STATUSES: set[str] = {
    "new",
    "open",
    "assigned",
    "in progress",
    "work in progress",
    "investigating",
}

PAUSED_STATUSES: set[str] = {
    "waiting for customer",
    "waiting for support",
    "pending",
    "pending customer",
    "pending vendor",
    "scheduled",
    "on hold",
    "awaiting approval",
    "waiting for approval",
}

TERMINAL_STATUSES: set[str] = {
    "resolved",
    "closed",
    "done",
    "cancelled",
    "declined",
    "canceled",
}

# SLA custom-field IDs used in JSM
_SLA_FIELDS: dict[str, str] = {
    "customfield_11266": "First Response",
    "customfield_11264": "Resolution",
    "customfield_11267": "Close After Resolution",
    "customfield_11268": "Review Normal Change",
}

# Priority display order
_PRIORITY_ORDER: list[str] = ["Highest", "High", "Medium", "Low", "Lowest"]

# Stale threshold in calendar days
_STALE_DAYS: int = 1

# Age-bucket boundaries (upper-bound in calendar days, label)
_AGE_BUCKETS: list[tuple[float, str]] = [
    (2, "0-2d"),
    (7, "3-7d"),
    (14, "8-14d"),
    (30, "15-30d"),
    (float("inf"), "30+d"),
]

# TTR-distribution bucket boundaries (upper-bound in hours, label)
_TTR_BUCKETS: list[tuple[float, str]] = [
    (1, "< 1h"),
    (4, "1-4h"),
    (8, "4-8h"),
    (24, "8-24h"),
    (72, "1-3d"),
    (168, "3-7d"),
    (336, "7-14d"),
    (720, "14-30d"),
    (float("inf"), "30+d"),
]

IssueScope = Literal["primary", "oasisdev", "all"]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def map_status_bucket(status_name: str | None) -> str:
    """Map a Jira status name to *Active*, *Paused*, or *Terminal*.

    Uses exact matching first, then substring-based fuzzy matching.
    Defaults to ``"Active"`` if no match is found (keeps the clock running).
    """
    s = (status_name or "").strip().lower()
    if s in TERMINAL_STATUSES:
        return "Terminal"
    if s in PAUSED_STATUSES:
        return "Paused"
    if s in ACTIVE_STATUSES:
        return "Active"
    # Fuzzy: substring containment in either direction
    for p in PAUSED_STATUSES:
        if p in s or s in p:
            return "Paused"
    for a in ACTIVE_STATUSES:
        if a in s or s in a:
            return "Active"
    return "Active"


def is_excluded(issue: dict[str, Any]) -> bool:
    """Return ``True`` if the issue should be excluded from metrics.

    An issue is excluded when its labels or summary contain *oasisdev*
    (case-insensitive).
    """
    fields = issue.get("fields", {})

    labels: list[str] = fields.get("labels") or []
    for label in labels:
        if "oasisdev" in label.lower():
            return True

    summary: str = fields.get("summary") or ""
    if "oasisdev" in summary.lower():
        return True

    return False


def parse_dt(s: str | None) -> Optional[datetime]:
    """Parse an ISO-8601 datetime string into a timezone-aware ``datetime``.

    Returns ``None`` for empty/null input or unparseable strings.
    """
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def safe_get(d: dict[str, Any], *keys: str, default: Any = "") -> Any:
    """Safely traverse nested dicts, returning *default* on any missing key."""
    current: Any = d
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
        if current is None:
            return default
    return current


def percentile(data: list[float], p: float) -> Optional[float]:
    """Compute the *p*-th percentile (0-100) via linear interpolation.

    Returns ``None`` if *data* is empty.
    """
    if not data:
        return None
    return _percentile_sorted(sorted(data), p)


def _percentile_sorted(s: list[float], p: float) -> Optional[float]:
    """Like ``percentile`` but *s* must already be sorted ascending."""
    if not s:
        return None
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = f + 1
    if c >= len(s):
        return s[f]
    return s[f] + (k - f) * (s[c] - s[f])


def extract_sla_status(sla_field: Any) -> str:
    """Extract a human-readable SLA status from a JSM SLA timer field value.

    Returns one of ``"Met"``, ``"BREACHED"``, ``"Running"``, ``"Paused"``,
    or ``""`` (empty string) when the field is absent / unparseable.
    """
    info = extract_sla_info(sla_field)
    return info["status"]


def extract_sla_info(sla_field: Any) -> dict[str, Any]:
    """Extract rich SLA data from a JSM SLA timer field.

    Returns a dict with:
      - ``status``: "Met", "BREACHED", "Running", "Paused", or ""
      - ``breach_time``: ISO-8601 string of when the SLA breaches/breached, or ""
      - ``remaining_millis``: milliseconds remaining (negative if breached), or None
      - ``elapsed_millis``: milliseconds elapsed on the timer, or None
    """
    empty: dict[str, Any] = {
        "status": "",
        "breach_time": "",
        "remaining_millis": None,
        "elapsed_millis": None,
    }
    if not sla_field or not isinstance(sla_field, dict):
        return empty

    # Check completed cycles first
    completed: list[dict[str, Any]] = sla_field.get("completedCycles") or []
    if completed:
        last = completed[-1]
        status = "BREACHED" if last.get("breached") else "Met"
        breach_time = (last.get("breachTime") or {}).get("iso8601", "")
        elapsed = last.get("elapsedTime", {}).get("millis")
        remaining = last.get("remainingTime", {}).get("millis")
        return {
            "status": status,
            "breach_time": breach_time,
            "remaining_millis": remaining,
            "elapsed_millis": elapsed,
        }

    # Ongoing cycle
    ongoing: dict[str, Any] | None = sla_field.get("ongoingCycle")
    if ongoing:
        if ongoing.get("breached"):
            status = "BREACHED"
        elif ongoing.get("paused"):
            status = "Paused"
        else:
            status = "Running"
        breach_time = (ongoing.get("breachTime") or {}).get("iso8601", "")
        elapsed = (ongoing.get("elapsedTime") or {}).get("millis")
        remaining = (ongoing.get("remainingTime") or {}).get("millis")
        return {
            "status": status,
            "breach_time": breach_time,
            "remaining_millis": remaining,
            "elapsed_millis": elapsed,
        }

    return empty


# ---------------------------------------------------------------------------
# Internal data extraction helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Return the current UTC time (extracted for testability)."""
    return datetime.now(timezone.utc)


def _hours_between(a: datetime | None, b: datetime | None) -> Optional[float]:
    """Return the hours between two datetimes, or ``None``."""
    if a and b:
        delta = (b - a).total_seconds() / 3600.0
        return max(delta, 0.0)
    return None


def _filter_issues(
    issues: list[dict[str, Any]],
    scope: IssueScope = "primary",
) -> tuple[list[dict[str, Any]], int]:
    """Partition issues into (included, excluded_count) for a dashboard scope."""
    included: list[dict[str, Any]] = []
    excluded_count = 0
    for issue in issues:
        excluded = is_excluded(issue)
        if scope == "all":
            included.append(issue)
            continue
        if scope == "oasisdev":
            if excluded:
                included.append(issue)
            continue
        if excluded:
            excluded_count += 1
        else:
            included.append(issue)
    return included, excluded_count


def _extract_status(issue: dict[str, Any]) -> tuple[str, str, str]:
    """Return (status_name, status_category_name, status_bucket)."""
    fields = issue.get("fields", {})
    status_obj = fields.get("status") or {}
    status_name: str = status_obj.get("name", "")
    sc = status_obj.get("statusCategory") or {}
    status_cat: str = sc.get("name", "")
    bucket = "Terminal" if status_cat == "Done" else map_status_bucket(status_name)
    return status_name, status_cat, bucket


def _is_open(issue: dict[str, Any]) -> bool:
    """Return ``True`` if the issue is not in a terminal status."""
    _, _, bucket = _extract_status(issue)
    return bucket != "Terminal"


# ---------------------------------------------------------------------------
# Computation functions
# ---------------------------------------------------------------------------


def compute_headline_metrics(
    issues: list[dict[str, Any]],
    excluded_count: int | None = None,
    scope: IssueScope = "primary",
) -> dict[str, Any]:
    """Compute headline KPIs from raw Jira issues.

    Issues marked as excluded are removed internally so the result matches the
    rest of the metrics module. When *excluded_count* is omitted it is derived
    from the provided issue list, which keeps date-scoped metrics accurate.
    """
    now = _now()
    included, inferred_excluded_count = _filter_issues(issues, scope=scope)
    effective_excluded_count = (
        inferred_excluded_count if excluded_count is None else excluded_count
    )

    open_issues: list[dict[str, Any]] = []
    resolved_issues: list[dict[str, Any]] = []
    ttr_values: list[float] = []
    stale_count = 0

    for iss in included:
        fields = iss.get("fields", {})
        created = parse_dt(fields.get("created"))
        resolved_dt = parse_dt(fields.get("resolutiondate"))
        updated = parse_dt(fields.get("updated"))

        if _is_open(iss):
            open_issues.append(iss)
            # Stale check
            if updated:
                days_since = (now - updated).total_seconds() / 86400.0
                if days_since >= _STALE_DAYS:
                    stale_count += 1
        else:
            resolved_issues.append(iss)
            ttr = _hours_between(created, resolved_dt)
            if ttr is not None:
                ttr_values.append(ttr)

    total = len(included)
    resolution_rate = (len(resolved_issues) / total * 100.0) if total else 0.0

    ttr_sorted = sorted(ttr_values)
    return {
        "total_tickets": total,
        "open_backlog": len(open_issues),
        "resolved": len(resolved_issues),
        "resolution_rate": round(resolution_rate, 2),
        "median_ttr_hours": _round_opt(_percentile_sorted(ttr_sorted, 50)),
        "p90_ttr_hours": _round_opt(_percentile_sorted(ttr_sorted, 90)),
        "p95_ttr_hours": _round_opt(_percentile_sorted(ttr_sorted, 95)),
        "stale_count": stale_count,
        "excluded_count": effective_excluded_count,
    }


def compute_monthly_volumes(
    issues: list[dict[str, Any]],
    scope: IssueScope = "primary",
) -> list[dict[str, Any]]:
    """Compute monthly created/resolved volumes.

    Returns a chronologically sorted list of dicts matching
    :class:`MonthlyVolume` field names.
    """
    included, _ = _filter_issues(issues, scope=scope)

    monthly_created: Counter[str] = Counter()
    monthly_resolved: Counter[str] = Counter()

    for iss in included:
        fields = iss.get("fields", {})
        created = parse_dt(fields.get("created"))
        resolved_dt = parse_dt(fields.get("resolutiondate"))

        if created:
            monthly_created[created.strftime("%Y-%m")] += 1

        if resolved_dt and not _is_open(iss):
            monthly_resolved[resolved_dt.strftime("%Y-%m")] += 1

    all_months = sorted(set(list(monthly_created.keys()) + list(monthly_resolved.keys())))

    result: list[dict[str, Any]] = []
    for m in all_months:
        c = monthly_created.get(m, 0)
        r = monthly_resolved.get(m, 0)
        result.append({
            "month": m,
            "created": c,
            "resolved": r,
            "net_flow": c - r,
        })

    return result


def compute_weekly_volumes(
    issues: list[dict[str, Any]],
    num_weeks: int = 8,
    span_days: int | None = None,
    scope: IssueScope = "primary",
) -> list[dict[str, Any]]:
    """Compute ticket volumes grouped adaptively by time range.

    Grouping adapts to selected date range:
      - ≤14 days → daily
      - ≤90 days → weekly (default)
      - >90 days → monthly

    Returns a chronologically sorted list of dicts with keys:
      ``period`` (date string), ``created``, ``resolved``, ``net_flow``, ``grouping``.
    """
    from datetime import timedelta

    included, _ = _filter_issues(issues, scope=scope)
    now = _now()
    today = now.date()

    # Determine grouping
    if span_days is not None and span_days <= 14:
        grouping = "daily"
        num_periods = max(span_days, 1)
        period_starts = [today - timedelta(days=num_periods - 1 - i) for i in range(num_periods)]
    elif span_days is not None and span_days > 90:
        grouping = "monthly"
        # Build list of month starts covering the span
        period_starts = []
        d = today.replace(day=1)
        months = (span_days // 30) + 1
        for i in range(months - 1, -1, -1):
            m = d.month - i
            y = d.year
            while m <= 0:
                m += 12
                y -= 1
            period_starts.append(d.replace(year=y, month=m, day=1))
    else:
        grouping = "weekly"
        current_monday = today - timedelta(days=today.weekday())
        actual_weeks = (span_days // 7 + 1) if span_days else num_weeks
        actual_weeks = max(actual_weeks, 2)
        period_starts = [current_monday - timedelta(weeks=actual_weeks - 1 - i) for i in range(actual_weeks)]

    # Build period keys
    period_keys = [p.isoformat() for p in period_starts]
    period_created: dict[str, int] = {k: 0 for k in period_keys}
    period_resolved: dict[str, int] = {k: 0 for k in period_keys}

    cutoff = datetime.combine(period_starts[0], datetime.min.time()).replace(
        tzinfo=timezone.utc
    )

    def _bucket_date(d: Any) -> str | None:
        """Map a date to its period key."""
        if grouping == "daily":
            key = d.isoformat()
            return key if key in period_created else None
        elif grouping == "monthly":
            key = d.replace(day=1).isoformat()
            return key if key in period_created else None
        else:  # weekly
            monday = (d - timedelta(days=d.weekday())).isoformat()
            return monday if monday in period_created else None

    for iss in included:
        fields = iss.get("fields", {})
        created = parse_dt(fields.get("created"))
        resolved_dt = parse_dt(fields.get("resolutiondate"))

        if created and created >= cutoff:
            key = _bucket_date(created.date())
            if key:
                period_created[key] += 1

        if resolved_dt and resolved_dt >= cutoff and not _is_open(iss):
            key = _bucket_date(resolved_dt.date())
            if key:
                period_resolved[key] += 1

    result: list[dict[str, Any]] = []
    for pk in period_keys:
        c = period_created[pk]
        r = period_resolved[pk]
        result.append({
            "week": pk,  # keep "week" key for backward compat
            "created": c,
            "resolved": r,
            "net_flow": c - r,
            "grouping": grouping,
        })

    return result


def _age_buckets_for_span(span_days: int | None) -> list[tuple[float, str]]:
    """Return age bucket definitions appropriate for the date range."""
    if span_days is not None and span_days <= 7:
        return [(1, "0-1d"), (2, "1-2d"), (3, "2-3d"), (5, "3-5d"), (float("inf"), "5d+")]
    if span_days is not None and span_days <= 30:
        return [(2, "0-2d"), (7, "3-7d"), (14, "8-14d"), (float("inf"), "14d+")]
    if span_days is not None and span_days <= 90:
        return [(7, "0-7d"), (14, "8-14d"), (30, "15-30d"), (60, "31-60d"), (float("inf"), "60d+")]
    return _AGE_BUCKETS


def compute_age_buckets(
    issues: list[dict[str, Any]],
    span_days: int | None = None,
    scope: IssueScope = "primary",
) -> list[dict[str, Any]]:
    """Compute age-distribution buckets for open tickets.

    Bucket boundaries adapt to the selected date range.
    """
    included, _ = _filter_issues(issues, scope=scope)
    now = _now()
    buckets = _age_buckets_for_span(span_days)

    bucket_counts: dict[str, int] = {label: 0 for _, label in buckets}

    for iss in included:
        if not _is_open(iss):
            continue
        fields = iss.get("fields", {})
        created = parse_dt(fields.get("created"))
        if not created:
            continue
        age_days = (now - created).total_seconds() / 86400.0
        for upper, label in buckets:
            if age_days <= upper:
                bucket_counts[label] += 1
                break

    return [{"bucket": label, "count": bucket_counts[label]} for label in bucket_counts]


def _ttr_buckets_for_span(span_days: int | None) -> list[tuple[float, str]]:
    """Return TTR bucket definitions appropriate for the date range."""
    if span_days is not None and span_days <= 7:
        return [
            (0.5, "<30m"), (1, "30m-1h"), (2, "1-2h"), (4, "2-4h"),
            (8, "4-8h"), (24, "8-24h"), (float("inf"), "24h+"),
        ]
    if span_days is not None and span_days <= 30:
        return [
            (1, "<1h"), (4, "1-4h"), (8, "4-8h"), (24, "8-24h"),
            (72, "1-3d"), (float("inf"), "3d+"),
        ]
    return _TTR_BUCKETS


def compute_ttr_distribution(
    issues: list[dict[str, Any]],
    span_days: int | None = None,
    scope: IssueScope = "primary",
) -> list[dict[str, Any]]:
    """Compute time-to-resolve distribution buckets.

    Bucket boundaries adapt to the selected date range.
    """
    included, _ = _filter_issues(issues, scope=scope)

    ttr_values: list[float] = []
    for iss in included:
        if _is_open(iss):
            continue
        fields = iss.get("fields", {})
        created = parse_dt(fields.get("created"))
        resolved_dt = parse_dt(fields.get("resolutiondate"))
        ttr = _hours_between(created, resolved_dt)
        if ttr is not None:
            ttr_values.append(ttr)

    buckets = _ttr_buckets_for_span(span_days)
    bucket_counts: dict[str, int] = {label: 0 for _, label in buckets}
    for h in ttr_values:
        for upper, label in buckets:
            if h < upper:
                bucket_counts[label] += 1
                break

    total = len(ttr_values) or 1
    cumulative = 0
    result: list[dict[str, Any]] = []
    for label in bucket_counts:
        cnt = bucket_counts[label]
        cumulative += cnt
        result.append({
            "bucket": label,
            "count": cnt,
            "percent": round(cnt / total * 100.0, 1),
            "cumulative_percent": round(cumulative / total * 100.0, 1),
        })

    return result


def compute_priority_counts(
    issues: list[dict[str, Any]],
    scope: IssueScope = "primary",
) -> list[dict[str, Any]]:
    """Compute ticket counts grouped by priority.

    Returns a list of dicts matching :class:`PriorityCount` field names,
    ordered Highest -> Lowest, then any remaining priorities alphabetically.
    """
    included, _ = _filter_issues(issues, scope=scope)

    total_by_priority: Counter[str] = Counter()
    open_by_priority: Counter[str] = Counter()

    for iss in included:
        fields = iss.get("fields", {})
        priority_obj = fields.get("priority") or {}
        pname: str = priority_obj.get("name", "") or ""
        total_by_priority[pname] += 1
        if _is_open(iss):
            open_by_priority[pname] += 1

    # Build ordered list: known priorities first, then extras sorted
    seen: set[str] = set()
    result: list[dict[str, Any]] = []

    for p in _PRIORITY_ORDER:
        if total_by_priority.get(p, 0) > 0:
            result.append({
                "priority": p,
                "total": total_by_priority[p],
                "open": open_by_priority.get(p, 0),
            })
            seen.add(p)

    for p in sorted(total_by_priority.keys()):
        if p not in seen:
            result.append({
                "priority": p or "(None)",
                "total": total_by_priority[p],
                "open": open_by_priority.get(p, 0),
            })

    return result


def compute_assignee_stats(
    issues: list[dict[str, Any]],
    scope: IssueScope = "primary",
) -> list[dict[str, Any]]:
    """Compute per-assignee workload metrics.

    Returns the top 30 assignees by resolved count, as a list of dicts
    matching :class:`AssigneeStats` field names.
    """
    included, _ = _filter_issues(issues, scope=scope)
    now = _now()

    resolved_by: Counter[str] = Counter()
    open_by: Counter[str] = Counter()
    stale_by: Counter[str] = Counter()
    ttr_by: defaultdict[str, list[float]] = defaultdict(list)

    for iss in included:
        fields = iss.get("fields", {})
        assignee_obj = fields.get("assignee") or {}
        aname: str = assignee_obj.get("displayName", "") or "(Unassigned)"
        if not aname:
            aname = "(Unassigned)"

        created = parse_dt(fields.get("created"))
        resolved_dt = parse_dt(fields.get("resolutiondate"))
        updated = parse_dt(fields.get("updated"))

        if _is_open(iss):
            open_by[aname] += 1
            if updated:
                days_since = (now - updated).total_seconds() / 86400.0
                if days_since >= _STALE_DAYS:
                    stale_by[aname] += 1
        else:
            resolved_by[aname] += 1
            ttr = _hours_between(created, resolved_dt)
            if ttr is not None:
                ttr_by[aname].append(ttr)

    # Merge assignee names from both resolved and open
    all_names: set[str] = set(resolved_by.keys()) | set(open_by.keys())
    entries: list[dict[str, Any]] = []
    for name in all_names:
        ttr_list = ttr_by.get(name, [])
        entries.append({
            "name": name,
            "resolved": resolved_by.get(name, 0),
            "open": open_by.get(name, 0),
            "median_ttr": _round_opt(percentile(ttr_list, 50)),
            "p90_ttr": _round_opt(percentile(ttr_list, 90)),
            "stale": stale_by.get(name, 0),
        })

    # Sort by resolved descending, take top 30
    entries.sort(key=lambda e: e["resolved"], reverse=True)
    return entries[:30]


def compute_sla_summary(
    issues: list[dict[str, Any]],
    scope: IssueScope = "primary",
) -> list[dict[str, Any]]:
    """Compute SLA timer summaries for each of the four JSM SLA timers.

    Returns a list of dicts matching :class:`SLATimerSummary` field names.

    SLA custom fields:
    - ``customfield_11266`` -- First Response
    - ``customfield_11264`` -- Resolution
    - ``customfield_11267`` -- Close After Resolution
    - ``customfield_11268`` -- Review Normal Change
    """
    included, _ = _filter_issues(issues, scope=scope)

    result: list[dict[str, Any]] = []

    for field_id, timer_name in _SLA_FIELDS.items():
        total = 0
        met = 0
        breached = 0
        running = 0
        paused = 0

        for iss in included:
            fields = iss.get("fields", {})
            sla_val = fields.get(field_id)
            status = extract_sla_status(sla_val)
            if not status:
                continue
            total += 1
            if status == "Met":
                met += 1
            elif status == "BREACHED":
                breached += 1
            elif status == "Running":
                running += 1
            elif status == "Paused":
                paused += 1

        met_rate = (met / total * 100.0) if total else 0.0
        breach_rate = (breached / total * 100.0) if total else 0.0

        result.append({
            "timer_name": timer_name,
            "total": total,
            "met": met,
            "breached": breached,
            "running": running,
            "paused": paused,
            "met_rate": round(met_rate, 2),
            "breach_rate": round(breach_rate, 2),
        })

    return result


def issue_to_row(
    issue: dict[str, Any],
    *,
    include_comment_meta: bool = True,
    include_description: bool = True,
) -> dict[str, Any]:
    """Convert a raw Jira issue dict into a flat dict matching :class:`TicketRow`.

    This is used to populate the tickets table in the frontend.
    """
    fields = issue.get("fields", {})
    now = _now()

    # Status
    status_obj = fields.get("status") or {}
    status_name: str = status_obj.get("name", "")
    sc = status_obj.get("statusCategory") or {}
    status_cat: str = sc.get("name", "")

    # Issue type
    issuetype_obj = fields.get("issuetype") or {}
    issue_type: str = issuetype_obj.get("name", "")

    # Priority
    priority_obj = fields.get("priority") or {}
    priority_name: str = priority_obj.get("name", "")

    # Resolution
    resolution_obj = fields.get("resolution") or {}
    resolution_name: str = resolution_obj.get("name", "") if isinstance(resolution_obj, dict) else ""

    # Assignee
    assignee_obj = fields.get("assignee") or {}
    assignee_name: str = assignee_obj.get("displayName", "") if isinstance(assignee_obj, dict) else ""
    assignee_id: str = assignee_obj.get("accountId", "") if isinstance(assignee_obj, dict) else ""

    # Reporter
    reporter_obj = fields.get("reporter") or {}
    reporter_name: str = reporter_obj.get("displayName", "") if isinstance(reporter_obj, dict) else ""
    reporter_id: str = reporter_obj.get("accountId", "") if isinstance(reporter_obj, dict) else ""

    # Dates
    created_str: str = fields.get("created") or ""
    updated_str: str = fields.get("updated") or ""
    resolved_str: str = fields.get("resolutiondate") or ""

    created_dt = parse_dt(created_str)
    updated_dt = parse_dt(updated_str)
    resolved_dt = parse_dt(resolved_str)

    # Request type (JSM custom fields)
    request_type = extract_request_type_name_from_fields(fields)
    request_type_id = extract_request_type_id_from_fields(fields)

    # Calendar TTR
    calendar_ttr = _hours_between(created_dt, resolved_dt)

    # Age in days (for open tickets)
    age_days: Optional[float] = None
    if created_dt and _is_open(issue):
        age_days = round((now - created_dt).total_seconds() / 86400.0, 1)

    # Days since last update
    days_since_update: Optional[float] = None
    if updated_dt:
        days_since_update = round((now - updated_dt).total_seconds() / 86400.0, 1)

    # SLA — rich data (status, breach time, remaining)
    sla_fr = extract_sla_info(fields.get("customfield_11266"))
    sla_res = extract_sla_info(fields.get("customfield_11264"))

    # Labels & components
    labels: list[str] = fields.get("labels") or []
    components: list[str] = [
        c.get("name", "") for c in (fields.get("components") or [])
        if isinstance(c, dict)
    ]

    # Work category
    work_category: str = fields.get("customfield_11239") or ""

    # Organizations
    orgs_raw = fields.get("customfield_10700") or []
    organizations: list[str] = [
        o.get("name", "") for o in orgs_raw if isinstance(o, dict)
    ]

    # Attachment count
    attachments = fields.get("attachment") or []
    attachment_count: int = len(attachments) if isinstance(attachments, list) else 0

    row = {
        "key": issue.get("key", ""),
        "summary": fields.get("summary", ""),
        "issue_type": issue_type,
        "status": status_name,
        "status_category": status_cat,
        "priority": priority_name,
        "resolution": resolution_name,
        "assignee": assignee_name,
        "assignee_account_id": assignee_id,
        "reporter": reporter_name,
        "reporter_account_id": reporter_id,
        "created": created_str,
        "updated": updated_str,
        "resolved": resolved_str,
        "request_type": request_type,
        "request_type_id": request_type_id,
        "calendar_ttr_hours": _round_opt(calendar_ttr),
        "age_days": age_days,
        "days_since_update": days_since_update,
        "excluded": is_excluded(issue),
        # SLA first response
        "sla_first_response_status": sla_fr["status"],
        "sla_first_response_breach_time": sla_fr["breach_time"],
        "sla_first_response_remaining_millis": sla_fr["remaining_millis"],
        # SLA resolution
        "sla_resolution_status": sla_res["status"],
        "sla_resolution_breach_time": sla_res["breach_time"],
        "sla_resolution_remaining_millis": sla_res["remaining_millis"],
        # Additional fields
        "labels": labels,
        "components": components,
        "work_category": work_category,
        "organizations": organizations,
        "attachment_count": attachment_count,
    }
    if include_comment_meta:
        row["comment_count"] = _comment_count(fields)
        row["last_comment_date"] = _last_comment_date(fields)
        row["last_comment_author"] = _last_comment_author(fields)
    if include_description:
        row["description"] = _extract_description(fields)
    return row


# ---------------------------------------------------------------------------
# Comment / description helpers
# ---------------------------------------------------------------------------


def _comment_count(fields: dict[str, Any]) -> int:
    comment_obj = fields.get("comment", {})
    if isinstance(comment_obj, dict):
        return comment_obj.get("total", len(comment_obj.get("comments", [])))
    return 0


def _last_comment_date(fields: dict[str, Any]) -> str:
    comment_obj = fields.get("comment", {})
    comments = comment_obj.get("comments", []) if isinstance(comment_obj, dict) else []
    if not comments:
        return ""
    last = comments[-1]
    return last.get("updated") or last.get("created") or ""


def _last_comment_author(fields: dict[str, Any]) -> str:
    comment_obj = fields.get("comment", {})
    comments = comment_obj.get("comments", []) if isinstance(comment_obj, dict) else []
    if not comments:
        return ""
    author = comments[-1].get("author") or {}
    return author.get("displayName", "")


def _extract_description(fields: dict[str, Any], max_len: int = 500) -> str:
    """Extract plain text from ADF or string description."""
    desc = fields.get("description")
    if not desc:
        return ""
    if isinstance(desc, str):
        return desc[:max_len] if max_len else desc
    # ADF format — extract text nodes
    if isinstance(desc, dict):
        texts: list[str] = []
        _walk_adf(desc, texts)
        full = " ".join(texts)
        return full[:max_len] if max_len else full
    return ""


def _all_comments_text(fields: dict[str, Any]) -> str:
    """Extract all comment bodies as plain text with author and date headers."""
    comment_obj = fields.get("comment", {})
    comments = comment_obj.get("comments", []) if isinstance(comment_obj, dict) else []
    if not comments:
        return ""
    parts: list[str] = []
    for c in comments:
        author = (c.get("author") or {}).get("displayName", "Unknown")
        date = c.get("created") or ""
        if date:
            date = date[:19].replace("T", " ")
        body_obj = c.get("body")
        if isinstance(body_obj, str):
            body = body_obj
        elif isinstance(body_obj, dict):
            texts: list[str] = []
            _walk_adf(body_obj, texts)
            body = " ".join(texts)
        else:
            body = ""
        parts.append(f"[{author} | {date}] {body}")
    return "\n---\n".join(parts)


def _walk_adf(node: dict[str, Any], texts: list[str]) -> None:
    """Recursively extract text from Atlassian Document Format."""
    if node.get("type") == "text":
        texts.append(node.get("text", ""))
    for child in node.get("content", []):
        if isinstance(child, dict):
            _walk_adf(child, texts)


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------


def _round_opt(value: Optional[float], ndigits: int = 2) -> Optional[float]:
    """Round a value if not ``None``."""
    if value is None:
        return None
    return round(value, ndigits)
