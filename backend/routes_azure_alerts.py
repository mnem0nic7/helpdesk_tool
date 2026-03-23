"""Azure alert rule CRUD and evaluation routes."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from auth import require_admin, require_authenticated_user
from azure_alert_engine import TRIGGER_SCHEMA, _evaluate_rule, parse_azure_alert_rule
from azure_alert_store import azure_alert_store
from models import (
    AzureAlertHistoryItem,
    AzureAlertRuleCreate,
    AzureAlertRuleResponse,
    AzureAlertRuleUpdate,
    AzureAlertTestResponse,
    AzureChatParseRequest,
    AzureChatParseResponse,
)
from site_context import get_current_site_scope

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/azure/alerts")


def _ensure_azure_site() -> None:
    if get_current_site_scope() != "azure":
        raise HTTPException(
            status_code=404,
            detail="Azure portal APIs are only available on azure.movedocs.com",
        )


def _get_rule_or_404(rule_id: str) -> dict[str, Any]:
    rule = azure_alert_store.get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return rule


def _validate_delivery(recipients: str, teams_url: str) -> None:
    if not recipients.strip() and not teams_url.strip():
        raise HTTPException(
            status_code=422,
            detail="At least one delivery channel (recipients or teams_webhook_url) is required",
        )


@router.get("/rules", response_model=list[AzureAlertRuleResponse])
def list_rules(_session: dict = Depends(require_authenticated_user)) -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_alert_store.list_rules()


@router.post("/rules", response_model=AzureAlertRuleResponse, status_code=201)
def create_rule(
    body: AzureAlertRuleCreate,
    _session: dict = Depends(require_authenticated_user),
) -> dict[str, Any]:
    _ensure_azure_site()
    _validate_delivery(body.recipients, body.teams_webhook_url)
    return azure_alert_store.create_rule(body.model_dump())


@router.get("/rules/{rule_id}", response_model=AzureAlertRuleResponse)
def get_rule(rule_id: str, _session: dict = Depends(require_authenticated_user)) -> dict[str, Any]:
    _ensure_azure_site()
    return _get_rule_or_404(rule_id)


@router.put("/rules/{rule_id}", response_model=AzureAlertRuleResponse)
def update_rule(
    rule_id: str,
    body: AzureAlertRuleUpdate,
    _session: dict = Depends(require_authenticated_user),
) -> dict[str, Any]:
    _ensure_azure_site()
    _get_rule_or_404(rule_id)
    _validate_delivery(body.recipients, body.teams_webhook_url)
    updated = azure_alert_store.update_rule(rule_id, body.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return updated


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, _session: dict = Depends(require_authenticated_user)) -> Response:
    _ensure_azure_site()
    _get_rule_or_404(rule_id)
    azure_alert_store.delete_rule(rule_id)
    return Response(status_code=204)


@router.post("/rules/{rule_id}/toggle", response_model=AzureAlertRuleResponse)
def toggle_rule(rule_id: str, _session: dict = Depends(require_authenticated_user)) -> dict[str, Any]:
    _ensure_azure_site()
    _get_rule_or_404(rule_id)
    result = azure_alert_store.toggle_rule(rule_id)
    if not result:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return result


@router.post("/rules/{rule_id}/test", response_model=AzureAlertTestResponse)
def test_rule(rule_id: str, _session: dict = Depends(require_authenticated_user)) -> dict[str, Any]:
    _ensure_azure_site()
    rule = _get_rule_or_404(rule_id)
    try:
        items = _evaluate_rule(rule)
    except Exception as exc:
        logger.exception("Azure alert rule dry run failed for %s", rule_id)
        raise HTTPException(status_code=500, detail=f"Evaluation error: {exc}") from exc
    return {"match_count": len(items), "sample_items": items[:10]}


@router.post("/rules/{rule_id}/send", status_code=202)
async def send_rule_now(rule_id: str, _admin: dict = Depends(require_admin)) -> dict[str, Any]:
    _ensure_azure_site()
    rule = _get_rule_or_404(rule_id)
    from azure_alert_engine import _deliver  # noqa: PLC0415
    items = _evaluate_rule(rule)
    if not items:
        return {"detail": "No matches — nothing sent"}
    status, error = await _deliver(rule, items)
    azure_alert_store.record_history(
        rule["id"], rule["name"], rule["trigger_type"],
        rule.get("recipients", ""), len(items), items, status, error,
    )
    azure_alert_store.update_last_run(rule["id"], last_sent=(status != "failed"))
    return {"status": status, "match_count": len(items), "error": error}


@router.post("/run", status_code=202)
def run_all_rules(_admin: dict = Depends(require_admin)) -> dict[str, Any]:
    _ensure_azure_site()
    import threading  # noqa: PLC0415
    from azure_alert_engine import run_due_rules  # noqa: PLC0415
    threading.Thread(target=run_due_rules, daemon=True).start()
    return {"detail": "Rule evaluation started in background"}


@router.get("/history", response_model=list[AzureAlertHistoryItem])
def get_history(
    limit: int = 100,
    rule_id: str | None = None,
    _session: dict = Depends(require_authenticated_user),
) -> list[dict[str, Any]]:
    _ensure_azure_site()
    return azure_alert_store.get_history(limit=limit, rule_id=rule_id)


@router.get("/trigger-types")
def get_trigger_types(_session: dict = Depends(require_authenticated_user)) -> dict[str, Any]:
    _ensure_azure_site()
    return TRIGGER_SCHEMA


@router.post("/chat-parse", response_model=AzureChatParseResponse)
def chat_parse(
    body: AzureChatParseRequest,
    _session: dict = Depends(require_authenticated_user),
) -> dict[str, Any]:
    _ensure_azure_site()
    result = parse_azure_alert_rule(body.message)
    if result.get("parsed"):
        rule_data = {k: v for k, v in result.items() if k not in ("parsed", "summary", "error")}
        return {
            "parsed": True,
            "rule": rule_data,
            "summary": result.get("summary", ""),
            "error": "",
        }
    return {"parsed": False, "rule": None, "summary": "", "error": result.get("error", "Could not parse")}
