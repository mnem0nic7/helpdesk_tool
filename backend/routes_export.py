"""API routes for Excel report export."""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import FileResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from config import JIRA_PROJECT
from jira_client import JiraClient
from metrics import issue_to_row

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Shared client instance
_client = JiraClient()

# Base JQL for all OIT issues (including excluded so they get the flag)
_ALL_JQL = f"project = {JIRA_PROJECT} ORDER BY key ASC"

# Column definitions: (header_text, row_dict_key)
_COLUMNS: list[tuple[str, str]] = [
    ("Key", "key"),
    ("Summary", "summary"),
    ("Type", "issue_type"),
    ("Status", "status"),
    ("Priority", "priority"),
    ("Assignee", "assignee"),
    ("Reporter", "reporter"),
    ("Created", "created"),
    ("Updated", "updated"),
    ("Resolved", "resolved"),
    ("TTR (h)", "calendar_ttr_hours"),
    ("Age (d)", "age_days"),
    ("SLA Response", "sla_first_response_status"),
    ("SLA Resolution", "sla_resolution_status"),
    ("Excluded", "excluded"),
]

# Header styling
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
_HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center")


@router.get("/export/excel")
async def export_excel() -> FileResponse:
    """Generate and return an Excel workbook with all OIT issues."""
    logger.info("Starting Excel export for project %s", JIRA_PROJECT)

    # Fetch all issues
    issues = _client.search_all(_ALL_JQL)
    logger.info("Fetched %d issues for export", len(issues))

    # Create workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "OIT Tickets"

    # Write header row
    for col_idx, (header_text, _) in enumerate(_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header_text)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _HEADER_ALIGNMENT

    # Write data rows
    for row_idx, issue in enumerate(issues, start=2):
        row_data = issue_to_row(issue)
        for col_idx, (_, dict_key) in enumerate(_COLUMNS, start=1):
            value = row_data.get(dict_key, "")
            # Convert booleans to Yes/No for readability
            if isinstance(value, bool):
                value = "Yes" if value else "No"
            # Convert None to empty string
            if value is None:
                value = ""
            ws.cell(row=row_idx, column=col_idx, value=value)

    # Auto-filter on all columns
    last_col_letter = chr(ord("A") + len(_COLUMNS) - 1)
    ws.auto_filter.ref = f"A1:{last_col_letter}{len(issues) + 1}"

    # Freeze the top row
    ws.freeze_panes = "A2"

    # Adjust column widths for readability
    _WIDTHS: dict[str, int] = {
        "Key": 12,
        "Summary": 50,
        "Type": 18,
        "Status": 22,
        "Priority": 12,
        "Assignee": 25,
        "Reporter": 25,
        "Created": 22,
        "Updated": 22,
        "Resolved": 22,
        "TTR (h)": 12,
        "Age (d)": 10,
        "SLA Response": 15,
        "SLA Resolution": 15,
        "Excluded": 10,
    }
    for col_idx, (header_text, _) in enumerate(_COLUMNS, start=1):
        col_letter = chr(ord("A") + col_idx - 1)
        ws.column_dimensions[col_letter].width = _WIDTHS.get(header_text, 15)

    # Save to temp file
    now = datetime.now(timezone.utc)
    filename = f"OIT_Report_{now.strftime('%Y%m%d_%H%M')}.xlsx"

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp_path = tmp.name
    tmp.close()

    wb.save(tmp_path)
    logger.info("Excel workbook saved to %s (%d rows)", tmp_path, len(issues))

    return FileResponse(
        path=tmp_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=None,
    )
