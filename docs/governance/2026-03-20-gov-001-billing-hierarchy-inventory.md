# GOV-001 Billing Hierarchy Inventory

**Status:** Draft
**Owner:** FinOps + Engineering
**Related roadmap item:** `GOV-001`

## Purpose

Capture the current Azure billing hierarchy so the team can choose one canonical reporting scope without guessing.

## Inventory Scope

- Billing account / billing profile
- Enrollment or agreement boundary
- Management groups
- Subscriptions
- High-risk subscopes

## Inventory

| Layer | Identifier / Name | Included in v1 reporting? | Notes |
|------|-------------------|---------------------------|-------|
| Billing account | TBD | TBD | Primary agreement boundary |
| Billing profile | TBD | TBD | MCA / EA specific value |
| Invoice section | TBD | TBD | If applicable |
| Management group root | TBD | TBD | Highest governed Azure scope |
| Management groups | TBD | TBD | List child groups here |
| Subscription | TBD | TBD | List highest-risk subscriptions |
| Resource group | TBD | TBD | Only if needed for drill-down |

## What To Capture

- Canonical identifier for each billing layer
- Whether the layer can host budgets, exports, and Cost Analysis views
- Whether the layer is suitable as the reporting scope of record
- Any child scopes that must remain visible for accountability
- Any scope that should be excluded from v1 reporting

## Decision Inputs

- Agreement model
- Governance feasibility
- Finance reporting needs
- Engineering ownership boundaries
- Known exceptions for shared or platform costs

## Acceptance Criteria

- The current billing hierarchy is listed in one place.
- The inventory names the candidate v1 reporting scope and visible child scopes.
- High-risk subscopes are called out for budget and anomaly review.
- The inventory is detailed enough to support the `GOV-001` decision record.

