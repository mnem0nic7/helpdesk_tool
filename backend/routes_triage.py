"""API routes for AI-powered ticket triage."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from ai_client import analyze_ticket, get_available_models, validate_suggestions
from auth import get_session
from issue_cache import cache
from jira_client import JiraClient
from models import TriageAnalyzeRequest, TriageApplyRequest, TriageFieldAction, TriageDismissRequest
from triage_store import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/triage")

_client = JiraClient()

# Progress tracking for run-all background task
_run_progress: dict[str, Any] = {"running": False, "processed": 0, "total": 0, "current_key": None}


@router.get("/models")
async def list_models() -> list[dict[str, Any]]:
    """Return available AI models (filtered by configured API keys)."""
    return [m.model_dump() for m in get_available_models()]


@router.get("/log")
async def get_triage_log() -> list[dict[str, Any]]:
    """Return all AI triage changes applied to Jira (auto and user-approved)."""
    return store.get_triage_log(limit=500)


@router.get("/run-status")
async def get_run_status() -> dict[str, Any]:
    """Return progress of the current run-all background task."""
    return dict(_run_progress)


@router.post("/run-all")
async def run_triage_all(background_tasks: BackgroundTasks, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run auto-triage on ALL existing cached tickets as a background task."""
    from config import AUTO_TRIAGE_MODEL

    model = (body or {}).get("model") or AUTO_TRIAGE_MODEL

    # Validate model
    available_ids = {m.id for m in get_available_models()}
    if model not in available_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model}' not available. Configure the API key or choose another model.",
        )

    all_issues = cache.get_all_issues()
    all_keys = [issue.get("key", "") for issue in all_issues if issue.get("key")]

    # Optional limit for testing
    limit = (body or {}).get("limit")
    if limit and isinstance(limit, int) and limit > 0:
        all_keys = all_keys[:limit]

    # Reset tracking so every ticket gets re-processed
    store.clear_auto_triaged()
    cache.reset_auto_triage_seen()

    _run_progress.update(running=True, processed=0, total=len(all_keys), current_key=None)

    async def _run() -> None:
        try:
            await cache._auto_triage_new_tickets(all_keys, progress=_run_progress)
        except Exception:
            logger.exception("run-all: background triage failed")
        finally:
            _run_progress.update(running=False, current_key=None)

    background_tasks.add_task(_run)

    return {"started": True, "total_tickets": len(all_keys)}


@router.get("/suggestions")
async def list_suggestions() -> list[dict[str, Any]]:
    """Return all cached triage suggestions."""
    return [r.model_dump() for r in store.list_all()]


@router.get("/suggestions/{key}")
async def get_suggestion(key: str) -> dict[str, Any]:
    """Return cached suggestion for a specific ticket."""
    result = store.get(key)
    if not result:
        raise HTTPException(status_code=404, detail=f"No suggestion for {key}")
    return result.model_dump()


@router.post("/analyze")
async def analyze(req: TriageAnalyzeRequest) -> list[dict[str, Any]]:
    """Analyze tickets. Returns cached results when available, else calls AI."""
    # Validate model
    available = get_available_models()
    model_ids = {m.id for m in available}
    if req.model not in model_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{req.model}' not available. Configure the API key or choose another model.",
        )

    # Check cache first (skip if force re-evaluation requested)
    cached = store.get_many(req.keys) if not req.force else {}
    results: list[dict[str, Any]] = []

    all_issues = {i.get("key", ""): i for i in cache.get_all_issues()}

    for key in req.keys:
        if key in cached:
            results.append(cached[key].model_dump())
            continue

        issue = all_issues.get(key)
        if not issue:
            results.append({"key": key, "error": f"Issue {key} not found in cache"})
            continue

        try:
            result = analyze_ticket(issue, req.model)
            result.suggestions = validate_suggestions(key, result.suggestions)
            store.save(result)
            results.append(result.model_dump())
        except Exception as exc:
            logger.exception("Failed to analyze %s", key)
            results.append({"key": key, "error": str(exc)})

    return results


