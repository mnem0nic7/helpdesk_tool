# Teams Message Retention (`retention.movedocs.com`) — Design Spec

**Date:** 2026-09-10
**Status:** Approved

---

## Overview

A new host, `retention.movedocs.com`, lets operators browse Microsoft Teams and their channels and configure a per-channel rolling message-retention window (1–365 days). Once a channel's policy is confirmed active, an hourly leader-only background job deletes channel messages (and their SharePoint attachments) older than the configured window — including an immediate backlog purge the first time a policy goes active — and keeps enforcing it going forward.

**Why delegated auth, not Purview or app-only:** Microsoft Graph's `ChannelMessage.ReadWrite` delete endpoint has no supported application-permission (app-only/client-credentials) path — deleting channel messages requires a delegated user token. Purview retention policies *are* app-only and unattended, but their enforcement boundary is the whole Team, not a single channel, which doesn't satisfy the per-channel requirement. So this feature signs in as a dedicated service account (e.g. `retention-bot@movedocs.com`) via an OAuth auth-code flow with `offline_access`, persists the refresh token server-side, and drives deletion through that identity on an unattended schedule — the same delegated-token-persistence shape this repo already uses for the Atlassian 3LO connection in `backend/auth.py`.

**Honesty note for the UI:** Graph's channel-message delete is a *soft* delete (Microsoft's own API limitation, not a design choice here) — there is no "permanent delete" call available. The UI should say "deleted" without implying an unrecoverable-at-Microsoft's-level guarantee beyond what Graph itself provides.

---

## Architecture

- **New site scope:** `"retention"` added to `backend/site_context.py`'s `SiteScope` literal and `_SITE_PROFILES`, with a `RETENTION_APP_HOST` config var (default `retention.movedocs.com`) in `backend/config.py`. Joins the existing "no Jira issues" group (alongside `azure`/`security`/`hrapp`) in `get_scoped_issues`/`issue_matches_scope`.
- **Frontend scope:** `isRetentionHost()` in `frontend/src/lib/siteContext.ts`, a `retention` branch in `getSiteBranding()`, `retentionNavGroups` in `frontend/src/components/Layout.tsx` (two items: Teams & Channels, Policy History).
- **New file:** `backend/retention_graph_connection.py` — service-account OAuth connection (auth-code + `offline_access`), Fernet-encrypted refresh token at rest, `get_valid_retention_graph_token()` with a 2-minute expiry buffer, mirroring `get_valid_atlassian_connection()` in `backend/auth.py`. Own OAuth client registration (`oauth.register("retention_graph", ...)`), own callback route.
- **New file:** `backend/retention_policy_store.py` — CRUD for `retention_policies`, `retention_runs`, `retention_deletions`; preview count computation (live Graph read, not persisted).
- **New file:** `backend/retention_cleanup_job.py` — `RetentionCleanupJob` class, same shape as `QuarantineReleaseJob`: leader-only background asyncio task, polled hourly.
- **New file:** `backend/routes_retention.py` — connection status/connect/callback routes, Teams/channels listing, policy CRUD + preview, run/deletion history routes. All gated by `RETENTION_ALLOWED_USERS`.
- **Modified:** `backend/main.py` — register `retention_cleanup_job.start_background_runner()`/`stop_background_runner()` in `_start_leader_services`/`_stop_leader_services`; include the new router.
- **New frontend files:** `frontend/src/pages/RetentionTeamsPage.tsx`, `frontend/src/pages/RetentionHistoryPage.tsx`.
- **Modified:** `frontend/src/lib/api.ts` — new types + API functions.

No MSAL library is introduced — the Graph token exchange follows the existing raw-`requests`-based OAuth pattern already used for Entra/Atlassian, not `azure_client.py`'s app-only client-credentials flow (that module's pattern doesn't apply here since this is delegated, not app-only).

---

## Configuration (`backend/config.py`)

| Env var | Default | Description |
|---|---|---|
| `RETENTION_APP_HOST` | `retention.movedocs.com` | Host used by `get_site_scope_for_host()` to select the `retention` scope. |
| `RETENTION_ALLOWED_USERS` | *(empty)* | Comma-separated allowlist of operator emails permitted to use this host, checked in addition to normal Entra SSO auth. Empty means nobody is allowed (fail closed), matching `ALLOWED_USERS`'s existing convention. |
| `RETENTION_GRAPH_CLIENT_ID` / `RETENTION_GRAPH_CLIENT_SECRET` / `RETENTION_GRAPH_TENANT_ID` | — | App registration used for the delegated service-account OAuth flow. |
| `RETENTION_TOKEN_ENCRYPTION_KEY` | derived fallback | Fernet key for encrypting the persisted refresh token, mirroring `ATLASSIAN_TOKEN_ENCRYPTION_KEY`. |

