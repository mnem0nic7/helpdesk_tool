# Security Portal Plan — security.movedocs.com

Tracks what is built, what is agreed, and what is deferred for the dedicated security portal.

---

## Current Architecture

| Component | What it does | AI |
|---|---|---|
| **Defender Agent** | Polls Microsoft Defender alerts every 2 min; auto-remediates T1, queues T2, surfaces T3 for approval | 50 built-in rules + custom rules + AI fallback classifier (gemma4:31b or runtime-config model, always T3-capped) |
| **Security Copilot** | On-demand investigation workbench; queries 16 internal sources, synthesizes with Ollama | gemma4:31b by default (admin-configurable via AI-05 runtime config); isolated security Ollama runtime |
| **Security Review Lanes** | 11 periodic-audit surfaces (Access, Identity, Users, Guests, Apps, Devices, Account Health, DLP, CA Tracker, Break-glass, Directory Roles) | AI-08 lane summaries implemented — 9 lanes, 60-min leader-only service; LaneSummaryPanel on all 9 lane pages; hub card teasers on Security Overview; regenerate endpoint for on-demand refresh |
| **Tools** | Login audit, mailbox delegate lookup, OneDrive copy | None |
| **Daily Digest** | Leader-only background service generating a 24h Defender activity summary | gemma4:31b via security Ollama runtime; Teams Adaptive Card webhook |

### Ollama Security Runtime

- **Host**: `http://10.76.1.180:11434`
- **Default model**: `gemma4:31b`
- **Config**: `OLLAMA_SECURITY_ENABLED`, `OLLAMA_SECURITY_BASE_URL`, `OLLAMA_SECURITY_MODEL` in `backend/.env`
- Isolated from the default Ollama queue used by helpdesk triage
- **Two-layer model config**: env vars set the startup default; the `security_runtime_config` DB table (AI-05) overrides the active model at runtime without restart. The DB value wins for model selection; env vars control everything else (host, enabled flag, digest hour, etc.)

### Data & Privacy

All AI inference runs locally on `10.76.1.180` — no data leaves the internal network. Data types processed per feature:

| Feature | Data sent to model |
|---|---|
| Copilot | Alert titles, entity names, Azure user/mailbox/group metadata, KB article content |
| AI fallback classifier | Alert title, category, severity, service source, description (first 500 chars) |
| AI narratives | Decision type, action type, entities, reason string |
| Daily digest | Aggregate counts (t1/t2/t3/skip), top category names, top entity names |
| Lane summaries | Attention counts, status labels, top 10 items per lane (account names, device names, app names) |

The model receives no credentials, no raw passwords, and no full email body content.

---

## Defender Agent — Rule Table

### Rule Category Summary

50 built-in rules evaluated top-to-bottom; first match wins. The catch-all always runs last.

| Category | Rules | Tiers in play | `off_hours_escalate` rules |
|---|---|---|---|
| **Identity & Session** — signin attacks, session/token hijacking, MFA abuse, OAuth, MCAS anomalies | 13 | T1–T3 | Password spray/brute force, MFA fatigue, AiTM, anomalous token (medium) — 4 rules |
| **Endpoint & Malware** — AV/device sync, malware signatures, process injection, C2, ransomware, named CVEs, persistence, recon | 21 | T1–T3 | None |
| **Email & Collaboration** — inbox rules, BEC, phishing delivery, MDO malicious-click upgrade | 6 | T1–T2 | Inbox rule manipulation (medium), BEC — 2 rules |
| **Red Canary Parity** — named RC playbooks, composites, threat families, IOC blocking, Kerberos attacks, PRT theft, defense evasion | 9 | T1–T2 | PRT theft — 1 rule |
| **Catch-all** — unmatched high/critical → human review | 1 | T3 | None |

Total rules with `off_hours_escalate`: **7** (all are identity-targeting T2s that auto-escalate to T1 execute when no operator is available to cancel).

### Custom Rules and Overrides

Built-in rules are evaluated top-to-bottom; first match wins. Custom rules are appended after all built-in rules, before the catch-all. The catch-all T3 always runs last regardless of custom rule count.

