"""XLSX export/import for bulk retention policy setup.

Builds a workbook listing every known team+channel with its current policy state, and
parses an edited workbook back into raw row dicts. Deliberately has no dependency on
RetentionPolicyStore or Graph — the create/update/validation logic that decides what to
do with each parsed row lives in routes_retention.py, the only caller with DB/session
access, so this module stays pure and independently testable.
"""
from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
_HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center")

# team_name/channel_name/current_* are informational only on import (ignored except
# team_name/channel_name, which are needed if a row creates a brand-new policy).
# Column order in the uploaded file doesn't matter — parsing looks columns up by name.
EXPORT_COLUMNS = [
    "team_id", "team_name", "channel_id", "channel_name",
    "current_status", "current_retention_days", "retention_days",
]
_COLUMN_WIDTHS = {
    "team_id": 36, "team_name": 30, "channel_id": 42, "channel_name": 25,
    "current_status": 16, "current_retention_days": 18, "retention_days": 16,
}
REQUIRED_IMPORT_COLUMNS = ("team_id", "channel_id", "retention_days")


def build_export_workbook(rows: list[dict[str, Any]]) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Retention Channels"
    for col_idx, key in enumerate(EXPORT_COLUMNS, 1):
        cell = ws.cell(row=1, column=col_idx, value=key)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _HEADER_ALIGNMENT
    for row_idx, row in enumerate(rows, 2):
        for col_idx, key in enumerate(EXPORT_COLUMNS, 1):
            ws.cell(row=row_idx, column=col_idx, value=row.get(key))
    last_col = get_column_letter(len(EXPORT_COLUMNS))
    ws.auto_filter.ref = f"A1:{last_col}{len(rows) + 1}"
    ws.freeze_panes = "A2"
    for col_idx, key in enumerate(EXPORT_COLUMNS, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = _COLUMN_WIDTHS.get(key, 18)
    return wb


def _cell_str(raw_row: tuple[Any, ...], col_index: dict[str, int], name: str) -> str:
    idx = col_index.get(name)
    if idx is None or idx >= len(raw_row):
        return ""
    value = raw_row[idx]
    if value is None:
        return ""
    # Excel stores whole numbers as floats internally (e.g. 45.0 for a retention_days
    # cell typed as "45") — avoid "45.0" leaking into a value the caller will int()-parse.
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_import_workbook(content: bytes) -> list[dict[str, str]]:
    """Read the header row by name and return one raw string dict per data row.

    Raises ValueError if the file can't be read as an .xlsx workbook, or is missing
    team_id / channel_id / retention_days — the only columns import logic reads by
    name; everything else (team_name, channel_name, current_status, ...) is optional
    here even though the exporter always includes them.
    """
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(f"Could not read file as an .xlsx workbook: {exc}") from exc
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        raise ValueError("Workbook has no header row")
    header_names = [str(h).strip() if h is not None else "" for h in header]
    missing = [c for c in REQUIRED_IMPORT_COLUMNS if c not in header_names]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}")
    col_index = {name: idx for idx, name in enumerate(header_names) if name}

    rows: list[dict[str, str]] = []
    for raw_row in rows_iter:
        if raw_row is None or all(v is None for v in raw_row):
            continue
        rows.append({
            "team_id": _cell_str(raw_row, col_index, "team_id"),
            "team_name": _cell_str(raw_row, col_index, "team_name"),
            "channel_id": _cell_str(raw_row, col_index, "channel_id"),
            "channel_name": _cell_str(raw_row, col_index, "channel_name"),
            "retention_days": _cell_str(raw_row, col_index, "retention_days"),
        })
    return rows
