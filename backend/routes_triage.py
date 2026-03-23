"""API routes for AI-powered ticket triage."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from ai_client import analyze_ticket, get_available_models, score_closed_ticket, validate_suggestions
from auth import get_session
from issue_cache import cache
from jira_client import JiraClient
from metrics import _is_open, issue_to_row
from models import TriageAnalyzeRequest, TriageApplyRequest, TriageFieldAction, TriageDismissRequest
from site_context import get_current_site_scope, get_scoped_issues, key_is_visible_in_scope
from triage_store import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/triage")

_client = JiraClient()

def _new_progress_state() -> dict[str, Any]:
    return {"running": False, "processed": 0, "total": 0, "current_key": None, "cancel": False}


_run_progress: dict[str, dict[str, Any]] = {
    "primary": _new_progress_state(),
    "oasisdev": _new_progress_state(),
}
_score_progress: dict[str, dict[str, Any]] = {
    "primary": _new_progress_state(),
    "oasisdev": _new_progress_state(),
}


def _current_run_progress() -> dict[str, Any]:
    return _run_progress[get_current_site_scope()]


def _current_score_progress() -> dict[str, Any]:
    return _score_progress[get_current_site_scope()]


def _visible_issue_keys() -> set[str]:
    return {issue.get("key", "") for issue in get_scoped_issues() if issue.get("key")}


def _ensure_ticket_visible(key: str) -> None:
    if not key_is_visible_in_scope(key):
        raise HTTPException(status_code=404, detail=f"Ticket {key} is not available on this site")


def _matches_technician_score_search(score: dict[str, Any], search: str) -> bool:
    query = search.strip().lower()
    if not query:
        return True
    haystack = " ".join(
        [
            str(score.get("key") or ""),
            str(score.get("ticket_summary") or ""),
            str(score.get("ticket_status") or ""),
            str(score.get("ticket_assignee") or ""),
            str(score.get("score_summary") or ""),
            str(score.get("communication_notes") or ""),
            str(score.get("documentation_notes") or ""),
            str(score.get("model_used") or ""),
        ]
    ).lower()
    return query in haystack


@router.get("/models")
async def list_models() -> list[dict[str, Any]]:
    """Return available AI models (filtered by configured API keys)."""
    return [m.model_dump() for m in get_available_models()]


@router.get("/log")
async def get_triage_log(search: str = Query(default="", max_length=200)) -> list[dict[str, Any]]:
    """Return all AI triage changes applied to Jira (auto and user-approved)."""
    visible_keys = _visible_issue_keys()
    return [
        entry
        for entry in store.get_triage_log(limit=500, search=search)
        if entry.get("key") in visible_keys
    ]


@router.get("/run-status")
async def get_run_status() -> dict[str, Any]:
    """Return progress of the current run-all background task, plus ticket counts."""
    result = dict(_current_run_progress())
    # Add counts for button labels
    already_done = store.get_auto_triaged_keys()
    all_keys = [iss.get("key", "") for iss in get_scoped_issues() if iss.get("key")]
    result["remaining_count"] = len([k for k in all_keys if k not in already_done])
    result["processed_count"] = len([k for k in all_keys if k in already_done])
    return result


@router.post("/run-cancel")
async def cancel_triage_run() -> dict[str, Any]:
    """Cancel the current triage run."""
    progress = _current_run_progress()
    if not progress["running"]:
        return {"cancelled": False, "message": "No triage run in progress"}
    progress["cancel"] = True
    return {"cancelled": True}


@router.post("/run-all")
async def run_triage_all(background_tasks: BackgroundTasks, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run auto-triage on ALL existing cached tickets as a background task."""
    from config import AUTO_TRIAGE_MODEL

    site_scope = get_current_site_scope()
    progress = _run_progress[site_scope]

    # Prevent concurrent runs
    if progress["running"]:
        return {"started": False, "total_tickets": progress["total"], "message": "Triage run already in progress"}

    model = (body or {}).get("model") or AUTO_TRIAGE_MODEL

    # Validate model
    available_ids = {m.id for m in get_available_models()}
    if model not in available_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model}' not available. Configure the API key or choose another model.",
        )

    all_issues = get_scoped_issues()
    all_keys = [issue.get("key", "") for issue in all_issues if issue.get("key")]

    # Mode flags:
    #   reset=true  → clear tracking, reprocess everything
    #   reprocess=true → only process already-done tickets (re-analyze them)
    #   default → only process unprocessed tickets
    reset = (body or {}).get("reset", False)
    reprocess = (body or {}).get("reprocess", False)

    already_done = store.get_auto_triaged_keys()

    if reset:
        store.clear_auto_triaged()
        cache.reset_auto_triage_seen()
        # Process all keys (tracking cleared)
    elif reprocess:
        # Only re-process previously done tickets
        all_keys = [k for k in all_keys if k in already_done]
        # Clear their tracking so they get re-processed
        store.clear_auto_triaged_keys(all_keys)
        cache.reset_auto_triage_seen()
    else:
        # Default: only unprocessed tickets
        all_keys = [k for k in all_keys if k not in already_done]

    all_keys.reverse()

    # Optional limit for testing
    limit = (body or {}).get("limit")
    if limit and isinstance(limit, int) and limit > 0:
        all_keys = all_keys[:limit]

    progress.update(running=True, processed=0, total=len(all_keys), current_key=None, cancel=False)

    async def _run() -> None:
        try:
            await cache._auto_triage_new_tickets(all_keys, progress=progress)
        except Exception:
            logger.exception("run-all: background triage failed")
        finally:
            progress.update(running=False, current_key=None, cancel=False)

    background_tasks.add_task(_run)

    return {"started": True, "total_tickets": len(all_keys)}


