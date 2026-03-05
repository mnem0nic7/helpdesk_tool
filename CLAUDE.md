# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OIT Helpdesk Dashboard — a full-stack Jira helpdesk analytics tool with AI-powered ticket triage. FastAPI backend connects to Jira Cloud, caches issues in SQLite, computes metrics, and serves a React SPA.

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
| `main.py` | FastAPI app, CORS, router registration, lifespan (cache start/stop) |
| `config.py` | Loads `.env` — Jira creds, AI keys, DATA_DIR |
| `jira_client.py` | Jira REST API v3 wrapper (search, transitions, comments, assignments) |
| `issue_cache.py` | SQLite-backed cache with async 10-min background refresh. Singleton `cache` instance |
| `metrics.py` | Pure functions computing KPIs, volumes, age buckets, TTR, SLA from issue dicts |
| `ai_client.py` | OpenAI/Anthropic abstraction for triage analysis |
| `triage_store.py` | SQLite persistence for triage results |
| `models.py` | Pydantic models for all API request/response types |
| `routes_*.py` | 7 routers: metrics, tickets, actions, export, cache, chart, triage |

**Exclusion rule**: Issues with "oasisdev" (case-insensitive) in labels or summary are filtered out. The cache maintains both filtered and unfiltered views.

### Frontend (`frontend/src/`)

- **State**: React Query (`@tanstack/react-query`) for server state; URL search params for filters
- **API layer**: `lib/api.ts` — centralized fetch helpers (`fetchJSON`, `postJSON`) and typed endpoint methods
- **Pages**: Dashboard, Tickets, Manage, SLA, Visualizations, Reports, Triage
- **Charts**: Recharts — components in `components/charts/`
- **Styling**: Tailwind CSS 4 (Vite plugin)

### Testing

**Backend tests** (`backend/tests/`):
- `conftest.py` provides: `sample_issues` (6 fixtures), `mock_cache` (MagicMock), `test_client` (monkeypatches cache into all route modules)
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
- Each router uses `APIRouter(prefix="/api")`
- Environment config via `backend/.env` (never committed — see `.env.example`)
- `CORS_ORIGIN` env var adds a production origin to the allow-list
- Caddy uses `tls internal` (self-signed) since this is an internal network app at `it-app.movedocs.com`
