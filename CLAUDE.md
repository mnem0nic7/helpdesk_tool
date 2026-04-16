# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repo is no longer just a Jira dashboard. It is a multi-surface operations portal with:

- A FastAPI backend in `backend/` that serves Jira helpdesk workflows, Azure operational data, alerts, reporting, knowledge-base features, and user lifecycle automation.
- A React SPA in `frontend/` that renders different navigation trees depending on the active site scope.
- A separate `azure_ingestion_platform/` starter service for multi-tenant Azure ingestion experiments.
- A `windows_agent/` PowerShell agent for Windows exit-workflow automation.

The shipped app title is still `OIT Helpdesk Dashboard API`, but the product surface now includes the Azure portal experience.

## Repo Map

- `backend/`: main FastAPI application, background workers, caches, routers, report builders, and data services.
- `frontend/`: React 19 + Vite SPA for the primary, OasisDev, and Azure site scopes.
- `azure_ingestion_platform/`: separate FastAPI/Postgres ingestion platform with its own README, tests, and Docker compose file.
- `windows_agent/`: Windows exit agent scripts and sample config.
- `docs/`: plans, specs, runbooks, governance notes, and templates.
- `.codex/skills/`: repo-local Codex skills for Altlassian-specific workflows.
- `e2e/`: Playwright test project.
- `private/`: private assets such as KB seed archives; assume contents are sensitive.
- `data/`: local runtime databases and caches used by the main app.
- `frontend copy/`: legacy artifact — ignore this directory; `frontend/` is canonical.

## Commands

### Main app backend

Run from `backend/` unless noted otherwise:

```bash
python main.py
pytest tests/
pytest tests/test_routes_azure.py
pytest tests/test_routes_azure.py::test_specific_function  # run a single test
```

### Frontend

Run from `frontend/`:

```bash
npm run dev
npm run build
npm run test:run
npm test                          # watch mode
npm run test:run -- SomeComponent # run a single test file
npm run lint
```

### Full local dev

Run from repo root:

```bash
./start.sh
docker compose up -d
docker compose down
./deploy.sh
./release.sh -m "message"
```

### E2E

Run from `e2e/`:

```bash
npm test
npm run test:headed
```

### Azure ingestion platform

Run from `azure_ingestion_platform/`:

```bash
docker compose up --build
cd /workspace/atlassian
DATABASE_URL=sqlite+pysqlite:///./azure_ingestion_platform_test.db ./.venv/bin/pytest -q azure_ingestion_platform/tests
```

### Repo hygiene

Run from repo root before committing or releasing:

```bash
./scripts/check_repo_hygiene.sh   # secret scan + general hygiene checks
./scripts/run_secret_scan.sh      # focused secret scan (git history + working tree)
```

`scripts/security_ollama_entrypoint.sh` is a container entrypoint for the `security_ollama` runtime in `docker-compose.yml` — do not invoke it directly.

## Runtime Architecture

### Main application

- `backend/main.py` wires all routers and owns lifecycle startup/shutdown.
- The backend starts leader-only background services such as Jira cache refresh, Azure cache refresh, cost-export processing, Azure alert polling, report AI summary generation, user admin jobs, and exit workflows.
- The frontend is a Vite-built SPA served by nginx in containers.
- `docker-compose.yml` runs blue/green backend and frontend pairs behind Caddy, plus Postgres, Redis, and a dedicated `security_ollama` runtime for Azure Security Copilot.

### Storage

- PostgreSQL is the primary shared database when `DATABASE_URL` is configured.
- Redis is used for shared runtime state and coordination.
- SQLite files under `data/` still exist for local persistence and dual-write compatibility.
- DuckDB is used for Azure FinOps reporting data. In blue/green Docker mode, default each runtime color to its own DuckDB file unless `AZURE_FINOPS_DUCKDB_PATH` is explicitly overridden on purpose.
- **Postgres schema migrations**: every new table or column added to any store must have a matching numbered `.sql` file in `backend/storage_migrations/`. Files are auto-applied on startup via `ensure_postgres_schema()`. Use `CREATE TABLE IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS` for idempotency. Use `SMALLINT` for boolean columns. Create migration files in the same commit as the SQLite schema change — not after. Missing migrations cause `relation "..." does not exist` errors in production.

