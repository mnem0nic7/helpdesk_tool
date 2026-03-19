"""Primary-site user administration APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import is_admin_user, require_authenticated_user
from models import (
    UserAdminAuditEntryResponse,
    UserAdminCapabilitiesResponse,
    UserAdminDeviceResponse,
    UserAdminGroupMembershipResponse,
    UserAdminJobCreateRequest,
    UserAdminJobResponse,
    UserAdminJobResultResponse,
    UserAdminLicenseResponse,
    UserAdminMailboxResponse,
    UserAdminRoleResponse,
    UserAdminUserDetailResponse,
)
from site_context import get_current_site_scope
from user_admin_jobs import user_admin_jobs
from user_admin_providers import UserAdminProviderError, user_admin_providers

router = APIRouter(prefix="/api/user-admin")


def _ensure_primary_site() -> None:
    if get_current_site_scope() != "primary":
        raise HTTPException(
            status_code=404,
            detail="User administration APIs are only available on it-app.movedocs.com",
        )


@router.get("/capabilities", response_model=UserAdminCapabilitiesResponse)
def get_user_admin_capabilities(session: dict = Depends(require_authenticated_user)):
    del session
    _ensure_primary_site()
    return user_admin_providers.get_capabilities()


@router.get("/users/{user_id}/detail", response_model=UserAdminUserDetailResponse)
def get_user_detail(user_id: str, session: dict = Depends(require_authenticated_user)):
    del session
    _ensure_primary_site()
    try:
        return user_admin_providers.get_user_detail(user_id)
    except UserAdminProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/users/{user_id}/groups", response_model=list[UserAdminGroupMembershipResponse])
def get_user_groups(user_id: str, session: dict = Depends(require_authenticated_user)):
    del session
    _ensure_primary_site()
    try:
        return user_admin_providers.list_groups(user_id)
    except UserAdminProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/users/{user_id}/licenses", response_model=list[UserAdminLicenseResponse])
def get_user_licenses(user_id: str, session: dict = Depends(require_authenticated_user)):
    del session
    _ensure_primary_site()
    try:
        return user_admin_providers.list_licenses(user_id)
    except UserAdminProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/users/{user_id}/roles", response_model=list[UserAdminRoleResponse])
def get_user_roles(user_id: str, session: dict = Depends(require_authenticated_user)):
    del session
    _ensure_primary_site()
    try:
        return user_admin_providers.list_roles(user_id)
    except UserAdminProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/users/{user_id}/mailbox", response_model=UserAdminMailboxResponse)
def get_user_mailbox(user_id: str, session: dict = Depends(require_authenticated_user)):
    del session
    _ensure_primary_site()
    try:
        return user_admin_providers.get_mailbox(user_id)
    except UserAdminProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/users/{user_id}/devices", response_model=list[UserAdminDeviceResponse])
def get_user_devices(user_id: str, session: dict = Depends(require_authenticated_user)):
    del session
    _ensure_primary_site()
    try:
        return user_admin_providers.list_devices(user_id)
    except UserAdminProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/users/{user_id}/activity", response_model=list[UserAdminAuditEntryResponse])
def get_user_activity(
    user_id: str,
    limit: int = Query(50, ge=1, le=200),
    session: dict = Depends(require_authenticated_user),
):
    del session
    _ensure_primary_site()
    return user_admin_jobs.list_audit(limit=limit, target_user_id=user_id)


@router.post("/jobs", response_model=UserAdminJobResponse)
def create_user_admin_job(
    body: UserAdminJobCreateRequest,
    session: dict = Depends(require_authenticated_user),
):
    _ensure_primary_site()
    try:
        return user_admin_jobs.create_job(
            action_type=body.action_type,
            target_user_ids=body.target_user_ids,
            params=body.params,
            requested_by_email=str(session.get("email") or ""),
            requested_by_name=str(session.get("name") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs/{job_id}", response_model=UserAdminJobResponse)
def get_user_admin_job(job_id: str, session: dict = Depends(require_authenticated_user)):
    _ensure_primary_site()
    if not user_admin_jobs.job_belongs_to(job_id, str(session.get("email") or ""), is_admin=is_admin_user(str(session.get("email") or ""))):
        raise HTTPException(status_code=404, detail="Job not found")
    job = user_admin_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/{job_id}/results", response_model=list[UserAdminJobResultResponse])
def get_user_admin_job_results(job_id: str, session: dict = Depends(require_authenticated_user)):
    _ensure_primary_site()
    if not user_admin_jobs.job_belongs_to(job_id, str(session.get("email") or ""), is_admin=is_admin_user(str(session.get("email") or ""))):
        raise HTTPException(status_code=404, detail="Job not found")
    if not user_admin_jobs.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return user_admin_jobs.get_job_results(job_id)


@router.get("/audit", response_model=list[UserAdminAuditEntryResponse])
def get_user_admin_audit(
    limit: int = Query(100, ge=1, le=500),
    session: dict = Depends(require_authenticated_user),
):
    del session
    _ensure_primary_site()
    return user_admin_jobs.list_audit(limit=limit)
