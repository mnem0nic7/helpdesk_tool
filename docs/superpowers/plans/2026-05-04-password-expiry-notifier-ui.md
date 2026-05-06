# Password Expiry Notifier UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/password-expiry` page to the primary (it-app) site with a DB-backed toggle, run history, and per-user notification log.

**Architecture:** A new `routes_password_expiry_notifier.py` serves four read endpoints (status, runs, notifications) and one admin-only PATCH settings endpoint. The notifier's daily job reads its enabled state from a new `password_expiry_notifier_settings` DB table instead of the fixed env var, so the toggle takes effect on the next run without restarting the backend. The frontend page uses two React Query queries (one per tab) plus a useMutation for the toggle.

**Tech Stack:** FastAPI, SQLite/Postgres (existing dual-write pattern), React 19, React Query 5, Tailwind CSS 4, Vitest

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `backend/storage_migrations/0025_password_expiry_notifier_settings.sql` | Settings table (single row) |
| Modify | `backend/password_expiry_notifier.py` | Add `_get_notify_enabled()` + settings DDL; use it in `run_daily_job()` |
| Create | `backend/routes_password_expiry_notifier.py` | GET status, GET runs, GET notifications, PATCH settings |
| Modify | `backend/main.py` | Import + register new router |
| Create | `backend/tests/test_routes_password_expiry_notifier.py` | 6 route tests |
| Modify | `frontend/src/lib/api.ts` | 3 new interfaces + 4 API functions |
| Modify | `frontend/src/components/Layout.tsx` | "Pwd Expiry" nav item |
| Modify | `frontend/src/App.tsx` | Lazy import + `/password-expiry` route |
| Create | `frontend/src/pages/PasswordExpiryNotifierPage.tsx` | Full page component |
| Create | `frontend/src/__tests__/PasswordExpiryNotifierPage.test.tsx` | 5 Vitest tests |

---

## Task 1: SQL Migration

**Files:**
- Create: `backend/storage_migrations/0025_password_expiry_notifier_settings.sql`

- [ ] **Step 1: Create the migration file**

```sql
CREATE TABLE IF NOT EXISTS password_expiry_notifier_settings (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    enabled     SMALLINT NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL DEFAULT ''
);
```

- [ ] **Step 2: Verify it exists**

```bash
ls backend/storage_migrations/0025_password_expiry_notifier_settings.sql
```

Expected: file path printed, no error.

- [ ] **Step 3: Commit**

```bash
git add backend/storage_migrations/0025_password_expiry_notifier_settings.sql
git commit -m "feat: add password expiry notifier settings table (migration 0025)"
```

---

## Task 2: DB-backed enabled check in the notifier

**Files:**
- Modify: `backend/password_expiry_notifier.py`
- Modify: `backend/tests/test_password_expiry_notifier.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_password_expiry_notifier.py`:

```python
def test_get_notify_enabled_db_row_present(tmp_path):
    n = _make_notifier(str(tmp_path))
    with n._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO password_expiry_notifier_settings (id, enabled, updated_at, updated_by) VALUES (1, 1, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), "admin@example.com"),
        )
    assert n._get_notify_enabled() is True


def test_get_notify_enabled_db_row_absent(tmp_path):
    # No DB row → falls back to self._notify_enabled which defaults to False
    n = _make_notifier(str(tmp_path))
    assert n._get_notify_enabled() is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python3 -m pytest tests/test_password_expiry_notifier.py -k "get_notify_enabled" -v
```

Expected: `FAILED` — `AttributeError: 'PasswordExpiryNotifier' object has no attribute '_get_notify_enabled'`

- [ ] **Step 3: Add settings DDL to `_init_db()` and add `_get_notify_enabled()`**

In `backend/password_expiry_notifier.py`, inside `_init_db()`, after the last `conn.execute(...)` block (the one creating `password_expiry_notify_runs`), append:

