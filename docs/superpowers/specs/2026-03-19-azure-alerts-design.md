# Azure Alerts — Design Spec

**Date:** 2026-03-19
**Scope:** Azure portal only (`site_scope = "azure"`)
**Status:** Approved

---

## Overview

A dedicated Alerts tab in the Azure portal that lets users define monitoring rules across Azure cost, VM, identity, and resource data. Rules can be created via a natural-language chat interface (Quick Builder) or a structured form (Form Builder). Matched conditions trigger email notifications and/or Microsoft Teams Adaptive Card webhooks.

This is a **parallel system** to the existing Jira helpdesk alert infrastructure — same patterns, completely separate code. No changes to `alert_store.py`, `alert_engine.py`, or `routes_alerts.py`.

---

## Architecture

### New Backend Files

| File | Role |
|------|------|
| `backend/azure_alert_store.py` | SQLite persistence — CRUD for rules, history, and state-tracking tables |
| `backend/azure_alert_engine.py` | Rule evaluation against `azure_cache` snapshots + email/Teams delivery |
| `backend/routes_azure_alerts.py` | FastAPI routes — CRUD, test, send, chat-parse, history |

### New Frontend File

| File | Role |
|------|------|
| `frontend/src/pages/AzureAlertsPage.tsx` | Main page — rules table, history tab, Quick + Form builder entry points |

### Wiring Changes

- `backend/main.py` — import `start_azure_alert_loop` / `stop_azure_alert_loop` from `azure_alert_engine` and call in the existing `lifespan` context manager (after `azure_cache.start_background_refresh()`, before `yield`; reverse on teardown)
- `backend/main.py` — register `routes_azure_alerts.router` unconditionally (same as all other routers; `_ensure_azure_site()` guards each endpoint internally)
- `frontend/src/App.tsx` — lazy import + `<Route path="alerts" element={<AzureAlertsPage />} />` inside the Azure branch, before the catch-all `<Route path="*" ...>`
- `frontend/src/components/Layout.tsx` — add `{ to: "/alerts", label: "Alerts", icon: "\u25B2" }` to `azureNavItems` (filled triangle, distinct from the Jira Alerts hollow `\u25B3`)

---

## Backend Design

### Database (`azure_alert_store.py`)

