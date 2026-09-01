"""FastAPI routes for the quarantine auto-release job."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from auth import require_admin
from quarantine_release_job import quarantine_release_job

router = APIRouter(prefix="/api/quarantine-release", tags=["quarantine-release"])


class PatchSettingsRequest(BaseModel):
    enabled: bool | None = None
    allowed_domains: list[str] | None = None


def _last_run(job) -> dict[str, Any] | None:
    with job._conn() as conn:
        row = conn.execute(
            "SELECT run_hour, ran_at, domains_checked, checked_count, released_count, failed_count, error "
            "FROM quarantine_release_runs ORDER BY run_hour DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row is not None else None


def _status_payload(job) -> dict[str, Any]:
    settings = job._get_settings()
    return {
        "enabled": settings["enabled"],
        "allowed_domains": settings["allowed_domains"],
        "last_run": _last_run(job),
    }


@router.get("/status", dependencies=[Depends(require_admin)])
async def get_status() -> dict[str, Any]:
    return _status_payload(quarantine_release_job)


@router.get("/runs", dependencies=[Depends(require_admin)])
async def get_runs(
    limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)
) -> dict[str, Any]:
    ph = quarantine_release_job._placeholder()
    with quarantine_release_job._conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS cnt FROM quarantine_release_runs").fetchone()["cnt"]
        rows = conn.execute(
            "SELECT run_hour, ran_at, domains_checked, checked_count, released_count, failed_count, error "
            f"FROM quarantine_release_runs ORDER BY run_hour DESC LIMIT {ph} OFFSET {ph}",
            (limit, offset),
        ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.get("/releases", dependencies=[Depends(require_admin)])
async def get_releases(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    run_hour: str | None = None,
) -> dict[str, Any]:
    ph = quarantine_release_job._placeholder()
    columns = (
        "id, run_hour, message_identity, sender_address, recipient_address, "
        "subject, received_at, quarantine_reason, status, error, released_at"
    )
    with quarantine_release_job._conn() as conn:
        if run_hour:
            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM quarantine_releases WHERE run_hour = {ph}",
                (run_hour,),
            ).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT {columns} FROM quarantine_releases WHERE run_hour = {ph} "
                f"ORDER BY released_at DESC LIMIT {ph} OFFSET {ph}",
                (run_hour, limit, offset),
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) AS cnt FROM quarantine_releases").fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT {columns} FROM quarantine_releases ORDER BY released_at DESC LIMIT {ph} OFFSET {ph}",
                (limit, offset),
            ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.patch("/settings")
async def patch_settings(
    body: PatchSettingsRequest,
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    current = quarantine_release_job._get_settings()
    enabled = current["enabled"] if body.enabled is None else body.enabled
    domains = current["allowed_domains"] if body.allowed_domains is None else body.allowed_domains
    updated_at = datetime.now(timezone.utc).isoformat()
    updated_by = user.get("email") or user.get("name") or "unknown"
    ph = quarantine_release_job._placeholder()
    with quarantine_release_job._conn() as conn:
        conn.execute(
            f"INSERT INTO quarantine_release_settings (id, enabled, allowed_domains, updated_at, updated_by) "
            f"VALUES (1, {ph}, {ph}, {ph}, {ph}) "
            f"ON CONFLICT (id) DO UPDATE SET "
            f"enabled = excluded.enabled, allowed_domains = excluded.allowed_domains, "
            f"updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (1 if enabled else 0, ",".join(domains), updated_at, updated_by),
        )
    return _status_payload(quarantine_release_job)