Per-rule overrides (disable a rule or adjust its confidence score) are applied per `rule_id` without code changes — operators can suppress a noisy built-in rule from the admin UI. Custom rules support the same keyword, severity, tier, and action_type fields as built-in rules. Entry points: `_RULES` list and `_classify_alert()` in `backend/defender_agent.py`; override storage in `defender_agent_store`.

### MITRE ATT&CK Technique Extraction

`_extract_mitre_techniques()` in `defender_agent.py` parses ATT&CK technique IDs (`T1055`, `T1078`, etc.) from Graph Security alert evidence fields and attaches them to the stored decision record. **The rule classifier does not yet use these IDs as match conditions** — rules currently match on alert title keywords and category strings only. MITRE technique-ID matching is deferred (see Deferred table).

### Red Canary Parity Coverage

#### Covered

| RC Playbook | Rule in table | Tier | Action |
|---|---|---|---|
| RC-6: MDO confirmed malicious URL click | `clicked malicious url`, `url detonation` (MDO service source) | T1 | `revoke_sessions` |
| RC-7: Anomalous token activity | `anomalous token`, `token issuer anomaly` | T1 (high) / T2 (medium) | `revoke_sessions` / `disable_sign_in` |
| RC-8: MCAS/Defender for Cloud Apps behavioral anomaly | `cloud app anomaly`, `mass download`, `ransomware activity in cloud` (MCAS service source) | T2 | `account_lockout` |
| RC-17: Known threat actor families | `qbot`, `qakbot`, `socgholish`, `impacket`, `raspberry robin`, and 6 others | T2 | `isolate_device` |
| RC-20: Inbox manipulation (HIGH severity upgrade) | `inbox rule`, `mailbox forwarding`, `suspicious forwarding` | T1 (high) / T2 (medium) | `revoke_sessions` / `disable_sign_in` |
| RC Containment: active attacker on endpoint + identity | `hands-on-keyboard`, `interactive attacker`, `human operated attack` | T2 composite | `isolate_device` + `revoke_sessions` |
| RC Full Containment: critical active exploitation | `ransomware encryption in progress`, `critical active exploitation` | T2 composite | `isolate_device` + `revoke_sessions` + `disable_sign_in` |
| Kerberoasting / AS-REP Roasting | `kerberoasting`, `asrep roasting`, `kerberos ticket abuse` | T2 | `collect_investigation_package` |
| PRT / Primary Refresh Token theft | `primary refresh token`, `prt theft`, `hybrid join token` | T2 (`off_hours_escalate`) | `revoke_sessions` |
| Defense evasion / security tool tampering | `amsi bypass`, `etw tampering`, `defender disabled`, `tamper protection disabled` | T1 | `start_investigation` |

#### Not Yet Covered (deferred)

| RC Category | Gap | Reason deferred |
|---|---|---|
| NTLM relay / SMB relay | No keyword rule; title varies by source | Needs MITRE technique-ID matching (T1557) — defer until technique-ID rules are implemented |
| Kerberos delegation abuse | Unconstrained/constrained delegation exploitation | Low prevalence in tenant; add when MITRE T1134.001/T1558.003 matching is available |
| Azure AD Connect sync abuse | AAD Connect service account compromise patterns | Specialist attack; revisit if/when AAD Connect is in scope |

### Off-Hours Escalation

**7 T2 rules auto-promote to T1 execute** when no operator is available to cancel. Business hours are defined as **Monday–Friday 08:00–17:00 US/Pacific (DST-aware)** — weekends and outside those hours are off-hours. Entry point: `_is_off_hours_pt()` in `backend/defender_agent.py`.

Rules with `off_hours_escalate=True`:
1. Password spray / brute force → `disable_sign_in`
2. MFA fatigue → `disable_sign_in`
3. AiTM / session hijacking → `revoke_sessions`
4. Anomalous token (medium severity) → `disable_sign_in`
5. Inbox rule manipulation (medium severity) → `disable_sign_in`
6. BEC / email impersonation → `disable_sign_in`
7. PRT / Primary Refresh Token theft → `revoke_sessions`

**Operator note**: if working outside Pacific business hours and you want to review before action, cancel any queued T2 decisions immediately on arriving at the feed — off-hours T2s promote automatically and there is no second window.

---

## Site Scope

