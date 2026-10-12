# Weekly E5 License Reclaim Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Sunday 13:00 UTC, email the SPE_E5 license reclaim workbook to Grant Allison and Wayne Berry.

**Architecture:** One new module `backend/e5_license_report.py` holds pure bucketing/workbook/summary builders, a Graph fetcher, a tiny run-marker store, and the weekly loop (modeled on `password_expiry_notifier.py`). `email_service.send_email` gains optional attachments. The loop is registered in `main.py` next to the password-expiry notifier (leader-only start path).

**Tech Stack:** Python 3.12, FastAPI lifespan background tasks, httpx, openpyxl 3.1.5, SQLite/Postgres (dual), pytest + pytest-asyncio (`asyncio_mode = auto`).

**Spec:** `docs/superpowers/specs/2026-10-12-weekly-e5-license-report-design.md`

## Global Constraints

- Recipients: `gallison@librasolutionsgroup.com`, `wberry@librasolutionsgroup.com` (configured via `E5_REPORT_RECIPIENTS`, comma-separated; not hardcoded in logic).
- Schedule: Sunday 13:00 UTC (`E5_REPORT_WEEKDAY=6`, `E5_REPORT_HOUR=13`).
- `E5_REPORT_ENABLED` defaults to `false`.
- Read-only: never modify licenses or users.
- Sender: default `it-ai@librasolutionsgroup.com` via existing `send_email`.
- Buckets/labels exactly: `Disabled`, `Enabled - never signed in`, `Enabled - idle >90d`, `Enabled - idle 60-90d`; enabled users with sign-in within 60 days are excluded from the accounts sheet.
- Flag text exactly: `Possible non-person account`.
- Workbook sheets exactly `Summary` and `E5 Accounts`; filename `e5_license_reclaim_candidates_YYYY-MM-DD.xlsx`.
- Every new table needs a numbered file in `backend/storage_migrations/` in the same commit as the SQLite schema (use `SMALLINT` for booleans, `IF NOT EXISTS`).
- Spec amendment: the spec said "no new tables"; the durable already-sent marker requires one small table (`e5_license_report_runs`, migration `0033`) because the repo has no generic key-value store.

## Review Focus

- Truncated/degraded Graph user fetch (fewer E5 users than ~50% of `consumedUnits`): must skip the send, never email a partial report (same failure class as the 2026-07-31 reconcile incident).
- Zero E5 users or `SPE_E5` SKU not found: skip, don't send an empty report.
- User with `signInActivity` null/absent vs. only non-interactive sign-in: latest of the two wins; both null means "never signed in".
- Restart or blue/green cutover on Sunday after the send: marker must prevent a duplicate.
- `send_email` returning False: marker must NOT be written so the next tick retries the same Sunday.
- Display names like "Preston" or "Contessa" must not trip the non-person flag (word-boundary match).

---

### Task 1: send_email attachment support

**Files:**
- Modify: `backend/email_service.py:48-97`
- Test: `backend/tests/test_email_service_attachments.py`

**Interfaces:**
- Produces: `send_email(to, subject, html_body, sender=DEFAULT_SENDER, cc=None, attachments: list[dict] | None = None) -> bool`, where each attachment is `{"name": str, "content_type": str, "content": bytes}`.

- [ ] **Step 1: Write the failing test**

