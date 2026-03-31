# Altlassian

Altlassian is a multi-surface operations portal that combines Jira helpdesk workflows with Azure operations, reporting, alerting, and user-lifecycle tooling.

The main application lives in `backend/` and `frontend/`. The repo also includes a separate Azure ingestion starter platform, Windows automation for exit workflows, and a growing set of runbooks and governance docs under `docs/`.

## Main surfaces

- Primary helpdesk dashboard for OIT ticket operations, SLA tracking, AI triage, reporting, alerts, and knowledge-base tooling.
- OasisDev-hosted helpdesk view that reuses the same application with scope-aware filtering.
- Azure Control Center for Azure inventory, cost, identity, VM and virtual desktop analysis, alerts, and optimization workflows.
- Shared signed-in tools on the primary and Azure hosts for OneDrive copy jobs, login audit review, read-only mailbox Inbox rule lookup, and Exchange mailbox delegate lookups for Send on behalf, Send As, and Full Access.

## Repository layout

- `backend/`: FastAPI API, caches, workers, report builders, and route handlers.
- `frontend/`: React 19 + Vite SPA with host-aware routing and branding.
- `azure_ingestion_platform/`: separate FastAPI/Postgres ingestion platform for multi-tenant Azure collection.
- `windows_agent/`: PowerShell-based Windows exit workflow agent.
- `docs/`: plans, specs, governance notes, templates, and runbooks.
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
- Governance references: `docs/governance/`
- Plans: `docs/plans/`
- Specs: `docs/specs/`
- Experimental Azure superpowers docs: `docs/superpowers/`

## Implementation notes

- The frontend switches between helpdesk and Azure route trees based on site branding and request host.
- The shared `/tools` surface is available to all signed-in users on the primary and Azure hosts and includes OneDrive copy, login audit, mailbox Inbox rule lookup, and Exchange mailbox delegate lookups for Send on behalf, Send As, and Full Access powered by the shared app registration.
- The backend serves all app surfaces from one FastAPI service and starts several background workers for caches, alerts, exports, reporting, and lifecycle automation.
- PostgreSQL and Redis are the intended shared services for the main app, while local development may still use SQLite-backed data under `data/`.
- In blue/green Docker deployments, Azure FinOps DuckDB defaults to color-scoped files like `azure_finops_blue.duckdb` and `azure_finops_green.duckdb` so the two runtimes do not fight over the same lock.
- The Azure Virtual Desktops page keeps its search input in local state while syncing route params so filtered refetches do not tear down the page and steal focus.

## Reporting notes

- The report builder export endpoint uses the active report configuration, so exported workbooks follow the current filters, selected columns, sorting, and grouping from the builder UI.
- The report builder preview includes an `Export Current View` action so users do not have to return to the page header to export the current configuration.
- Master workbook dashboard AI summaries are grouped by KPI row in the export workbook so each metric keeps its own paragraph and bullets together in a single wrapped cell.