`security.movedocs.com` is the **4th site scope** in this repo, alongside `primary` (it-app.movedocs.com), `oasisdev` (oasisdev.movedocs.com), and `azure` (azure.movedocs.com). It is a dedicated security-ops surface with Entra-only auth — `AZURE_AUTH_PROVIDER=entra` is required, not a config option.

- **Auth**: Entra-only (no Atlassian/Jira login)
- **All authenticated users are operators** — no in-app RBAC tier; access is gated at the Entra level
- **No Jira integration** — pure security-ops surface
- **No reporting page, no Knowledge Base in nav**

**Backend scope guard**: all security backend routes accept both `azure` and `security` scopes (guards call `_ensure_azure_site()` or equivalent). New routes targeting the security surface must include both scopes in their guard. The `security` scope enforces Entra-only auth as a hard constraint — do not add Atlassian auth fallback to security-scoped routes.

### Site Relationship — security.movedocs.com vs. azure.movedocs.com

Both sites share the same backend routes and all 11 review lanes. The distinction is surface and audience:

| | security.movedocs.com | azure.movedocs.com |
|---|---|---|
| Auth | Entra-only | Atlassian or Entra |
| Audience | Dedicated security operators | IT operators who also work helpdesk |
| Jira surface | None | Full helpdesk |
| Defender Agent | Yes (landing page) | Yes (available in nav) |
| AI-08 lane summaries | Yes | Yes — same backend endpoint serves both scopes |
| AI-05 model picker | Admin panel on Security Overview | Not surfaced (backend accepts both) |
| Copilot model picker | Removed (admin-controlled only) | Per-session override retained |
| Teams digest | Config in `.env`; fires regardless of site | Same service |

### Nav Order (implemented)
1. Defender Agent (home / landing page)
2. Security Overview
3. Copilot
4. Tools
5. Access Review
6. Identity Review
7. User Review
8. Guest Access Review
9. App Hygiene
10. Device Compliance
11. Account Health
12. DLP Review
13. Conditional Access Tracker
14. Break Glass Validation
15. Directory Role Review

---

## Operator Workflow

### Reactive — alert fires

1. Defender Agent (background) classifies the alert within 2 minutes of detection.
2. **T1** decisions execute automatically (session revoke, device sync). Operator sees the result in the feed; no action required unless they want to investigate further.
3. **T2** decisions enter a delayed queue with a cancellation window (default: off-hours gating). Operator reviews the T2 queue and cancels if the alert is a false positive before `not_before_at` passes.
4. **T3** decisions surface in the feed as "recommend only." Operator reviews the AI narrative, opens Copilot via the "Investigate with Copilot" button, runs the investigation, saves findings back to the decision via "Save to Decision," then approves or dismisses.
5. **AI fallback** decisions (no built-in rule matched) are always T3. Treat them with extra scrutiny — the AI classification is a best-effort suggestion.

### Proactive — morning hygiene pass

1. **Teams digest** arrives at the configured hour (default 8 AM UTC). Review the 24h summary: decision counts by tier, unresolved T3s, top alert categories.
2. **Security Overview hub cards** show AI teasers for each review lane. Cards ranked by attention score — highest-severity lanes appear in "Needs Attention Now."
3. Open flagged lanes and read the AI triage summary panel at the top of each lane page for specific findings. Work down the priority list.
4. Use **Copilot** for deeper investigation on specific accounts, devices, or apps surfaced by the lane review. DLP Review starts in Copilot's `dlp_finding` mode for pasted Purview findings.

### Degraded mode — security Ollama runtime unavailable

Quick diagnostic: `curl http://10.76.1.180:11434/api/tags` — if it fails or times out, all AI features degrade silently.

| Feature | What operator sees | Impact |
|---|---|---|
| Copilot | HTTP 400 "No AI model available" | Cannot run investigations |
| AI fallback classifier | Unmatched alerts fall through to `skip` (logged) | Rule-based T1/T2 unaffected |
| AI narratives | Narrative column blank; "Generate" button silently fails | Feed still usable |
| Daily digest | No Teams message sent; logged warning | No operational impact |
| Lane summaries | Stale `generated_at` timestamp; panel shows last cached summary | Summaries age but remain readable |

Rule-based Defender Agent classification (T1/T2 auto-remediation) continues unaffected during a runtime outage — only AI-augmented paths are blocked.

---

