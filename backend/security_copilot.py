"""Ollama-backed Azure security incident copilot orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Callable

from ai_client import extract_adf_text, invoke_model_text
from auth import list_login_audit, session_can_manage_users
from azure_alert_store import azure_alert_store
from azure_cache import azure_cache
from issue_cache import cache
from knowledge_base import kb_store
from mailbox_delegate_scan_jobs import mailbox_delegate_scan_jobs
from models import (
    AzureCitation,
    SecurityCopilotAnswer,
    SecurityCopilotChatRequest,
    SecurityCopilotChatMessage,
    SecurityCopilotChatResponse,
    SecurityCopilotFollowUpQuestion,
    SecurityCopilotIdentityCandidate,
    SecurityCopilotIncident,
    SecurityCopilotJobRef,
    SecurityCopilotPlannedSource,
    SecurityCopilotSourceResult,
)
from request_type import extract_request_type_name_from_fields
from site_context import get_current_site_scope
from user_admin_jobs import user_admin_jobs
from user_admin_providers import UserAdminProviderError, user_admin_providers

logger = logging.getLogger(__name__)

_INCIDENT_PROMPT = """You are an internal security incident intake copilot.
Read the current normalized incident profile plus the newest user message and update the incident facts.

Rules:
- Return only JSON.
- Use one lane from: identity_compromise, mailbox_abuse, app_or_service_principal, azure_alert_or_resource, unknown.
- Preserve existing facts unless the new message clearly adds or corrects them.
- Extract concrete identifiers when present: users, mailboxes, apps, resources, alerts, URLs, IPs, GUIDs.
- Keep timeframe as plain text exactly as the operator would understand it.
- Do not invent facts that are not grounded in the chat.
- If the user message is too vague, keep the lane as unknown unless the evidence is strong.

Return exactly this JSON shape:
{
  "lane": "unknown",
  "summary": "",
  "timeframe": "",
  "affected_users": [],
  "affected_mailboxes": [],
  "affected_apps": [],
  "affected_resources": [],
  "alert_names": [],
  "observed_artifacts": [],
  "confidence": 0.0
}
"""

_ANSWER_PROMPT = """You are a security incident copilot for an internal Azure and IT operations portal.
Summarize only from the provided incident profile and grounded source results.

Rules:
- Return only JSON.
- Do not claim that any destructive action was performed.
- Call out stale or unavailable sources when they materially limit confidence.
- If results are empty, say that clearly instead of speculating.
- Keep findings concrete and operator-friendly.

