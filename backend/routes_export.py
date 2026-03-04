"""API routes for Excel report export and report builder."""

from __future__ import annotations

import logging
import statistics
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from issue_cache import cache
from metrics import issue_to_row
from models import ReportConfig
from routes_tickets import _match

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# ---------------------------------------------------------------------------
# Column metadata — maps TicketRow field keys to human-readable labels
# ---------------------------------------------------------------------------

FIELD_META: dict[str, dict[str, str]] = {
    "key": {"label": "Key", "description": "Jira issue key"},
    "summary": {"label": "Summary", "description": "Issue title"},
    "issue_type": {"label": "Type", "description": "Issue type"},
    "status": {"label": "Status", "description": "Current status"},
    "status_category": {"label": "Status Category", "description": "Status category (To Do / In Progress / Done)"},
    "priority": {"label": "Priority", "description": "Priority level"},
    "resolution": {"label": "Resolution", "description": "Resolution type"},
    "assignee": {"label": "Assignee", "description": "Assigned team member"},
    "assignee_account_id": {"label": "Assignee ID", "description": "Assignee Atlassian account ID"},
    "reporter": {"label": "Reporter", "description": "Person who created the ticket"},
    "created": {"label": "Created", "description": "Date ticket was created"},
    "updated": {"label": "Updated", "description": "Date ticket was last updated"},
    "resolved": {"label": "Resolved", "description": "Date ticket was resolved"},
    "request_type": {"label": "Request Type", "description": "JSM request type"},
    "calendar_ttr_hours": {"label": "TTR (h)", "description": "Calendar time-to-resolution in hours"},
    "age_days": {"label": "Age (d)", "description": "Age of open tickets in days"},
    "days_since_update": {"label": "Days Since Update", "description": "Days since last update"},
    "excluded": {"label": "Excluded", "description": "Excluded from metrics"},
    "sla_first_response_status": {"label": "SLA Response", "description": "First-response SLA status"},
    "sla_resolution_status": {"label": "SLA Resolution", "description": "Resolution SLA status"},
    "labels": {"label": "Labels", "description": "Issue labels"},
}

# All TicketRow field keys in display order
ALL_FIELDS: list[str] = list(FIELD_META.keys())

# Default columns shown when no selection is provided
DEFAULT_COLUMNS: list[str] = [
    "key", "summary", "issue_type", "status", "priority",
    "assignee", "created", "resolved", "calendar_ttr_hours",
]

# ---------------------------------------------------------------------------
# Legacy column definitions for the old /export/excel endpoint
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Report builder helpers
# ---------------------------------------------------------------------------


def _apply_config(config: ReportConfig) -> list[dict[str, Any]]:
    """Filter, convert to flat rows, and sort according to the config."""
    # Choose issue set based on include_excluded
    if config.include_excluded:
        issues = cache.get_all_issues()
    else:
        issues = cache.get_filtered_issues()

    # Apply filters via the shared _match function
    filters = config.filters.model_dump(exclude_none=True)
    # Remove false booleans so _match doesn't treat them as active
    for k in ("open_only", "stale_only"):
        if not filters.get(k):
            filters.pop(k, None)
    matched = [iss for iss in issues if _match(iss, **filters)]

    # Convert to flat rows
    rows = [issue_to_row(iss) for iss in matched]

    # Sort
    sort_field = config.sort_field or "created"
    reverse = config.sort_dir == "desc"

    def sort_key(row: dict[str, Any]) -> Any:
        val = row.get(sort_field)
        if val is None:
            return "" if isinstance(row.get(sort_field, ""), str) else -1
        return val

    rows.sort(key=sort_key, reverse=reverse)

    return rows