## Configuration Reference

### Ollama Security Runtime

| Variable | Default | What it controls | Required |
|---|---|---|---|
| `OLLAMA_SECURITY_ENABLED` | `1` | Enables the security Ollama runtime | Yes |
| `OLLAMA_SECURITY_BASE_URL` | `http://10.76.1.180:11434` | Security Ollama host | Yes |
| `OLLAMA_SECURITY_MODEL` | `gemma4:31b` | Startup model default (overridden by DB config at runtime) | Yes |

### Defender Agent Notifications

Real-time per-decision Teams pings — distinct from the daily digest.

| Variable | Default | What it controls | Required |
|---|---|---|---|
| `DEFENDER_AGENT_TEAMS_WEBHOOK_URL` | _(empty)_ | Teams webhook for per-decision alerts; agent skips Teams if empty | No |
| `DEFENDER_AGENT_TEAMS_NOTIFY_T1` | `true` | Send Teams ping on T1 auto-execute decisions | No |
| `DEFENDER_AGENT_TEAMS_NOTIFY_T2` | `true` | Send Teams ping on T2 queued decisions | No |

### Digest Service

| Variable | Default | What it controls | Required |
|---|---|---|---|
| `SECURITY_DIGEST_TEAMS_WEBHOOK` | _(empty)_ | Teams webhook URL for daily digest; service no-ops if empty | No |
| `SECURITY_DIGEST_HOUR` | `8` | UTC hour to fire daily digest | No |

### Lane Summary Service (AI-08)

| Variable | Default | What it controls | Required |
|---|---|---|---|
| `SECURITY_LANE_SUMMARY_INTERVAL_MINUTES` | `60` | How often the lane summary service regenerates all 9 lanes | No |

### Auth

| Variable | Default | What it controls | Required |
|---|---|---|---|
| `AZURE_AUTH_PROVIDER` | `entra` | Auth provider for `azure.movedocs.com` | Yes |
| `ENTRA_TENANT_ID` | — | Entra tenant for OAuth | Yes |
| `ENTRA_CLIENT_ID` | — | App registration client ID | Yes |
| `ENTRA_CLIENT_SECRET` | — | App registration client secret | Yes |

**Runtime model override (AI-05)**: after startup, an admin can change the active Ollama model via `PUT /api/azure/security/runtime-config` with `{"ollama_model": "model-id"}`. This writes to the `security_runtime_config` Postgres table and takes effect on the next AI call — no restart required. To revert to the env-var default, delete the DB row or set the key to an empty string.

### Action Types Reference

All action types the Defender Agent dispatches. Tier safety column shows the lowest tier at which the action may be auto-executed (T1 = automatic; T2 = queued with cancellation window; T3 = human approval required).

| Action | What it does | Min auto tier | Composite? |
|---|---|---|---|
| `revoke_sessions` | Invalidates all active Entra sessions for matched user(s) | T1 | No |
| `disable_sign_in` | Blocks sign-in for matched user(s) in Entra | T2 | No |
| `account_lockout` | Revoke sessions **and** disable sign-in together | T2 | Yes — `revoke_sessions` + `disable_sign_in` |
| `reset_password` | Queues Entra random password reset via `user_admin_jobs` | T3 (approval) | No |
| `device_sync` | Forces Intune policy sync on matched device | T1 | No |
| `run_av_scan` | Triggers full AV scan on matched device via MDE | T1 | No |
| `isolate_device` | Network-isolates device in MDE (preserves forensic state) | T2 | No |
| `unisolate_device` | Releases MDE network isolation | T2 | No |
| `device_wipe` | Full device wipe via Intune | T3 (approval) | No |
| `device_retire` | Retire device from Intune (softer than wipe) | T3 (approval) | No |
| `restrict_app_execution` | Blocks non-Microsoft binaries from running on device | T3 (approval) | No |
| `unrestrict_app_execution` | Releases app execution restriction | T2 | No |
| `start_investigation` | Triggers MDE automated investigation on device | T1 | No |
| `collect_investigation_package` | Collects forensic package from device via MDE | T2 | No |
| `stop_and_quarantine_file` | Stops process and quarantines malicious file on device | T1 | No |
| `create_block_indicator` | Creates tenant-wide IOC block (IP, domain, or file hash) in MDE | T2 | No |

