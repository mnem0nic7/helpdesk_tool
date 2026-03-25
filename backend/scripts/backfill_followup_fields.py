"""
Backfill Jira Daily Public Follow-Up custom fields from JSM request comments.

Usage:
    python backend/scripts/backfill_followup_fields.py [--days 60] [--write]

Defaults to dry-run mode. Use --write to persist the computed field values
back to Jira for the matching issues.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent
_backend = _here.parent
sys.path.insert(0, str(_backend))

from config import (  # noqa: E402
    JIRA_FOLLOWUP_AGENT_GROUPS,
    JIRA_FOLLOWUP_BREACHED_AT_FIELD_ID,
    JIRA_FOLLOWUP_LAST_PUBLIC_AGENT_TOUCH_FIELD_ID,
    JIRA_FOLLOWUP_PUBLIC_AGENT_TOUCH_COUNT_FIELD_ID,
    JIRA_FOLLOWUP_STATUS_FIELD_ID,
    JIRA_PROJECT,
)
from jira_client import JiraClient  # noqa: E402
from metrics import parse_dt  # noqa: E402

FOLLOWUP_WINDOW = timedelta(hours=24)


@dataclass
class FollowUpComputation:
    status: str
    last_touch_at: str
    touch_count: int
    breached_at: str


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


def build_followup_field_payload(computed: FollowUpComputation) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if JIRA_FOLLOWUP_LAST_PUBLIC_AGENT_TOUCH_FIELD_ID:
        payload[JIRA_FOLLOWUP_LAST_PUBLIC_AGENT_TOUCH_FIELD_ID] = computed.last_touch_at or None
    if JIRA_FOLLOWUP_PUBLIC_AGENT_TOUCH_COUNT_FIELD_ID:
        payload[JIRA_FOLLOWUP_PUBLIC_AGENT_TOUCH_COUNT_FIELD_ID] = computed.touch_count
    if JIRA_FOLLOWUP_STATUS_FIELD_ID:
        payload[JIRA_FOLLOWUP_STATUS_FIELD_ID] = {"value": computed.status}
    if JIRA_FOLLOWUP_BREACHED_AT_FIELD_ID:
        payload[JIRA_FOLLOWUP_BREACHED_AT_FIELD_ID] = computed.breached_at or None
    return payload


def _current_value(fields: dict[str, Any], field_id: str) -> Any:
    return fields.get(field_id) if field_id else None


def current_followup_field_payload(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    return build_followup_field_payload(
        FollowUpComputation(
            status=str((_current_value(fields, JIRA_FOLLOWUP_STATUS_FIELD_ID) or {}).get("value") or _current_value(fields, JIRA_FOLLOWUP_STATUS_FIELD_ID) or "").strip(),
            last_touch_at=str(_current_value(fields, JIRA_FOLLOWUP_LAST_PUBLIC_AGENT_TOUCH_FIELD_ID) or "").strip(),
            touch_count=int(float(_current_value(fields, JIRA_FOLLOWUP_PUBLIC_AGENT_TOUCH_COUNT_FIELD_ID) or 0)),
            breached_at=str(_current_value(fields, JIRA_FOLLOWUP_BREACHED_AT_FIELD_ID) or "").strip(),
        )
    )


def _payloads_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left == right


def load_agent_account_ids(client: JiraClient) -> set[str]:
    account_ids: set[str] = set()
    for group_name in JIRA_FOLLOWUP_AGENT_GROUPS:
        for member in client.get_group_members(group_name):
            account_id = str(member.get("accountId") or "").strip()
            if account_id:
                account_ids.add(account_id)
    return account_ids


def _validate_config() -> None:
    missing: list[str] = []
    if not JIRA_FOLLOWUP_LAST_PUBLIC_AGENT_TOUCH_FIELD_ID:
        missing.append("JIRA_FOLLOWUP_LAST_PUBLIC_AGENT_TOUCH_FIELD_ID")
    if not JIRA_FOLLOWUP_PUBLIC_AGENT_TOUCH_COUNT_FIELD_ID:
        missing.append("JIRA_FOLLOWUP_PUBLIC_AGENT_TOUCH_COUNT_FIELD_ID")
    if not JIRA_FOLLOWUP_STATUS_FIELD_ID:
        missing.append("JIRA_FOLLOWUP_STATUS_FIELD_ID")
    if not JIRA_FOLLOWUP_BREACHED_AT_FIELD_ID:
        missing.append("JIRA_FOLLOWUP_BREACHED_AT_FIELD_ID")
    if not JIRA_FOLLOWUP_AGENT_GROUPS:
        missing.append("JIRA_FOLLOWUP_AGENT_GROUPS")
    if missing:
        raise SystemExit(f"Missing required follow-up config: {', '.join(missing)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=60, help="How many days of OIT tickets to backfill")
    parser.add_argument("--write", action="store_true", help="Persist updates back to Jira")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _validate_config()

    client = JiraClient()
    project_key = JIRA_PROJECT.strip() or "OIT"
    jql = f'project = "{project_key}" AND updated >= -{max(args.days, 1)}d ORDER BY updated DESC'
    print(f"Loading Jira issues for {project_key} updated in the last {max(args.days, 1)} days...")
    issues = client.search_all(jql)
    print(f"Loaded {len(issues)} issues")

    print(f"Resolving Jira agent groups: {', '.join(JIRA_FOLLOWUP_AGENT_GROUPS)}")
    agent_account_ids = load_agent_account_ids(client)
    print(f"Loaded {len(agent_account_ids)} Jira agent account IDs")

    changed = 0
    written = 0
    for index, issue in enumerate(issues, start=1):
        key = str(issue.get("key") or "").strip()
        if not key:
            continue
        comments = client.get_request_comments(key)
        computed = compute_followup_from_public_agent_comments(
            issue,
            comments,
            agent_account_ids=agent_account_ids,
        )
        desired_payload = build_followup_field_payload(computed)
        current_payload = current_followup_field_payload(issue)
        if _payloads_equal(desired_payload, current_payload):
            continue
        changed += 1
        print(
            f"[{index:>3}/{len(issues)}] {key}: {computed.status} | "
            f"touches={computed.touch_count} | last_touch={computed.last_touch_at or '-'} | "
            f"breached_at={computed.breached_at or '-'}"
        )
        if args.write:
            client.update_issue_fields(key, desired_payload)
            written += 1

    mode = "WRITE" if args.write else "DRY-RUN"
    print(f"{mode} complete: {changed} issues need updates; {written} issues written.")


if __name__ == "__main__":
    main()
