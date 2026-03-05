"""API routes for custom SLA tracking with configurable targets and business hours."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from issue_cache import cache
from sla_engine import sla_config, compute_sla_for_issues

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sla")


@router.get("/metrics")
async def get_sla_metrics(
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Compute custom SLA metrics for all filtered issues, optionally narrowed by date range."""
    issues = cache.get_filtered_issues()
    return compute_sla_for_issues(issues, date_from=date_from, date_to=date_to)


@router.get("/config")
async def get_sla_config() -> dict[str, Any]:
    """Return current SLA targets and business hours settings."""
    return {
        "settings": sla_config.get_settings(),
        "targets": sla_config.get_targets(),
    }


@router.post("/config/targets")
async def set_sla_target(body: dict[str, Any]) -> dict[str, Any]:
    """Create or update an SLA target."""
    sla_type = body.get("sla_type")
    dimension = body.get("dimension", "default")
    dimension_value = body.get("dimension_value", "*")
    target_minutes = body.get("target_minutes")

    if sla_type not in ("first_response", "resolution"):
        raise HTTPException(400, "sla_type must be 'first_response' or 'resolution'")
    if dimension not in ("default", "priority", "request_type"):
        raise HTTPException(400, "dimension must be 'default', 'priority', or 'request_type'")
    if not isinstance(target_minutes, (int, float)) or target_minutes <= 0:
        raise HTTPException(400, "target_minutes must be a positive number")

    return sla_config.set_target(sla_type, dimension, dimension_value, int(target_minutes))


@router.delete("/config/targets/{target_id}")
async def delete_sla_target(target_id: int) -> dict[str, Any]:
    """Delete an SLA target by ID."""
    if not sla_config.delete_target(target_id):
        raise HTTPException(404, f"Target {target_id} not found")
    return {"deleted": True}


@router.put("/config/settings")
async def update_sla_settings(body: dict[str, str]) -> dict[str, str]:
    """Update business hours settings."""
    allowed_keys = {"business_hours_start", "business_hours_end",
                    "business_timezone", "business_days"}
    filtered = {k: v for k, v in body.items() if k in allowed_keys}
    if not filtered:
        raise HTTPException(400, "No valid settings provided")
    return sla_config.update_settings(filtered)