Stored in `azure_alerts.db` in `DATA_DIR`. Four tables:

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS azure_alert_rules (
    id              TEXT PRIMARY KEY,       -- UUID string
    name            TEXT NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    domain          TEXT NOT NULL,          -- cost | vms | identity | resources
    trigger_type    TEXT NOT NULL,
    trigger_config  TEXT NOT NULL,          -- JSON object
    frequency       TEXT NOT NULL,          -- immediate | hourly | daily | weekly
    schedule_time   TEXT NOT NULL DEFAULT '09:00',   -- HH:MM, always UTC
    schedule_days   TEXT NOT NULL DEFAULT '0,1,2,3,4', -- 0=Mon..6=Sun
    recipients      TEXT NOT NULL DEFAULT '',          -- comma-separated emails
    teams_webhook_url TEXT NOT NULL DEFAULT '',
    custom_subject  TEXT NOT NULL DEFAULT '',
    custom_message  TEXT NOT NULL DEFAULT '',
    last_run        TEXT,
    last_sent       TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_azure_alert_rules_domain_enabled
    ON azure_alert_rules (domain, enabled);

CREATE TABLE IF NOT EXISTS azure_alert_history (
    id              TEXT PRIMARY KEY,
    rule_id         TEXT NOT NULL REFERENCES azure_alert_rules(id) ON DELETE CASCADE,
    rule_name       TEXT NOT NULL,
    trigger_type    TEXT NOT NULL,
    sent_at         TEXT NOT NULL,
    recipients      TEXT NOT NULL,
    match_count     INTEGER NOT NULL DEFAULT 0,
    match_summary   TEXT NOT NULL DEFAULT '{}',  -- JSON: up to 10 sample items
    status          TEXT NOT NULL,  -- sent | partial | failed | dry_run
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_azure_alert_history_rule_sent
    ON azure_alert_history (rule_id, sent_at);

-- Tracks first-seen-deallocated timestamp per VM (for vm_deallocated trigger)
CREATE TABLE IF NOT EXISTS azure_alert_vm_states (
    vm_id                   TEXT PRIMARY KEY,
    first_seen_deallocated  TEXT NOT NULL   -- ISO timestamp UTC
);

-- Tracks last-known enabled state per user (for accounts_disabled trigger)
CREATE TABLE IF NOT EXISTS azure_alert_user_states (
    user_id     TEXT PRIMARY KEY,
    enabled     INTEGER NOT NULL,           -- 1 or 0
    recorded_at TEXT NOT NULL               -- ISO timestamp UTC
);
```

**ID convention:** All rule IDs are UUID strings (`str(uuid.uuid4())`), deliberately different from the Jira system's integer auto-increment IDs, since both DBs may be present on the same host and integer IDs would be ambiguous in logs.

**Validation:** At route layer, reject `CREATE`/`UPDATE` if both `recipients` and `teams_webhook_url` are empty. At least one delivery channel is required.

**Zero-match history:** No history row is written when `match_count == 0`. An evaluator returning zero matches is a successful no-op; the rule's `last_run` is still updated.

### Pydantic Models (add to `models.py`)

```python
class AzureAlertRuleCreate(BaseModel):
    name: str
    domain: Literal["cost", "vms", "identity", "resources"]
    trigger_type: str
    trigger_config: dict[str, Any] = {}
    frequency: Literal["immediate", "hourly", "daily", "weekly"]
    schedule_time: str = "09:00"       # HH:MM UTC
    schedule_days: str = "0,1,2,3,4"  # comma-separated ints
    recipients: str = ""               # comma-separated emails
    teams_webhook_url: str = ""
    custom_subject: str = ""
    custom_message: str = ""

class AzureAlertRuleUpdate(AzureAlertRuleCreate):
    pass

class AzureAlertRuleResponse(AzureAlertRuleCreate):
    id: str
    enabled: bool
    last_run: str | None
    last_sent: str | None
    created_at: str
    updated_at: str

class AzureAlertTestResponse(BaseModel):
    match_count: int
    sample_items: list[dict[str, Any]]

class AzureAlertHistoryItem(BaseModel):
    id: str
    rule_id: str
    rule_name: str
    trigger_type: str
    sent_at: str
    recipients: str
    match_count: int
    match_summary: dict[str, Any]
    status: str
    error: str | None

class AzureChatParseRequest(BaseModel):
    message: str

class AzureChatParseResponse(BaseModel):
    parsed: bool
    rule: AzureAlertRuleCreate | None = None
    summary: str = ""
    error: str = ""
```

### Trigger Types (`azure_alert_engine.py`)

All evaluators receive relevant snapshot data (fetched via `azure_cache._snapshot(name)`) and return `list[dict]` of matched items. The engine calls `azure_cache._snapshot()` directly — this is the established internal access pattern used throughout `azure_cache.py` itself.

**Staleness check:** Before evaluating, the engine checks freshness via `azure_cache.status()["datasets"]`. Each dataset entry has `last_refresh` (ISO string) and `interval_minutes`. If `last_refresh` is `None` or age > `2 × interval_minutes`, the evaluator returns `[]` with a warning log — it does not fire an alert on stale or empty data.

**Snapshot-to-dataset mapping** (for freshness checks):

| Snapshot | Dataset key |
|----------|-------------|
| `cost_summary`, `cost_trend`, `advisor` | `"cost"` |
| `resources`, `reservations` | `"inventory"` |
| `users` | `"directory"` |

---

**Cost domain**

`cost_trend` row shape (from `azure_client.get_cost_trend()`): `{"date": "YYYY-MM-DD", "cost": float, "currency": "USD"}`

| Trigger | Config fields | Logic |
|---------|--------------|-------|
| `cost_threshold` | `period: "monthly"\|"weekly"`, `threshold_usd: float` | Sum `cost` from `cost_trend` rows: monthly = all rows (up to `AZURE_COST_LOOKBACK_DAYS`), weekly = last 7 rows. Match if sum > `threshold_usd`. Returns single-item list with `{"period", "total_cost", "currency"}`. |
| `cost_spike` | `spike_pct: int` (default 20) | Use `cost_trend`. Exclude the most recent row (today's data is partial). Compare second-to-last row ("yesterday") against average of prior 6 rows. If fewer than 3 prior rows exist, skip evaluation (insufficient data). Match if delta > `spike_pct`%. |
| `advisor_savings` | `min_monthly_savings_usd: float` (default 100) | Filter `advisor` snapshot items where `monthly_savings >= min_monthly_savings_usd`. Each item is `{"title", "description", "monthly_savings", "annual_savings", "currency", "subscription_name"}`. |

---

**VM domain**

`resources` snapshot contains all Azure resources. VMs identified by `resource_type.lower() == "microsoft.compute/virtualmachines"`. VM `state` field contains power state string (e.g. `"PowerState/deallocated"`).

| Trigger | Config fields | Logic |
|---------|--------------|-------|
| `vm_deallocated` | `min_days: int` (default 7) | For each VM with `"deallocated"` in `state.lower()`: look up `azure_alert_vm_states` — if no row, insert with `first_seen_deallocated = now`. If row exists, compute days since `first_seen_deallocated`. Match if days >= `min_days`. Purge rows for VMs that are no longer deallocated. |
| `vm_no_reservation` | — | Build reservation coverage map from `reservations` snapshot: key = `(sku.lower(), location.lower())`, value = sum of `quantity` across all reservations with that key. `applied_scope_type` is intentionally ignored (Shared reservations are assumed to cover all matching VMs; Single-scope filtering is out of scope). For each running VM (state contains `"running"` or `"powerstate/running"`), check if `(vm_size.lower(), location.lower())` exists in coverage map with remaining quantity > 0 (decrement as VMs are matched). Return unmatched VMs. |

---

**Identity domain**

All identity fields are accessed from the normalized user dict. User-type fields live in `user["extra"]`:
- `user["extra"]["user_type"]` → `"Member"` or `"Guest"`
- `user["extra"]["created_datetime"]` → ISO string (empty if unknown)
- `user["extra"]["last_password_change"]` → ISO string (empty if unknown or on-prem managed)
- `user["extra"]["on_prem_sync"]` → `"true"` or `""`

| Trigger | Config fields | Logic |
|---------|--------------|-------|
| `new_guest_users` | — | Filter users where `extra["user_type"] == "Guest"` and `extra["created_datetime"]` is parseable and > `last_run` timestamp. If `last_run` is None, return all current guests (baseline run). |
| `accounts_disabled` | — | For each user in snapshot: upsert into `azure_alert_user_states` with current `enabled` value. Compare against stored value — match users where stored `enabled` was `1` (true) and current `enabled` is `0`/`False`. Update stored state. On first run (no stored state), baseline all users without matching. |
| `stale_accounts` | `min_days: int` (default 90) | Filter users where `enabled == True`, `extra["on_prem_sync"] != "true"` (exclude on-prem accounts — their passwords are managed outside Azure AD), and `extra["last_password_change"]` is non-empty and older than `min_days`. Skip users with empty `last_password_change` (insufficient data). |

---

**Resource domain**

| Trigger | Config fields | Logic |
|---------|--------------|-------|
| `resource_count_exceeded` | `resource_type: str` (e.g. `"microsoft.compute/virtualmachines"`), `threshold: int` | Count items in `resources` snapshot where `resource_type.lower() == config.resource_type.lower()`. Match if count > threshold. Returns single-item result with `{"resource_type", "count", "threshold"}`. |
| `resource_untagged` | `required_tags: list[str]` | Filter `resources` snapshot for items where `tags` dict is missing any key from `required_tags` (case-insensitive key comparison). Returns matched resources with `{"name", "resource_type", "resource_group", "missing_tags"}`. |

---

### Notification Delivery

**Email** — `from email_service import send_email`. Signature: `send_email(to: list[str], subject: str, html_body: str, sender: str, cc: list[str] | None) -> bool`. Each trigger type has a custom HTML table in the body (same dark-header + table pattern as existing Jira alerts). Called asynchronously. Returns `True` on success, `False` on failure (does not raise).

Subject: `[Azure Alert] {rule.name}: {match_count} {trigger_label}` (or `custom_subject` if set, with `{rule_name}`, `{match_count}`, `{trigger_label}` template variables).

**Teams** — `httpx.AsyncClient` POST to `teams_webhook_url` with Adaptive Card JSON payload. Adaptive Card body:

```json
{
  "type": "message",
  "attachments": [{
    "contentType": "application/vnd.microsoft.card.adaptive",
    "content": {
      "$schema": "...",
      "type": "AdaptiveCard",
      "version": "1.4",
      "body": [
        { "type": "TextBlock", "text": "🔔 Azure Alert — {rule_name}", "weight": "Bolder", "size": "Medium" },
        { "type": "TextBlock", "text": "{trigger_label} · {timestamp}", "isSubtle": true },
        { "type": "TextBlock", "text": "{match_count} items matched", "weight": "Bolder" },
        { "type": "TextBlock", "text": "{2–3 line plain-text summary}", "wrap": true }
      ],
      "actions": [
        { "type": "Action.OpenUrl", "title": "View in Dashboard", "url": "{site_origin}/alerts" },
        { "type": "Action.OpenUrl", "title": "Open Azure Portal", "url": "https://portal.azure.com" }
      ]
    }
  }]
}
```

**Delivery logic:** Email and Teams sends run via `asyncio.gather(email_task, teams_task, return_exceptions=True)`. Status:
- Both succeed → `"sent"`
- One fails → `"partial"`, error logged in history
- Both fail → `"failed"`, combined error in history

**Background loop wiring:** `azure_alert_engine.py` exposes two coroutines:

```python
async def start_azure_alert_loop() -> None: ...
async def stop_azure_alert_loop() -> None: ...
```

These manage an `asyncio.Task` (same pattern as `azure_cache.start_background_refresh()`). The loop wakes every 60 seconds, calls `run_due_rules()` in an executor thread. Added to `main.py` lifespan:

```python
from azure_alert_engine import start_azure_alert_loop, stop_azure_alert_loop

async with lifespan(app):
    await azure_cache.start_background_refresh()
    await start_azure_alert_loop()   # ← new
    yield
    await stop_azure_alert_loop()    # ← new
    await azure_cache.stop_background_refresh()
```

### Schedule Evaluation

Same logic as Jira alerts: `_should_run(rule)` compares `rule.last_run` against `frequency` + `schedule_time` (UTC) + `schedule_days`. Throttle windows: `immediate` = 10 min, `hourly` = 50 min, `daily` = 20 hours, `weekly` = 140 hours.

### API Routes (`routes_azure_alerts.py`)

All routes gated by `_ensure_azure_site()` and `require_authenticated_user`. Admin-only routes marked ★.

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/azure/alerts/rules` | User | List all rules |
| POST | `/api/azure/alerts/rules` | User | Create rule |
| GET | `/api/azure/alerts/rules/{id}` | User | Get single rule |
| PUT | `/api/azure/alerts/rules/{id}` | User | Update rule |
| DELETE | `/api/azure/alerts/rules/{id}` | User | Delete rule + cascades history |
| POST | `/api/azure/alerts/rules/{id}/toggle` | User | Enable/disable (not admin-gated) |
| POST | `/api/azure/alerts/rules/{id}/test` | User | Dry run — returns `AzureAlertTestResponse` |
| POST | `/api/azure/alerts/rules/{id}/send` | ★ Admin | Send immediately |
| POST | `/api/azure/alerts/run` | ★ Admin | Run all enabled rules |
| GET | `/api/azure/alerts/history` | User | History log (`?limit=50&rule_id=...`) |
| GET | `/api/azure/alerts/trigger-types` | User | Trigger schema catalog for form builder |
| POST | `/api/azure/alerts/chat-parse` | User | Parse natural language → `AzureChatParseResponse` |

### Chat Parse Endpoint

Request: `AzureChatParseRequest { message: str }`

Uses `ai_client.py` with a system prompt that provides the full list of valid `domain` values, `trigger_type` values per domain, and the `AzureAlertRuleCreate` JSON schema. Temperature = 0. Instructs the model to return only valid JSON matching the schema, or a JSON error object if it cannot parse confidently.

Response: `AzureChatParseResponse`. On success: `parsed=True`, `rule=<AzureAlertRuleCreate>`, `summary="Monthly cost > $10,000 — daily at 09:00 UTC"`. On failure: `parsed=False`, `error="<explanation>"`. HTTP 200 in both cases — the frontend handles the `parsed` flag.

---

## Frontend Design

### `AzureAlertsPage.tsx`

**Page header:**
```
Alerts                          [+ New Alert ▼]
                                  ├ Quick (AI)
                                  └ Builder (Form)
```

**Two tabs: Rules | History**

**Rules tab** — infinite-scroll table, 50 rows initial:

| Column | Notes |
|--------|-------|
| Name | Plain text |
| Domain | Colour chip: Cost=blue, VMs=purple, Identity=green, Resources=amber |
| Trigger | Human-readable label from trigger-types catalog |
| Schedule | e.g. "Daily 09:00 UTC" |
| Last Sent | Formatted date or "Never" |
| Status | Toggle switch (enabled/disabled), calls `/toggle` |
| Actions | "Test" button (inline result), delete icon |

Empty state: "No alert rules yet — use Quick or Builder to create your first one."

**History tab** — infinite-scroll table, 50 rows initial:

| Column | Notes |
|--------|-------|
| Rule | Name |
| Trigger | Label |
| Sent At | Formatted datetime |
| Recipients | First email shown; "+N more" if multiple |
| Matches | Integer count |
| Status | Chip: sent=green, partial=amber, failed=red, dry_run=slate |

### Form Builder (Drawer)

Resizable slide-in drawer (same pattern as `AzureVMsPage`). Single scrollable form with five sections — no separate steps/pages so users can scroll back:

1. **Domain** — pill toggles: Cost | VMs | Identity | Resources
2. **Trigger** — dropdown from `/api/azure/alerts/trigger-types` for selected domain; dynamic config fields below (number inputs for thresholds/days, tag-key chip input for `required_tags`, resource-type text for `resource_count_exceeded`)
3. **Schedule** — pill toggles: Immediate | Hourly | Daily | Weekly; UTC time input + weekday checkboxes appear for Daily/Weekly. Label: "Times are UTC."
4. **Notify** — email chip input (add/remove individual addresses); Teams webhook URL text field; validation error shown if both empty on save attempt
5. **Name + Save** — text input; `[Test]` runs dry run and shows inline: `"3 VMs matched"` or error; `[Save]` submits

### Quick Builder (Modal)

Full-overlay modal, not a drawer. Single-turn: one user message in, one interpreted rule out.

```
┌─────────────────────────────────────────────────────┐
│ Quick Alert                                [Close]  │
├─────────────────────────────────────────────────────┤
│ Describe what you want to monitor:                  │
│                                                      │
│ Examples:                                            │
│ · "Alert me when monthly spend exceeds $10k"        │
│ · "Email me when a VM is off for 7+ days"           │
│ · "Notify Teams when new guests are added"          │
│                                                      │
│ [_____________________________________________]      │
│                                              [Send] │
│                                                      │
│ ── Interpreted rule ─────────────────────────────── │
│ Name:     Monthly cost threshold                     │
│ Domain:   Cost                                       │
│ Trigger:  Cost > $10,000 (monthly)                  │
│ Schedule: Daily at 09:00 UTC                        │
│ Notify:   your-email@company.com                    │
│                                                      │
│                              [Edit in Builder] [Save]│
└─────────────────────────────────────────────────────┘
```

- AI greeting + examples shown before user types
- After `[Send]`: spinner → interpreted rule summary card appears, or inline error: "I couldn't parse that — try the Builder instead."
- `[Edit in Builder]`: closes modal, opens Form Builder drawer pre-filled with AI's rule
- `[Save]`: POSTs directly to `POST /api/azure/alerts/rules`, closes modal, refreshes rules list

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Azure snapshot stale or empty | Evaluator returns `[]`, no alert fired, warning logged, `last_run` updated |
| Email delivery fails | History `status: "partial"` or `"failed"`, error stored, Teams still sent |
| Teams webhook fails | History `status: "partial"` or `"failed"`, error stored, email still sent |
| AI parse returns no confident match | `parsed: false`, HTTP 200, frontend shows error inline |
| Rule config invalid (bad trigger_type, missing threshold) | Rejected at `POST /api/azure/alerts/rules` with HTTP 422 |
| Stale accounts with empty `last_password_change` | Silently skipped (insufficient data — field blank for on-prem accounts) |
| VM state table missing row | Treated as first observation; `first_seen_deallocated` set to now |

---

## Out of Scope (Future)

- Azure mutation actions (disable user, tag resource, shut down VM) — the evaluator's `matched_items` list is the hook point for a future `azure_action_engine.py`
- Multi-turn chat for iterative rule refinement
- Slack / generic JSON webhook destinations
- Per-subscription or per-resource-group filter scoping on rules
- Alerting on data not currently fetched (VM state-change timestamps, sign-in activity, MFA status)