---

## Implemented

| # | Feature | Files |
|---|---|---|
| S-01 | security.movedocs.com 4th site scope | `backend/site_context.py`, `backend/config.py` |
| S-02 | Entra-only auth for security scope | `backend/config.py` (`SECURITY_AUTH_PROVIDER=entra`) |
| S-03 | Security-only nav (15 items, Defender first) | `frontend/src/components/Layout.tsx` |
| S-04 | Root redirects to `/security/agent` | `frontend/src/App.tsx` |
| S-05 | Tools page included in security routes | `frontend/src/App.tsx` |
| S-06 | Security Copilot defaults to gemma4:31b on security site | `frontend/src/pages/AzureSecurityCopilotPage.tsx` |
| S-07 | Backend route guards accept `security` scope | `routes_azure_security.py`, `routes_defender_agent.py`, `routes_azure_security_copilot.py` |
| S-08 | Caddy TLS for security.movedocs.com | `Caddyfile` |
| S-09 | Approve button visible for all non-cancelled decisions | `AzureSecurityAgentPage.tsx`, `routes_defender_agent.py` |

---

## Implemented — AI Integration

| # | Feature | Status | Key Files |
|---|---|---|---|
| AI-01 | Investigate with Copilot (Defender → Copilot handoff) | ✅ Implemented | `AzureSecurityAgentPage.tsx`, `AzureSecurityCopilotPage.tsx` |
| AI-02 | AI Fallback Classification for Defender Agent | ✅ Implemented | `defender_agent.py`, `ai_client.py` (FIX-02 applied) |
| AI-03 | AI Narrative on Defender Decisions | ✅ Implemented | `defender_agent_store.py`, `routes_defender_agent.py`, `ai_client.py`, `AzureSecurityAgentPage.tsx` (FIX-04 applied) |
| AI-04 | Save Copilot Investigation to Decision | ✅ Implemented | `AzureSecurityCopilotPage.tsx` |
| AI-05 | Site-wide Model Picker (Admin) | ✅ Implemented | `routes_azure_security.py`, `defender_agent_store.py`, `AzureSecurityPage.tsx`, `ai_client.py` (FIX-01, FIX-06, FIX-07 applied) |
| AI-06 | Security Knowledge Base Category | ✅ Implemented | `knowledge_base.py`, `security_copilot.py`, `models.py`, migration 0018 (FIX-03 applied) |
| AI-07 | Daily Security Digest to Teams | ✅ Implemented | `security_digest_service.py`, `main.py`, `config.py`, `.env` |
| AI-08 | Security Lane AI Summaries | ✅ Implemented | `security_lane_summary_service.py`, `routes_azure_security.py`, `AzureSecurityLane.tsx`, `AzureSecurityPage.tsx`, migration 0019 |

### AI-01: Investigate with Copilot (Defender → Copilot handoff)
**How it works**: "Investigate with Copilot" button on each Defender decision row and detail drawer. Navigates to `/security/copilot?decisionId=<id>`. Copilot reads the param on mount, fetches the decision, builds a prompt from alert title/entities/severity/MITRE/reason, and auto-submits immediately via a `useRef` one-shot pattern that tracks the submitted decision ID (not a boolean) to prevent double-submit on re-render. A "Save to Decision" button appears when launched from a decision and posts the investigation markdown back to the decision notes.

### AI-02: AI Fallback Classification for Defender Agent
**How it works**: After built-in rules and custom rules both miss, `_ai_classify_alert_fallback()` calls `invoke_model_text()` with the security Ollama runtime. **Always caps at T3/recommend** regardless of model suggestion — AI-classified alerts are never auto-executed. Falls back to `skip` on model failure. The model used is resolved from `security_runtime_config` once per agent cycle (FIX-02), so the fallback classifier uses the same model as Copilot and the narrative generator.

### AI-03: AI Narrative on Defender Decisions
**How it works**: `ai_narrative` and `ai_narrative_generated_at` columns on `defender_agent_decisions` (migration 0018). Generated lazily via background task when a non-skip decision is fetched for the first time. Manual trigger via `POST /decisions/{id}/narrative`. The detail drawer shows the narrative in a blue block when present, or a "Generate AI summary" button when `ai_narrative` is null — available for all decision types including skip (FIX-04). Displayed as blue italic text below the action type in the feed row.

