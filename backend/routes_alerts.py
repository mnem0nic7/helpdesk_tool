"""API routes for email alert rule management."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from alert_store import alert_store
from alert_engine import run_alert_checks, EVALUATORS, TRIGGER_LABELS
from issue_cache import cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts")


@router.get("/rules")
async def list_rules() -> list[dict[str, Any]]:
    """List all alert rules."""
    return alert_store.get_rules()


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: int) -> dict[str, Any]:
    """Get a single alert rule."""
    rule = alert_store.get_rule(rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return rule


@router.post("/rules")
async def create_rule(body: dict[str, Any]) -> dict[str, Any]:
    """Create a new alert rule."""
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    if body.get("trigger_type") not in EVALUATORS:
        raise HTTPException(400, f"trigger_type must be one of: {list(EVALUATORS.keys())}")
    if not body.get("recipients"):
        raise HTTPException(400, "recipients is required")
    return alert_store.create_rule(body)


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Update an alert rule."""
    if body.get("trigger_type") and body["trigger_type"] not in EVALUATORS:
        raise HTTPException(400, f"trigger_type must be one of: {list(EVALUATORS.keys())}")
    result = alert_store.update_rule(rule_id, body)
    if not result:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return result


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int) -> dict[str, Any]:
    """Delete an alert rule."""
    if not alert_store.delete_rule(rule_id):
        raise HTTPException(404, f"Rule {rule_id} not found")
    return {"deleted": True}


@router.post("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: int) -> dict[str, Any]:
    """Toggle a rule's enabled state."""
    rule = alert_store.get_rule(rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return alert_store.update_rule(rule_id, {"enabled": not rule["enabled"]})  # type: ignore[return-value]


@router.post("/rules/{rule_id}/test")
async def test_rule(rule_id: int) -> dict[str, Any]:
    """Test-run a rule: evaluate without sending email, return matching tickets."""
    rule = alert_store.get_rule(rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")

    evaluator = EVALUATORS.get(rule["trigger_type"])
    if not evaluator:
        raise HTTPException(400, f"Unknown trigger type: {rule['trigger_type']}")

    issues = cache.get_filtered_issues()
    filtered = [iss for iss in issues if True]  # Apply filters later

    from alert_engine import _matches_filters
    filtered = [iss for iss in issues if _matches_filters(iss, rule["filters"])]
    matching = evaluator(filtered, rule["trigger_config"])

    return {
        "rule": rule,
        "matching_count": len(matching),
        "sample_keys": [iss.get("key", "") for iss in matching[:20]],
    }


@router.post("/rules/{rule_id}/send")
async def send_rule_now(rule_id: int) -> dict[str, Any]:
    """Immediately evaluate and send a single rule's alert."""
    rule = alert_store.get_rule(rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")

    evaluator = EVALUATORS.get(rule["trigger_type"])
    if not evaluator:
        raise HTTPException(400, f"Unknown trigger type: {rule['trigger_type']}")

    from alert_engine import _matches_filters, _render_email, _refresh_tickets, set_jira_base_url
    from email_service import send_email
    from config import JIRA_BASE_URL
    set_jira_base_url(JIRA_BASE_URL)

    issues = cache.get_filtered_issues()
    filtered = [iss for iss in issues if _matches_filters(iss, rule["filters"])]
    matching = evaluator(filtered, rule["trigger_config"])

    if not matching:
        return {"sent": False, "matching_count": 0, "reason": "No matching tickets"}

    # Refresh from Jira and re-evaluate to avoid sending stale data
    matching = _refresh_tickets(matching)
    matching = evaluator(matching, rule["trigger_config"])
    matching = [iss for iss in matching if _matches_filters(iss, rule["filters"])]

    if not matching:
        return {"sent": False, "matching_count": 0, "reason": "No matching tickets after refresh"}

    subject, html = _render_email(rule, matching)
    recipients = [r.strip() for r in rule["recipients"].split(",") if r.strip()]
    cc = [c.strip() for c in (rule.get("cc") or "").split(",") if c.strip()] or None

    if not recipients:
        raise HTTPException(400, "Rule has no recipients")

    success = await send_email(recipients, subject, html, cc=cc)
    ticket_keys = [iss.get("key", "") for iss in matching]

    alert_store.record_send(
        rule, ticket_keys,
        status="sent" if success else "failed",
        error=None if success else "Email delivery failed",
    )
    alert_store.update_last_run(rule["id"], sent=success)

    return {"sent": success, "matching_count": len(matching), "ticket_count": len(ticket_keys)}


@router.post("/run")
async def run_alerts_now() -> dict[str, Any]:
    """Manually trigger all enabled alert rules."""
    issues = cache.get_filtered_issues()
    sent = await run_alert_checks(issues)
    return {"sent_count": sent}


@router.get("/history")
async def get_history(limit: int = 50, rule_id: int | None = None) -> list[dict[str, Any]]:
    """Get alert send history."""
    return alert_store.get_history(limit=limit, rule_id=rule_id)


@router.get("/trigger-types")
async def get_trigger_types() -> list[dict[str, str]]:
    """Return available trigger types for the UI."""
    return [
        {"value": k, "label": v}
        for k, v in TRIGGER_LABELS.items()
    ]
