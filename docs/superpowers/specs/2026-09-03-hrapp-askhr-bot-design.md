# hrapp.movedocs.com Site + AskHR/Benefits Jira Bot — Design Spec

**Date:** 2026-09-03
**Status:** Approved

---

## Overview

Two pieces, built together but separable in review:

1. **A new site scope**, `hrapp`, served at `hrapp.movedocs.com`, following the exact same host-based-scope + Entra SSO pattern already used by `azure`/`security`. No new Docker service, no new Caddy site block, no new deploy step — it's a purely application-layer addition (Python scope registration + TS hostname matcher) on infrastructure that already serves four hostnames from one backend/frontend pair.
2. **The first hrapp tool**: a leader-only background bot that replaces the mail-flow Bcc-forwarding rules for `AskHR@` and `Benefits@librasolutionsgroup.com` with direct Jira Service Management ticket creation — reporter is AskHR/Benefits (via `raiseOnBehalfOf` or a classic-issue fallback), not the original external sender. Disabling the four legacy transport rules is an explicit **manual runbook step**, not a code path, done only after the bot is verified end-to-end.

Pattern mirrors `backend/quarantine_release_job.py` (leader-only background service, DB-backed enabled toggle, run-history + detail-log tables, paginated admin routes), with these deliberate differences: two mailboxes instead of one dataset, a checkpoint-bounded poll window instead of an hour-gate, and a detail table that also drives a manual **Retry** action.

---

## Part A — `hrapp` Site Scope

### Backend

- `backend/site_context.py`: add `"hrapp"` to the `SiteScope` literal; add an `_SITE_PROFILES["hrapp"]` branding entry (app_name, dashboard_name, host); add a branch in `get_site_scope_for_host()` checking `HRAPP_APP_HOST`; `issue_matches_scope()` returns `False` for `hrapp` (not a helpdesk queue, same as `azure`/`security`).
- `backend/config.py`: add `HRAPP_APP_HOST` (default `hrapp.movedocs.com`); `get_auth_provider_for_scope("hrapp")` → `"entra"` (default, overridable via `HRAPP_AUTH_PROVIDER` like the other scopes).
- No changes to `backend/auth.py` or `backend/routes_auth.py` — the existing per-scope-provider branching in `/api/auth/login`/`/api/auth/callback` already handles any scope whose provider is `"entra"`.

### Frontend

- `frontend/src/lib/siteContext.ts`: add `"hrapp"` to `SiteBranding["scope"]`; add `isHrappHost()` hostname matcher alongside the existing `isAzureHost`/`isSecurityHost`/`isOasisDevHost`.
- `frontend/src/components/Layout.tsx`: add an `hrappNavGroups: NavGroup[]` (grouped nav, following the `securityNavGroups` shape since this is a catalog-style workspace, not a flat helpdesk nav) and select it when `scope === "hrapp"`.
- `frontend/src/App.tsx`: add a route branch for `isHrappSite`, lazy-loading `HrAppPage.tsx` (landing/catalog) and `AskHrBotPage.tsx` (sub-page), following the same structure as the `securityRoutes` array reused across the security-only and azure-hosted trees.

### Infra

- `Caddyfile:8`: append `hrapp.movedocs.com` to the existing comma-separated host list on the shared site block. Requires DNS for the new host to exist; no other Caddy/compose/deploy changes.

### Access model

Any signed-in user via Entra SSO — same global `ALLOWED_USERS` allowlist that already gates `azure`/`security` today, so this adds a new host under the existing login, not a new access boundary. `require_admin` is a no-op for Entra sessions (all pass), so admin-gated routes below are gated for consistency with the rest of the Entra-scoped surface, not because they're more restricted than "signed in."

---

## Part B — AskHR/Benefits Bot

### Architecture

