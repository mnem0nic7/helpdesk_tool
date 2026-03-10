"""AI provider abstraction for ticket triage analysis."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from config import OPENAI_API_KEY, ANTHROPIC_API_KEY
from models import (
    AIModel,
    KnowledgeBaseArticle,
    KnowledgeBaseDraft,
    TechnicianScore,
    TriageResult,
    TriageSuggestion,
)
from request_type import extract_request_type_name_from_fields

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

_SECURITY_ALERT_REQUEST_TYPE = "Security Alert"
_SECURITY_PRIORITY_REASONING = "Security Alert tickets must be triaged at High priority."
_HIGH_ENOUGH_SECURITY_PRIORITIES = {"High", "Highest"}

SYSTEM_PROMPT = """You are an IT helpdesk triage assistant for a Jira Service Management project (OIT).
Your job is to analyze tickets and suggest improvements for: priority, request_type, status, assignee, and an optional comment.

## General Rules
- Only suggest changes where you see a clear improvement. If a field looks correct, omit it — EXCEPT for request_type which you MUST always suggest.
- Priority must be one of: {priorities}
- Status must be one of: {statuses}
- For assignee, suggest a name only if you can identify the right person from context. Otherwise omit.
- For comments, suggest a brief triage note only if it would help the agent handling the ticket.
- Relevant internal knowledge base articles may be included. Use them as context for classification and handling notes, but do not assume facts not present in the ticket or KB excerpts.
- Provide a confidence score (0.0-1.0) and brief reasoning for each suggestion.

## Request Type Classification Rules
You MUST ALWAYS suggest a request_type. Classify every ticket into exactly one of the categories below.
Do NOT use any request type not in this list: {request_types}

**Classification procedure:**
1. Scan the ticket Summary, Description, and Comments against the keyword lists below.
2. Categories are in PRIORITY ORDER. When a ticket matches multiple categories, assign it to whichever appears FIRST in this list.
   Example: a ticket mentioning both "phishing" and "email" → Security Alert (not Email or Outlook).
3. Keyword matching is case-insensitive. Match partial words where indicated (e.g., "authenticat" matches "authentication", "authenticator").
4. If no keywords match and the ticket does not clearly fit any category, assign "Get IT help".

### 1. Security Alert (HIGHEST PRIORITY)
Automated security notifications, threat reports, phishing, and security incidents.
Keywords: threat has been reported, unknown email in phisher, red canary, potentially malicious url, phish, quarantine, spam, junk mail, suspicious email, malware, ransomware, virus, trojan, compromised, breach, security incident, unauthorized access, threat published

### 2. Onboard new employees
Set up new user accounts, provision access for new hires, contractors, or interns.
Keywords: new account for, new hire, new employee, onboard, onboarding, new contractor activation, activation -, activation:, activation-, new user, new account

### 3. Offboard employees
Disable accounts, revoke access for departing employees or terminated staff.
Keywords: offboard, offboarding, termination, deactivation, employee deactivation, disable account, remove access, deactivate user, deactivation request

### 4. Password MFA Authentication
Passwords, multi-factor auth, login failures, lockouts, SSO, credential resets.
Keywords: password, credential, mfa, multi-factor, 2fa, authenticat (partial), locked out, lockout, unable to login, can't login, cant log, login issue, sign in, sign-in, sso, reset password, unlock account, password reset, password expired

### 5. VPN
VPN connectivity, FortiClient, remote access issues.
Keywords: vpn, forticlient, remote access, remote into, remote desktop, remote connect, vpn issues, vpn not connecting

### 6. Virtual Desktop
Windows Virtual Desktop (WVD), Azure Virtual Desktop (AVD), Citrix, virtual desktop environments.
Keywords: wvd, avd, virtual desktop, citrix, virtual machine desktop

### 7. Email or Outlook
Email delivery, Outlook client, shared mailboxes, distribution lists, calendar issues, aliases, auto-replies.
Keywords: email, e-mail, outlook, mailbox, inbox, alias, distribution list, autoreply, auto reply, shared mailbox, calendar invite, calendar issue, exchange, email chain, email access

