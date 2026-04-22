# Security Portal Plan — security.movedocs.com

Tracks what is built, what is agreed, and what is deferred for the dedicated security portal.

---

## Current Architecture

| Component | What it does | AI |
|---|---|---|
| **Defender Agent** | Polls Microsoft Defender alerts every 2 min; auto-remediates T1, queues T2, surfaces T3 for approval | 47 built-in rules + custom rules + AI fallback classifier (gemma4:31b, always T3-capped) |
| **Security Copilot** | On-demand investigation workbench; queries 16 internal sources, synthesizes with Ollama | gemma4:31b by default (admin-configurable via AI-05 runtime config); isolated security Ollama runtime |
| **Security Review Lanes** | 11 periodic-audit surfaces (Access, Identity, Users, Guests, Apps, Devices, Account Health, DLP, CA Tracker, Break-glass, Directory Roles) | AI-08 lane summaries planned — 9 lanes, 60-min generation cycle |
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

## Site Scope

- **URL**: `security.movedocs.com`
- **Auth**: Entra-only (no Atlassian/Jira login)
- **All authenticated users are operators** — no in-app RBAC tier; access is gated at the Entra level
- **No Jira integration** — pure security-ops surface
- **No reporting page, no Knowledge Base in nav**

### Site Relationship — security.movedocs.com vs. azure.movedocs.com

Both sites share the same backend routes (guards accept both `azure` and `security` scopes) and all 11 review lanes. The distinction is surface and audience:

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
2. **Security Overview hub cards** show AI teasers for each review lane (once AI-08 is live). Cards ranked by attention score — highest-severity lanes appear in "Needs Attention Now."
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

### Digest Service

| Variable | Default | What it controls | Required |
|---|---|---|---|
| `SECURITY_DIGEST_TEAMS_WEBHOOK` | _(empty)_ | Teams webhook URL; service no-ops if empty | No |
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
| AI-02 | AI Fallback Classification for Defender Agent | ✅ Implemented | `defender_agent.py`, `ai_client.py` |
| AI-03 | AI Narrative on Defender Decisions | ✅ Implemented | `defender_agent_store.py`, `routes_defender_agent.py`, `ai_client.py`, `AzureSecurityAgentPage.tsx` |
| AI-04 | Save Copilot Investigation to Decision | ✅ Implemented | `AzureSecurityCopilotPage.tsx` |
| AI-05 | Site-wide Model Picker (Admin) | ✅ Implemented | `routes_azure_security.py`, `defender_agent_store.py`, `AzureSecurityPage.tsx` |
| AI-06 | Security Knowledge Base Category | ✅ Implemented | `knowledge_base.py`, `security_copilot.py`, `models.py`, migration 0018 |
| AI-07 | Daily Security Digest to Teams | ✅ Implemented | `security_digest_service.py`, `main.py`, `config.py`, `.env` |

### AI-01: Investigate with Copilot (Defender → Copilot handoff)
**How it works**: "Investigate with Copilot" button on each Defender decision row and detail drawer. Navigates to `/security/copilot?decisionId=<id>`. Copilot reads the param on mount, fetches the decision, builds a prompt from alert title/entities/severity/MITRE/reason, and auto-submits immediately via `useRef` one-shot pattern. A "Save to Decision" button appears when launched from a decision and posts the investigation markdown back to the decision notes.

### AI-02: AI Fallback Classification for Defender Agent
**How it works**: After built-in rules and custom rules both miss, `_ai_classify_alert_fallback()` calls `invoke_model_text()` with the security Ollama runtime. **Always caps at T3/recommend** regardless of model suggestion — AI-classified alerts are never auto-executed. Falls back to `skip` on model failure.

### AI-03: AI Narrative on Defender Decisions
**How it works**: `ai_narrative` and `ai_narrative_generated_at` columns on `defender_agent_decisions` (migration 0018). Generated lazily via background task when a non-skip decision is fetched for the first time. Manual trigger via `POST /decisions/{id}/narrative`. Displayed as blue italic text below the action type in the feed row. Skip decisions require manual trigger.

### AI-04: Save Copilot Investigation to Decision
**How it works**: When Copilot is opened with `?decisionId=`, a "Save to Decision" button appears in the export section. POSTs the full investigation markdown (truncated at 8 000 chars) to `POST /api/azure/security/defender-agent/decisions/{id}/notes`. Button shows saving/saved/error states.

### AI-05: Site-wide Model Picker (Admin)
**How it works**: `security_runtime_config` table in Postgres (migration 0018). `GET/PUT /api/azure/security/runtime-config` endpoints (admin-gated PUT). `AzureSecurityPage.tsx` shows a violet admin panel at the bottom for admins only, with a dropdown of available models from `/api/azure/security/copilot/models` and a Save button.

### AI-06: Security Knowledge Base Category
**How it works**: `category TEXT DEFAULT ''` column on `kb_articles` (migration 0018 + SQLite CREATE TABLE updated). `list_articles()` accepts `category=` filter. Security Copilot KB source prefers `category="security"` articles, falling back to all articles if none tagged. `KnowledgeBaseArticle` model has `category: str = ""`.

