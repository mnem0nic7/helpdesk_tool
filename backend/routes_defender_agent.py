"""REST routes for the Defender autonomous agent."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_admin, require_authenticated_user
from defender_agent_store import defender_agent_store
from models import (
    DefenderAgentConfigResponse,
    DefenderAgentConfigUpdate,
    DefenderAgentDecisionItem,
    DefenderAgentDecisionsResponse,
    DefenderAgentRunResponse,
    DefenderAgentSummaryResponse,
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
    if row.get("decision") != "recommend":
        raise HTTPException(status_code=400, detail="Only T3 recommended decisions can be approved")
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
    if row.get("action_type") != "restrict_app_execution":
        raise HTTPException(status_code=400, detail="Only app-restriction decisions can be unrestricted")
    if not row.get("job_ids"):
        raise HTTPException(status_code=400, detail="App restriction was never applied (no jobs dispatched)")

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
    if row.get("action_type") != "isolate_device":
        raise HTTPException(status_code=400, detail="Only isolation decisions can be unisolated")
    if not row.get("job_ids"):
        raise HTTPException(status_code=400, detail="Device was never isolated (no jobs dispatched)")

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
    if row.get("decision") != "skip":
        raise HTTPException(status_code=400, detail="Only skipped decisions can be force-investigated")

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
