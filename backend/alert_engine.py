"""Alert engine — evaluates rules against tickets and sends email alerts."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from datetime import timedelta

from alert_store import alert_store
from email_service import send_email
from metrics import _is_open
from request_type import extract_request_type_name_from_fields
from sla_engine import sla_config, business_minutes_between, _parse_dt
from site_context import get_site_origin, get_site_profile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ticket evaluation per trigger type
# ---------------------------------------------------------------------------

def _get_status_category(issue: dict) -> str:
    return (
        (issue.get("fields", {}).get("status") or {})
        .get("statusCategory", {})
        .get("name", "")
    )


def _get_priority(issue: dict) -> str:
    return (issue.get("fields", {}).get("priority") or {}).get("name", "")


def _get_assignee(issue: dict) -> str:
    return (issue.get("fields", {}).get("assignee") or {}).get("displayName", "Unassigned")


def _get_request_type(issue: dict) -> str:
    return extract_request_type_name_from_fields(issue.get("fields", {}))


def _updated_minutes_ago(issue: dict, now: datetime) -> float:
    updated_str = issue.get("fields", {}).get("updated")
    if not updated_str:
        return float("inf")
    updated = _parse_dt(updated_str)
    if not updated:
        return float("inf")
    return (now - updated).total_seconds() / 60.0


def _matches_filters(issue: dict, filters: dict) -> bool:
    """Check if an issue matches the rule's optional filters."""
    if not filters:
        return True

    priority = _get_priority(issue).lower()
    if filters.get("priorities"):
        allowed = [p.lower() for p in filters["priorities"]]
        if not priority or priority not in allowed:
            return False

    assignee = _get_assignee(issue).lower()
    if filters.get("assignees"):
        allowed = [a.lower() for a in filters["assignees"]]
        # Treat empty/missing assignee as "unassigned"
        effective = assignee if assignee else "unassigned"
        if effective not in allowed:
            return False

    request_type = _get_request_type(issue).lower()
    if filters.get("request_types"):
        allowed = [r.lower() for r in filters["request_types"]]
        if not request_type or request_type not in allowed:
            return False

    return True


def _apply_ticket_scope(issues: list[dict], filters: dict, rule: dict) -> list[dict]:
    """Pre-filter issues by ticket_scope before running the evaluator.

    Scopes:
      "open" (default) — only open/in-progress tickets
      "all"            — all tickets regardless of status
      "new"            — tickets created since the rule last ran (or last 24 h)
    """
    scope = (filters.get("ticket_scope") or "open")
    if scope == "all":
        return issues
    if scope == "open":
        return [iss for iss in issues if _is_open(iss)]
    if scope == "new":
        last_run_str = rule.get("last_run")
        if last_run_str:
            cutoff = _parse_dt(last_run_str) or (datetime.now(timezone.utc) - timedelta(hours=24))
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        return [
            iss for iss in issues
            if (created := _parse_dt((iss.get("fields") or {}).get("created")))
            and created >= cutoff
        ]
    # Unknown scope — fall back to open-only
    return [iss for iss in issues if _is_open(iss)]


def evaluate_stale(issues: list[dict], config: dict) -> list[dict]:
    """Find open tickets not updated within stale_hours (default 24)."""
    stale_hours = config.get("stale_hours", 24)
    stale_minutes = stale_hours * 60
    now = datetime.now(timezone.utc)
    return [
        iss for iss in issues
        if _is_open(iss) and _updated_minutes_ago(iss, now) > stale_minutes
    ]


