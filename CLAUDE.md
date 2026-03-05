# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OIT Helpdesk Dashboard — a full-stack Jira helpdesk analytics tool with AI-powered ticket triage and custom SLA tracking. FastAPI backend connects to Jira Cloud, caches issues in SQLite, computes metrics, runs AI triage, and serves a React SPA.

## Commands

### Backend (run from `backend/`)
```bash
python main.py                                    # Dev server (port 8000, auto-reload if DASHBOARD_DEV=1)
pytest tests/                                     # Run all tests
pytest tests/test_metrics.py::TestParseDt::test_valid_iso  # Single test
```

### Frontend (run from `frontend/`)
```bash
npm run dev          # Vite dev server (port 5173, proxies /api → localhost:8000)
npm run build        # TypeScript check + production build
npm run test:run     # Single test run (CI)
npm test             # Watch mode
npm run lint         # ESLint
```

### Docker (from project root)
```bash
docker compose up -d       # Start Caddy (TLS) + Dashboard
docker compose down        # Stop all
./deploy.sh                # Full deploy: build, restart, health check
./deploy.sh --no-cache     # Rebuild without Docker cache
```

## Architecture

```
Browser → Caddy (:443, TLS) → nginx (:80, static + /api proxy) → uvicorn (:8000, FastAPI)
```

**Docker**: Multi-stage build — Node 20 builds frontend, Python 3.12-slim runs backend. Supervisord manages nginx + uvicorn in a single container. Caddy runs as a separate container for HTTPS.

**Dev mode**: Vite dev server proxies `/api/` to `localhost:8000` (configured in `vite.config.ts`).

### Backend (`backend/`)

| Module | Role |
|--------|------|
| `main.py` | FastAPI app, CORS, auth middleware, router registration, lifespan (cache start/stop) |
| `config.py` | Loads `.env` — Jira creds, AI keys, DATA_DIR, APP_SECRET_KEY |
| `auth.py` | Microsoft Entra (Azure AD) SSO authentication, session management with periodic cleanup |
| `jira_client.py` | Jira REST API v3 wrapper (search, transitions, comments, assignments, request types) |
| `issue_cache.py` | SQLite-backed cache with async 10-min background refresh. Auto-triage on new tickets. Singleton `cache` |
| `metrics.py` | Pure functions computing KPIs, volumes, age buckets, TTR from issue dicts |
| `ai_client.py` | OpenAI/Anthropic abstraction for triage analysis |
| `triage_store.py` | SQLite persistence for triage suggestions and change log |
| `sla_engine.py` | Custom SLA config store, business hours calculator, SLA computation engine |
| `models.py` | Pydantic models for all API request/response types |
| `routes_metrics.py` | Dashboard metrics, legacy JSM SLA endpoints |
| `routes_tickets.py` | Ticket list, single ticket, input validation |
| `routes_actions.py` | Bulk operations (status, assign, priority, comment) |
| `routes_export.py` | Excel export |
| `routes_cache.py` | Cache refresh triggers |
| `routes_chart.py` | Grouped and time series chart data |
| `routes_triage.py` | AI triage: analyze, apply, dismiss, run-all with progress tracking |
| `routes_sla.py` | Custom SLA metrics and configuration endpoints |
| `routes_auth.py` | Auth login/callback/logout/me |

### Frontend (`frontend/src/`)

- **State**: React Query (`@tanstack/react-query`) for server state; URL search params for filters
- **API layer**: `lib/api.ts` — centralized fetch helpers (`fetchJSON`, `postJSON`) and typed endpoint methods
- **Pages**: Dashboard, Tickets, Manage, SLA Tracker, Visualizations, Reports, AI Triage, AI Change Log
- **Charts**: Recharts — components in `components/charts/`
- **Styling**: Tailwind CSS 4 (Vite plugin)
- **Auth**: Layout.tsx gates rendering on auth check — shows spinner until resolved, redirects if unauthenticated