```python
"""send_email attachment payload shape."""
import base64

import email_service


async def test_send_email_includes_file_attachments(monkeypatch):
    monkeypatch.setattr(email_service, "ENTRA_TENANT_ID", "t")
    monkeypatch.setattr(email_service, "ENTRA_CLIENT_ID", "c")
    monkeypatch.setattr(email_service, "ENTRA_CLIENT_SECRET", "s")

    async def fake_token():
        return "tok"

    monkeypatch.setattr(email_service, "_get_access_token", fake_token)
    captured = {}

    class FakeResp:
        status_code = 202
        text = ""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            captured["json"] = json
            return FakeResp()

    monkeypatch.setattr(email_service.httpx, "AsyncClient", lambda: FakeClient())

    ok = await email_service.send_email(
        ["a@example.com"],
        "subj",
        "<p>hi</p>",
        attachments=[{"name": "r.xlsx", "content_type": "application/vnd.ms-excel", "content": b"abc"}],
    )

    assert ok is True
    att = captured["json"]["message"]["attachments"][0]
    assert att["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert att["name"] == "r.xlsx"
    assert att["contentType"] == "application/vnd.ms-excel"
    assert att["contentBytes"] == base64.b64encode(b"abc").decode()


async def test_send_email_without_attachments_has_no_attachments_key(monkeypatch):
    monkeypatch.setattr(email_service, "ENTRA_TENANT_ID", "t")
    monkeypatch.setattr(email_service, "ENTRA_CLIENT_ID", "c")
    monkeypatch.setattr(email_service, "ENTRA_CLIENT_SECRET", "s")

    async def fake_token():
        return "tok"

    monkeypatch.setattr(email_service, "_get_access_token", fake_token)
    captured = {}

    class FakeResp:
        status_code = 202
        text = ""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            captured["json"] = json
            return FakeResp()

    monkeypatch.setattr(email_service.httpx, "AsyncClient", lambda: FakeClient())
    assert await email_service.send_email(["a@example.com"], "s", "<p>x</p>") is True
    assert "attachments" not in captured["json"]["message"]
```

- [ ] **Step 2: Run to verify it fails**

Run (from `backend/`): `pytest tests/test_email_service_attachments.py -v`
Expected: FAIL with `TypeError: send_email() got an unexpected keyword argument 'attachments'`.

- [ ] **Step 3: Implement**

In `backend/email_service.py` add `import base64` to the imports, extend the signature and message build:

```python
async def send_email(
    to: list[str],
    subject: str,
    html_body: str,
    sender: str = DEFAULT_SENDER,
    cc: list[str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> bool:
```

After the `if cc:` block add:

```python
    if attachments:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att["name"],
                "contentType": att["content_type"],
                "contentBytes": base64.b64encode(att["content"]).decode("ascii"),
            }
            for att in attachments
        ]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_email_service_attachments.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/email_service.py backend/tests/test_email_service_attachments.py
git commit -m "feat(email): support file attachments in send_email" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Pure report builders (bucketing, flags, workbook, summary HTML)

**Files:**
- Create: `backend/e5_license_report.py`
- Test: `backend/tests/test_e5_license_report.py`

**Interfaces:**
- Produces (all in `e5_license_report`):
  - `STATUS_DISABLED`, `STATUS_NEVER`, `STATUS_IDLE_90`, `STATUS_IDLE_60` (the exact label strings above)
  - `@dataclass E5Seats(purchased: int, consumed: int)`
  - `classify_user(user: dict, now: datetime) -> dict | None`: `user` is a Graph user dict (`displayName`, `userPrincipalName`, `accountEnabled`, `createdDateTime`, `onPremisesSyncEnabled`, `signInActivity`). Returns `None` for active enabled users (signed in within 60 days), else `{"display_name","upn","enabled","last_sign_in": datetime|None,"days": int|None,"created": datetime|None,"synced": bool,"status": str,"flag": str}`.
  - `build_rows(users: list[dict], now: datetime) -> tuple[list[dict], int]`: classified rows sorted by `(status order, last_sign_in)`, plus the count of excluded active users.
  - `build_workbook(rows: list[dict], excluded_active: int, seats: E5Seats, now: datetime) -> bytes`
  - `build_summary_html(rows: list[dict], excluded_active: int, seats: E5Seats, now: datetime) -> str`

- [ ] **Step 1: Write the failing tests**

```python
"""E5 license report: pure builders."""
import io
from datetime import datetime, timedelta, timezone

from openpyxl import load_workbook

import e5_license_report as r

NOW = datetime(2026, 10, 12, 13, 0, tzinfo=timezone.utc)


