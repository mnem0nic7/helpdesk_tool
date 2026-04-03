"""Azure security workspace routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from auth import require_authenticated_user, session_can_manage_users
from models import (
    SecurityAccessReviewResponse,
    SecurityAppHygieneResponse,
    SecurityBreakGlassValidationResponse,
    SecurityConditionalAccessTrackerResponse,
    SecurityDeviceActionJob,
    SecurityDeviceActionJobResult,
    SecurityDeviceActionRequest,
    SecurityDeviceComplianceResponse,
    SecurityDirectoryRoleReviewResponse,
)
from security_application_hygiene import build_security_application_hygiene
from security_access_review import build_security_access_review
from security_break_glass_validation import build_security_break_glass_validation
from security_conditional_access_tracker import build_security_conditional_access_tracker
from security_device_compliance import build_security_device_compliance_review
from security_device_jobs import SecurityDeviceJobError, security_device_jobs
from security_directory_role_review import build_security_directory_role_review
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
