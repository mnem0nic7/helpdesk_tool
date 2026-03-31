# Altlassian

Altlassian is a multi-surface operations portal that combines Jira helpdesk workflows with Azure operations, reporting, alerting, and user-lifecycle tooling.

The main application lives in `backend/` and `frontend/`. The repo also includes a separate Azure ingestion starter platform, Windows automation for exit workflows, and a growing set of runbooks and governance docs under `docs/`.

## Main surfaces

- Primary helpdesk dashboard for OIT ticket operations, SLA tracking, AI triage, reporting, alerts, and knowledge-base tooling.
- OasisDev-hosted helpdesk view that reuses the same application with scope-aware filtering.
- Azure Control Center for Azure inventory, cost, identity, VM and virtual desktop analysis, alerts, and optimization workflows.
- Shared signed-in tools on the primary and Azure hosts for OneDrive copy jobs, login audit review, read-only mailbox Inbox rule lookup, Exchange mailbox delegate lookups for Send on behalf, Send As, and Full Access, and an admin-only Emailgistics Helper that grants mailbox access, adds the Emailgistics add-in group membership, and runs a targeted shared-mailbox sync.

## Repository layout

- `backend/`: FastAPI API, caches, workers, report builders, and route handlers.
- `frontend/`: React 19 + Vite SPA with host-aware routing and branding.
- `azure_ingestion_platform/`: separate FastAPI/Postgres ingestion platform for multi-tenant Azure collection.
- `windows_agent/`: PowerShell-based Windows exit workflow agent.
- `docs/`: plans, specs, governance notes, templates, and runbooks.
- `.codex/skills/`: repo-local Codex skills for recurring Altlassian workflows.
- `e2e/`: Playwright end-to-end test project.
- `scripts/`: repo maintenance and safety scripts.

## Quick start

### Local app development

From the repo root:

```bash
./start.sh
```

This launches:

- Backend on `http://localhost:8000`
- Frontend on `http://localhost:5173`

You can also run the pieces separately:

```bash
cd backend
python main.py
```

```bash
cd frontend
npm run dev
```

### Full Docker stack

From the repo root:

```bash
docker compose up -d
docker compose down
```

The compose stack includes:

- Caddy for ingress and blue/green upstream switching
- `backend_blue` and `backend_green`
- `frontend_blue` and `frontend_green`
- PostgreSQL
- Redis

## Common commands

### Backend

```bash
cd backend
pytest tests/
pytest tests/test_routes_azure.py
```

### Frontend

```bash
cd frontend
npm run build
npm run test:run
npm run lint
```

### End-to-end

```bash
cd e2e
npm test
```

### Azure ingestion platform

```bash
cd azure_ingestion_platform
docker compose up --build
```

## Documentation

- Runbooks: `docs/runbooks/`
- AI workflow runbooks and agent playbooks: `docs/runbooks/ai/`
- Governance references: `docs/governance/`
- Plans: `docs/plans/`
- Specs: `docs/specs/`
- Experimental Azure superpowers docs: `docs/superpowers/`

## Implementation notes

- The frontend switches between helpdesk and Azure route trees based on site branding and request host.
- The shared `/tools` surface is available to all signed-in users on the primary and Azure hosts and includes OneDrive copy, login audit, mailbox Inbox rule lookup, and Exchange mailbox delegate lookups for Send on behalf, Send As, and Full Access powered by the shared app registration.
- The org-wide "find mailboxes where a user has delegate access" workflow is a durable server-side job, not a page-local request. Users should normally expect results in about 20 to 90 seconds, but larger tenants can take 5 to 10 minutes because the app has to sweep Exchange mailbox and permission data. Each signed-in user sees their own recent delegate scan jobs and any still-running jobs when they come back to the Tools page, can cancel a queued or running scan from the Tools UI if they no longer need it, and can clear finished delegate history without touching running work.
- Both job history cards on the Tools page now expose `Clear finished` actions. The shared OneDrive history card clears completed, failed, or cancelled jobs from shared history, while the delegate-scan history card clears the signed-in user's finished delegate jobs. Neither action removes queued or running jobs.
- The Tools page also includes an admin-only `Emailgistics Helper` action for a user mailbox plus shared mailbox pair. It grants `Full Access`, grants `Send As`, adds the user to `Emailgistics_UserAddin`, and then runs the targeted `scripts/syncUsers/syncUsers.ps1` flow. The helper preflights the Emailgistics sync configuration before making Exchange permission changes so a missing sync dependency fails safely.
- The backend image copies only `scripts/syncUsers/syncUsers.ps1`. Do not commit or bake `scripts/syncUsers/customerData.json`; instead supply Emailgistics API settings through `backend/.env` with `EMAILGISTICS_TOKEN_VALID_URL`, `EMAILGISTICS_USER_SYNC_URL`, and `EMAILGISTICS_AUTH_TOKEN`.
- Repo-specific Codex skills are versioned in `.codex/skills/`, while the human-readable source of truth for those workflows lives in `docs/runbooks/ai/`.
- The backend serves all app surfaces from one FastAPI service and starts several background workers for caches, alerts, exports, reporting, and lifecycle automation.
- PostgreSQL and Redis are the intended shared services for the main app, while local development may still use SQLite-backed data under `data/`.
- In blue/green Docker deployments, Azure FinOps DuckDB defaults to color-scoped files like `azure_finops_blue.duckdb` and `azure_finops_green.duckdb` so the two runtimes do not fight over the same lock.
- The Azure Virtual Desktops page keeps its search input in local state while syncing route params so filtered refetches do not tear down the page and steal focus.

## Reporting notes

- The report builder export endpoint uses the active report configuration, so exported workbooks follow the current filters, selected columns, sorting, and grouping from the builder UI.
- The report builder preview includes an `Export Current View` action so users do not have to return to the page header to export the current configuration.
- Master workbook dashboard AI summaries are grouped by KPI row in the export workbook so each metric keeps its own paragraph and bullets together in a single wrapped cell.
