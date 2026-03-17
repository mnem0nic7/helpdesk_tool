"""API routes for the Azure portal site."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from ai_client import (
    answer_azure_cost_question,
    get_available_copilot_models,
    get_default_copilot_model_id,
)
from auth import require_admin
from azure_cache import azure_cache
from models import AzureCostChatRequest
from site_context import get_current_site_scope

router = APIRouter(prefix="/api/azure")


def _ensure_azure_site() -> None:
    if get_current_site_scope() != "azure":
        raise HTTPException(status_code=404, detail="Azure portal APIs are only available on azure.movedocs.com")


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
