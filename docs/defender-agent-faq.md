# Defender Autonomous Agent — FAQ

Available at **azure.movedocs.com → Security → Defender Agent**.

---

## Overview

### What does the Defender Agent do?

It polls Microsoft Graph Security API for Defender alerts on a configurable interval (default every 2 minutes), classifies each new alert against a built-in decision rule table, and automatically dispatches safe remediation actions through the existing user-admin and device-action queues. Every decision — including skips — is logged durably for operator review.

### Does it touch Graph APIs directly to remediate?

No. The agent never calls Graph mutation APIs itself. It creates jobs in the `user_admin_jobs` and `security_device_jobs` queues, which are the same queues used by the Security workspace's manual action flows. This means all rate-limiting, auditing, and error handling from those queues applies here too.

### Is it available on all sites?

No. The agent and all its APIs are available only on **azure.movedocs.com**. Requests from other host scopes receive a 404.

### Does it run on every backend instance?

No. It is a leader-only background service. Only the elected leader instance polls and dispatches. In blue/green deployments the active color is the leader.

---

## Safety Tiers

### What are the three tiers?

| Tier | Decision | Actions | Operator window |
|------|----------|---------|----------------|
| **T1** | `execute` | Revoke sessions, device sync | None — fires immediately on first cycle |
| **T2** | `queue` | Disable sign-in | Configurable delay (default 15 min) — operator can cancel before `not_before_at` |
| **T3** | `recommend` | Device wipe, device retire | Requires explicit human approval via the UI or `POST /decisions/{id}/approve` |
| **Skip** | `skip` | None | Alert below `min_severity`, no matching rule, or entity on cooldown |

### Why can I cancel a T2 but not a T1?

T1 actions (revoke sessions, device sync) are designed to be fast and inherently reversible — a session can be re-established on next sign-in, and a device sync has no destructive side effects. T2 actions (disable sign-in) are more impactful and may surprise a user, so they are queued with a cancellation window to allow operator review.

### What happens to T2 rules outside business hours?

Several T2 rules are tagged `off_hours_escalate`. During weekends or outside 08:00–17:00 US/Pacific, those rules automatically promote their decision to T1-execute, because there is no operator available to cancel within the delay window. Affected rules include: password spray/brute force, MFA fatigue, AiTM/session-hijacking, and medium-severity anomalous token activity.

### Can T2 and T3 decisions be cancelled?

**T2**: Yes, from the decision feed's Cancel button before `not_before_at` passes. Once the delay window expires the job is dispatched and cancellation is no longer possible through the agent.

**T3**: T3 decisions are recommendation-only and have no queued job — they do nothing until you approve them. You can leave them pending indefinitely or approve them from the detail drawer.

### What happens after I approve a T3?

The agent's background loop picks up pending T3 decisions and dispatches the appropriate device job (wipe or retire). There is no additional cancellation window after approval.

---

## Alert Classification

### In what order are rules evaluated?

Top-to-bottom. First match wins. Built-in rules are always evaluated first. If all built-in rules produce a `skip`, custom detection rules (Phase 18) are evaluated in creation order.

### What fields are matched?

Built-in rules match on:
- `title_keywords` — case-insensitive substring match against the alert title
- `service_source_contains` — substring match against the service source (e.g. `defender`, `office365`)
- `min_severity` — alert severity must meet or exceed the rule's threshold

### What triggers a skip?

An alert is skipped when:
- Its severity is below the configured `min_severity` threshold
- No built-in or custom rule matches
- The alert has already been seen (within the seen-alert window, default 7 days)
- An entity in the alert has been acted on within the entity cooldown window (default 24 hours) for the same action type
- The alert matches an active suppression rule

Skipped decisions are still logged.

### What is alert deduplication?

Within a configurable window (default 30 minutes), the agent suppresses duplicate decisions for the same entity + action type combination. This prevents a burst of correlated alerts from spawning multiple identical jobs.

---

## Configuration

### Who can change the configuration?

Only **admins**. The config `PUT` endpoint requires the `require_admin` auth dependency. Read-only config fetch is available to all authenticated users.

### What configuration options are available?

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | true | Master on/off switch |
| `min_severity` | medium | Minimum alert severity to process (`informational`, `low`, `medium`, `high`, `critical`) |
| `tier2_delay_minutes` | 15 | How long T2 decisions wait before executing |
| `dry_run` | false | Log decisions but do not dispatch any jobs |
| `entity_cooldown_hours` | 24 | Suppress repeat actions against the same entity within this window |
| `alert_dedup_window_minutes` | 30 | Suppress duplicate entity+action decisions within this window |
| `min_confidence` | 0 | Skip decisions below this confidence score (0 = no filter) |
| `poll_interval_seconds` | 0 | Override poll interval (0 = use server default of 120 s) |
| `teams_tier1_webhook` | — | Per-tier Teams webhook; falls back to global env webhook if blank |
| `teams_tier2_webhook` | — | " |
| `teams_tier3_webhook` | — | " |

### What does dry_run do?

When enabled, the agent runs its full classification and logging cycle but calls `_dispatch_remediation` with `dry_run=True`, which skips job creation. Decisions are still written to the store so operators can audit what would have fired.

---

## Suppressions

### What can be suppressed?

