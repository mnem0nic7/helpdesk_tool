"""Azure security incident copilot routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ai_client import (
    get_available_security_copilot_models,
    get_default_security_copilot_model_id,
)
from auth import require_authenticated_user
from models import SecurityCopilotChatRequest, SecurityCopilotChatResponse
from security_copilot import run_security_copilot_chat
from site_context import get_current_site_scope

router = APIRouter(prefix="/api/azure/security/copilot")


def _ensure_azure_site() -> None:
    if get_current_site_scope() not in ("azure", "security"):
        raise HTTPException(
            status_code=404,
            detail="Azure security copilot APIs are only available on azure.movedocs.com or security.movedocs.com",
        )


@router.get("/models")
def get_security_copilot_models(
    _session: dict[str, Any] = Depends(require_authenticated_user),
) -> list[dict[str, str]]:
    _ensure_azure_site()
    return [model.model_dump() for model in get_available_security_copilot_models()]


@router.post("/chat", response_model=SecurityCopilotChatResponse)
def post_security_copilot_chat(
    body: SecurityCopilotChatRequest,
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityCopilotChatResponse:
    _ensure_azure_site()
    available = get_available_security_copilot_models()
    if not available:
        raise HTTPException(
            status_code=400,
            detail="No AI model available for the Azure security copilot. Ensure Ollama is running and the configured local model is pulled.",
        )
    available_ids = {model.id for model in available}
    model_id = body.model or get_default_security_copilot_model_id(available)
    if not model_id:
        raise HTTPException(
            status_code=400,
            detail="No AI model available for the Azure security copilot. Ensure Ollama is running and the configured local model is pulled.",
        )
    if model_id not in available_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model_id}' is not available from the active Security Copilot Ollama provider",
        )
    if not str(body.message or "").strip() and not body.incident.summary.strip() and not body.jobs:
        raise HTTPException(status_code=400, detail="Message or existing incident context is required")
    return run_security_copilot_chat(body, session, model_id=model_id)