```python
            conn.execute("""
                CREATE TABLE IF NOT EXISTS password_expiry_notifier_settings (
                    id          INTEGER PRIMARY KEY DEFAULT 1,
                    enabled     SMALLINT NOT NULL DEFAULT 0,
                    updated_at  TEXT NOT NULL DEFAULT '',
                    updated_by  TEXT NOT NULL DEFAULT ''
                )
            """)
```

Then add this method to `PasswordExpiryNotifier` after `_record_run`:

```python
    def _get_notify_enabled(self) -> bool:
        """Read enabled from DB settings row; fall back to env-var default."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT enabled FROM password_expiry_notifier_settings WHERE id = 1"
            ).fetchone()
        return bool(row["enabled"]) if row is not None else self._notify_enabled
```

- [ ] **Step 4: Update `run_daily_job()` to use `_get_notify_enabled()`**

Replace the entire `run_daily_job` method body in `backend/password_expiry_notifier.py` with:

```python
    async def run_daily_job(self) -> None:
        import ad_client as ad
        import email_service

        loop = asyncio.get_event_loop()

        with self._conn() as conn:
            if self._already_ran_today(conn):
                return

        notify_enabled = self._get_notify_enabled()

        logger.info(
            "Password expiry notifier: starting daily job (test_mode=%s)",
            not notify_enabled,
        )

        try:
            result = await loop.run_in_executor(
                None,
                lambda: ad.search_users(page=1, limit=10000),
            )
        except Exception:
            logger.exception("Password expiry notifier: failed to fetch AD users")
            return

        users = result.get("items", [])
        notified = 0

        for user in users:
            sam = user.get("sam_account_name", "")
            email = user.get("email", "")
            display_name = user.get("display_name", "")

            days = _should_notify(
                user,
                max_age_days=AD_MAX_PWD_AGE_DAYS,
                days_before=PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE,
            )
            if days is None:
                continue

            with self._conn() as conn:
                if self._already_notified_today(sam, conn):
                    continue

            last_set = datetime.fromisoformat(user["pwd_last_set"]).replace(tzinfo=timezone.utc)
            expiry_date = (last_set + timedelta(days=AD_MAX_PWD_AGE_DAYS)).date().isoformat()

            if not notify_enabled:
                logger.info(
                    "[TEST MODE] Would notify %s <%s> — password expires in %d day(s) on %s",
                    sam, email, days, expiry_date,
                )
            else:
                subject = f"Your password expires in {days} day(s) — action required"
                body = _build_email_body(display_name, days, expiry_date)
                sent = await email_service.send_email(to=[email], subject=subject, html_body=body)
                if not sent:
                    logger.error("Password expiry notifier: failed to send email to %s", email)
                    continue

            with self._conn() as conn:
                self._record_notification(
                    sam=sam,
                    email=email,
                    expiry_date=expiry_date,
                    days=days,
                    test_mode=not notify_enabled,
                    conn=conn,
                )
            notified += 1

        with self._conn() as conn:
            self._record_run(
                users_notified=notified,
                test_mode=not notify_enabled,
                conn=conn,
            )

        logger.info(
            "Password expiry notifier: daily job complete — %d user(s) notified (test_mode=%s)",
            notified,
            not notify_enabled,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/test_password_expiry_notifier.py -v
```