## Site Scopes

Host-aware scope lives in `backend/site_context.py`.

- `primary`: default OIT helpdesk surface.
- `oasisdev`: helpdesk surface constrained to OasisDev issues.
- `azure`: Azure Control Center surface with Azure-only pages and no Jira issue list.

Frontend routing switches on `getSiteBranding()` in `frontend/src/App.tsx`. Do not assume one static nav tree.

## Backend Areas

- Jira/helpdesk: `issue_cache.py`, `jira_client.py`, `routes_tickets.py`, `routes_actions.py`, `routes_metrics.py`, `routes_triage.py`, `sla_engine.py`.
- Azure operations: `azure_cache.py`, `routes_azure.py`, `routes_azure_alerts.py`, `azure_finops*.py`, `azure_cost_exports.py`, `azure_vm_export_jobs.py`.
- Knowledge base and tooling: `knowledge_base.py`, `routes_kb.py`, `routes_tools.py`.
- User lifecycle: `user_admin_jobs.py`, `routes_user_admin.py`, `user_exit_workflows.py`, `routes_user_exit.py`, `deactivation_schedule.py`, `routes_deactivation_schedule.py`.
- On-prem Active Directory: `ad_client.py` (ldap3-based, LDAPS for password reset), `routes_ad.py` (`/api/ad/*` — users, groups, computers, OUs).
- Reporting and exports: `report_workbook_builder.py`, `report_ai_summary_service.py`, `routes_export.py`.
- Azure security review lanes: `security_workspace_summary.py`, `security_access_review.py`, `security_application_hygiene.py`, `security_break_glass_validation.py`, `security_conditional_access_tracker.py`, `security_device_compliance.py`, `security_device_jobs.py`, `security_directory_role_review.py`, `security_finding_exception_store.py`, `security_copilot.py`, `routes_azure_security.py`, `routes_azure_security_copilot.py`.
- Defender autonomous agent: `defender_agent.py`, `defender_agent_store.py`, `routes_defender_agent.py` (`/api/azure/security/defender-agent/*`), frontend surface at `frontend/src/pages/AzureSecurityAgentPage.tsx`.

## Frontend Notes

- Stack: React 19, React Router 7, React Query 5, Tailwind CSS 4, Recharts 3.
- `frontend/vite.config.ts` proxies `/api` to `http://localhost:8000` in local dev.
- Pages under `frontend/src/pages/` are split between helpdesk and Azure surfaces.
- The layout and branding logic determine which routes appear; check `frontend/src/components/Layout.tsx` and `frontend/src/lib/siteContext.ts`.

## Testing Notes

- Backend tests live in `backend/tests/`.
- Frontend tests live in `frontend/src/__tests__/` and use Vitest + Testing Library.
- E2E coverage lives in `e2e/tests/`.
- When changing Azure routes or cache shape, look for paired backend and frontend tests before adding new coverage.

## Working Conventions

- Backend uses snake_case JSON; frontend API types mirror that shape closely in `frontend/src/lib/api.ts`.
- All API routes are under `/api`.
- Prefer updating existing docs under `docs/` when behavior changes materially.
- AI workflow docs live under `docs/runbooks/ai/`, and their matching repo-local Codex skills live under `.codex/skills/`. Keep the docs canonical and the skills aligned with them.
- Keep host/scope behavior in mind before changing filtering logic or navigation.
- Avoid assuming Jira data is available on the Azure site scope.

## Important Business Rules

