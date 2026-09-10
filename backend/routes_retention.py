"""FastAPI routes for the Teams retention workspace (retention.movedocs.com)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from auth import oauth, require_retention_access
from retention_cleanup_job import retention_cleanup_job
from retention_graph_client import list_channels as _list_channels, list_teams as _list_teams
from retention_graph_connection import (
    RetentionGraphConnectionError,
    retention_graph_connection,
    retention_graph_oauth_configured,
)
from retention_policy_store import retention_policy_store
from routes_auth import _oauth_redirect_uri

router = APIRouter(prefix="/api/retention", tags=["retention"])

_VALID_STATUSES = {"active", "disabled", "pending_preview"}


class CreatePolicyRequest(BaseModel):
    team_id: str
    team_name: str
    channel_id: str
    channel_name: str
    retention_days: int


class UpdatePolicyRequest(BaseModel):
    retention_days: int | None = None
    status: str | None = None


@router.get("/connection/status", dependencies=[Depends(require_retention_access)])
async def connection_status() -> dict[str, Any]:
    return retention_graph_connection.get_status()


@router.get("/connection/connect", dependencies=[Depends(require_retention_access)])
async def connection_connect(request: Request):
    if not retention_graph_oauth_configured():
        raise HTTPException(status_code=500, detail="Retention Graph OAuth is not configured")
    client = oauth.create_client("retention_graph")
    if not client:
        raise HTTPException(status_code=500, detail="Retention Graph OAuth is not configured")
    redirect_uri = _oauth_redirect_uri(request, "retention_graph_callback")
    return await client.authorize_redirect(request, redirect_uri, prompt="select_account")


@router.get("/connection/callback", name="retention_graph_callback")
async def connection_callback(request: Request, session: dict[str, Any] = Depends(require_retention_access)):
    client = oauth.create_client("retention_graph")
    if not client:
        raise HTTPException(status_code=500, detail="Retention Graph OAuth is not configured")
    token = await client.authorize_access_token(request)
    access_token = str(token.get("access_token") or "").strip()
    refresh_token = str(token.get("refresh_token") or "").strip()
    expires_in = int(token.get("expires_in") or 3600)
    if not access_token or not refresh_token:
        raise HTTPException(status_code=400, detail="Retention Graph OAuth response was missing required tokens")
    userinfo = token.get("userinfo") or {}
    service_account_upn = str(userinfo.get("preferred_username") or userinfo.get("email") or "")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(expires_in - 60, 60))
    retention_graph_connection.save_connection(
        service_account_upn=service_account_upn,
        refresh_token=refresh_token,
        access_token=access_token,
        access_token_expires_at=expires_at,
        connected_by=str(session.get("email") or ""),
    )
    return RedirectResponse(url="/")


@router.get("/teams", dependencies=[Depends(require_retention_access)])
async def get_teams(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    token = retention_graph_connection.get_valid_token()
    teams = _list_teams(token)
    active_by_team: dict[str, int] = {}
    for policy in retention_policy_store.list_active_policies():
        active_by_team[policy["team_id"]] = active_by_team.get(policy["team_id"], 0) + 1
    for team in teams:
        team["policy_count"] = active_by_team.get(team["id"], 0)
    return {"items": teams[offset : offset + limit], "total": len(teams)}


@router.get("/teams/{team_id}/channels", dependencies=[Depends(require_retention_access)])
async def get_channels(
    team_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    token = retention_graph_connection.get_valid_token()
    channels = _list_channels(token, team_id)
    for channel in channels:
        channel["policy"] = retention_policy_store.get_policy_for_channel(team_id, channel["id"])
    return {"items": channels[offset : offset + limit], "total": len(channels)}


@router.post("/policies", dependencies=[Depends(require_retention_access)])
async def create_policy(
    body: CreatePolicyRequest, session: dict[str, Any] = Depends(require_retention_access),
) -> dict[str, Any]:
    if not 1 <= body.retention_days <= 365:
        raise HTTPException(status_code=400, detail="retention_days must be between 1 and 365")
    if retention_policy_store.get_policy_for_channel(body.team_id, body.channel_id):
        raise HTTPException(status_code=409, detail="A policy already exists for this channel")
    return retention_policy_store.create_policy(
        team_id=body.team_id, team_name=body.team_name, channel_id=body.channel_id,
        channel_name=body.channel_name, retention_days=body.retention_days,
        created_by=str(session.get("email") or ""),
    )


@router.get("/policies", dependencies=[Depends(require_retention_access)])
async def list_policies(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    items, total = retention_policy_store.list_policies(limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/policies/{policy_id}/preview", dependencies=[Depends(require_retention_access)])
async def preview_policy(policy_id: str) -> dict[str, Any]:
    try:
        return await retention_cleanup_job.compute_preview(policy_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RetentionGraphConnectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/policies/{policy_id}/confirm", dependencies=[Depends(require_retention_access)])
async def confirm_policy(policy_id: str) -> dict[str, Any]:
    policy = retention_policy_store.confirm_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


@router.patch("/policies/{policy_id}", dependencies=[Depends(require_retention_access)])
async def update_policy(policy_id: str, body: UpdatePolicyRequest) -> dict[str, Any]:
    if body.retention_days is not None and not 1 <= body.retention_days <= 365:
        raise HTTPException(status_code=400, detail="retention_days must be between 1 and 365")
    if body.status is not None and body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    policy = retention_policy_store.update_policy(policy_id, retention_days=body.retention_days, status=body.status)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


@router.get("/runs", dependencies=[Depends(require_retention_access)])
async def list_runs(
    policy_id: str | None = None, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items, total = retention_policy_store.list_runs(policy_id=policy_id, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/deletions", dependencies=[Depends(require_retention_access)])
async def list_deletions(
    run_id: str | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items, total = retention_policy_store.list_deletions(run_id=run_id, limit=limit, offset=offset)
    return {"items": items, "total": total}