Expected: all 18 tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend/password_expiry_notifier.py backend/tests/test_password_expiry_notifier.py
git commit -m "feat: read notifier enabled state from DB at each daily job run"
```

---

## Task 3: Backend API routes

**Files:**
- Create: `backend/routes_password_expiry_notifier.py`
- Create: `backend/tests/test_routes_password_expiry_notifier.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_routes_password_expiry_notifier.py`:

```python
"""Tests for password expiry notifier API routes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def test_get_status_no_db_row(test_client, monkeypatch, tmp_path):
    """GET /status returns enabled=False and null last_run when no rows exist."""
    import password_expiry_notifier as pen_module

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    resp = test_client.get("/api/password-expiry-notifier/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["last_run"] is None
    assert data["config"]["max_age_days"] == 90
    assert data["config"]["days_before"] == 14


def test_get_status_with_db_row(test_client, monkeypatch, tmp_path):
    """GET /status returns enabled=True when DB settings row has enabled=1."""
    import password_expiry_notifier as pen_module

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    with notifier._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO password_expiry_notifier_settings (id, enabled, updated_at, updated_by) VALUES (1, 1, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), "admin@example.com"),
        )
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    resp = test_client.get("/api/password-expiry-notifier/status")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


def test_get_runs_pagination(test_client, monkeypatch, tmp_path):
    """GET /runs returns rows newest-first with correct total."""
    import password_expiry_notifier as pen_module

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    with notifier._sqlite_conn() as conn:
        for date in ["2026-05-01", "2026-05-02", "2026-05-03"]:
            conn.execute(
                "INSERT INTO password_expiry_notify_runs (run_date, ran_at, users_notified, test_mode) VALUES (?, ?, ?, ?)",
                (date, f"{date}T02:00:00+00:00", 5, 1),
            )
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    resp = test_client.get("/api/password-expiry-notifier/runs?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["items"][0]["run_date"] == "2026-05-03"  # newest first


def test_get_notifications_pagination(test_client, monkeypatch, tmp_path):
    """GET /notifications returns rows newest-first with correct total."""
    import password_expiry_notifier as pen_module

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    with notifier._sqlite_conn() as conn:
        for i, ts in enumerate(["2026-05-01T02:00:00+00:00", "2026-05-02T02:00:00+00:00"]):
            conn.execute(
                "INSERT INTO password_expiry_notifications "
                "(id, sam_account_name, email, expiry_date, days_until_expiry, notified_at, test_mode) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, f"user{i}", f"user{i}@corp.com", "2026-06-01", 10 - i, ts, 1),
            )
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    resp = test_client.get("/api/password-expiry-notifier/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["items"][0]["notified_at"] == "2026-05-02T02:00:00+00:00"  # newest first


def test_patch_settings_admin(test_client, monkeypatch, tmp_path):
    """PATCH /settings with admin session enables the notifier."""
    import password_expiry_notifier as pen_module

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    resp = test_client.patch("/api/password-expiry-notifier/settings", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


def test_patch_settings_non_admin_forbidden(test_client, monkeypatch, tmp_path):
    """PATCH /settings with non-admin session returns 403."""
    import password_expiry_notifier as pen_module
    from auth import create_session

    notifier = pen_module.PasswordExpiryNotifier(db_path=str(tmp_path / "pen.db"))
    import routes_password_expiry_notifier
    monkeypatch.setattr(routes_password_expiry_notifier, "password_expiry_notifier", notifier)

    # atlassian provider + explicit is_admin=False bypasses the always-True shortcut
    non_admin_sid = create_session(
        "non-admin@example.com", "Non Admin",
        auth_provider="atlassian",
        is_admin=False,
    )
    test_client.cookies.set("session_id", non_admin_sid)
    try:
        resp = test_client.patch("/api/password-expiry-notifier/settings", json={"enabled": True})
        assert resp.status_code == 403
    finally:
        # Restore admin session for other tests
        from auth import create_session as cs
        test_client.cookies.set("session_id", cs("test@example.com", "Test User"))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python3 -m pytest tests/test_routes_password_expiry_notifier.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'routes_password_expiry_notifier'`

- [ ] **Step 3: Create `backend/routes_password_expiry_notifier.py`**

```python
"""FastAPI routes for the password expiry notifier."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_admin, require_authenticated_user
from config import AD_MAX_PWD_AGE_DAYS, PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE
from password_expiry_notifier import password_expiry_notifier

router = APIRouter(prefix="/api/password-expiry-notifier", tags=["password-expiry-notifier"])


class PatchSettingsRequest(BaseModel):
    enabled: bool


