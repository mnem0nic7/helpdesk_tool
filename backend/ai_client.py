"""AI provider abstraction for ticket triage analysis."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from config import OPENAI_API_KEY, ANTHROPIC_API_KEY
from models import AIModel, TriageResult, TriageSuggestion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

MODELS: list[dict[str, str]] = [
    {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai"},
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "openai"},
    {"id": "gpt-4.1", "name": "GPT-4.1", "provider": "openai"},
    {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini", "provider": "openai"},
    {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "provider": "anthropic"},
    {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "provider": "anthropic"},
]


def get_available_models() -> list[AIModel]:
    """Return models filtered by which API keys are configured."""
    available: list[AIModel] = []
    for m in MODELS:
        if m["provider"] == "openai" and OPENAI_API_KEY:
            available.append(AIModel(**m))
        elif m["provider"] == "anthropic" and ANTHROPIC_API_KEY:
            available.append(AIModel(**m))
    return available


def _get_model_provider(model_id: str) -> str | None:
    for m in MODELS:
        if m["id"] == model_id:
            return m["provider"]
    return None


# ---------------------------------------------------------------------------
# ADF text extraction
# ---------------------------------------------------------------------------


def extract_adf_text(adf: dict | None) -> str:
    """Recursively walk Atlassian Document Format and extract plain text."""
    if not adf or not isinstance(adf, dict):
        return ""

    parts: list[str] = []

    if adf.get("type") == "text":
        parts.append(adf.get("text", ""))

    for child in adf.get("content", []):
        parts.append(extract_adf_text(child))

    return "".join(parts)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

KNOWN_PRIORITIES = ["Highest", "High", "Medium", "Low", "New"]

KNOWN_STATUSES = [
    "New", "Open", "Assigned", "In Progress", "Work in Progress",
    "Investigating", "Waiting for Customer", "Waiting for Support",
    "Pending", "Pending Customer", "Pending Vendor", "Scheduled",
    "On Hold", "Awaiting Approval", "Waiting for Approval",
    "Resolved", "Closed", "Done", "Cancelled", "Declined",
]

SYSTEM_PROMPT = """\
You are an IT helpdesk triage assistant for a Jira Service Management project (OIT).
Your job is to analyze tickets and suggest improvements for: priority, status, assignee, and an optional comment.

Rules:
- Only suggest changes where you see a clear improvement. If a field looks correct, omit it.
- Priority must be one of: {priorities}
- Status must be one of: {statuses}
- For assignee, suggest a name only if you can identify the right person from context. Otherwise omit.
- For comments, suggest a brief triage note only if it would help the agent handling the ticket.
- Provide a confidence score (0.0-1.0) and brief reasoning for each suggestion.

Respond with ONLY valid JSON (no markdown fences) in this format:
{{
  "suggestions": [
    {{
      "field": "priority",
      "suggested_value": "High",
      "reasoning": "Customer reports complete service outage",
      "confidence": 0.85
    }}
  ]
}}

