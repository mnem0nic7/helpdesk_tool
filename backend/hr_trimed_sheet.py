"""Trimed roster spreadsheet: a fallback source for HR-board ticket fields.

Trimed (trimed-billing.com) employees are not reliably populated in Entra, so the Entra -> Jira sync
also consults an ADP "Employment Profile" export. The sheet only *fills gaps*: Entra values win, and
the sheet supplies any mapped field Entra left empty (or all of them when Entra has no match).

The file lives at ``HR_TRIMED_SHEET_PATH`` (default ``DATA_DIR/hr_trimed_roster.xlsx``) and is never
committed. Replace the file to refresh it; it is re-read when its mtime changes. A missing or
unreadable file disables the feature rather than failing the sync.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timedelta
from typing import Any

import hr_entra_field_map as fmap
from config import HR_TRIMED_SHEET_PATH

logger = logging.getLogger(__name__)

# Jira field name (hr_entra_field_map.FieldMapping.jira_name) -> sheet column header.
SHEET_COLUMNS: dict[str, str] = {
    "Business Unit": "Business Unit Description",
    "Home State": "Primary Address: State / Territory Description",
    "Home Department": "Home Department Description",
    "Function": "Job Function Description",
    "Job Title": "Job Title Description",
    "Leadership Level 2": "Leadership Levels (L2)",
    "Leadership Level 3": "Leadership Levels (L3)",
    "Legal First Name": "Legal First Name",
    "Legal Last Name": "Legal Last Name",
    "Employee location": "Location Description",
    "Position ID": "Position ID",
    "Position Status": "Position Status",
    "Seniority Date": "Seniority Date",
}
_WORK_EMAIL = "Work Contact: Work Email"
_PERSONAL_EMAIL = "Personal Contact: Personal Email"
_POSITION_ID = "Position ID"

_lock = threading.Lock()
_cache: dict[str, Any] = {"path": None, "mtime": None, "rows": [], "by_email": {}, "by_position": {}}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _excel_date(value: Any) -> str:
    """ISO date for an Excel serial number, a datetime/date, or a date string; '' if unparseable."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _text(value)
    if text.replace(".", "", 1).isdigit():
        return (date(1899, 12, 30) + timedelta(days=int(float(text)))).isoformat()
    parsed = fmap.parse_date(text)
    return parsed.isoformat() if parsed else ""


def _person_name(last_first: str) -> str:
    """'James, Brodie' -> 'Brodie James' (the sheet stores legal names as 'Last, First')."""
    last, sep, first = last_first.partition(",")
    return f"{first.strip()} {last.strip()}".strip() if sep else last_first.strip()


def _load(path: str) -> dict[str, Any]:
    import openpyxl  # imported lazily: only needed when the sheet exists

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        header: list[str] | None = None
        rows: list[dict[str, Any]] = []
        for raw in wb.worksheets[0].iter_rows(values_only=True):
            if header is None:  # the header row is the first one containing "Position ID"
                cells = [_text(c) for c in raw]
                if _POSITION_ID in cells:
                    header = cells
                continue
            row = {h: raw[i] for i, h in enumerate(header) if h and i < len(raw)}
            if _text(row.get(_POSITION_ID)) or _text(row.get(_WORK_EMAIL)):
                rows.append(row)
    finally:
        wb.close()
    by_email: dict[str, dict[str, Any]] = {}
    by_position: dict[str, dict[str, Any]] = {}
    for row in rows:
        for col in (_WORK_EMAIL, _PERSONAL_EMAIL):
            email = fmap.normalize_email(row.get(col))
            if email:
                by_email.setdefault(email, row)
        position = _text(row.get(_POSITION_ID))
        if position:
            by_position.setdefault(position, row)
    return {"rows": rows, "by_email": by_email, "by_position": by_position}


def _index() -> dict[str, Any]:
    path = HR_TRIMED_SHEET_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {"by_email": {}, "by_position": {}}
    with _lock:
        if _cache["path"] != path or _cache["mtime"] != mtime:
            try:
                loaded = _load(path)
            except Exception:  # noqa: BLE001 - a bad file must never break the sync
                logger.exception("HR Trimed sheet: could not read %s", path)
                loaded = {"rows": [], "by_email": {}, "by_position": {}}
            else:
                logger.info("HR Trimed sheet: loaded %d row(s) from %s", len(loaded["rows"]), path)
            _cache.update(path=path, mtime=mtime, **loaded)
        return _cache


def find_row(emails: list[str], position_id: str = "") -> dict[str, Any] | None:
    """The sheet row for any of the emails (work or personal), else by Position ID; ``None`` if no match."""
    index = _index()
    for email in emails:
        row = index["by_email"].get(email.lower())
        if row:
            return row
    position = position_id.strip()
    return index["by_position"].get(position) if position else None


def build_issue_fields(row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """(jira fields payload, jira names the sheet had no value for) for the currently active mappings."""
    payload: dict[str, Any] = {}
    empty: list[str] = []
    for mapping in fmap.active_mappings():
        raw: Any = None
        if mapping.jira_name == "Preferred Name":
            first = _text(row.get("Preferred or Chosen First Name")) or _text(row.get("Legal First Name"))
            last = _text(row.get("Preferred or Chosen Last Name")) or _text(row.get("Legal Last Name"))
            raw = f"{first} {last}".strip()
        elif mapping.derived == "manager_name":
            raw = _person_name(_text(row.get("Reports To Legal Name")))
        elif mapping.jira_name in SHEET_COLUMNS:
            raw = row.get(SHEET_COLUMNS[mapping.jira_name])
            if mapping.kind in (fmap.KIND_DATE, fmap.KIND_DATETIME):
                raw = _excel_date(raw)
        value = fmap.jira_value(mapping, raw)
        if value is None:
            empty.append(mapping.jira_name)
        else:
            payload[mapping.jira_field_id] = value  # type: ignore[index]
    return payload, empty
