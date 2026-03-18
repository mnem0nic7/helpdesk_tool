"""API routes for the Azure portal site."""

from __future__ import annotations

import asyncio
import csv
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from starlette.background import BackgroundTask

from ai_client import (
    answer_azure_cost_question,
    get_available_copilot_models,
    get_default_copilot_model_id,
)
from auth import is_admin_user, require_admin, require_authenticated_user
from azure_cache import azure_cache
from azure_vm_export_jobs import azure_vm_export_jobs
from models import (
    AzureCostChatRequest,
    AzureVirtualMachineCostExportJobCreateRequest,
    AzureVirtualMachineCostExportJobResponse,
    AzureVirtualMachineDetailResponse,
)
from site_context import get_current_site_scope

router = APIRouter(prefix="/api/azure")

_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
_HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center")


def _ensure_azure_site() -> None:
    if get_current_site_scope() != "azure":
        raise HTTPException(status_code=404, detail="Azure portal APIs are only available on azure.movedocs.com")


def _safe_export_text(value: Any) -> str:
    text = str(value or "")
    if text and text[0] in ("=", "+", "-", "@"):
        return "\t" + text
    return text


def _coverage_label(delta: Any) -> str:
    if delta is None:
        return "Unavailable"
    try:
        amount = int(delta)
    except (TypeError, ValueError):
        return "Unavailable"
    if amount > 0:
        return f"{amount} needed"
    if amount < 0:
        return f"{abs(amount)} excess"
    return "Balanced"


def _vm_coverage_export_rows() -> list[dict[str, Any]]:
    payload = azure_cache.list_virtual_machines()
    rows: list[dict[str, Any]] = []
    for item in payload.get("by_size") or []:
        rows.append(
            {
                "SKU": _safe_export_text(item.get("label") or ""),
                "Region": _safe_export_text(item.get("region") or ""),
                "VMs": int(item.get("vm_count") or 0),
                "Reserved Instances (RI)": (
                    int(item.get("reserved_instance_count") or 0)
                    if item.get("reserved_instance_count") is not None
                    else ""
                ),
                "Needed / Excess": _safe_export_text(_coverage_label(item.get("delta"))),
            }
        )
    return rows


def _vm_excess_export_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in azure_cache.get_vm_excess_reservation_report():
        rows.append(
            {
                "SKU": _safe_export_text(item.get("label") or ""),
                "Region": _safe_export_text(item.get("region") or ""),
                "VMs": int(item.get("vm_count") or 0),
                "Reserved Instances (RI)": int(item.get("reserved_instance_count") or 0),
                "Excess": int(item.get("excess_count") or 0),
                "Active Reservation Names": _safe_export_text(
                    "; ".join(item.get("active_reservation_names") or [])
                ),
            }
        )
    return rows