@router.get("/technician-scores")
async def get_technician_scores(search: str = Query(default="", max_length=200)) -> list[dict[str, Any]]:
    """Return stored technician QA scores for closed tickets."""
    visible_keys = _visible_issue_keys()
    issues_by_key = {
        issue.get("key", ""): issue
        for issue in get_scoped_issues()
        if issue.get("key")
    }
    results: list[dict[str, Any]] = []
    for score in store.list_technician_scores(limit=500):
        if score.key not in visible_keys:
            continue
        issue = issues_by_key.get(score.key)
        ticket = issue_to_row(issue) if issue else None
        results.append({
            **score.model_dump(),
            "overall_score": round((score.communication_score + score.documentation_score) / 2, 1),
            "ticket_summary": ticket.get("summary", "") if ticket else "",
            "ticket_status": ticket.get("status", "") if ticket else "",
            "ticket_assignee": ticket.get("assignee", "") if ticket else "",
            "ticket_resolved": ticket.get("resolved", "") if ticket else "",
        })
    return [score for score in results if _matches_technician_score_search(score, search)]


@router.get("/score-run-status")
async def get_technician_score_run_status() -> dict[str, Any]:
    """Return progress for the closed-ticket QA scoring workflow."""
    result = dict(_current_score_progress())
    closed_keys = [
        iss.get("key", "")
        for iss in get_scoped_issues()
        if iss.get("key") and not _is_open(iss)
    ]
    scored_keys = store.get_technician_scored_keys()
    result["remaining_count"] = len([k for k in closed_keys if k not in scored_keys])
    result["processed_count"] = len([k for k in closed_keys if k in scored_keys])
    return result


@router.post("/score-cancel")
async def cancel_closed_ticket_scoring() -> dict[str, Any]:
    """Cancel the current closed-ticket QA scoring run."""
    progress = _current_score_progress()
    if not progress["running"]:
        return {"cancelled": False, "message": "No technician scoring run in progress"}
    progress["cancel"] = True
    return {"cancelled": True}


