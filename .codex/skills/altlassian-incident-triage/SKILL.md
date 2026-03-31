---
name: altlassian-incident-triage
description: Incident-triage workflow for Altlassian outages, 502s, blank pages, and host-specific regressions. Use when `it-app`, `oasisdev`, or `azure` appears down, a page falls into a generic error boundary, or a recent deploy needs fast fault isolation.
---

# Altlassian Incident Triage

If you are using this skill from the repo, read `../../../docs/runbooks/ai/skills/altlassian-incident-triage.md` and `../../../CLAUDE.md` first. If those files are not available from your current skill location, use this file as the operating guide.

## Workflow

1. Confirm the exact host, path, timestamp, and visible symptom.
2. Check live `/api/health` and `/api/health/ready` for the affected host.
3. Inspect active blue and green runtime state, then read the most relevant logs.
4. Separate app failures from dependency failures such as Jira, Graph, or Exchange permission problems.
5. Identify the likely fault domain and recommend the next safe action: retry, fail over, hotfix, redeploy, or rollback.

## Guardrails

- Treat scope-aware route differences as part of diagnosis. Not every host exposes the same surface.
- Remember that a healthy standby color does not prove the active color is healthy.
- Check for known signatures such as DuckDB lock contention and frontend hook-order crashes.
- Do not start editing code until the fault domain is narrowed.

## Verification

- State the host, active color, and likely fault domain.
- Cite the evidence that supports the diagnosis.
- Confirm public recovery before declaring the incident resolved.
