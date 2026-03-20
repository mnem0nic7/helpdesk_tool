# GOV-001 Reporting Scope Decision

**Status:** Draft
**Owner:** FinOps + Engineering
**Related roadmap item:** `GOV-001`

## Purpose

Choose one canonical reporting scope for Azure Cost Management, exports, Power BI, and downstream governance.

## Decision Required

Pick one:

- Billing profile / billing account scope
- Management group scope
- Subscription scope

## Inputs To Review

- Current billing hierarchy
- Supported child scopes
- High-risk subscopes that need separate budgets or anomaly attention
- Agreement-model constraints
- Finance and engineering sign-off path

## Decision Record

| Field | Value |
|------|-------|
| Canonical scope of record | TBD |
| Allowed child scopes | TBD |
| Excluded scopes | TBD |
| High-risk subscopes | TBD |
| Finance owner | TBD |
| Engineering owner | TBD |
| Decision date | TBD |

## Acceptance Criteria

- One scope is named as the reporting scope of record.
- Child scopes and excluded scopes are documented.
- High-risk subscopes are called out explicitly.
- Finance and engineering approve the selection.

## Implementation Notes

- Use this record as the source of truth for budgets, saved views, anomaly alerts, exports, and BI.
- If management-group behavior differs by billing model, record that exception here rather than in downstream docs.

