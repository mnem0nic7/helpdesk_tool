"""API routes for metrics and SLA data."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from config import JIRA_PROJECT
from jira_client import JiraClient
from metrics import (
    compute_headline_metrics,
    compute_monthly_volumes,
    compute_weekly_volumes,
    compute_age_buckets,
    compute_ttr_distribution,
    compute_priority_counts,
    compute_assignee_stats,
    compute_sla_summary,
    extract_sla_status,
    issue_to_row,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Shared client instance
_client = JiraClient()

# Base JQL that excludes oasisdev tickets
_BASE_JQL = f'project = {JIRA_PROJECT} AND labels not in ("oasisdev")'

# SLA custom-field IDs
_SLA_FIELD_IDS = [
    "customfield_11266",
    "customfield_11264",
    "customfield_11267",
    "customfield_11268",
]


@router.get("/metrics")
async def get_metrics() -> dict[str, Any]:
    """Return all dashboard metrics computed from the full OIT issue set."""
    issues = _client.search_all(_BASE_JQL)
    return {
        "headline": compute_headline_metrics(issues),
        "weekly_volumes": compute_weekly_volumes(issues),
        "age_buckets": compute_age_buckets(issues),
        "ttr_distribution": compute_ttr_distribution(issues),
        "priority_counts": compute_priority_counts(issues),
        "assignee_stats": compute_assignee_stats(issues),
    }


@router.get("/sla/summary")
async def get_sla_summary() -> dict[str, Any]:
    """Return SLA timer summaries for all JSM SLA timers."""
    issues = _client.search_all(_BASE_JQL)
    return {"timers": compute_sla_summary(issues)}


@router.get("/sla/breaches")
async def get_sla_breaches() -> dict[str, Any]:
    """Return tickets that have any BREACHED SLA timer."""
    issues = _client.search_all(_BASE_JQL)

    breaches: list[dict[str, Any]] = []
    for issue in issues:
        fields = issue.get("fields", {})
        has_breach = False
        for field_id in _SLA_FIELD_IDS:
            sla_val = fields.get(field_id)
            status = extract_sla_status(sla_val)
            if status == "BREACHED":
                has_breach = True
                break
        if has_breach:
            breaches.append(issue_to_row(issue))

    return {"breaches": breaches}