Any individual alert can be silenced by entity or by title. Active suppressions are checked before rule classification. An alert matching any active suppression is logged as `skip` with the suppression reason.

### Do suppressions expire?

Optionally. When creating a suppression you can set an `expires_at` timestamp. After that time the suppression is treated as inactive and alerts are re-evaluated normally.

---

## Rule Management

### Can I disable a built-in rule?

Yes. From the Rules panel in the agent UI, or via `PUT /api/azure/security/defender-agent/rules/{rule_id}`, set `disabled: true`. Disabled rules are skipped during classification. The rule_id for each built-in rule is stable across restarts (`rule_00`, `rule_01`, etc.).

### Can I override a rule's confidence score?

Yes, through the same `PUT /rules/{rule_id}` endpoint with `confidence_score: <0–100>`. This overrides the built-in score and is respected by the `min_confidence` filter.

### What are custom detection rules?

Operators can define supplemental rules that fire only when all built-in rules produce a skip. A custom rule specifies:
- `match_field`: `title`, `category`, `service_source`, or `severity`
- `match_value`: the string to match
- `match_mode`: `contains`, `exact`, or `startswith`
- `tier`, `action_type`, and `confidence_score`

Custom rules are evaluated in creation order; first match wins.

---

## Decisions & Feed

### How far back does the feed go?

The feed is paginated (`limit` up to 500, `offset`). All decisions are retained in the database with no automatic pruning.

### What is the confidence score?

Each matched rule carries a confidence score (0–100) representing how strongly the rule correlates with a genuine threat. Higher scores mean higher operator confidence in the classification. The `min_confidence` config setting can filter out low-confidence decisions. Scores can be overridden per rule.

### What is entity enrichment?

When a decision is created the agent cross-references alert evidence against the Azure user and device caches. Affected users are enriched with display name, UPN, job title, and department. Devices are enriched with OS, compliance state, and primary-user info. This enrichment is visible in the decision drawer without requiring a live Graph call.

### What are tags?

Free-form string labels that analysts can attach to any decision (e.g. `confirmed-fp`, `escalated`, `reviewed`). Tags appear as pills in the feed and can be added or removed from the detail drawer. The `GET /tags` endpoint lists all tags currently in use.

### What is the analyst disposition?

After reviewing a decision, an analyst can stamp it as `true_positive`, `false_positive`, or `inconclusive`. Dispositions feed the false-positive rate metric in the detection metrics dashboard and can include an optional note and attribution.

### Can I export decisions?

Yes. The **Export CSV** button in the feed header downloads a CSV of decisions from the last 30 days (default). The `days` query parameter on `GET /decisions/export` accepts 1–365.

---

## Watchlist

### What is the entity watchlist?

A persistent list of high-risk users and devices that operators flag for elevated scrutiny. When a decision involves a watchlisted entity, the entity is marked in the decision's `watchlisted_entities` list and the decision's tier can be automatically promoted (if `boost_tier` is set on the entry).

### How is the watchlist populated?

From the agent UI's Watchlist panel, or via `POST /watchlist`. Each entry specifies `entity_type` (`user` or `device`), `entity_id` (UPN or device object ID), an optional display name, and a reason.

---

## Investigation Notes

### What are investigation notes?

A chronological analyst case log attached to each decision. Notes are append-only (text, author, timestamp) and are stored as a JSON array in the decision row. They appear in the decision detail drawer and are included in the CSV export.

---

## Teams Notifications

### When does the agent send Teams messages?

The agent notifies Teams after each decision where a job was dispatched or queued. Configurable per tier — if a `teams_tier1_webhook` (or tier 2/3) URL is set in config, that webhook is used; otherwise the global `DEFENDER_AGENT_TEAMS_WEBHOOK_URL` environment variable is used as a fallback.

### Can I suppress Teams notifications for a tier?

Leave the per-tier webhook blank and clear `DEFENDER_AGENT_TEAMS_WEBHOOK_URL`. If no webhook URL is found the notification is silently skipped.

---

## Metrics

### What metrics does the dashboard show?

The detection metrics dashboard (`GET /metrics/detections`) aggregates over a configurable number of days (default 30):

- Total decisions and tier distribution (T1 / T2 / T3 / skip)
- Daily decision volume chart
- Top 10 most-affected entities by decision count
- Top 10 most-frequent alert titles
- Analyst disposition summary and false-positive rate
- Top action type distribution

---

## Troubleshooting

### The agent shows a run error — where do I look?

The run list panel shows the last 20 run records including any error message. Common causes:
- Graph token expired or `AZURE_TENANT_ID` / client credentials not set
- `DATABASE_URL` Postgres migrations not applied — check startup logs for `relation "..." does not exist`
- Agent disabled in config

### An alert I expected to be acted on was skipped — why?

Check the decision record. The `reason` field explains the classification outcome. Common reasons:
- Alert severity below `min_severity`
- Entity already acted on within the cooldown window
- Alert already seen (within 7-day dedup window)
- Rule disabled via rule override
- Active suppression matched
- `min_confidence` threshold not met
- Agent in `dry_run` mode

### A T2 decision fired before I could cancel it — what happened?

If the rule has `off_hours_escalate: true` and the alert arrived outside business hours (08:00–17:00 PT, Mon–Fri), the decision was automatically promoted to T1 and executed immediately with no delay window. Check `executed_at` and the `reason` field on the decision.