def _user(name="Jane Doe", upn="jdoe@movedocs.com", enabled=True, last=None, nonint=None, synced=True):
    sia = {}
    if last is not None:
        sia["lastSignInDateTime"] = (NOW - timedelta(days=last)).isoformat()
    if nonint is not None:
        sia["lastNonInteractiveSignInDateTime"] = (NOW - timedelta(days=nonint)).isoformat()
    return {
        "displayName": name,
        "userPrincipalName": upn,
        "accountEnabled": enabled,
        "createdDateTime": "2024-01-01T00:00:00Z",
        "onPremisesSyncEnabled": synced or None,
        "signInActivity": sia or None,
    }


def test_active_enabled_user_excluded():
    assert r.classify_user(_user(last=10), NOW) is None
    assert r.classify_user(_user(last=60), NOW) is None


def test_buckets():
    assert r.classify_user(_user(enabled=False, last=5), NOW)["status"] == r.STATUS_DISABLED
    assert r.classify_user(_user(), NOW)["status"] == r.STATUS_NEVER
    assert r.classify_user(_user(last=61), NOW)["status"] == r.STATUS_IDLE_60
    assert r.classify_user(_user(last=90), NOW)["status"] == r.STATUS_IDLE_60
    assert r.classify_user(_user(last=91), NOW)["status"] == r.STATUS_IDLE_90


def test_latest_of_interactive_and_noninteractive_wins():
    row = r.classify_user(_user(last=200, nonint=75), NOW)
    assert row["days"] == 75
    assert row["status"] == r.STATUS_IDLE_60


def test_nonperson_flag_uses_word_boundaries():
    assert r.classify_user(_user(name="Conf Room 4", enabled=False), NOW)["flag"] == "Possible non-person account"
    assert r.classify_user(_user(name="Test User", enabled=False), NOW)["flag"] == "Possible non-person account"
    assert r.classify_user(_user(name="Preston Latest", enabled=False), NOW)["flag"] == ""
    assert r.classify_user(_user(name="Contessa Rhodes", enabled=False), NOW)["flag"] == ""


def test_build_rows_counts_excluded_and_sorts():
    users = [_user(last=5), _user(name="A", upn="a@x.com", enabled=False, last=100), _user(name="B", upn="b@x.com")]
    rows, excluded = r.build_rows(users, NOW)
    assert excluded == 1
    assert [x["status"] for x in rows] == [r.STATUS_DISABLED, r.STATUS_NEVER]


def test_workbook_sheets_and_summary_formulas():
    rows, excluded = r.build_rows(
        [_user(enabled=False, last=100), _user(name="B", upn="b@x.com"), _user(name="C", upn="c@x.com", last=95)], NOW
    )
    data = r.build_workbook(rows, excluded, r.E5Seats(975, 965), NOW)
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Summary", "E5 Accounts"]
    acc = wb["E5 Accounts"]
    assert [c.value for c in acc[1]] == [
        "Display Name", "UPN", "Enabled", "Last Sign-In (any)", "Days Since Sign-In",
        "Created", "Synced From AD", "Status", "Flag",
    ]
    assert acc.max_row == 4
    s = wb["Summary"]
    assert s["A4"].value == "Status"
    assert s["B5"].value == "=COUNTIF('E5 Accounts'!$H$2:$H$4,A5)"
    assert s["B9"].value == "=SUM(B5:B8)"
    assert s["B11"].value == "=B5+B6+B7"
    assert s["B13"].value == 975
    assert s["B14"].value == 965


def test_summary_html_mentions_counts_and_seats():
    rows, excluded = r.build_rows([_user(enabled=False, last=100), _user(name="B", upn="b@x.com")], NOW)
    html = r.build_summary_html(rows, excluded, r.E5Seats(975, 965), NOW)
    assert "965" in html and "975" in html
    assert "Disabled" in html and "never signed in" in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_e5_license_report.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'e5_license_report'`.

- [ ] **Step 3: Implement**

Create `backend/e5_license_report.py`:

```python
"""Weekly SPE_E5 license reclaim report: builds the workbook and emails it."""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_e5_license_report.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/e5_license_report.py backend/tests/test_e5_license_report.py
git commit -m "feat(e5-report): classification and workbook builders" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Graph fetch with truncation guard