### 8. Phone RingCentral
RingCentral phone system, caller ID, voicemail, phone lines, extensions.
Keywords: ring central, ringcentral, caller id, phone system, voicemail, phone line, phone number, extension, incontact

### 9. Report a computer equipment problem
Hardware failures, peripherals (monitors, keyboards, mice, docking stations), laptops, printers, equipment replacement.
Keywords: laptop, monitor, mouse, keyboard, printer, headset, dock, docking station, charge, charging, equipment, hardware, pc setup, pc replacement, hinge, screen, broken, not charging, usb, webcam, camera, extended screen

### 10. Server Infrastructure Database
Servers, Azure cloud, SSL certificates, DNS, firewalls, database admin, SQL Server, patching, port changes.
Keywords: server, azure, infrastructure, certificate, ssl, patching, sql, dba request, database, db (word boundary), port change, dns, firewall, site recovery, sql server, db write access
Note: "db " (with trailing space/boundary) to avoid false positives.

### 11. Backup and Storage
Disk space, storage allocation, backup jobs, drive access, low memory warnings.
Keywords: disk, storage, backup, space, virtual memory, drive, low memory, insufficient disk, disk space, c disk, l & w drive

### 12. Request new PC software
Install software, upgrade applications, obtain licenses, local admin rights for installation.
Keywords: install, software install, adobe, license, local admin, out of date, new software, software request, software access

### 13. Business Application Support
Specific business apps: MoveDocs, Concur, ADP, CIMI, Libra, C3, MedPort, MDM, Salesforce, Power BI, Teams, SharePoint, OneDrive, Bitbucket, GRS.
Keywords: movedocs, concur, adp, cimi, libra, c3, medport, mdm, salesforce, sales force, powerbi, power bi, bit bucket, bitbucket, grs, teams, microsoft teams, sharepoint, onedrive, one drive

### 14. Get IT help (DEFAULT — lowest priority)
General IT issues, PC performance, OS problems, sound/audio, file access, and anything that doesn't match above.
Keywords: slow, freeze, crash, blue screen, reboot, restart, performance, windows 10, windows 11, can't open, cant open, unable to save, unable to open, not working, issue, problem, error, help, sound, audio, speaker, microphone
Assign this category when no other category clearly matches.

## Response Format
Respond with ONLY valid JSON (no markdown fences):
{{
  "suggestions": [
    {{
      "field": "priority",
      "suggested_value": "High",
      "reasoning": "Customer reports complete service outage",
      "confidence": 0.85
    }},
    {{
      "field": "request_type",
      "suggested_value": "Security Alert",
      "reasoning": "Subject mentions phishing report from PhishER",
      "confidence": 0.95
    }}
  ]
}}

If no changes are needed (except request_type which is always required), return only the request_type suggestion.
"""

KB_REFORMAT_PROMPT = """You are reformatting an IT knowledge base article for better readability.

Restructure the content using clean markdown:
- ## for section headings (e.g. ## Description, ## Steps, ## Notes, ## Additional Information)
- ### for sub-headings
- Numbered lists for step-by-step procedures: 1. First step\n2. Second step (grouped, not separated by blank lines)
- - for unordered bullet lists
- Start callout paragraphs with one of: Note:, Warning:, Tip:, Caution:, or Important:
- **bold** for key terms or UI element names

Preserve all technical content exactly — do not add, remove, or alter any technical information.
Return ONLY the reformatted content. No preamble, no explanation, no markdown fences."""


KB_DRAFT_PROMPT = """You are maintaining the internal OIT helpdesk knowledge base.
Use the closed ticket evidence and any existing related KB article to draft either:
- an update to the existing article, or
- a new article when no existing article covers the resolution well.

Rules:
- Use only information supported by the ticket description, comments, and notes.
- Remove customer-specific details, names, email addresses, and one-off context unless it is operationally necessary.
- Focus on reusable troubleshooting and resolution guidance for technicians.
- Prefer concise section headings and action-oriented steps.
- If an existing article is provided, preserve its general scope and improve it with the new resolution details.

