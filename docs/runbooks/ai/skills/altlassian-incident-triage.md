# Altlassian Incident Triage

Use this workflow for site-down reports, 502s, blank pages, generic frontend error boundaries, and host-specific regressions.

## Trigger conditions

- The user reports `it-app`, `oasisdev`, or `azure` is down.
- A page shows a generic "Something went wrong" state and the fault domain is unclear.
- A release needs fast fault isolation before deciding rollback vs forward-fix.

## Required first reads

- `CLAUDE.md`
- `backend/main.py`
- `backend/site_context.py`
- `docker-compose.yml`

## Commands and checks to run first

- Confirm the exact host, path, timestamp, and visible symptom.
- Check live `/api/health` and `/api/health/ready` for the affected host.
- Inspect active backend and frontend container state for both blue and green runtimes.
- Read the most relevant logs for the active color before editing anything.

## Workflow

- Narrow the issue to host, path, and fault type before you change code.
- Separate app failures from dependency failures such as Graph, Exchange, or Jira permission issues.
- Determine whether the problem is proxy routing, runtime health, leader coordination, or a feature regression.
- Check known recurring signatures, especially DuckDB lock contention across blue/green and frontend hook-order crashes.
- Recommend the next safe action: retry, fail over, hotfix, redeploy, or rollback.

## Invariants and gotchas

- Tools routes intentionally do not exist on `oasisdev`; a `404` there may be expected.
- A healthy standby color does not mean the active color is healthy.
- A frontend error boundary can look like an outage even when backend health is fine.
- Shared Azure FinOps storage can create restart contention if color scoping is bypassed.

## Required verification

- Identify the likely fault domain with concrete evidence.
- Confirm whether the issue is host-specific or cross-surface.
- State the active runtime color and whether `leader_ready` is healthy.
- If the system recovers, confirm the public host is serving again before closing the incident.

## Closeout checklist

- Capture the host, runtime color, and root cause in the final summary.
- Update `CLAUDE.md` or an incident-related runbook if a new failure mode or recovery step was discovered.

## Validation scenario

- Dry-run against the March 30, 2026 blue/green DuckDB lock contention outage.