**Files:**
- Modify: `backend/e5_license_report.py` (append)
- Test: `backend/tests/test_e5_license_report.py` (append)

**Interfaces:**
- Consumes: `email_service._get_access_token() -> str`, `E5Seats`.
- Produces: `class E5FetchError(RuntimeError)`; `async fetch_e5_data() -> tuple[list[dict], E5Seats]` returning only users holding `SPE_E5`; `select_e5_users(users, sku_id) -> list[dict]`; `check_coverage(e5_users, seats)` raising `E5FetchError` when no users or fewer than 50% of `consumedUnits`.

- [ ] **Step 1: Write the failing tests** (append)

```python
import pytest


def test_check_coverage_rejects_empty_and_truncated():
    with pytest.raises(r.E5FetchError):
        r.check_coverage([], r.E5Seats(975, 965))
    with pytest.raises(r.E5FetchError):
        r.check_coverage([{}] * 100, r.E5Seats(975, 965))
    r.check_coverage([{}] * 500, r.E5Seats(975, 965))  # ok, >= 50%


def test_select_e5_users_filters_by_sku():
    users = [
        {"id": "1", "assignedLicenses": [{"skuId": "sku-e5"}]},
        {"id": "2", "assignedLicenses": [{"skuId": "other"}]},
        {"id": "3", "assignedLicenses": []},
    ]
    assert [u["id"] for u in r.select_e5_users(users, "sku-e5")] == ["1"]


async def test_fetch_e5_data_pages_and_returns_seats(monkeypatch):
    async def fake_token():
        return "tok"

    monkeypatch.setattr(r, "_get_access_token", fake_token)
    pages = {
        "https://graph.microsoft.com/v1.0/subscribedSkus": {
            "value": [{"skuPartNumber": "SPE_E5", "skuId": "sku-e5", "consumedUnits": 2,
                       "prepaidUnits": {"enabled": 3}}]
        },
        "u1": {"value": [{"id": "1", "assignedLicenses": [{"skuId": "sku-e5"}]}], "@odata.nextLink": "u2"},
        "u2": {"value": [{"id": "2", "assignedLicenses": [{"skuId": "sku-e5"}]}]},
    }
    calls = []

    class FakeResp:
        def __init__(self, body):
            self._b = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._b

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, timeout=None):
            calls.append(url)
            if "/users" in url:
                return FakeResp(pages["u1"])
            return FakeResp(pages.get(url) or pages[url])

    # route /users first page to u1, nextLink "u2" to second page
    class RoutingClient(FakeClient):
        async def get(self, url, headers=None, timeout=None):
            calls.append(url)
            if url == "u2":
                return FakeResp(pages["u2"])
            if "/users" in url:
                return FakeResp(pages["u1"])
            return FakeResp(pages[url])

    monkeypatch.setattr(r.httpx, "AsyncClient", lambda: RoutingClient())
    users, seats = await r.fetch_e5_data()
    assert [u["id"] for u in users] == ["1", "2"]
    assert (seats.purchased, seats.consumed) == (3, 2)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_e5_license_report.py -v`
Expected: FAIL with `AttributeError: module 'e5_license_report' has no attribute 'E5FetchError'`.

- [ ] **Step 3: Implement** (append; add `import httpx` and `from email_service import _get_access_token` to the imports)

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_e5_license_report.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/e5_license_report.py backend/tests/test_e5_license_report.py
git commit -m "feat(e5-report): Graph fetch with truncation guard" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Run-marker store, weekly job, config, migration, wiring

**Files:**
- Create: `backend/storage_migrations/0033_e5_license_report_runs.sql`
- Modify: `backend/config.py` (after the `SECURITY_DIGEST_HOUR` line, ~346)
- Modify: `backend/e5_license_report.py` (append store + job)
- Modify: `backend/main.py` (import near line 56; start near line 152; stop near line 220)
- Test: `backend/tests/test_e5_license_report_job.py`

