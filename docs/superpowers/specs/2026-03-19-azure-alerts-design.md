# Azure Alerts — Design Spec

**Date:** 2026-03-19
**Scope:** Azure portal only (`site_scope = "azure"`)
**Status:** Approved

---

## Overview

A dedicated Alerts tab in the Azure portal that lets users define monitoring rules across Azure cost, VM, identity, and resource data. Rules can be created via a natural-language chat interface (Quick Builder) or a structured form (Form Builder). Matched conditions trigger email notifications and/or Microsoft Teams Adaptive Card webhooks.

This is a **parallel system** to the existing Jira helpdesk alert infrastructure — same patterns, completely separate code. No changes to the existing `alert_store.py`, `alert_engine.py`, or `routes_alerts.py`.

---

## Architecture

### New Backend Files

| File | Role |
|------|------|
| `backend/azure_alert_store.py` | SQLite persistence — CRUD for rules and history |
| `backend/azure_alert_engine.py` | Rule evaluation against `azure_cache` snapshots + notification delivery |
| `backend/routes_azure_alerts.py` | FastAPI routes — CRUD, test, send, chat-parse, history |

### New Frontend File

| File | Role |
|------|------|
| `frontend/src/pages/AzureAlertsPage.tsx` | Main page — rules table, history tab, Quick + Form builder entry points |

### Wiring

- `backend/main.py` — register `routes_azure_alerts.router`
- `frontend/src/App.tsx` — add lazy import + `<Route path="alerts" />`
- `frontend/src/components/Layout.tsx` — add "Alerts" nav item to `azureNavItems`

---

## Backend Design

### Database Schema (`azure_alert_store.py`)

Two SQLite tables in `azure_alerts.db` (in `DATA_DIR`):

**`azure_alert_rules`**
```sql
CREATE TABLE azure_alert_rules (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    domain       TEXT NOT NULL,          -- cost | vms | identity | resources
    trigger_type TEXT NOT NULL,
    trigger_config TEXT NOT NULL,        -- JSON
    frequency    TEXT NOT NULL,          -- immediate | hourly | daily | weekly
    schedule_time TEXT NOT NULL DEFAULT '09:00',  -- HH:MM UTC
    schedule_days TEXT NOT NULL DEFAULT '0,1,2,3,4',  -- 0=Mon..6=Sun
    recipients   TEXT NOT NULL DEFAULT '',         -- comma-separated emails
    teams_webhook_url TEXT NOT NULL DEFAULT '',
    custom_subject   TEXT NOT NULL DEFAULT '',
    custom_message   TEXT NOT NULL DEFAULT '',
    last_run     TEXT,
    last_sent    TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
```

**`azure_alert_history`**
```sql
CREATE TABLE azure_alert_history (
    id           TEXT PRIMARY KEY,
    rule_id      TEXT NOT NULL,
    rule_name    TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    sent_at      TEXT NOT NULL,
    recipients   TEXT NOT NULL,
    match_count  INTEGER NOT NULL DEFAULT 0,
    match_summary TEXT NOT NULL DEFAULT '{}',  -- JSON: top items for the record
    status       TEXT NOT NULL,   -- sent | partial | failed | dry_run
    error        TEXT
);
```

At least one of `recipients` or `teams_webhook_url` must be non-empty (validated at the route layer).

### Trigger Types (`azure_alert_engine.py`)

All evaluators receive the relevant `azure_cache` snapshot(s) and return a list of matched items with a summary dict.

**Cost domain**

| Trigger | Config fields | Evaluator logic |
|---------|--------------|-----------------|
| `cost_threshold` | `period` (monthly/weekly), `threshold_usd` | Sum cost from `cost_summary` snapshot; match if > threshold |
| `cost_spike` | `spike_pct` (default 20) | Compare latest daily cost to 7-day average from `cost_trend`; match if delta > spike_pct% |
| `advisor_savings` | `min_monthly_savings_usd` (default 100) | Filter `advisor` snapshot items where `monthly_savings` > threshold |

**VM domain**

| Trigger | Config fields | Evaluator logic |
|---------|--------------|-----------------|
| `vm_deallocated` | `min_days` (default 7) | Filter `resources` snapshot for VMs with `power_state` deallocated; compute days since last state change if available, else flag all deallocated |
| `vm_no_reservation` | — | Cross-reference running VMs against `reservations` snapshot by SKU+region; return unmatched |

**Identity domain**

| Trigger | Config fields | Evaluator logic |
|---------|--------------|-----------------|
| `new_guest_users` | — | Filter `users` snapshot for `user_type == "Guest"` with `created_datetime` after `last_run` |
| `accounts_disabled` | — | Filter `users` snapshot for `enabled == false` with accounts that were not disabled on previous run (tracked via `last_run` timestamp + `updated_at` field comparison) |
| `stale_accounts` | `min_days` (default 90) | Filter `users` snapshot for enabled accounts where `last_password_change` is older than `min_days` |

**Resource domain**

| Trigger | Config fields | Evaluator logic |
|---------|--------------|-----------------|
| `resource_count_exceeded` | `resource_type` (e.g. `microsoft.compute/virtualmachines`), `threshold` | Count matching type in `resources` snapshot; match if > threshold |
| `resource_untagged` | `required_tags` (list of tag keys) | Filter `resources` snapshot for items where `tags` dict is missing any required key |

### Notification Delivery

**Email** — Imports and calls the existing `send_alert_email()` from `alert_engine.py`. Each trigger type provides a custom HTML table renderer:
- Cost → cost breakdown (service, amount, % share)
- VMs → VM list (name, size, state, days deallocated/uncovered)
- Identity → user list (name, UPN, department, relevant date)
- Resources → resource list (name, type, resource group, tag status)

Subject: `[Azure Alert] {rule_name}: {match_count} {trigger_label}`

