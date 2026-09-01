# Quarantine Auto-Release Job — Design Spec

**Date:** 2026-09-01
**Status:** Approved

---

## Overview

An admin-only Tools-page feature that checks Exchange Online (Defender for Office 365 / EOP) quarantine hourly for messages sent from a configurable list of trusted domains (default: `complexlegal.com`) and releases them automatically to all original recipients. Admins can toggle the job on/off and edit the trusted-domain list at any time; when off, the job does nothing (no dry-run/test-mode concept — this is a live action, so "off" means genuinely inactive). All activity is recorded durably: one row per hourly run (counts), one row per released/failed message (audit detail).

This intentionally releases everything matching the domain, including phishing/malware quarantine categories — the operator has accepted that risk for this specific trusted partner domain in exchange for not needing to review known-good mail from a spoofable sender address.

Pattern mirrors `backend/password_expiry_notifier.py` (leader-only background service, DB-backed enabled toggle, run-history + detail-log tables, paginated routes) with two deliberate differences: no test-mode/dry-run (see above), and hourly cadence instead of daily.

---

## Architecture

- **New file:** `backend/quarantine_release_job.py` — `QuarantineReleaseJob` class, same shape as `PasswordExpiryNotifier`: background asyncio task polled every 5 minutes, executing the real check once per UTC clock hour.
- **Modified:** `backend/exchange_online_client.py` — two new methods on `ExchangeOnlinePowerShellClient`: `list_quarantine_messages(domains)` and `release_quarantine_message(identity)`. Add `Get-QuarantineMessage` and `Release-QuarantineMessage` to the `Connect-ExchangeOnline -CommandName` allow-list in `_run_script` (the same allow-list already carrying `Set-Mailbox` and `Remove-DistributionGroupMember` from the offboarding-tool fixes).
- **New file:** `backend/routes_quarantine_release.py` — 4 routes, all admin-only.
- **Modified:** `backend/main.py` — register `quarantine_release_job.start_background_runner()` / `stop_background_runner()` in `_start_leader_services` / `_stop_leader_services`; include the new router.
- **New file:** `frontend/src/components/QuarantineReleaseTool.tsx` — rendered from `ToolsPage.tsx` for admins only, same pattern as `AdEmployeeNumberImportTool.tsx`.
- **Modified:** `frontend/src/lib/api.ts` — new types + 4 API functions.
- **Modified:** `frontend/src/pages/ToolsPage.tsx` — render the new component in the admin section.

The job reuses the existing `ExchangeOnlinePowerShellClient` instance at `user_admin_providers.user_admin_providers.mailbox.exchange_powershell` (same singleton `offboarding_runs.py` already uses) rather than constructing a new client.

---

## Configuration (`backend/config.py`)

| Env var | Default | Description |
|---|---|---|
| `QUARANTINE_RELEASE_DEFAULT_DOMAINS` | `complexlegal.com` | Seed value for `allowed_domains` the first time the settings row is created. Ignored once a settings row exists. |

No env var controls `enabled` — the settings row always defaults `enabled=0` on creation, and there is no env-var fallback (unlike the notifier, doing nothing is always the safe default here).

---

## Data Model

### Migration: `backend/storage_migrations/0027_quarantine_release.sql`

**Table: `quarantine_release_settings`**

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK DEFAULT 1 | Single row |
| `enabled` | SMALLINT NOT NULL DEFAULT 0 | |
| `allowed_domains` | TEXT NOT NULL DEFAULT '' | Comma-separated, e.g. `complexlegal.com` |
| `updated_at` | TEXT NOT NULL DEFAULT '' | ISO datetime UTC |
| `updated_by` | TEXT NOT NULL DEFAULT '' | Caller email |

**Table: `quarantine_release_runs`**

| Column | Type | Notes |
|---|---|---|
| `run_hour` | TEXT PK | `YYYY-MM-DDTHH:00:00Z`, unique — gates one run per clock hour |
| `ran_at` | TEXT NOT NULL | ISO datetime UTC |
| `domains_checked` | TEXT NOT NULL | Comma-separated snapshot of `allowed_domains` at run time |
| `checked_count` | INTEGER NOT NULL DEFAULT 0 | Quarantine entries matched |
| `released_count` | INTEGER NOT NULL DEFAULT 0 | |
| `failed_count` | INTEGER NOT NULL DEFAULT 0 | |

**Table: `quarantine_releases`**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `run_hour` | TEXT NOT NULL | FK-ish reference to `quarantine_release_runs.run_hour` |
| `message_identity` | TEXT NOT NULL | `Identity` from `Get-QuarantineMessage` |
| `sender_address` | TEXT NOT NULL | |
| `recipient_address` | TEXT NOT NULL | |
| `subject` | TEXT NOT NULL DEFAULT '' | |
| `received_at` | TEXT NOT NULL DEFAULT '' | ISO datetime, from `ReceivedTime` |
| `quarantine_reason` | TEXT NOT NULL DEFAULT '' | From `Type`/`PolicyType` (e.g. `Spam`, `Phish`, `Malware`, `Bulk`, `TransportRule`) |
| `status` | TEXT NOT NULL | `released` \| `failed` |
| `error` | TEXT | Populated when `status = failed` |
| `released_at` | TEXT NOT NULL | ISO datetime UTC |

Index: `idx_qr_run_hour ON quarantine_releases (run_hour)`.

---

## Job Logic