**Interfaces:**
- Consumes: `fetch_e5_data`, `build_rows`, `build_workbook`, `build_summary_html`, `email_service.send_email(..., attachments=...)`.
- Produces: `class E5LicenseReportJob(db_path: str | None = None)` with `already_ran(run_date: str) -> bool`, `async run_weekly_job(now: datetime | None = None) -> bool` (True only when sent), `is_due(now) -> bool`, `start_background_runner()`, `stop_background_runner()`; module singleton `e5_license_report_job`.

- [ ] **Step 1: Write the failing tests**

```python
"""E5 license report weekly job."""
from datetime import datetime, timezone

import pytest

import e5_license_report as r

SUNDAY_1300 = datetime(2026, 10, 18, 13, 5, tzinfo=timezone.utc)  # a Sunday
assert SUNDAY_1300.weekday() == 6


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "E5_REPORT_ENABLED", True)
    monkeypatch.setattr(r, "E5_REPORT_RECIPIENTS", ["a@x.com", "b@x.com"])
    monkeypatch.setattr(r, "E5_REPORT_WEEKDAY", 6)
    monkeypatch.setattr(r, "E5_REPORT_HOUR", 13)
    return r.E5LicenseReportJob(db_path=str(tmp_path / "e5.db"))


def _patch_fetch(monkeypatch):
    async def fake_fetch():
        users = [{"displayName": "A", "userPrincipalName": "a@x.com", "accountEnabled": False,
                  "createdDateTime": "2024-01-01T00:00:00Z", "signInActivity": None}] * 500
        return users, r.E5Seats(975, 600)

    monkeypatch.setattr(r, "fetch_e5_data", fake_fetch)


def test_is_due_only_sunday_after_hour(job):
    assert job.is_due(SUNDAY_1300) is True
    assert job.is_due(datetime(2026, 10, 18, 12, 59, tzinfo=timezone.utc)) is False
    assert job.is_due(datetime(2026, 10, 19, 13, 5, tzinfo=timezone.utc)) is False


async def test_sends_once_with_attachment_and_marks_run(job, monkeypatch):
    _patch_fetch(monkeypatch)
    sent = []

    async def fake_send(to, subject, html_body, **kw):
        sent.append((to, subject, kw))
        return True

    monkeypatch.setattr(r, "send_email", fake_send)
    assert await job.run_weekly_job(SUNDAY_1300) is True
    assert await job.run_weekly_job(SUNDAY_1300) is False  # duplicate guard
    assert len(sent) == 1
    to, subject, kw = sent[0]
    assert to == ["a@x.com", "b@x.com"]
    assert kw["attachments"][0]["name"] == "e5_license_reclaim_candidates_2026-10-18.xlsx"
    assert job.already_ran("2026-10-18")


async def test_send_failure_does_not_mark_run(job, monkeypatch):
    _patch_fetch(monkeypatch)

    async def failing_send(*a, **kw):
        return False

    monkeypatch.setattr(r, "send_email", failing_send)
    assert await job.run_weekly_job(SUNDAY_1300) is False
    assert not job.already_ran("2026-10-18")


async def test_fetch_error_skips_send(job, monkeypatch):
    async def bad_fetch():
        raise r.E5FetchError("truncated")

    monkeypatch.setattr(r, "fetch_e5_data", bad_fetch)
    called = []

    async def fake_send(*a, **kw):
        called.append(1)
        return True

    monkeypatch.setattr(r, "send_email", fake_send)
    assert await job.run_weekly_job(SUNDAY_1300) is False
    assert called == []
    assert not job.already_ran("2026-10-18")


async def test_disabled_does_nothing(job, monkeypatch):
    monkeypatch.setattr(r, "E5_REPORT_ENABLED", False)
    _patch_fetch(monkeypatch)
    assert await job.run_weekly_job(SUNDAY_1300) is False
    assert not job.already_ran("2026-10-18")


def test_config_defaults(monkeypatch):
    import importlib
    import config

    for k in ("E5_REPORT_ENABLED", "E5_REPORT_RECIPIENTS", "E5_REPORT_WEEKDAY", "E5_REPORT_HOUR"):
        monkeypatch.delenv(k, raising=False)
    cfg = importlib.reload(config)
    assert cfg.E5_REPORT_ENABLED is False
    assert cfg.E5_REPORT_WEEKDAY == 6
    assert cfg.E5_REPORT_HOUR == 13
    assert cfg.E5_REPORT_RECIPIENTS == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_e5_license_report_job.py -v`
