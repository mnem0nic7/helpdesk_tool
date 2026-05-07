"""FastAPI routes for the password expiry notifier."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_admin, require_authenticated_user
from config import AD_MAX_PWD_AGE_DAYS, PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE
from password_expiry_notifier import password_expiry_notifier

router = APIRouter(prefix="/api/password-expiry-notifier", tags=["password-expiry-notifier"])


class PatchSettingsRequest(BaseModel):
    enabled: bool


def _last_run(notifier) -> dict[str, Any] | None:
    with notifier._conn() as conn:
        row = conn.execute(
            "SELECT run_date, ran_at, users_notified, test_mode "
            "FROM password_expiry_notify_runs ORDER BY run_date DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row is not None else None


def _status_payload(notifier) -> dict[str, Any]:
    return {
        "enabled": notifier._get_notify_enabled(),
        "last_run": _last_run(notifier),
        "config": {
            "max_age_days": AD_MAX_PWD_AGE_DAYS,
            "days_before": PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE,
        },
    }


@router.get("/status", dependencies=[Depends(require_authenticated_user)])
async def get_status() -> dict[str, Any]:
    return _status_payload(password_expiry_notifier)


@router.get("/runs", dependencies=[Depends(require_authenticated_user)])
async def get_runs(limit: int = 30, offset: int = 0) -> dict[str, Any]:
    limit = min(limit, 100)
    with password_expiry_notifier._conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS cnt FROM password_expiry_notify_runs"
        ).fetchone()["cnt"]
        rows = conn.execute(
            "SELECT run_date, ran_at, users_notified, test_mode "
            "FROM password_expiry_notify_runs ORDER BY run_date DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.get("/notifications", dependencies=[Depends(require_authenticated_user)])
async def get_notifications(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit = min(limit, 100)
    with password_expiry_notifier._conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS cnt FROM password_expiry_notifications"
        ).fetchone()["cnt"]
        rows = conn.execute(
            "SELECT id, sam_account_name, email, expiry_date, days_until_expiry, notified_at, test_mode "
            "FROM password_expiry_notifications ORDER BY notified_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.patch("/settings")
async def patch_settings(
    body: PatchSettingsRequest,
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    updated_at = datetime.now(timezone.utc).isoformat()
    updated_by = user.get("email") or user.get("name") or "unknown"
    ph = password_expiry_notifier._placeholder()
    with password_expiry_notifier._conn() as conn:
        conn.execute(
            f"INSERT INTO password_expiry_notifier_settings (id, enabled, updated_at, updated_by) "
            f"VALUES (1, {ph}, {ph}, {ph}) "
            f"ON CONFLICT (id) DO UPDATE SET "
            f"enabled = excluded.enabled, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (1 if body.enabled else 0, updated_at, updated_by),
        )
    return _status_payload(password_expiry_notifier)