- Issues tagged as OasisDev are filtered out of the primary helpdesk scope and shown only in the OasisDev scope.
- The Azure scope should not surface Jira issue lists.
- Knowledge-base seed import runs asynchronously on startup and reports readiness through app state.
- Blue/green runtime coordination exists; some background services should only run on the elected leader instance.
- The Defender autonomous agent polls Graph Security API for Microsoft Defender alerts and classifies each one through a decision rule table with three safety tiers: **T1** (immediate — revoke sessions, device sync; auto-executed on first cycle), **T2** (delayed queue — disable sign-in, cancellable by operators before `not_before_at`, time-gated to off-hours), and **T3** (recommend only — wipe/retire, requires human approval via `POST /api/azure/security/defender-agent/decisions/{id}/approve`). Alerts below `min_severity` or with no matching rule are logged as `skip`. Remediation dispatches through the existing `user_admin_jobs` and `security_device_jobs` queues — the agent never calls Graph mutation APIs directly. Every decision, including skips, is logged durably in `defender_agent_store` for operator review and Teams notification. Runs as a leader-only background service; the composite playbook engine supports Red Canary parity rules (e.g., `account_lockout` composites). Only available on the `azure` site scope.

## Operational Invariants

These are durable rules and design contracts — not time-bound release notes. Grouped by topic for navigation.

### Reporting

- The report builder preview includes an `Export Current View` action in `frontend/src/pages/ReportsPage.tsx`; it reuses the existing report export API and should export the current filters, selected columns, sort, and grouping.
- Master workbook dashboard AI summaries are written per KPI row in `backend/report_workbook_builder.py`; keep each metric's paragraph and bullets in one wrapped cell so summaries do not spill into adjacent metric rows.

### Shared Tools surface

- The shared Tools surface on `it-app.movedocs.com` and `azure.movedocs.com` is available to all signed-in users, not just a small operator allowlist. It includes OneDrive copy, login audit, read-only mailbox Inbox rule lookup, and Exchange mailbox delegate lookups for Send on behalf, Send As, and Full Access that use the shared app registration. Keep that access model and feature set aligned across `backend/auth.py`, `backend/routes_tools.py`, `frontend/src/components/Layout.tsx`, and `frontend/src/pages/ToolsPage.tsx`. `TOOLS_ALLOWED_IDENTIFIERS` is now legacy-only config and should not be treated as an active runtime gate.
- The "find mailboxes where a user has delegate access" Tools flow is a durable per-user background job backed by persisted job history, not a synchronous page-bound lookup. Keep its job routes, worker startup, retention config, cancel behavior, clear-finished behavior, and Tools-page resume behavior aligned so a user sees their latest job, any still-running job after navigating away and back, can cancel a queued or running scan from the UI, and can clear finished history without touching in-flight jobs. Normal runtime is roughly 20 to 90 seconds, but Exchange sweeps can take 5 to 10 minutes in larger tenants.
- The Tools page has an admin-only Emailgistics Helper that grants `Full Access`, grants `Send As`, and adds a user to `Emailgistics_UserAddin` for a shared mailbox. The helper does not run Emailgistics sync scripts. Keep the admin gate aligned between `backend/routes_tools.py` and `frontend/src/pages/ToolsPage.tsx`, and keep the helper step order intact in `backend/emailgistics_helper_service.py`.
- `scripts/syncUsers/customerData.json` is treated as local sensitive config and must not be committed or baked into Docker images. The runtime expects Emailgistics API settings from environment variables such as `EMAILGISTICS_TOKEN_VALID_URL`, `EMAILGISTICS_USER_SYNC_URL`, `EMAILGISTICS_AUTH_TOKEN`, and `EMAILGISTICS_CONFIGURED_MAILBOXES`; only the script itself is copied into the backend image.

### Azure Security workspace