### AI-04: Save Copilot Investigation to Decision
**How it works**: When Copilot is opened with `?decisionId=`, a "Save to Decision" button appears in the export section. POSTs the full investigation markdown (truncated at 8 000 chars) to `POST /api/azure/security/defender-agent/decisions/{id}/notes`. Button shows saving/saved/error states.

### AI-05: Site-wide Model Picker (Admin)
**How it works**: `security_runtime_config` table in Postgres (migration 0018). `GET/PUT /api/azure/security/runtime-config` endpoints (admin-gated PUT). `AzureSecurityPage.tsx` shows a violet admin panel at the bottom for admins only, with a dropdown of available models from `/api/azure/security/copilot/models` and a Save button. The DB override is now wired into `get_default_security_copilot_model_id()` in `ai_client.py` (FIX-01), the Copilot page initial model state (FIX-06), and the lane summary service — so all AI features use the same runtime-resolved model without restart. The per-session model picker `<select>` is hidden on the security scope; only the admin panel may change the model there (FIX-07).

### AI-06: Security Knowledge Base Category
**How it works**: `category TEXT DEFAULT ''` column on `kb_articles` (migration 0018 + SQLite CREATE TABLE updated). `list_articles()` accepts `category=` filter. Security Copilot KB source prefers `category="security"` articles, falling back to all articles if none tagged. `KnowledgeBaseArticle` and `KnowledgeBaseArticleUpsertRequest` both have `category: str = ""` (FIX-03). `create_article()` and `update_article()` persist the category field. Seed import auto-tags `KB-SEC-*` articles as `category="security"` on first import.

### AI-07: Daily Security Digest to Teams
**How it works**: `security_digest_service.py` leader-only background service. Fires at `SECURITY_DIGEST_HOUR` UTC (default 8). Queries last 1 000 decisions for 24h stats (t1/t2/t3/skips/ai_fallback/unresolved_t3/top_categories/top_entities). Calls `generate_security_digest()` with the runtime-config-resolved model. Posts Teams Adaptive Card to `SECURITY_DIGEST_TEAMS_WEBHOOK`. No-ops if webhook is unconfigured.

### AI-08: Security Lane AI Summaries
**How it works**: `security_lane_summary_service.py` — leader-only background service that fires immediately on first start, then repeats on a configurable interval (default 60 minutes via `SECURITY_LANE_SUMMARY_INTERVAL_MINUTES`). Covers 9 data-rich review lanes: `access-review`, `conditional-access-tracker`, `break-glass-validation`, `identity-review`, `app-hygiene`, `user-review`, `guest-access-review`, `account-health`, `device-compliance`. Directory Role Review and DLP Review are excluded — directory roles has sparse enough data that a generic count summary adds little signal; DLP Review is Copilot-native (`dlp_finding` mode) and already gets AI output inline from the Copilot engine rather than a separate background job.

Per-lane data extraction: the 5 lanes with dedicated builders (`access-review`, `conditional-access-tracker`, `break-glass-validation`, `app-hygiene`, `device-compliance`) call their builders directly with a synthetic Entra system session for session-gated builders. The 4 workspace-summary lanes (`identity-review`, `user-review`, `guest-access-review`, `account-health`) call `build_security_workspace_summary()` once and extract per-lane attention data.

`generate_lane_summary()` in `ai_client.py` sends lane name + status + attention count + top 10 items as JSON to the security Ollama runtime with a JSON-only system prompt. Output shape: `{teaser, narrative, bullets}`. Results are persisted to `security_lane_ai_summaries` (migration 0019: `lane_key TEXT PRIMARY KEY, narrative, teaser, bullets_json, generated_at, model_used`).

Two endpoints: `GET /api/azure/security/lane-summaries` (all rows, both scopes) and `POST /api/azure/security/lane-summaries/{lane_key}/regenerate` (any authenticated user, enqueues background task). On the frontend, a shared `useQuery(["azure", "security", "lane-summaries"])` with 5-minute stale time is used by the `LaneSummaryPanel` component in `AzureSecurityLane.tsx`. The panel is collapsible, shows narrative + bulleted list, displays a relative timestamp ("Generated N min ago"), and has a Regenerate button. A quiet placeholder ("AI summary generates hourly — not yet available") is shown when no row exists yet. Hub cards on `AzureSecurityPage.tsx` show the `teaser` field in italic below the secondary label for both `LaneCard` and `PriorityLaneCard`.

