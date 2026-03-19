"""Primary-site user exit workflow APIs and Windows agent bridge."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from auth import require_authenticated_user
from config import USER_EXIT_AGENT_SHARED_SECRET
from models import (
    UserExitAgentClaimRequest,
    UserExitAgentClaimResponse,
    UserExitAgentCompleteRequest,
    UserExitAgentHeartbeatRequest,
    UserExitManualTaskCompleteRequest,
    UserExitPreflightResponse,
    UserExitRetryStepRequest,
    UserExitWorkflowCreateRequest,
    UserExitWorkflowResponse,
)
from site_context import get_current_site_scope
from user_admin_providers import UserAdminProviderError
from user_exit_workflows import UserExitWorkflowError, user_exit_workflows

router = APIRouter(prefix="/api/user-exit")


def _ensure_primary_site() -> None:
    if get_current_site_scope() != "primary":
        raise HTTPException(
            status_code=404,
            detail="User exit workflow APIs are only available on it-app.movedocs.com",
        )


def _require_agent_secret(x_user_exit_agent_secret: str | None = Header(default=None)) -> None:
    _ensure_primary_site()
    expected = USER_EXIT_AGENT_SHARED_SECRET.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="User exit agent secret is not configured")
    if (x_user_exit_agent_secret or "").strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid user exit agent secret")


@router.get("/users/{user_id}/preflight", response_model=UserExitPreflightResponse)
def get_user_exit_preflight(
    user_id: str,
    session: dict = Depends(require_authenticated_user),
):
    del session
    _ensure_primary_site()
    try:
        return user_exit_workflows.build_preflight(user_id)
    except UserExitWorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UserAdminProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/workflows", response_model=UserExitWorkflowResponse)
def create_user_exit_workflow(
    body: UserExitWorkflowCreateRequest,
    session: dict = Depends(require_authenticated_user),
):
    _ensure_primary_site()
    try:
        return user_exit_workflows.create_workflow(
            user_id=body.user_id,
            typed_upn_confirmation=body.typed_upn_confirmation,
            on_prem_sam_account_name_override=body.on_prem_sam_account_name_override,
            requested_by_email=str(session.get("email") or ""),
            requested_by_name=str(session.get("name") or ""),
        )
    except UserExitWorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UserAdminProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}", response_model=UserExitWorkflowResponse)
def get_user_exit_workflow(
    workflow_id: str,
    session: dict = Depends(require_authenticated_user),
):
    del session
    _ensure_primary_site()
    workflow = user_exit_workflows.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Exit workflow not found")
    return workflow


@router.post("/workflows/{workflow_id}/retry-step", response_model=UserExitWorkflowResponse)
def retry_user_exit_workflow_step(
    workflow_id: str,
    body: UserExitRetryStepRequest,
    session: dict = Depends(require_authenticated_user),
):
    del session
    _ensure_primary_site()
    try:
        return user_exit_workflows.retry_step(workflow_id, body.step_id)
    except UserExitWorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/manual-tasks/{task_id}/complete", response_model=UserExitWorkflowResponse)
def complete_user_exit_manual_task(
    workflow_id: str,
    task_id: str,
    body: UserExitManualTaskCompleteRequest,
    session: dict = Depends(require_authenticated_user),
):
    _ensure_primary_site()
    try:
        return user_exit_workflows.complete_manual_task(
            workflow_id,
            task_id,
            actor_email=str(session.get("email") or ""),
            actor_name=str(session.get("name") or ""),
            notes=body.notes,
        )
    except UserExitWorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/agent/steps/claim", response_model=UserExitAgentClaimResponse | None)
def claim_user_exit_agent_step(
    body: UserExitAgentClaimRequest,
    _: None = Depends(_require_agent_secret),
):
    return user_exit_workflows.claim_agent_step(agent_id=body.agent_id, profile_keys=body.profile_keys)


@router.post("/agent/steps/{step_id}/heartbeat", status_code=204)
def heartbeat_user_exit_agent_step(
    step_id: str,
    body: UserExitAgentHeartbeatRequest,
    _: None = Depends(_require_agent_secret),
):
    try:
        user_exit_workflows.heartbeat_agent_step(step_id=step_id, agent_id=body.agent_id)
    except UserExitWorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return None


@router.post("/agent/steps/{step_id}/complete", response_model=UserExitWorkflowResponse)
def complete_user_exit_agent_step(
    step_id: str,
    body: UserExitAgentCompleteRequest,
    _: None = Depends(_require_agent_secret),
):
    try:
        return user_exit_workflows.complete_agent_step(
            step_id=step_id,
            agent_id=body.agent_id,
            status=body.status,
            summary=body.summary,
            error=body.error,
            before_summary=body.before_summary,
            after_summary=body.after_summary,
        )
    except UserExitWorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
