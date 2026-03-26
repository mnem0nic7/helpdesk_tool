"""Shared tools routes for the primary and Azure hosts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import list_login_audit, require_tools_access
from azure_cache import azure_cache
from models import (
    AppLoginAuditEventResponse,
    OneDriveCopyJobCreateRequest,
    OneDriveCopyJobResponse,
    OneDriveCopyUserOptionResponse,
)
from onedrive_copy_jobs import onedrive_copy_jobs
from site_context import get_current_site_scope

router = APIRouter(prefix="/api/tools/onedrive-copy")


def _ensure_tools_site() -> str:
    scope = get_current_site_scope()
    if scope not in {"primary", "azure"}:
        raise HTTPException(status_code=404, detail="Tools are only available on it-app.movedocs.com and azure.movedocs.com")
    return scope


def _require_tools_session(session: dict[str, Any] = Depends(require_tools_access)) -> dict[str, Any]:
    _ensure_tools_site()
    return session


@router.get("/users", response_model=list[OneDriveCopyUserOptionResponse])
def search_onedrive_copy_users(
    search: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> list[OneDriveCopyUserOptionResponse]:
    rows = azure_cache.list_directory_objects("users", search=search)
    normalized = [
        {
            "id": str(row.get("id") or ""),
            "display_name": str(row.get("display_name") or ""),
            "principal_name": str(row.get("principal_name") or ""),
            "mail": str(row.get("mail") or ""),
            "enabled": row.get("enabled"),
        }
        for row in rows
        if str(row.get("id") or "").strip()
    ]
    normalized.sort(key=lambda row: (str(row["display_name"]).lower(), str(row["principal_name"]).lower()))
    return [OneDriveCopyUserOptionResponse.model_validate(row) for row in normalized[:limit]]


@router.post("/jobs", response_model=OneDriveCopyJobResponse, status_code=202)
def create_onedrive_copy_job(
    body: OneDriveCopyJobCreateRequest,
    session: dict[str, Any] = Depends(_require_tools_session),
) -> OneDriveCopyJobResponse:
    scope = get_current_site_scope()
    try:
        job = onedrive_copy_jobs.create_job(
            site_scope=scope,
            source_upn=body.source_upn,
            destination_upn=body.destination_upn,
            destination_folder=body.destination_folder,
            test_mode=bool(body.test_mode),
            test_file_limit=int(body.test_file_limit),
            exclude_system_folders=bool(body.exclude_system_folders),
            requested_by_email=str(session.get("email") or ""),
            requested_by_name=str(session.get("name") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OneDriveCopyJobResponse.model_validate(job)


@router.get("/jobs", response_model=list[OneDriveCopyJobResponse])
def list_onedrive_copy_jobs(
    limit: int = Query(default=100, ge=1, le=200),
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> list[OneDriveCopyJobResponse]:
    return [OneDriveCopyJobResponse.model_validate(job) for job in onedrive_copy_jobs.list_jobs(limit=limit)]


@router.get("/jobs/{job_id}", response_model=OneDriveCopyJobResponse)
def get_onedrive_copy_job(
    job_id: str,
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> OneDriveCopyJobResponse:
    job = onedrive_copy_jobs.get_job(job_id, include_events=True)
    if not job:
        raise HTTPException(status_code=404, detail="OneDrive copy job was not found")
    return OneDriveCopyJobResponse.model_validate(job)


@router.get("/login-audit", response_model=list[AppLoginAuditEventResponse])
def get_login_audit(
    limit: int = Query(default=100, ge=1, le=200),
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> list[AppLoginAuditEventResponse]:
    return [AppLoginAuditEventResponse.model_validate(row) for row in list_login_audit(limit=limit)]