- **New file:** `backend/askhr_bot_job.py` — `AskHrBotJob` class, same shape as `QuarantineReleaseJob`: background asyncio task (`start_background_runner`/`stop_background_runner`), polling both mailboxes on a fixed interval rather than an hour-gate.
- **Modified:** `backend/jira_client.py` — new `create_request()` method (JSM `POST /rest/servicedeskapi/request`) and `create_issue_with_reporter()` (classic `POST /rest/api/3/issue` with `fields.reporter.id`), following the existing `create_issue()` pattern (jira_client.py:687). New `find_issue_by_internet_message_id()` using `POST /rest/api/3/search/jql`.
- **Modified:** `backend/azure_client.py` — no structural change; the bot uses the existing `graph_paged_get`/`graph_raw_request` wrappers directly (no new client needed, per the exploration).
- **Modified:** `backend/exchange_online_client.py` — add `get_transport_rule_domains(rule_identity)` method (`Get-TransportRule -Identity ... | select -ExpandProperty ExceptIfSenderDomainIs`); add `Get-TransportRule` to the `Connect-ExchangeOnline -CommandName` allow-list in `_run_script`.
- **New file:** `backend/routes_askhr_bot.py` — routes below, all `require_admin`.
- **Modified:** `backend/main.py` — register `askhr_bot_job.start_background_runner()`/`stop_background_runner()` in `_start_leader_services`/`_stop_leader_services`; include the new router.
- **New file:** `frontend/src/pages/HrAppPage.tsx` — lane-catalog landing page (one lane today: "AskHR / Benefits Bot"), same pattern as `AzureSecurityPage.tsx`.
- **New file:** `frontend/src/pages/AskHrBotPage.tsx` — status + settings + run history + message detail + retry, route `/askhr-bot`.
- **Modified:** `frontend/src/lib/api.ts` — new types + API functions.
- **Modified:** `frontend/src/lib/queryPolling.ts` usage — the status/history queries use an existing shared polling tier, not an ad hoc interval.

### Configuration (`backend/config.py`)

| Env var | Default | Description |
|---|---|---|
| `HRAPP_APP_HOST` | `hrapp.movedocs.com` | Host match for the new scope. |
| `ASKHR_BOT_ENABLED_DEFAULT` | `false` | Seed value for `enabled` the first time the settings row is created. Ignored once a settings row exists — mirrors the quarantine job's "off is always the safe default" contract. |

No new secrets: Graph calls reuse `ENTRA_CLIENT_ID`/`ENTRA_CLIENT_SECRET`/`ENTRA_TENANT_ID` (tenant-wide `Mail.Read` application permission must be added + admin-consented on this existing app registration — manual prerequisite, not code). Jira calls reuse `JIRA_EMAIL`/`JIRA_API_TOKEN`, already present.

### Data Model

Migration: `backend/storage_migrations/0029_askhr_bot.sql`

**Table: `askhr_bot_settings`**

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK DEFAULT 1 | Single row |
| `enabled` | SMALLINT NOT NULL DEFAULT 0 | |
| `poll_interval_seconds` | INTEGER NOT NULL DEFAULT 120 | |
| `lookback_minutes` | INTEGER NOT NULL DEFAULT 15 | Overlap margin subtracted from the last checkpoint when querying Graph, so a slow cycle or clock skew can't skip mail. |
| `askhr_checkpoint_at` | TEXT NOT NULL DEFAULT '' | ISO datetime UTC; latest `receivedDateTime` successfully processed for `AskHR@...` |
| `benefits_checkpoint_at` | TEXT NOT NULL DEFAULT '' | Same, for `Benefits@...` |
| `trusted_domains` | TEXT NOT NULL DEFAULT '' | JSON array snapshot from `Get-TransportRule` |
| `trusted_domains_refreshed_at` | TEXT NOT NULL DEFAULT '' | ISO datetime UTC |
| `domain_refresh_interval_seconds` | INTEGER NOT NULL DEFAULT 3600 | Decoupled from `poll_interval_seconds` to avoid a `pwsh` session every poll. |
| `reporter_mode` | TEXT NOT NULL DEFAULT 'unset' | `unset` \| `raise_on_behalf_of` \| `classic_reporter_field` |
| `updated_at` | TEXT NOT NULL DEFAULT '' | |
| `updated_by` | TEXT NOT NULL DEFAULT '' | |

**Table: `askhr_bot_runs`**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `mailbox` | TEXT NOT NULL | `askhr` \| `benefits` |
| `run_started_at` | TEXT NOT NULL | ISO datetime UTC |
| `messages_scanned` | INTEGER NOT NULL DEFAULT 0 | |
| `created_count` | INTEGER NOT NULL DEFAULT 0 | |
| `skipped_count` | INTEGER NOT NULL DEFAULT 0 | |
| `failed_count` | INTEGER NOT NULL DEFAULT 0 | |

**Table: `askhr_bot_messages`**