### Testing

**Backend tests** (`backend/tests/`):
- `conftest.py` provides: `sample_issues` (6 fixtures), `mock_cache` (MagicMock), `test_client` (monkeypatches cache + includes auth session cookie)
- Time-frozen at `FROZEN_NOW = 2026-03-04T12:00:00Z` for deterministic assertions
- `pyproject.toml`: asyncio_mode = "auto", function-scoped fixtures

**Frontend tests** (`frontend/src/__tests__/`):
- `test-utils.tsx` exports custom `render()` wrapping components in QueryClientProvider + BrowserRouter
- `test-setup.ts` loads `@testing-library/jest-dom/vitest` matchers
- Environment: jsdom, global test APIs enabled in `vitest.config.ts`

## Key Conventions

- All API routes use `/api/` prefix
- Backend uses snake_case everywhere; frontend API types mirror this
- Route files follow `routes_{domain}.py` naming pattern
- Each router uses `APIRouter(prefix="/api")` or `APIRouter(prefix="/api/{domain}")`
- Environment config via `backend/.env` (never committed — see `.env.example`)
- `CORS_ORIGIN` env var adds a production origin to the allow-list
- Caddy uses `tls internal` (self-signed) since this is an internal network app at `it-app.movedocs.com`

## Business Rules

### Exclusion Rule
Issues with "oasisdev" (case-insensitive) in labels or summary are excluded from all metrics, SLA, triage, and analysis. The cache maintains both filtered and unfiltered views. **All code paths must use `get_filtered_issues()` for user-facing data** — `get_all_issues()` is only for export.

### AI Auto-Triage
- Priority changes auto-apply at **>= 70% confidence**
- Request type changes auto-apply at **>= 90% confidence**
- Model configured via `AUTO_TRIAGE_MODEL` env var
- Background processing with progress tracking via `/api/triage/run-status`
- Modes: Run Remaining (unprocessed only), Test (10 tickets), Reprocess Done, Rerun All
- All changes logged to `auto_triage_log` table and visible on AI Change Log page
- Local cache (in-memory + SQLite) updated after each Jira write

### Stale Threshold
A ticket is "stale" when it's open and not updated in **1+ calendar days**. Defined by `_STALE_DAYS = 1` in `metrics.py`.

### Custom SLA System (`sla_engine.py`)
- **First Response**: time from ticket creation to first comment by non-reporter (agent)
- **Resolution**: time from creation to resolution date
- Computed in **business hours** — configurable via `/api/sla/config/settings`
- Defaults: Mon-Fri, 8am-8pm ET (covers Eastern through Pacific US timezones)
- Default targets: 2h first response, 9h (1 business day) resolution
- Targets configurable per **priority** or **request type** with fallback to default
- Target lookup priority: priority-specific > request_type-specific > default
- Config stored in SQLite (`sla_config.db`), editable from SLA Settings modal in UI

## Security

- Auth middleware protects all `/api/*` paths except public auth endpoints
- Trailing slash bypass prevented (`path.rstrip("/")`)
- Jira key validation via regex (`^[A-Z][A-Z0-9_]+-\d+$`) prevents path traversal
- Exception details sanitized in error responses
- Expired sessions cleaned up periodically
- Security headers added via nginx (X-Content-Type-Options, X-Frame-Options, Referrer-Policy)
- `APP_SECRET_KEY` warns on startup if using insecure default

## UI Patterns

- **Infinite scroll**: Pages with large tables (SLA, AI Log, Tickets) show 100 rows initially, load more on scroll via IntersectionObserver with 200px rootMargin
- **Sorting**: Clickable column headers with asc/desc toggle; priority uses semantic order (Highest → Lowest)
- **Filtering**: Text search + dropdown filters + toggle buttons (Open Only, Stale)
- **Jira links**: Ticket keys link to Jira when `jira_base_url` is available from cache status