---

## Delivery Log

All three phases complete as of 2026-04-22. RC parity rules expanded 2026-04-23.

- **Phase 1 — FIX-01–07** (2026-04-22): Runtime config wired into all AI model resolution paths; KB category field threaded end-to-end; AI narrative "Generate" button in decision drawer; handoff ref guard bug fixed; per-session model picker hidden on security scope. Single commit batch.
- **Phase 2 — AI-08 backend** (2026-04-22): `security_lane_summary_service.py`, migration 0019, `generate_lane_summary()` in `ai_client.py`, `GET/POST /lane-summaries` routes, `SECURITY_LANE_SUMMARY_INTERVAL_MINUTES` config.
- **Phase 3 — AI-08 frontend** (2026-04-22): `SecurityLaneAISummary` type + API calls in `api.ts`; `LaneSummaryPanel` component in `AzureSecurityLane.tsx`; hub card teasers in `AzureSecurityPage.tsx`; panel added to all 9 lane pages.
- **Phase 4 — RC parity expansion** (2026-04-23): 3 new rules added (Kerberoasting T2, PRT theft T2 with off_hours_escalate, defense evasion T1). Rule count 47 → 50. Plan updated with rule-category table, action types reference, RC parity coverage tables, off-hours escalation list, MITRE technique extraction gap, custom rules/overrides note, Defender Agent notification config, 4th-scope context, backend scope guard note.

---

## ✅ Complete — AI Gap Fixes (Phase 1)

Gaps identified in the post-implementation review. All implemented as a single commit batch (2026-04-22).

| # | Gap | Fix |
|---|---|---|
| FIX-01 | AI-05 runtime config not wired into Copilot server-side default | `get_default_security_copilot_model_id()` reads `security_runtime_config.ollama_model` before falling back to `OLLAMA_SECURITY_MODEL` |
| FIX-02 | AI-02 fallback classifier ignores runtime config | `_run_agent_cycle()` reads runtime config once per cycle, passes resolved model to `_ai_classify_alert_fallback()` |
| FIX-03 | AI-06 category field missing from upsert request | Add `category: str = ""` to `KnowledgeBaseArticleUpsertRequest`; thread through `create_article()` and `update_article()`; auto-tag KB-SEC-001 seed article on import |
| FIX-04 | AI-03 no "Generate" button for skip/failed decisions | Add "Generate AI summary" button in decision detail drawer when `ai_narrative` is null — triggers `POST /decisions/{id}/narrative` mutation, invalidates decision query |
| FIX-05 | AI-01 handoff ref guard breaks on second decision from same Copilot session | Change `handoffSubmittedRef` from `boolean` to `string \| null`; guard compares against current `handoffDecisionId` instead of `true` |
| FIX-06 | Copilot initial model hardcoded to `"gemma4:31b"` on security site | Fetch `GET /api/azure/security/runtime-config` on mount; use `config.ollama_model \|\| "gemma4:31b"` as initial model state |
| FIX-07 | Per-session model picker shown on security site (all requests must use security LLM) | Hide model picker `<select>` and model label when `getSiteBranding().scope === "security"`; model is admin-controlled via AI-05 only |

---

## ✅ Complete — AI-08: Security Lane AI Summaries (Phases 2–3)

**What**: Each of the 9 data-rich review lanes gets an AI-generated triage summary: a 1-sentence teaser shown on the Security Overview hub card, and a full narrative + 3–5 actionable bullet points shown in a collapsible panel at the top of each lane page.

**Lanes covered** (all with `summaryMode: "count"`, excluding Defender Agent which is covered by AI-03/AI-07):
`access-review`, `conditional-access-tracker`, `break-glass-validation`, `identity-review`, `app-hygiene`, `user-review`, `guest-access-review`, `account-health`, `device-compliance`