def _delete_file(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _build_vm_coverage_file_response(path: str, filename: str, media_type: str) -> FileResponse:
    return FileResponse(
        path,
        filename=filename,
        media_type=media_type,
        background=BackgroundTask(_delete_file, path),
    )


def _get_export_job_or_404(job_id: str) -> dict[str, Any]:
    job = azure_vm_export_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Azure VM cost export job was not found")
    return job


def _ensure_export_job_access(job_id: str, session: dict[str, Any]) -> dict[str, Any]:
    job = _get_export_job_or_404(job_id)
    if not azure_vm_export_jobs.job_belongs_to(
        job_id,
        str(session.get("email") or ""),
        is_admin=is_admin_user(str(session.get("email") or "")),
    ):
        raise HTTPException(status_code=403, detail="You do not have access to this Azure VM export job")
    return job


@router.get("/status")
async def get_status() -> dict[str, Any]:
    _ensure_azure_site()
    return azure_cache.status()


@router.post("/refresh")
async def refresh_azure(
    background_tasks: BackgroundTasks,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    _ensure_azure_site()
    if azure_cache.status().get("refreshing"):
        return {**azure_cache.status(), "message": "Refresh already in progress"}

    async def _run() -> None:
        await asyncio.get_running_loop().run_in_executor(None, azure_cache.trigger_refresh)

    background_tasks.add_task(_run)
    return {**azure_cache.status(), "started": True}


@router.get("/overview")
async def get_overview() -> dict[str, Any]:
    _ensure_azure_site()
    return azure_cache.get_overview()


@router.get("/subscriptions")
async def list_subscriptions() -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_cache._snapshot("subscriptions") or []


@router.get("/management-groups")
async def list_management_groups() -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_cache._snapshot("management_groups") or []


@router.get("/role-assignments")
async def list_role_assignments(
    search: str = Query(default=""),
    subscription_id: str = Query(default=""),
) -> list[dict[str, Any]]:
    _ensure_azure_site()
    rows = azure_cache._snapshot("role_assignments") or []
    search_lower = search.strip().lower()
    subscription_lower = subscription_id.strip().lower()
    result: list[dict[str, Any]] = []
    for item in rows:
        if subscription_lower and str(item.get("subscription_id") or "").lower() != subscription_lower:
            continue
        if search_lower:
            haystack = " ".join(
                [
                    str(item.get("scope") or ""),
                    str(item.get("principal_id") or ""),
                    str(item.get("principal_type") or ""),
                    str(item.get("role_name") or ""),
                ]
            ).lower()
            if search_lower not in haystack:
                continue
        result.append(item)
    return result


@router.get("/resources")
async def get_resources(
    search: str = Query(default=""),
    subscription_id: str = Query(default=""),
    resource_group: str = Query(default=""),
    resource_type: str = Query(default=""),
    location: str = Query(default=""),
    state: str = Query(default=""),
    tag_key: str = Query(default=""),
    tag_value: str = Query(default=""),
) -> dict[str, Any]:
    _ensure_azure_site()
    return azure_cache.list_resources(
        search=search,
        subscription_id=subscription_id,
        resource_group=resource_group,
        resource_type=resource_type,
        location=location,
        state=state,
        tag_key=tag_key,
        tag_value=tag_value,
    )


@router.get("/vms")
async def get_virtual_machines(
    search: str = Query(default=""),
    subscription_id: str = Query(default=""),
    resource_group: str = Query(default=""),
    location: str = Query(default=""),
    state: str = Query(default=""),
    size: str = Query(default=""),
) -> dict[str, Any]:
    _ensure_azure_site()
    return azure_cache.list_virtual_machines(
        search=search,
        subscription_id=subscription_id,
        resource_group=resource_group,
        location=location,
        state=state,
        size=size,
    )


@router.get("/vms/detail")
async def get_virtual_machine_detail(resource_id: str = Query(default="")) -> AzureVirtualMachineDetailResponse:
    _ensure_azure_site()
    detail = azure_cache.get_virtual_machine_detail(resource_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Virtual machine was not found in the Azure cache")
    return AzureVirtualMachineDetailResponse.model_validate(detail)


@router.post("/vms/cost-export-jobs", status_code=202)
async def create_virtual_machine_cost_export_job(
    body: AzureVirtualMachineCostExportJobCreateRequest,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> AzureVirtualMachineCostExportJobResponse:
    _ensure_azure_site()
    try:
        job = azure_vm_export_jobs.create_job(
            recipient_email=str(session.get("email") or ""),
            requester_name=str(session.get("name") or ""),
            scope=body.scope,
            lookback_days=int(body.lookback_days),
            filters=body.filters.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AzureVirtualMachineCostExportJobResponse.model_validate(job)


@router.get("/vms/cost-export-jobs/{job_id}")
async def get_virtual_machine_cost_export_job(
    job_id: str,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> AzureVirtualMachineCostExportJobResponse:
    _ensure_azure_site()
    job = _ensure_export_job_access(job_id, session)
    return AzureVirtualMachineCostExportJobResponse.model_validate(job)


@router.get("/vms/cost-export-jobs/{job_id}/download")
async def download_virtual_machine_cost_export_job(
    job_id: str,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> FileResponse:
    _ensure_azure_site()
    job = _ensure_export_job_access(job_id, session)
    if str(job.get("status") or "") != "completed":
        raise HTTPException(status_code=409, detail="Azure VM export is not ready yet")

    file_path = str(job.get("file_path") or "")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=410, detail="Azure VM export file is no longer available")

    return FileResponse(
        file_path,
        filename=str(job.get("file_name") or os.path.basename(file_path)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/vms/coverage/export.csv")
async def export_virtual_machine_coverage_csv() -> FileResponse:
    _ensure_azure_site()
    rows = _vm_coverage_export_rows()
    now = datetime.now(timezone.utc)
    filename = f"azure_vm_coverage_{now.strftime('%Y%m%d_%H%M')}.csv"
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    fieldnames = ["SKU", "Region", "VMs", "Reserved Instances (RI)", "Needed / Excess"]
    try:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        tmp.flush()
    finally:
        tmp.close()
    return _build_vm_coverage_file_response(tmp.name, filename, "text/csv; charset=utf-8")


@router.get("/vms/coverage/export.xlsx")
async def export_virtual_machine_coverage_excel() -> FileResponse:
    _ensure_azure_site()
    rows = _vm_coverage_export_rows()
    now = datetime.now(timezone.utc)
    filename = f"azure_vm_coverage_{now.strftime('%Y%m%d_%H%M')}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "VM Coverage"
    headers = ["SKU", "Region", "VMs", "Reserved Instances (RI)", "Needed / Excess"]
    for column_index, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=column_index, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _HEADER_ALIGNMENT

    for row_index, row in enumerate(rows, 2):
        ws.cell(row=row_index, column=1, value=row["SKU"])
        ws.cell(row=row_index, column=2, value=row["Region"])
        ws.cell(row=row_index, column=3, value=row["VMs"])
        ws.cell(row=row_index, column=4, value=row["Reserved Instances (RI)"])
        ws.cell(row=row_index, column=5, value=row["Needed / Excess"])

    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 24
    ws.column_dimensions["E"].width = 18

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    try:
        wb.save(tmp.name)
    finally:
        tmp.close()
    return _build_vm_coverage_file_response(
        tmp.name,
        filename,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/vms/excess/export.csv")
async def export_virtual_machine_excess_csv() -> FileResponse:
    _ensure_azure_site()
    rows = _vm_excess_export_rows()
    now = datetime.now(timezone.utc)
    filename = f"azure_vm_ri_excess_{now.strftime('%Y%m%d_%H%M')}.csv"
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    fieldnames = ["SKU", "Region", "VMs", "Reserved Instances (RI)", "Excess", "Active Reservation Names"]
    try:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        tmp.flush()
    finally:
        tmp.close()
    return _build_vm_coverage_file_response(tmp.name, filename, "text/csv; charset=utf-8")


@router.get("/vms/excess/export.xlsx")
async def export_virtual_machine_excess_excel() -> FileResponse:
    _ensure_azure_site()
    rows = _vm_excess_export_rows()
    now = datetime.now(timezone.utc)
    filename = f"azure_vm_ri_excess_{now.strftime('%Y%m%d_%H%M')}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "VM RI Excess"
    headers = ["SKU", "Region", "VMs", "Reserved Instances (RI)", "Excess", "Active Reservation Names"]
    for column_index, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=column_index, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _HEADER_ALIGNMENT

    for row_index, row in enumerate(rows, 2):
        ws.cell(row=row_index, column=1, value=row["SKU"])
        ws.cell(row=row_index, column=2, value=row["Region"])
        ws.cell(row=row_index, column=3, value=row["VMs"])
        ws.cell(row=row_index, column=4, value=row["Reserved Instances (RI)"])
        ws.cell(row=row_index, column=5, value=row["Excess"])
        ws.cell(row=row_index, column=6, value=row["Active Reservation Names"])

    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 24
    ws.column_dimensions["E"].width = 10
    ws.column_dimensions["F"].width = 56

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    try:
        wb.save(tmp.name)
    finally:
        tmp.close()
    return _build_vm_coverage_file_response(
        tmp.name,
        filename,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/directory/users")
async def get_users(search: str = Query(default="")) -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_cache.list_directory_objects("users", search=search)


@router.get("/directory/groups")
async def get_groups(search: str = Query(default="")) -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_cache.list_directory_objects("groups", search=search)


@router.get("/directory/enterprise-apps")
async def get_enterprise_apps(search: str = Query(default="")) -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_cache.list_directory_objects("service_principals", search=search)


@router.get("/directory/app-registrations")
async def get_app_registrations(search: str = Query(default="")) -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_cache.list_directory_objects("applications", search=search)


@router.get("/directory/roles")
async def get_directory_roles(search: str = Query(default="")) -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_cache.list_directory_objects("directory_roles", search=search)


@router.get("/cost/summary")
async def get_cost_summary() -> dict[str, Any]:
    _ensure_azure_site()
    return azure_cache.get_cost_summary()


@router.get("/cost/trend")
async def get_cost_trend() -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_cache.get_cost_trend()


@router.get("/cost/breakdown")
async def get_cost_breakdown(group_by: str = Query(default="service")) -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_cache.get_cost_breakdown(group_by)


@router.get("/advisor")
async def get_advisor() -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_cache.get_advisor()


@router.get("/storage")
async def get_storage() -> dict[str, Any]:
    _ensure_azure_site()
    return azure_cache.get_storage_summary()


@router.get("/compute/optimization")
async def get_compute_optimization() -> dict[str, Any]:
    _ensure_azure_site()
    return azure_cache.get_compute_optimization()


@router.get("/ai/models")
async def get_ai_models() -> list[dict[str, str]]:
    _ensure_azure_site()
    return [model.model_dump() for model in get_available_copilot_models()]


@router.post("/ai/cost-chat")
async def post_cost_chat(body: AzureCostChatRequest) -> dict[str, Any]:
    _ensure_azure_site()
    available = get_available_copilot_models()
    if not available:
        raise HTTPException(status_code=400, detail="No AI model available for the Azure copilot")
    available_ids = {model.id for model in available}
    model_id = body.model or get_default_copilot_model_id(available)
    if not model_id:
        raise HTTPException(status_code=400, detail="No AI model available for the Azure copilot")
    if model_id not in available_ids:
        raise HTTPException(status_code=400, detail=f"Model '{model_id}' is not available")
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question is required")
    result = answer_azure_cost_question(
        body.question,
        azure_cache.get_grounding_context(),
        model_id,
    )
    return result.model_dump()