- The Azure host has a dedicated `Security` workspace under `frontend/src/pages/AzureSecurityPage.tsx` and the Azure nav in `frontend/src/components/Layout.tsx`. New Azure security-oriented tools should land there first and reuse the existing Azure overview/status cache context unless they need a new backend data lane.
- The Security workspace hub is triage-first and is backed by the lightweight `/api/azure/security/workspace-summary` payload from `backend/security_workspace_summary.py`. Keep hub cards keyed by stable lane ids, reuse cached Azure datasets and existing lane heuristics for workspace ranking, avoid triggering expensive live lane builders just to render `/security`, and preserve the static catalog fallback when the summary call is unavailable.
- The Security workspace ships dedicated first-class review lanes at `/security/access-review`, `/security/identity-review`, `/security/user-review`, `/security/guest-access-review`, `/security/dlp-review`, `/security/account-health`, `/security/app-hygiene`, `/security/device-compliance`, `/security/conditional-access-tracker`, `/security/break-glass-validation`, and `/security/directory-role-review`. Treat those routes as the canonical operator entrypoints — do not fold those checks back into the broader access or identity pages, and do not add more one-off cards to the workspace shell.
- `/security/copilot` is an Ollama-backed incident investigation surface implemented through `backend/security_copilot.py`, `backend/routes_azure_security_copilot.py`, and `frontend/src/pages/AzureSecurityCopilotPage.tsx`. Keep new incident sources in the backend source registry, keep query building deterministic from the normalized incident profile, report permission-gated or unavailable sources as explicit skipped/error results instead of silently dropping them, preserve the built-in investigation export, and keep the identity-candidate confirmation flow intact so display-name style prompts resolve to Azure user choices before the copilot commits to a target account. The active conversation stays in the top chat panel and reuses the same compose box for each reply, while normalized findings and investigation outputs stay below. The same copilot engine powers `/security/dlp-review`, which starts in a `dlp_finding` lane and is intended for pasted Purview-style findings rather than a live Purview feed. In Docker deployments, Security Copilot uses the dedicated `security_ollama` runtime wired through `docker-compose.yml` and `scripts/security_ollama_entrypoint.sh` instead of competing with the default-runtime Ollama queue used by triage and other AI jobs.
- Tenant-wide Azure security review lanes must keep their visible queues paged on the frontend. Cached Graph-backed data can still be large enough to make browsers sluggish if a page mounts every filtered card or table row at once, so prefer paged slices or existing infinite-scroll helpers over full-list rendering for access review, user review, identity review, guest review, app hygiene, conditional access, device compliance, and similar security surfaces.
- User-centric Azure security findings can be marked as approved exceptions from `/security/user-review`. Exceptions are stored durably in `backend/security_finding_exception_store.py`, managed through `/api/azure/security/finding-exceptions`, and suppress the matching finding type from User Review, Guest Access Review, Account Health, and the `/api/azure/security/workspace-summary` counts until the finding is restored. Legacy broad exceptions still exist as `all-findings` wildcards.
- The device-compliance lane is backed by its own cached `device_compliance` dataset plus Azure-host-only device action jobs. Keep its recommendations deterministic, expose direct per-device fixes plus the smart `Fix selected` preview flow from the lane, route all execution through `backend/security_device_jobs.py`, and keep primary-user reassignment grounded in the cached Azure user directory instead of free-form identifiers. The smart bulk planner stays backend-owned and deterministic: `sync` and `retire` can be auto-proposed, `remote lock` and `wipe` stay manual, and devices with `no_primary_user` must stop for an explicit cached-user selection before execution. Fail closed when the signed-in session cannot manage users.
- The Conditional Access tracker is backed by a separate cached `conditional_access` dataset composed from policy snapshots and directory-audit changes. Keep it read-only, tenant-wide, and grounded in cached Graph data instead of layering live mutation controls into that lane.
- Keep raw `/identity` and `/users` routes available as hidden support pages for query-param drill-ins, entity pivots, and deeper inventory inspection. Do not re-add them as top-level Azure nav items unless the product direction changes. The legacy `/account-health` route remains a compatibility redirect to `/security/account-health`.
- The Azure directory refresh populates an `application_security` snapshot alongside `applications`. Keep the richer app-registration metadata aligned across `backend/azure_client.py`, `backend/azure_cache.py`, and `frontend/src/lib/api.ts`: batched owner lookups should stay best-effort, app hygiene should keep warning when the rich snapshot is not ready yet, and app credential review should continue using cached Graph metadata rather than live per-page Graph calls.

### AI and Ollama runtime