Expected: FAIL (`E5LicenseReportJob` missing / config vars missing).

- [ ] **Step 3: Implement**

Migration `backend/storage_migrations/0033_e5_license_report_runs.sql`:

```sql
CREATE TABLE IF NOT EXISTS e5_license_report_runs (
    run_date    TEXT PRIMARY KEY,
    sent_at     TEXT NOT NULL,
    recipients  TEXT NOT NULL DEFAULT '',
    row_count   INTEGER NOT NULL DEFAULT 0
);
```

`backend/config.py` after `SECURITY_DIGEST_HOUR`:

```python
E5_REPORT_ENABLED: bool = os.getenv("E5_REPORT_ENABLED", "false").lower() == "true"
E5_REPORT_RECIPIENTS: list[str] = [
    a.strip() for a in os.getenv("E5_REPORT_RECIPIENTS", "").split(",") if a.strip()
]
E5_REPORT_WEEKDAY: int = int(os.getenv("E5_REPORT_WEEKDAY", "6"))  # Monday=0 ... Sunday=6
E5_REPORT_HOUR: int = int(os.getenv("E5_REPORT_HOUR", "13"))  # UTC
```

Append to `backend/e5_license_report.py` (add imports `asyncio, os, sqlite3, threading`, `from config import DATA_DIR, E5_REPORT_ENABLED, E5_REPORT_RECIPIENTS, E5_REPORT_WEEKDAY, E5_REPORT_HOUR`, `from email_service import send_email`, `from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled`, `from sqlite_utils import connect_sqlite`):

```python
_DB_PATH = os.path.join(DATA_DIR, "e5_license_report.db")
_POLL_SECONDS = 900


class E5LicenseReportJob:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._bg_task: asyncio.Task[None] | None = None
        self._init_db()

    def _ph(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _conn(self):
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return connect_sqlite(self._db_path)

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            return
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS e5_license_report_runs (
                    run_date    TEXT PRIMARY KEY,
                    sent_at     TEXT NOT NULL,
                    recipients  TEXT NOT NULL DEFAULT '',
                    row_count   INTEGER NOT NULL DEFAULT 0
                )"""
            )

    def already_ran(self, run_date: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT 1 FROM e5_license_report_runs WHERE run_date = {self._ph()}", (run_date,)
            ).fetchone()
        return row is not None

    def _record_run(self, run_date: str, recipients: list[str], row_count: int) -> None:
        ph = self._ph()
        with self._conn() as conn:
            conn.execute(
                f"""INSERT INTO e5_license_report_runs (run_date, sent_at, recipients, row_count)
                    VALUES ({ph},{ph},{ph},{ph})
                    ON CONFLICT (run_date) DO NOTHING""",
                (run_date, datetime.now(timezone.utc).isoformat(), ",".join(recipients), row_count),
            )

    def is_due(self, now: datetime) -> bool:
        return now.weekday() == E5_REPORT_WEEKDAY and now.hour >= E5_REPORT_HOUR

    async def run_weekly_job(self, now: datetime | None = None) -> bool:
        """Build and send the report. True only when an email was actually sent."""
        if not E5_REPORT_ENABLED or not E5_REPORT_RECIPIENTS:
            return False
        now = now or datetime.now(timezone.utc)
        run_date = now.strftime("%Y-%m-%d")
        if self.already_ran(run_date):
            return False
        try:
            users, seats = await fetch_e5_data()
        except Exception:
            logger.exception("E5 license report: Graph fetch failed; skipping send")
            return False
        rows, excluded = build_rows(users, now)
        attachment = {
            "name": f"e5_license_reclaim_candidates_{run_date}.xlsx",
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "content": build_workbook(rows, excluded, seats, now),
        }
        ok = await send_email(
            list(E5_REPORT_RECIPIENTS),
            f"Weekly E5 license reclaim report - {run_date}",
            build_summary_html(rows, excluded, seats, now),
            attachments=[attachment],
        )
        if not ok:
            logger.error("E5 license report: send_email failed; will retry next tick")
            return False
        self._record_run(run_date, E5_REPORT_RECIPIENTS, len(rows))
        logger.info("E5 license report sent to %s (%d rows)", E5_REPORT_RECIPIENTS, len(rows))
        return True

    def start_background_runner(self) -> None:
        self._bg_task = asyncio.get_event_loop().create_task(self._run_loop())

    def stop_background_runner(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()

    async def _run_loop(self) -> None:
        while True:
            try:
                now = datetime.now(timezone.utc)
                if self.is_due(now):
                    await self.run_weekly_job(now)
                await asyncio.sleep(_POLL_SECONDS)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("E5 license report loop error")
                await asyncio.sleep(300)


e5_license_report_job = E5LicenseReportJob()
```

