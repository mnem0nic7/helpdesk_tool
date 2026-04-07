"""API routes for AI-powered ticket triage."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from ai_client import (
    analyze_ticket,
    get_available_models,
    get_ollama_queue_snapshot,
    normalize_triage_priority_value,
    select_available_ollama_model,
    validate_suggestions,
)
from auth import get_session
from config import AUTO_TRIAGE_MODEL, OLLAMA_MODEL, TECHNICIAN_SCORE_POLL_INTERVAL_MINUTES
from issue_cache import cache
from jira_client import JiraClient
from jira_write_service import add_fallback_internal_audit_note, get_jira_write_context, prepend_fallback_actor_line
from metrics import _is_open, issue_to_row
from models import TriageAnalyzeRequest, TriageApplyRequest, TriageFieldAction, TriageDismissRequest
from site_context import get_current_site_scope, get_scoped_issues, key_is_visible_in_scope
from technician_scoring_manager import TechnicianScoringManager, new_progress_state
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
    "primary": new_progress_state(),
    "oasisdev": new_progress_state(),
}

technician_scoring_manager = TechnicianScoringManager(
    client=_client,
    store=store,
    progress_by_scope=_score_progress,
    poll_interval_seconds=TECHNICIAN_SCORE_POLL_INTERVAL_MINUTES * 60,
)

_TRIAGE_HEALTH_STALE_MINUTES = 10


def _normalize_requested_model(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized.lower() in {"none", "null", "undefined"}:
        return ""
    return normalized


def _ensure_processed_backfill() -> None:
    handler = getattr(cache, "ensure_auto_triage_processed_backfill", None)
    if callable(handler):
        handler()


def _current_run_progress() -> dict[str, Any]:
    return _run_progress[get_current_site_scope()]


def _current_score_progress() -> dict[str, Any]:
    return technician_scoring_manager.get_progress(get_current_site_scope())


def _visible_issue_keys() -> set[str]:
    return {issue.get("key", "") for issue in get_scoped_issues() if issue.get("key")}


def _parse_status_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if (
        len(normalized) >= 5
        and normalized[-5] in {"+", "-"}
        and normalized[-3] != ":"
        and normalized[-4:].isdigit()
    ):
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _summarize_auto_triage_activity(entries: list[dict[str, Any]]) -> dict[str, Any]:
    changed_count = 0
    no_change_count = 0
    backfilled_count = 0
    failed_count = 0
    activity_keys: set[str] = set()
    last_activity_at: datetime | None = None
    last_live_activity_at: datetime | None = None
    last_successful_activity_at: datetime | None = None

    for entry in entries:
        key = str(entry.get("key") or "").strip().upper()
        if key:
            activity_keys.add(key)
        outcome = str(entry.get("outcome") or "").strip().lower()
        if outcome == "changed":
            changed_count += 1
        elif outcome == "no_change":
            no_change_count += 1
        elif outcome == "backfill":
            backfilled_count += 1
        elif outcome == "failed":
            failed_count += 1

        processed_at = _parse_status_datetime(entry.get("processed_at"))
        if not processed_at:
            continue
        if last_activity_at is None or processed_at > last_activity_at:
            last_activity_at = processed_at
        if str(entry.get("source") or "").strip().lower() == "auto":
            if last_live_activity_at is None or processed_at > last_live_activity_at:
                last_live_activity_at = processed_at
            if outcome in {"changed", "no_change"} and (
                last_successful_activity_at is None or processed_at > last_successful_activity_at
            ):
                last_successful_activity_at = processed_at

    return {
        "changed_count": changed_count,
        "no_change_count": no_change_count,
        "backfilled_count": backfilled_count,
        "failed_count": failed_count,
        "activity_keys": activity_keys,
        "last_activity_at": last_activity_at.isoformat() if last_activity_at else None,
        "last_live_activity_at": last_live_activity_at.isoformat() if last_live_activity_at else None,
        "last_successful_activity_at": (
            last_successful_activity_at.isoformat() if last_successful_activity_at else None
        ),
    }


def _evaluate_triage_health(
    *,
    visible_keys: set[str],
    activity_summary: dict[str, Any],
    auto_status: dict[str, Any],
) -> tuple[str, str]:
    available_model = select_available_ollama_model(
        get_available_models(),
        preferred_model_id=AUTO_TRIAGE_MODEL,
        fallback_model_id=OLLAMA_MODEL,
    )
    if not available_model:
        return (
            "broken",
            "Auto-triage has no available AI model. Ensure Ollama is running and the configured local model is pulled.",
        )

    processed_keys = store.get_auto_triaged_keys() & visible_keys
    activity_keys = set(activity_summary.get("activity_keys") or set())
    missing_activity_count = len(processed_keys - activity_keys)
    if missing_activity_count:
        return (
            "broken",
            f"Auto-triage has {missing_activity_count} processed ticket(s) without matching activity records.",
        )

    pending_count = int(auto_status.get("pending_count") or 0)
    running = bool(auto_status.get("running"))
    current_key = str(auto_status.get("current_key") or "").strip()
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=_TRIAGE_HEALTH_STALE_MINUTES)
    last_started = _parse_status_datetime(auto_status.get("last_started"))
    last_live_activity = _parse_status_datetime(activity_summary.get("last_live_activity_at"))
    last_success = _parse_status_datetime(activity_summary.get("last_successful_activity_at"))

    if running:
        last_progress = last_live_activity
        if last_started and (last_progress is None or last_started > last_progress):
            last_progress = last_started
        if last_progress and last_progress <= stale_before:
            target = current_key or "the current ticket"
            return (
                "broken",
                f"Auto-triage still reports running on {target}, but no activity has been recorded in the last {_TRIAGE_HEALTH_STALE_MINUTES} minutes.",
            )
        if not last_progress and (last_started is None or last_started <= stale_before):
            target = current_key or "the current ticket"
            return (
                "broken",
                f"Auto-triage still reports running on {target}, but it has not produced any activity in the last {_TRIAGE_HEALTH_STALE_MINUTES} minutes.",
            )

    if pending_count > 0 and not running:
        if not last_success or last_success <= stale_before:
            return (
                "broken",
                f"{pending_count} ticket(s) are still pending, but there has been no successful auto-triage activity in the last {_TRIAGE_HEALTH_STALE_MINUTES} minutes.",
            )

    return ("healthy", "")


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
    """Return available AI models from the active Ollama runtime."""
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
    visible_keys = _visible_issue_keys()
    auto_status = cache.auto_triage_status(get_current_site_scope())
    already_done = store.get_auto_triaged_keys() & visible_keys
    activity_entries = [
        entry
        for entry in store.list_auto_triage_activity()
        if str(entry.get("key") or "").strip().upper() in visible_keys
    ]
    activity_summary = _summarize_auto_triage_activity(activity_entries)
    health, health_message = _evaluate_triage_health(
        visible_keys=visible_keys,
        activity_summary=activity_summary,
        auto_status=auto_status,
    )

    result["remaining_count"] = len(visible_keys - already_done)
    result["ai_processed_count"] = (
        int(activity_summary["changed_count"]) + int(activity_summary["no_change_count"])
    )
    result["processed_count"] = result["ai_processed_count"]
    result["changed_count"] = int(activity_summary["changed_count"])
    result["no_change_count"] = int(activity_summary["no_change_count"])
    result["backfilled_count"] = int(activity_summary["backfilled_count"])
    result["failed_count"] = int(activity_summary["failed_count"])
    result["last_activity_at"] = activity_summary["last_activity_at"]
    result["health"] = health
    result["health_message"] = health_message
    return result


@router.get("/ollama-queue")
async def get_ollama_queue() -> list[dict[str, Any]]:
    """Return a live snapshot of every Ollama request coordinator (primary, secondary, security)."""
    return get_ollama_queue_snapshot()


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
    site_scope = get_current_site_scope()
    progress = _run_progress[site_scope]

    # Prevent concurrent runs
    if progress["running"]:
        return {"started": False, "total_tickets": progress["total"], "message": "Triage run already in progress"}

    requested_model = _normalize_requested_model((body or {}).get("model"))
    available_models = get_available_models()
    if not available_models:
        raise HTTPException(
            status_code=400,
            detail="No AI model available. Ensure Ollama is running and the configured local model is pulled.",
        )
    model = requested_model or select_available_ollama_model(
        available_models,
        preferred_model_id=AUTO_TRIAGE_MODEL,
        fallback_model_id=OLLAMA_MODEL,
    )

    available_ids = {m.id for m in available_models}
    if not model or model not in available_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model}' is not available from the active Ollama provider.",
        )

    all_issues = get_scoped_issues()
    all_keys = [issue.get("key", "") for issue in all_issues if issue.get("key")]
    _ensure_processed_backfill()

    # Mode flags:
    #   reset=true  → clear tracking, reprocess everything
    #   reprocess=true → only process already-done tickets (re-analyze them)
    #   default → only process unprocessed tickets
    reset = (body or {}).get("reset", False)
    reprocess = (body or {}).get("reprocess", False)

    already_done = store.get_auto_triaged_keys()
    ai_processed_keys = store.get_auto_triage_activity_keys(["changed", "no_change"])

    if reset:
        store.clear_auto_triaged()
        cache.reset_auto_triage_seen()
        # Process all keys (tracking cleared)
    elif reprocess:
        # Only re-process live AI outcomes, not legacy backfill placeholders.
        all_keys = [k for k in all_keys if k in ai_processed_keys]
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
            await cache._auto_triage_new_tickets(all_keys, progress=progress, model_id=model)
        except Exception:
            logger.exception("run-all: background triage failed")
        finally:
            progress.update(running=False, current_key=None, cancel=False)

    background_tasks.add_task(_run)

    return {"started": True, "total_tickets": len(all_keys)}


@router.get("/technician-scores")
async def get_technician_scores(
    search: str = Query(default="", max_length=200),
    key: str = Query(default="", max_length=40),
) -> list[dict[str, Any]]:
    """Return stored technician QA scores for closed tickets."""
    visible_keys = _visible_issue_keys()
    issues_by_key = {
        issue.get("key", ""): issue
        for issue in get_scoped_issues()
        if issue.get("key")
    }
    exact_key = key.strip().upper()

    if exact_key:
        if exact_key not in visible_keys:
            return []
        score = store.get_technician_score(exact_key)
        if not score:
            return []
        issue = issues_by_key.get(score.key)
        ticket = issue_to_row(issue) if issue else None
        result = {
            **score.model_dump(),
            "overall_score": round((score.communication_score + score.documentation_score) / 2, 1),
            "ticket_summary": ticket.get("summary", "") if ticket else "",
            "ticket_status": ticket.get("status", "") if ticket else "",
            "ticket_assignee": ticket.get("assignee", "") if ticket else "",
            "ticket_resolved": ticket.get("resolved", "") if ticket else "",
        }
        return [result] if _matches_technician_score_search(result, search) else []

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
    site_scope = get_current_site_scope()
    result = dict(_current_score_progress())
    closed_keys = [
        iss.get("key", "")
        for iss in get_scoped_issues()
        if iss.get("key") and not _is_open(iss)
    ]
    scored_keys = store.get_technician_scored_keys()
    result["remaining_count"] = len([k for k in closed_keys if k not in scored_keys])
    result["processed_count"] = len([k for k in closed_keys if k in scored_keys])
    priority_gate = technician_scoring_manager.get_priority_gate(site_scope)
    result["priority_blocked"] = bool(priority_gate.get("blocked"))
    result["priority_message"] = str(priority_gate.get("message") or "")
    result["priority_reason"] = str(priority_gate.get("reason") or "")
    result["priority_pending_count"] = int(priority_gate.get("pending_count") or 0)
    result["priority_running"] = bool(priority_gate.get("running"))
    result["priority_current_key"] = priority_gate.get("current_key")
    return result


@router.post("/score-cancel")
async def cancel_closed_ticket_scoring() -> dict[str, Any]:
    """Cancel the current closed-ticket QA scoring run."""
    if not technician_scoring_manager.cancel_scope(get_current_site_scope()):
        return {"cancelled": False, "message": "No technician scoring run in progress"}
    return {"cancelled": True}


@router.post("/score-closed")
async def run_closed_ticket_scoring(
    background_tasks: BackgroundTasks,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run technician QA scoring for closed tickets already in the cache."""
    site_scope = get_current_site_scope()
    progress = technician_scoring_manager.get_progress(site_scope)

    if progress["running"]:
        return {
            "started": False,
            "total_tickets": progress["total"],
            "message": "Technician scoring run already in progress",
        }

    reset = bool((body or {}).get("reset", False))
    limit = (body or {}).get("limit")
    try:
        preview = technician_scoring_manager.preview_scope_run(
            site_scope,
            reset=reset,
            limit=limit if isinstance(limit, int) and limit > 0 else None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(
        technician_scoring_manager.run_scope_once,
        site_scope,
        reset=reset,
        limit=limit if isinstance(limit, int) and limit > 0 else None,
        trigger="manual",
    )

    return {"started": True, "total_tickets": preview["total_tickets"]}


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
    from config import AUTO_TRIAGE_MODEL, OLLAMA_MODEL

    # Validate model
    available = get_available_models()
    if not available:
        raise HTTPException(
            status_code=400,
            detail="No AI model available. Ensure Ollama is running and the configured local model is pulled.",
        )
    requested_model = _normalize_requested_model(req.model)
    model_id = requested_model or select_available_ollama_model(
        available,
        preferred_model_id=AUTO_TRIAGE_MODEL,
        fallback_model_id=OLLAMA_MODEL,
    )
    model_ids = {m.id for m in available}
    if not model_id or model_id not in model_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{req.model}' is not available from the active Ollama provider.",
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
            result = analyze_ticket(issue, model_id)
            result.suggestions = validate_suggestions(key, result.suggestions)
            store.save(result)
            results.append(result.model_dump())
        except Exception as exc:
            logger.exception("Failed to analyze %s", key)
            results.append({"key": key, "error": str(exc)})

    return results


@router.post("/apply")
async def apply_suggestion(req: TriageApplyRequest, request: Request) -> dict[str, Any]:
    """Apply accepted suggestions to a ticket via Jira API."""
    _ensure_ticket_visible(req.key)
    suggestion = store.get(req.key)
    if not suggestion:
        raise HTTPException(status_code=404, detail=f"No suggestion for {req.key}")

    applied: list[str] = []
    errors: list[dict[str, str]] = []
    sid = request.cookies.get("session_id", "")
    session = get_session(sid) if sid else None
    ctx = get_jira_write_context(session, shared_client=_client)
    audit_lines: list[str] = []

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
                target_priority = normalize_triage_priority_value(s.suggested_value)
                if target_priority not in valid:
                    errors.append({"field": field_name, "error": f"Invalid priority '{target_priority}'. Valid: {', '.join(sorted(valid))}"})
                    continue
                ctx.client.update_priority(req.key, target_priority)
                cache.update_cached_field(req.key, "priority", target_priority)
                applied.append(field_name)
                audit_lines.append(f"AI applied priority -> {target_priority}")

            elif field_name == "assignee":
                from config import JIRA_PROJECT
                users = _client.get_users_assignable(JIRA_PROJECT)
                account_id = None
                for u in users:
                    if u.get("displayName", "").lower() == s.suggested_value.lower():
                        account_id = u.get("accountId")
                        break
                if account_id:
                    ctx.client.assign_issue(req.key, account_id)
                    cache.update_cached_field(
                        req.key,
                        "assignee",
                        {"displayName": s.suggested_value, "accountId": account_id},
                    )
                    applied.append(field_name)
                    audit_lines.append(f"AI applied assignee -> {s.suggested_value}")
                else:
                    errors.append({"field": field_name, "error": f"Could not find user: {s.suggested_value}"})

            elif field_name == "reporter":
                account_id = _client.find_user_account_id(s.suggested_value)
                if account_id:
                    ctx.client.update_reporter(req.key, account_id)
                    cache.update_cached_field(
                        req.key,
                        "reporter",
                        {"displayName": s.suggested_value, "accountId": account_id},
                    )
                    applied.append(field_name)
                    audit_lines.append(f"AI applied reporter -> {s.suggested_value}")
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
                    ctx.client.transition_issue(req.key, transition_id)
                    cache.update_cached_field(req.key, "status", s.suggested_value)
                    applied.append(field_name)
                    audit_lines.append(f"AI applied status -> {s.suggested_value}")
                else:
                    errors.append({
                        "field": field_name,
                        "error": f"No transition to '{s.suggested_value}' available",
                    })

            elif field_name == "request_type":
                from ai_client import get_request_type_id
                rt_id = get_request_type_id(s.suggested_value)
                if rt_id:
                    ctx.client.set_request_type(req.key, rt_id)
                    cache.update_cached_field(req.key, "request_type", s.suggested_value)
                    applied.append(field_name)
                    audit_lines.append(f"AI applied request type -> {s.suggested_value}")
                else:
                    errors.append({"field": field_name, "error": f"Unknown request type: {s.suggested_value}"})

            elif field_name == "comment":
                comment_text = f"[AI-Suggestion] {s.suggested_value}"
                if ctx.is_fallback:
                    comment_text = prepend_fallback_actor_line(comment_text, session)
                ctx.client.add_comment(req.key, comment_text)
                applied.append(field_name)

            else:
                errors.append({"field": field_name, "error": f"Unsupported field: {field_name}"})

        except Exception as exc:
            errors.append({"field": field_name, "error": str(exc)})

    # Only delete suggestion if at least one field was successfully applied
    if applied:
        store.delete(req.key)
        if ctx.is_fallback and audit_lines:
            add_fallback_internal_audit_note(
                req.key,
                action_summary="; ".join(audit_lines),
                session=session,
                shared_client=_client,
            )

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
    ctx = get_jira_write_context(session, shared_client=_client)

    # Apply the field to Jira
    try:
        if req.field == "priority":
            from ai_client import _get_valid_priorities
            valid = _get_valid_priorities()
            target_priority = normalize_triage_priority_value(s.suggested_value)
            if target_priority not in valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid priority '{target_priority}'. Valid: {', '.join(sorted(valid))}",
                )
            ctx.client.update_priority(req.key, target_priority)
            cache.update_cached_field(req.key, "priority", target_priority)

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
            ctx.client.assign_issue(req.key, account_id)
            cache.update_cached_field(
                req.key,
                "assignee",
                {"displayName": s.suggested_value, "accountId": account_id},
            )

        elif req.field == "reporter":
            account_id = _client.find_user_account_id(s.suggested_value)
            if not account_id:
                raise HTTPException(status_code=400, detail=f"Could not find reporter: {s.suggested_value}")
            ctx.client.update_reporter(req.key, account_id)
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
            ctx.client.transition_issue(req.key, transition_id)
            cache.update_cached_field(req.key, "status", s.suggested_value)

        elif req.field == "request_type":
            from ai_client import get_request_type_id
            rt_id = get_request_type_id(s.suggested_value)
            if not rt_id:
                raise HTTPException(status_code=400, detail=f"Unknown request type: {s.suggested_value}")
            ctx.client.set_request_type(req.key, rt_id)
            cache.update_cached_field(req.key, "request_type", s.suggested_value)

        elif req.field == "comment":
            comment_text = f"[AI-Suggestion] {s.suggested_value}"
            if ctx.is_fallback:
                comment_text = prepend_fallback_actor_line(comment_text, session)
            ctx.client.add_comment(req.key, comment_text)

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
        new_value=normalize_triage_priority_value(s.suggested_value) if req.field == "priority" else s.suggested_value,
        confidence=s.confidence,
        model=suggestion.model_used,
        source="user",
        approved_by=approved_by,
    )

    # Remove the field from the stored suggestion (deletes row if none left)
    remaining = store.remove_field(req.key, req.field)
    if ctx.is_fallback and req.field != "comment":
        add_fallback_internal_audit_note(
            req.key,
            action_summary=(
                f"AI applied {req.field} -> "
                f"{normalize_triage_priority_value(s.suggested_value) if req.field == 'priority' else s.suggested_value}"
            ),
            session=session,
            shared_client=_client,
        )

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
