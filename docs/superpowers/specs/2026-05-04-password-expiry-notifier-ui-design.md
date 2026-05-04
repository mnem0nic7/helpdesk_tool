# Password Expiry Notifier UI — Design Spec

**Date:** 2026-05-04
**Status:** Approved

---

## Overview

A read-accessible admin page at `/password-expiry` on the primary (it-app) site scope. All signed-in users can view the run history and notification log. Admins can toggle the notifier on/off via a DB-backed switch that takes effect on the next daily job run — no restart required.

---

## Architecture

| Action | Path | Responsibility |
|---|---|---|
| Create | `backend/storage_migrations/0025_password_expiry_notifier_settings.sql` | Single-row settings table |
| Modify | `backend/password_expiry_notifier.py` | Read `enabled` from DB at each job start; fall back to env var |
| Create | `backend/routes_password_expiry_notifier.py` | 4 API routes |
| Modify | `backend/main.py` | Register new router |
| Create | `frontend/src/pages/PasswordExpiryNotifierPage.tsx` | Page component |
| Modify | `frontend/src/lib/api.ts` | 4 new API functions |
| Modify | `frontend/src/components/Layout.tsx` | Nav item on primary scope |
| Modify | `frontend/src/App.tsx` | Route `/password-expiry` |

---

## Data Model

### Migration: `backend/storage_migrations/0025_password_expiry_notifier_settings.sql`

```sql
CREATE TABLE IF NOT EXISTS password_expiry_notifier_settings (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    enabled     SMALLINT NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL DEFAULT ''
);
```

Single row (id=1). The notifier reads this row at the start of every `run_daily_job()` call. If the row does not exist, it falls back to `PASSWORD_EXPIRY_NOTIFY_ENABLED` env var.

---

## Backend Routes

New file: `backend/routes_password_expiry_notifier.py`  
Router prefix: `/api/password-expiry-notifier`

### `GET /status`

Auth: any signed-in user (`require_authenticated_user`).

Response:
```json
{
  "enabled": true,
  "last_run": {
    "run_date": "2026-05-04",
    "ran_at": "2026-05-04T02:00:12+00:00",
    "users_notified": 12,
    "test_mode": 0
  },
  "config": {
    "max_age_days": 90,
    "days_before": 14
  }
}
```

`last_run` is `null` if no runs recorded yet. `enabled` comes from the DB settings row; falls back to env var default if no row exists.

### `GET /runs?limit=30&offset=0`

Auth: any signed-in user.

Response:
```json
{
  "items": [
    {
      "run_date": "2026-05-04",
      "ran_at": "2026-05-04T02:00:12+00:00",
      "users_notified": 12,
      "test_mode": 0
    }
  ],
  "total": 45
}
```

Ordered newest-first. Max `limit` capped at 100.

### `GET /notifications?limit=50&offset=0`

Auth: any signed-in user.

Response:
```json
{
  "items": [
    {
      "id": "abc123",
      "sam_account_name": "jsmith",
      "email": "jsmith@corp.com",
      "expiry_date": "2026-05-11",
      "days_until_expiry": 7,
      "notified_at": "2026-05-04T02:00:13+00:00",
      "test_mode": 0
    }
  ],
  "total": 312
}
```

Ordered newest-first. Max `limit` capped at 100.

### `PATCH /settings`

Auth: admin only (`require_admin`).

Request body:
```json
{ "enabled": true }
```

Upserts the settings row (id=1). Sets `updated_at` to current UTC datetime and `updated_by` to the caller's email. Returns the same shape as `GET /status`.

---

## Notifier Changes

`backend/password_expiry_notifier.py` — `run_daily_job()` reads the DB settings row at the start of each run:

```python
# At start of run_daily_job(), before checking _already_ran_today:
with self._conn() as conn:
    row = conn.execute(
        "SELECT enabled FROM password_expiry_notifier_settings WHERE id = 1"
    ).fetchone()
    if row is not None:
        notify_enabled = bool(row["enabled"])
    else:
        notify_enabled = self._notify_enabled  # env-var default
```

`notify_enabled` replaces uses of `self._notify_enabled` within the job body. `_init_db()` gains the new settings table DDL.

---

## Frontend

### Nav item

`frontend/src/components/Layout.tsx` — append to `helpdeskNavItems`:
```typescript
{ to: "/password-expiry", label: "Pwd Expiry", icon: "⏰", primaryOnly: true }
```

### Route

`frontend/src/App.tsx` — add alongside other primary-scope routes:
```tsx
<Route path="/password-expiry" element={<PasswordExpiryNotifierPage />} />
```

### API functions (`frontend/src/lib/api.ts`)

```typescript
getPasswordExpiryStatus(): Promise<PasswordExpiryStatus>
getPasswordExpiryRuns(limit?: number, offset?: number): Promise<{ items: PasswordExpiryRun[]; total: number }>
getPasswordExpiryNotifications(limit?: number, offset?: number): Promise<{ items: PasswordExpiryNotification[]; total: number }>
patchPasswordExpirySettings(enabled: boolean): Promise<PasswordExpiryStatus>
```

Types:
```typescript
interface PasswordExpiryStatus {
  enabled: boolean;
  last_run: { run_date: string; ran_at: string; users_notified: number; test_mode: number } | null;
  config: { max_age_days: number; days_before: number };
}
interface PasswordExpiryRun {
  run_date: string;
  ran_at: string;
  users_notified: number;
  test_mode: number;
}
interface PasswordExpiryNotification {
  id: string;
  sam_account_name: string;
  email: string;
  expiry_date: string;
  days_until_expiry: number;
  notified_at: string;
  test_mode: number;
}
```

### Page component (`frontend/src/pages/PasswordExpiryNotifierPage.tsx`)

**Status bar** (top of page):
- Mode badge: green `LIVE` or amber `TEST` based on `status.enabled`
- Last run: date + users notified count, or "No runs yet"
- Config chips: "Window: N days" and "Max age: N days" (read-only from status)
- Toggle switch: visible to all, interactive only for admins. Non-admins see it disabled with tooltip "Admin access required." Toggle calls `PATCH /settings` via `useMutation`; invalidates the status query on success.

**Tabs** (below status bar):
- Local `useState` for active tab: `"runs"` | `"notifications"`
- No URL parameter needed

**Run History tab**:
- `useQuery` for `getPasswordExpiryRuns(30, offset)`
- Table columns: Date, Ran At (UTC), Users Notified, Mode badge
- Pagination: prev/next buttons, 30 rows/page

**Notification Log tab**:
- `useQuery` for `getPasswordExpiryNotifications(50, offset)`
- Table columns: User (SAM), Email, Expiry Date, Days, Notified At, Mode badge
- Pagination: prev/next buttons, 50 rows/page

**Loading state**: spinner centred in table area while query is pending.

**Error state**: inline red error message below status bar.

**No auto-polling** — data is historical. Page has a manual Refresh button that calls `queryClient.invalidateQueries`.

---

## Out of Scope

- Filtering / search within the notification log
- Per-user notification suppression
- Email preview / resend from the UI
- Notification log export to CSV

---

## Testing

- Backend: unit tests for `GET /status` (no DB row → falls back to env var; DB row present → uses DB value), `PATCH /settings` (admin succeeds, non-admin 403), `GET /runs` and `GET /notifications` pagination
- Frontend: Vitest tests for page render with mocked API (status bar shows correct badge, toggle disabled for non-admin, tabs switch correctly)