**Architecture**:
- New `backend/security_lane_summary_service.py` — leader-only background service on a 60-minute fixed loop (configurable via `SECURITY_LANE_SUMMARY_INTERVAL_MINUTES`, default 60); fires immediately on first start
- Uses a synthetic system session `{"auth_provider": "entra", "is_admin": True}` for session-gated builders (`device_compliance`, `conditional_access_tracker`)
- For `identity-review`, `user-review`, `guest-access-review`, `account-health`: calls `build_security_workspace_summary(system_session)` once and extracts attention data
- For the 5 lanes with dedicated builders: calls each builder directly
- Generic prompt template: lane name + status + attention count + top 10 items as JSON → one paragraph (50 words max) + 3–5 bullets
- All calls use security Ollama runtime (gemma4:31b or runtime config model)
- New `security_lane_ai_summaries` table: `lane_key TEXT PRIMARY KEY, narrative TEXT, teaser TEXT, bullets_json TEXT, generated_at TEXT, model_used TEXT`
- New endpoints: `GET /api/azure/security/lane-summaries` (all rows, both azure and security scopes), `POST /api/azure/security/lane-summaries/{lane_key}/regenerate` (any authenticated user on either scope, runs as background task)

**Frontend**:
- `AzureSecurityPage.tsx` hub cards: show `teaser` field below the `secondary_label` when available
- Each of 9 lane pages: collapsible "AI Triage Summary" panel at the top, showing `narrative` + bulleted `bullets_json`; "Generated N min ago" label; "Regenerate" button
- Quiet placeholder ("AI summary generates hourly — not yet available") when no row exists for a lane
- Shared `useQuery(["azure", "security", "lane-summaries"])` with 5-minute stale time across all lane pages

**Storage migration**: `backend/storage_migrations/0019_security_lane_ai_summaries.sql`

### Acceptance Criteria

**Functional** ✅:
- All 9 lanes produce summaries within 60 minutes of first service start
- Hub card teasers appear on the Security Overview for lanes with summaries
- Regenerate endpoint enqueues a background task and returns immediately
- Quiet placeholder shown correctly on first run before any summary exists

**Quality signal**:
- Each narrative references at least one specific count or entity name (not generic filler like "there are some issues")
- Evaluate on first real tenant run; if output is too vague, promote per-lane payload shaping from Deferred to active work

**Degraded** ✅:
- Stale `generated_at` timestamp visible in panel so operators know data age
- When runtime is down, last cached summary remains readable; no panel crash or blank screen

---

## Deferred / Future

| Item | Why deferred |
|---|---|
| **Copilot remediation actions** | Safety/audit complexity; Defender Agent is the single action executor. Revisit when audit trail for dual-path mutations is designed. |
| **External threat intelligence** — VirusTotal, MITRE ATT&CK API | API key management, latency, cost. Internal sources sufficient for now. |
| **AI risk score on feed** | Redundant with Defender severity + AI narrative; creates competing signals. |
| **Teams webhook admin UI** | AI-07 webhook configured via env var for now; admin UI in AzureSecurityPage.tsx deferred. |
| **Per-lane AI summary prompt tuning** | Start generic; add lane-specific payload shaping only if output proves too vague after real use. Promote to active if narratives consistently lack specific counts or entity names — the first signal is the lane summary panel on a real tenant. Entry point: `generate_lane_summary()` in `ai_client.py` and the `_get_lane_data()` extractors in `security_lane_summary_service.py`. |
| **S-10: Per-session Copilot model override** | Removed on security.movedocs.com by FIX-07 — all Copilot requests use the admin-configured security runtime model. Per-session override remains available on azure.movedocs.com. |
| **MITRE technique-ID rule matching** | `_extract_mitre_techniques()` in `defender_agent.py` already parses ATT&CK IDs from alert evidence and stores them on decisions, but the rule classifier uses only title/category keywords. Add a `technique_ids` field to the rule schema; classifier tests extracted IDs as an OR-condition alongside title keywords. Promotes NTLM relay and Kerberos delegation abuse rules from "not yet covered" to implementable. Entry point: `_classify_alert()` and `_extract_mitre_techniques()` in `backend/defender_agent.py`. |
| **NTLM relay / SMB relay rule** | Title keywords too inconsistent across alert sources. Implement once MITRE technique-ID matching (T1557) is available. |
| **Kerberos delegation abuse rule** | Low prevalence; implement once MITRE T1134.001/T1558.003 matching is available. |
