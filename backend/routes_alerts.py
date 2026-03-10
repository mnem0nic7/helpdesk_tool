"""API routes for email alert rule management."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from alert_store import alert_store
from auth import require_admin
from alert_engine import (
    baseline_new_ticket_rule,
    get_rule_matches,
    mark_rule_tickets_seen,
    run_alert_checks,
    EVALUATORS,
    TRIGGER_LABELS,
)
from issue_cache import cache
from site_context import filter_issues_for_scope, get_current_site_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts")


def _should_rebaseline_new_ticket_rule(
    previous_rule: dict[str, Any],
    updated_rule: dict[str, Any],
    body: dict[str, Any],
) -> bool:
    if updated_rule["trigger_type"] != "new_ticket":
        return False
    if previous_rule["trigger_type"] != "new_ticket":
        return True
    if not previous_rule.get("enabled", True) and updated_rule.get("enabled", True):
        return True
    return any(field in body for field in ("filters", "trigger_config"))


def _current_scope_issues() -> list[dict[str, Any]]:
    try:
        return filter_issues_for_scope(cache.get_all_issues(), get_current_site_scope())
    except AttributeError:
        return cache.get_filtered_issues()


@router.get("/rules")
async def list_rules() -> list[dict[str, Any]]:
    """List all alert rules."""
    return alert_store.get_rules(site_scope=get_current_site_scope())


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: int) -> dict[str, Any]:
    """Get a single alert rule."""
    rule = alert_store.get_rule(rule_id, site_scope=get_current_site_scope())
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
    site_scope = get_current_site_scope()
    rule = alert_store.create_rule({**body, "site_scope": site_scope})
    if rule["trigger_type"] == "new_ticket":
        baseline_new_ticket_rule(rule, _current_scope_issues())
    return rule


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Update an alert rule."""
    site_scope = get_current_site_scope()
    existing = alert_store.get_rule(rule_id, site_scope=site_scope)
    if not existing:
        raise HTTPException(404, f"Rule {rule_id} not found")
    if body.get("trigger_type") and body["trigger_type"] not in EVALUATORS:
        raise HTTPException(400, f"trigger_type must be one of: {list(EVALUATORS.keys())}")
    result = alert_store.update_rule(rule_id, body, site_scope=site_scope)
    if not result:
        raise HTTPException(500, f"Failed to update rule {rule_id}")
    if existing["trigger_type"] == "new_ticket" and result["trigger_type"] != "new_ticket":
        alert_store.clear_seen_ticket_keys(rule_id)
    elif _should_rebaseline_new_ticket_rule(existing, result, body):
        baseline_new_ticket_rule(result, _current_scope_issues())
    return result


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int) -> dict[str, Any]:
    """Delete an alert rule."""
    if not alert_store.delete_rule(rule_id, site_scope=get_current_site_scope()):
        raise HTTPException(404, f"Rule {rule_id} not found")
    return {"deleted": True}


@router.post("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: int) -> dict[str, Any]:
    """Toggle a rule's enabled state."""
    site_scope = get_current_site_scope()
    rule = alert_store.get_rule(rule_id, site_scope=site_scope)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    updated = alert_store.update_rule(rule_id, {"enabled": not rule["enabled"]}, site_scope=site_scope)
    if not updated:
        raise HTTPException(500, f"Failed to toggle rule {rule_id}")
    if _should_rebaseline_new_ticket_rule(rule, updated, {"enabled": updated["enabled"]}):
        baseline_new_ticket_rule(updated, _current_scope_issues())
    return updated


@router.post("/rules/{rule_id}/test")
async def test_rule(rule_id: int) -> dict[str, Any]:
    """Test-run a rule: evaluate without sending email, return matching tickets."""
    rule = alert_store.get_rule(rule_id, site_scope=get_current_site_scope())
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")

    try:
        matching = get_rule_matches(rule, _current_scope_issues())
    except ValueError:
        raise HTTPException(400, f"Unknown trigger type: {rule['trigger_type']}") from None

    return {
        "rule": rule,
        "matching_count": len(matching),
        "sample_keys": [iss.get("key", "") for iss in matching[:20]],
    }


@router.post("/rules/{rule_id}/send")
async def send_rule_now(rule_id: int, _admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Immediately evaluate and send a single rule's alert."""
    site_scope = get_current_site_scope()
    rule = alert_store.get_rule(rule_id, site_scope=site_scope)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")

    from alert_engine import _render_email
    from email_service import send_email

    try:
        matching = get_rule_matches(rule, _current_scope_issues(), refresh=True)
    except ValueError:
        raise HTTPException(400, f"Unknown trigger type: {rule['trigger_type']}") from None

    if not matching:
        return {"sent": False, "matching_count": 0, "reason": "No matching tickets"}

    subject, html = _render_email(rule, matching, site_scope=site_scope)
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
    alert_store.update_last_run(rule["id"], sent=success, site_scope=site_scope)
    if success:
        mark_rule_tickets_seen(rule, matching)

    return {"sent": success, "matching_count": len(matching), "ticket_count": len(ticket_keys)}


@router.post("/run")
async def run_alerts_now(_admin: dict = Depends(require_admin)) -> dict[str, Any]:
    """Manually trigger all enabled alert rules."""
    site_scope = get_current_site_scope()
    issues = _current_scope_issues()
    sent = await run_alert_checks(issues, site_scope=site_scope)
    return {"sent_count": sent}


@router.get("/history")
async def get_history(limit: int = 50, rule_id: int | None = None) -> list[dict[str, Any]]:
    """Get alert send history."""
    return alert_store.get_history(limit=limit, rule_id=rule_id, site_scope=get_current_site_scope())


@router.get("/trigger-types")
async def get_trigger_types() -> list[dict[str, str]]:
    """Return available trigger types for the UI."""
    return [
        {"value": k, "label": v}
        for k, v in TRIGGER_LABELS.items()
    ]
