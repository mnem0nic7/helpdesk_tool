"""Custom SLA configuration, business hours calculation, and SLA computation."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from config import DATA_DIR
from request_type import extract_request_type_name_from_fields
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SLA Configuration Store
# ---------------------------------------------------------------------------

class SLAConfig:
    """SQLite-backed store for SLA targets and business hours settings."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "sla_config.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path, row_factory=None)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sla_targets ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "sla_type TEXT NOT NULL, "
                "dimension TEXT NOT NULL DEFAULT 'default', "
                "dimension_value TEXT NOT NULL DEFAULT '*', "
                "target_minutes INTEGER NOT NULL, "
                "UNIQUE(sla_type, dimension, dimension_value))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sla_settings ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            # Seed defaults if empty
            if conn.execute("SELECT COUNT(*) FROM sla_targets").fetchone()[0] == 0:
                conn.executemany(
                    "INSERT INTO sla_targets (sla_type, dimension, dimension_value, target_minutes) "
                    "VALUES (?, ?, ?, ?)",
                    [
                        ("first_response", "default", "*", 120),   # 2 hours
                        ("resolution", "default", "*", 540),       # 1 business day (9h)
                    ],
                )
            if conn.execute("SELECT COUNT(*) FROM sla_settings").fetchone()[0] == 0:
                defaults = {
                    "business_hours_start": "08:00",
                    "business_hours_end": "20:00",
                    "business_timezone": "America/New_York",
                    "business_days": "0,1,2,3,4",
                    "integration_reporters": "OSIJIRAOCC",
                }
                conn.executemany(
                    "INSERT INTO sla_settings (key, value) VALUES (?, ?)",
                    list(defaults.items()),
                )
            # Migrate: add integration_reporters if missing
            existing_keys = {r[0] for r in conn.execute("SELECT key FROM sla_settings").fetchall()}
            if "integration_reporters" not in existing_keys:
                conn.execute(
                    "INSERT INTO sla_settings (key, value) VALUES (?, ?)",
                    ("integration_reporters", "OSIJIRAOCC"),
                )

    # -- Targets --

    def get_targets(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, sla_type, dimension, dimension_value, target_minutes "
                "FROM sla_targets ORDER BY sla_type, dimension, dimension_value"
            ).fetchall()
        return [
            {"id": r[0], "sla_type": r[1], "dimension": r[2],
             "dimension_value": r[3], "target_minutes": r[4]}
            for r in rows
        ]

    def set_target(self, sla_type: str, dimension: str,
                   dimension_value: str, target_minutes: int) -> dict[str, Any]:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sla_targets (sla_type, dimension, dimension_value, target_minutes) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(sla_type, dimension, dimension_value) "
                "DO UPDATE SET target_minutes = excluded.target_minutes",
                (sla_type, dimension, dimension_value, target_minutes),
            )
            row = conn.execute(
                "SELECT id, sla_type, dimension, dimension_value, target_minutes "
                "FROM sla_targets WHERE sla_type=? AND dimension=? AND dimension_value=?",
                (sla_type, dimension, dimension_value),
            ).fetchone()
        return {"id": row[0], "sla_type": row[1], "dimension": row[2],
                "dimension_value": row[3], "target_minutes": row[4]}

    def delete_target(self, target_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM sla_targets WHERE id = ?", (target_id,))
        return cur.rowcount > 0

    def get_target_for_ticket(self, sla_type: str, priority: str,
                              request_type: str) -> int:
        """Look up target minutes: priority-specific > request_type-specific > default."""
        targets = self.get_targets()
        by_key: dict[tuple[str, str], int] = {}
        for t in targets:
            if t["sla_type"] == sla_type:
                by_key[(t["dimension"], t["dimension_value"])] = t["target_minutes"]

        if priority and ("priority", priority) in by_key:
            return by_key[("priority", priority)]
        if request_type and ("request_type", request_type) in by_key:
            return by_key[("request_type", request_type)]
        return by_key.get(("default", "*"), 120)

    # -- Settings --

    def get_settings(self) -> dict[str, str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM sla_settings").fetchall()
        return {r[0]: r[1] for r in rows}

    def update_settings(self, settings: dict[str, str]) -> dict[str, str]:
        with self._conn() as conn:
            for key, value in settings.items():
                conn.execute(
                    "INSERT INTO sla_settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
        return self.get_settings()


# Module-level singleton
sla_config = SLAConfig()


# ---------------------------------------------------------------------------
# Business hours calculation
# ---------------------------------------------------------------------------

def _parse_time(s: str) -> tuple[int, int]:
    """Parse 'HH:MM' string into (hour, minute) tuple."""
    parts = s.split(":")
    return int(parts[0]), int(parts[1])


@dataclass(frozen=True)
class _BusinessHoursContext:
    tz: ZoneInfo
    bh_start_h: int
    bh_start_m: int
    bh_end_h: int
    bh_end_m: int
    working_days: frozenset[int]


def _compile_business_hours(settings: dict[str, str]) -> _BusinessHoursContext:
    bh_start_h, bh_start_m = _parse_time(settings.get("business_hours_start", "08:00"))
    bh_end_h, bh_end_m = _parse_time(settings.get("business_hours_end", "20:00"))
    working_days = frozenset(
        int(d) for d in settings.get("business_days", "0,1,2,3,4").split(",") if d
    )
    return _BusinessHoursContext(
        tz=ZoneInfo(settings.get("business_timezone", "America/New_York")),
        bh_start_h=bh_start_h,
        bh_start_m=bh_start_m,
        bh_end_h=bh_end_h,
        bh_end_m=bh_end_m,
        working_days=working_days,
    )


def _business_minutes_between_compiled(
    start: datetime,
    end: datetime,
    context: _BusinessHoursContext,
) -> float:
    """Count business minutes using a precompiled business-hours context."""
    start_local = start.astimezone(context.tz)
    end_local = end.astimezone(context.tz)

    if start_local >= end_local:
        return 0.0

    total_minutes = 0.0
    current_date = start_local.date()
    end_date = end_local.date()

    while current_date <= end_date:
        if current_date.weekday() in context.working_days:
            day_bh_start = datetime(
                current_date.year,
                current_date.month,
                current_date.day,
                context.bh_start_h,
                context.bh_start_m,
                tzinfo=context.tz,
            )
            day_bh_end = datetime(
                current_date.year,
                current_date.month,
                current_date.day,
                context.bh_end_h,
                context.bh_end_m,
                tzinfo=context.tz,
            )
            overlap_start = max(start_local, day_bh_start)
            overlap_end = min(end_local, day_bh_end)
            if overlap_start < overlap_end:
                total_minutes += (overlap_end - overlap_start).total_seconds() / 60.0
        current_date += timedelta(days=1)

    return total_minutes


def business_minutes_between(
    start: datetime, end: datetime, settings: dict[str, str],
) -> float:
    """Count business minutes between two timezone-aware datetimes."""
    return _business_minutes_between_compiled(start, end, _compile_business_hours(settings))


# ---------------------------------------------------------------------------
# DateTime parsing
# ---------------------------------------------------------------------------

def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s = s.replace("+0000", "+00:00").replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _build_target_lookup(targets: list[dict[str, Any]]) -> dict[str, dict[tuple[str, str], int]]:
    lookup: dict[str, dict[tuple[str, str], int]] = {
        "first_response": {},
        "resolution": {},
    }
    for target in targets:
        sla_type = target["sla_type"]
        lookup.setdefault(sla_type, {})[
            (target["dimension"], target["dimension_value"])
        ] = target["target_minutes"]
    return lookup


def _get_target_from_lookup(
    lookup: dict[str, dict[tuple[str, str], int]],
    sla_type: str,
    priority: str,
    request_type: str,
) -> int:
    sla_targets = lookup.get(sla_type, {})
    if priority and ("priority", priority) in sla_targets:
        return sla_targets[("priority", priority)]
    if request_type and ("request_type", request_type) in sla_targets:
        return sla_targets[("request_type", request_type)]
    return sla_targets.get(("default", "*"), 120)


# ---------------------------------------------------------------------------
# SLA computation
# ---------------------------------------------------------------------------

def compute_sla_for_issues(
    issues: list[dict[str, Any]],
    config: SLAConfig | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str = "",
    settings: dict[str, str] | None = None,
    targets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute custom SLA metrics for a list of issues.

    Returns:
        {
            "summary": {"first_response": {...}, "resolution": {...}},
            "tickets": [...],
            "settings": {...},
            "targets": [...]
        }
    """
    from metrics import issue_to_row

    cfg = config or sla_config
    settings = settings or cfg.get_settings()
    targets = targets or cfg.get_targets()
    now = datetime.now(timezone.utc)
    business_hours = _compile_business_hours(settings)
    target_lookup = _build_target_lookup(targets)
    from_dt = datetime.fromisoformat(f"{date_from}T00:00:00+00:00") if date_from else None
    to_dt = datetime.fromisoformat(f"{date_to}T23:59:59+00:00") if date_to else None

    # Integration reporter names — their comments count as agent responses
    integration_names = {
        n.strip().lower()
        for n in settings.get("integration_reporters", "").split(",")
        if n.strip()
    }

    # Compute per-ticket SLA
    fr_stats = {"met": 0, "breached": 0, "running": 0, "total": 0, "elapsed_sum": 0.0}
    res_stats = {"met": 0, "breached": 0, "running": 0, "total": 0, "elapsed_sum": 0.0}
    fr_elapsed_list: list[float] = []
    res_elapsed_list: list[float] = []
    ticket_rows: list[dict[str, Any]] = []

    for issue in issues:
        fields = issue.get("fields", {})
        created = _parse_dt(fields.get("created"))
        if not created:
            continue
        if from_dt and created < from_dt:
            continue
        if to_dt and created > to_dt:
            continue

        # Basic ticket info
        row = issue_to_row(
            issue,
            include_comment_meta=False,
            include_description=False,
        )

        # Priority and request type for target lookup
        priority = (fields.get("priority") or {}).get("name", "")
        request_type = extract_request_type_name_from_fields(fields)

        # Status
        status_cat = ((fields.get("status") or {}).get("statusCategory") or {}).get("name", "")
        is_open = status_cat != "Done"

        # Reporter
        reporter_obj = fields.get("reporter") or {}
        reporter_id = reporter_obj.get("accountId", "")
        reporter_name = (reporter_obj.get("displayName") or "").lower()

        # If the reporter is an integration account, their comments ARE agent responses
        reporter_is_integration = reporter_name in integration_names

        # --- First Response ---
        comments = (fields.get("comment") or {}).get("comments", [])
        first_response_time = None
        for comment in comments:
            author_id = (comment.get("author") or {}).get("accountId", "")
            if not author_id:
                continue
            if reporter_is_integration:
                # Integration reporter: any comment counts as first response
                first_response_time = _parse_dt(comment.get("created"))
                break
            elif author_id != reporter_id:
                # Normal reporter: only non-reporter comments count
                first_response_time = _parse_dt(comment.get("created"))
                break

        fr_target = _get_target_from_lookup(
            target_lookup,
            "first_response",
            priority,
            request_type,
        )
        if first_response_time:
            elapsed = _business_minutes_between_compiled(created, first_response_time, business_hours)
            fr_status = "breached" if elapsed > fr_target else "met"
        elif is_open:
            elapsed = _business_minutes_between_compiled(created, now, business_hours)
            fr_status = "breached" if elapsed > fr_target else "running"
        else:
            # Resolved without any agent response — breached
            end_time = _parse_dt(fields.get("resolutiondate")) or now
            elapsed = _business_minutes_between_compiled(created, end_time, business_hours)
            fr_status = "breached"
        fr_result = {
            "status": fr_status,
            "elapsed_minutes": round(elapsed, 1),
            "target_minutes": fr_target,
        }
        fr_stats["total"] += 1
        fr_stats[fr_status] += 1
        fr_stats["elapsed_sum"] += elapsed
        fr_elapsed_list.append(elapsed)

        # --- Resolution ---
        resolution_time = _parse_dt(fields.get("resolutiondate"))
        res_target = _get_target_from_lookup(
            target_lookup,
            "resolution",
            priority,
            request_type,
        )
        if resolution_time:
            elapsed = _business_minutes_between_compiled(created, resolution_time, business_hours)
            res_status = "breached" if elapsed > res_target else "met"
        else:
            # Open ticket — still running
            elapsed = _business_minutes_between_compiled(created, now, business_hours)
            res_status = "breached" if elapsed > res_target else "running"
        res_result = {
            "status": res_status,
            "elapsed_minutes": round(elapsed, 1),
            "target_minutes": res_target,
        }
        res_stats["total"] += 1
        res_stats[res_status] += 1
        res_stats["elapsed_sum"] += elapsed
        res_elapsed_list.append(elapsed)

        row["sla_first_response"] = fr_result
        row["sla_resolution"] = res_result
        ticket_rows.append(row)

    import math

    def _percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        idx = math.ceil(pct / 100.0 * len(s)) - 1
        return round(s[max(idx, 0)], 1)

    def _distribution(values: list[float], buckets: list[tuple[str, float, float]]) -> list[dict[str, Any]]:
        result = []
        for label, lo, hi in buckets:
            count = sum(1 for v in values if lo <= v < hi)
            result.append({"label": label, "count": count})
        return result

    FR_BUCKETS: list[tuple[str, float, float]] = [
        ("<30m", 0, 30), ("30m–1h", 30, 60), ("1–2h", 60, 120),
        ("2–4h", 120, 240), ("4–8h", 240, 480), ("8h+", 480, float("inf")),
    ]
    RES_BUCKETS: list[tuple[str, float, float]] = [
        ("<2h", 0, 120), ("2–4h", 120, 240), ("4–8h", 240, 480),
        ("1 day", 480, 540), ("1–2d", 540, 1080), ("2–5d", 1080, 2700),
        ("5d+", 2700, float("inf")),
    ]

    def _make_summary(stats: dict, elapsed_list: list[float],
                      buckets: list[tuple[str, float, float]]) -> dict[str, Any]:
        total = stats["total"]
        completed = stats["met"] + stats["breached"]
        return {
            "total": total,
            "met": stats["met"],
            "breached": stats["breached"],
            "running": stats["running"],
            "compliance_pct": round(stats["met"] / completed * 100, 1) if completed else 0.0,
            "avg_elapsed_minutes": round(stats["elapsed_sum"] / total, 1) if total else 0.0,
            "p95_elapsed_minutes": _percentile(elapsed_list, 95),
            "distribution": _distribution(elapsed_list, buckets),
        }

    search_lower = search.strip().lower()
    if search_lower:
        ticket_rows = [
            row
            for row in ticket_rows
            if search_lower in " ".join(
                [
                    str(row.get("key") or ""),
                    str(row.get("summary") or ""),
                    str(row.get("assignee") or ""),
                    str(row.get("status") or ""),
                    str(row.get("priority") or ""),
                ]
            ).lower()
        ]

    return {
        "summary": {
            "first_response": _make_summary(fr_stats, fr_elapsed_list, FR_BUCKETS),
            "resolution": _make_summary(res_stats, res_elapsed_list, RES_BUCKETS),
        },
        "tickets": ticket_rows,
        "settings": settings,
        "targets": targets,
    }
