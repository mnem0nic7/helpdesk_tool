# CLAUDE.md

This file captures working memory for agents editing this repository.

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

## Commands

### Main app backend

Run from `backend/` unless noted otherwise:

```bash
python main.py
pytest tests/
pytest tests/test_routes_azure.py
```

### Frontend

Run from `frontend/`:

```bash
npm run dev
npm run build
npm run test:run
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
cd /workspace/altlassian
DATABASE_URL=sqlite+pysqlite:///./azure_ingestion_platform_test.db ./.venv/bin/pytest -q azure_ingestion_platform/tests
```

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
- User lifecycle: `user_admin_jobs.py`, `routes_user_admin.py`, `user_exit_workflows.py`, `routes_user_exit.py`.
- Reporting and exports: `report_workbook_builder.py`, `report_ai_summary_service.py`, `routes_export.py`.

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

## Recent Report Notes

- The report builder preview now includes an `Export Current View` action in `frontend/src/pages/ReportsPage.tsx`; it reuses the existing report export API and should export the current filters, selected columns, sort, and grouping.
- Master workbook dashboard AI summaries are written per KPI row in `backend/report_workbook_builder.py`; keep each metric's paragraph and bullets in one wrapped cell so summaries do not spill into adjacent metric rows.
- The shared Tools surface on `it-app.movedocs.com` and `azure.movedocs.com` is available to all signed-in users, not just a small operator allowlist, and it includes OneDrive copy, login audit, read-only mailbox Inbox rule lookup, and Exchange mailbox delegate lookups for Send on behalf, Send As, and Full Access that use the shared app registration. Keep that access model and feature set aligned across `backend/auth.py`, `backend/routes_tools.py`, `frontend/src/components/Layout.tsx`, and `frontend/src/pages/ToolsPage.tsx`. `TOOLS_ALLOWED_IDENTIFIERS` is now legacy-only config and should not be treated as an active runtime gate.
- The "find mailboxes where a user has delegate access" Tools flow is now a durable per-user background job backed by persisted job history, not a synchronous page-bound lookup. Keep its job routes, worker startup, retention config, cancel behavior, clear-finished behavior, and Tools-page resume behavior aligned so a user sees their latest job, any still-running job after navigating away and back, can cancel a queued or running scan from the UI, and can clear finished history without touching in-flight jobs. Normal runtime is roughly 20 to 90 seconds, but Exchange sweeps can take 5 to 10 minutes in larger tenants.
- The Tools page has an admin-only Emailgistics Helper that grants `Full Access`, grants `Send As`, and adds a user to `Emailgistics_UserAddin` for a shared mailbox. The helper no longer runs Emailgistics sync scripts. Keep the admin gate aligned between `backend/routes_tools.py` and `frontend/src/pages/ToolsPage.tsx`, and keep the helper step order intact in `backend/emailgistics_helper_service.py`.
- `scripts/syncUsers/customerData.json` is treated as local sensitive config and must not be committed or baked into Docker images. The runtime now expects Emailgistics API settings from environment variables such as `EMAILGISTICS_TOKEN_VALID_URL`, `EMAILGISTICS_USER_SYNC_URL`, `EMAILGISTICS_AUTH_TOKEN`, and `EMAILGISTICS_CONFIGURED_MAILBOXES`, while only the script itself is copied into the backend image.
- The repo now carries a first-wave AI workflow suite: release/cutover, incident triage, Jira hotfix, Microsoft 365 Tools, closeout, and SLA/reporting review skills under `.codex/skills/`, plus matching human docs and agent playbooks under `docs/runbooks/ai/`. Prefer those playbooks over inventing ad-hoc operational flows.
- The Azure Virtual Desktops search box should keep local input state and preserve previous query results during refetch so typing does not remount the page or drop focus.
- A March 30, 2026 outage came from blue and green backend containers contending for the same Azure FinOps DuckDB file during restart. Keep the color-scoped DuckDB default in mind when touching blue/green config or FinOps storage initialization.
- Bulk AI triage runs triggered from the AI Change Log should treat placeholder model values such as `None`, `null`, and `undefined` as unset, fall back to the configured Ollama model, and pass any explicit model choice through to the background auto-triage worker so route validation and worker execution stay aligned.
- Host-aware frontend tests should prefer `document.documentElement.dataset.siteHostname` when forcing site branding in Vitest; that avoids JSDOM cross-origin `window.history.replaceState()` failures while still exercising scope-aware routing and page behavior.
- The Azure host now has a dedicated `Security` workspace under `frontend/src/pages/AzureSecurityPage.tsx` and the Azure nav in `frontend/src/components/Layout.tsx`. New Azure security-oriented tools should land there first and reuse the existing Azure overview/status cache context unless they need a new backend data lane.
- The Azure `Security` workspace now includes a dedicated Ollama-backed incident investigation surface at `/security/copilot`, implemented through `backend/security_copilot.py`, `backend/routes_azure_security_copilot.py`, and `frontend/src/pages/AzureSecurityCopilotPage.tsx`. Keep new incident sources in the backend source registry, keep query building deterministic from the normalized incident profile, report permission-gated or unavailable sources as explicit skipped/error results instead of silently dropping them, preserve the built-in investigation export, and keep the identity-candidate confirmation flow intact so display-name style prompts resolve to Azure user choices before the copilot commits to a target account. The active conversation should stay in the top chat panel and reuse the same compose box for each reply, while normalized findings and investigation outputs stay below. The same copilot engine now powers `/security/dlp-review`, which starts in a `dlp_finding` lane and is intended for pasted Purview-style findings rather than a live Purview feed. In Docker deployments, Security Copilot should use the dedicated `security_ollama` runtime wired through `docker-compose.yml` and `scripts/security_ollama_entrypoint.sh` instead of competing with the default-runtime Ollama queue used by triage and other AI jobs.
- The Azure `Security` workspace now also ships dedicated first-class review lanes at `/security/access-review`, `/security/identity-review`, `/security/user-review`, `/security/guest-access-review`, `/security/dlp-review`, `/security/account-health`, and `/security/app-hygiene`. Treat those pages as the canonical homes for privileged access review, identity review, guest/external access review, DLP finding review, user-account review, account-health review, app owner coverage, and credential-expiry review instead of adding more one-off cards to the workspace shell.
- Keep raw `/identity` and `/users` routes available as hidden support pages for query-param drill-ins, entity pivots, and deeper inventory inspection. Do not re-add them as top-level Azure nav items unless the product direction changes. The legacy `/account-health` route should remain a compatibility redirect to `/security/account-health`.
- The Azure directory refresh now populates an `application_security` snapshot alongside `applications`. Keep the richer app-registration metadata aligned across `backend/azure_client.py`, `backend/azure_cache.py`, and `frontend/src/lib/api.ts`: batched owner lookups should stay best-effort, app hygiene should keep warning when the rich snapshot is not ready yet, and app credential review should continue using cached Graph metadata rather than live per-page Graph calls.
- Ollama-backed features now prefer `qwen3.5:4b` as the default local model. Keep the runtime fallback order aligned in `backend/ai_client.py` and config defaults so hosts drop cleanly to `nemotron-3-nano:4b` when Qwen is unavailable instead of failing model selection.
- The default local Ollama runtime is serialized through a priority queue in `backend/ai_client.py`. Keep `azure_security_copilot` at the front of that queue when multiple features share one runtime in local development, but preserve the separate security-runtime path and `/api/azure/security/copilot/models` endpoint so deployed Security Copilot traffic stays isolated from ticket auto-triage.