Respond with ONLY valid JSON:
{
  "title": "Article title",
  "request_type": "One request type name or empty string",
  "summary": "One or two sentence overview.",
  "content": "Full article body in plain text with section headings and paragraph breaks.",
  "recommended_action": "update_existing",
  "change_summary": "What this draft adds or changes."
}
"""

TECHNICIAN_SCORE_PROMPT = """You are a QA reviewer for closed IT helpdesk tickets.
Evaluate the technician's handling of a resolved or closed ticket using only the evidence provided.

Score these dimensions from 1 to 5:
- communication_score: how clearly and professionally the technician communicated with the end user
- documentation_score: how well the technician documented what they did, what fixed the issue, and any follow-up context

Scoring guidance:
- 5 = excellent, complete, clear, and customer-friendly
- 4 = strong with minor gaps
- 3 = adequate but missing useful detail
- 2 = weak, sparse, or unclear
- 1 = little to no evidence

Rules:
- Customer-facing communication should be judged mainly from public comments/replies.
- Documentation should be judged from internal notes, public replies, and the final resolution context together.
- If there are no public replies, communication_score should usually be 1 or 2.
- If the notes do not explain what was done to resolve the ticket, documentation_score should usually be 1 or 2.
- Be strict about evidence. Do not assume work happened if it is not documented.