If no changes are needed, return: {{"suggestions": []}}
"""


def _build_ticket_context(issue: dict[str, Any]) -> str:
    """Build a text representation of a ticket for the AI prompt."""
    fields = issue.get("fields", {})

    # Basic info
    key = issue.get("key", "")
    summary = fields.get("summary", "")
    description = extract_adf_text(fields.get("description"))

    # Status
    status_obj = fields.get("status") or {}
    status = status_obj.get("name", "Unknown")

    # Priority
    priority_obj = fields.get("priority") or {}
    priority = priority_obj.get("name", "None")

    # Assignee
    assignee_obj = fields.get("assignee") or {}
    assignee = (
        assignee_obj.get("displayName", "Unassigned")
        if isinstance(assignee_obj, dict)
        else "Unassigned"
    )

    # Issue type
    issuetype_obj = fields.get("issuetype") or {}
    issue_type = issuetype_obj.get("name", "")

    # Request type
    request_type = ""
    crf = fields.get("customfield_10010")
    if crf and isinstance(crf, dict):
        rt_obj = crf.get("requestType")
        if isinstance(rt_obj, dict):
            request_type = rt_obj.get("name", "")

    # Dates
    created = fields.get("created", "")
    updated = fields.get("updated", "")

    # Labels
    labels = fields.get("labels") or []

    # Comments (last 5)
    comment_data = fields.get("comment") or {}
    comments = comment_data.get("comments", []) if isinstance(comment_data, dict) else []
    recent_comments = comments[-5:]
    comment_texts: list[str] = []
    for c in recent_comments:
        author = (c.get("author") or {}).get("displayName", "Unknown")
        body = extract_adf_text(c.get("body"))
        if body:
            comment_texts.append(f"  [{author}]: {body[:300]}")

    lines = [
        f"Ticket: {key}",
        f"Type: {issue_type}",
        f"Request Type: {request_type or 'Not set'}",
        f"Summary: {summary}",
        f"Status: {status}",
        f"Priority: {priority}",
        f"Assignee: {assignee}",
        f"Labels: {', '.join(labels) if labels else 'None'}",
        f"Created: {created}",
        f"Updated: {updated}",
    ]
    if description:
        lines.append(f"Description:\n{description[:1000]}")
    if comment_texts:
        lines.append("Recent Comments:\n" + "\n".join(comment_texts))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AI API calls
# ---------------------------------------------------------------------------


def _call_openai(model_id: str, system: str, user_msg: str) -> str:
    """Call OpenAI API and return the response text."""
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.3,
        max_tokens=1000,
    )
    return resp.choices[0].message.content or ""


def _call_anthropic(model_id: str, system: str, user_msg: str) -> str:
    """Call Anthropic API and return the response text."""
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=model_id,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.3,
        max_tokens=1000,
    )
    return resp.content[0].text


def _parse_suggestions(raw: str, issue: dict[str, Any]) -> list[TriageSuggestion]:
    """Parse AI response JSON into TriageSuggestion list."""
    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse AI response as JSON: %s", text[:200])
        return []

    fields_data = issue.get("fields", {})
    current_values = {
        "priority": (fields_data.get("priority") or {}).get("name", ""),
        "status": (fields_data.get("status") or {}).get("name", ""),
        "assignee": (
            (fields_data.get("assignee") or {}).get("displayName", "Unassigned")
            if isinstance(fields_data.get("assignee"), dict)
            else "Unassigned"
        ),
        "comment": "",
        "request_type": "",
    }

    suggestions: list[TriageSuggestion] = []
    for s in data.get("suggestions", []):
        field = s.get("field", "")
        if field not in current_values:
            continue
        suggestions.append(
            TriageSuggestion(
                field=field,
                current_value=current_values.get(field, ""),
                suggested_value=s.get("suggested_value", ""),
                reasoning=s.get("reasoning", ""),
                confidence=float(s.get("confidence", 0.5)),
            )
        )
    return suggestions


# ---------------------------------------------------------------------------
# Main analysis entry point
# ---------------------------------------------------------------------------


def analyze_ticket(issue: dict[str, Any], model_id: str) -> TriageResult:
    """Analyze a single ticket and return triage suggestions."""
    provider = _get_model_provider(model_id)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")

    system = SYSTEM_PROMPT.format(
        priorities=", ".join(KNOWN_PRIORITIES),
        statuses=", ".join(KNOWN_STATUSES),
    )
    user_msg = _build_ticket_context(issue)

    logger.info("Analyzing %s with %s (%s)", issue.get("key"), model_id, provider)

    if provider == "openai":
        raw = _call_openai(model_id, system, user_msg)
    elif provider == "anthropic":
        raw = _call_anthropic(model_id, system, user_msg)
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    suggestions = _parse_suggestions(raw, issue)

    return TriageResult(
        key=issue.get("key", ""),
        suggestions=suggestions,
        model_used=model_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Suggestion validation against live Jira data
# ---------------------------------------------------------------------------

# TTL-cached lookups to avoid hammering the Jira API on every validation.
_priority_cache: tuple[float, set[str]] = (0.0, set())
_user_cache: tuple[float, dict[str, str]] = (0.0, {})  # display_name_lower -> accountId
_CACHE_TTL = 600  # 10 minutes


def _get_valid_priorities() -> set[str]:
    """Return the set of valid priority names, cached with TTL."""
    global _priority_cache
    now = time.monotonic()
    if _priority_cache[1] and now - _priority_cache[0] < _CACHE_TTL:
        return _priority_cache[1]

    from jira_client import JiraClient
    try:
        client = JiraClient()
        raw = client.get_priorities()
        names = {p.get("name", "") for p in raw if p.get("name")}
        _priority_cache = (now, names)
        logger.info("Validation: cached %d valid priorities: %s", len(names), names)
        return names
    except Exception:
        logger.exception("Validation: failed to fetch priorities from Jira")
        # Fall back to hardcoded list so we don't block analysis
        return set(KNOWN_PRIORITIES)


def _get_valid_users() -> dict[str, str]:
    """Return {display_name_lower: accountId} for assignable users, cached with TTL."""
    global _user_cache
    now = time.monotonic()
    if _user_cache[1] and now - _user_cache[0] < _CACHE_TTL:
        return _user_cache[1]

    from jira_client import JiraClient
    from config import JIRA_PROJECT
    try:
        client = JiraClient()
        raw = client.get_users_assignable(JIRA_PROJECT)
        users = {
            u.get("displayName", "").lower(): u.get("accountId", "")
            for u in raw
            if u.get("displayName") and u.get("accountId")
        }
        _user_cache = (now, users)
        logger.info("Validation: cached %d assignable users", len(users))
        return users
    except Exception:
        logger.exception("Validation: failed to fetch assignable users from Jira")
        return {}


def _get_reachable_statuses(key: str) -> set[str]:
    """Return the set of status names reachable via transitions for an issue."""
    from jira_client import JiraClient
    try:
        client = JiraClient()
        transitions = client.get_transitions(key)
        names = set()
        for t in transitions:
            # Transition name (e.g. "Start Progress")
            names.add(t.get("name", "").lower())
            # Target status name (e.g. "In Progress")
            to_status = t.get("to", {})
            if isinstance(to_status, dict):
                names.add(to_status.get("name", "").lower())
        return names
    except Exception:
        logger.exception("Validation: failed to fetch transitions for %s", key)
        return set()


def validate_suggestions(key: str, suggestions: list[TriageSuggestion]) -> list[TriageSuggestion]:
    """Filter out suggestions that reference invalid priorities, users, or statuses.

    Returns the subset of suggestions that are valid. Invalid ones are logged
    and silently dropped so the user only sees actionable suggestions.
    """
    if not suggestions:
        return suggestions

    valid: list[TriageSuggestion] = []
    priorities: set[str] | None = None
    users: dict[str, str] | None = None
    reachable: set[str] | None = None

    for s in suggestions:
        if s.field == "priority":
            if priorities is None:
                priorities = _get_valid_priorities()
            if s.suggested_value not in priorities:
                logger.warning(
                    "Validation: dropping %s priority suggestion '%s' — "
                    "not in valid priorities %s",
                    key, s.suggested_value, priorities,
                )
                continue

        elif s.field == "assignee":
            if users is None:
                users = _get_valid_users()
            if s.suggested_value.lower() not in users:
                logger.warning(
                    "Validation: dropping %s assignee suggestion '%s' — "
                    "not an assignable user",
                    key, s.suggested_value,
                )
                continue

        elif s.field == "status":
            if reachable is None:
                reachable = _get_reachable_statuses(key)
            if s.suggested_value.lower() not in reachable:
                logger.warning(
                    "Validation: dropping %s status suggestion '%s' — "
                    "not a reachable transition (available: %s)",
                    key, s.suggested_value, reachable,
                )
                continue

        # comment and other fields pass through without validation
        valid.append(s)

    dropped = len(suggestions) - len(valid)
    if dropped:
        logger.info("Validation: %s — kept %d/%d suggestions (%d invalid dropped)",
                     key, len(valid), len(suggestions), dropped)
    return valid
