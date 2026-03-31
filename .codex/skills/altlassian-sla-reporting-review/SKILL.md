---
name: altlassian-sla-reporting-review
description: SLA and reporting analysis workflow for the Altlassian repo. Use when asked for a deep dive on SLA behavior, report accuracy, export discrepancies, workbook summary behavior, or prioritized recommendations before a reporting refactor.
---

# Altlassian SLA Reporting Review

If you are using this skill from the repo, read `../../../docs/runbooks/ai/skills/altlassian-sla-reporting-review.md` and `../../../CLAUDE.md` first. If those files are not available from your current skill location, use this file as the operating guide.

## Workflow

1. Confirm which surface is under review: dashboard, export, workbook, or AI summary.
2. Trace the metric definition from source data through backend generation and frontend or workbook presentation.
3. Separate calculation problems from formatting and narrative problems.
4. Lead with findings, then open questions, then recommended improvements.
5. Tie every recommendation back to a concrete code path or missing test.

## Guardrails

- Treat AI summaries as presentation, not the source of truth for metric definitions.
- Keep scope-aware filtering in mind when comparing primary and OasisDev behavior.
- Do not change SLA semantics casually or without documenting the rule change.
- Prefer small high-confidence improvements before large semantic rewrites.

## Verification

- Cite the code paths that define the reported behavior.
- Call out missing tests or unclear specs explicitly.
- If code changes later, add paired backend and frontend or workbook coverage where needed.
