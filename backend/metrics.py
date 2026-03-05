"""Metrics computation helpers for the OIT Helpdesk Dashboard.

All ``compute_*`` functions accept a list of raw Jira issue dicts (as returned
by the REST API) and filter out excluded tickets internally before computing.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Optional


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
_STALE_DAYS: int = 7

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
    s = sorted(data)
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


def _filter_issues(issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Partition *issues* into (included, excluded_count)."""
    included: list[dict[str, Any]] = []
    excluded_count = 0
    for issue in issues:
        if is_excluded(issue):
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
    bucket = map_status_bucket(status_name)
    return status_name, status_cat, bucket


def _is_open(issue: dict[str, Any]) -> bool:
    """Return ``True`` if the issue is not in a terminal status."""
    _, _, bucket = _extract_status(issue)
    return bucket != "Terminal"


# ---------------------------------------------------------------------------
# Computation functions
# ---------------------------------------------------------------------------


def compute_headline_metrics(
    issues: list[dict[str, Any]], excluded_count: int = 0
) -> dict[str, Any]:
    """Compute headline KPIs from pre-filtered Jira issues.

    *excluded_count* should be passed by the caller (from the cache)
    since the issues list is already filtered.
    """
    now = _now()

    open_issues: list[dict[str, Any]] = []
    resolved_issues: list[dict[str, Any]] = []
    ttr_values: list[float] = []
    stale_count = 0

    for iss in issues:
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

    total = len(issues)
    resolution_rate = (len(resolved_issues) / total * 100.0) if total else 0.0

    return {
        "total_tickets": total,
        "open_backlog": len(open_issues),
        "resolved": len(resolved_issues),
        "resolution_rate": round(resolution_rate, 2),
        "median_ttr_hours": _round_opt(percentile(ttr_values, 50)),
        "p90_ttr_hours": _round_opt(percentile(ttr_values, 90)),
        "p95_ttr_hours": _round_opt(percentile(ttr_values, 95)),
        "stale_count": stale_count,
        "excluded_count": excluded_count,
    }


def compute_monthly_volumes(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute monthly created/resolved volumes.

    Returns a chronologically sorted list of dicts matching
    :class:`MonthlyVolume` field names.
    """
    included, _ = _filter_issues(issues)

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
    issues: list[dict[str, Any]], num_weeks: int = 8
) -> list[dict[str, Any]]:
    """Compute weekly created/resolved volumes for the last *num_weeks* weeks.

    Each week starts on Monday. Returns a chronologically sorted list of dicts
    with keys ``week`` (Monday date as ``YYYY-MM-DD``), ``created``,
    ``resolved``, and ``net_flow``.
    """
    from datetime import timedelta

    included, _ = _filter_issues(issues)
    now = _now()

    # Find the Monday of the current week
    today = now.date()
    current_monday = today - timedelta(days=today.weekday())

    # Build the list of week-start Mondays (oldest first)
    week_starts: list[Any] = []
    for i in range(num_weeks - 1, -1, -1):
        week_starts.append(current_monday - timedelta(weeks=i))

    # Initialise counters
    weekly_created: dict[str, int] = {ws.isoformat(): 0 for ws in week_starts}
    weekly_resolved: dict[str, int] = {ws.isoformat(): 0 for ws in week_starts}

    # Cutoff: beginning of the earliest week
    cutoff = datetime.combine(week_starts[0], datetime.min.time()).replace(
        tzinfo=timezone.utc
    )

    for iss in included:
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

    result: list[dict[str, Any]] = []
    for ws in week_starts:
        key = ws.isoformat()
        c = weekly_created[key]
        r = weekly_resolved[key]
        result.append({
            "week": key,
            "created": c,
            "resolved": r,
            "net_flow": c - r,
        })

    return result


def compute_age_buckets(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute age-distribution buckets for open tickets.

    Returns a list of dicts matching :class:`AgeBucket` field names.
    """
    included, _ = _filter_issues(issues)
    now = _now()

    # Initialise buckets preserving order
    bucket_counts: dict[str, int] = {label: 0 for _, label in _AGE_BUCKETS}

    open_count = 0
    for iss in included:
        if not _is_open(iss):
            continue
        open_count += 1
        fields = iss.get("fields", {})
        created = parse_dt(fields.get("created"))
        if not created:
            continue
        age_days = (now - created).total_seconds() / 86400.0
        for upper, label in _AGE_BUCKETS:
            if age_days <= upper:
                bucket_counts[label] += 1
                break

    result: list[dict[str, Any]] = []
    for label in bucket_counts:
        result.append({
            "bucket": label,
            "count": bucket_counts[label],
        })

    return result


def compute_ttr_distribution(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute time-to-resolve distribution buckets.

    Returns a list of dicts matching :class:`TTRBucket` field names.
    """
    included, _ = _filter_issues(issues)

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

    # Initialise buckets preserving order
    bucket_counts: dict[str, int] = {label: 0 for _, label in _TTR_BUCKETS}
    for h in ttr_values:
        for upper, label in _TTR_BUCKETS:
            if h < upper:
                bucket_counts[label] += 1
                break

    total = len(ttr_values) or 1  # avoid division by zero
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


def compute_priority_counts(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute ticket counts grouped by priority.

    Returns a list of dicts matching :class:`PriorityCount` field names,
    ordered Highest -> Lowest, then any remaining priorities alphabetically.
    """
    included, _ = _filter_issues(issues)

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


def compute_assignee_stats(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute per-assignee workload metrics.

    Returns the top 30 assignees by resolved count, as a list of dicts
    matching :class:`AssigneeStats` field names.
    """
    included, _ = _filter_issues(issues)
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


def compute_sla_summary(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute SLA timer summaries for each of the four JSM SLA timers.

    Returns a list of dicts matching :class:`SLATimerSummary` field names.

    SLA custom fields:
    - ``customfield_11266`` -- First Response
    - ``customfield_11264`` -- Resolution
    - ``customfield_11267`` -- Close After Resolution
    - ``customfield_11268`` -- Review Normal Change
    """
    included, _ = _filter_issues(issues)

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


def issue_to_row(issue: dict[str, Any]) -> dict[str, Any]:
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

    # Dates
    created_str: str = fields.get("created") or ""
    updated_str: str = fields.get("updated") or ""
    resolved_str: str = fields.get("resolutiondate") or ""

    created_dt = parse_dt(created_str)
    updated_dt = parse_dt(updated_str)
    resolved_dt = parse_dt(resolved_str)

    # Request type (JSM customfield_10010)
    request_type = ""
    crf = fields.get("customfield_10010")
    if crf and isinstance(crf, dict):
        rt_obj = crf.get("requestType")
        if isinstance(rt_obj, dict):
            request_type = rt_obj.get("name", "")

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

    return {
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
        "created": created_str,
        "updated": updated_str,
        "resolved": resolved_str,
        "request_type": request_type,
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


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------


def _round_opt(value: Optional[float], ndigits: int = 2) -> Optional[float]:
    """Round a value if not ``None``."""
    if value is None:
        return None
    return round(value, ndigits)