def evaluate_fr_breach(issues: list[dict], config: dict) -> list[dict]:
    """Find tickets that have breached first response SLA."""
    settings = sla_config.get_settings()
    now = datetime.now(timezone.utc)
    integration_names = {
        n.strip().lower()
        for n in settings.get("integration_reporters", "").split(",")
        if n.strip()
    }
    result = []
    for iss in issues:
        fields = iss.get("fields", {})
        created = _parse_dt(fields.get("created"))
        if not created:
            continue

        priority = _get_priority(iss)
        request_type = _get_request_type(iss)
        target = sla_config.get_target_for_ticket("first_response", priority, request_type)

        reporter_obj = fields.get("reporter") or {}
        reporter_id = reporter_obj.get("accountId", "")
        reporter_name = (reporter_obj.get("displayName") or "").lower()
        reporter_is_integration = reporter_name in integration_names

        comments = (fields.get("comment") or {}).get("comments", [])
        first_response_time = None
        for comment in comments:
            author_id = (comment.get("author") or {}).get("accountId", "")
            if not author_id:
                continue
            if reporter_is_integration:
                first_response_time = _parse_dt(comment.get("created"))
                break
            elif author_id != reporter_id:
                first_response_time = _parse_dt(comment.get("created"))
                break

        if first_response_time:
            elapsed = business_minutes_between(created, first_response_time, settings)
        elif _is_open(iss):
            elapsed = business_minutes_between(created, now, settings)
        else:
            end_time = _parse_dt(fields.get("resolutiondate")) or now
            elapsed = business_minutes_between(created, end_time, settings)

        if elapsed > target:
            result.append(iss)
    return result


def evaluate_res_breach(issues: list[dict], config: dict) -> list[dict]:
    """Find tickets that have breached resolution SLA."""
    settings = sla_config.get_settings()
    now = datetime.now(timezone.utc)
    result = []
    for iss in issues:
        fields = iss.get("fields", {})
        created = _parse_dt(fields.get("created"))
        if not created:
            continue

        priority = _get_priority(iss)
        request_type = _get_request_type(iss)
        target = sla_config.get_target_for_ticket("resolution", priority, request_type)

        resolution_time = _parse_dt(fields.get("resolutiondate"))
        if resolution_time:
            elapsed = business_minutes_between(created, resolution_time, settings)
        else:
            elapsed = business_minutes_between(created, now, settings)

        if elapsed > target:
            result.append(iss)
    return result


def evaluate_fr_approaching(issues: list[dict], config: dict) -> list[dict]:
    """Find open tickets approaching first response SLA (default 80% of target)."""
    threshold_pct = config.get("threshold_pct", 80) / 100.0
    settings = sla_config.get_settings()
    now = datetime.now(timezone.utc)
    integration_names = {
        n.strip().lower()
        for n in settings.get("integration_reporters", "").split(",")
        if n.strip()
    }
    result = []
    for iss in issues:
        if not _is_open(iss):
            continue
        fields = iss.get("fields", {})
        created = _parse_dt(fields.get("created"))
        if not created:
            continue

        priority = _get_priority(iss)
        request_type = _get_request_type(iss)
        target = sla_config.get_target_for_ticket("first_response", priority, request_type)

        reporter_obj = fields.get("reporter") or {}
        reporter_id = reporter_obj.get("accountId", "")
        reporter_name = (reporter_obj.get("displayName") or "").lower()
        reporter_is_integration = reporter_name in integration_names

        comments = (fields.get("comment") or {}).get("comments", [])
        has_response = False
        for comment in comments:
            author_id = (comment.get("author") or {}).get("accountId", "")
            if not author_id:
                continue
            if reporter_is_integration or author_id != reporter_id:
                has_response = True
                break

        if has_response:
            continue

        elapsed = business_minutes_between(created, now, settings)
        if target * threshold_pct <= elapsed <= target:
            result.append(iss)
    return result


def evaluate_res_approaching(issues: list[dict], config: dict) -> list[dict]:
    """Find open tickets approaching resolution SLA."""
    threshold_pct = config.get("threshold_pct", 80) / 100.0
    settings = sla_config.get_settings()
    now = datetime.now(timezone.utc)
    result = []
    for iss in issues:
        if not _is_open(iss):
            continue
        fields = iss.get("fields", {})
        created = _parse_dt(fields.get("created"))
        if not created:
            continue

        priority = _get_priority(iss)
        request_type = _get_request_type(iss)
        target = sla_config.get_target_for_ticket("resolution", priority, request_type)

        elapsed = business_minutes_between(created, now, settings)
        if target * threshold_pct <= elapsed <= target:
            result.append(iss)
    return result


def evaluate_new_ticket(issues: list[dict], config: dict) -> list[dict]:
    """Return currently matching tickets for unseen/new-ticket evaluation."""
    return list(issues)


