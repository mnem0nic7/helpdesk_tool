"""Shared tools routes for the primary and Azure hosts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import list_login_audit, require_tools_access
from azure_cache import azure_cache
from models import (
    AppLoginAuditEventResponse,
    MailboxRulesResponse,
    OneDriveCopyJobCreateRequest,
    OneDriveCopyJobResponse,
    OneDriveCopyUserOptionResponse,
)
from onedrive_copy_jobs import onedrive_copy_jobs
from site_context import get_current_site_scope
from user_admin_providers import UserAdminProviderError, user_admin_providers

router = APIRouter(prefix="/api/tools")


def _ensure_tools_site() -> str:
    scope = get_current_site_scope()
    if scope not in {"primary", "azure"}:
        raise HTTPException(status_code=404, detail="Tools are only available on it-app.movedocs.com and azure.movedocs.com")
    return scope


def _require_tools_session(session: dict[str, Any] = Depends(require_tools_access)) -> dict[str, Any]:
    _ensure_tools_site()
    return session


def _normalized_upn(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_user_option(row: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    principal_name = str(row.get("principal_name") or "").strip()
    mail = str(row.get("mail") or "").strip()
    normalized_upn = _normalized_upn(principal_name or mail)
    if not normalized_upn:
        return None
    return {
        "id": str(row.get("id") or (f"{source}:{normalized_upn}")),
        "display_name": str(row.get("display_name") or "").strip(),
        "principal_name": principal_name or normalized_upn,
        "mail": mail,
        "enabled": row.get("enabled"),
        "source": "entra" if source == "entra" else "saved",
    }


def _find_exact_entra_user(upn: str) -> dict[str, Any] | None:
    normalized_upn = _normalized_upn(upn)
    if not normalized_upn:
        return None
    for row in azure_cache.list_directory_objects("users", search=upn):
        option = _normalize_user_option(row, source="entra")
        if not option:
            continue
        if normalized_upn in {
            _normalized_upn(option.get("principal_name")),
            _normalized_upn(option.get("mail")),
        }:
            return option
    return None


@router.get("/onedrive-copy/users", response_model=list[OneDriveCopyUserOptionResponse])
def search_onedrive_copy_users(
    search: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> list[OneDriveCopyUserOptionResponse]:
    normalized_options: list[dict[str, Any]] = []
    seen: set[str] = set()

    if search.strip():
        entra_rows = []
        for row in azure_cache.list_directory_objects("users", search=search):
            option = _normalize_user_option(row, source="entra")
            if not option:
                continue
            entra_rows.append(option)
        entra_rows.sort(key=lambda row: (str(row["display_name"]).lower(), str(row["principal_name"]).lower()))
        for option in entra_rows:
            normalized_upn = _normalized_upn(option.get("principal_name") or option.get("mail"))
            if not normalized_upn or normalized_upn in seen:
                continue
            seen.add(normalized_upn)
            normalized_options.append(option)

    for row in onedrive_copy_jobs.list_saved_user_options(search=search, limit=limit):
        option = _normalize_user_option(row, source="saved")
        if not option:
            continue
        normalized_upn = _normalized_upn(option.get("principal_name") or option.get("mail"))
        if not normalized_upn or normalized_upn in seen:
            continue
        seen.add(normalized_upn)
        normalized_options.append(option)
        if len(normalized_options) >= limit:
            break

    return [OneDriveCopyUserOptionResponse.model_validate(row) for row in normalized_options[:limit]]


@router.post("/onedrive-copy/jobs", response_model=OneDriveCopyJobResponse, status_code=202)
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
    for upn in (body.source_upn, body.destination_upn):
        exact_match = _find_exact_entra_user(upn)
        if exact_match:
            onedrive_copy_jobs.remember_user_option(
                upn,
                display_name=str(exact_match.get("display_name") or ""),
                principal_name=str(exact_match.get("principal_name") or ""),
                mail=str(exact_match.get("mail") or ""),
                source_hint="entra",
                used_by_email=str(session.get("email") or ""),
            )
    return OneDriveCopyJobResponse.model_validate(job)


@router.get("/onedrive-copy/jobs", response_model=list[OneDriveCopyJobResponse])
def list_onedrive_copy_jobs(
    limit: int = Query(default=100, ge=1, le=200),
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> list[OneDriveCopyJobResponse]:
    return [OneDriveCopyJobResponse.model_validate(job) for job in onedrive_copy_jobs.list_jobs(limit=limit)]


@router.get("/onedrive-copy/jobs/{job_id}", response_model=OneDriveCopyJobResponse)
def get_onedrive_copy_job(
    job_id: str,
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> OneDriveCopyJobResponse:
    job = onedrive_copy_jobs.get_job(job_id, include_events=True)
    if not job:
        raise HTTPException(status_code=404, detail="OneDrive copy job was not found")
    return OneDriveCopyJobResponse.model_validate(job)


@router.get("/onedrive-copy/login-audit", response_model=list[AppLoginAuditEventResponse])
def get_login_audit(
    limit: int = Query(default=100, ge=1, le=200),
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> list[AppLoginAuditEventResponse]:
    return [AppLoginAuditEventResponse.model_validate(row) for row in list_login_audit(limit=limit)]


@router.get("/mailbox-rules", response_model=MailboxRulesResponse)
def list_mailbox_rules(
    mailbox: str = Query(..., min_length=3, max_length=320),
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> MailboxRulesResponse:
    try:
        return MailboxRulesResponse.model_validate(user_admin_providers.list_mailbox_rules(mailbox))
    except UserAdminProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
