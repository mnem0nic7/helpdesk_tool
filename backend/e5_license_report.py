"""Weekly SPE_E5 license reclaim report: builds the workbook and emails it."""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from email_service import _get_access_token

logger = logging.getLogger(__name__)

STATUS_DISABLED = "Disabled"
STATUS_NEVER = "Enabled - never signed in"
STATUS_IDLE_90 = "Enabled - idle >90d"
STATUS_IDLE_60 = "Enabled - idle 60-90d"
_STATUS_ORDER = [STATUS_DISABLED, STATUS_NEVER, STATUS_IDLE_90, STATUS_IDLE_60]
_NON_PERSON_FLAG = "Possible non-person account"
_NON_PERSON_RE = re.compile(
    r"\b(room|conf|conference|test|migration|svc|service|noreply|no-reply|scanner|printer|shared)\b",
    re.IGNORECASE,
)
_GUIDANCE = {
    STATUS_DISABLED: "Check mailbox size / hold / convert to shared before removing license",
    STATUS_NEVER: "Confirm with manager; likely safe to reclaim",
    STATUS_IDLE_90: "Confirm with manager (leave, seasonal, or non-person account)",
    STATUS_IDLE_60: "Watch list - not yet a reclaim candidate",
}


@dataclass
class E5Seats:
    purchased: int
    consumed: int


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def classify_user(user: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    sia = user.get("signInActivity") or {}
    stamps = [
        d
        for d in (
            _parse_dt(sia.get("lastSignInDateTime")),
            _parse_dt(sia.get("lastNonInteractiveSignInDateTime")),
        )
        if d
    ]
    last = max(stamps) if stamps else None
    days = (now - last).days if last else None
    enabled = bool(user.get("accountEnabled"))

    if not enabled:
        status = STATUS_DISABLED
    elif last is None:
        status = STATUS_NEVER
    elif days <= 60:
        return None
    elif days <= 90:
        status = STATUS_IDLE_60
    else:
        status = STATUS_IDLE_90

    name = user.get("displayName") or ""
    upn = user.get("userPrincipalName") or ""
    return {
        "display_name": name,
        "upn": upn,
        "enabled": enabled,
        "last_sign_in": last,
        "days": days,
        "created": _parse_dt(user.get("createdDateTime")),
        "synced": bool(user.get("onPremisesSyncEnabled")),
        "status": status,
        "flag": _NON_PERSON_FLAG if _NON_PERSON_RE.search(f"{name} {upn.split('@')[0]}") else "",
    }


def build_rows(users: list[dict[str, Any]], now: datetime) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    excluded = 0
    for user in users:
        row = classify_user(user, now)
        if row is None:
            excluded += 1
        else:
            rows.append(row)
    far_past = datetime.min.replace(tzinfo=timezone.utc)
    rows.sort(key=lambda x: (_STATUS_ORDER.index(x["status"]), x["last_sign_in"] or far_past))
    return rows, excluded


def _count(rows: list[dict[str, Any]], status: str) -> int:
    return sum(1 for r in rows if r["status"] == status)


def build_workbook(rows: list[dict[str, Any]], excluded_active: int, seats: E5Seats, now: datetime) -> bytes:
    wb = Workbook()
    s = wb.active
    s.title = "Summary"
    acc = wb.create_sheet("E5 Accounts")

    headers = [
        "Display Name", "UPN", "Enabled", "Last Sign-In (any)", "Days Since Sign-In",
        "Created", "Synced From AD", "Status", "Flag",
    ]
    acc.append(headers)
    for c in acc[1]:
        c.font = Font(bold=True)
    for r in rows:
        acc.append([
            r["display_name"],
            r["upn"],
            "Yes" if r["enabled"] else "No",
            r["last_sign_in"].replace(tzinfo=None) if r["last_sign_in"] else None,
            r["days"],
            r["created"].replace(tzinfo=None) if r["created"] else None,
            "Yes" if r["synced"] else "No",
            r["status"],
            r["flag"],
        ])
    for col in (4, 6):
        for cell in acc[get_column_letter(col)][1:]:
            cell.number_format = "yyyy-mm-dd"
    for idx, width in enumerate([28, 38, 9, 18, 18, 14, 14, 26, 28], start=1):
        acc.column_dimensions[get_column_letter(idx)].width = width
    acc.freeze_panes = "A2"
    last_row = max(acc.max_row, 2)

    date_str = now.strftime("%Y-%m-%d")
    s["A1"] = "OLF tenant - SPE_E5 license review"
    s["A1"].font = Font(bold=True, size=14)
    s["A2"] = (
        f"Data as of {date_str} via Graph /users (signInActivity = latest of interactive and "
        "non-interactive). signInActivity can lag; treat as leads, not proof."
    )
    s["A3"] = f"Active enabled users ({excluded_active} with sign-in in the last 60 days) are excluded from this workbook."
    for col, text in zip("ABC", ["Status", "Accounts", "Reclaim guidance"]):
        s[f"{col}4"] = text
        s[f"{col}4"].font = Font(bold=True)
    for i, status in enumerate(_STATUS_ORDER):
        row = 5 + i
        s[f"A{row}"] = status
        s[f"B{row}"] = f"=COUNTIF('E5 Accounts'!$H$2:$H${last_row},A{row})"
        s[f"C{row}"] = _GUIDANCE[status]
    s["A9"], s["B9"] = "Total accounts listed", "=SUM(B5:B8)"
    s["A10"] = "Possible non-person accounts (Flag)"
    s["B10"] = f"=COUNTIF('E5 Accounts'!$I$2:$I${last_row},\"Possible*\")"
    s["C10"] = "Conference rooms, test, migration, marketing dev, service accounts"
    s["A11"], s["B11"] = "Candidates (Disabled + never + >90d)", "=B5+B6+B7"
    s["C11"] = "Upper bound before mailbox/hold checks"
    s["A13"], s["B13"] = "SPE_E5 seats purchased", seats.purchased
    s["C13"] = f"Source: Graph /subscribedSkus, {date_str}"
    s["A14"], s["B14"] = "Seats consumed", seats.consumed
    s["C14"] = "Source: Graph /subscribedSkus (consumedUnits)"
    s.column_dimensions["A"].width = 38
    s.column_dimensions["B"].width = 12
    s.column_dimensions["C"].width = 70

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_summary_html(rows: list[dict[str, Any]], excluded_active: int, seats: E5Seats, now: datetime) -> str:
    candidates = _count(rows, STATUS_DISABLED) + _count(rows, STATUS_NEVER) + _count(rows, STATUS_IDLE_90)
    return (
        f"<p>Weekly SPE_E5 license review as of {now.strftime('%Y-%m-%d')}.</p>"
        f"<p>Seats: <b>{seats.consumed}</b> consumed of <b>{seats.purchased}</b> purchased.</p>"
        "<ul>"
        f"<li>Disabled with license: {_count(rows, STATUS_DISABLED)}</li>"
        f"<li>Enabled, never signed in: {_count(rows, STATUS_NEVER)}</li>"
        f"<li>Enabled, idle &gt;90d: {_count(rows, STATUS_IDLE_90)}</li>"
        f"<li>Enabled, idle 60-90d (watch list): {_count(rows, STATUS_IDLE_60)}</li>"
        "</ul>"
        f"<p>Reclaim candidates (upper bound before mailbox/hold checks): <b>{candidates}</b>. "
        f"{excluded_active} active users excluded.</p>"
        "<p>Sign-in data can lag; treat the attached workbook as leads, not proof.</p>"
    )


_GRAPH = "https://graph.microsoft.com/v1.0"
_USER_SELECT = (
    "id,displayName,userPrincipalName,accountEnabled,createdDateTime,"
    "onPremisesSyncEnabled,assignedLicenses,signInActivity"
)
_MIN_COVERAGE_RATIO = 0.5
_E5_SKU = "SPE_E5"


class E5FetchError(RuntimeError):
    """Raised when Graph data is missing or looks truncated; the report must not be sent."""


def select_e5_users(users: list[dict[str, Any]], sku_id: str) -> list[dict[str, Any]]:
    return [
        u for u in users
        if any(lic.get("skuId") == sku_id for lic in (u.get("assignedLicenses") or []))
    ]


def check_coverage(e5_users: list[dict[str, Any]], seats: E5Seats) -> None:
    if not e5_users:
        raise E5FetchError("No SPE_E5 users returned from Graph")
    if seats.consumed and len(e5_users) < seats.consumed * _MIN_COVERAGE_RATIO:
        raise E5FetchError(
            f"Graph returned {len(e5_users)} E5 users but {seats.consumed} seats are consumed; "
            "treating the fetch as truncated"
        )


async def fetch_e5_data() -> tuple[list[dict[str, Any]], E5Seats]:
    token = await _get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_GRAPH}/subscribedSkus", headers=headers, timeout=60.0)
        resp.raise_for_status()
        sku = next((s for s in resp.json().get("value", []) if s.get("skuPartNumber") == _E5_SKU), None)
        if not sku:
            raise E5FetchError(f"{_E5_SKU} SKU not found in /subscribedSkus")
        seats = E5Seats(
            purchased=int((sku.get("prepaidUnits") or {}).get("enabled") or 0),
            consumed=int(sku.get("consumedUnits") or 0),
        )

        users: list[dict[str, Any]] = []
        url: str | None = f"{_GRAPH}/users?$select={_USER_SELECT}&$top=500"
        while url:
            page = await client.get(url, headers=headers, timeout=120.0)
            page.raise_for_status()
            body = page.json()
            users.extend(body.get("value", []))
            url = body.get("@odata.nextLink")

    e5_users = select_e5_users(users, sku["skuId"])
    check_coverage(e5_users, seats)
    return e5_users, seats