**Teams** — POST to `teams_webhook_url` with Adaptive Card JSON. Sent in parallel with email via `asyncio.gather`. Card layout:
- Title: rule name + trigger label
- Body: match count + 2-3 line summary
- Actions: `[View in Dashboard]` (deep link to `/alerts`) + `[Open Azure Portal]`

Teams failure → history entry gets `status: "partial"`, email still delivered. Email failure with Teams success → `status: "partial"`. Both fail → `status: "failed"`. Error stored in `history.error`.

### Schedule Evaluation

Same frequency model as Jira alerts: `immediate` (~10-min polling), `hourly`, `daily`, `weekly`. Background task added to the Azure cache refresh loop. `_should_run()` checks `last_run` against `frequency` + `schedule_time` + `schedule_days`.

### API Routes (`routes_azure_alerts.py`)

All routes gated by `_ensure_azure_site()` and `require_authenticated_user`. Send/run routes additionally require `require_admin`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/azure/alerts/rules` | List all rules |
| POST | `/api/azure/alerts/rules` | Create rule |
| GET | `/api/azure/alerts/rules/{id}` | Get single rule |
| PUT | `/api/azure/alerts/rules/{id}` | Update rule |
| DELETE | `/api/azure/alerts/rules/{id}` | Delete rule |
| POST | `/api/azure/alerts/rules/{id}/toggle` | Enable/disable |
| POST | `/api/azure/alerts/rules/{id}/test` | Dry run — returns `{match_count, sample_items}` |
| POST | `/api/azure/alerts/rules/{id}/send` | Send immediately (admin) |
| POST | `/api/azure/alerts/run` | Run all enabled rules (admin) |
| GET | `/api/azure/alerts/history` | History log (query: `limit`, `rule_id`) |
| GET | `/api/azure/alerts/trigger-types` | Trigger schema catalog for form builder |
| POST | `/api/azure/alerts/chat-parse` | Parse natural language → rule JSON |

### Chat Parse Endpoint

Request: `{ "message": "Alert me when monthly spend exceeds $10k" }`

Response: `{ "parsed": true, "rule": { ...AzureAlertRuleCreate fields... }, "summary": "Monthly cost > $10,000 — daily at 9am" }` or `{ "parsed": false, "error": "..." }`

Uses `ai_client.py` with a system prompt that defines the rule JSON schema and valid trigger types. Temperature 0 for deterministic output. Returns structured JSON that maps directly to `AzureAlertRuleCreate`.

---

## Frontend Design

### Nav + Route

- `Layout.tsx` — add `{ to: "/alerts", label: "Alerts", icon: "△" }` to `azureNavItems`
- `App.tsx` — lazy import + `<Route path="alerts" element={<AzureAlertsPage />} />`

### `AzureAlertsPage.tsx`

**Page header:**
```
Alerts                          [+ New Alert ▼ (Quick / Builder)]
Monitor Azure and get notified when thresholds are crossed.
```

**Two tabs: Rules | History**

**Rules tab** — table with columns:
- Name, Domain chip, Trigger, Schedule, Last Sent, Status toggle (enabled/disabled), Test button, Delete button
- Empty state: "No alert rules yet. Use Quick or Builder to create your first one."

**History tab** — table with columns:
- Rule name, Trigger, Sent at, Recipients, Match count, Status chip (sent/partial/failed)
- Infinite scroll, 50 rows initial

### Form Builder (Drawer)

Resizable slide-in drawer (same pattern as AzureVMsPage). Single scrollable form with five logical sections — not separate pages/steps, so users can scroll back freely:

1. **Domain** — pill toggles: Cost | VMs | Identity | Resources
2. **Trigger** — dropdown populated by `/api/azure/alerts/trigger-types` for selected domain; dynamic config fields appear below (number inputs, tag list, etc.)
3. **Schedule** — pill toggles: Immediate | Hourly | Daily | Weekly; time + day pickers appear for Daily/Weekly
4. **Notify** — email chip input (add multiple); Teams webhook URL field; validation requires at least one
5. **Name + Save** — text input; `[Test]` button shows inline result; `[Save]` submits

### Quick Builder (Modal)

Full-screen-overlay modal (not a drawer). Chat-style UI:

1. AI greeting + 3 example prompts shown
2. User types natural language description
3. AI responds with interpreted rule summary card:
   - Shows: Name, Domain, Trigger + config, Schedule, Notify targets
   - Two buttons: `[Edit in Builder]` (opens Form Builder pre-filled) and `[Save]`
4. If parse fails: AI explains what it couldn't understand, suggests builder

The chat is single-turn — one message in, one interpreted rule out. Not a multi-turn conversation. This keeps scope tight and prevents ambiguity loops.

---

## Error Handling

- **Azure cache not populated** — evaluators check snapshot freshness; if `last_refresh` is null or > 2× refresh interval, return `{ match_count: 0, error: "Azure data not yet available" }` rather than alerting on stale/empty data
- **Missing config** — trigger config validation at store layer (Pydantic); invalid rules rejected at creation, not at evaluation time
- **Email/Teams delivery failure** — logged to history with error text; does not retry automatically (next scheduled run will re-evaluate and re-send if condition still true)
- **AI parse failure** — `chat-parse` endpoint returns `{ parsed: false, error }` with HTTP 200; frontend shows the error inline and offers the builder fallback

---

## Out of Scope (Future)

- Azure mutation actions (disable user, tag resource, shut down VM) — architecture leaves a clean hook: evaluators return a `matched_items` list that a future `azure_action_engine.py` could consume
- Multi-turn chat for iterative rule refinement
- Slack / PagerDuty webhook destinations (generic JSON POST can be added alongside Teams)
- Per-subscription or per-resource-group filter scoping on rules