### AI-07: Daily Security Digest to Teams
**How it works**: `security_digest_service.py` leader-only background service. Fires at `SECURITY_DIGEST_HOUR` UTC (default 8). Queries last 1 000 decisions for 24h stats (t1/t2/t3/skips/ai_fallback/unresolved_t3/top_categories/top_entities). Calls `generate_security_digest()` with gemma4:31b. Posts Teams Adaptive Card to `SECURITY_DIGEST_TEAMS_WEBHOOK`. No-ops if webhook is unconfigured.

---

## Implementation Order

### Phase 1 — FIX batch (prerequisite for Phase 2)
*Scope: ~7 focused changes in existing files — single commit batch.*

FIX-01 through FIX-07 must land first because they establish the runtime config as the canonical model source. AI-08 lane summaries must use the same model resolution path.

### Phase 2 — AI-08 backend
*Scope: new service file, migration, config, 2 new API endpoints.*

- Storage migration 0019
- `security_lane_summary_service.py` and `main.py` wiring
- `GET /api/azure/security/lane-summaries` + `POST /lane-summaries/{key}/regenerate`
- `ai_client.py` `generate_lane_summary()` function and priority queue entry

### Phase 3 — AI-08 frontend
*Scope: shared query hook, hub card teasers, 9 lane page panels.*

- `api.ts` types and API calls
- Hub card teasers in `AzureSecurityPage.tsx`
- Collapsible AI summary panel in each of the 9 lane pages

---

## Planned — AI Gap Fixes (Phase 1)

These gaps were identified in the post-implementation review. All are agreed. Implement as a single commit batch.

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

## Planned — AI-08: Security Lane AI Summaries (Phases 2–3)

**What**: Each of the 9 data-rich review lanes gets an AI-generated triage summary: a 1-sentence teaser shown on the Security Overview hub card, and a full narrative + 3–5 actionable bullet points shown in a collapsible panel at the top of each lane page.

**Lanes covered** (all with `summaryMode: "count"`, excluding Defender Agent which is covered by AI-03/AI-07):
`access-review`, `conditional-access-tracker`, `break-glass-validation`, `identity-review`, `app-hygiene`, `user-review`, `guest-access-review`, `account-health`, `device-compliance`

**Architecture**:
- New `backend/security_lane_summary_service.py` — leader-only background service on a 60-minute fixed loop (configurable via `SECURITY_LANE_SUMMARY_INTERVAL_MINUTES`, default 60)
- Uses a synthetic system session `{"auth_provider": "entra", "is_admin": True}` for session-gated builders (`device_compliance`, `conditional_access_tracker`)
- For `identity-review`, `user-review`, `guest-access-review`, `account-health`: calls `build_security_workspace_summary(system_session)` once and extracts attention data; supplements with `azure_cache._snapshot()` for top items
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

**Files to create/modify**:
- `backend/security_lane_summary_service.py` — new
- `backend/storage_migrations/0019_security_lane_ai_summaries.sql` — new
- `backend/main.py` — start service as leader-only
- `backend/config.py` — `SECURITY_LANE_SUMMARY_INTERVAL_MINUTES`
- `backend/.env` — add config var
- `backend/ai_client.py` — add `generate_lane_summary()` function and priority queue entry
- `backend/routes_azure_security.py` — GET /lane-summaries + POST /lane-summaries/{key}/regenerate
- `frontend/src/lib/api.ts` — `SecurityLaneAISummary` type + `getLaneSummaries()` + `regenerateLaneSummary()`
- `frontend/src/pages/AzureSecurityPage.tsx` — teaser in hub cards
- `frontend/src/pages/AzureSecurityAccessReviewPage.tsx` — AI summary panel
- `frontend/src/pages/AzureSecurityConditionalAccessTrackerPage.tsx` — AI summary panel
- `frontend/src/pages/AzureSecurityBreakGlassValidationPage.tsx` — AI summary panel
- `frontend/src/pages/AzureSecurityIdentityReviewPage.tsx` — AI summary panel
- `frontend/src/pages/AzureSecurityAppHygienePage.tsx` — AI summary panel
- `frontend/src/pages/AzureSecurityUserReviewPage.tsx` — AI summary panel
- `frontend/src/pages/AzureSecurityGuestAccessReviewPage.tsx` — AI summary panel
- `frontend/src/pages/AzureAccountHealthPage.tsx` — AI summary panel
- `frontend/src/pages/AzureSecurityDeviceCompliancePage.tsx` — AI summary panel

### Acceptance Criteria

**Functional**:
- All 9 lanes produce summaries within 60 minutes of first service start
- Hub card teasers appear on the Security Overview for lanes with summaries
- Regenerate endpoint enqueues a background task and returns immediately
- Quiet placeholder shown correctly on first run before any summary exists

**Quality signal**:
- Each narrative references at least one specific count or entity name (not generic filler like "there are some issues")
- Evaluate on first real tenant run; if output is too vague, promote per-lane payload shaping from Deferred to active work

**Degraded**:
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
| **Per-lane AI summary prompt tuning** | Start generic; add lane-specific payload shaping only if output proves too vague after real use. |
| **S-10: Per-session Copilot model override** | Removed on security.movedocs.com by FIX-07 — all Copilot requests use the admin-configured security runtime model. Per-session override remains available on azure.movedocs.com. |