Return exactly this JSON shape:
{
  "summary": "",
  "findings": [],
  "next_steps": [],
  "warnings": []
}
"""

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_GUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_RESOURCE_ID_RE = re.compile(r"/subscriptions/[^\s]+", re.IGNORECASE)
_TIMEFRAME_RE = re.compile(
    r"\b(last\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+\w+|since\s+[^,.]+|from\s+[^,.]+\s+to\s+[^,.]+|today|yesterday|overnight|this morning|this afternoon)\b",
    re.IGNORECASE,
)
_DISPLAY_NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b")
_NAME_CONTEXT_PATTERNS = (
    re.compile(r"\b([A-Za-z][A-Za-z'.-]+(?:\s+[A-Za-z][A-Za-z'.-]+){1,2})\s+(?:had|has|reported|reports|triggered|received|showed|shows)\b", re.IGNORECASE),
    re.compile(r"\b(?:user|employee|account|for|investigate|check)\s+([A-Za-z][A-Za-z'.-]+(?:\s+[A-Za-z][A-Za-z'.-]+){1,2})\b", re.IGNORECASE),
)
_IDENTITY_CONFIRM_YES = {"yes", "y", "confirm", "confirmed", "that's right", "that one", "correct"}
_IDENTITY_CONFIRM_INDEX = {
    "1": 0,
    "first": 0,
    "the first one": 0,
    "option 1": 0,
    "2": 1,
    "second": 1,
    "the second one": 1,
    "option 2": 1,
    "3": 2,
    "third": 2,
    "the third one": 2,
    "option 3": 2,
}
_MAX_PREVIEW_ROWS = 6


@dataclass(frozen=True)
class SecuritySourceDefinition:
    key: str
    label: str
    permission: str
    applies: Callable[[SecurityCopilotIncident], bool]
    query_summary: Callable[[SecurityCopilotIncident], str]
    runner: Callable[
        [SecurityCopilotIncident, dict[str, Any], list[SecurityCopilotJobRef]],
        tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]],
    ]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: Any, limit: int = 180) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _unique_list(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _identity_candidate_value(candidate: SecurityCopilotIdentityCandidate) -> str:
    return str(candidate.principal_name or candidate.mail or candidate.display_name or "").strip()


def _identity_candidate_label(candidate: SecurityCopilotIdentityCandidate) -> str:
    identity = _identity_candidate_value(candidate)
    display_name = str(candidate.display_name or "").strip()
    if display_name and identity and display_name.lower() != identity.lower():
        return f"{display_name} <{identity}>"
    return display_name or identity


def _normalize_identity_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _clear_identity_candidates(incident: SecurityCopilotIncident) -> SecurityCopilotIncident:
    if not incident.identity_candidates and not incident.identity_query:
        return incident
    updated = incident.model_copy(deep=True)
    updated.identity_query = ""
    updated.identity_candidates = []
    return updated


def _extract_identity_lookup_queries(*texts: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for text in texts:
        raw = str(text or "").strip()
        if not raw:
            continue
        for pattern in _NAME_CONTEXT_PATTERNS:
            for match in pattern.findall(raw):
                normalized = re.sub(r"\s+", " ", str(match or "").strip())
                key = normalized.lower()
                if key and key not in seen:
                    seen.add(key)
                    candidates.append(normalized)
        for match in _DISPLAY_NAME_RE.findall(raw):
            normalized = re.sub(r"\s+", " ", str(match or "").strip())
            key = normalized.lower()
            if key and key not in seen:
                seen.add(key)
                candidates.append(normalized)
    return candidates[:3]


def _lookup_identity_candidates(*queries: str) -> tuple[str, list[SecurityCopilotIdentityCandidate]]:
    for query in _extract_identity_lookup_queries(*queries):
        try:
            rows = azure_cache.list_directory_objects("users", search=query)[:6]
        except Exception:
            logger.exception("Security copilot failed to resolve Azure user candidates for %s", query)
            return "", []
        candidates: list[SecurityCopilotIdentityCandidate] = []
        query_lower = query.lower()
        for row in rows:
            display_name = str(row.get("display_name") or "").strip()
            principal_name = str(row.get("principal_name") or "").strip()
            mail = str(row.get("mail") or "").strip()
            if not (display_name or principal_name or mail):
                continue
            match_reason = "display_name_contains"
            if display_name.lower() == query_lower:
                match_reason = "display_name_exact"
            elif principal_name.lower() == query_lower or mail.lower() == query_lower:
                match_reason = "principal_exact"
            candidates.append(
                SecurityCopilotIdentityCandidate(
                    id=str(row.get("id") or ""),
                    display_name=display_name,
                    principal_name=principal_name,
                    mail=mail,
                    match_reason=match_reason,
                )
            )
        if candidates:
            candidates.sort(
                key=lambda item: (
                    0 if item.match_reason == "display_name_exact" else 1 if item.match_reason == "principal_exact" else 2,
                    _identity_candidate_label(item).lower(),
                )
            )
            deduped: list[SecurityCopilotIdentityCandidate] = []
            seen: set[str] = set()
            for candidate in candidates:
                key = _normalize_identity_text(_identity_candidate_value(candidate))
                if not key or key in seen:
                    continue
                seen.add(key)
                deduped.append(candidate)
            if deduped:
                return query, deduped[:4]
    return "", []


def _resolve_identity_candidate_reply(
    incident: SecurityCopilotIncident,
    message: str,
) -> SecurityCopilotIncident:
    if not incident.identity_candidates or incident.affected_users:
        return incident
    normalized = _normalize_identity_text(message)
    if not normalized:
        return incident

    chosen: SecurityCopilotIdentityCandidate | None = None
    if normalized in _IDENTITY_CONFIRM_YES and len(incident.identity_candidates) == 1:
        chosen = incident.identity_candidates[0]
    elif normalized in _IDENTITY_CONFIRM_INDEX:
        index = _IDENTITY_CONFIRM_INDEX[normalized]
        if 0 <= index < len(incident.identity_candidates):
            chosen = incident.identity_candidates[index]
    else:
        for candidate in incident.identity_candidates:
            haystacks = {
                _normalize_identity_text(candidate.display_name),
                _normalize_identity_text(candidate.principal_name),
                _normalize_identity_text(candidate.mail),
                _normalize_identity_text(_identity_candidate_label(candidate)),
            }
            if any(value and value in normalized for value in haystacks):
                chosen = candidate
                break

    if chosen is None:
        return incident

    updated = incident.model_copy(deep=True)
    identity = _identity_candidate_value(chosen)
    if identity:
        updated.affected_users = _unique_list([identity, *updated.affected_users])
    if updated.lane == "mailbox_abuse":
        mailbox = str(chosen.mail or chosen.principal_name or "").strip()
        if mailbox:
            updated.affected_mailboxes = _unique_list([mailbox, *updated.affected_mailboxes])
    updated.identity_query = ""
    updated.identity_candidates = []
    return updated


def _resolve_identity_candidates(
    incident: SecurityCopilotIncident,
    *texts: str,
) -> SecurityCopilotIncident:
    if incident.affected_users or incident.lane not in {"identity_compromise", "unknown"}:
        return _clear_identity_candidates(incident)
    query, candidates = _lookup_identity_candidates(*texts)
    if not candidates:
        return incident
    updated = incident.model_copy(deep=True)
    updated.identity_query = query
    updated.identity_candidates = candidates
    return updated


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {}


def _merge_summary(current_summary: str, update_summary: str) -> str:
    current_text = str(current_summary or "").strip()
    update_text = str(update_summary or "").strip()
    if not update_text:
        return current_text
    if not current_text:
        return update_text
    normalized = _normalize_identity_text(update_text)
    if normalized in _IDENTITY_CONFIRM_YES or normalized in _IDENTITY_CONFIRM_INDEX:
        return current_text
    if len(update_text.split()) <= 5 and len(update_text) <= 64:
        return current_text
    if normalized in _normalize_identity_text(current_text):
        return current_text
    return update_text


def _compact_history(history: list[SecurityCopilotChatMessage]) -> list[dict[str, str]]:
    transcript: list[dict[str, str]] = []
    for item in history[-6:]:
        content = _clip(item.content, 280)
        if not content:
            continue
        transcript.append(
            {
                "role": item.role,
                "content": content,
            }
        )
    return transcript


def _lane_from_keywords(text: str, existing_lane: str = "unknown") -> str:
    lowered = text.lower()
    lane_keywords = (
        (
            "mailbox_abuse",
            (
                "mailbox",
                "inbox rule",
                "forwarding",
                "forwarded",
                "send as",
                "send on behalf",
                "delegate",
                "outlook rule",
                "transport rule",
            ),
        ),
        (
            "app_or_service_principal",
            (
                "service principal",
                "enterprise app",
                "app registration",
                "client secret",
                "application id",
                "consent",
                "oauth app",
                "token",
            ),
        ),
        (
            "azure_alert_or_resource",
            (
                "azure alert",
                "defender",
                "resource group",
                "subscription",
                "virtual machine",
                "vm ",
                "avd",
                "wvd",
                "virtual desktop",
                "resource id",
            ),
        ),
        (
            "identity_compromise",
            (
                "impossible travel",
                "risky user",
                "sign-in",
                "signin",
                "mfa",
                "compromised",
                "unauthorized access",
                "account takeover",
                "password spray",
                "phish",
            ),
        ),
    )
    for lane, keywords in lane_keywords:
        if any(keyword in lowered for keyword in keywords):
            return lane
    return existing_lane if existing_lane != "unknown" else "unknown"


def _heuristic_incident_update(message: str, existing: SecurityCopilotIncident) -> SecurityCopilotIncident:
    text = str(message or "").strip()
    lane = _lane_from_keywords(text, existing.lane)
    emails = _unique_list(_EMAIL_RE.findall(text))
    urls = _unique_list(_URL_RE.findall(text))
    ips = _unique_list(_IP_RE.findall(text))
    guids = _unique_list(_GUID_RE.findall(text))
    resources = _unique_list(_RESOURCE_ID_RE.findall(text))
    timeframe_match = _TIMEFRAME_RE.search(text)
    timeframe = timeframe_match.group(1).strip() if timeframe_match else ""
    artifacts = _unique_list([*urls, *ips, *guids])

    affected_users: list[str] = []
    affected_mailboxes: list[str] = []
    if lane == "mailbox_abuse":
        affected_mailboxes = emails
        affected_users = emails
    elif lane == "identity_compromise":
        affected_users = emails
        affected_mailboxes = emails
    else:
        affected_users = emails
        if "mailbox" in text.lower():
            affected_mailboxes = emails

    affected_apps = guids if lane == "app_or_service_principal" else []
    if lane == "azure_alert_or_resource" and not resources and guids:
        resources = guids

    alert_names: list[str] = []
    if "alert" in text.lower():
        alert_names = [_clip(text, 120)]

    return SecurityCopilotIncident(
        lane=lane,
        summary=text,
        timeframe=timeframe,
        affected_users=affected_users,
        affected_mailboxes=affected_mailboxes,
        affected_apps=affected_apps,
        affected_resources=resources,
        alert_names=alert_names,
        observed_artifacts=artifacts,
        confidence=0.45 if text else 0.0,
    )


def _invoke_incident_model(
    message: str,
    incident: SecurityCopilotIncident,
    model_id: str,
    history: list[SecurityCopilotChatMessage] | None = None,
) -> SecurityCopilotIncident | None:
    if not message.strip():
        return None
    payload = {
        "current_incident": incident.model_dump(),
        "recent_history": _compact_history(history or []),
        "new_user_message": message.strip(),
    }
    try:
        raw = invoke_model_text(
            model_id,
            _INCIDENT_PROMPT,
            json.dumps(payload, separators=(",", ":")),
            feature_surface="azure_security_copilot",
            app_surface="azure_portal",
            actor_type="user",
            actor_id="azure-security-copilot",
            max_output_tokens=900,
            json_output=True,
            metadata={"stage": "intake", "message_length": len(message.strip())},
        )
        parsed = _extract_json_object(raw)
        return SecurityCopilotIncident.model_validate(parsed)
    except Exception:
        logger.exception("Security copilot intake parse failed")
        return None


def _merge_incident(
    current: SecurityCopilotIncident,
    update: SecurityCopilotIncident | None,
) -> SecurityCopilotIncident:
    if update is None:
        merged = current.model_copy(deep=True)
    else:
        lane = update.lane if update.lane != "unknown" else current.lane
        merged = SecurityCopilotIncident(
            lane=lane if lane else "unknown",
            summary=_clip(_merge_summary(current.summary, update.summary), 600),
            timeframe=update.timeframe or current.timeframe,
            affected_users=_unique_list([*current.affected_users, *update.affected_users]),
            affected_mailboxes=_unique_list([*current.affected_mailboxes, *update.affected_mailboxes]),
            affected_apps=_unique_list([*current.affected_apps, *update.affected_apps]),
            affected_resources=_unique_list([*current.affected_resources, *update.affected_resources]),
            alert_names=_unique_list([*current.alert_names, *update.alert_names]),
            observed_artifacts=_unique_list([*current.observed_artifacts, *update.observed_artifacts]),
            identity_query=current.identity_query,
            identity_candidates=[candidate.model_copy(deep=True) for candidate in current.identity_candidates],
            confidence=max(float(current.confidence or 0.0), float(update.confidence or 0.0)),
            missing_fields=[],
        )

    if merged.lane == "mailbox_abuse" and not merged.affected_mailboxes and merged.affected_users:
        merged.affected_mailboxes = list(merged.affected_users)
    if merged.lane == "identity_compromise" and not merged.affected_users and merged.affected_mailboxes:
        merged.affected_users = list(merged.affected_mailboxes)
    if merged.lane == "app_or_service_principal" and not merged.affected_apps:
        merged.affected_apps = [
            artifact
            for artifact in merged.observed_artifacts
            if _GUID_RE.fullmatch(artifact)
        ]
    return merged


def _resolve_incident_profile(
    message: str,
    current: SecurityCopilotIncident,
    model_id: str,
    history: list[SecurityCopilotChatMessage] | None = None,
) -> SecurityCopilotIncident:
    heuristic = _heuristic_incident_update(message, current)
    merged = _merge_incident(current, heuristic)
    ai_update = _invoke_incident_model(message, merged, model_id, history=history)
    merged = _merge_incident(merged, ai_update)
    merged = _resolve_identity_candidate_reply(merged, message)
    merged = _resolve_identity_candidates(merged, message, merged.summary)
    if merged.affected_users:
        merged = _clear_identity_candidates(merged)
    if not merged.summary and message.strip():
        merged.summary = _clip(message.strip(), 600)
    merged.missing_fields = _missing_fields_for_incident(merged)
    return merged


def _missing_fields_for_incident(incident: SecurityCopilotIncident) -> list[str]:
    missing: list[str] = []
    if not incident.summary.strip():
        missing.append("summary")
    if not incident.timeframe.strip():
        missing.append("timeframe")

    if incident.identity_candidates and not incident.affected_users:
        missing.append("identity_confirmation")
    elif incident.lane == "identity_compromise" and not incident.affected_users:
        missing.append("affected_users")
    elif incident.lane == "mailbox_abuse" and not incident.affected_mailboxes:
        missing.append("affected_mailboxes")
    elif incident.lane == "app_or_service_principal" and not incident.affected_apps:
        missing.append("affected_apps")
    elif incident.lane == "azure_alert_or_resource" and not (incident.affected_resources or incident.alert_names):
        missing.append("affected_resources")
    elif incident.lane == "unknown":
        if not (
            incident.affected_users
            or incident.affected_mailboxes
            or incident.affected_apps
            or incident.affected_resources
            or incident.alert_names
            or incident.observed_artifacts
        ):
            missing.append("scope")
    return missing


def _follow_up_question(field_key: str, incident: SecurityCopilotIncident) -> SecurityCopilotFollowUpQuestion:
    identity_choices = [_identity_candidate_label(candidate) for candidate in incident.identity_candidates]
    identity_query = incident.identity_query or "that name"
    catalog: dict[str, SecurityCopilotFollowUpQuestion] = {
        "summary": SecurityCopilotFollowUpQuestion(
            key="summary",
            label="Incident summary",
            prompt="What is happening, in one or two sentences?",
            placeholder="Example: User reported suspicious sign-ins and new MFA prompts.",
            input_type="textarea",
        ),
        "timeframe": SecurityCopilotFollowUpQuestion(
            key="timeframe",
            label="Timeframe",
            prompt="When did this start, or what time window should I investigate?",
            placeholder="Example: Since 2:00 AM UTC today.",
        ),
        "affected_users": SecurityCopilotFollowUpQuestion(
            key="affected_users",
            label="Affected user",
            prompt="Which user account should I investigate first?",
            placeholder="Example: ada@example.com",
            input_type="email",
        ),
        "identity_confirmation": SecurityCopilotFollowUpQuestion(
            key="identity_confirmation",
            label="Confirm user account",
            prompt=(
                f"I found {len(identity_choices)} Azure user match(es) for {identity_query}. "
                "Confirm which account I should investigate first."
            ),
            placeholder="Reply with the exact account, or click one of the matches below.",
            input_type="list",
            choices=identity_choices,
        ),
        "affected_mailboxes": SecurityCopilotFollowUpQuestion(
            key="affected_mailboxes",
            label="Affected mailbox",
            prompt="Which mailbox or shared mailbox is involved?",
            placeholder="Example: payroll@example.com",
            input_type="email",
        ),
        "affected_apps": SecurityCopilotFollowUpQuestion(
            key="affected_apps",
            label="Affected app",
            prompt="Which app, service principal, app registration, or app ID should I investigate?",
            placeholder="Example: finance-bot or 11111111-2222-3333-4444-555555555555",
        ),
        "affected_resources": SecurityCopilotFollowUpQuestion(
            key="affected_resources",
            label="Affected Azure resource",
            prompt="Which Azure alert, resource, VM, or resource ID should I look into?",
            placeholder="Example: vm-payroll-01 or /subscriptions/.../virtualMachines/vm-payroll-01",
        ),
        "scope": SecurityCopilotFollowUpQuestion(
            key="scope",
            label="Scope hint",
            prompt="What concrete identifier do you already have, like a user, mailbox, app, resource, IP, URL, or alert name?",
            placeholder="Example: ada@example.com and impossible travel alert.",
            input_type="textarea",
        ),
    }
    return catalog[field_key]


def _build_follow_up_questions(incident: SecurityCopilotIncident) -> list[SecurityCopilotFollowUpQuestion]:
    return [_follow_up_question(field_key, incident) for field_key in incident.missing_fields[:3]]


def _lane_label(lane: str) -> str:
    labels = {
        "identity_compromise": "identity compromise",
        "mailbox_abuse": "mailbox abuse",
        "app_or_service_principal": "app or service principal abuse",
        "azure_alert_or_resource": "Azure alert or resource incident",
        "unknown": "security incident",
    }
    return labels.get(lane, "security incident")


def _assistant_message_for_intake(incident: SecurityCopilotIncident) -> str:
    questions = _build_follow_up_questions(incident)
    if incident.identity_candidates and not incident.affected_users:
        options = "; ".join(_identity_candidate_label(candidate) for candidate in incident.identity_candidates[:3])
        remaining_prompts = "; ".join(
            question.prompt for question in questions if question.key != "identity_confirmation"
        )
        return (
            f"I can investigate this as {_lane_label(incident.lane)}. "
            f"I found Azure user matches for {incident.identity_query or 'the provided name'}: {options}. "
            + (
                f"Confirm which account I should investigate first. I still need: {remaining_prompts}"
                if remaining_prompts
                else "Confirm which account I should investigate first."
            )
        )
    prompts = "; ".join(question.prompt for question in questions)
    if prompts:
        return (
            f"I can investigate this as {_lane_label(incident.lane)}. "
            f"I still need {len(questions)} detail(s) before I query sources: {prompts}"
        )
    return "Share the incident details and I will build the investigation plan."


def _tokenize_summary(summary: str) -> list[str]:
    stop_words = {
        "about",
        "after",
        "alert",
        "azure",
        "been",
        "from",
        "have",
        "incident",
        "mailbox",
        "reported",
        "security",
        "since",
        "that",
        "this",
        "user",
        "with",
    }
    tokens = re.findall(r"[a-z0-9._/-]{4,}", summary.lower())
    result: list[str] = []
    for token in tokens:
        if token in stop_words:
            continue
        if token not in result:
            result.append(token)
        if len(result) >= 4:
            break
    return result


def build_query_terms(incident: SecurityCopilotIncident) -> list[str]:
    terms = _unique_list(
        [
            *incident.affected_users,
            *incident.affected_mailboxes,
            *incident.affected_apps,
            *incident.affected_resources,
            *incident.alert_names,
            *incident.observed_artifacts,
            *_tokenize_summary(incident.summary),
        ]
    )
    return terms[:8]


def _preview_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return rows[:_MAX_PREVIEW_ROWS]


def _result(
    *,
    key: str,
    label: str,
    status: str,
    query_summary: str,
    item_count: int = 0,
    highlights: list[str] | None = None,
    preview: list[dict[str, Any]] | None = None,
    citations: list[AzureCitation] | None = None,
    reason: str = "",
) -> SecurityCopilotSourceResult:
    return SecurityCopilotSourceResult(
        key=key,
        label=label,
        status=status,  # type: ignore[arg-type]
        query_summary=query_summary,
        item_count=item_count,
        highlights=highlights or [],
        preview=preview or [],
        citations=citations or [],
        reason=reason,
    )


def _tenant_status_query_summary(_incident: SecurityCopilotIncident) -> str:
    return "Tenant cache health, dataset freshness, and Azure security workspace coverage."


def _source_query_summary(incident: SecurityCopilotIncident) -> str:
    terms = build_query_terms(incident)
    return ", ".join(terms) if terms else incident.summary or "incident context"


def _format_refresh_age(value: Any) -> tuple[str, bool]:
    text = str(value or "").strip()
    if not text:
        return ("No refresh timestamp recorded", True)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return (text, False)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    hours = age.total_seconds() / 3600
    return (f"{text} ({hours:.1f} hours old)", hours > 4.0)


def _run_tenant_status_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    del incident
    status = azure_cache.status()
    overview = azure_cache.get_overview()
    last_refresh_label, stale = _format_refresh_age(status.get("last_refresh"))
    datasets = status.get("datasets") or []
    unhealthy = [
        dataset
        for dataset in datasets
        if dataset.get("configured") and dataset.get("error")
    ]
    highlights = [
        f"Azure cache initialized: {bool(status.get('initialized'))}",
        f"Last refresh: {last_refresh_label}",
        f"Configured datasets: {sum(1 for dataset in datasets if dataset.get('configured'))}",
    ]
    if unhealthy:
        highlights.append(f"Datasets with errors: {len(unhealthy)}")
    if stale:
        highlights.append("Warning: Azure cache data is stale for incident triage.")
    preview = [
        {
            "subscriptions": overview.get("subscriptions"),
            "resources": overview.get("resources"),
            "users": overview.get("users"),
            "directory_roles": overview.get("directory_roles"),
            "last_refresh": status.get("last_refresh"),
        }
    ]
    citations = [
        AzureCitation(source_type="azure_status", label="Azure cache status", detail=last_refresh_label),
    ]
    reason = "Azure cache data is older than 4 hours." if stale else ""
    return (
        _result(
            key="tenant_status",
            label="Azure tenant status",
            status="completed",
            query_summary=_tenant_status_query_summary(SecurityCopilotIncident()),
            item_count=len(datasets),
            highlights=highlights,
            preview=preview,
            citations=citations,
            reason=reason,
        ),
        jobs,
    )


def _run_alert_history_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    terms = build_query_terms(incident)
    rows = azure_alert_store.get_history(limit=100)
    if terms:
        filtered: list[dict[str, Any]] = []
        for row in rows:
            haystack = " ".join(
                [
                    str(row.get("rule_name") or ""),
                    str(row.get("trigger_type") or ""),
                    str(row.get("status") or ""),
                    json.dumps(row.get("sample_items") or [], default=str),
                ]
            ).lower()
            if any(term.lower() in haystack for term in terms):
                filtered.append(row)
        rows = filtered
    rows = rows[:_MAX_PREVIEW_ROWS]
    highlights = [
        f"{row.get('rule_name') or row.get('trigger_type')}: {row.get('status')} ({int(row.get('match_count') or 0)} matches)"
        for row in rows[:5]
    ]
    if not highlights:
        highlights = ["No matching Azure alert history rows were found."]
    citations = [
        AzureCitation(source_type="azure_alert_history", label="Azure alert history", detail=f"{len(rows)} matching rows"),
    ]
    preview = [
        {
            "rule_name": str(row.get("rule_name") or ""),
            "trigger_type": str(row.get("trigger_type") or ""),
            "status": str(row.get("status") or ""),
            "match_count": int(row.get("match_count") or 0),
            "sent_at": str(row.get("sent_at") or ""),
        }
        for row in rows
    ]
    return (
        _result(
            key="alert_history",
            label="Azure alert history",
            status="completed",
            query_summary=_source_query_summary(incident),
            item_count=len(rows),
            highlights=highlights,
            preview=preview,
            citations=citations,
        ),
        jobs,
    )


def _run_quick_search_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    terms = build_query_terms(incident)
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for term in terms[:4]:
        for item in azure_cache.quick_search(term):
            key = (str(item.get("kind") or ""), str(item.get("id") or ""))
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
            if len(results) >= _MAX_PREVIEW_ROWS:
                break
        if len(results) >= _MAX_PREVIEW_ROWS:
            break
    highlights = [
        f"{item.get('label')}: {item.get('subtitle') or item.get('route')}"
        for item in results[:5]
    ]
    if not highlights:
        highlights = ["No Azure quick-search matches were found for the current incident terms."]
    citations = [
        AzureCitation(source_type="azure_search", label="Azure quick search", detail=f"{len(results)} result(s)"),
    ]
    return (
        _result(
            key="quick_search",
            label="Azure quick search",
            status="completed",
            query_summary=_source_query_summary(incident),
            item_count=len(results),
            highlights=highlights,
            preview=_preview_rows(results),
            citations=citations,
        ),
        jobs,
    )


def _directory_search_terms(incident: SecurityCopilotIncident) -> list[str]:
    terms = _unique_list(
        [
            *incident.affected_users,
            *incident.affected_mailboxes,
            *incident.affected_apps,
            *incident.observed_artifacts,
        ]
    )
    return terms[:4]


def _run_directory_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    terms = _directory_search_terms(incident) or build_query_terms(incident)
    snapshot_map = {
        "users": "user",
        "groups": "group",
        "enterprise_apps": "enterprise_app",
        "app_registrations": "app_registration",
        "directory_roles": "directory_role",
    }
    matched: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for snapshot_name, _object_type in snapshot_map.items():
        search_term = terms[0] if terms else ""
        rows = azure_cache.list_directory_objects(snapshot_name, search=search_term)
        if len(terms) > 1:
            extra_rows: list[dict[str, Any]] = []
            for term in terms[1:]:
                extra_rows.extend(azure_cache.list_directory_objects(snapshot_name, search=term))
            rows = [*rows, *extra_rows]
        for row in rows:
            key = (snapshot_name, str(row.get("id") or ""))
            if key in seen:
                continue
            seen.add(key)
            matched.append(row)
    matched = matched[:_MAX_PREVIEW_ROWS]
    highlights = [
        f"{row.get('object_type')}: {row.get('display_name')} ({row.get('principal_name') or row.get('mail') or row.get('app_id') or row.get('id')})"
        for row in matched[:5]
    ]
    if not highlights:
        highlights = ["No directory object matches were found."]
    citations = [
        AzureCitation(source_type="directory", label="Azure directory", detail=f"{len(matched)} matching object(s)"),
    ]
    preview = [
        {
            "object_type": str(row.get("object_type") or ""),
            "display_name": str(row.get("display_name") or ""),
            "principal_name": str(row.get("principal_name") or ""),
            "mail": str(row.get("mail") or ""),
            "app_id": str(row.get("app_id") or ""),
        }
        for row in matched
    ]
    return (
        _result(
            key="directory",
            label="Azure directory objects",
            status="completed",
            query_summary=_source_query_summary(incident),
            item_count=len(matched),
            highlights=highlights,
            preview=preview,
            citations=citations,
        ),
        jobs,
    )


def _run_role_assignments_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    terms = build_query_terms(incident)
    rows = azure_cache._snapshot("role_assignments") or []
    if terms:
        filtered: list[dict[str, Any]] = []
        for row in rows:
            haystack = " ".join(
                [
                    str(row.get("scope") or ""),
                    str(row.get("principal_id") or ""),
                    str(row.get("principal_type") or ""),
                    str(row.get("role_name") or ""),
                    str(row.get("subscription_name") or ""),
                ]
            ).lower()
            if any(term.lower() in haystack for term in terms):
                filtered.append(row)
        rows = filtered
    rows = rows[:_MAX_PREVIEW_ROWS]
    highlights = [
        f"{row.get('role_name')} on {row.get('scope') or row.get('subscription_name')}"
        for row in rows[:5]
    ]
    if not highlights:
        highlights = ["No matching Azure role assignments were found."]
    citations = [
        AzureCitation(source_type="role_assignments", label="Azure role assignments", detail=f"{len(rows)} matching row(s)"),
    ]
    preview = [
        {
            "role_name": str(row.get("role_name") or ""),
            "scope": str(row.get("scope") or ""),
            "principal_type": str(row.get("principal_type") or ""),
            "principal_id": str(row.get("principal_id") or ""),
        }
        for row in rows
    ]
    return (
        _result(
            key="role_assignments",
            label="Azure role assignments",
            status="completed",
            query_summary=_source_query_summary(incident),
            item_count=len(rows),
            highlights=highlights,
            preview=preview,
            citations=citations,
        ),
        jobs,
    )


def _run_resources_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    terms = build_query_terms(incident)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for term in terms[:3] or [incident.summary]:
        payload = azure_cache.list_resources(search=term)
        for row in payload.get("resources") or []:
            resource_id = str(row.get("id") or "")
            if resource_id in seen:
                continue
            seen.add(resource_id)
            rows.append(row)
            if len(rows) >= _MAX_PREVIEW_ROWS:
                break
        if len(rows) >= _MAX_PREVIEW_ROWS:
            break
    highlights = [
        f"{row.get('name')} ({row.get('resource_type')}) in {row.get('resource_group')}"
        for row in rows[:5]
    ]
    if not highlights:
        highlights = ["No matching Azure resources were found."]
    citations = [
        AzureCitation(source_type="resources", label="Azure resources", detail=f"{len(rows)} matching resource(s)"),
    ]
    preview = [
        {
            "name": str(row.get("name") or ""),
            "resource_type": str(row.get("resource_type") or ""),
            "resource_group": str(row.get("resource_group") or ""),
            "subscription_name": str(row.get("subscription_name") or row.get("subscription_id") or ""),
            "state": str(row.get("state") or ""),
        }
        for row in rows
    ]
    return (
        _result(
            key="resources",
            label="Azure resources",
            status="completed",
            query_summary=_source_query_summary(incident),
            item_count=len(rows),
            highlights=highlights,
            preview=preview,
            citations=citations,
        ),
        jobs,
    )


def _run_vm_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    terms = build_query_terms(incident)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for term in terms[:3] or [incident.summary]:
        payload = azure_cache.list_virtual_machines(search=term)
        for row in payload.get("vms") or []:
            resource_id = str(row.get("id") or "")
            if resource_id in seen:
                continue
            seen.add(resource_id)
            rows.append(row)
            if len(rows) >= _MAX_PREVIEW_ROWS:
                break
        if len(rows) >= _MAX_PREVIEW_ROWS:
            break
    highlights = [
        f"{row.get('name')} ({row.get('power_state') or row.get('state') or 'unknown state'})"
        for row in rows[:5]
    ]
    if not highlights:
        highlights = ["No matching Azure VMs were found."]
    citations = [
        AzureCitation(source_type="vms", label="Azure virtual machines", detail=f"{len(rows)} matching VM(s)"),
    ]
    preview = [
        {
            "name": str(row.get("name") or ""),
            "resource_group": str(row.get("resource_group") or ""),
            "power_state": str(row.get("power_state") or row.get("state") or ""),
            "size": str(row.get("size") or row.get("vm_size") or ""),
        }
        for row in rows
    ]
    return (
        _result(
            key="vms",
            label="Azure virtual machines",
            status="completed",
            query_summary=_source_query_summary(incident),
            item_count=len(rows),
            highlights=highlights,
            preview=preview,
            citations=citations,
        ),
        jobs,
    )


def _run_virtual_desktops_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    terms = build_query_terms(incident)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for term in terms[:3] or [incident.summary]:
        payload = azure_cache.list_virtual_desktop_removal_candidates(search=term, removal_only=False)
        for row in payload.get("desktops") or []:
            desktop_id = str(row.get("id") or "")
            if desktop_id in seen:
                continue
            seen.add(desktop_id)
            rows.append(row)
            if len(rows) >= _MAX_PREVIEW_ROWS:
                break
        if len(rows) >= _MAX_PREVIEW_ROWS:
            break
    highlights = [
        f"{row.get('name')} ({row.get('resource_group') or row.get('host_pool_name') or 'desktop'})"
        for row in rows[:5]
    ]
    if not highlights:
        highlights = ["No matching virtual desktops were found."]
    citations = [
        AzureCitation(source_type="virtual_desktops", label="Azure virtual desktops", detail=f"{len(rows)} matching desktop(s)"),
    ]
    preview = [
        {
            "name": str(row.get("name") or ""),
            "resource_group": str(row.get("resource_group") or ""),
            "host_pool_name": str(row.get("host_pool_name") or ""),
            "state": str(row.get("state") or ""),
        }
        for row in rows
    ]
    return (
        _result(
            key="virtual_desktops",
            label="Azure virtual desktops",
            status="completed",
            query_summary=_source_query_summary(incident),
            item_count=len(rows),
            highlights=highlights,
            preview=preview,
            citations=citations,
        ),
        jobs,
    )


def _run_login_audit_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    targets = _unique_list([*incident.affected_users, *incident.affected_mailboxes])
    rows = list_login_audit(limit=200)
    if targets:
        rows = [
            row
            for row in rows
            if any(target.lower() in str(row.get("email") or "").lower() for target in targets)
        ]
    rows = rows[:_MAX_PREVIEW_ROWS]
    highlights = [
        f"{row.get('email')} via {row.get('auth_provider')} on {row.get('site_scope')}"
        for row in rows[:5]
    ]
    if not highlights:
        highlights = ["No matching application login audit rows were found."]
    citations = [
        AzureCitation(source_type="login_audit", label="App login audit", detail=f"{len(rows)} matching login row(s)"),
    ]
    preview = [
        {
            "email": str(row.get("email") or ""),
            "auth_provider": str(row.get("auth_provider") or ""),
            "site_scope": str(row.get("site_scope") or ""),
            "created_at": str(row.get("created_at") or ""),
        }
        for row in rows
    ]
    return (
        _result(
            key="login_audit",
            label="App login audit",
            status="completed",
            query_summary=_source_query_summary(incident),
            item_count=len(rows),
            highlights=highlights,
            preview=preview,
            citations=citations,
        ),
        jobs,
    )


def _mail_targets(incident: SecurityCopilotIncident) -> list[str]:
    return _unique_list([*incident.affected_mailboxes, *incident.affected_users])[:2]


def _run_mailbox_rules_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    targets = _mail_targets(incident)
    preview: list[dict[str, Any]] = []
    highlights: list[str] = []
    error_messages: list[str] = []
    rule_count = 0
    for target in targets:
        try:
            payload = user_admin_providers.list_mailbox_rules(target)
            count = int(payload.get("rule_count") or 0)
            rule_count += count
            preview.append(
                {
                    "mailbox": str(payload.get("mailbox") or target),
                    "rule_count": count,
                    "note": str(payload.get("note") or ""),
                }
            )
            if count > 0:
                highlights.append(f"{payload.get('mailbox')}: {count} inbox rule(s)")
            else:
                highlights.append(f"{payload.get('mailbox')}: {payload.get('note') or 'No inbox rules found.'}")
        except UserAdminProviderError as exc:
            error_messages.append(str(exc))
    status = "completed" if not error_messages else "error"
    reason = "; ".join(error_messages)
    if not highlights and reason:
        highlights = ["Mailbox rule lookup failed for the current target."]
    citations = [
        AzureCitation(source_type="mailbox_rules", label="Mailbox inbox rules", detail=f"{rule_count} rule(s) across {len(preview)} mailbox lookup(s)"),
    ]
    return (
        _result(
            key="mailbox_rules",
            label="Mailbox inbox rules",
            status=status,
            query_summary=_source_query_summary(incident),
            item_count=rule_count,
            highlights=highlights,
            preview=preview,
            citations=citations,
            reason=reason,
        ),
        jobs,
    )


def _run_mailbox_delegates_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    targets = _mail_targets(incident)
    preview: list[dict[str, Any]] = []
    highlights: list[str] = []
    error_messages: list[str] = []
    delegate_count = 0
    for target in targets:
        try:
            payload = user_admin_providers.list_mailbox_delegates(target)
            count = int(payload.get("delegate_count") or 0)
            delegate_count += count
            preview.append(
                {
                    "mailbox": str(payload.get("mailbox") or target),
                    "delegate_count": count,
                    "note": str(payload.get("note") or ""),
                }
            )
            if count > 0:
                highlights.append(f"{payload.get('mailbox')}: {count} delegate(s)")
            else:
                highlights.append(f"{payload.get('mailbox')}: {payload.get('note') or 'No mailbox delegates found.'}")
        except UserAdminProviderError as exc:
            error_messages.append(str(exc))
    status = "completed" if not error_messages else "error"
    reason = "; ".join(error_messages)
    if not highlights and reason:
        highlights = ["Mailbox delegate lookup failed for the current target."]
    citations = [
        AzureCitation(source_type="mailbox_delegates", label="Mailbox delegates", detail=f"{delegate_count} delegate(s) across {len(preview)} mailbox lookup(s)"),
    ]
    return (
        _result(
            key="mailbox_delegates",
            label="Mailbox delegates",
            status=status,
            query_summary=_source_query_summary(incident),
            item_count=delegate_count,
            highlights=highlights,
            preview=preview,
            citations=citations,
            reason=reason,
        ),
        jobs,
    )


def _run_delegate_mailboxes_live_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    targets = _unique_list([*incident.affected_users, *incident.affected_mailboxes])[:2]
    preview: list[dict[str, Any]] = []
    highlights: list[str] = []
    error_messages: list[str] = []
    mailbox_count = 0
    for target in targets:
        try:
            payload = user_admin_providers.list_delegate_mailboxes_for_user(target)
            count = int(payload.get("mailbox_count") or 0)
            mailbox_count += count
            preview.append(
                {
                    "user": str(payload.get("user") or target),
                    "mailbox_count": count,
                    "scanned_mailbox_count": int(payload.get("scanned_mailbox_count") or 0),
                    "note": str(payload.get("note") or ""),
                }
            )
            if count > 0:
                highlights.append(f"{payload.get('user')}: delegate access to {count} mailbox(es)")
            else:
                highlights.append(f"{payload.get('user')}: {payload.get('note') or 'No delegate mailbox access found.'}")
        except UserAdminProviderError as exc:
            error_messages.append(str(exc))
    status = "completed" if not error_messages else "error"
    reason = "; ".join(error_messages)
    if not highlights and reason:
        highlights = ["Direct delegate mailbox lookup failed for the current target."]
    citations = [
        AzureCitation(source_type="delegate_mailboxes", label="Delegate mailbox lookup", detail=f"{mailbox_count} mailbox match(es)"),
    ]
    return (
        _result(
            key="delegate_mailboxes_live",
            label="Delegate mailbox lookup",
            status=status,
            query_summary=_source_query_summary(incident),
            item_count=mailbox_count,
            highlights=highlights,
            preview=preview,
            citations=citations,
            reason=reason,
        ),
        jobs,
    )


def _needs_delegate_scan(incident: SecurityCopilotIncident) -> bool:
    return incident.lane in {"identity_compromise", "mailbox_abuse"} and bool(
        incident.affected_users or incident.affected_mailboxes
    )


def _sync_delegate_scan_jobs(
    incident: SecurityCopilotIncident,
    session: dict[str, Any],
    current_jobs: list[SecurityCopilotJobRef],
) -> tuple[list[SecurityCopilotJobRef], list[dict[str, Any]], list[str]]:
    if not _needs_delegate_scan(incident):
        return (current_jobs, [], [])

    targets = _unique_list([*incident.affected_users, *incident.affected_mailboxes])[:2]
    existing_by_target = {
        str(job.target or "").strip().lower(): job
        for job in current_jobs
        if job.job_type == "delegate_mailbox_scan"
    }
    refreshed_jobs: list[SecurityCopilotJobRef] = []
    completed_payloads: list[dict[str, Any]] = []
    errors: list[str] = []
    for target in targets:
        existing = existing_by_target.get(target.lower())
        payload = mailbox_delegate_scan_jobs.get_job(existing.job_id, include_events=True) if existing else None
        if payload is None:
            try:
                payload = mailbox_delegate_scan_jobs.create_job(
                    site_scope=get_current_site_scope(),
                    user=target,
                    requested_by_email=str(session.get("email") or ""),
                    requested_by_name=str(session.get("name") or ""),
                )
            except ValueError as exc:
                errors.append(str(exc))
                continue
        status = str(payload.get("status") or "queued")
        phase = str(payload.get("phase") or "")
        summary = (
            f"{payload.get('mailbox_count') or 0} mailbox match(es)"
            if status == "completed"
            else phase.replace("_", " ")
        )
        refreshed = SecurityCopilotJobRef(
            job_type="delegate_mailbox_scan",
            label="Delegate mailbox scan",
            job_id=str(payload.get("job_id") or ""),
            status=status,
            phase=phase,
            target=str(payload.get("user") or target),
            summary=_clip(summary, 140),
            started_automatically=True,
        )
        refreshed_jobs.append(refreshed)
        if status == "completed":
            completed_payloads.append(payload)
        elif status in {"failed", "cancelled"}:
            errors.append(str(payload.get("note") or f"Job {refreshed.job_id} {status}"))
    return refreshed_jobs, completed_payloads, errors


def _run_delegate_scan_source(
    incident: SecurityCopilotIncident,
    session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    refreshed_jobs, completed_payloads, errors = _sync_delegate_scan_jobs(incident, session, jobs)
    if not refreshed_jobs and errors:
        return (
            _result(
                key="delegate_mailbox_scan_job",
                label="Delegate mailbox scan job",
                status="error",
                query_summary=_source_query_summary(incident),
                highlights=["Could not start the delegate mailbox background scan."],
                reason="; ".join(errors),
            ),
            jobs,
        )

    running_jobs = [job for job in refreshed_jobs if job.status not in {"completed", "failed", "cancelled"}]
    preview = [
        {
            "job_id": job.job_id,
            "target": job.target,
            "status": job.status,
            "phase": job.phase,
            "summary": job.summary,
        }
        for job in refreshed_jobs
    ]

    if running_jobs:
        highlights = [
            f"{job.target}: {job.status} ({job.phase.replace('_', ' ') or job.summary})"
            for job in running_jobs
        ]
        if errors:
            highlights.extend(errors[:2])
        return (
            _result(
                key="delegate_mailbox_scan_job",
                label="Delegate mailbox scan job",
                status="running",
                query_summary=_source_query_summary(incident),
                item_count=len(refreshed_jobs),
                highlights=highlights,
                preview=preview,
                citations=[
                    AzureCitation(
                        source_type="delegate_mailbox_scan",
                        label="Delegate mailbox scan",
                        detail=f"{len(running_jobs)} running job(s)",
                    )
                ],
                reason="; ".join(errors),
            ),
            refreshed_jobs,
        )

    mailbox_count = sum(int(payload.get("mailbox_count") or 0) for payload in completed_payloads)
    highlights = [
        f"{payload.get('user')}: {int(payload.get('mailbox_count') or 0)} mailbox match(es)"
        for payload in completed_payloads
    ]
    if not highlights:
        highlights = ["Delegate mailbox scans finished without mailbox matches."]
    citations = [
        AzureCitation(
            source_type="delegate_mailbox_scan",
            label="Delegate mailbox scan",
            detail=f"{mailbox_count} mailbox match(es) from {len(completed_payloads)} completed job(s)",
        )
    ]
    if errors:
        highlights.extend(errors[:2])
    return (
        _result(
            key="delegate_mailbox_scan_job",
            label="Delegate mailbox scan job",
            status="completed" if not errors else "error",
            query_summary=_source_query_summary(incident),
            item_count=mailbox_count,
            highlights=highlights,
            preview=preview,
            citations=citations,
            reason="; ".join(errors),
        ),
        refreshed_jobs,
    )


def _run_kb_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    search_terms = build_query_terms(incident)
    articles = []
    if search_terms:
        for term in search_terms[:3]:
            articles.extend(kb_store.list_articles(search=term))
    else:
        articles = kb_store.list_articles(request_type="Security Alert")
    unique_articles: list[dict[str, Any]] = []
    seen: set[int] = set()
    for article in articles:
        if article.id is None or article.id in seen:
            continue
        seen.add(article.id)
        unique_articles.append(article.model_dump())
        if len(unique_articles) >= _MAX_PREVIEW_ROWS:
            break
    highlights = [
        f"{article.get('title')}: {article.get('summary') or article.get('request_type')}"
        for article in unique_articles[:5]
    ]
    if not highlights:
        highlights = ["No matching internal knowledge-base articles were found."]
    citations = [
        AzureCitation(source_type="knowledge_base", label="Knowledge base", detail=f"{len(unique_articles)} matching article(s)"),
    ]
    preview = [
        {
            "id": article.get("id"),
            "title": str(article.get("title") or ""),
            "request_type": str(article.get("request_type") or ""),
            "summary": _clip(article.get("summary") or "", 140),
        }
        for article in unique_articles
    ]
    return (
        _result(
            key="knowledge_base",
            label="Internal knowledge base",
            status="completed",
            query_summary=_source_query_summary(incident),
            item_count=len(unique_articles),
            highlights=highlights,
            preview=preview,
            citations=citations,
        ),
        jobs,
    )


def _ticket_haystack(issue: dict[str, Any]) -> str:
    fields = issue.get("fields") or {}
    return " ".join(
        [
            str(issue.get("key") or ""),
            str(fields.get("summary") or ""),
            extract_request_type_name_from_fields(fields),
            " ".join(str(label or "") for label in (fields.get("labels") or [])),
            extract_adf_text(fields.get("description")),
        ]
    ).lower()


def _run_ticket_search_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    terms = build_query_terms(incident)
    issues = cache.get_all_issues()
    matched: list[dict[str, Any]] = []
    for issue in issues:
        haystack = _ticket_haystack(issue)
        request_type = extract_request_type_name_from_fields(issue.get("fields") or {})
        if terms:
            if not any(term.lower() in haystack for term in terms):
                if incident.lane == "unknown":
                    continue
        elif incident.lane != "unknown" and request_type != "Security Alert":
            continue
        matched.append(issue)
        if len(matched) >= _MAX_PREVIEW_ROWS:
            break
    highlights = [
        f"{issue.get('key')}: {(issue.get('fields') or {}).get('summary') or ''}"
        for issue in matched[:5]
    ]
    if not highlights:
        highlights = ["No matching local tickets were found in the issue cache."]
    citations = [
        AzureCitation(source_type="tickets", label="Local ticket cache", detail=f"{len(matched)} matching ticket(s)"),
    ]
    preview = [
        {
            "key": str(issue.get("key") or ""),
            "summary": str((issue.get("fields") or {}).get("summary") or ""),
            "status": str((((issue.get("fields") or {}).get("status") or {}).get("name") or "")),
            "request_type": extract_request_type_name_from_fields(issue.get("fields") or {}),
        }
        for issue in matched
    ]
    return (
        _result(
            key="ticket_search",
            label="Local ticket cache",
            status="completed",
            query_summary=_source_query_summary(incident),
            item_count=len(matched),
            highlights=highlights,
            preview=preview,
            citations=citations,
        ),
        jobs,
    )


def _resolve_user_identifier(identifier: str) -> str:
    candidates = azure_cache.list_directory_objects("users", search=identifier)
    identifier_lower = identifier.strip().lower()
    for candidate in candidates:
        if identifier_lower in {
            str(candidate.get("id") or "").strip().lower(),
            str(candidate.get("principal_name") or "").strip().lower(),
            str(candidate.get("mail") or "").strip().lower(),
        }:
            return str(candidate.get("id") or candidate.get("principal_name") or identifier)
    if candidates:
        first = candidates[0]
        return str(first.get("id") or first.get("principal_name") or identifier)
    return identifier


def _run_user_admin_source(
    incident: SecurityCopilotIncident,
    _session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[SecurityCopilotSourceResult, list[SecurityCopilotJobRef]]:
    targets = _unique_list([*incident.affected_users, *incident.affected_mailboxes])[:2]
    highlights: list[str] = []
    preview: list[dict[str, Any]] = []
    errors: list[str] = []
    for target in targets:
        user_id = _resolve_user_identifier(target)
        try:
            detail = user_admin_providers.get_user_detail(user_id)
            mailbox = user_admin_providers.get_mailbox(user_id)
            roles = user_admin_providers.list_roles(user_id)
            groups = user_admin_providers.list_groups(user_id)
            devices = user_admin_providers.list_devices(user_id)
            audit = user_admin_jobs.list_audit(limit=20, target_user_id=user_id)
            preview.append(
                {
                    "user": str(detail.get("principal_name") or detail.get("mail") or target),
                    "enabled": detail.get("enabled"),
                    "license_count": int(detail.get("license_count") or 0),
                    "role_count": len(roles),
                    "group_count": len(groups),
                    "device_count": len(devices),
                    "audit_events": len(audit),
                    "forwarding_enabled": bool(mailbox.get("forwarding_enabled")),
                }
            )
            highlight = (
                f"{detail.get('principal_name') or target}: "
                f"{len(roles)} role(s), {len(groups)} group(s), {len(devices)} device(s)"
            )
            if mailbox.get("forwarding_enabled"):
                highlight += f"; forwarding to {mailbox.get('forwarding_address') or 'configured target'}"
            highlights.append(highlight)
        except UserAdminProviderError as exc:
            errors.append(str(exc))
    if not highlights and errors:
        highlights = ["User admin detail lookup failed for the current target."]
    citations = [
        AzureCitation(source_type="user_admin", label="User admin", detail=f"{len(preview)} enriched user profile(s)"),
    ]
    status = "completed" if not errors else "error"
    return (
        _result(
            key="user_admin",
            label="User admin detail",
            status=status,
            query_summary=_source_query_summary(incident),
            item_count=len(preview),
            highlights=highlights,
            preview=preview,
            citations=citations,
            reason="; ".join(errors),
        ),
        jobs,
    )


def _build_source_registry() -> list[SecuritySourceDefinition]:
    return [
        SecuritySourceDefinition(
            key="tenant_status",
            label="Azure tenant status",
            permission="authenticated",
            applies=lambda incident: True,
            query_summary=_tenant_status_query_summary,
            runner=_run_tenant_status_source,
        ),
        SecuritySourceDefinition(
            key="alert_history",
            label="Azure alert history",
            permission="authenticated",
            applies=lambda incident: incident.lane in {"azure_alert_or_resource", "identity_compromise", "unknown"} or bool(incident.alert_names),
            query_summary=_source_query_summary,
            runner=_run_alert_history_source,
        ),
        SecuritySourceDefinition(
            key="quick_search",
            label="Azure quick search",
            permission="authenticated",
            applies=lambda incident: bool(build_query_terms(incident)),
            query_summary=_source_query_summary,
            runner=_run_quick_search_source,
        ),
        SecuritySourceDefinition(
            key="directory",
            label="Azure directory objects",
            permission="authenticated",
            applies=lambda incident: incident.lane in {"identity_compromise", "app_or_service_principal", "unknown"} or bool(_directory_search_terms(incident)),
            query_summary=_source_query_summary,
            runner=_run_directory_source,
        ),
        SecuritySourceDefinition(
            key="role_assignments",
            label="Azure role assignments",
            permission="authenticated",
            applies=lambda incident: incident.lane in {"app_or_service_principal", "azure_alert_or_resource"} or bool(incident.affected_apps or incident.affected_resources),
            query_summary=_source_query_summary,
            runner=_run_role_assignments_source,
        ),
        SecuritySourceDefinition(
            key="resources",
            label="Azure resources",
            permission="authenticated",
            applies=lambda incident: incident.lane == "azure_alert_or_resource" or bool(incident.affected_resources),
            query_summary=_source_query_summary,
            runner=_run_resources_source,
        ),
        SecuritySourceDefinition(
            key="vms",
            label="Azure virtual machines",
            permission="authenticated",
            applies=lambda incident: incident.lane == "azure_alert_or_resource" or any("vm" in term.lower() for term in build_query_terms(incident)),
            query_summary=_source_query_summary,
            runner=_run_vm_source,
        ),
        SecuritySourceDefinition(
            key="virtual_desktops",
            label="Azure virtual desktops",
            permission="authenticated",
            applies=lambda incident: any(term.lower() in {"avd", "wvd"} or "desktop" in term.lower() for term in build_query_terms(incident)),
            query_summary=_source_query_summary,
            runner=_run_virtual_desktops_source,
        ),
        SecuritySourceDefinition(
            key="login_audit",
            label="App login audit",
            permission="authenticated",
            applies=lambda incident: incident.lane in {"identity_compromise", "mailbox_abuse"} or bool(incident.affected_users or incident.affected_mailboxes),
            query_summary=_source_query_summary,
            runner=_run_login_audit_source,
        ),
        SecuritySourceDefinition(
            key="mailbox_rules",
            label="Mailbox inbox rules",
            permission="authenticated",
            applies=lambda incident: incident.lane == "mailbox_abuse" or bool(incident.affected_mailboxes),
            query_summary=_source_query_summary,
            runner=_run_mailbox_rules_source,
        ),
        SecuritySourceDefinition(
            key="mailbox_delegates",
            label="Mailbox delegates",
            permission="authenticated",
            applies=lambda incident: incident.lane == "mailbox_abuse" or bool(incident.affected_mailboxes),
            query_summary=_source_query_summary,
            runner=_run_mailbox_delegates_source,
        ),
        SecuritySourceDefinition(
            key="delegate_mailboxes_live",
            label="Delegate mailbox lookup",
            permission="authenticated",
            applies=lambda incident: incident.lane in {"identity_compromise", "mailbox_abuse"} and bool(incident.affected_users or incident.affected_mailboxes),
            query_summary=_source_query_summary,
            runner=_run_delegate_mailboxes_live_source,
        ),
        SecuritySourceDefinition(
            key="delegate_mailbox_scan_job",
            label="Delegate mailbox scan job",
            permission="authenticated",
            applies=_needs_delegate_scan,
            query_summary=_source_query_summary,
            runner=_run_delegate_scan_source,
        ),
        SecuritySourceDefinition(
            key="knowledge_base",
            label="Internal knowledge base",
            permission="authenticated",
            applies=lambda incident: True,
            query_summary=_source_query_summary,
            runner=_run_kb_source,
        ),
        SecuritySourceDefinition(
            key="ticket_search",
            label="Local ticket cache",
            permission="authenticated",
            applies=lambda incident: True,
            query_summary=_source_query_summary,
            runner=_run_ticket_search_source,
        ),
        SecuritySourceDefinition(
            key="user_admin",
            label="User admin detail",
            permission="manage_users",
            applies=lambda incident: bool(incident.affected_users or incident.affected_mailboxes),
            query_summary=_source_query_summary,
            runner=_run_user_admin_source,
        ),
    ]


def plan_security_sources(
    incident: SecurityCopilotIncident,
    session: dict[str, Any],
) -> list[SecurityCopilotPlannedSource]:
    can_manage_users = session_can_manage_users(session)
    planned: list[SecurityCopilotPlannedSource] = []
    for source in _build_source_registry():
        if not source.applies(incident):
            continue
        reason = ""
        status = "planned"
        if source.permission == "manage_users" and not can_manage_users:
            status = "skipped"
            reason = "Current session does not have user-admin access."
        planned.append(
            SecurityCopilotPlannedSource(
                key=source.key,
                label=source.label,
                status=status,
                query_summary=source.query_summary(incident),
                reason=reason,
            )
        )
    return planned


def _execute_sources(
    incident: SecurityCopilotIncident,
    session: dict[str, Any],
    jobs: list[SecurityCopilotJobRef],
) -> tuple[list[SecurityCopilotSourceResult], list[SecurityCopilotJobRef]]:
    can_manage_users = session_can_manage_users(session)
    results: list[SecurityCopilotSourceResult] = []
    current_jobs = jobs
    for source in _build_source_registry():
        if not source.applies(incident):
            continue
        if source.permission == "manage_users" and not can_manage_users:
            results.append(
                _result(
                    key=source.key,
                    label=source.label,
                    status="skipped",
                    query_summary=source.query_summary(incident),
                    highlights=["Skipped because this session does not have user-admin access."],
                    reason="Current session does not have user-admin access.",
                )
            )
            continue
        try:
            result, current_jobs = source.runner(incident, session, current_jobs)
            results.append(result)
        except Exception as exc:
            logger.exception("Security copilot source %s failed", source.key)
            results.append(
                _result(
                    key=source.key,
                    label=source.label,
                    status="error",
                    query_summary=source.query_summary(incident),
                    highlights=[f"{source.label} failed during investigation."],
                    reason=str(exc),
                )
            )
    return results, current_jobs


def _collect_citations(results: list[SecurityCopilotSourceResult]) -> list[AzureCitation]:
    citations: list[AzureCitation] = []
    seen: set[tuple[str, str, str]] = set()
    for result in results:
        for citation in result.citations:
            key = (citation.source_type, citation.label, citation.detail)
            if key in seen:
                continue
            seen.add(key)
            citations.append(citation)
    return citations[:20]


def _fallback_answer(
    incident: SecurityCopilotIncident,
    results: list[SecurityCopilotSourceResult],
    phase: str,
) -> SecurityCopilotAnswer:
    completed = [result for result in results if result.status == "completed"]
    finding_lines = [
        highlight
        for result in completed
        for highlight in result.highlights[:2]
        if highlight and "No matching" not in highlight
    ]
    warnings = [
        result.reason
        for result in results
        if result.status in {"skipped", "error"} and result.reason
    ]
    stale_results = [
        result.label
        for result in results
        if "stale" in result.reason.lower() or "older than 4 hours" in result.reason.lower()
    ]
    if stale_results:
        warnings.append(
            f"Stale source data may limit confidence: {', '.join(stale_results[:3])}."
        )
    if phase == "running_jobs":
        warnings.append("Background mailbox delegate scans are still running.")
    summary = (
        f"Investigated {_lane_label(incident.lane)} across {len(results)} source group(s)."
        if results
        else f"Investigated {_lane_label(incident.lane)}."
    )
    if not finding_lines:
        finding_lines = ["No high-confidence findings were returned from the currently available sources."]
    next_steps = []
    if incident.lane in {"identity_compromise", "mailbox_abuse"}:
        next_steps.append("Review mailbox rules, delegation, and recent identity events for the affected account.")
    if incident.lane == "app_or_service_principal":
        next_steps.append("Review app ownership, role assignments, and recent consent or credential changes.")
    if incident.lane == "azure_alert_or_resource":
        next_steps.append("Confirm the affected Azure resource state and correlate with recent alert history.")
    return SecurityCopilotAnswer(
        summary=summary,
        findings=finding_lines[:5],
        next_steps=next_steps[:4],
        warnings=_unique_list(warnings)[:4],
    )


def _synthesize_answer(
    incident: SecurityCopilotIncident,
    results: list[SecurityCopilotSourceResult],
    model_id: str,
    *,
    phase: str,
) -> SecurityCopilotAnswer:
    compact_results = [
        {
            "key": result.key,
            "label": result.label,
            "status": result.status,
            "item_count": result.item_count,
            "highlights": result.highlights[:5],
            "reason": result.reason,
            "preview": result.preview[:4],
        }
        for result in results
    ]
    user_msg = json.dumps(
        {
            "incident": incident.model_dump(),
            "phase": phase,
            "source_results": compact_results,
        },
        separators=(",", ":"),
        default=str,
    )
    try:
        raw = invoke_model_text(
            model_id,
            _ANSWER_PROMPT,
            user_msg,
            feature_surface="azure_security_copilot",
            app_surface="azure_portal",
            actor_type="user",
            actor_id="azure-security-copilot",
            max_output_tokens=1200,
            json_output=True,
            metadata={"stage": "answer", "phase": phase, "source_count": len(results)},
        )
        parsed = _extract_json_object(raw)
        return SecurityCopilotAnswer.model_validate(parsed)
    except Exception:
        logger.exception("Security copilot answer synthesis failed")
        return _fallback_answer(incident, results, phase)


def run_security_copilot_chat(
    request: SecurityCopilotChatRequest,
    session: dict[str, Any],
    *,
    model_id: str,
) -> SecurityCopilotChatResponse:
    incident = request.incident.model_copy(deep=True)
    message = str(request.message or "").strip()
    if message or not incident.summary:
        incident = _resolve_incident_profile(message, incident, model_id, history=request.history)
    else:
        incident.missing_fields = _missing_fields_for_incident(incident)

    planned_sources = plan_security_sources(incident, session)
    follow_up_questions = _build_follow_up_questions(incident)
    if incident.missing_fields:
        return SecurityCopilotChatResponse(
            phase="needs_input",
            assistant_message=_assistant_message_for_intake(incident),
            incident=incident,
            follow_up_questions=follow_up_questions,
            planned_sources=planned_sources,
            source_results=[],
            jobs=request.jobs,
            answer=SecurityCopilotAnswer(),
            citations=[],
            model_used=model_id,
            generated_at=_utc_now(),
        )

    source_results, jobs = _execute_sources(incident, session, request.jobs)
    planned_by_key = {item.key: item for item in planned_sources}
    for result in source_results:
        if result.key in planned_by_key:
            planned_by_key[result.key].status = result.status  # type: ignore[assignment]
            if result.reason:
                planned_by_key[result.key].reason = result.reason
    planned_sources = list(planned_by_key.values())

    jobs_running = any(job.status not in {"completed", "failed", "cancelled"} for job in jobs)
    citations = _collect_citations(source_results)

    if jobs_running:
        completed_count = len([result for result in source_results if result.status == "completed"])
        assistant_message = (
            f"I queried {completed_count} source group(s) and started {len(jobs)} background mailbox scan job(s). "
            "Partial results are ready now, and I will finalize the investigation when those jobs finish."
        )
        return SecurityCopilotChatResponse(
            phase="running_jobs",
            assistant_message=assistant_message,
            incident=incident,
            follow_up_questions=[],
            planned_sources=planned_sources,
            source_results=source_results,
            jobs=jobs,
            answer=SecurityCopilotAnswer(),
            citations=citations,
            model_used=model_id,
            generated_at=_utc_now(),
        )

    answer = _synthesize_answer(incident, source_results, model_id, phase="complete")
    assistant_message = answer.summary or "Investigation complete."
    return SecurityCopilotChatResponse(
        phase="complete",
        assistant_message=assistant_message,
        incident=incident,
        follow_up_questions=[],
        planned_sources=planned_sources,
        source_results=source_results,
        jobs=jobs,
        answer=answer,
        citations=citations,
        model_used=model_id,
        generated_at=_utc_now(),
    )
