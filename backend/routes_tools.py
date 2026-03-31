"""Shared tools routes for the primary and Azure hosts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import list_login_audit, require_tools_access
from azure_cache import azure_cache
from models import (
    AppLoginAuditEventResponse,
    DelegateMailboxJobCreateRequest,
    DelegateMailboxJobResponse,
    DelegateMailboxesResponse,
    MailboxDelegatesResponse,
    MailboxRulesResponse,
    OneDriveCopyJobCreateRequest,
    OneDriveCopyJobResponse,
    OneDriveCopyUserOptionResponse,
)
from mailbox_delegate_scan_jobs import mailbox_delegate_scan_jobs
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


def _friendly_mailbox_rules_error(message: str) -> str:
    text = str(message or "").strip()
    if (
        "mailFolders/inbox/messageRules" in text
        and "ErrorAccessDenied" in text
        and "(403)" in text
    ):
        return (
            "Mailbox rule lookup is not enabled for the shared Graph app yet. "
            "The Entra app registration needs Microsoft Graph application permission "
            "MailboxSettings.Read with admin consent before this tool can list Inbox rules."
        )
    return text


def _friendly_mailbox_delegate_error(message: str) -> str:
    text = str(message or "").strip()
    if "adminapi/v2.0" in text and "(403)" in text:
        return (
            "Mailbox delegation lookup is not enabled for the shared Exchange app yet. "
            "The Entra app registration needs Office 365 Exchange Online application permission "
            "Exchange.ManageAsAppV2 with admin consent plus an Exchange RBAC role such as Recipient Management "
            "before this tool can read mailbox delegation."
        )
    if "pwsh is not installed" in text or "ExchangeOnlineManagement" in text or "Connect-ExchangeOnline" in text:
        return (
            "Mailbox delegation lookup needs Exchange Online PowerShell support on the app runtime. "
            "Install pwsh plus the ExchangeOnlineManagement module so the app can read Send As and Full Access."
        )
    return text


def _ensure_delegate_scan_job_access(job_id: str, session: dict[str, Any]) -> dict[str, Any]:
    job = mailbox_delegate_scan_jobs.get_job(job_id, include_events=True)
    if not job:
        raise HTTPException(status_code=404, detail="Mailbox delegate scan job was not found")
    if not mailbox_delegate_scan_jobs.job_belongs_to(job_id, str(session.get("email") or ""), is_admin=bool(session.get("is_admin"))):
        raise HTTPException(status_code=403, detail="You do not have access to this mailbox delegate scan job")
    return job


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


@router.post("/onedrive-copy/jobs/clear-finished")
def clear_finished_onedrive_copy_jobs(
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> dict[str, Any]:
    deleted_count = onedrive_copy_jobs.clear_finished_jobs()
    return {"deleted_count": int(deleted_count)}


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
        raise HTTPException(status_code=502, detail=_friendly_mailbox_rules_error(str(exc))) from exc


@router.get("/mailbox-delegates", response_model=MailboxDelegatesResponse)
def list_mailbox_delegates(
    mailbox: str = Query(..., min_length=3, max_length=320),
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> MailboxDelegatesResponse:
    try:
        return MailboxDelegatesResponse.model_validate(user_admin_providers.list_mailbox_delegates(mailbox))
    except UserAdminProviderError as exc:
        raise HTTPException(status_code=502, detail=_friendly_mailbox_delegate_error(str(exc))) from exc


@router.get("/delegate-mailboxes", response_model=DelegateMailboxesResponse)
def list_delegate_mailboxes(
    user: str = Query(..., min_length=3, max_length=320),
    _session: dict[str, Any] = Depends(_require_tools_session),
) -> DelegateMailboxesResponse:
    try:
        return DelegateMailboxesResponse.model_validate(user_admin_providers.list_delegate_mailboxes_for_user(user))
    except UserAdminProviderError as exc:
        raise HTTPException(status_code=502, detail=_friendly_mailbox_delegate_error(str(exc))) from exc


@router.post("/delegate-mailboxes/jobs", response_model=DelegateMailboxJobResponse, status_code=202)
def create_delegate_mailbox_job(
    body: DelegateMailboxJobCreateRequest,
    session: dict[str, Any] = Depends(_require_tools_session),
) -> DelegateMailboxJobResponse:
    scope = get_current_site_scope()
    try:
        job = mailbox_delegate_scan_jobs.create_job(
            site_scope=scope,
            user=body.user,
            requested_by_email=str(session.get("email") or ""),
            requested_by_name=str(session.get("name") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    exact_match = _find_exact_entra_user(body.user)
    if exact_match:
        onedrive_copy_jobs.remember_user_option(
            body.user,
            display_name=str(exact_match.get("display_name") or ""),
            principal_name=str(exact_match.get("principal_name") or ""),
            mail=str(exact_match.get("mail") or ""),
            source_hint="entra",
            used_by_email=str(session.get("email") or ""),
        )
    else:
        onedrive_copy_jobs.remember_user_option(
            body.user,
            principal_name=body.user,
            source_hint="manual",
            used_by_email=str(session.get("email") or ""),
        )
    return DelegateMailboxJobResponse.model_validate(job)


@router.get("/delegate-mailboxes/jobs", response_model=list[DelegateMailboxJobResponse])
def list_delegate_mailbox_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    session: dict[str, Any] = Depends(_require_tools_session),
) -> list[DelegateMailboxJobResponse]:
    jobs = mailbox_delegate_scan_jobs.list_jobs_for_user(str(session.get("email") or ""), limit=limit)
    return [DelegateMailboxJobResponse.model_validate(job) for job in jobs]


@router.post("/delegate-mailboxes/jobs/clear-finished")
def clear_finished_delegate_mailbox_jobs(
    session: dict[str, Any] = Depends(_require_tools_session),
) -> dict[str, Any]:
    deleted_count = mailbox_delegate_scan_jobs.clear_finished_jobs_for_user(str(session.get("email") or ""))
    return {"deleted_count": int(deleted_count)}


@router.get("/delegate-mailboxes/jobs/{job_id}", response_model=DelegateMailboxJobResponse)
def get_delegate_mailbox_job(
    job_id: str,
    session: dict[str, Any] = Depends(_require_tools_session),
) -> DelegateMailboxJobResponse:
    job = _ensure_delegate_scan_job_access(job_id, session)
    return DelegateMailboxJobResponse.model_validate(job)


@router.post("/delegate-mailboxes/jobs/{job_id}/cancel")
def cancel_delegate_mailbox_job(
    job_id: str,
    session: dict[str, Any] = Depends(_require_tools_session),
) -> dict[str, Any]:
    _ensure_delegate_scan_job_access(job_id, session)
    cancelled = mailbox_delegate_scan_jobs.cancel_job(job_id)
    if cancelled:
        return {"cancelled": True, "message": "Mailbox delegate scan cancelled."}
    return {"cancelled": False, "message": "Mailbox delegate scan is already finished."}
