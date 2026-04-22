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

## Planned — AI Integration

### AI-01: Investigate with Copilot (Defender → Copilot handoff)
**What**: "Investigate with Copilot" button on each Defender Agent decision row (and detail drawer). Opens the Copilot pre-seeded with alert title, entities, severity, MITRE techniques, and `decision_id`. Auto-submits immediately — no manual re-click.

**How**: URL navigation to `/security/copilot?decisionId=<id>`. Copilot page reads the query param on mount, fetches the decision, builds a structured prompt, and fires the first investigation turn automatically.

**Files to change**:
- `frontend/src/pages/AzureSecurityAgentPage.tsx` — add "Investigate" button
- `frontend/src/pages/AzureSecurityCopilotPage.tsx` — read `?decisionId=` param, auto-submit on mount
- `backend/routes_defender_agent.py` — `GET /api/azure/security/defender-agent/decisions/{id}` already exists ✓

---

### AI-02: AI Fallback Classification for Defender Agent
**What**: When no built-in or custom rule matches a Defender alert, send the alert title, description, category, and severity to gemma4:31b. Ask it to suggest a tier (1/2/3) and action. Log result as a `recommend` (T3) decision with `reason: "AI fallback — <model>"`. **Never auto-execute AI-classified alerts.**

**How**: In `defender_agent.py`, after the rule-matching loop returns no match, call `invoke_model_text()` with `feature_surface="defender_agent_fallback"`. Route to security Ollama runtime. Parse structured JSON response (tier, action, reasoning). Fallback to `skip` if model returns invalid JSON.

**Files to change**:
- `backend/defender_agent.py` — add `_ai_classify_alert()` function, call after rule miss
- `backend/ai_client.py` — add `defender_agent_fallback` priority queue entry

---

### AI-03: AI Narrative on Defender Decisions
**What**: Each Defender decision (where `decision != "skip"`) gets a one-line AI-generated narrative stored in the decision record. Generated lazily on first view of the decision, then cached. Skip decisions can be manually triggered to generate a narrative via a button.

**How**: New field `ai_narrative` on `defender_agent_decisions` table (Postgres migration required). On `GET /api/azure/security/defender-agent/decisions/{id}`, if `ai_narrative` is null and `decision != "skip"`, generate it asynchronously (or on-demand). New endpoint `POST /api/azure/security/defender-agent/decisions/{id}/narrative` for manual trigger.

**Files to change**:
- `backend/storage_migrations/` — add migration for `ai_narrative` column
- `backend/defender_agent_store.py` — `set_decision_narrative()` 
- `backend/routes_defender_agent.py` — trigger on fetch if null; add `/narrative` endpoint
- `backend/ai_client.py` — narrative prompt for `defender_agent_narrative` surface
- `frontend/src/pages/AzureSecurityAgentPage.tsx` — display narrative in feed row + detail drawer; add "Generate" button for skips

---

### AI-04: Save Copilot Investigation to Decision
**What**: When the Copilot is launched from a Defender decision (via AI-01), a "Save to decision" button appears alongside the existing export. Posts the investigation markdown to the decision's investigation notes.

**How**: Pass `decision_id` through the Copilot session state (from the `?decisionId=` URL param). The "Save to decision" button calls `POST /api/azure/security/defender-agent/decisions/{id}/notes` (already exists as investigation notes endpoint — check). Display a toast confirming the save.

**Files to change**:
- `frontend/src/pages/AzureSecurityCopilotPage.tsx` — persist `decisionId` in state, show "Save to decision" button when set
- `backend/routes_defender_agent.py` — verify `/notes` endpoint exists or add it

---

### AI-05: Site-wide Model Picker (Admin)
**What**: Admin-only control in the Security Overview page to change the active Ollama model site-wide. Stores the selection in the backend as a runtime config override (no `.env` edit, no restart required). All subsequent Copilot sessions and AI fallback calls use the new model.

**How**: New `security_runtime_config` key in a lightweight backend settings store (or extend the existing defender agent config pattern). New endpoint `GET/PUT /api/azure/security/runtime-config` (admin-only). Security Overview page shows a model picker dropdown loaded from `/api/azure/security/copilot/models`.

**Files to change**:
- `backend/routes_azure_security.py` — add runtime config endpoints
- `backend/security_workspace_summary.py` (or new `security_runtime_config.py`) — store/retrieve config
- `backend/ai_client.py` — check runtime config before falling back to `OLLAMA_SECURITY_MODEL`
- `frontend/src/pages/AzureSecurityPage.tsx` — admin model picker UI

---

### AI-06: Security Knowledge Base Category
**What**: KB articles tagged with `category: security` are queried by the Security Copilot. Helpdesk KB queries exclude this category. Seed with IR playbooks, break-glass procedures, escalation contacts.

**How**: Add optional `category` field to KB article schema. Security Copilot source builder passes `category_filter="security"` when querying KB. Existing KB admin interface (if any) gets a category field. No new DB tables.

**Files to change**:
- `backend/knowledge_base.py` — add `category` filter to search
- `backend/security_copilot.py` — pass `category_filter="security"` in KB source
- `backend/storage_migrations/` — `ADD COLUMN IF NOT EXISTS category TEXT` on KB table

---

### AI-07: Daily Security Digest to Teams
**What**: Once-daily Teams message (configurable time, default 8 AM local) summarizing the prior 24h of Defender activity: decisions by tier, unresolved T3s, top 3 alert categories, any AI fallback classifications. Written by gemma4:31b. Sent to a configurable Teams webhook URL.

**How**: New background service `security_digest_service.py` started as leader-only at startup. Reads aggregated decision data from `defender_agent_store`. Builds a summary dict, calls `invoke_model_text()` with `feature_surface="security_digest"`, POSTs to Teams webhook. Webhook URL stored in backend config (env var `SECURITY_DIGEST_TEAMS_WEBHOOK`).

**Files to change**:
- `backend/security_digest_service.py` — new file
- `backend/main.py` — start as leader-only background service
- `backend/.env` — add `SECURITY_DIGEST_TEAMS_WEBHOOK` and `SECURITY_DIGEST_HOUR` vars
- `frontend/src/pages/AzureSecurityPage.tsx` — (future) admin UI to configure webhook

---

## Deferred / Future

| Item | Why deferred |
|---|---|
| **Copilot remediation actions** (Q4) | Safety/audit complexity; Defender Agent is the single action executor. Revisit when audit trail for dual-path mutations is designed. |
| **External threat intelligence** (Q6) — VirusTotal, MITRE ATT&CK API | API key management, latency, cost. Internal sources sufficient for now. |
| **AI risk score on feed** (Q9) | Redundant with Defender severity + AI narrative; creates competing signals. |
| **External TI in Copilot** | Same as above. |

---

## Implementation Order (suggested)

1. **AI-01 + AI-04** — Copilot handoff + save-back (highest analyst value, low backend cost)
2. **AI-03** — AI narratives on decisions (makes the feed self-explanatory)
3. **AI-02** — AI fallback classification (extends rule coverage)
4. **AI-06** — Security KB category (seeds Copilot with runbooks)
5. **AI-05** — Admin model picker (operational convenience)
6. **AI-07** — Daily digest (leadership visibility)
