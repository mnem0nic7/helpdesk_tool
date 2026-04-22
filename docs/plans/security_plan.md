# Security Portal Plan — security.movedocs.com

Tracks what is built, what is agreed, and what is deferred for the dedicated security portal.

---

## Current Architecture

| Component | What it does | AI? |
|---|---|---|
| **Defender Agent** | Polls Microsoft Defender alerts every 2 min; auto-remediates T1, queues T2, surfaces T3 for approval | Rule-based only (67 built-in rules + custom rules) |
| **Security Copilot** | On-demand investigation workbench; queries 16 internal sources, synthesizes with Ollama | gemma4:31b on 10.76.1.180 |
| **Security Review Lanes** | 11 periodic-audit surfaces (Access, Identity, Users, Guests, Apps, Devices, Account Health, DLP, CA Tracker, Break-glass, Directory Roles) | None |
| **Tools** | Login audit, mailbox delegate lookup, OneDrive copy | None |

### Ollama Security Runtime
- **Host**: `http://10.76.1.180:11434`
- **Model**: `gemma4:31b`
- **Config**: `OLLAMA_SECURITY_ENABLED`, `OLLAMA_SECURITY_BASE_URL`, `OLLAMA_SECURITY_MODEL` in `backend/.env`
- Isolated from the default Ollama queue used by helpdesk triage

---

## Site Scope

- **URL**: `security.movedocs.com`
- **Auth**: Entra-only (no Atlassian/Jira login)
- **All authenticated users are operators** — no in-app RBAC tier; access is gated at the Entra level
- **No Jira integration** — pure security-ops surface
- **No reporting page, no Knowledge Base in nav**

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
| S-10 | Security Copilot model picker per-session override | `AzureSecurityCopilotPage.tsx` |

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
**How it works**: `ai_narrative` and `ai_narrative_generated_at` columns on `defender_agent_decisions` (migration 0018). Generated lazily via background task when a non-skip decision is fetched for the first time. Manual trigger via `POST /decisions/{id}/narrative`. Displayed as blue italic text below the action type in the feed row. Agents with `decision == "skip"` require manual trigger.

### AI-04: Save Copilot Investigation to Decision
**How it works**: When Copilot is opened with `?decisionId=`, a "Save to Decision" button appears in the export section. POSTs the full investigation markdown to `POST /api/azure/security/defender-agent/decisions/{id}/notes` (existing endpoint). Button shows saving/saved/error states.

### AI-05: Site-wide Model Picker (Admin)
**How it works**: `security_runtime_config` table in Postgres (migration 0018). `GET/PUT /api/azure/security/runtime-config` endpoints (admin-gated PUT). `AzureSecurityPage.tsx` shows a violet admin panel at the bottom for admins only, with a dropdown of available models from `/api/azure/security/copilot/models` and a Save button.

### AI-06: Security Knowledge Base Category
**How it works**: `category TEXT DEFAULT ''` column on `kb_articles` (migration 0018 + SQLite CREATE TABLE updated). `list_articles()` accepts `category=` filter. Security Copilot KB source prefers `category="security"` articles, falling back to all articles if none tagged. `KnowledgeBaseArticle` model has `category: str = ""`.

### AI-07: Daily Security Digest to Teams
**How it works**: `security_digest_service.py` leader-only background service. Fires at `SECURITY_DIGEST_HOUR` UTC (default 8). Queries last 1000 decisions for 24h stats (t1/t2/t3/skips/ai_fallback/unresolved_t3/top_categories/top_entities). Calls `generate_security_digest()` with gemma4:31b. Posts Teams Adaptive Card to `SECURITY_DIGEST_TEAMS_WEBHOOK`. No-ops if webhook is unconfigured.

---

## Planned — AI Gap Fixes (implement next)

These gaps were identified in the post-implementation review. All are agreed. Implement in one commit batch.

| # | Gap | Fix |
|---|---|---|
| FIX-01 | AI-05 runtime config not wired into Copilot server-side default | `get_default_security_copilot_model_id()` reads `security_runtime_config.ollama_model` before falling back to `OLLAMA_SECURITY_MODEL` |
| FIX-02 | AI-02 fallback classifier ignores runtime config | `_run_agent_cycle()` reads runtime config once per cycle, passes resolved model to `_ai_classify_alert_fallback()` |
| FIX-03 | AI-06 category field missing from upsert request | Add `category: str = ""` to `KnowledgeBaseArticleUpsertRequest`; thread through `create_article()` and `update_article()`; auto-tag KB-SEC-001 seed article on import |
| FIX-04 | AI-03 no "Generate" button for skip/failed decisions | Add "Generate AI summary" button in decision detail drawer when `ai_narrative` is null — triggers `POST /decisions/{id}/narrative` mutation, invalidates decision query |
| FIX-05 | AI-01 handoff ref guard breaks on second decision from same Copilot session | Change `handoffSubmittedRef` from `boolean` to `string | null`; guard compares against current `handoffDecisionId` instead of `true` |
| FIX-06 | Copilot initial model hardcoded to `"gemma4:31b"` on security site | Fetch `GET /api/azure/security/runtime-config` on mount; use `config.ollama_model \|\| "gemma4:31b"` as initial model state |
| FIX-07 | Per-session model picker shown on security site (all requests must use security LLM) | Hide model picker `<select>` and model label when `getSiteBranding().scope === "security"`; model is admin-controlled via AI-05 only |

---

## Planned — AI-08: Security Lane AI Summaries

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
- New endpoints: `GET /api/azure/security/lane-summaries` (all rows), `POST /api/azure/security/lane-summaries/{lane_key}/regenerate` (any authenticated security site user, runs as background task)

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
- 9 lane page `.tsx` files — collapsible AI summary panel

---

## Deferred / Future

| Item | Why deferred |
|---|---|
| **Copilot remediation actions** | Safety/audit complexity; Defender Agent is the single action executor. Revisit when audit trail for dual-path mutations is designed. |
| **External threat intelligence** — VirusTotal, MITRE ATT&CK API | API key management, latency, cost. Internal sources sufficient for now. |
| **AI risk score on feed** | Redundant with Defender severity + AI narrative; creates competing signals. |
| **Teams webhook admin UI** | AI-07 webhook configured via env var for now; admin UI in AzureSecurityPage.tsx deferred. |
| **Per-lane AI summary prompt tuning** | Start generic (FIX batch above); add lane-specific payload shaping only if output proves too vague after real use. |