---

## Data Model

### Migration: `backend/storage_migrations/0031_retention.sql`

**Table: `retention_graph_connection`**

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK DEFAULT 1 | Single row |
| `service_account_upn` | TEXT NOT NULL DEFAULT '' | e.g. `retention-bot@movedocs.com` |
| `encrypted_refresh_token` | TEXT NOT NULL DEFAULT '' | Fernet-encrypted |
| `access_token_cache` | TEXT NOT NULL DEFAULT '' | Encrypted, short-lived |
| `access_token_expires_at` | TEXT NOT NULL DEFAULT '' | ISO datetime UTC |
| `status` | TEXT NOT NULL DEFAULT 'disconnected' | `connected` \| `disconnected` |
| `last_refreshed_at` | TEXT | ISO datetime UTC |
| `last_error` | TEXT | Populated when a refresh attempt fails |
| `connected_by` | TEXT NOT NULL DEFAULT '' | Operator email who completed the OAuth flow |
| `connected_at` | TEXT NOT NULL DEFAULT '' | ISO datetime UTC |

**Table: `retention_policies`**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `team_id` | TEXT NOT NULL | |
| `team_name` | TEXT NOT NULL DEFAULT '' | Cached label |
| `channel_id` | TEXT NOT NULL | |
| `channel_name` | TEXT NOT NULL DEFAULT '' | Cached label |
| `retention_days` | INTEGER NOT NULL | 1–365 |
| `status` | TEXT NOT NULL DEFAULT 'pending_preview' | `pending_preview` \| `active` \| `disabled` |
| `created_by` | TEXT NOT NULL DEFAULT '' | |
| `created_at` | TEXT NOT NULL DEFAULT '' | ISO datetime UTC |
| `updated_at` | TEXT NOT NULL DEFAULT '' | ISO datetime UTC |

Unique index on `(team_id, channel_id)` — one policy per channel.

**Table: `retention_runs`**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `policy_id` | TEXT NOT NULL | |
| `started_at` | TEXT NOT NULL | ISO datetime UTC |
| `finished_at` | TEXT | ISO datetime UTC |
| `outcome` | TEXT NOT NULL DEFAULT 'running' | `ok` \| `partial` \| `failed` \| `running` |
| `messages_deleted` | INTEGER NOT NULL DEFAULT 0 | |
| `attachments_deleted` | INTEGER NOT NULL DEFAULT 0 | |
| `error` | TEXT | Populated on `failed`/`partial` |

Index: `idx_retention_runs_policy ON retention_runs (policy_id)`.

**Table: `retention_deletions`**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID |
| `run_id` | TEXT NOT NULL | |
| `item_type` | TEXT NOT NULL | `message` \| `attachment` |
| `item_id` | TEXT NOT NULL | Graph message/driveItem id |
| `sender_or_author` | TEXT NOT NULL DEFAULT '' | Best-effort, for audit readability |
| `original_created_at` | TEXT NOT NULL DEFAULT '' | ISO datetime, from Graph |
| `deleted_at` | TEXT NOT NULL | ISO datetime UTC |
| `status` | TEXT NOT NULL | `deleted` \| `failed` |
| `error` | TEXT | Populated when `status='failed'` |

Index: `idx_retention_deletions_run ON retention_deletions (run_id)`.

Use `SMALLINT` for any future boolean columns per repo convention; none needed here since `status` enums cover the on/off states.

---

## Service-Account Connection Flow

1. Retention admin opens the Teams & Channels page; if `retention_graph_connection.status != 'connected'`, a banner links to `POST /api/retention/connect`, which redirects to Microsoft's OAuth authorize endpoint with delegated scopes: `ChannelMessage.ReadWrite Files.ReadWrite.All Team.ReadBasic.All Channel.ReadBasic.All offline_access`.
2. The admin signs in **as the service account** (`retention-bot@movedocs.com`) at Microsoft's login page.
3. `GET /api/retention/callback` exchanges the auth code for tokens, encrypts the refresh token, upserts the single `retention_graph_connection` row (`status='connected'`, `connected_by`, `connected_at`).
4. `get_valid_retention_graph_token()`: if `access_token_expires_at` is more than 2 minutes out, return the cached access token; otherwise call Microsoft's `grant_type=refresh_token` endpoint, persist the (possibly rotated) refresh token and new access token/expiry, and return the fresh token. On failure (revoked/invalid_grant), set `status='disconnected'`, `last_error`, and raise — callers (worker and read routes) must treat this as fail-closed, not retry-forever.

