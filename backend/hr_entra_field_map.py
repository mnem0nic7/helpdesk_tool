"""Mapping between Entra user attributes and Jira HR-board custom fields.

Source of truth is ``ADP Jira Mapping v1.xlsx``. A row is only written to Jira when it is
``enabled`` *and* has a ``jira_field_id``. Rows the sheet marks "Create" have no Jira field ID
until ``scripts/hr_jira_field_admin.py`` has been applied -- paste the emitted IDs in here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

EXT_PREFIX = "extension_e845d067ba25406ab31994d924ae9524_"

# Jira field value kinds -> how the payload is shaped.
KIND_TEXT = "text"
KIND_SELECT = "select"
KIND_DATE = "date"
KIND_DATETIME = "datetime"


@dataclass(frozen=True)
class FieldMapping:
    jira_name: str
    kind: str
    # Entra property to $select. ``None`` for values derived from another lookup (manager).
    entra_property: str | None = None
    # Field-id as ``customfield_NNNNN``; ``None`` until the Jira field has been created.
    jira_field_id: str | None = None
    # Special derivations resolved by the sync service: "manager_name" / "manager_email".
    derived: str | None = None
    enabled: bool = True
    note: str = ""


def _ext(name: str) -> str:
    return f"{EXT_PREFIX}{name}"


FIELD_MAP: tuple[FieldMapping, ...] = (
    FieldMapping("Business Unit", KIND_TEXT, _ext("division"), "customfield_13458"),
    FieldMapping("Preferred Name", KIND_TEXT, "displayName", "customfield_15085"),
    FieldMapping("Home State", KIND_TEXT, _ext("msDS_cloudExtensionAttribute19"), "customfield_15086"),
    FieldMapping(
        "FLSA Status", KIND_SELECT, "employeeId", "customfield_13028", enabled=False,
        note="Sheet maps FLSA to employeeID, which looks wrong; Jira options are Exempt/Non-Exempt/Unknown. Confirm source.",
    ),
    FieldMapping("Home Department", KIND_TEXT, "department", "customfield_13459"),
    FieldMapping("Function", KIND_SELECT, _ext("jobFunction"), "customfield_11113"),
    FieldMapping("Job Title", KIND_TEXT, "title", "customfield_12866"),
    FieldMapping("Leadership Level 2", KIND_TEXT, _ext("msDS_cloudExtensionAttribute14"), "customfield_15087"),
    FieldMapping("Leadership Level 3", KIND_TEXT, _ext("msDS_cloudExtensionAttribute15"), "customfield_15088"),
    FieldMapping("Legal First Name", KIND_TEXT, "givenName", "customfield_12873"),
    FieldMapping("Legal Last Name", KIND_TEXT, "surname", "customfield_12874"),
    FieldMapping(
        "Legal Middle Name", KIND_TEXT, None, "customfield_12881", enabled=False,
        note="'middleName' is an AD attribute, not a Microsoft Graph v1.0 user property; confirm the Entra source.",
    ),
    FieldMapping("Employee location", KIND_TEXT, "officeLocation", "customfield_12893"),
    FieldMapping("People Manager (Yes/No)", KIND_SELECT, _ext("msDS_cloudExtensionAttribute13"), "customfield_15089"),
    FieldMapping("Position ID", KIND_TEXT, _ext("positionID"), "customfield_12865"),
    FieldMapping("Position Status", KIND_TEXT, _ext("positionStatus"), "customfield_15090"),
    FieldMapping("Manager Name", KIND_TEXT, None, "customfield_15038", derived="manager_name"),
    FieldMapping("Seniority Date", KIND_DATE, _ext("msDS_cloudExtensionAttribute1"), "customfield_15091"),
    # --- Sheet rows still marked "Please provide": wired up but off until HR/ADP define the source. ---
    FieldMapping("Associate ID", KIND_TEXT, None, "customfield_15092", enabled=False, note="Entra source undefined in sheet."),
    FieldMapping("Company email address", KIND_TEXT, None, "customfield_12879", enabled=False, note="Entra source undefined in sheet."),
    FieldMapping("Hire Date", KIND_DATETIME, None, "customfield_12870", enabled=False, note="Entra source undefined in sheet."),
    FieldMapping("Worker Category", KIND_SELECT, None, "customfield_12894", enabled=False, note="Entra source undefined in sheet."),
    FieldMapping("Job Class", KIND_TEXT, None, "customfield_15093", enabled=False, note="Entra source undefined in sheet."),
    FieldMapping("Manager Email", KIND_TEXT, None, "customfield_15094", derived="manager_email", enabled=False, note="Entra source undefined in sheet."),
    FieldMapping("Work Arrangement", KIND_SELECT, None, "customfield_15095", enabled=False, note="Entra source undefined in sheet."),
)

COMPANY_EMAIL_FIELD_ID = "customfield_12879"
PERSONAL_EMAIL_FIELD_ID = "customfield_12883"

# Jira fields that carry the address used to find the Entra user (checked in this order).
LOOKUP_EMAIL_FIELD_IDS: tuple[str, ...] = (
    COMPANY_EMAIL_FIELD_ID,  # Company email address (HRD)
    PERSONAL_EMAIL_FIELD_ID,  # Personal Email Address (New Hire) (HRD onboarding, LIBTA)
)


def active_mappings() -> list[FieldMapping]:
    """Mappings that can actually be written right now."""
    return [m for m in FIELD_MAP if m.enabled and m.jira_field_id]


def graph_select_properties() -> list[str]:
    props = {"id", "userPrincipalName", "mail", "otherMails", "manager", "displayName", "accountEnabled", "userType"}
    props.update(m.entra_property for m in active_mappings() if m.entra_property)
    return sorted(props)


def issue_fields_to_request() -> list[str]:
    ids = set(LOOKUP_EMAIL_FIELD_IDS) | {"reporter"}
    ids.update(m.jira_field_id for m in active_mappings() if m.jira_field_id)
    return sorted(ids)


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d", "%m-%d-%Y")


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# Entra spellings that mean an option Jira already has (Function select). Anything else that is not a Jira
# option is rejected by Jira per-field and skipped, so add new Jira options rather than aliases for new concepts.
SELECT_ALIASES: dict[str, dict[str, str]] = {
    "Function": {"information technology": "IT", "human resources": "HR"},
}
# ADP import header text that leaked into some accounts' attributes; never a real value.
_HEADER_ARTIFACTS = {"jobfunction", "jobfunctiondescription"}

_YES = {"y", "yes", "true", "1"}
_NO = {"n", "no", "false", "0"}


def to_yes_no(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in _YES:
        return "Yes"
    if text in _NO:
        return "No"
    return None


def jira_value(mapping: FieldMapping, raw: Any) -> Any | None:
    """Shape an Entra value for the Jira REST payload; ``None`` means nothing to write."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if mapping.kind == KIND_TEXT:
        return str(raw).strip()
    if mapping.kind == KIND_SELECT:
        if mapping.jira_name == "People Manager (Yes/No)":
            normalized = to_yes_no(raw)
            return {"value": normalized} if normalized else None
        text = str(raw).strip()
        if text.lower() in _HEADER_ARTIFACTS:
            return None
        return {"value": SELECT_ALIASES.get(mapping.jira_name, {}).get(text.lower(), text)}
    if mapping.kind in (KIND_DATE, KIND_DATETIME):
        parsed = parse_date(raw)
        if parsed is None:
            return None
        if mapping.kind == KIND_DATE:
            return parsed.isoformat()
        stamp = datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)
        return stamp.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    return None


