"""FastAPI routes for the Teams retention workspace (retention.movedocs.com)."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from auth import oauth, require_retention_access
from retention_cleanup_job import retention_cleanup_job
from retention_directory_cache import retention_directory_cache
from retention_graph_client import (
    RetentionGraphError,
    list_channels as _list_channels,
    list_teams as _list_teams,
)
from retention_graph_connection import (
    RetentionGraphConnectionError,
    retention_graph_connection,
    retention_graph_oauth_configured,
)
from retention_import_export import build_export_workbook, parse_import_workbook
from retention_policy_store import retention_policy_store
from routes_auth import _oauth_redirect_uri
from site_context import get_current_site_scope

router = APIRouter(prefix="/api/retention", tags=["retention"])

_VALID_STATUSES = {"active", "disabled", "pending_preview"}


def _ensure_retention_site() -> None:
    if get_current_site_scope() != "retention":
        raise HTTPException(status_code=404, detail="This feature is only available on retention.movedocs.com")


def _require_retention_session(session: dict[str, Any] = Depends(require_retention_access)) -> dict[str, Any]:
    """Composed gate: retention site scope + RETENTION_ALLOWED_USERS allowlist.

    Same composition pattern as _require_tools_session/_ensure_tools_site in
    routes_tools.py, so every route in this module is unreachable from the other
    hosts (it-app, oasisdev, azure, security, hrapp) instead of merely 403ing
    non-allowlisted callers there.
    """
    _ensure_retention_site()
    return session


class CreatePolicyRequest(BaseModel):
    team_id: str
    team_name: str
    channel_id: str
    channel_name: str
    retention_days: int


class UpdatePolicyRequest(BaseModel):
    retention_days: int | None = None
    status: str | None = None


@router.get("/connection/status", dependencies=[Depends(_require_retention_session)])
async def connection_status() -> dict[str, Any]:
    return retention_graph_connection.get_status()


@router.get("/connection/connect", dependencies=[Depends(_require_retention_session)])
async def connection_connect(request: Request):
    if not retention_graph_oauth_configured():
        raise HTTPException(status_code=500, detail="Retention Graph OAuth is not configured")
    client = oauth.create_client("retention_graph")
    if not client:
        raise HTTPException(status_code=500, detail="Retention Graph OAuth is not configured")
    redirect_uri = _oauth_redirect_uri(request, "retention_graph_callback")
    return await client.authorize_redirect(request, redirect_uri, prompt="select_account")


@router.get("/connection/callback", name="retention_graph_callback")
async def connection_callback(request: Request, session: dict[str, Any] = Depends(_require_retention_session)):
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


# NOTE: get_teams/get_channels are deliberately plain `def`, not `async def`.
# Both do blocking `requests`-based Graph enumeration with no await, so declaring
# them async would stall the single shared backend event loop for every other host
# (it-app, oasisdev, azure, security, hrapp) for the duration of the Graph calls.
# Plain `def` lets FastAPI run them in its threadpool, matching this repo's
# precedent for blocking-I/O handlers in routes_ad.py / routes_tools.py.
@router.get("/teams", dependencies=[Depends(_require_retention_session)])
def get_teams(
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), q: str = Query(""),
) -> dict[str, Any]:
    try:
        token = retention_graph_connection.get_valid_token()
        teams = _list_teams(token)
    except RetentionGraphConnectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RetentionGraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    active_by_team: dict[str, int] = {}
    for policy in retention_policy_store.list_active_policies():
        active_by_team[policy["team_id"]] = active_by_team.get(policy["team_id"], 0) + 1
    for team in teams:
        team["policy_count"] = active_by_team.get(team["id"], 0)
    needle = q.strip().lower()
    if needle:
        # Graph has no "search channels across every team" endpoint, so matching a
        # channel name at this top level means checking every team's channel list.
        # A live fan-out (even batched 20-teams-per-call) took 30-60+ seconds against
        # this tenant's 300+ teams, so this reads retention_directory_cache's
        # periodically-refreshed snapshot instead — results can lag actual Teams state
        # by up to the cache's refresh interval, a deliberate tradeoff for a usable
        # search box. A team missing from the snapshot (cache not warmed up yet, or a
        # team created since the last refresh) is treated as having no known channels
        # rather than failing the search.
        channels_by_team = retention_directory_cache.channels_by_team_snapshot()
        teams = [
            t for t in teams
            if needle in t["name"].lower()
            or any(needle in c["name"].lower() for c in channels_by_team.get(t["id"], []))
        ]
    return {"items": teams[offset : offset + limit], "total": len(teams)}


@router.get("/teams/{team_id}/channels", dependencies=[Depends(_require_retention_session)])
def get_channels(
    team_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), q: str = Query(""),
) -> dict[str, Any]:
    try:
        token = retention_graph_connection.get_valid_token()
        channels = _list_channels(token, team_id)
    except RetentionGraphConnectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RetentionGraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    for channel in channels:
        channel["policy"] = retention_policy_store.get_policy_for_channel(team_id, channel["id"])
    needle = q.strip().lower()
    if needle:
        channels = [c for c in channels if needle in c["name"].lower()]
    return {"items": channels[offset : offset + limit], "total": len(channels)}


@router.post("/policies", dependencies=[Depends(_require_retention_session)])
async def create_policy(
    body: CreatePolicyRequest, session: dict[str, Any] = Depends(_require_retention_session),
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


@router.get("/policies", dependencies=[Depends(_require_retention_session)])
async def list_policies(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    items, total = retention_policy_store.list_policies(limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/policies/{policy_id}/preview", dependencies=[Depends(_require_retention_session)])
async def preview_policy(policy_id: str) -> dict[str, Any]:
    try:
        return await retention_cleanup_job.compute_preview(policy_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RetentionGraphConnectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RetentionGraphError as exc:
        # A Graph read failure (403 after the service account lost owner rights,
        # sustained 429, deleted channel) must surface as an explicit upstream
        # error, not a 500 — the frontend renders it in the preview error branch
        # so Confirm & Enable is never offered next to a fabricated "0" count.
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/policies/{policy_id}/confirm", dependencies=[Depends(_require_retention_session)])
async def confirm_policy(policy_id: str) -> dict[str, Any]:
    policy = retention_policy_store.confirm_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


@router.patch("/policies/{policy_id}", dependencies=[Depends(_require_retention_session)])
async def update_policy(policy_id: str, body: UpdatePolicyRequest) -> dict[str, Any]:
    if body.retention_days is not None and not 1 <= body.retention_days <= 365:
        raise HTTPException(status_code=400, detail="retention_days must be between 1 and 365")
    if body.status is not None and body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    policy = retention_policy_store.update_policy(policy_id, retention_days=body.retention_days, status=body.status)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


@router.get("/runs", dependencies=[Depends(_require_retention_session)])
async def list_runs(
    policy_id: str | None = None, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items, total = retention_policy_store.list_runs(policy_id=policy_id, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/deletions", dependencies=[Depends(_require_retention_session)])
async def list_deletions(
    run_id: str | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items, total = retention_policy_store.list_deletions(run_id=run_id, limit=limit, offset=offset)
    return {"items": items, "total": total}


_MAX_IMPORT_FILE_BYTES = 10 * 1024 * 1024


def _require_xlsx_upload(file: UploadFile) -> None:
    filename = file.filename or "upload.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="File must be a .xlsx workbook")


def _build_import_preview(raw_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Validate parsed rows against RetentionPolicyStore and decide an action for each.

    A blank retention_days means "no change" (skip) rather than "disable" — a bulk
    import accidentally blanking a column should never silently disable existing
    policies. Duplicate (team_id, channel_id) pairs within one file are flagged as
    errors rather than both being applied, since the second would race the first.
    """
    seen: set[tuple[str, str]] = set()
    preview: list[dict[str, Any]] = []
    for raw in raw_rows:
        team_id = raw["team_id"]
        channel_id = raw["channel_id"]
        row: dict[str, Any] = {
            "team_id": team_id,
            "team_name": raw["team_name"],
            "channel_id": channel_id,
            "channel_name": raw["channel_name"],
            "current_status": None,
            "current_retention_days": None,
            "retention_days": None,
            "action": "skip",
            "error": None,
        }

        if not team_id or not channel_id:
            row["action"] = "error"
            row["error"] = "Missing team_id or channel_id"
            preview.append(row)
            continue

        key = (team_id, channel_id)
        if key in seen:
            row["action"] = "error"
            row["error"] = "Duplicate row for this channel in this file"
            preview.append(row)
            continue
        seen.add(key)

        existing = retention_policy_store.get_policy_for_channel(team_id, channel_id)
        if existing:
            row["current_status"] = existing["status"]
            row["current_retention_days"] = existing["retention_days"]

        retention_days_raw = raw["retention_days"]
        if not retention_days_raw:
            preview.append(row)  # no change requested for this row
            continue

        try:
            retention_days = int(float(retention_days_raw))
        except ValueError:
            row["action"] = "error"
            row["error"] = "retention_days must be a whole number"
            preview.append(row)
            continue
        if not 1 <= retention_days <= 365:
            row["action"] = "error"
            row["error"] = "retention_days must be between 1 and 365"
            preview.append(row)
            continue

        row["retention_days"] = retention_days
        if existing:
            row["action"] = "update"
        elif not raw["team_name"] or not raw["channel_name"]:
            row["action"] = "error"
            row["error"] = "team_name and channel_name are required to create a new policy"
        else:
            row["action"] = "create"
        preview.append(row)
    return preview