`backend/main.py`: add `from e5_license_report import e5_license_report_job as _e5_license_report_job` beside the password-expiry import (~line 56); add after the password-expiry start block (~line 154):

```python
    try:
        _e5_license_report_job.start_background_runner()
    except Exception:
        logger.exception("Failed to start E5 license report job")
```

and `_e5_license_report_job.stop_background_runner()` beside line 220's password-expiry stop.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_e5_license_report.py tests/test_e5_license_report_job.py tests/test_email_service_attachments.py -v`
Expected: all pass. Then `python -c "import main"` from `backend/` to confirm the app still imports.

- [ ] **Step 5: Commit**

```bash
git add backend/storage_migrations/0033_e5_license_report_runs.sql backend/config.py backend/e5_license_report.py backend/main.py backend/tests/test_e5_license_report_job.py
git commit -m "feat(e5-report): weekly Sunday email job with duplicate-send guard" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Docs and rollout

**Files:**
- Modify: `CLAUDE.md` (Operational Invariants, new short bullet under a "Reporting" entry)
- Modify: `backend/.env` and `docker-compose.yml` env passthrough if other `SECURITY_DIGEST_*` vars are listed there (grep first)
- Modify: spec: replace "No new tables" line with the `e5_license_report_runs` note.

- [ ] **Step 1:** `grep -n "SECURITY_DIGEST_HOUR" docker-compose.yml backend/.env* .env* 2>/dev/null` and add `E5_REPORT_ENABLED`, `E5_REPORT_RECIPIENTS`, `E5_REPORT_WEEKDAY`, `E5_REPORT_HOUR` wherever it appears.
- [ ] **Step 2:** Add to CLAUDE.md Reporting section: weekly E5 report module, schedule, `E5_REPORT_ENABLED` default off, the truncation guard (skip rather than send partial), marker semantics (written only after a successful send).
- [ ] **Step 3:** Fix the spec's "No new tables" sentence.
- [ ] **Step 4:** Run `./scripts/check_repo_hygiene.sh`; expected pass.
- [ ] **Step 5:** Commit docs.

```bash
git add CLAUDE.md docs/ docker-compose.yml
git commit -m "docs: document weekly E5 license report" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6 (rollout, after approval to deploy):** set `E5_REPORT_ENABLED=true` and `E5_REPORT_RECIPIENTS=gallison@librasolutionsgroup.com,wberry@librasolutionsgroup.com` in the deployed env, deploy via `./deploy.sh`, and verify the Graph app registration has `AuditLog.Read.All` (needed for `signInActivity`) by running a one-off `await e5_license_report_job.run_weekly_job()` against a test recipient first.