| Column | Type | Notes |
|---|---|---|
| `internet_message_id` | TEXT PK | Graph `internetMessageId`; primary idempotency key |
| `mailbox` | TEXT NOT NULL | `askhr` \| `benefits` |
| `graph_message_id` | TEXT NOT NULL | Graph `id`, needed for `$value`/attachment fetch on retry |
| `subject` | TEXT NOT NULL DEFAULT '' | |
| `sender_email` | TEXT NOT NULL DEFAULT '' | |
| `received_at` | TEXT NOT NULL DEFAULT '' | ISO datetime UTC |
| `status` | TEXT NOT NULL | `created` \| `skipped_internal_domain` \| `failed` |
| `jira_issue_key` | TEXT | Set once the ticket exists, even if a later step (attachment) fails |
| `error` | TEXT | Populated when `status = failed` |
| `processed_at` | TEXT NOT NULL | ISO datetime UTC, last attempt (updated on retry) |

Index: `idx_askhr_bot_messages_mailbox_received ON askhr_bot_messages (mailbox, received_at)`.

### Job Logic

1. Background loop wakes every `poll_interval_seconds`. Read settings row (bootstrap with defaults if absent, `enabled` from `ASKHR_BOT_ENABLED_DEFAULT`). If `enabled` is false, skip entirely — no run row written, same "off means inactive" contract as quarantine release.
2. If `now - trusted_domains_refreshed_at >= domain_refresh_interval_seconds`, refresh: call `exchange_powershell.get_transport_rule_domains("Forward External Mail to Jira - AskHR")`, store as JSON, update `trusted_domains_refreshed_at`.
3. For each mailbox (`askhr` → request type `420`, `benefits` → request type `619`):
   a. Compute `since = checkpoint_at - lookback_minutes` (or a fixed lookback if checkpoint is empty, e.g. first run — never an unbounded full-history scan).
   b. `GET /users/{mailbox}/mailFolders/Inbox/messages?$filter=receivedDateTime ge {since}&$orderby=receivedDateTime asc` via `graph_paged_get`.
   c. For each message not already in `askhr_bot_messages` (by `internetMessageId`):
      - Filter: skip (`skipped_internal_domain`) unless sender domain is outside `trusted_domains` **or** sender is exactly `payroll@librasolutionsgroup.com`.
      - Otherwise, run **ticket creation + attachment** (below). Record the outcome.
   d. Advance `{mailbox}_checkpoint_at` to the latest `receivedDateTime` actually processed in this batch (not `now()`), so nothing arriving mid-cycle is skipped by the next cycle's window.
   e. Insert an `askhr_bot_runs` summary row for this mailbox/cycle.
4. One message's failure never aborts the batch — continue to the next message, same as quarantine release's per-item error isolation.

### Ticket Creation + Attachment (shared by the job and the Retry action)

1. **Idempotency check**: look up `internet_message_id` in `askhr_bot_messages` first (fast, authoritative for anything this bot has seen). If a row exists with `status='created'` and a `jira_issue_key`, skip straight to step 3 (attachment-only retry path) instead of re-creating. Otherwise, as a defensive fallback before creating, run `find_issue_by_internet_message_id()` (JQL) — catches the case where a ticket was created but the local DB write failed afterward.
2. **Create the ticket**, branching on `reporter_mode`:
   - `unset`: attempt `create_request()` (`raiseOnBehalfOf`). On 400/403, set `reporter_mode='classic_reporter_field'` and fall back to `create_issue_with_reporter()` for this message; on success, set `reporter_mode='raise_on_behalf_of'`. Mode is cached from here on — subsequent messages use the cached mode directly, no more probing.
   - `raise_on_behalf_of`: call `create_request()` directly.
   - `classic_reporter_field`: call `create_issue_with_reporter()` directly.
   - `summary` = original email subject; `description` = `"Originally sent by: {name} <{email}> on {received date, local time}\n\n{body}"`.
3. **Attach the original email**: `graph_raw_request("GET", "/users/{mailbox}/messages/{graph_message_id}/$value")` → multipart `POST /rest/api/3/issue/{issueKey}/attachments` with `X-Atlassian-Token: no-check`.
4. **Record outcome** in `askhr_bot_messages` regardless of which step failed. A ticket created but not yet attached keeps `jira_issue_key` set with `status='failed'` and an attachment-specific error, so retry only re-runs the missing step, never creating a duplicate ticket.