def _apply_import_rows(preview_rows: list[dict[str, Any]], *, created_by: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in preview_rows:
        result = dict(row)
        action = row["action"]
        if action not in ("create", "update"):
            result["result"] = "skipped"
            results.append(result)
            continue
        try:
            existing = retention_policy_store.get_policy_for_channel(row["team_id"], row["channel_id"])
            if action == "create":
                # Re-check for a race: another operator (or a confirm click elsewhere)
                # may have created this policy between preview and apply.
                if existing:
                    result["result"] = "failed"
                    result["error"] = "A policy already exists for this channel"
                else:
                    retention_policy_store.create_policy(
                        team_id=row["team_id"], team_name=row["team_name"],
                        channel_id=row["channel_id"], channel_name=row["channel_name"],
                        retention_days=row["retention_days"], created_by=created_by,
                    )
                    result["result"] = "created"
            else:
                if not existing:
                    result["result"] = "failed"
                    result["error"] = "Policy no longer exists for this channel"
                else:
                    retention_policy_store.update_policy(existing["id"], retention_days=row["retention_days"])
                    result["result"] = "updated"
        except Exception as exc:
            result["result"] = "failed"
            result["error"] = str(exc)
        results.append(result)
    return results


@router.get("/export", dependencies=[Depends(_require_retention_session)])
def export_channels() -> FileResponse:
    """Export every known team/channel with its current policy state. Blocking
    Graph call for team names, so this is a plain def like get_teams/get_channels
    to run in FastAPI's threadpool rather than the shared event loop."""
    try:
        token = retention_graph_connection.get_valid_token()
        teams = _list_teams(token)
    except RetentionGraphConnectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RetentionGraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    channels_by_team = retention_directory_cache.channels_by_team_snapshot()
    rows: list[dict[str, Any]] = []
    for team in teams:
        for channel in channels_by_team.get(team["id"], []):
            policy = retention_policy_store.get_policy_for_channel(team["id"], channel["id"])
            rows.append({
                "team_id": team["id"],
                "team_name": team["name"],
                "channel_id": channel["id"],
                "channel_name": channel["name"],
                "current_status": policy["status"] if policy else "none",
                "current_retention_days": policy["retention_days"] if policy else None,
                "retention_days": policy["retention_days"] if policy else None,
            })

    wb = build_export_workbook(rows)
    now = datetime.now(timezone.utc)
    filename = f"retention_channels_{now.strftime('%Y%m%d_%H%M')}.xlsx"
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp_path = tmp.name
    tmp.close()
    wb.save(tmp_path)
    return FileResponse(
        path=tmp_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(os.unlink, tmp_path),
    )


@router.post("/import/preview", dependencies=[Depends(_require_retention_session)])
async def import_preview(file: UploadFile = File(...)) -> dict[str, Any]:
    _require_xlsx_upload(file)
    content = await file.read()
    if len(content) > _MAX_IMPORT_FILE_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")
    try:
        raw_rows = parse_import_workbook(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rows": _build_import_preview(raw_rows)}


@router.post("/import/apply", dependencies=[Depends(_require_retention_session)])
async def import_apply(
    file: UploadFile = File(...), session: dict[str, Any] = Depends(_require_retention_session),
) -> dict[str, Any]:
    _require_xlsx_upload(file)
    content = await file.read()
    if len(content) > _MAX_IMPORT_FILE_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")
    try:
        raw_rows = parse_import_workbook(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    preview_rows = _build_import_preview(raw_rows)
    results = _apply_import_rows(preview_rows, created_by=str(session.get("email") or ""))
    return {"rows": results}