Respond with ONLY valid JSON:
{
  "communication_score": 3,
  "communication_notes": "Short explanation of the communication quality.",
  "documentation_score": 4,
  "documentation_notes": "Short explanation of the documentation quality.",
  "score_summary": "One-sentence overall assessment."
}
"""


def _build_ticket_context(
    issue: dict[str, Any],
    kb_matches: list[KnowledgeBaseArticle] | None = None,
) -> str:
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
    request_type = extract_request_type_name_from_fields(fields)

    # Reporter
    reporter_obj = fields.get("reporter") or {}
    reporter = (
        reporter_obj.get("displayName", "Unknown")
        if isinstance(reporter_obj, dict)
        else "Unknown"
    )

    # Dates
    created = fields.get("created", "")
    updated = fields.get("updated", "")
    resolved = fields.get("resolutiondate") or ""

    # Labels
    labels = fields.get("labels") or []

    # Components
    components = [
        c.get("name", "") for c in (fields.get("components") or [])
        if isinstance(c, dict)
    ]

    # Organizations
    orgs_raw = fields.get("customfield_10700") or []
    organizations = [
        o.get("name", "") for o in orgs_raw if isinstance(o, dict)
    ]

    # Comments (all)
    comment_data = fields.get("comment") or {}
    comments = comment_data.get("comments", []) if isinstance(comment_data, dict) else []
    comment_texts: list[str] = []
    for c in comments:
        author = (c.get("author") or {}).get("displayName", "Unknown")
        date = (c.get("created") or "")[:19].replace("T", " ")
        body = extract_adf_text(c.get("body"))
        if body:
            comment_texts.append(f"  [{author} | {date}]: {body}")

    # Steps to re-create (customfield_11121)
    steps = extract_adf_text(fields.get("customfield_11121"))

    # Work category
    work_category = fields.get("customfield_11239") or ""

    lines = [
        f"Ticket: {key}",
        f"Type: {issue_type}",
        f"Request Type: {request_type or 'Not set'}",
        f"Summary: {summary}",
        f"Status: {status}",
        f"Priority: {priority}",
        f"Reporter: {reporter}",
        f"Assignee: {assignee}",
        f"Labels: {', '.join(labels) if labels else 'None'}",
        f"Components: {', '.join(components) if components else 'None'}",
        f"Organizations: {', '.join(organizations) if organizations else 'None'}",
        f"Work Category: {work_category or 'Not set'}",
        f"Created: {created}",
        f"Updated: {updated}",
        *([ f"Resolved: {resolved}" ] if resolved else []),
    ]
    if description:
        lines.append(f"Description:\n{description}")
    if steps:
        lines.append(f"Steps to Re-Create:\n{steps}")
    if comment_texts:
        lines.append(f"Comments ({len(comments)} total):\n" + "\n".join(comment_texts))
    if kb_matches:
        kb_lines = []
        for article in kb_matches:
            excerpt = article.content[:1200].strip()
            kb_lines.append(
                f"- {article.title} ({article.request_type or 'General'}): {article.summary or 'No summary'}\n"
                f"{excerpt}"
            )
        lines.append("Relevant Knowledge Base Articles:\n" + "\n\n".join(kb_lines))

    return "\n".join(lines)


def _extract_comment_body(comment: dict[str, Any]) -> str:
    body = comment.get("body")
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        return extract_adf_text(body)
    return ""


def _build_technician_score_context(
    issue: dict[str, Any],
    request_comments: list[dict[str, Any]],
) -> str:
    """Build a closed-ticket QA context focused on technician communication."""
    fields = issue.get("fields", {})
    key = issue.get("key", "")
    summary = fields.get("summary", "")
    description = extract_adf_text(fields.get("description"))
    steps = extract_adf_text(fields.get("customfield_11121"))
    status_obj = fields.get("status") or {}
    status = status_obj.get("name", "Unknown")
    resolution = ((fields.get("resolution") or {}).get("name") or "")
    resolved = fields.get("resolutiondate") or ""
    assignee_obj = fields.get("assignee") or {}
    assignee = (
        assignee_obj.get("displayName", "Unassigned")
        if isinstance(assignee_obj, dict)
        else "Unassigned"
    )
    request_type = extract_request_type_name_from_fields(fields)

    public_comments: list[str] = []
    internal_comments: list[str] = []
    for comment in request_comments:
        author = ((comment.get("author") or {}).get("displayName") or "Unknown")
        created = str(comment.get("created") or "")[:19].replace("T", " ")
        body = _extract_comment_body(comment)
        if not body:
            continue
        line = f"[{author} | {created}]: {body}"
        if comment.get("public"):
            public_comments.append(line)
        else:
            internal_comments.append(line)

    raw_comments = []
    comment_obj = fields.get("comment") or {}
    if isinstance(comment_obj, dict):
        for comment in comment_obj.get("comments", []) or []:
            author = ((comment.get("author") or {}).get("displayName") or "Unknown")
            created = str(comment.get("created") or "")[:19].replace("T", " ")
            body = _extract_comment_body(comment)
            if body:
                raw_comments.append(f"[{author} | {created}]: {body}")

    lines = [
        f"Ticket: {key}",
        f"Summary: {summary}",
        f"Request Type: {request_type or 'Not set'}",
        f"Status: {status}",
        f"Resolution: {resolution or 'Not set'}",
        f"Resolved: {resolved or 'Not set'}",
        f"Assignee: {assignee}",
    ]
    if description:
        lines.append(f"Description:\n{description}")
    if steps:
        lines.append(f"Steps to Re-Create:\n{steps}")
    lines.append(
        "Customer-Facing Comments:\n"
        + ("\n".join(public_comments) if public_comments else "None")
    )
    lines.append(
        "Internal Notes:\n"
        + ("\n".join(internal_comments) if internal_comments else "None")
    )
    if raw_comments:
        lines.append("All Jira Comments:\n" + "\n".join(raw_comments))
    return "\n".join(lines)


def _build_kb_draft_context(
    issue: dict[str, Any],
    request_comments: list[dict[str, Any]],
    existing_article: KnowledgeBaseArticle | None,
) -> str:
    """Build the context for an AI-generated KB draft."""
    ticket_context = _build_technician_score_context(issue, request_comments)
    if not existing_article:
        return ticket_context + "\n\nExisting KB Article:\nNone"
    return (
        ticket_context
        + "\n\nExisting KB Article:\n"
        + f"Title: {existing_article.title}\n"
        + f"Request Type: {existing_article.request_type or 'Not set'}\n"
        + f"Summary: {existing_article.summary or 'None'}\n"
        + f"Content:\n{existing_article.content}"
    )


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

    # Extract current request type name
    current_rt = extract_request_type_name_from_fields(fields_data)

    current_values = {
        "priority": (fields_data.get("priority") or {}).get("name", ""),
        "request_type": current_rt,
        "status": (fields_data.get("status") or {}).get("name", ""),
        "assignee": (
            (fields_data.get("assignee") or {}).get("displayName", "Unassigned")
            if isinstance(fields_data.get("assignee"), dict)
            else "Unassigned"
        ),
        "comment": "",
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


def _enforce_security_priority(issue: dict[str, Any], suggestions: list[TriageSuggestion]) -> list[TriageSuggestion]:
    """Force security-classified tickets to carry a High priority suggestion.

    The AI prompt already asks for this behavior, but auto-triage needs a
    deterministic server-side rule so Security Alert tickets are never left at
    low priority due to model drift or omissions.
    """
    if not suggestions:
        return suggestions

    fields = issue.get("fields", {})
    current_request_type = extract_request_type_name_from_fields(fields)
    request_type_suggestion = next(
        (s for s in suggestions if s.field == "request_type"),
        None,
    )

    if request_type_suggestion is not None:
        is_security_ticket = request_type_suggestion.suggested_value == _SECURITY_ALERT_REQUEST_TYPE
    else:
        is_security_ticket = current_request_type == _SECURITY_ALERT_REQUEST_TYPE

    if not is_security_ticket:
        return suggestions

    current_priority = (fields.get("priority") or {}).get("name", "")
    if current_priority in _HIGH_ENOUGH_SECURITY_PRIORITIES:
        return [s for s in suggestions if s.field != "priority"]

    normalized: list[TriageSuggestion] = []
    priority_replaced = False
    for suggestion in suggestions:
        if suggestion.field != "priority":
            normalized.append(suggestion)
            continue
        if not priority_replaced:
            normalized.append(
                TriageSuggestion(
                    field="priority",
                    current_value=suggestion.current_value or current_priority,
                    suggested_value="High",
                    reasoning=_SECURITY_PRIORITY_REASONING,
                    confidence=max(suggestion.confidence, 0.99),
                )
            )
            priority_replaced = True

    if not priority_replaced:
        normalized.append(
            TriageSuggestion(
                field="priority",
                current_value=current_priority,
                suggested_value="High",
                reasoning=_SECURITY_PRIORITY_REASONING,
                confidence=0.99,
            )
        )

    return normalized


# ---------------------------------------------------------------------------
# Main analysis entry point
# ---------------------------------------------------------------------------


def analyze_ticket(issue: dict[str, Any], model_id: str) -> TriageResult:
    """Analyze a single ticket and return triage suggestions."""
    provider = _get_model_provider(model_id)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")
    fields = issue.get("fields", {})
    request_type = extract_request_type_name_from_fields(fields)

    system = SYSTEM_PROMPT.format(
        priorities=", ".join(KNOWN_PRIORITIES),
        request_types=", ".join(get_request_type_names()),
        statuses=", ".join(KNOWN_STATUSES),
    )
    from knowledge_base import kb_store

    base_context = _build_ticket_context(issue)
    kb_matches = kb_store.find_relevant_articles(
        request_type=request_type,
        query_text=base_context,
        limit=3,
    )
    user_msg = _build_ticket_context(issue, kb_matches=kb_matches)

    logger.info("Analyzing %s with %s (%s)", issue.get("key"), model_id, provider)

    if provider == "openai":
        raw = _call_openai(model_id, system, user_msg)
    elif provider == "anthropic":
        raw = _call_anthropic(model_id, system, user_msg)
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    suggestions = _enforce_security_priority(issue, _parse_suggestions(raw, issue))

    return TriageResult(
        key=issue.get("key", ""),
        suggestions=suggestions,
        model_used=model_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _parse_technician_score(raw: str, key: str, model_id: str) -> TechnicianScore:
    """Parse AI response JSON into a TechnicianScore."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse technician score JSON: %s", text[:200])
        raise ValueError("Model returned invalid technician score JSON") from exc

    def _clamp_score(value: Any) -> int:
        try:
            numeric = int(round(float(value)))
        except (TypeError, ValueError):
            numeric = 1
        return max(1, min(5, numeric))

    return TechnicianScore(
        key=key,
        communication_score=_clamp_score(data.get("communication_score")),
        communication_notes=str(data.get("communication_notes", "")).strip(),
        documentation_score=_clamp_score(data.get("documentation_score")),
        documentation_notes=str(data.get("documentation_notes", "")).strip(),
        score_summary=str(data.get("score_summary", "")).strip(),
        model_used=model_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _parse_kb_draft(
    raw: str,
    key: str,
    model_id: str,
    existing_article: KnowledgeBaseArticle | None,
    fallback_request_type: str = "",
) -> KnowledgeBaseDraft:
    """Parse AI response JSON into a KB draft payload."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse KB draft JSON: %s", text[:200])
        raise ValueError("Model returned invalid KB draft JSON") from exc

    request_type = str(data.get("request_type", "")).strip() or fallback_request_type

    recommended_action = str(data.get("recommended_action", "")).strip().lower()
    if recommended_action not in {"update_existing", "create_new"}:
        recommended_action = "update_existing" if existing_article else "create_new"

    return KnowledgeBaseDraft(
        title=str(data.get("title", "")).strip() or (existing_article.title if existing_article else f"{key} Resolution"),
        request_type=request_type or (existing_article.request_type if existing_article else ""),
        summary=str(data.get("summary", "")).strip(),
        content=str(data.get("content", "")).strip(),
        model_used=model_id,
        source_ticket_key=key,
        suggested_article_id=existing_article.id if existing_article else None,
        suggested_article_title=existing_article.title if existing_article else "",
        recommended_action=recommended_action,
        change_summary=str(data.get("change_summary", "")).strip(),
    )


def score_closed_ticket(
    issue: dict[str, Any],
    request_comments: list[dict[str, Any]],
    model_id: str,
) -> TechnicianScore:
    """Score technician communication/documentation for a closed ticket."""
    provider = _get_model_provider(model_id)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")

    user_msg = _build_technician_score_context(issue, request_comments)
    logger.info("Scoring technician QA for %s with %s (%s)", issue.get("key"), model_id, provider)

    if provider == "openai":
        raw = _call_openai(model_id, TECHNICIAN_SCORE_PROMPT, user_msg)
    elif provider == "anthropic":
        raw = _call_anthropic(model_id, TECHNICIAN_SCORE_PROMPT, user_msg)
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    return _parse_technician_score(raw, issue.get("key", ""), model_id)


def draft_kb_article(
    issue: dict[str, Any],
    request_comments: list[dict[str, Any]],
    model_id: str,
    existing_article: KnowledgeBaseArticle | None = None,
) -> KnowledgeBaseDraft:
    """Generate a KB draft from a closed ticket and optional existing article."""
    provider = _get_model_provider(model_id)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")

    user_msg = _build_kb_draft_context(issue, request_comments, existing_article)
    logger.info("Drafting KB article for %s with %s (%s)", issue.get("key"), model_id, provider)

    if provider == "openai":
        raw = _call_openai(model_id, KB_DRAFT_PROMPT, user_msg)
    elif provider == "anthropic":
        raw = _call_anthropic(model_id, KB_DRAFT_PROMPT, user_msg)
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    return _parse_kb_draft(
        raw,
        issue.get("key", ""),
        model_id,
        existing_article,
        fallback_request_type=extract_request_type_name_from_fields(issue.get("fields", {})),
    )


def reformat_kb_article_content(article: KnowledgeBaseArticle, model_id: str) -> str:
    """Reformat an existing KB article's content as structured markdown."""
    provider = _get_model_provider(model_id)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")

    user_msg = (
        f"Article Title: {article.title}\n"
        f"Request Type: {article.request_type or 'General'}\n\n"
        f"Current content:\n{article.content}"
    )
    logger.info("Reformatting KB article %s with %s (%s)", article.id, model_id, provider)

    if provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": KB_REFORMAT_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=3000,
        )
        return (resp.choices[0].message.content or "").strip()

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=model_id,
        system=KB_REFORMAT_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.2,
        max_tokens=3000,
    )
    return resp.content[0].text.strip()