def _select_columns(row: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    """Pick only the selected keys from a row dict."""
    return {k: row.get(k) for k in columns}


def _aggregate(rows: list[dict[str, Any]], group_by: str) -> list[dict[str, Any]]:
    """Group flat rows by a field and return summary rows."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        val = row.get(group_by)
        if isinstance(val, list):
            key = ", ".join(val) if val else "(none)"
        elif isinstance(val, bool):
            key = "Yes" if val else "No"
        else:
            key = str(val) if val else "(none)"
        groups[key].append(row)

    summary: list[dict[str, Any]] = []
    for group_val, group_rows in sorted(groups.items()):
        open_count = sum(
            1 for r in group_rows
            if r.get("status_category", "") != "Done"
        )
        ttrs = [
            r["calendar_ttr_hours"] for r in group_rows
            if r.get("calendar_ttr_hours") is not None
        ]
        avg_ttr = round(statistics.mean(ttrs), 1) if ttrs else None
        summary.append({
            "group": group_val,
            "count": len(group_rows),
            "open": open_count,
            "avg_ttr_hours": avg_ttr,
        })

    return summary


def _cell_value(value: Any) -> Any:
    """Convert a value for Excel output."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if value is None:
        return ""
    return value


# ---------------------------------------------------------------------------
# Report builder endpoints
# ---------------------------------------------------------------------------


@router.post("/report/preview")
async def report_preview(config: ReportConfig) -> dict[str, Any]:
    """Return a preview of the report (capped at 100 rows)."""
    rows = _apply_config(config)
    columns = config.columns or DEFAULT_COLUMNS

    if config.group_by:
        agg = _aggregate(rows, config.group_by)
        return {
            "rows": agg[:100],
            "total_count": len(agg),
            "grouped": True,
        }

    selected = [_select_columns(r, columns) for r in rows[:100]]
    return {
        "rows": selected,
        "total_count": len(rows),
        "grouped": False,
    }


@router.post("/report/export")
async def report_export(config: ReportConfig) -> FileResponse:
    """Generate and return an Excel workbook from the report config."""
    rows = _apply_config(config)
    columns = config.columns or DEFAULT_COLUMNS

    wb = Workbook()
    ws = wb.active

    if config.group_by:
        # Grouped summary sheet
        ws.title = f"By {FIELD_META.get(config.group_by, {}).get('label', config.group_by)}"
        agg = _aggregate(rows, config.group_by)
        headers = [
            FIELD_META.get(config.group_by, {}).get("label", config.group_by),
            "Count", "Open", "Avg TTR (h)",
        ]
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
            cell.alignment = _HEADER_ALIGNMENT
        for row_idx, agg_row in enumerate(agg, 2):
            ws.cell(row=row_idx, column=1, value=agg_row["group"])
            ws.cell(row=row_idx, column=2, value=agg_row["count"])
            ws.cell(row=row_idx, column=3, value=agg_row["open"])
            ws.cell(row=row_idx, column=4, value=agg_row["avg_ttr_hours"] or "")
        # Column widths
        ws.column_dimensions["A"].width = 30
        ws.column_dimensions["B"].width = 10
        ws.column_dimensions["C"].width = 10
        ws.column_dimensions["D"].width = 14
    else:
        # Flat detail sheet
        ws.title = "OIT Report"
        headers = [FIELD_META.get(c, {}).get("label", c) for c in columns]
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
            cell.alignment = _HEADER_ALIGNMENT
        for row_idx, row in enumerate(rows, 2):
            for col_idx, col_key in enumerate(columns, 1):
                ws.cell(row=row_idx, column=col_idx, value=_cell_value(row.get(col_key)))

        # Auto-filter & freeze
        if columns:
            last_col = get_column_letter(len(columns))
            ws.auto_filter.ref = f"A1:{last_col}{len(rows) + 1}"
        ws.freeze_panes = "A2"

        # Column widths
        _WIDTH_DEFAULTS: dict[str, int] = {
            "key": 12, "summary": 50, "issue_type": 18, "status": 22,
            "priority": 12, "assignee": 25, "reporter": 25, "created": 22,
            "updated": 22, "resolved": 22, "calendar_ttr_hours": 12,
            "age_days": 10, "sla_first_response_status": 15,
            "sla_resolution_status": 15, "excluded": 10, "labels": 30,
        }
        for col_idx, col_key in enumerate(columns, 1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = _WIDTH_DEFAULTS.get(col_key, 15)

    # Save to temp file
    now = datetime.now(timezone.utc)
    filename = f"OIT_Report_{now.strftime('%Y%m%d_%H%M')}.xlsx"
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp_path = tmp.name
    tmp.close()
    wb.save(tmp_path)
    logger.info("Report export saved to %s (%d rows)", tmp_path, len(rows))

    return FileResponse(
        path=tmp_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=None,
    )


# ---------------------------------------------------------------------------
# Legacy full export (unchanged)
# ---------------------------------------------------------------------------


@router.get("/export/excel")
async def export_excel() -> FileResponse:
    """Generate and return an Excel workbook with all OIT issues."""
    logger.info("Starting Excel export from cache")

    # Read from cache (all issues, including excluded)
    issues = cache.get_all_issues()
    logger.info("Export: %d issues from cache", len(issues))

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
