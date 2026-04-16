"""REST routes for the Defender autonomous agent."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_admin, require_authenticated_user
from defender_agent_store import defender_agent_store
from models import (
    DefenderAgentBuiltinRule,
    DefenderAgentConfigResponse,
    DefenderAgentConfigUpdate,
    DefenderAgentCustomRule,
    DefenderAgentCustomRuleCreate,
    DefenderAgentDecisionItem,
    DefenderAgentDecisionsResponse,
    DefenderAgentDispositionStats,
    DefenderAgentDispositionUpdate,
    DefenderAgentEntityTimelineResponse,
    DefenderAgentRunResponse,
    DefenderAgentRuleUpdate,
    DefenderAgentSummaryResponse,
    DefenderAgentMetrics,
    DefenderAgentNoteCreate,
    DefenderAgentWatchlistCreate,
    DefenderAgentWatchlistEntry,
    DefenderAgentWatchlistResponse,
    DefenderAgentSuppressionCreate,
    DefenderAgentSuppressionItem,
    DefenderAgentSuppressionsResponse,
)
from site_context import get_current_site_scope

router = APIRouter(prefix="/api/azure/security/defender-agent")


def _ensure_azure_site() -> None:
    if get_current_site_scope() != "azure":
        raise HTTPException(
            status_code=404,
            detail="Defender agent APIs are only available on azure.movedocs.com",
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@router.get("/config", response_model=DefenderAgentConfigResponse)
def get_config(_session: dict = Depends(require_authenticated_user)) -> dict:
    _ensure_azure_site()
    return defender_agent_store.get_config()


@router.put("/config", response_model=DefenderAgentConfigResponse)
def update_config(
    body: DefenderAgentConfigUpdate,
    _session: dict = Depends(require_admin),
) -> dict:
    _ensure_azure_site()
    return defender_agent_store.upsert_config(
        enabled=body.enabled,
        min_severity=body.min_severity,
        tier2_delay_minutes=body.tier2_delay_minutes,
        dry_run=body.dry_run,
        entity_cooldown_hours=body.entity_cooldown_hours,
        alert_dedup_window_minutes=body.alert_dedup_window_minutes,
        min_confidence=body.min_confidence,
        poll_interval_seconds=body.poll_interval_seconds,
        teams_tier1_webhook=body.teams_tier1_webhook,
        teams_tier2_webhook=body.teams_tier2_webhook,
        teams_tier3_webhook=body.teams_tier3_webhook,
        updated_by=str(_session.get("email") or ""),
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

@router.get("/runs", response_model=list[DefenderAgentRunResponse])
def list_runs(
    limit: int = Query(20, ge=1, le=100),
    _session: dict = Depends(require_authenticated_user),
) -> list[dict]:
    _ensure_azure_site()
    return defender_agent_store.list_runs(limit=limit)


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

@router.get("/decisions", response_model=DefenderAgentDecisionsResponse)
def list_decisions(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    decisions, total = defender_agent_store.list_decisions(limit=limit, offset=offset)
    return {"decisions": decisions, "total": total}


# ---------------------------------------------------------------------------
# Phase 21: Decision CSV export (must be before /{decision_id} to avoid route conflict)
# ---------------------------------------------------------------------------

@router.get("/decisions/export")
def export_decisions(
    days: int = Query(default=30, ge=1, le=365),
    _session: dict = Depends(require_authenticated_user),
) -> object:
    """Stream a CSV of decisions from the last N days."""
    import csv
    import io
    from datetime import datetime, timedelta, timezone
    from fastapi.responses import StreamingResponse

    _ensure_azure_site()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with defender_agent_store._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM defender_agent_decisions WHERE executed_at >= ? ORDER BY executed_at DESC",
            (since,),
        ).fetchall()

    def _generate() -> object:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "decision_id", "alert_id", "alert_title", "alert_severity", "alert_category",
            "alert_created_at", "service_source", "tier", "decision", "action_type",
            "confidence_score", "reason", "executed_at", "not_before_at",
            "cancelled", "cancelled_at", "cancelled_by",
            "human_approved", "approved_at", "approved_by",
            "disposition", "disposition_note", "disposition_by", "disposition_at",
            "tags",
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)
        for row in rows:
            d = dict(row)
            tags = json.loads(d.get("tags_json") or "[]")
            writer.writerow([
                d.get("decision_id", ""),
                d.get("alert_id", ""),
                d.get("alert_title", ""),
                d.get("alert_severity", ""),
                d.get("alert_category", ""),
                d.get("alert_created_at", ""),
                d.get("service_source", ""),
                d.get("tier", ""),
                d.get("decision", ""),
                d.get("action_type", ""),
                d.get("confidence_score", ""),
                d.get("reason", ""),
                d.get("executed_at", ""),
                d.get("not_before_at", ""),
                bool(d.get("cancelled", 0)),
                d.get("cancelled_at", ""),
                d.get("cancelled_by", ""),
                bool(d.get("human_approved", 0)),
                d.get("approved_at", ""),
                d.get("approved_by", ""),
                d.get("disposition", ""),
                d.get("disposition_note", ""),
                d.get("disposition_by", ""),
                d.get("disposition_at", ""),
                "|".join(tags),
            ])
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

    filename = f"defender-decisions-{days}d.csv"
    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/decisions/{decision_id}", response_model=DefenderAgentDecisionItem)
def get_decision(
    decision_id: str,
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    row = defender_agent_store.get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return row


@router.post("/decisions/{decision_id}/cancel", response_model=DefenderAgentDecisionItem)
def cancel_decision(
    decision_id: str,
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    row = defender_agent_store.get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if row.get("decision") != "queue":
        raise HTTPException(status_code=400, detail="Only queued (T2) decisions can be cancelled")
    if row.get("cancelled"):
        raise HTTPException(status_code=400, detail="Decision is already cancelled")
    if row.get("job_ids"):
        raise HTTPException(status_code=400, detail="Decision has already been dispatched")
    updated = defender_agent_store.cancel_decision(
        decision_id,
        cancelled_by=str(_session.get("email") or ""),
    )
    return updated or row


@router.post("/decisions/{decision_id}/execute-now", response_model=DefenderAgentDecisionItem)
def execute_decision_now(
    decision_id: str,
    _session: dict = Depends(require_admin),
) -> dict:
    """Force-execute a T2 queued decision before its scheduled delay (admin only)."""
    _ensure_azure_site()
    row = defender_agent_store.get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if row.get("decision") != "queue":
        raise HTTPException(status_code=400, detail="Only T2 queued decisions can be force-executed")
    if row.get("cancelled"):
        raise HTTPException(status_code=400, detail="Decision has been cancelled")
    if row.get("job_ids"):
        raise HTTPException(status_code=400, detail="Decision has already been dispatched")

    from defender_agent import _dispatch_action
    from security_device_jobs import security_device_jobs as sdj
    from user_admin_jobs import user_admin_jobs

    entities = row.get("entities") or []
    reason = f"{row.get('reason', '')} [Force-executed early by {_session.get('email')}]"
    stored_ats: list[str] = row.get("action_types") or [str(row.get("action_type") or "")]
    all_job_ids: list[str] = []
    for at in stored_ats:
        jids = _dispatch_action(
            action_type=at,
            entities=entities,
            alert={},
            user_admin_jobs=user_admin_jobs,
            security_device_jobs=sdj,
            reason=reason,
            alert_severity=str(row.get("alert_severity") or ""),
        )
        all_job_ids.extend(jids)
    if all_job_ids:
        defender_agent_store.update_decision_jobs(decision_id, all_job_ids)

    return defender_agent_store.get_decision(decision_id) or row


@router.post("/decisions/{decision_id}/approve", response_model=DefenderAgentDecisionItem)
def approve_decision(
    decision_id: str,
    _session: dict = Depends(require_admin),
) -> dict:
    _ensure_azure_site()
    row = defender_agent_store.get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if row.get("human_approved"):
        raise HTTPException(status_code=400, detail="Decision is already approved")
    if row.get("cancelled"):
        raise HTTPException(status_code=400, detail="Decision has been cancelled")

    # Approve in store first
    updated = defender_agent_store.approve_decision(
        decision_id,
        approved_by=str(_session.get("email") or ""),
    )

    # Dispatch the T3 action immediately
    try:
        from defender_agent import dispatch_approved_t3, _notify_teams
        dispatch_approved_t3(decision_id)
    except Exception as exc:
        # Don't roll back the approval — the operator knows it was approved even if dispatch fails
        import logging
        logging.getLogger(__name__).warning("T3 dispatch failed after approval: %s", exc)

    # Notify Teams that the T3 was approved and dispatched
    try:
        from defender_agent import _notify_teams
        decision_data = updated or row
        _notify_teams(
            title=str(decision_data.get("alert_title") or ""),
            severity=str(decision_data.get("alert_severity") or ""),
            tier=decision_data.get("tier"),
            action_type=str(decision_data.get("action_type") or ""),
            service_source=str(decision_data.get("service_source") or ""),
            entities=decision_data.get("entities") or [],
            reason=str(decision_data.get("reason") or ""),
            is_approval=True,
        )
    except Exception:
        pass

    return updated or row


@router.post("/decisions/{decision_id}/unrestrict", response_model=DefenderAgentDecisionItem)
def unrestrict_decision_device(
    decision_id: str,
    _session: dict = Depends(require_admin),
) -> dict:
    """Remove app execution restriction from a previously restricted device (admin only)."""
    _ensure_azure_site()
    row = defender_agent_store.get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    from security_device_jobs import security_device_jobs as sdj

    device_ids = [
        e["id"] for e in (row.get("entities") or [])
        if e.get("type") == "device" and e.get("id")
    ]
    if not device_ids:
        raise HTTPException(status_code=400, detail="No device IDs found in decision entities")

    try:
        sdj.create_job(
            action_type="unrestrict_app_execution",  # type: ignore[arg-type]
            device_ids=device_ids,
            reason=f"Manual unrestrict by {_session.get('email')}",
            params={
                "device_names": device_ids,
                "reason": f"App restriction removed by {_session.get('email')}",
            },
            confirm_device_count=None,
            confirm_device_names=None,
            requested_by_email=str(_session.get("email") or ""),
            requested_by_name=str(_session.get("name") or ""),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return row


@router.post("/decisions/{decision_id}/unisolate", response_model=DefenderAgentDecisionItem)
def unisolate_decision_device(
    decision_id: str,
    _session: dict = Depends(require_admin),
) -> dict:
    """Release a previously isolated device from network isolation (admin only)."""
    _ensure_azure_site()
    row = defender_agent_store.get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    from security_device_jobs import security_device_jobs as sdj

    device_ids = [
        e["id"] for e in (row.get("entities") or [])
        if e.get("type") == "device" and e.get("id")
    ]
    if not device_ids:
        raise HTTPException(status_code=400, detail="No device IDs found in decision entities")

    try:
        sdj.create_job(
            action_type="unisolate_device",  # type: ignore[arg-type]
            device_ids=device_ids,
            reason=f"Manual unisolation by {_session.get('email')}",
            params={
                "device_names": device_ids,
                "reason": f"Released from isolation by {_session.get('email')}",
            },
            confirm_device_count=None,
            confirm_device_names=None,
            requested_by_email=str(_session.get("email") or ""),
            requested_by_name=str(_session.get("name") or ""),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return row


@router.post("/decisions/{decision_id}/force-investigate", response_model=DefenderAgentDecisionItem)
def force_investigate_decision(
    decision_id: str,
    _session: dict = Depends(require_admin),
) -> dict:
    """Manually trigger start_investigation on device(s) from a skipped decision (admin only)."""
    _ensure_azure_site()
    row = defender_agent_store.get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    from security_device_jobs import security_device_jobs as sdj

    device_ids = [
        e["id"] for e in (row.get("entities") or [])
        if e.get("type") == "device" and e.get("id")
    ]
    if not device_ids:
        raise HTTPException(status_code=400, detail="No MDE device entities in this decision")

    device_names = [
        e.get("name") or e["id"] for e in (row.get("entities") or [])
        if e.get("type") == "device" and e.get("id")
    ]
    try:
        sdj.create_job(
            action_type="start_investigation",
            device_ids=device_ids,
            reason=f"Force-investigated by {_session.get('email')} from skipped decision {decision_id}",
            params={
                "device_names": device_names,
                "reason": f"Manual escalation of skipped alert: {row.get('alert_title', '')}",
            },
            confirm_device_count=None,
            confirm_device_names=None,
            requested_by_email=str(_session.get("email") or ""),
            requested_by_name=str(_session.get("name") or ""),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return row


@router.post("/decisions/{decision_id}/enable-sign-in", response_model=DefenderAgentDecisionItem)
def enable_sign_in_decision(
    decision_id: str,
    _session: dict = Depends(require_admin),
) -> dict:
    """Re-enable sign-in for user entities from a disable_sign_in or revoke_sessions decision (admin only)."""
    _ensure_azure_site()
    row = defender_agent_store.get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    from user_admin_jobs import user_admin_jobs as uaj

    user_ids = [
        e["id"] for e in (row.get("entities") or [])
        if e.get("type") in ("user", "account") and e.get("id")
    ]
    if not user_ids:
        raise HTTPException(status_code=400, detail="No user entities found in this decision")

    try:
        uaj.create_job(
            action_type="enable_sign_in",
            target_user_ids=user_ids,
            params={"reason": f"Manual enable-sign-in for alert: {row.get('alert_title', '')}"},
            requested_by_email=str(_session.get("email") or ""),
            requested_by_name=str(_session.get("name") or ""),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return row


# ---------------------------------------------------------------------------
# Summary (for security workspace hub)
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=DefenderAgentSummaryResponse)
def get_summary(_session: dict = Depends(require_authenticated_user)) -> dict:
    _ensure_azure_site()
    return defender_agent_store.get_summary()


# ---------------------------------------------------------------------------
# Manual trigger
# ---------------------------------------------------------------------------

@router.post("/run-now")
def run_now(_session: dict = Depends(require_admin)) -> dict:
    _ensure_azure_site()
    import uuid
    run_id = uuid.uuid4().hex

    async def _fire() -> None:
        import asyncio
        from defender_agent import _run_agent_cycle
        await asyncio.get_running_loop().run_in_executor(None, _run_agent_cycle)

    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_fire())
        started = True
    except RuntimeError:
        started = False

    return {"run_id": run_id, "started": started}


# ---------------------------------------------------------------------------
# Entity timeline
# ---------------------------------------------------------------------------

@router.get("/entities/{entity_id}/timeline", response_model=DefenderAgentEntityTimelineResponse)
def get_entity_timeline(
    entity_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    decisions = defender_agent_store.get_entity_timeline(entity_id, limit=limit)
    return {"entity_id": entity_id, "decisions": decisions, "total": len(decisions)}


# ---------------------------------------------------------------------------
# Analyst disposition
# ---------------------------------------------------------------------------

@router.post("/decisions/{decision_id}/disposition", response_model=DefenderAgentDecisionItem)
def set_disposition(
    decision_id: str,
    body: DefenderAgentDispositionUpdate,
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    try:
        result = defender_agent_store.set_decision_disposition(
            decision_id,
            body.disposition,
            note=body.note,
            by=str(_session.get("email") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return result


@router.get("/disposition-stats", response_model=DefenderAgentDispositionStats)
def get_disposition_stats(
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    return defender_agent_store.get_disposition_stats()


@router.get("/metrics", response_model=DefenderAgentMetrics)
def get_agent_metrics(
    days: int = Query(default=30, ge=1, le=365),
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    return defender_agent_store.get_agent_metrics(days=days)


# ---------------------------------------------------------------------------
# Investigation notes
# ---------------------------------------------------------------------------

@router.post("/decisions/{decision_id}/notes", response_model=DefenderAgentDecisionItem)
def add_investigation_note(
    decision_id: str,
    body: DefenderAgentNoteCreate,
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    try:
        result = defender_agent_store.append_investigation_note(
            decision_id,
            body.text,
            by=str(_session.get("email") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return result


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

@router.get("/watchlist", response_model=DefenderAgentWatchlistResponse)
def list_watchlist(
    include_inactive: bool = Query(False),
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    entries = defender_agent_store.list_watchlist(include_inactive=include_inactive)
    return {"entries": entries, "total": len(entries)}


@router.post("/watchlist", response_model=DefenderAgentWatchlistEntry)
def add_watchlist_entry(
    body: DefenderAgentWatchlistCreate,
    _session: dict = Depends(require_admin),
) -> dict:
    _ensure_azure_site()
    try:
        return defender_agent_store.add_watchlist_entry(
            body.entity_type,
            body.entity_id,
            entity_name=body.entity_name,
            reason=body.reason,
            boost_tier=body.boost_tier,
            created_by=str(_session.get("email") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/watchlist/{entry_id}")
def remove_watchlist_entry(
    entry_id: str,
    _session: dict = Depends(require_admin),
) -> dict:
    _ensure_azure_site()
    found = defender_agent_store.remove_watchlist_entry(entry_id)
    if not found:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    return {"deleted": True, "id": entry_id}


# ---------------------------------------------------------------------------
# Suppressions
# ---------------------------------------------------------------------------

@router.get("/suppressions", response_model=DefenderAgentSuppressionsResponse)
def list_suppressions(
    include_inactive: bool = Query(False),
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    rows = defender_agent_store.list_suppressions(include_inactive=include_inactive)
    return {"suppressions": rows, "total": len(rows)}


@router.post("/suppressions", response_model=DefenderAgentSuppressionItem)
def create_suppression(
    body: DefenderAgentSuppressionCreate,
    _session: dict = Depends(require_admin),
) -> dict:
    _ensure_azure_site()
    row = defender_agent_store.create_suppression(
        suppression_type=body.suppression_type,
        value=body.value.strip(),
        reason=body.reason,
        created_by=str(_session.get("email") or ""),
        expires_at=body.expires_at,
    )
    return row


@router.delete("/suppressions/{suppression_id}", response_model=DefenderAgentSuppressionItem)
def delete_suppression(
    suppression_id: str,
    _session: dict = Depends(require_admin),
) -> dict:
    _ensure_azure_site()
    row = defender_agent_store.get_suppression(suppression_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Suppression not found")
    defender_agent_store.delete_suppression(suppression_id)
    return defender_agent_store.get_suppression(suppression_id) or row


# ---------------------------------------------------------------------------
# Indicator management (tenant-wide IOC blocks)
# ---------------------------------------------------------------------------

@router.get("/indicators")
def list_indicators(_session: dict = Depends(require_authenticated_user)) -> dict:
    """List all tenant-wide block indicators (requires Ti.ReadWrite.All on the app registration)."""
    _ensure_azure_site()
    from azure_client import azure_client
    items = azure_client.list_indicators()
    return {"indicators": items, "total": len(items)}


@router.delete("/indicators/{indicator_id}")
def delete_indicator(
    indicator_id: str,
    _session: dict = Depends(require_admin),
) -> dict:
    """Remove a tenant-wide block indicator (admin only)."""
    _ensure_azure_site()
    from azure_client import azure_client
    ok = azure_client.delete_indicator(indicator_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete indicator from MDE")
    return {"deleted": True, "indicator_id": indicator_id}


# ---------------------------------------------------------------------------
# Phase 17: Built-in rule management
# ---------------------------------------------------------------------------

@router.get("/rules", response_model=list[DefenderAgentBuiltinRule])
def list_rules(_session: dict = Depends(require_authenticated_user)) -> list[dict]:
    """Return all built-in classification rules with any operator overrides merged in."""
    _ensure_azure_site()
    from defender_agent import _RULES
    overrides = defender_agent_store.get_rule_overrides()
    result: list[dict] = []
    for rule in _RULES:
        rid = str(rule.get("rule_id", ""))
        ov = overrides.get(rid, {})
        title_kw = list(rule.get("title_keywords") or [])
        cat_kw = list(rule.get("category_keywords") or [])
        svc_filter = list(rule.get("service_source_contains") or [])
        action_types = list(rule.get("action_types") or ([rule["action_type"]] if rule.get("action_type") else []))
        result.append({
            "rule_id": rid,
            "title_keywords": title_kw,
            "category_keywords": cat_kw,
            "service_source_contains": svc_filter,
            "min_severity": rule.get("min_severity", "high"),
            "tier": rule["tier"],
            "decision": rule["decision"],
            "action_type": rule.get("action_type", ""),
            "action_types": action_types,
            "confidence_score": int(rule.get("confidence_score", 50)),
            "reason": rule.get("reason", ""),
            "off_hours_escalate": bool(rule.get("off_hours_escalate", False)),
            "disabled": bool(ov.get("disabled", False)),
            "override_confidence": ov.get("confidence_score"),
            "updated_at": ov.get("updated_at"),
            "updated_by": ov.get("updated_by", ""),
        })
    return result


@router.put("/rules/{rule_id}", response_model=DefenderAgentBuiltinRule)
def update_rule(
    rule_id: str,
    body: DefenderAgentRuleUpdate,
    _session: dict = Depends(require_admin),
) -> dict:
    """Override a built-in rule: disable it or adjust its confidence score."""
    _ensure_azure_site()
    from defender_agent import _RULES
    rule_ids = {str(r.get("rule_id", "")) for r in _RULES}
    if rule_id not in rule_ids:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    ov = defender_agent_store.upsert_rule_override(
        rule_id,
        disabled=body.disabled,
        confidence_score=body.confidence_score,
        updated_by=str(_session.get("email") or ""),
    )
    # Return full merged view
    rule = next((r for r in _RULES if str(r.get("rule_id", "")) == rule_id), {})
    action_types = list(rule.get("action_types") or ([rule["action_type"]] if rule.get("action_type") else []))
    return {
        "rule_id": rule_id,
        "title_keywords": list(rule.get("title_keywords") or []),
        "category_keywords": list(rule.get("category_keywords") or []),
        "service_source_contains": list(rule.get("service_source_contains") or []),
        "min_severity": rule.get("min_severity", "high"),
        "tier": rule.get("tier", 3),
        "decision": rule.get("decision", "recommend"),
        "action_type": rule.get("action_type", ""),
        "action_types": action_types,
        "confidence_score": int(rule.get("confidence_score", 50)),
        "reason": rule.get("reason", ""),
        "off_hours_escalate": bool(rule.get("off_hours_escalate", False)),
        "disabled": ov.get("disabled", False),
        "override_confidence": ov.get("confidence_score"),
        "updated_at": ov.get("updated_at"),
        "updated_by": ov.get("updated_by", ""),
    }


# ---------------------------------------------------------------------------
# Phase 18: Custom detection rules
# ---------------------------------------------------------------------------

@router.get("/custom-rules", response_model=list[DefenderAgentCustomRule])
def list_custom_rules(
    enabled_only: bool = Query(False),
    _session: dict = Depends(require_authenticated_user),
) -> list[dict]:
    _ensure_azure_site()
    return defender_agent_store.list_custom_rules(enabled_only=enabled_only)


@router.post("/custom-rules", response_model=DefenderAgentCustomRule)
def create_custom_rule(
    body: DefenderAgentCustomRuleCreate,
    _session: dict = Depends(require_admin),
) -> dict:
    _ensure_azure_site()
    return defender_agent_store.create_custom_rule(
        name=body.name,
        match_field=body.match_field,
        match_value=body.match_value.strip(),
        match_mode=body.match_mode,
        tier=body.tier,
        action_type=body.action_type,
        confidence_score=body.confidence_score,
        created_by=str(_session.get("email") or ""),
    )


@router.delete("/custom-rules/{rule_id}")
def delete_custom_rule(
    rule_id: str,
    _session: dict = Depends(require_admin),
) -> dict:
    _ensure_azure_site()
    found = defender_agent_store.delete_custom_rule(rule_id)
    if not found:
        raise HTTPException(status_code=404, detail="Custom rule not found")
    return {"deleted": True, "id": rule_id}


@router.put("/custom-rules/{rule_id}/toggle", response_model=DefenderAgentCustomRule)
def toggle_custom_rule(
    rule_id: str,
    enabled: bool = Query(...),
    _session: dict = Depends(require_admin),
) -> dict:
    _ensure_azure_site()
    result = defender_agent_store.toggle_custom_rule(rule_id, enabled=enabled)
    if result is None:
        raise HTTPException(status_code=404, detail="Custom rule not found")
    return result


# ---------------------------------------------------------------------------
# Phase 19: Alert tagging
# ---------------------------------------------------------------------------

@router.get("/tags")
def list_known_tags(_session: dict = Depends(require_authenticated_user)) -> dict:
    _ensure_azure_site()
    tags = defender_agent_store.list_known_tags()
    return {"tags": tags}


@router.post("/decisions/{decision_id}/tags/{tag}", response_model=DefenderAgentDecisionItem)
def add_decision_tag(
    decision_id: str,
    tag: str,
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    try:
        result = defender_agent_store.add_decision_tag(decision_id, tag)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return result


@router.delete("/decisions/{decision_id}/tags/{tag}", response_model=DefenderAgentDecisionItem)
def remove_decision_tag(
    decision_id: str,
    tag: str,
    _session: dict = Depends(require_authenticated_user),
) -> dict:
    _ensure_azure_site()
    result = defender_agent_store.remove_decision_tag(decision_id, tag)
    if result is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return result