- `nemotron-3-nano:4b` is the default Ollama model for all features — there is no longer a separate "quality" model. Keep `OLLAMA_MODEL`, `OLLAMA_FAST_MODEL`, `AUTO_TRIAGE_MODEL`, and `OLLAMA_SECURITY_MODEL` all pointing at `nemotron-3-nano:4b` in `backend/.env` and `backend/config.py`. Do not reintroduce qwen.
- Technician QA scoring stays on the fast structured-model path. The scoring prompt in `backend/ai_client.py` is intentionally JSON-only, retries once with a stricter schema reminder and `temperature=0`, and then saves a conservative fallback score if the model still refuses to return valid JSON so one malformed ticket does not get reselected forever by the background scheduler.
- The default local Ollama runtime is serialized through a priority queue in `backend/ai_client.py`. Keep `azure_security_copilot` at the front of that queue when multiple features share one runtime in local development, but preserve the separate security-runtime path and `/api/azure/security/copilot/models` endpoint so deployed Security Copilot traffic stays isolated from ticket auto-triage.
- Ticket auto-triage and technician QA scoring support a secondary Ollama instance at `OLLAMA_SECONDARY_BASE_URL` for round-robin load sharing. Health-checked every 30 s with a 3 s timeout; falls back to primary automatically. All other features always use their configured runtime URL. Secondary must have `nemotron-3-nano:4b` pulled to participate.
- AI triage operator status comes from the durable auto-triage activity ledger in `backend/triage_store.py`, not from `auto_triaged` alone. Keep the AI Change Log change-only, record a single most-recent activity outcome per ticket as `changed`, `no_change`, `failed`, or `backfill`, keep `reprocess=true` limited to live AI outcomes (`changed` and `no_change`), and surface backend-generated triage health on `/api/triage/run-status` so the AI Log can show an explicit red broken-state banner instead of making operators infer failures from raw counts.
- Bulk AI triage runs triggered from the AI Change Log should treat placeholder model values such as `None`, `null`, and `undefined` as unset, fall back to the configured Ollama model, and pass any explicit model choice through to the background auto-triage worker so route validation and worker execution stay aligned.

### User lifecycle and AD

- The deactivation scheduler (`backend/deactivation_schedule.py`, `/api/deactivation-schedule`) queues scheduled or immediate user deactivations tied to a Jira ticket key. Each job runs four steps in order: Entra disable sign-in → Entra revoke sessions → Entra random password reset → AD disable + AD random password reset. Any step error marks the entire job `failed`. The scheduler polls every 30 s and is started as a leader-only background service.
- On-prem AD client (`backend/ad_client.py`) uses ldap3. Strip `ldap://`/`ldaps://` scheme from `AD_SERVER` before passing to `ldap3.Server()`. LDAPS on port 636 is required for password reset. `AD_BIND_DN` must be the full Distinguished Name of the service account.

### Frontend conventions

- The Azure Virtual Desktops search box keeps local input state and preserves previous query results during refetch so typing does not remount the page or drop focus.
- Host-aware frontend tests should prefer `document.documentElement.dataset.siteHostname` when forcing site branding in Vitest; that avoids JSDOM cross-origin `window.history.replaceState()` failures while still exercising scope-aware routing and page behavior.
- Frontend polling policy is centralized in `frontend/src/lib/queryPolling.ts`. Review and inventory pages should use the shared polling tiers plus hidden-tab-safe `refetchInterval` helpers instead of ad hoc polling literals. Global React Query defaults in `frontend/src/main.tsx` keep `refetchOnWindowFocus`, `refetchOnReconnect`, and background interval polling disabled unless a page explicitly opts into a live operational loop.

### Runbooks and playbooks

- The repo carries a first-wave AI workflow suite: release/cutover, incident triage, Jira hotfix, Microsoft 365 Tools, closeout, and SLA/reporting review skills under `.codex/skills/`, plus matching human docs and agent playbooks under `docs/runbooks/ai/`. Prefer those playbooks over inventing ad-hoc operational flows.

### Historical incidents

- **2026-03-30 — blue/green Azure FinOps DuckDB contention.** Both backend containers contended for the same Azure FinOps DuckDB file during restart and caused an outage. Keep the color-scoped DuckDB default in mind when touching blue/green config or FinOps storage initialization.