1. Background loop wakes every 5 minutes. Compute `current_hour = now.replace(minute=0, second=0, microsecond=0).isoformat()`. If a `quarantine_release_runs` row for `current_hour` already exists, skip.
2. Read settings row. If it doesn't exist, create it with `enabled=0`, `allowed_domains=QUARANTINE_RELEASE_DEFAULT_DOMAINS`. If `enabled` is false, skip entirely — **no run row is written** (off means inactive, not logged-as-skipped).
3. Parse `allowed_domains` into a list; if empty, skip (nothing to check).
4. Call `exchange_powershell.list_quarantine_messages(domains)` → list of `{identity, sender_address, recipient_address, subject, received_at, quarantine_reason}`.
5. For each message: call `exchange_powershell.release_quarantine_message(identity)`.
   - Success → insert `quarantine_releases` row with `status='released'`.
   - Exception → insert row with `status='failed'`, `error=str(exc)`; continue to the next message (one failure doesn't abort the run).
6. Insert the `quarantine_release_runs` summary row (`checked_count = len(messages)`, `released_count`, `failed_count`).

`list_quarantine_messages` implementation detail: runs `Get-QuarantineMessage -SenderAddress "*@<domain>" -PageSize 100 -Page <n>` per configured domain (EOP does not support a single call across multiple sender-domain wildcards), paging until a page returns fewer than `PageSize` results, and concatenates results across domains. `release_quarantine_message` runs `Release-QuarantineMessage -Identity <id> -ReleaseToAll -Confirm:$false` so it delivers to every original recipient, not just one.

---

## Backend Routes

New file: `backend/routes_quarantine_release.py`
Router prefix: `/api/quarantine-release`
Auth: **all four routes** use `require_admin` (unlike the password-expiry notifier, this whole feature is admin-only per product decision).

### `GET /status`
```json
{
  "enabled": true,
  "allowed_domains": ["complexlegal.com"],
  "last_run": {
    "run_hour": "2026-09-01T14:00:00Z",
    "ran_at": "2026-09-01T14:02:11+00:00",
    "checked_count": 3,
    "released_count": 3,
    "failed_count": 0
  }
}
```
`last_run` is `null` if no runs recorded yet (including "never been enabled").

### `GET /runs?limit=30&offset=0`
Paginated, newest-first, same row shape as `last_run` above plus `domains_checked`. `limit` capped at 100.

### `GET /releases?limit=50&offset=0&run_hour=`
Paginated, newest-first. Optional `run_hour` filters to one run. Row shape: `id, run_hour, message_identity, sender_address, recipient_address, subject, received_at, quarantine_reason, status, error, released_at`. `limit` capped at 100.

### `PATCH /settings`
Request: `{ "enabled": true, "allowed_domains": ["complexlegal.com", "example.com"] }` (either field optional — partial update). Upserts the settings row, joining `allowed_domains` back to a comma-separated string for storage. Sets `updated_at`/`updated_by`. Returns the same shape as `GET /status`.

---

## Frontend

### API (`frontend/src/lib/api.ts`)
```typescript
getQuarantineReleaseStatus(): Promise<QuarantineReleaseStatus>
getQuarantineReleaseRuns(limit?: number, offset?: number): Promise<{ items: QuarantineReleaseRun[]; total: number }>
getQuarantineReleaseReleases(limit?: number, offset?: number, runHour?: string): Promise<{ items: QuarantineReleaseMessage[]; total: number }>
patchQuarantineReleaseSettings(body: { enabled?: boolean; allowed_domains?: string[] }): Promise<QuarantineReleaseStatus>
```

### Component (`frontend/src/components/QuarantineReleaseTool.tsx`)
Rendered from `ToolsPage.tsx` inside the existing admin-only section (same gate as `AdEmployeeNumberImportTool`).

- **Status row**: on/off toggle (calls `PATCH /settings`, invalidates status query), editable domain list as a comma-separated text input with a Save button, last-run summary (`checked/released/failed` counts + timestamp, or "No runs yet").
- **Run history table**: paginated (`getQuarantineReleaseRuns`), columns Hour, Checked, Released, Failed. Clicking a row filters the releases table below to that `run_hour`.
- **Releases table**: paginated (`getQuarantineReleaseReleases`), columns Sender, Recipient, Subject, Reason, Status, Released At. Status failures shown with the error message on hover/expand.
- No auto-polling — manual Refresh button, consistent with other historical-data views on this page.

---

## Out of Scope

- Category filtering (e.g. excluding phishing/malware) — explicitly rejected; this releases everything matching the domain.
- Per-recipient release (always releases to all recipients via `-ReleaseToAll`).
- Notifying anyone when a release happens (no email/Teams notification — visibility is via the Tools-page UI only).
- Editing/removing individual `quarantine_releases` rows, or a "clear history" action.
- Non-admin visibility.

---

## Testing

- **`backend/tests/test_quarantine_release_job.py`**: hour-gating logic (skip if already ran this hour), skip-when-disabled (no run row written), settings-row bootstrap from env var default, per-message failure doesn't abort the run, run summary counts.
- **`backend/tests/test_exchange_online_client.py`** (extend existing file): `list_quarantine_messages` builds one `Get-QuarantineMessage -SenderAddress "*@domain"` call per domain and merges results; `release_quarantine_message` builds a `Release-QuarantineMessage -Identity ... -ReleaseToAll` script; `Get-QuarantineMessage`/`Release-QuarantineMessage` present in the `-CommandName` allow-list (extending the existing allow-list test).
- **`backend/tests/test_routes_quarantine_release.py`**: all 4 routes reject non-admin callers (403); `GET /status` reflects settings + last run; `PATCH /settings` upserts and partial-updates; pagination on `/runs` and `/releases`, including the `run_hour` filter on `/releases`.
- **Frontend**: Vitest test for `QuarantineReleaseTool.tsx` — toggle calls the patch mutation, domain list edits, run history row click filters the releases table, empty states render correctly.
