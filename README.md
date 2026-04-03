# Altlassian

Altlassian is a multi-surface operations portal that combines Jira helpdesk workflows with Azure operations, reporting, alerting, and user-lifecycle tooling.

The main application lives in `backend/` and `frontend/`. The repo also includes a separate Azure ingestion starter platform, Windows automation for exit workflows, and a growing set of runbooks and governance docs under `docs/`.

## Main surfaces

- Primary helpdesk dashboard for OIT ticket operations, SLA tracking, AI triage, reporting, alerts, and knowledge-base tooling.
- OasisDev-hosted helpdesk view that reuses the same application with scope-aware filtering.
- Azure Control Center for Azure inventory, cost, identity, VM and virtual desktop analysis, alerts, optimization workflows, and a dedicated Security workspace for Azure security tooling, including an Ollama-backed incident copilot.
- Shared signed-in tools on the primary and Azure hosts for OneDrive copy jobs, login audit review, read-only mailbox Inbox rule lookup, Exchange mailbox delegate lookups for Send on behalf, Send As, and Full Access, and admin-only Emailgistics actions that either grant mailbox access and sync a shared mailbox or rerun `syncUsers.ps1` for all configured Emailgistics mailboxes or one targeted shared mailbox.

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
- `security_ollama` for the dedicated Security Copilot runtime
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
- The Azure host now includes a dedicated `/security` workspace for security-oriented tooling and operator jump points. New Azure security flows should prefer that surface over overloading the generic `/tools` page.
- The Azure security workspace also includes `/security/copilot`, an Ollama-backed incident workbench that keeps incident state in the browser, asks follow-up questions until the intake is sufficient, resolves display-name style prompts into Azure user candidates for operator confirmation, queries the relevant Azure and local/internal sources the current session can use, auto-starts safe delegate-mailbox scan jobs when mailbox or identity incidents need deeper Exchange evidence, and can export a grounded markdown or JSON investigation handoff bundle for escalation or post-incident review. The live conversation now stays in the top chat panel with the same compose box used for every reply, while normalized findings and source evidence stay below. The same engine now also powers `/security/dlp-review` for pasted DLP findings and Purview-style review flows. In Docker deployments, Security Copilot now uses its own `security_ollama` runtime so incident investigations do not block ticket auto-triage or other default-runtime Ollama work.
- The Azure security workspace now ships dedicated review lanes at `/security/access-review`, `/security/break-glass-validation`, `/security/directory-role-review`, `/security/identity-review`, `/security/user-review`, `/security/guest-access-review`, `/security/dlp-review`, `/security/account-health`, `/security/app-hygiene`, `/security/device-compliance`, and `/security/conditional-access-tracker`. Treat those routes as the canonical operator entrypoints for privileged access, emergency-account validation, direct Entra directory-role review, directory identity review, guest/external access review, DLP finding review, user-account review, account-health review, app hygiene, tenant-wide device compliance remediation, and conditional-access drift tracking.
- Tenant-wide security review lanes should not mount their entire filtered dataset into the DOM at once. Keep their queues paged on the frontend, even when the backend already returns cached data quickly, so large Azure tenants do not bog down operator browsers just by opening the page.
- Frontend polling is intentionally conservative now. Shared React Query polling tiers live in `frontend/src/lib/queryPolling.ts`, hidden tabs should stop interval-driven refetches, and review-style pages should prefer the slow or manual tiers instead of page-local 30-second loops unless the screen is acting as a live operational monitor.
- The raw Azure `/identity` and `/users` pages still exist, but they are now hidden support surfaces for entity drill-ins, query-param pivots, and deeper inventory views launched from the security review lanes. The legacy `/account-health` path is now a compatibility redirect to `/security/account-health`.
- The AI Change Log remains a change-only table, but operator-visible triage progress now comes from the durable auto-triage activity ledger. `AI processed` means live AI ran and ended in `changed` or `no_change`; `Backfilled` means the one-time legacy processed migration skipped those tickets without live AI analysis; and the page now shows a backend-generated red broken-state banner when pending tickets, stale workers, missing models, or integrity mismatches prove triage is unhealthy.
- Azure directory refreshes now populate richer cached app-registration metadata, including credential expiry and batched owner lookups, so the Application Hygiene lane can stay fast and grounded from cached Graph data. If the richer snapshot is not populated yet after a deploy or first refresh, the page warns and falls back cleanly instead of failing.
- Azure security now also keeps dedicated cached datasets for tenant-wide Intune managed-device posture and Conditional Access policy drift. Device Compliance Review is intentionally deterministic and now supports direct per-device remediation, cached-user primary-user reassignment, explicit bulk device actions, and a smart `Fix selected` preview-and-execute flow that fans out into durable Azure-host device action jobs. Keep that lane paged on the frontend rather than rendering the full tenant result set at once, because large managed-device populations can otherwise make the operator browser sluggish. Conditional Access tracking stays read-only and highlights broad or exception-heavy policy changes from cached policy and audit data.
- Local Ollama-backed features now default to `qwen3.5:4b` when it is available. Fast structured lanes such as ticket auto-triage use `nemotron-3-nano:4b` by default so CPU-bound hosts keep processing queue work instead of stalling behind long Qwen JSON calls. If a host does not have Qwen available, the app falls back cleanly to `nemotron-3-nano:4b` for general discovery as well.
- Technician QA scoring also follows the fast structured-model path. Keep it on the Nemotron fast model by default, use the JSON-only retry prompt when the first answer is malformed, and save a conservative fallback score after repeated invalid JSON so one bad ticket cannot stall the background scoring queue.
- Default-runtime Ollama work still uses the shared local queue, which keeps `Security Copilot` ahead of lower-priority background jobs when both features share one runtime in local development. In Docker deployments, `Security Copilot` should instead use the dedicated `security_ollama` runtime and model endpoint so ticket triage can continue on the default Ollama runtime.
- The shared `/tools` surface is available to all signed-in users on the primary and Azure hosts and includes OneDrive copy, login audit, mailbox Inbox rule lookup, and Exchange mailbox delegate lookups for Send on behalf, Send As, and Full Access powered by the shared app registration.
- The org-wide "find mailboxes where a user has delegate access" workflow is a durable server-side job, not a page-local request. Users should normally expect results in about 20 to 90 seconds, but larger tenants can take 5 to 10 minutes because the app has to sweep Exchange mailbox and permission data. Each signed-in user sees their own recent delegate scan jobs and any still-running jobs when they come back to the Tools page, can cancel a queued or running scan from the Tools UI if they no longer need it, and can clear finished delegate history without touching running work.
- Both job history cards on the Tools page now expose `Clear finished` actions. The shared OneDrive history card clears completed, failed, or cancelled jobs from shared history, while the delegate-scan history card clears the signed-in user's finished delegate jobs. Neither action removes queued or running jobs.
- The Tools page includes an admin-only Emailgistics Helper. It takes a user mailbox plus shared mailbox pair, grants `Full Access`, grants `Send As`, and adds the user to `Emailgistics_UserAddin`. The helper no longer runs any Emailgistics sync script.
- Repo-specific Codex skills are versioned in `.codex/skills/`, while the human-readable source of truth for those workflows lives in `docs/runbooks/ai/`.
- The backend serves all app surfaces from one FastAPI service and starts several background workers for caches, alerts, exports, reporting, and lifecycle automation.
- PostgreSQL and Redis are the intended shared services for the main app, while local development may still use SQLite-backed data under `data/`.
- In blue/green Docker deployments, Azure FinOps DuckDB defaults to color-scoped files like `azure_finops_blue.duckdb` and `azure_finops_green.duckdb` so the two runtimes do not fight over the same lock.
- The Azure Virtual Desktops page keeps its search input in local state while syncing route params so filtered refetches do not tear down the page and steal focus.
- Bulk AI triage actions launched from the AI Change Log use the configured Ollama triage model when no explicit model is supplied. Placeholder client values like `None` are treated as unset, and any explicit model choice is forwarded into the background auto-triage worker so validation and execution use the same model.

## Reporting notes

- The report builder export endpoint uses the active report configuration, so exported workbooks follow the current filters, selected columns, sorting, and grouping from the builder UI.
- The report builder preview includes an `Export Current View` action so users do not have to return to the page header to export the current configuration.
- Master workbook dashboard AI summaries are grouped by KPI row in the export workbook so each metric keeps its own paragraph and bullets together in a single wrapped cell.
