# Altlassian SLA Reporting Review

Use this workflow for SLA deep dives, reporting accuracy reviews, export discrepancies, and report-summary behavior questions.

## Trigger conditions

- The user asks for a deep dive on SLA reporting.
- Metrics disagree across the UI, exports, or workbook outputs.
- AI summary formatting or report interpretation needs review.

## Required first reads

- `CLAUDE.md`
- `backend/sla_engine.py`
- `backend/routes_metrics.py`
- `backend/routes_export.py`
- `backend/report_workbook_builder.py`
- `backend/report_ai_summary_service.py`

## Commands and checks to run first

- Identify which surface is in question: dashboard, export, workbook, or AI summary.
- Trace the metric definition from source data through the API and rendered output.
- Review the nearest specs or report tests before proposing changes.

## Workflow

- Map the SLA metric definition, filters, clock behavior, and exclusions before making recommendations.
- Compare backend metric generation with frontend presentation and workbook export behavior.
- Distinguish accuracy issues from formatting or narrative issues.
- Prioritize improvements by impact, verification cost, and risk of behavioral regression.
- When asked for a review, lead with findings, then open questions, then recommended changes.

## Invariants and gotchas

- Report exports and in-app summaries may share data but present it differently.
- AI summaries should not be treated as the source of truth for metric calculations.
- Scope-aware filtering still matters when comparing primary and OasisDev helpdesk behavior.
- Do not change SLA semantics casually; document any metric-definition change.

## Required verification

- Cite the code path that defines the metric or export behavior.
- Call out any missing tests or unclear specification.
- If code is changed later, add paired backend and frontend or workbook coverage where appropriate.

## Closeout checklist

- Summarize the highest-risk discrepancies first.
- Recommend the smallest high-confidence improvements before larger semantic changes.
- Update a spec or runbook if the review settles a recurring reporting rule.

## Validation scenario

- Dry-run against an SLA accuracy or summary-format review request.