def evaluate_unresolved(issues: list[dict], config: dict) -> list[dict]:
    """Find open tickets still unresolved after a given number of hours (wall-clock)."""
    hours = float(config.get("hours", 8))
    threshold_minutes = hours * 60
    now = datetime.now(timezone.utc)
    result = []
    for iss in issues:
        if not _is_open(iss):
            continue
        created_str = (iss.get("fields") or {}).get("created")
        if not created_str:
            continue
        created = _parse_dt(created_str)
        if not created:
            continue
        if (now - created).total_seconds() / 60.0 > threshold_minutes:
            result.append(iss)
    return result


EVALUATORS = {
    "stale": evaluate_stale,
    "fr_breach": evaluate_fr_breach,
    "res_breach": evaluate_res_breach,
    "fr_approaching": evaluate_fr_approaching,
    "res_approaching": evaluate_res_approaching,
    "new_ticket": evaluate_new_ticket,
    "unresolved": evaluate_unresolved,
}


# ---------------------------------------------------------------------------
# Email rendering
# ---------------------------------------------------------------------------

def _site_ticket_url(key: str, site_scope: str) -> str:
    query = urlencode({"ticket": key})
    return f"{get_site_origin(site_scope)}/tickets?{query}"


TRIGGER_LABELS = {
    "stale": "Stale Tickets",
    "fr_breach": "First Response SLA Breaches",
    "res_breach": "Resolution SLA Breaches",
    "fr_approaching": "Approaching First Response SLA",
    "res_approaching": "Approaching Resolution SLA",
    "new_ticket": "New Tickets",
    "unresolved": "Unresolved Past Time Limit",
}


def _ticket_keys(tickets: list[dict]) -> list[str]:
    return [key for key in (iss.get("key", "") for iss in tickets) if key]


def _evaluate_rule(rule: dict, issues: list[dict]) -> list[dict]:
    evaluator = EVALUATORS.get(rule["trigger_type"])
    if not evaluator:
        raise ValueError(f"Unknown trigger type: {rule['trigger_type']}")

    filters = rule["filters"]
    scoped = _apply_ticket_scope(issues, filters, rule)
    filtered = [iss for iss in scoped if _matches_filters(iss, filters)]
    return evaluator(filtered, rule["trigger_config"])


def _filter_unseen_tickets(rule: dict, tickets: list[dict]) -> list[dict]:
    if rule["trigger_type"] != "new_ticket":
        return tickets

    seen_keys = alert_store.get_seen_ticket_keys(rule["id"])
    return [iss for iss in tickets if iss.get("key", "") not in seen_keys]


def get_rule_matches(
    rule: dict,
    issues: list[dict],
    *,
    refresh: bool = False,
    only_new: bool = True,
) -> list[dict]:
    """Return tickets matching a rule, optionally refreshed and deduped."""
    matching = _evaluate_rule(rule, issues)

    if refresh and matching:
        matching = _refresh_tickets(matching)
        matching = _evaluate_rule(rule, matching)

    if only_new:
        matching = _filter_unseen_tickets(rule, matching)

    return matching


def baseline_new_ticket_rule(rule: dict, issues: list[dict]) -> None:
    """Seed seen-ticket state so a new-ticket rule starts from the current backlog."""
    if rule["trigger_type"] != "new_ticket":
        return

    matching = get_rule_matches(rule, issues, refresh=False, only_new=False)
    alert_store.replace_seen_ticket_keys(rule["id"], _ticket_keys(matching))


def mark_rule_tickets_seen(rule: dict, tickets: list[dict]) -> None:
    """Remember successfully-alerted tickets for new-ticket rules."""
    if rule["trigger_type"] != "new_ticket":
        return

    alert_store.mark_ticket_keys_seen(rule["id"], _ticket_keys(tickets))


def _apply_template(template: str, variables: dict[str, str]) -> str:
    """Replace {var_name} placeholders with values."""
    result = template
    for key, val in variables.items():
        result = result.replace(f"{{{key}}}", val)
    return result


