# OIT Helpdesk Dashboard — Design Document

**Date**: 2026-03-03
**Status**: Approved

## Overview

A local web application for bulk-managing OIT helpdesk tickets and visualizing metrics against the established baseline framework. React SPA frontend with a Python FastAPI backend that proxies all Jira REST API calls.

## Architecture

```
Browser (localhost:5173) — React + Vite SPA
  ├── Dashboard (metrics/charts)
  ├── Tickets (filterable data table)
  ├── Bulk Manage (multi-select + actions)
  ├── SLA Tracker (compliance/breach views)
  └── Reports (Excel export)
        │
        │ REST calls
        ▼
Python FastAPI (localhost:8000)
  ├── /api/metrics    (read)
  ├── /api/tickets    (read)
  ├── /api/sla        (read)
  ├── /api/actions    (write → Jira)
  └── /api/export     (generate Excel)
        │
        ▼
  Jira REST API v3 (keyjira.atlassian.net)
```

Two processes: FastAPI on port 8000, Vite dev server on port 5173. API keys stay server-side only.

## Views

### 1. Metrics Dashboard (Home)
- Headline cards: Total tickets, Open backlog, Median TTR, P90 TTR, Stale count
- Monthly trend chart: Created vs Resolved (line chart)
- TTR distribution: histogram of resolution time buckets
- Backlog aging: pie chart (0-2d / 3-7d / 8-14d / 15-30d / 30+d)
- Priority breakdown: bar chart
- Top assignees by volume (resolved + open WIP)
- All metrics exclude `oasisdev` per baseline exclusion rules

### 2. Ticket Table
- Filterable, sortable, searchable with all available columns
- Filters: status, priority, assignee, date range, issue type, request type
- Quick filters: Open only, Stale, High priority
- Row click opens ticket detail panel
- Server-side pagination (50/page)

### 3. Bulk Management
- Multi-select tickets with checkboxes
- Bulk actions toolbar: change status, reassign, change priority, add comment
- Triage queue: pre-filtered unassigned + stale tickets
- Confirmation modal before executing bulk writes

### 4. SLA Tracker
- SLA compliance cards: % Met vs % Breached for 4 SLA timers (First Response, Resolution, Close After Resolution, Review Normal Change)
- At-risk tickets: SLA "Running" and approaching breach
- Breach log: all breached tickets, sortable by timer type
- SLA trend chart: monthly breach rate
- Drill-down to ticket SLA timeline

### 5. Reports
- Export to Excel (baseline report format)
- Date range selector for filtered exports
- Download link for generated .xlsx

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend framework | React 18 + TypeScript |
| Build tool | Vite |
| Routing | React Router v6 |
| UI components | Shadcn/ui + Tailwind CSS |
| Charts | Recharts |
| Data table | TanStack Table |
| State/fetching | TanStack Query |
| Backend | FastAPI (Python) |
| Jira integration | requests + REST API token |

## API Endpoints

```
GET  /api/metrics                 → headline KPIs + monthly trends
GET  /api/tickets?page=&filters=  → paginated ticket list
GET  /api/tickets/{key}           → single ticket detail
GET  /api/sla/summary             → SLA compliance stats
GET  /api/sla/breaches            → breached tickets list
GET  /api/assignees               → assignee list for picker
GET  /api/statuses                → available status transitions
POST /api/tickets/bulk/status     → bulk status change
POST /api/tickets/bulk/assign     → bulk reassignment
POST /api/tickets/bulk/priority   → bulk priority change
POST /api/tickets/bulk/comment    → bulk add comment
GET  /api/export/excel            → generate + download Excel report
```

## Data Rules

- **Exclusions**: All metrics exclude tickets with label/summary containing `oasisdev` (case-insensitive)
- **Status mapping**: Per baseline framework — Active (clock running), Paused (clock stopped), Terminal (resolved/closed)
- **TTR**: Calendar TTR (Created → Resolved) as primary; Active TTR noted as unavailable without changelog
- **Statistics**: Always median + P90/P95, not averages, per baseline

## Deployment

- Local only (localhost)
- Launch: `python backend/main.py` + `npm run dev` (or a single start script)
- No authentication needed (local access only)