def _last_run(notifier) -> dict[str, Any] | None:
    with notifier._conn() as conn:
        row = conn.execute(
            "SELECT run_date, ran_at, users_notified, test_mode "
            "FROM password_expiry_notify_runs ORDER BY run_date DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row is not None else None


def _status_payload(notifier) -> dict[str, Any]:
    return {
        "enabled": notifier._get_notify_enabled(),
        "last_run": _last_run(notifier),
        "config": {
            "max_age_days": AD_MAX_PWD_AGE_DAYS,
            "days_before": PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE,
        },
    }


@router.get("/status", dependencies=[Depends(require_authenticated_user)])
async def get_status() -> dict[str, Any]:
    return _status_payload(password_expiry_notifier)


@router.get("/runs", dependencies=[Depends(require_authenticated_user)])
async def get_runs(limit: int = 30, offset: int = 0) -> dict[str, Any]:
    limit = min(limit, 100)
    with password_expiry_notifier._conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM password_expiry_notify_runs"
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT run_date, ran_at, users_notified, test_mode "
            "FROM password_expiry_notify_runs ORDER BY run_date DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.get("/notifications", dependencies=[Depends(require_authenticated_user)])
async def get_notifications(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit = min(limit, 100)
    with password_expiry_notifier._conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM password_expiry_notifications"
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT id, sam_account_name, email, expiry_date, days_until_expiry, notified_at, test_mode "
            "FROM password_expiry_notifications ORDER BY notified_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.patch("/settings")
async def patch_settings(
    body: PatchSettingsRequest,
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    updated_at = datetime.now(timezone.utc).isoformat()
    updated_by = user.get("email") or user.get("name") or "unknown"
    ph = password_expiry_notifier._placeholder()
    with password_expiry_notifier._conn() as conn:
        conn.execute(
            f"INSERT INTO password_expiry_notifier_settings (id, enabled, updated_at, updated_by) "
            f"VALUES (1, {ph}, {ph}, {ph}) "
            f"ON CONFLICT (id) DO UPDATE SET "
            f"enabled = excluded.enabled, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (1 if body.enabled else 0, updated_at, updated_by),
        )
    return _status_payload(password_expiry_notifier)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/test_routes_password_expiry_notifier.py -v
```

Expected: all 6 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/routes_password_expiry_notifier.py backend/tests/test_routes_password_expiry_notifier.py
git commit -m "feat: add password expiry notifier API routes with tests"
```

---

## Task 4: Register router in main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add the import**

In `backend/main.py`, after line 50 (`from routes_deactivation_schedule import router as deactivation_schedule_router`), add:

```python
from routes_password_expiry_notifier import router as password_expiry_notifier_router
```

- [ ] **Step 2: Register the router**

In `backend/main.py`, after line 461 (`app.include_router(deactivation_schedule_router)`), add:

```python
app.include_router(password_expiry_notifier_router)
```

- [ ] **Step 3: Verify backend starts cleanly**

```bash
cd backend && python3 -c "import main; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: register password expiry notifier router in main.py"
```

---

## Task 5: Frontend types + API functions

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add interfaces**

In `frontend/src/lib/api.ts`, after the `SecurityLaneAISummary` interface (at the very end of the interface definitions, before the `export default` or the last closing of the `api` object), add:

```typescript
export interface PasswordExpiryStatus {
  enabled: boolean;
  last_run: {
    run_date: string;
    ran_at: string;
    users_notified: number;
    test_mode: number;
  } | null;
  config: {
    max_age_days: number;
    days_before: number;
  };
}

export interface PasswordExpiryRun {
  run_date: string;
  ran_at: string;
  users_notified: number;
  test_mode: number;
}

export interface PasswordExpiryNotification {
  id: string;
  sam_account_name: string;
  email: string;
  expiry_date: string;
  days_until_expiry: number;
  notified_at: string;
  test_mode: number;
}
```

- [ ] **Step 2: Add API functions**

In `frontend/src/lib/api.ts`, inside the `api` object (after the last function before the closing `}`), add:

```typescript
  getPasswordExpiryStatus(): Promise<PasswordExpiryStatus> {
    return fetchJSON<PasswordExpiryStatus>("/api/password-expiry-notifier/status");
  },

  getPasswordExpiryRuns(
    limit = 30,
    offset = 0
  ): Promise<{ items: PasswordExpiryRun[]; total: number }> {
    return fetchJSON(`/api/password-expiry-notifier/runs?limit=${limit}&offset=${offset}`);
  },

  getPasswordExpiryNotifications(
    limit = 50,
    offset = 0
  ): Promise<{ items: PasswordExpiryNotification[]; total: number }> {
    return fetchJSON(`/api/password-expiry-notifier/notifications?limit=${limit}&offset=${offset}`);
  },

  async patchPasswordExpirySettings(enabled: boolean): Promise<PasswordExpiryStatus> {
    const res = await fetch("/api/password-expiry-notifier/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    if (res.status === 401) {
      window.location.href = "/api/auth/login";
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      throw new Error(await buildErrorMessage("PATCH", "/api/password-expiry-notifier/settings", res));
    }
    return res.json() as Promise<PasswordExpiryStatus>;
  },
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: build completes without TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add password expiry notifier API types and functions"
```

---

## Task 6: Nav item and route

**Files:**
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add nav item to Layout.tsx**

In `frontend/src/components/Layout.tsx`, after line 33 (`{ to: "/active-directory", label: "Active Directory", icon: "▦", primaryOnly: true },`), add:

```typescript
  { to: "/password-expiry", label: "Pwd Expiry", icon: "⏰", primaryOnly: true },
```

- [ ] **Step 2: Add lazy import to App.tsx**

In `frontend/src/App.tsx`, after line 47 (`const ADManagementPage = lazy(() => import("./pages/ADManagementPage"));`), add:

```typescript
const PasswordExpiryNotifierPage = lazy(() => import("./pages/PasswordExpiryNotifierPage"));
```

- [ ] **Step 3: Add route to App.tsx**

In `frontend/src/App.tsx`, after line 133 (`{branding.scope === "primary" ? <Route path="active-directory" element={<ADManagementPage />} /> : null}`), add:

```tsx
                {branding.scope === "primary" ? <Route path="password-expiry" element={<PasswordExpiryNotifierPage />} /> : null}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: build completes. (The page import will fail until Task 7 creates the file — skip this step until after Task 7 if preferred.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout.tsx frontend/src/App.tsx
git commit -m "feat: add Pwd Expiry nav item and route"
```

---

## Task 7: PasswordExpiryNotifierPage component + tests

**Files:**
- Create: `frontend/src/pages/PasswordExpiryNotifierPage.tsx`
- Create: `frontend/src/__tests__/PasswordExpiryNotifierPage.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/__tests__/PasswordExpiryNotifierPage.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import PasswordExpiryNotifierPage from "../pages/PasswordExpiryNotifierPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getMe: vi.fn(),
    getPasswordExpiryStatus: vi.fn(),
    getPasswordExpiryRuns: vi.fn(),
    getPasswordExpiryNotifications: vi.fn(),
    patchPasswordExpirySettings: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({ api: mockApi, default: mockApi }));

const baseStatus = {
  enabled: false,
  last_run: null,
  config: { max_age_days: 90, days_before: 14 },
};

const adminMe = { email: "admin@corp.com", name: "Admin", is_admin: true };
const staffMe = { email: "staff@corp.com", name: "Staff", is_admin: false };

beforeEach(() => {
  mockApi.getMe.mockResolvedValue(adminMe);
  mockApi.getPasswordExpiryStatus.mockResolvedValue(baseStatus);
  mockApi.getPasswordExpiryRuns.mockResolvedValue({ items: [], total: 0 });
  mockApi.getPasswordExpiryNotifications.mockResolvedValue({ items: [], total: 0 });
});

describe("PasswordExpiryNotifierPage", () => {
  it("shows TEST badge when enabled=false", async () => {
    render(<PasswordExpiryNotifierPage />);
    await waitFor(() => expect(screen.getByText("TEST")).toBeInTheDocument());
  });

  it("shows LIVE badge when enabled=true", async () => {
    mockApi.getPasswordExpiryStatus.mockResolvedValue({ ...baseStatus, enabled: true });
    render(<PasswordExpiryNotifierPage />);
    await waitFor(() => expect(screen.getByText("LIVE")).toBeInTheDocument());
  });

  it("toggle is disabled for non-admin users", async () => {
    mockApi.getMe.mockResolvedValue(staffMe);
    render(<PasswordExpiryNotifierPage />);
    await waitFor(() => screen.getByRole("switch", { name: /enable live emails/i }));
    const toggle = screen.getByRole("switch", { name: /enable live emails/i });
    expect(toggle).toBeDisabled();
  });

  it("toggle is enabled for admin users", async () => {
    render(<PasswordExpiryNotifierPage />);
    await waitFor(() => screen.getByRole("switch", { name: /enable live emails/i }));
    expect(screen.getByRole("switch", { name: /enable live emails/i })).not.toBeDisabled();
  });

  it("clicking Notification Log tab shows the notifications table", async () => {
    const user = userEvent.setup();
    render(<PasswordExpiryNotifierPage />);
    await waitFor(() => screen.getByText("Notification Log"));
    await user.click(screen.getByText("Notification Log"));
    await waitFor(() => expect(mockApi.getPasswordExpiryNotifications).toHaveBeenCalled());
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && npm run test:run -- PasswordExpiryNotifierPage 2>&1 | tail -15
```

Expected: `FAILED` — cannot find module `../pages/PasswordExpiryNotifierPage.tsx`

- [ ] **Step 3: Create `frontend/src/pages/PasswordExpiryNotifierPage.tsx`**

```tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, {
  type PasswordExpiryStatus,
  type PasswordExpiryRun,
  type PasswordExpiryNotification,
} from "../lib/api.ts";

type Tab = "runs" | "notifications";

const RUNS_PAGE_SIZE = 30;
const NOTIF_PAGE_SIZE = 50;

function ModeBadge({ testMode }: { testMode: number }) {
  return testMode === 0 ? (
    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
      LIVE
    </span>
  ) : (
    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
      TEST
    </span>
  );
}

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.ceil(total / pageSize);
  if (pages <= 1) return null;
  return (
    <div className="mt-3 flex items-center gap-2 text-sm text-slate-500">
      <button
        disabled={page === 0}
        onClick={() => onPage(page - 1)}
        className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40"
      >
        ‹ Prev
      </button>
      <span>
        Page {page + 1} of {pages}
      </span>
      <button
        disabled={page >= pages - 1}
        onClick={() => onPage(page + 1)}
        className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40"
      >
        Next ›
      </button>
    </div>
  );
}

function RunsTable({
  data,
  isLoading,
  error,
  page,
  onPage,
}: {
  data: { items: PasswordExpiryRun[]; total: number } | undefined;
  isLoading: boolean;
  error: Error | null;
  page: number;
  onPage: (p: number) => void;
}) {
  if (isLoading) {
    return <div className="py-12 text-center text-sm text-slate-400">Loading…</div>;
  }
  if (error) {
    return <p className="text-sm text-red-600">Failed to load runs: {String(error)}</p>;
  }
  const items = data?.items ?? [];
  return (
    <>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
            <th className="pb-2 pr-4">Date</th>
            <th className="pb-2 pr-4">Ran At (UTC)</th>
            <th className="pb-2 pr-4">Users Notified</th>
            <th className="pb-2">Mode</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={4} className="py-8 text-center text-sm text-slate-400">
                No runs recorded yet.
              </td>
            </tr>
          ) : (
            items.map((row) => (
              <tr key={row.run_date} className="border-b border-slate-100">
                <td className="py-2 pr-4 font-mono text-xs">{row.run_date}</td>
                <td className="py-2 pr-4 text-xs text-slate-500">{fmt(row.ran_at)}</td>
                <td className="py-2 pr-4 font-medium">{row.users_notified}</td>
                <td className="py-2">
                  <ModeBadge testMode={row.test_mode} />
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
      <Pager page={page} pageSize={RUNS_PAGE_SIZE} total={data?.total ?? 0} onPage={onPage} />
    </>
  );
}

function NotificationsTable({
  data,
  isLoading,
  error,
  page,
  onPage,
}: {
  data: { items: PasswordExpiryNotification[]; total: number } | undefined;
  isLoading: boolean;
  error: Error | null;
  page: number;
  onPage: (p: number) => void;
}) {
  if (isLoading) {
    return <div className="py-12 text-center text-sm text-slate-400">Loading…</div>;
  }
  if (error) {
    return <p className="text-sm text-red-600">Failed to load notifications: {String(error)}</p>;
  }
  const items = data?.items ?? [];
  return (
    <>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
            <th className="pb-2 pr-4">User (SAM)</th>
            <th className="pb-2 pr-4">Email</th>
            <th className="pb-2 pr-4">Expiry Date</th>
            <th className="pb-2 pr-4">Days</th>
            <th className="pb-2 pr-4">Notified At</th>
            <th className="pb-2">Mode</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={6} className="py-8 text-center text-sm text-slate-400">
                No notifications recorded yet.
              </td>
            </tr>
          ) : (
            items.map((row) => (
              <tr key={row.id} className="border-b border-slate-100">
                <td className="py-2 pr-4 font-mono text-xs">{row.sam_account_name}</td>
                <td className="py-2 pr-4 text-xs text-slate-600">{row.email}</td>
                <td className="py-2 pr-4 font-mono text-xs">{row.expiry_date}</td>
                <td className="py-2 pr-4 font-medium">{row.days_until_expiry}</td>
                <td className="py-2 pr-4 text-xs text-slate-500">{fmt(row.notified_at)}</td>
                <td className="py-2">
                  <ModeBadge testMode={row.test_mode} />
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
      <Pager
        page={page}
        pageSize={NOTIF_PAGE_SIZE}
        total={data?.total ?? 0}
        onPage={onPage}
      />
    </>
  );
}

export default function PasswordExpiryNotifierPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("runs");
  const [runsPage, setRunsPage] = useState(0);
  const [notifPage, setNotifPage] = useState(0);

  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.getMe(),
    staleTime: 5 * 60 * 1000,
  });
  const isAdmin = !!meQuery.data?.is_admin;

  const statusQuery = useQuery<PasswordExpiryStatus>({
    queryKey: ["password-expiry", "status"],
    queryFn: () => api.getPasswordExpiryStatus(),
  });

  const runsQuery = useQuery({
    queryKey: ["password-expiry", "runs", runsPage],
    queryFn: () => api.getPasswordExpiryRuns(RUNS_PAGE_SIZE, runsPage * RUNS_PAGE_SIZE),
    enabled: tab === "runs",
  });

  const notifQuery = useQuery({
    queryKey: ["password-expiry", "notifications", notifPage],
    queryFn: () =>
      api.getPasswordExpiryNotifications(NOTIF_PAGE_SIZE, notifPage * NOTIF_PAGE_SIZE),
    enabled: tab === "notifications",
  });

  const toggleMut = useMutation({
    mutationFn: (enabled: boolean) => api.patchPasswordExpirySettings(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["password-expiry", "status"] }),
  });

  const status = statusQuery.data;
  const enabled = status?.enabled ?? false;

  function handleRefresh() {
    qc.invalidateQueries({ queryKey: ["password-expiry"] });
  }

  return (
    <div className="p-6 max-w-5xl">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">Password Expiry Notifier</h1>
          <p className="text-sm text-slate-500">Daily notifications for expiring AD passwords</p>
        </div>
        <button
          onClick={handleRefresh}
          className="rounded border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
        >
          Refresh
        </button>
      </div>

      {statusQuery.error && (
        <p className="mb-4 text-sm text-red-600">
          Failed to load status: {String(statusQuery.error)}
        </p>
      )}

      {/* Status bar */}
      <div className="mb-6 flex flex-wrap items-center gap-4 rounded-lg border border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">Live emails</span>
          <button
            role="switch"
            aria-checked={enabled}
            aria-label="Enable live emails"
            disabled={!isAdmin || toggleMut.isPending}
            title={!isAdmin ? "Admin access required" : undefined}
            onClick={() => toggleMut.mutate(!enabled)}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
              enabled ? "bg-emerald-500" : "bg-slate-300"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                enabled ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
          <ModeBadge testMode={enabled ? 0 : 1} />
        </div>

        <div className="h-4 w-px bg-slate-200" />

        <div className="text-sm text-slate-600">
          {status ? (
            status.last_run ? (
              <>
                Last run: <strong>{status.last_run.run_date}</strong> ·{" "}
                <strong>{status.last_run.users_notified}</strong> notified
              </>
            ) : (
              "No runs yet"
            )
          ) : (
            "Loading…"
          )}
        </div>

        {status && (
          <>
            <div className="h-4 w-px bg-slate-200" />
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              Window: {status.config.days_before} days
            </span>
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              Max age: {status.config.max_age_days} days
            </span>
          </>
        )}
      </div>

      {/* Tabs */}
      <div className="mb-4 flex gap-0 border-b border-slate-200">
        {(["runs", "notifications"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t
                ? "border-b-2 border-blue-600 text-blue-600"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t === "runs" ? "Run History" : "Notification Log"}
          </button>
        ))}
      </div>

      {tab === "runs" && (
        <RunsTable
          data={runsQuery.data}
          isLoading={runsQuery.isLoading}
          error={runsQuery.error as Error | null}
          page={runsPage}
          onPage={(p) => setRunsPage(p)}
        />
      )}
      {tab === "notifications" && (
        <NotificationsTable
          data={notifQuery.data}
          isLoading={notifQuery.isLoading}
          error={notifQuery.error as Error | null}
          page={notifPage}
          onPage={(p) => setNotifPage(p)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && npm run test:run -- PasswordExpiryNotifierPage 2>&1 | tail -15
```

Expected: all 5 tests `PASSED`

- [ ] **Step 5: Run full frontend test suite to check for regressions**

```bash
cd frontend && npm run test:run 2>&1 | tail -10
```

Expected: all existing tests still pass.

- [ ] **Step 6: Run backend test suite to check for regressions**

```bash
cd backend && python3 -m pytest tests/ -q --ignore=tests/test_auth.py 2>&1 | tail -10
```

Expected: no new failures (pre-existing failures in `test_auth.py` are unrelated).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/PasswordExpiryNotifierPage.tsx frontend/src/__tests__/PasswordExpiryNotifierPage.test.tsx
git commit -m "feat: add PasswordExpiryNotifierPage with toggle, run history, and notification log"
```

---

## Verification Checklist

- [ ] `backend/storage_migrations/0025_password_expiry_notifier_settings.sql` exists
- [ ] All 18 tests in `test_password_expiry_notifier.py` pass
- [ ] All 6 tests in `test_routes_password_expiry_notifier.py` pass
- [ ] `python3 -c "import main; print('OK')"` succeeds
- [ ] All 5 tests in `PasswordExpiryNotifierPage.test.tsx` pass
- [ ] `/password-expiry` nav item appears on the primary (it-app) site
- [ ] Toggle is disabled for non-admin users (test with `is_admin: false` in `getMe` mock)
- [ ] Switching to "Notification Log" tab triggers `getPasswordExpiryNotifications`

## Enabling Live Emails from the UI

Once deployed, log in as an admin on `it-app.movedocs.com`, navigate to **Pwd Expiry** in the sidebar, and flip the toggle to **LIVE**. The change takes effect on the notifier's next daily run (within 24 hours).
