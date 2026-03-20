# GOV-002 Azure Access Matrix

**Status:** Draft
**Owner:** FinOps + Azure Platform
**Related roadmap item:** `GOV-002`

## Purpose

Define the Azure-side permissions needed to operate cost governance safely.

## Access Model

| Role | Who needs it | Scope | Purpose |
|------|--------------|-------|---------|
| Cost Management Reader | Finance viewers, BI consumers | Canonical reporting scope | Read Cost Analysis, budgets, and reports |
| Cost Management Contributor | FinOps builders, Azure platform operators | Canonical reporting scope | Create and manage governance controls |
| Storage Account Contributor or equivalent | Export operators | Export landing zone | Configure export writes and validate storage access |
| Monitoring Contributor or equivalent | Notification operators | Alert or action-group scope | Manage budgets, anomaly notifications, and scheduled responses |

## Operating Roles

| Role | Primary DRI | Backup | Notes |
|------|-------------|--------|-------|
| FinOps | TBD | TBD | Owns budget and governance cadence |
| Azure platform | TBD | TBD | Owns RBAC and export plumbing |
| BI | TBD | TBD | Owns downstream reporting and validation |
| App integration | TBD | TBD | Owns app-facing handoff and status surfaces |

## Required Identities

- Export writer
- Ingestion reader
- Finance reviewer
- Engineering operator
- Break-glass owner

## Access Request Path

| Field | Value |
|------|-------|
| Request mechanism | TBD |
| Required justification | Yes |
| Approver chain | TBD |
| Fulfillment owner | TBD |
| Target SLA | TBD |

## Validation Checklist

- Confirm the requester needs Azure-side access, not app-only access.
- Confirm the role is scoped to the canonical reporting scope or export target.
- Confirm the request is least-privilege for the intended task.
- Confirm temporary access is time-bound and reviewable.

## Acceptance Criteria

- Required Azure permissions are documented by activity and scope.
- DRIs are named for all operating lanes.
- The access-request path is defined well enough to follow without tribal knowledge.