# ---------------------------------------------------------------------------
# Suggestion validation against live Jira data
# ---------------------------------------------------------------------------

# TTL-cached lookups to avoid hammering the Jira API on every validation.
_priority_cache: tuple[float, set[str]] = (0.0, set())
_user_cache: tuple[float, dict[str, str]] = (0.0, {})  # display_name_lower -> accountId
_rt_cache: tuple[float, dict[str, str]] = (0.0, {})  # name -> requestTypeId
_CACHE_TTL = 600  # 10 minutes

# Service desk ID (auto-detected on first call)
_service_desk_id: str | None = None


def _get_service_desk_id() -> str:
    """Auto-detect the service desk ID for the configured project."""
    global _service_desk_id
    if _service_desk_id:
        return _service_desk_id

    from jira_client import JiraClient
    from config import JIRA_PROJECT
    client = JiraClient()
    url = f"{client.base_url}/rest/servicedeskapi/servicedesk"
    resp = client.session.get(url)
    resp.raise_for_status()
    desks = resp.json().get("values", [])
    # Prefer the desk matching the configured project key (e.g. OIT)
    for d in desks:
        if d.get("projectKey", "").upper() == JIRA_PROJECT.upper():
            _service_desk_id = str(d.get("id", "1"))
            logger.info("Auto-detected service desk ID: %s (project %s)", _service_desk_id, JIRA_PROJECT)
            return _service_desk_id
    # Fallback to first desk
    if desks:
        _service_desk_id = str(desks[0].get("id", "1"))
    else:
        _service_desk_id = "1"
    logger.info("Auto-detected service desk ID: %s (fallback)", _service_desk_id)
    return _service_desk_id