@router.post("/apply")
async def apply_suggestion(req: TriageApplyRequest) -> dict[str, Any]:
    """Apply accepted suggestions to a ticket via Jira API."""
    suggestion = store.get(req.key)
    if not suggestion:
        raise HTTPException(status_code=404, detail=f"No suggestion for {req.key}")

    applied: list[str] = []
    errors: list[dict[str, str]] = []

    # Index suggestions by field
    by_field = {s.field: s for s in suggestion.suggestions}

    for field_name in req.accepted_fields:
        s = by_field.get(field_name)
        if not s:
            continue

        try:
            if field_name == "priority":
                from ai_client import _get_valid_priorities
                valid = _get_valid_priorities()
                if s.suggested_value not in valid:
                    errors.append({"field": field_name, "error": f"Invalid priority '{s.suggested_value}'. Valid: {', '.join(sorted(valid))}"})
                    continue
                _client.update_priority(req.key, s.suggested_value)
                applied.append(field_name)

            elif field_name == "assignee":
                # Need to look up account ID from display name
                # For now, try the suggested value as-is (could be account ID or name)
                from config import JIRA_PROJECT
                users = _client.get_users_assignable(JIRA_PROJECT)
                account_id = None
                for u in users:
                    if u.get("displayName", "").lower() == s.suggested_value.lower():
                        account_id = u.get("accountId")
                        break
                if account_id:
                    _client.assign_issue(req.key, account_id)
                    applied.append(field_name)
                else:
                    errors.append({"field": field_name, "error": f"Could not find user: {s.suggested_value}"})

            elif field_name == "status":
                # Look up the transition ID for the target status
                transitions = _client.get_transitions(req.key)
                transition_id = None
                for t in transitions:
                    if t.get("name", "").lower() == s.suggested_value.lower():
                        transition_id = t.get("id")
                        break
                if transition_id:
                    _client.transition_issue(req.key, transition_id)
                    applied.append(field_name)
                else:
                    errors.append({
                        "field": field_name,
                        "error": f"No transition to '{s.suggested_value}' available",
                    })

            elif field_name == "request_type":
                from ai_client import get_request_type_id
                rt_id = get_request_type_id(s.suggested_value)
                if rt_id:
                    _client.set_request_type(req.key, rt_id)
                    applied.append(field_name)
                else:
                    errors.append({"field": field_name, "error": f"Unknown request type: {s.suggested_value}"})

            elif field_name == "comment":
                _client.add_comment(req.key, f"[AI-Suggestion] {s.suggested_value}")
                applied.append(field_name)

            else:
                errors.append({"field": field_name, "error": f"Unsupported field: {field_name}"})

        except Exception as exc:
            errors.append({"field": field_name, "error": str(exc)})

    # Delete suggestion from store after applying
    store.delete(req.key)

    return {"key": req.key, "applied": applied, "errors": errors}


@router.post("/apply-field")
async def apply_single_field(req: TriageFieldAction, request: Request) -> dict[str, Any]:
    """Apply a single suggestion field to Jira and remove it from the stored suggestion."""
    suggestion = store.get(req.key)
    if not suggestion:
        raise HTTPException(status_code=404, detail=f"No suggestion for {req.key}")

    by_field = {s.field: s for s in suggestion.suggestions}
    s = by_field.get(req.field)
    if not s:
        raise HTTPException(status_code=404, detail=f"No suggestion for field '{req.field}' on {req.key}")

    # Identify the approving user
    sid = request.cookies.get("session_id", "")
    session = get_session(sid) if sid else None
    approved_by = session["email"] if session else None

    # Apply the field to Jira
    try:
        if req.field == "priority":
            from ai_client import _get_valid_priorities
            valid = _get_valid_priorities()
            if s.suggested_value not in valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid priority '{s.suggested_value}'. Valid: {', '.join(sorted(valid))}",
                )
            _client.update_priority(req.key, s.suggested_value)

        elif req.field == "assignee":
            from config import JIRA_PROJECT
            users = _client.get_users_assignable(JIRA_PROJECT)
            account_id = None
            for u in users:
                if u.get("displayName", "").lower() == s.suggested_value.lower():
                    account_id = u.get("accountId")
                    break
            if not account_id:
                raise HTTPException(status_code=400, detail=f"Could not find user: {s.suggested_value}")
            _client.assign_issue(req.key, account_id)

        elif req.field == "status":
            transitions = _client.get_transitions(req.key)
            transition_id = None
            for t in transitions:
                if t.get("name", "").lower() == s.suggested_value.lower():
                    transition_id = t.get("id")
                    break
            if not transition_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"No transition to '{s.suggested_value}' available",
                )
            _client.transition_issue(req.key, transition_id)

        elif req.field == "request_type":
            from ai_client import get_request_type_id
            rt_id = get_request_type_id(s.suggested_value)
            if not rt_id:
                raise HTTPException(status_code=400, detail=f"Unknown request type: {s.suggested_value}")
            _client.set_request_type(req.key, rt_id)

        elif req.field == "comment":
            _client.add_comment(req.key, f"[AI-Suggestion] {s.suggested_value}")

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported field: {req.field}")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Log the user-approved change
    store.log_change(
        key=req.key,
        field=req.field,
        old_value=s.current_value,
        new_value=s.suggested_value,
        confidence=s.confidence,
        model=suggestion.model_used,
        source="user",
        approved_by=approved_by,
    )

    # Remove the field from the stored suggestion (deletes row if none left)
    remaining = store.remove_field(req.key, req.field)

    return {
        "key": req.key,
        "field": req.field,
        "applied": True,
        "remaining_suggestions": remaining.model_dump() if remaining else None,
    }


@router.post("/dismiss")
async def dismiss_suggestion(req: TriageDismissRequest) -> dict[str, Any]:
    """Dismiss (delete) all suggestions for a ticket."""
    existing = store.get(req.key)
    if not existing:
        raise HTTPException(status_code=404, detail=f"No suggestion for {req.key}")
    store.delete(req.key)
    return {"key": req.key, "dismissed": True}
