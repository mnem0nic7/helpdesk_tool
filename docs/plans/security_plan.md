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

## Deferred / Future

| Item | Why deferred |
|---|---|
| **Copilot remediation actions** (Q4) | Safety/audit complexity; Defender Agent is the single action executor. Revisit when audit trail for dual-path mutations is designed. |
| **External threat intelligence** (Q6) — VirusTotal, MITRE ATT&CK API | API key management, latency, cost. Internal sources sufficient for now. |
| **AI risk score on feed** (Q9) | Redundant with Defender severity + AI narrative; creates competing signals. |
| **Teams webhook admin UI** | AI-07 webhook configured via env var for now; admin UI in AzureSecurityPage.tsx deferred. |