def _render_email(
    rule: dict,
    tickets: list[dict],
    site_scope: str = "primary",
) -> tuple[str, str]:
    """Render email subject and HTML body for an alert.

    Custom templates support these variables:
      {rule_name}, {trigger_label}, {ticket_count}
    """
    trigger_label = TRIGGER_LABELS.get(rule["trigger_type"], rule["trigger_type"])
    profile = get_site_profile(site_scope)  # type: ignore[arg-type]
    template_vars = {
        "rule_name": rule["name"],
        "trigger_label": trigger_label,
        "ticket_count": str(len(tickets)),
    }

    # Subject — use custom or default
    custom_subject = (rule.get("custom_subject") or "").strip()
    if custom_subject:
        subject = _apply_template(custom_subject, template_vars)
    else:
        subject = f"[{profile['alert_prefix']} Alert] {rule['name']}: {len(tickets)} {trigger_label}"

    # Custom message — inserted above the ticket table
    custom_message = (rule.get("custom_message") or "").strip()
    message_html = ""
    if custom_message:
        # Convert newlines to <br> for plain-text messages, escape HTML
        escaped = html.escape(_apply_template(custom_message, template_vars))
        escaped = escaped.replace("\n", "<br>")
        message_html = f'<div style="margin-bottom:16px;font-size:14px;color:#374151;line-height:1.6">{escaped}</div>'

    rows_html = ""
    for iss in tickets[:100]:
        raw_key = iss.get("key", "?")
        key = html.escape(raw_key)
        fields = iss.get("fields", {})
        summary = html.escape(fields.get("summary", "")[:80])
        priority = html.escape(_get_priority(iss))
        assignee = html.escape(_get_assignee(iss))
        status = html.escape((fields.get("status") or {}).get("name", ""))
        url = _site_ticket_url(raw_key, site_scope)
        rows_html += f"""<tr>
            <td style="padding:6px 10px;border-bottom:1px solid #eee"><a href="{url}" style="color:#2563eb;text-decoration:none">{key}</a></td>
            <td style="padding:6px 10px;border-bottom:1px solid #eee">{summary}</td>
            <td style="padding:6px 10px;border-bottom:1px solid #eee">{priority}</td>
            <td style="padding:6px 10px;border-bottom:1px solid #eee">{assignee}</td>
            <td style="padding:6px 10px;border-bottom:1px solid #eee">{status}</td>
        </tr>"""

    overflow = ""
    if len(tickets) > 100:
        overflow = f"<p style='color:#6b7280;font-size:13px'>...and {len(tickets) - 100} more tickets.</p>"
    manage_alerts_url = f"{get_site_origin(site_scope)}/alerts"

    html_body = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:800px;margin:0 auto">
        <div style="background:#1e293b;color:white;padding:16px 24px;border-radius:8px 8px 0 0">
            <h2 style="margin:0;font-size:18px">{html.escape(trigger_label)}</h2>
            <p style="margin:4px 0 0;font-size:13px;color:#94a3b8">Alert: {html.escape(rule['name'])} &bull; {len(tickets)} ticket(s)</p>
        </div>
        <div style="border:1px solid #e5e7eb;border-top:none;padding:20px 24px;border-radius:0 0 8px 8px">
            {message_html}
            <table style="width:100%;border-collapse:collapse;font-size:13px">
                <thead>
                    <tr style="background:#f9fafb">
                        <th style="padding:8px 10px;text-align:left;color:#6b7280;font-weight:600">Key</th>
                        <th style="padding:8px 10px;text-align:left;color:#6b7280;font-weight:600">Summary</th>
                        <th style="padding:8px 10px;text-align:left;color:#6b7280;font-weight:600">Priority</th>
                        <th style="padding:8px 10px;text-align:left;color:#6b7280;font-weight:600">Assignee</th>
                        <th style="padding:8px 10px;text-align:left;color:#6b7280;font-weight:600">Status</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
            {overflow}
            <p style="margin-top:20px;font-size:12px;color:#9ca3af">
                Sent from {html.escape(profile['app_name'])} &bull; <a href="{manage_alerts_url}" style="color:#2563eb">Manage Alerts</a>
            </p>
        </div>
    </div>
    """
    return subject, html_body


# ---------------------------------------------------------------------------
# Ticket refresh before send
# ---------------------------------------------------------------------------

def _refresh_tickets(tickets: list[dict]) -> list[dict]:
    """Re-fetch tickets from Jira to ensure data is current before sending alerts."""
    if not tickets:
        return tickets

    keys = [iss.get("key", "") for iss in tickets if iss.get("key")]
    if not keys:
        return tickets

    try:
        from jira_client import JiraClient
        from config import JIRA_EMAIL, JIRA_API_TOKEN, JIRA_BASE_URL
        from issue_cache import cache

        client = JiraClient(JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)

        # Fetch in batches of 50 using JQL key in (...)
        refreshed: dict[str, dict] = {}
        for i in range(0, len(keys), 50):
            batch = keys[i:i + 50]
            jql = f"key in ({','.join(batch)})"
            fresh_issues = client.search_all(jql)
            for iss in fresh_issues:
                k = iss.get("key", "")
                if k:
                    refreshed[k] = iss
                    # Also update the cache so dashboard reflects current data
                    with cache._lock:
                        cache._all_issues[k] = iss
                        if not JiraClient.is_excluded(iss):
                            cache._issues[k] = iss

        logger.info("Alert refresh: re-fetched %d/%d tickets from Jira", len(refreshed), len(keys))

        # Return refreshed versions, fall back to cached if fetch failed
        result = []
        for iss in tickets:
            k = iss.get("key", "")
            result.append(refreshed.get(k, iss))
        return result

    except Exception:
        logger.exception("Failed to refresh tickets before alert send")
        return tickets


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

async def run_alert_checks(issues: list[dict], site_scope: str = "primary") -> int:
    """Evaluate all enabled rules and send alerts. Returns number of emails sent."""
    rules = alert_store.get_enabled_rules(site_scope=site_scope)
    if not rules:
        return 0

    now = datetime.now(timezone.utc)
    sent_count = 0

    for rule in rules:
        if not _should_run(rule, now):
            continue

        try:
            matching = get_rule_matches(rule, issues, refresh=True)
        except ValueError:
            logger.warning("Unknown trigger type: %s", rule["trigger_type"])
            continue

        if not matching:
            alert_store.update_last_run(rule["id"], sent=False, site_scope=site_scope)
            continue

        # Render and send
        subject, html = _render_email(rule, matching, site_scope=site_scope)
        recipients = [r.strip() for r in rule["recipients"].split(",") if r.strip()]
        cc = [c.strip() for c in (rule.get("cc") or "").split(",") if c.strip()] or None

        if not recipients:
            logger.warning("Rule %s has no recipients", rule["name"])
            continue

        success = await send_email(recipients, subject, html, cc=cc)
        ticket_keys = [iss.get("key", "") for iss in matching]

        alert_store.record_send(
            rule, ticket_keys,
            status="sent" if success else "failed",
            error=None if success else "Email delivery failed",
        )
        alert_store.update_last_run(rule["id"], sent=success, site_scope=site_scope)

        if success:
            mark_rule_tickets_seen(rule, matching)
            sent_count += 1

    return sent_count


def _should_run(rule: dict, now: datetime) -> bool:
    """Determine if a rule should run based on frequency and schedule."""
    frequency = rule["frequency"]

    if frequency == "immediate":
        # Run every check cycle (~1 min) but only send if there are new matches
        return True

    last_run_str = rule.get("last_run")
    if not last_run_str:
        return True

    last_run = _parse_dt(last_run_str)
    if not last_run:
        return True

    elapsed_hours = (now - last_run).total_seconds() / 3600.0

    if frequency == "hourly":
        return elapsed_hours >= 1.0

    if frequency == "daily":
        schedule_days = {int(d) for d in rule.get("schedule_days", "0,1,2,3,4").split(",") if d.strip()}
        if now.weekday() not in schedule_days:
            return False
        if elapsed_hours < 20:  # Don't re-run within 20 hours
            return False
        # Check if we've reached the scheduled send time today
        schedule_time = rule.get("schedule_time", "08:00")
        try:
            hour, minute = (int(x) for x in schedule_time.split(":"))
        except (ValueError, AttributeError):
            hour, minute = 8, 0
        if now.hour < hour or (now.hour == hour and now.minute < minute):
            return False
        return True

    if frequency == "weekly":
        schedule_days = {int(d) for d in rule.get("schedule_days", "0,1,2,3,4").split(",") if d.strip()}
        if now.weekday() not in schedule_days:
            return False
        if elapsed_hours < 7 * 20:
            return False
        # Also respect schedule_time for weekly
        schedule_time = rule.get("schedule_time", "08:00")
        try:
            hour, minute = (int(x) for x in schedule_time.split(":"))
        except (ValueError, AttributeError):
            hour, minute = 8, 0
        if now.hour < hour or (now.hour == hour and now.minute < minute):
            return False
        return True

    return elapsed_hours >= 24
