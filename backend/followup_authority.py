"""Authoritative daily follow-up computation from public Jira comments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

FOLLOWUP_WINDOW = timedelta(hours=24)

LOCAL_FOLLOWUP_STATUS_FIELD = "_movedocs_followup_status"
LOCAL_FOLLOWUP_LAST_TOUCH_FIELD = "_movedocs_followup_last_touch_at"
LOCAL_FOLLOWUP_TOUCH_COUNT_FIELD = "_movedocs_followup_touch_count"
LOCAL_FOLLOWUP_BREACHED_AT_FIELD = "_movedocs_followup_breached_at"
LOCAL_FOLLOWUP_SYNCED_UPDATED_FIELD = "_movedocs_followup_synced_for_updated"
LOCAL_FOLLOWUP_SOURCE_FIELD = "_movedocs_followup_source"
LOCAL_FOLLOWUP_SOURCE_VALUE = "public_agent_comments"


@dataclass
class FollowUpComputation:
    status: str
    last_touch_at: str
    touch_count: int
    breached_at: str


def parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_iso(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _comment_created_dt(comment: dict[str, Any]) -> datetime | None:
    raw = comment.get("created")
    if isinstance(raw, dict):
        raw = raw.get("iso8601") or raw.get("jira") or raw.get("friendly") or ""
    return parse_dt(raw)


def _comment_author_account_id(comment: dict[str, Any]) -> str:
    author = comment.get("author") or {}
    return str(author.get("accountId") or "").strip()


def _is_public_agent_comment(comment: dict[str, Any], agent_account_ids: set[str]) -> bool:
    if not bool(comment.get("public", False)):
        return False
    if not agent_account_ids:
        return False
    return _comment_author_account_id(comment) in agent_account_ids


def _issue_resolved_dt(issue: dict[str, Any]) -> datetime | None:
    return parse_dt((issue.get("fields") or {}).get("resolutiondate"))


def _issue_is_open(issue: dict[str, Any]) -> bool:
    fields = issue.get("fields") or {}
    resolved_dt = _issue_resolved_dt(issue)
    status_category = str((((fields.get("status") or {}).get("statusCategory") or {}).get("name") or "")).strip().lower()
    return resolved_dt is None and status_category != "done"


def compute_followup_from_public_agent_comments(
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    *,
    agent_account_ids: set[str],
    now: datetime | None = None,
) -> FollowUpComputation:
    """Compute authoritative daily follow-up fields from public agent comments."""
    clock = now or datetime.now(timezone.utc)
    public_agent_events = sorted(
        (
            _comment_created_dt(comment)
            for comment in comments
            if _is_public_agent_comment(comment, agent_account_ids)
        ),
        key=lambda dt: dt or datetime.min.replace(tzinfo=timezone.utc),
    )
    event_times = [dt for dt in public_agent_events if dt is not None]
    resolved_dt = _issue_resolved_dt(issue)
    is_open = _issue_is_open(issue)

    if not event_times:
        if resolved_dt is not None:
            return FollowUpComputation(
                status="BREACHED",
                last_touch_at="",
                touch_count=0,
                breached_at=_format_iso(resolved_dt),
            )
        return FollowUpComputation(status="Running", last_touch_at="", touch_count=0, breached_at="")

    breach_at: datetime | None = None
    previous = event_times[0]
    for current in event_times[1:]:
        if current - previous > FOLLOWUP_WINDOW:
            breach_at = previous + FOLLOWUP_WINDOW
            break
        previous = current

    if breach_at is None:
        end_dt = clock if is_open else resolved_dt
        if end_dt and end_dt - previous > FOLLOWUP_WINDOW:
            breach_at = previous + FOLLOWUP_WINDOW

    if breach_at is not None:
        status = "BREACHED"
    elif is_open:
        status = "Running"
    else:
        status = "Met"

    return FollowUpComputation(
        status=status,
        last_touch_at=_format_iso(event_times[-1]),
        touch_count=len(event_times),
        breached_at=_format_iso(breach_at),
    )


def apply_local_followup_fields(issue: dict[str, Any], computed: FollowUpComputation) -> dict[str, Any]:
    """Write authoritative follow-up results into local cached issue fields."""
    fields = issue.setdefault("fields", {})
    fields[LOCAL_FOLLOWUP_STATUS_FIELD] = computed.status
    fields[LOCAL_FOLLOWUP_LAST_TOUCH_FIELD] = computed.last_touch_at or ""
    fields[LOCAL_FOLLOWUP_TOUCH_COUNT_FIELD] = computed.touch_count
    fields[LOCAL_FOLLOWUP_BREACHED_AT_FIELD] = computed.breached_at or ""
    fields[LOCAL_FOLLOWUP_SYNCED_UPDATED_FIELD] = str(fields.get("updated") or "").strip()
    fields[LOCAL_FOLLOWUP_SOURCE_FIELD] = LOCAL_FOLLOWUP_SOURCE_VALUE
    return fields