---

## Job Logic (`backend/retention_cleanup_job.py`)

Leader-only, polled every 5 minutes, executing the real hourly pass once per UTC clock hour (same gating shape as `QuarantineReleaseJob`: a run-hour dedupe check, though here scoped by including the hour in each policy's run rather than a single global run row, since multiple policies run independently per cycle).

For each policy where `status = 'active'`:
1. Resolve a valid delegated token via `get_valid_retention_graph_token()` **once per cycle**, before iterating policies (there is one shared connection, so a failure here affects every policy equally). On failure, insert one `retention_runs` row per active policy with `outcome='failed'`, `error='token_invalid'`, log the failure a single time, and skip the rest of the cycle — rather than repeating the same Graph call and failure once per policy.
2. `GET /teams/{team_id}/channels/{channel_id}/messages` (paged) plus `GET .../messages/{id}/replies` for each root message, filtering to items with `createdDateTime` older than `now - retention_days`. Replies are fetched and evaluated independently since Graph does not cascade-delete replies when a root message is deleted.
3. For each qualifying message or reply: `DELETE /teams/{team_id}/channels/{channel_id}/messages/{id}` (soft delete, per Graph's own limitation). For each of its attachments: resolve `contentUrl` to a SharePoint driveItem and `DELETE /sites/{site_id}/drive/items/{item_id}` (this call supports app-only permissions too, but reuses the same delegated token here for one credential to monitor).
4. Each delete attempt (message or attachment) writes a `retention_deletions` row (`status='deleted'` or `'failed'` with `error`); a single item failure is logged and the loop continues rather than aborting the run.
5. 429 responses: retry with backoff honoring `Retry-After` (new helper, since `azure_client.py`'s generic `_request` doesn't provide this transparently — mirror the shape of `_cost_management_request`'s existing backoff instead).
6. Insert/update the `retention_runs` row: `outcome='ok'` if every item succeeded, `'partial'` if some failed, `'failed'` if the whole run errored before completing (e.g. the channel-messages list call itself failed with `permission_denied`/`not_found` — service account lost owner rights, or the Team/channel was deleted).

**First-activation backlog purge:** when a policy transitions `pending_preview` → `active` (see Preview flow below), no special-casing is needed in the job itself — the "older than window" filter naturally captures the entire existing backlog on the very first run, then only newly-aged content on subsequent runs.

---

## Preview Flow

`POST /api/retention/policies/{id}/preview` (or a query-param variant of policy creation before it's persisted) performs a **live, read-only** Graph query using the same message/reply-listing logic as the job, counting (not deleting) items older than the proposed `retention_days`, and returns:

```json
{
  "messages_count": 142,
  "attachments_count": 9,
  "oldest_message_at": "2025-11-02T14:03:00Z"
}
```

The policy is created with `status='pending_preview'` when first saved. A separate `POST /api/retention/policies/{id}/confirm` flips it to `active`, at which point the next scheduled worker cycle performs the actual (including backlog) deletion. Nothing deletes on save alone — only `confirm` arms it.

---

## Backend Routes

New file: `backend/routes_retention.py`, prefix `/api/retention`, all routes gated by the `retention` site scope + `RETENTION_ALLOWED_USERS`.

- `GET /connection/status` — connection health (`status`, `service_account_upn`, `last_refreshed_at`, `last_error`).
- `POST /connection/connect` — redirect to Microsoft OAuth authorize.
- `GET /connection/callback` — OAuth callback, completes the exchange.
- `GET /teams?limit=&offset=` — paged Team listing (delegated `GET /teams` via the service-account token; falls back to last-cached snapshot with an explicit "connection unavailable" flag if the token can't be refreshed).
- `GET /teams/{team_id}/channels?limit=&offset=` — paged channel listing per Team, annotated with each channel's current policy (if any).
- `POST /policies` — create a policy (`team_id`, `channel_id`, `retention_days`) → `status='pending_preview'`.
- `GET /policies/{id}/preview` — live dry-run counts (see above).
- `POST /policies/{id}/confirm` — flips to `active`.
- `PATCH /policies/{id}` — update `retention_days` or `status`. Setting `status='disabled'` takes effect immediately (the worker skips non-`active` policies, so disabling is not destructive and needs no re-confirmation). Changing `retention_days` always resets `status` to `pending_preview` regardless of the prior state, so the worker stops enforcing that policy until the operator re-runs preview and confirms the new window — this avoids silently widening or narrowing a live deletion window without review.
- `GET /policies?limit=&offset=` — paged list of all configured policies.
- `GET /runs?policy_id=&limit=&offset=` — paged run history, optional policy filter.
- `GET /deletions?run_id=&limit=&offset=` — paged per-item audit trail, optional run filter.

All list/paged routes cap `limit` at 100, following existing convention.

---

## Frontend

### Pages
- **`RetentionTeamsPage.tsx`** (route `/`): connection-health banner at top (Connect/Reconnect action if disconnected); paged Team list, each expandable to its paged channel list; each channel row shows policy status and a "Configure retention" action opening a modal (day-count input → Preview → counts shown → Confirm & Enable).
- **`RetentionHistoryPage.tsx`** (route `/history`): paged policy list with per-policy run history; drill-in to a run's `retention_deletions` rows.

### API (`frontend/src/lib/api.ts`)
```typescript
getRetentionConnectionStatus(): Promise<RetentionConnectionStatus>
getRetentionTeams(limit?: number, offset?: number): Promise<{ items: RetentionTeam[]; total: number }>
getRetentionChannels(teamId: string, limit?: number, offset?: number): Promise<{ items: RetentionChannel[]; total: number }>
createRetentionPolicy(body: { team_id: string; channel_id: string; retention_days: number }): Promise<RetentionPolicy>
previewRetentionPolicy(policyId: string): Promise<RetentionPreview>
confirmRetentionPolicy(policyId: string): Promise<RetentionPolicy>
patchRetentionPolicy(policyId: string, body: { retention_days?: number; status?: string }): Promise<RetentionPolicy>
getRetentionPolicies(limit?: number, offset?: number): Promise<{ items: RetentionPolicy[]; total: number }>
getRetentionRuns(policyId?: string, limit?: number, offset?: number): Promise<{ items: RetentionRun[]; total: number }>
getRetentionDeletions(runId?: string, limit?: number, offset?: number): Promise<{ items: RetentionDeletion[]; total: number }>
```

No auto-polling on either page — manual Refresh, consistent with other historical-data views. Both pages use existing paging helpers rather than rendering full lists, per this repo's convention for tenant-wide Graph-backed data.

---

## Error Handling

| Failure | Behavior |
|---|---|
| Refresh token revoked/invalid | Connection flips `disconnected`; worker skips all active policies that cycle, logs once; UI banner prompts reconnect. |
| Service account loses owner rights on a Team, or Team/channel deleted | That policy's run marked `failed` with a specific error; other policies unaffected. |
| Graph 429 | Retry with `Retry-After` backoff; if still failing at cycle end, run marked `partial`/`failed`, retried next hourly cycle. |
| Single message/attachment delete fails | Logged as a `failed` `retention_deletions` row; run continues; naturally retried next cycle since the item is still in the "older than window" set. |
| Preview/confirm drift (content changes between preview and confirm) | Accepted as advisory drift — preview is not a locked snapshot. |

---

## Out of Scope

- Purview/whole-Team retention policies (superseded by the delegated per-channel approach).
- Hard/permanent message deletion (not offered by Graph's API at all).
- Notifying channel members when their messages are deleted.
- Editing or clearing `retention_deletions`/`retention_runs` history.
- Non-allowlisted operator visibility (this host is allowlist-gated, stricter than the general admin pool).
- E2E test coverage against a live tenant (too destructive to exercise in CI).

---

## Testing

- **`backend/tests/test_site_context.py`** (extend): `retention` host maps to the `retention` scope; scope excluded from `get_scoped_issues`.
- **`backend/tests/test_retention_graph_connection.py`**: token refresh/expiry-buffer logic (mock token endpoint), refresh-token rotation persisted, `invalid_grant` flips status to `disconnected` with `last_error` set.
- **`backend/tests/test_retention_cleanup_job.py`**: hour-gating, message+reply selection against the retention window, attachment resolution/deletion, 429-retry-with-backoff, partial-failure doesn't abort the run, first-activation backlog purge (no special-casing needed — window filter naturally covers it), token-invalid skip behavior.
- **`backend/tests/test_routes_retention.py`**: allowlist gating (403 for non-allowlisted callers even if authenticated), policy CRUD + preview/confirm state transitions, pagination on teams/channels/policies/runs/deletions routes.
- **Frontend**: Vitest coverage for `RetentionTeamsPage.tsx` (connection banner states, preview-then-confirm modal flow, paging) and `RetentionHistoryPage.tsx` (run/deletion drill-in, paging).