@router.post("/score-closed")
async def run_closed_ticket_scoring(
    background_tasks: BackgroundTasks,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run technician QA scoring for closed tickets already in the cache."""
    from config import AUTO_TRIAGE_MODEL
    site_scope = get_current_site_scope()
    progress = _score_progress[site_scope]

    if progress["running"]:
        return {
            "started": False,
            "total_tickets": progress["total"],
            "message": "Technician scoring run already in progress",
        }

    available = get_available_models()
    if not available:
        raise HTTPException(
            status_code=400,
            detail="No AI model available. Configure an API key before scoring technician responses.",
        )
    available_ids = {model.id for model in available}
    model_id = AUTO_TRIAGE_MODEL if AUTO_TRIAGE_MODEL in available_ids else available[0].id

    issues = get_scoped_issues()
    issues_by_key = {issue.get("key", ""): issue for issue in issues if issue.get("key")}
    all_closed_keys = [key for key, issue in issues_by_key.items() if not _is_open(issue)]

    reset = bool((body or {}).get("reset", False))
    already_scored = store.get_technician_scored_keys()
    keys_to_process = all_closed_keys if reset else [key for key in all_closed_keys if key not in already_scored]

    limit = (body or {}).get("limit")
    if isinstance(limit, int) and limit > 0:
        keys_to_process = keys_to_process[:limit]

    progress.update(
        running=True,
        processed=0,
        total=len(keys_to_process),
        current_key=None,
        cancel=False,
    )

    async def _run() -> None:
        import asyncio

        loop = asyncio.get_running_loop()
        try:
            for index, key in enumerate(keys_to_process):
                if progress.get("cancel"):
                    logger.info("Technician scoring cancelled after %d/%d", index, len(keys_to_process))
                    break
                progress.update(processed=index, current_key=key)

                issue = issues_by_key.get(key)
                if not issue or _is_open(issue):
                    continue

                try:
                    request_comments = await loop.run_in_executor(None, _client.get_request_comments, key)
                except Exception:
                    logger.exception("Failed to load request comments for %s during technician scoring", key)
                    request_comments = []

                score = await loop.run_in_executor(
                    None,
                    score_closed_ticket,
                    issue,
                    request_comments,
                    model_id,
                )
                store.save_technician_score(score)

            progress.update(processed=len(keys_to_process))
        except Exception:
            logger.exception("Closed-ticket technician scoring failed")
        finally:
            progress.update(running=False, current_key=None, cancel=False)

    background_tasks.add_task(_run)

    return {"started": True, "total_tickets": len(keys_to_process)}


@router.get("/suggestions")
async def list_suggestions() -> list[dict[str, Any]]:
    """Return cached triage suggestions, excluding auto-triage-owned fields."""
    visible_keys = _visible_issue_keys()
    return [
        result.model_dump()
        for result in store.list_all(strip_auto_fields=True)
        if result.key in visible_keys
    ]


@router.get("/suggestions/{key}")
async def get_suggestion(key: str) -> dict[str, Any]:
    """Return cached suggestion for a specific ticket."""
    _ensure_ticket_visible(key)
    result = store.get(key)
    if not result:
        raise HTTPException(status_code=404, detail=f"No suggestion for {key}")
    # Strip auto-triage-owned fields for tickets that were auto-processed
    triaged = store.get_auto_triaged_keys()
    if key in triaged:
        result.suggestions = [
            s for s in result.suggestions
            if s.field not in ("priority", "request_type")
        ]
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

    all_issues = {i.get("key", ""): i for i in get_scoped_issues()}

    for key in req.keys:
        issue = all_issues.get(key)
        if not issue:
            results.append({"key": key, "error": f"Issue {key} not found in cache"})
            continue

        if key in cached:
            results.append(cached[key].model_dump())
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
    _ensure_ticket_visible(req.key)
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
                cache.update_cached_field(req.key, "priority", s.suggested_value)
                applied.append(field_name)

            elif field_name == "assignee":
                from config import JIRA_PROJECT
                users = _client.get_users_assignable(JIRA_PROJECT)
                account_id = None
                for u in users:
                    if u.get("displayName", "").lower() == s.suggested_value.lower():
                        account_id = u.get("accountId")
                        break
                if account_id:
                    _client.assign_issue(req.key, account_id)
                    cache.update_cached_field(
                        req.key,
                        "assignee",
                        {"displayName": s.suggested_value, "accountId": account_id},
                    )
                    applied.append(field_name)
                else:
                    errors.append({"field": field_name, "error": f"Could not find user: {s.suggested_value}"})

            elif field_name == "reporter":
                account_id = _client.find_user_account_id(s.suggested_value)
                if account_id:
                    _client.update_reporter(req.key, account_id)
                    cache.update_cached_field(
                        req.key,
                        "reporter",
                        {"displayName": s.suggested_value, "accountId": account_id},
                    )
                    applied.append(field_name)
                else:
                    errors.append({"field": field_name, "error": f"Could not find reporter: {s.suggested_value}"})

            elif field_name == "status":
                transitions = _client.get_transitions(req.key)
                transition_id = None
                for t in transitions:
                    if t.get("name", "").lower() == s.suggested_value.lower():
                        transition_id = t.get("id")
                        break
                if transition_id:
                    _client.transition_issue(req.key, transition_id)
                    cache.update_cached_field(req.key, "status", s.suggested_value)
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
                    cache.update_cached_field(req.key, "request_type", s.suggested_value)
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

    # Only delete suggestion if at least one field was successfully applied
    if applied:
        store.delete(req.key)

    return {"key": req.key, "applied": applied, "errors": errors}


@router.post("/apply-field")
async def apply_single_field(req: TriageFieldAction, request: Request) -> dict[str, Any]:
    """Apply a single suggestion field to Jira and remove it from the stored suggestion."""
    _ensure_ticket_visible(req.key)
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
            cache.update_cached_field(req.key, "priority", s.suggested_value)

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
            cache.update_cached_field(
                req.key,
                "assignee",
                {"displayName": s.suggested_value, "accountId": account_id},
            )

        elif req.field == "reporter":
            account_id = _client.find_user_account_id(s.suggested_value)
            if not account_id:
                raise HTTPException(status_code=400, detail=f"Could not find reporter: {s.suggested_value}")
            _client.update_reporter(req.key, account_id)
            cache.update_cached_field(
                req.key,
                "reporter",
                {"displayName": s.suggested_value, "accountId": account_id},
            )

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
            cache.update_cached_field(req.key, "status", s.suggested_value)

        elif req.field == "request_type":
            from ai_client import get_request_type_id
            rt_id = get_request_type_id(s.suggested_value)
            if not rt_id:
                raise HTTPException(status_code=400, detail=f"Unknown request type: {s.suggested_value}")
            _client.set_request_type(req.key, rt_id)
            cache.update_cached_field(req.key, "request_type", s.suggested_value)

        elif req.field == "comment":
            _client.add_comment(req.key, f"[AI-Suggestion] {s.suggested_value}")

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported field: {req.field}")

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to apply %s for %s", req.field, req.key)
        raise HTTPException(status_code=500, detail=f"Failed to apply {req.field} for {req.key}") from exc

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
    _ensure_ticket_visible(req.key)
    existing = store.get(req.key)
    if not existing:
        raise HTTPException(status_code=404, detail=f"No suggestion for {req.key}")
    store.delete(req.key)
    return {"key": req.key, "dismissed": True}