# Approved request types — only these should be assigned during triage
_APPROVED_REQUEST_TYPES: set[str] = {
    "Security Alert",
    "Get IT help",
    "Email or Outlook",
    "Password MFA Authentication",
    "Server Infrastructure Database",
    "Business Application Support",
    "VPN",
    "Backup and Storage",
    "Report a computer equipment problem",
    "Request a new user account",
    "Offboard employees",
    "Onboard new employees",
    "Phone RingCentral",
    "Virtual Desktop",
    "Request new PC software",
}


def _get_request_types() -> dict[str, str]:
    """Return {name: requestTypeId} for approved request types, cached with TTL."""
    global _rt_cache
    now = time.monotonic()
    if _rt_cache[1] and now - _rt_cache[0] < _CACHE_TTL:
        return _rt_cache[1]

    from jira_client import JiraClient
    try:
        client = JiraClient()
        sd_id = _get_service_desk_id()
        raw = client.get_request_types(sd_id)
        # Only include approved request types
        rt_map = {}
        for rt in raw:
            name = rt.get("name", "")
            rid = rt.get("id")
            if not name or not rid:
                continue
            if name in _APPROVED_REQUEST_TYPES:
                rt_map[name] = str(rid)
        _rt_cache = (now, rt_map)
        logger.info("Validation: cached %d request types: %s", len(rt_map), list(rt_map.keys()))
        return rt_map
    except Exception:
        logger.exception("Validation: failed to fetch request types")
        return {}


def get_request_type_names() -> list[str]:
    """Return list of valid request type names."""
    return list(_get_request_types().keys())


def get_request_type_id(name: str) -> str | None:
    """Return the request type ID for a given name, or None."""
    return _get_request_types().get(name)


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

        elif s.field == "request_type":
            valid_rts = get_request_type_names()
            if s.suggested_value not in valid_rts:
                logger.warning(
                    "Validation: dropping %s request_type suggestion '%s' — "
                    "not a valid request type",
                    key, s.suggested_value,
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