_EMAIL_FIND_RE = re.compile(r"[A-Za-z0-9._%+'\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def normalize_email(value: Any) -> str | None:
    """First email address in a field value, lowercased.

    Jira text fields often hold wiki links (``[a@x.com|mailto:a@x.com]``) rather than a bare address.
    Apostrophes are legal in a local part (O'Brien), so quoting is handled where the address is used.
    """
    match = _EMAIL_FIND_RE.search(str(value or ""))
    if not match:
        return None
    local, _, domain = match.group(0).partition("@")
    local = local.strip("'")
    return f"{local}@{domain}".lower() if local else None


# Mailboxes the AskHR/Benefits bot files tickets as; a ticket whose reporter is one of these has no human reporter.
SERVICE_MAILBOXES = frozenset({"askhr@librasolutionsgroup.com", "benefits@librasolutionsgroup.com"})
# Same intent as e5_license_report's non-person flag: shared/room/test/service-style accounts are not employees.
NON_PERSON_RE = re.compile(
    r"(?<![a-z0-9])(room|conf|conference|test|migration|svc|service|noreply|no-reply|donotreply|scanner|printer"
    r"|shared|payroll|benefits|askhr|marketing[\s._-]*dev)(?![a-z0-9])",
    re.IGNORECASE,
)
_PERSON_REPORTER_TYPES = {"customer", "atlassian"}


def ticket_emails(fields: dict[str, Any]) -> list[str]:
    """Work/personal emails typed on the ticket, in LOOKUP_EMAIL_FIELD_IDS order, de-duplicated."""
    found: list[str] = []
    for field_id in LOOKUP_EMAIL_FIELD_IDS:
        email = normalize_email(fields.get(field_id))
        if email and email not in found:
            found.append(email)
    return found


def ticket_emails_by_field(fields: dict[str, Any]) -> list[tuple[str, str]]:
    """(email, jira field id) for each lookup field that holds an address, de-duplicated by address."""
    found: list[tuple[str, str]] = []
    for field_id in LOOKUP_EMAIL_FIELD_IDS:
        email = normalize_email(fields.get(field_id))
        if email and email not in [e for e, _ in found]:
            found.append((email, field_id))
    return found


def is_internal_email(email: str, internal_domains: set[str] | frozenset[str]) -> bool:
    """True if the address is on a tenant domain (or a subdomain of one)."""
    domain = email.rpartition("@")[2].lower()
    return any(domain == d or domain.endswith("." + d) for d in internal_domains)


def fingerprint(emails: list[str]) -> str:
    return "|".join(sorted(emails))


def reporter_email(fields: dict[str, Any]) -> str | None:
    """The reporter's email when the reporter is a person (not an app, a bot mailbox, or a service-style account)."""
    reporter = fields.get("reporter") or {}
    if str(reporter.get("accountType") or "") not in _PERSON_REPORTER_TYPES:
        return None
    email = normalize_email(reporter.get("emailAddress"))
    if not email or email in SERVICE_MAILBOXES:
        return None
    if NON_PERSON_RE.search(email.split("@")[0]) or NON_PERSON_RE.search(str(reporter.get("displayName") or "")):
        return None
    return email


def is_person_account(user: dict[str, Any]) -> bool:
    """Entra-side check for a reporter-derived match: an enabled member account that is not service-style."""
    if user.get("accountEnabled") is False:
        return False
    if str(user.get("userType") or "Member") != "Member":
        return False
    return not NON_PERSON_RE.search(str(user.get("displayName") or ""))


def entra_value(mapping: FieldMapping, user: dict[str, Any], manager: dict[str, Any] | None) -> Any:
    if mapping.derived == "manager_name":
        return (manager or {}).get("displayName")
    if mapping.derived == "manager_email":
        return (manager or {}).get("mail")
    if mapping.entra_property:
        return user.get(mapping.entra_property)
    return None


def build_issue_fields(
    user: dict[str, Any], manager: dict[str, Any] | None
) -> tuple[dict[str, Any], list[str]]:
    """Return (jira fields payload, jira names Entra had no value for)."""
    payload: dict[str, Any] = {}
    empty: list[str] = []
    for mapping in active_mappings():
        value = jira_value(mapping, entra_value(mapping, user, manager))
        if value is None:
            empty.append(mapping.jira_name)
            continue
        payload[mapping.jira_field_id] = value  # type: ignore[index]
    return payload, empty
