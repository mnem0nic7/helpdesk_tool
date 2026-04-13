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
        from defender_agent import dispatch_approved_t3
        dispatch_approved_t3(decision_id)
    except Exception as exc:
        # Don't roll back the approval — the operator knows it was approved even if dispatch fails
        import logging
        logging.getLogger(__name__).warning("T3 dispatch failed after approval: %s", exc)

    return updated or row


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
