"""Azure security workspace routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_authenticated_user, session_can_manage_users
from azure_cache import azure_cache
from models import (
    SecurityAccessReviewResponse,
    SecurityAppHygieneResponse,
    SecurityFindingException,
    SecurityFindingExceptionCreateRequest,
    SecurityDeviceActionBatchResult,
    SecurityDeviceActionBatchStatus,
    SecurityBreakGlassValidationResponse,
    SecurityConditionalAccessTrackerResponse,
    SecurityDeviceActionJob,
    SecurityDeviceActionJobResult,
    SecurityDeviceActionRequest,
    SecurityDeviceComplianceResponse,
    SecurityDeviceFixPlanExecuteRequest,
    SecurityDeviceFixPlanRequest,
    SecurityDeviceFixPlanResponse,
    SecurityDirectoryRoleReviewResponse,
    SecurityWorkspaceSummaryResponse,
)
from security_application_hygiene import build_security_application_hygiene
from security_access_review import build_security_access_review
from security_break_glass_validation import build_security_break_glass_validation
from security_conditional_access_tracker import build_security_conditional_access_tracker
from security_device_compliance import build_security_device_compliance_review, build_security_device_fix_plan
from security_device_jobs import SecurityDeviceJobError, security_device_jobs
from security_directory_role_review import build_security_directory_role_review
from security_finding_exception_store import security_finding_exception_store
from security_workspace_summary import build_security_workspace_summary
from site_context import get_current_site_scope

router = APIRouter(prefix="/api/azure/security")


def _ensure_azure_site() -> None:
    if get_current_site_scope() != "azure":
        raise HTTPException(
            status_code=404,
            detail="Azure security APIs are only available on azure.movedocs.com",
        )


@router.get("/access-review", response_model=SecurityAccessReviewResponse)
def get_security_access_review(
    _session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityAccessReviewResponse:
    _ensure_azure_site()
    return build_security_access_review()


@router.get("/workspace-summary", response_model=SecurityWorkspaceSummaryResponse)
def get_security_workspace_summary(
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityWorkspaceSummaryResponse:
    _ensure_azure_site()
    return build_security_workspace_summary(session)


@router.get("/finding-exceptions", response_model=list[SecurityFindingException])
def list_security_finding_exceptions(
    scope: Literal["directory_user"] = Query(default="directory_user"),
    active_only: bool = Query(default=True),
    _session: dict[str, Any] = Depends(require_authenticated_user),
) -> list[SecurityFindingException]:
    _ensure_azure_site()
    return [
        SecurityFindingException.model_validate(item)
        for item in security_finding_exception_store.list_exceptions(scope=scope, active_only=active_only)
    ]


@router.post("/finding-exceptions", response_model=SecurityFindingException)
def create_security_finding_exception(
    body: SecurityFindingExceptionCreateRequest,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityFindingException:
    _ensure_azure_site()
    return SecurityFindingException.model_validate(
        security_finding_exception_store.upsert_exception(
            scope=body.scope,
            finding_key=body.finding_key,
            finding_label=body.finding_label,
            entity_id=body.entity_id,
            entity_label=body.entity_label,
            entity_subtitle=body.entity_subtitle,
            reason=body.reason,
            actor_email=str(session.get("email") or ""),
            actor_name=str(session.get("name") or ""),
        )
    )


@router.post("/finding-exceptions/{exception_id}/restore", response_model=SecurityFindingException)
def restore_security_finding_exception(
    exception_id: str,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityFindingException:
    _ensure_azure_site()
    payload = security_finding_exception_store.restore_exception(
        exception_id,
        actor_email=str(session.get("email") or ""),
        actor_name=str(session.get("name") or ""),
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Security finding exception not found.")
    return SecurityFindingException.model_validate(payload)


@router.get("/app-hygiene", response_model=SecurityAppHygieneResponse)
def get_security_app_hygiene(
    _session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityAppHygieneResponse:
    _ensure_azure_site()
    return build_security_application_hygiene()


@router.get("/break-glass-validation", response_model=SecurityBreakGlassValidationResponse)
def get_security_break_glass_validation(
    _session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityBreakGlassValidationResponse:
    _ensure_azure_site()
    return build_security_break_glass_validation()


@router.get("/conditional-access-tracker", response_model=SecurityConditionalAccessTrackerResponse)
def get_security_conditional_access_tracker(
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityConditionalAccessTrackerResponse:
    _ensure_azure_site()
    return build_security_conditional_access_tracker(session)


@router.get("/directory-role-review", response_model=SecurityDirectoryRoleReviewResponse)
def get_security_directory_role_review(
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityDirectoryRoleReviewResponse:
    _ensure_azure_site()
    return build_security_directory_role_review(session)


@router.get("/device-compliance", response_model=SecurityDeviceComplianceResponse)
def get_security_device_compliance(
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityDeviceComplianceResponse:
    _ensure_azure_site()
    return build_security_device_compliance_review(session)


@router.post("/device-compliance/actions", response_model=SecurityDeviceActionJob)
def create_security_device_action_job(
    body: SecurityDeviceActionRequest,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityDeviceActionJob:
    _ensure_azure_site()
    if not session_can_manage_users(session):
        raise HTTPException(status_code=403, detail="User administration access is required to run device compliance actions.")
    try:
        return SecurityDeviceActionJob.model_validate(
            security_device_jobs.create_job(
                action_type=body.action_type,
                device_ids=body.device_ids,
                reason=body.reason,
                params=body.params,
                confirm_device_count=body.confirm_device_count,
                confirm_device_names=body.confirm_device_names,
                requested_by_email=str(session.get("email") or ""),
                requested_by_name=str(session.get("name") or ""),
            )
        )
    except SecurityDeviceJobError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/device-compliance/fix-plan", response_model=SecurityDeviceFixPlanResponse)
def preview_security_device_fix_plan(
    body: SecurityDeviceFixPlanRequest,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityDeviceFixPlanResponse:
    _ensure_azure_site()
    if not session_can_manage_users(session):
        raise HTTPException(status_code=403, detail="User administration access is required to preview device compliance fixes.")
    return build_security_device_fix_plan(session, body.device_ids)


@router.post("/device-compliance/fix-plan/execute", response_model=SecurityDeviceActionBatchStatus)
def execute_security_device_fix_plan(
    body: SecurityDeviceFixPlanExecuteRequest,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityDeviceActionBatchStatus:
    _ensure_azure_site()
    if not session_can_manage_users(session):
        raise HTTPException(status_code=403, detail="User administration access is required to run device compliance fixes.")

    plan = build_security_device_fix_plan(session, body.device_ids)
    users = {
        str(item.get("id") or ""): item
        for item in (azure_cache._snapshot("users") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }

    executable_items: list[dict[str, Any]] = []
    for item in plan.items:
        if item.action_type in {"device_sync", "device_retire"}:
            executable_items.append(
                {
                    "device_id": item.device_id,
                    "device_name": item.device_name,
                    "action_type": item.action_type,
                    "params": {},
                }
            )
        elif item.action_type == "device_reassign_primary_user":
            primary_user_id = str((body.assignment_map or {}).get(item.device_id) or "").strip()
            if not primary_user_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Select a primary user for {item.device_name} before executing the remediation plan.",
                )
            user = users.get(primary_user_id)
            if not user:
                raise HTTPException(status_code=400, detail="One or more selected primary users are no longer present in the cached directory.")
            executable_items.append(
                {
                    "device_id": item.device_id,
                    "device_name": item.device_name,
                    "action_type": "device_reassign_primary_user",
                    "params": {
                        "primary_user_id": primary_user_id,
                        "primary_user_display_name": str(
                            user.get("display_name") or user.get("principal_name") or user.get("mail") or primary_user_id
                        ),
                    },
                    "assignment_user_id": primary_user_id,
                    "assignment_user_display_name": str(
                        user.get("display_name") or user.get("principal_name") or user.get("mail") or primary_user_id
                    ),
                }
            )

    if not executable_items:
        raise HTTPException(status_code=400, detail="No smart remediation actions are available for the selected devices.")

    try:
        return SecurityDeviceActionBatchStatus.model_validate(
            security_device_jobs.create_batch(
                plan_items=executable_items,
                reason=body.reason,
                confirm_device_count=body.confirm_device_count,
                confirm_device_names=body.confirm_device_names,
                requested_by_email=str(session.get("email") or ""),
                requested_by_name=str(session.get("name") or ""),
            )
        )
    except SecurityDeviceJobError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/device-compliance/jobs/{job_id}", response_model=SecurityDeviceActionJob)
def get_security_device_action_job(
    job_id: str,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityDeviceActionJob:
    _ensure_azure_site()
    if not session_can_manage_users(session):
        raise HTTPException(status_code=403, detail="User administration access is required to view device compliance jobs.")
    job = security_device_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Device action job not found.")
    return SecurityDeviceActionJob.model_validate(job)


@router.get("/device-compliance/jobs/{job_id}/results", response_model=list[SecurityDeviceActionJobResult])
def get_security_device_action_job_results(
    job_id: str,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> list[SecurityDeviceActionJobResult]:
    _ensure_azure_site()
    if not session_can_manage_users(session):
        raise HTTPException(status_code=403, detail="User administration access is required to view device compliance job results.")
    job = security_device_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Device action job not found.")
    return [SecurityDeviceActionJobResult.model_validate(item) for item in security_device_jobs.get_job_results(job_id)]


@router.get("/device-compliance/job-batches/{batch_id}", response_model=SecurityDeviceActionBatchStatus)
def get_security_device_action_batch(
    batch_id: str,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityDeviceActionBatchStatus:
    _ensure_azure_site()
    if not session_can_manage_users(session):
        raise HTTPException(status_code=403, detail="User administration access is required to view device compliance job batches.")
    batch = security_device_jobs.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Device action batch not found.")
    return SecurityDeviceActionBatchStatus.model_validate(batch)


@router.get("/device-compliance/job-batches/{batch_id}/results", response_model=list[SecurityDeviceActionBatchResult])
def get_security_device_action_batch_results(
    batch_id: str,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> list[SecurityDeviceActionBatchResult]:
    _ensure_azure_site()
    if not session_can_manage_users(session):
        raise HTTPException(status_code=403, detail="User administration access is required to view device compliance job batches.")
    batch = security_device_jobs.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Device action batch not found.")
    return [SecurityDeviceActionBatchResult.model_validate(item) for item in security_device_jobs.get_batch_results(batch_id)]
