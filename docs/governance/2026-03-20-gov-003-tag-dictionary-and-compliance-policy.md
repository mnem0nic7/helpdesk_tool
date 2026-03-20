# GOV-003 Tag Dictionary And Compliance Policy

**Status:** Draft
**Owner:** FinOps + Azure Platform
**Related roadmap item:** `GOV-003`

## Purpose

Standardize the business dimensions used for showback, chargeback, and BI slicing.

## Required Tags

- `application_service`
- `environment`
- `owner`
- `cost_center`
- `business_unit`

## Policy Decisions

| Field | Value |
|------|-------|
| Required tags | TBD |
| Optional tags | TBD |
| Allowed value format | TBD |
| Controlled vocabulary source | TBD |
| Tag inheritance enabled in v1 | TBD |
| Exceptions | TBD |

## Compliance Rules

- Missing required tags must be tracked.
- Invalid values must be remediated by an assigned owner.
- Tag inheritance timing must be explicitly documented.
- The policy must support BI dimensions without requiring ad hoc mappings.

## Baseline Audit Inputs

- Current resource-tag inventory
- Missing-tag evaluation
- Conflicting tag keys or casing
- Legacy alias keys

## Acceptance Criteria

- Canonical tag keys are documented.
- Required versus optional tags are explicit.
- Remediation ownership exists for missing or invalid tags.
- The inheritance decision is recorded.

