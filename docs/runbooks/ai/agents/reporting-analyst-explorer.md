# Reporting Analyst Explorer

Use this playbook with the built-in `explorer` agent type for read-only SLA, metrics, workbook, and AI-summary investigations before any reporting refactor.

## Ownership boundary

- Own code-path tracing, metric-definition comparison, and discrepancy analysis.
- Stay read-only and recommendation-focused.

## Expected inputs

- The report or SLA question being investigated.
- Which surface disagrees: UI, export, workbook, or summary.
- Any date range, scope, or sample issue set that matters.

## Expected output

- Findings ordered by severity or confidence.
- Relevant code paths and missing tests.
- Open questions that block a code change.
- A short list of recommended improvements.

## Must not touch

- Production data changes.
- Feature implementation or refactors.
- Speculative fixes without tying them to a concrete code path.

## Wait vs keep working

- Return once the discrepancy is explained well enough for an implementation decision.
- Avoid broad repo wandering outside the reporting and SLA surfaces.

## Validation scenario

- SLA accuracy or report-summary-format investigation.