An admin **"re-test reporter mode"** action resets `reporter_mode` to `unset`, forcing the probe again on the next message (for use after a Jira permission change).

### Backend Routes

New file: `backend/routes_askhr_bot.py`
Router prefix: `/api/askhr-bot`
Auth: all routes `require_admin`.

- `GET /status` → `{ enabled, poll_interval_seconds, lookback_minutes, checkpoints: {askhr, benefits}, trusted_domains, trusted_domains_refreshed_at, reporter_mode, last_runs: {askhr, benefits} }` (each `last_run` null if none yet).
- `GET /runs?mailbox=&limit=30&offset=0` — paginated, newest-first.
- `GET /messages?mailbox=&status=&limit=50&offset=0` — paginated, newest-first, optional `status`/`mailbox` filters.
- `PATCH /settings` — partial update of `enabled`, `poll_interval_seconds`, `lookback_minutes`, `domain_refresh_interval_seconds`; upserts, sets `updated_at`/`updated_by`.
- `POST /reporter-mode/reset` — sets `reporter_mode='unset'`.
- `POST /messages/{internet_message_id}/retry` — re-fetches the message from Graph by `graph_message_id`, re-runs the shared ticket-creation-and-attachment flow (idempotency-safe per above), updates the row, returns the updated row.

### Frontend

- `HrAppPage.tsx`: single lane card ("AskHR / Benefits Bot") linking to `/askhr-bot`.
- `AskHrBotPage.tsx`:
  - **Status panel**: enabled toggle, poll interval, per-mailbox last checkpoint, trusted-domain count + refreshed-at, current `reporter_mode` with a "Re-test" button.
  - **Run history table**: paginated, columns Mailbox, Started At, Scanned, Created, Skipped, Failed.
  - **Message detail table**: paginated, filterable by mailbox/status, columns Mailbox, Subject, Sender, Received, Status, Jira Key (link), Error. **Retry** button on `failed` rows.
  - Status/history queries use a shared `queryPolling.ts` tier; no ad hoc interval literal.

### Out of Scope

- Disabling the four legacy transport rules from the app — manual runbook (`docs/runbooks/askhr-bot-cutover.md`) run once by a human after end-to-end verification.
- Graph webhook/change-notification subscriptions — polling only for v1.
- Application Access Policy scoping of the `Mail.Read` grant — tenant-wide permission on the existing shared app registration, per product decision.
- Teams/email failure notifications — visibility is via the `/askhr-bot` UI only.
- Moving, flagging, or deleting processed messages in the source mailbox — the bot only reads; Inbox state is untouched.
- Non-admin visibility of settings/history (route-level; recall `require_admin` ≈ "signed in" for Entra sessions in this codebase today).

---

## Testing

- **`backend/tests/test_askhr_bot_job.py`**: skip-when-disabled (no run row written); checkpoint advances to latest processed `receivedDateTime`, not `now()`; domain-refresh cadence independent of poll cadence; filter logic (internal domain skip, payroll bypass); per-message failure doesn't abort the batch; reporter-mode probe-then-cache behavior (mock 403 → falls back and caches `classic_reporter_field`); idempotency (local dedup short-circuits Graph/Jira calls; JQL fallback only runs when local lookup misses); attachment-only retry when ticket exists but attachment previously failed.
- **`backend/tests/test_jira_client.py`** (extend): `create_request()` builds correct `raiseOnBehalfOf` payload; `create_issue_with_reporter()` builds correct classic payload; `find_issue_by_internet_message_id()` builds correct JQL.
- **`backend/tests/test_exchange_online_client.py`** (extend): `get_transport_rule_domains()` builds the correct `Get-TransportRule | select -ExpandProperty ...` script; `Get-TransportRule` present in the allow-list test.
- **`backend/tests/test_routes_askhr_bot.py`**: all routes reject non-admin (403); `GET /status` reflects settings + last runs; `PATCH /settings` partial-update semantics; `POST /reporter-mode/reset`; `POST /messages/{id}/retry` returns updated row and doesn't duplicate an existing ticket.
- **`backend/tests/test_site_context.py`** (extend): `hrapp` host resolves to `hrapp` scope; `issue_matches_scope()` returns `False` for `hrapp`.
- **Frontend**: Vitest for `AskHrBotPage.tsx` (toggle, retry action, empty states) and a host-branding test for `isHrappHost()`/`getSiteBranding()` following the existing `dataset.siteHostname` test-hook convention.
