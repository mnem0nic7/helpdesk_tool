# GOV-002 Cost Governance Ownership Matrix

**Status:** Draft
**Owner:** FinOps + Azure Platform
**Related roadmap item:** `GOV-002`

## Purpose

Name the DRIs and boundaries for native Azure cost governance work.

## Operating Lanes

- FinOps
- Azure platform
- BI
- App integration

## Ownership Matrix

| Activity | Primary DRI | Backup | Approver | Notes |
|---------|-------------|--------|----------|-------|
| Cost Analysis views | TBD | TBD | TBD | Includes saved views and sharing |
| Budgets | TBD | TBD | TBD | Includes threshold reviews |
| Anomaly review | TBD | TBD | TBD | Includes weekly follow-up |
| Export setup | TBD | TBD | TBD | Includes storage and RBAC |
| BI handoff | TBD | TBD | TBD | Includes report consumers and refresh |

## Required Azure Access

| Role | Who needs it | Scope |
|------|--------------|-------|
| Cost Management Contributor | Builders | Canonical scope |
| Cost Management Reader | Viewers | Canonical scope |
| Storage Account Contributor or equivalent | Export operators | Export target |
| Monitoring Contributor or equivalent | Notification operators | Alert/action-group scope |

## Required Identities

- Export writer
- Ingestion reader
- Finance reviewer
- Engineering operator
- Break-glass owner

## Access Request Path

- Request mechanism: TBD
- Justification required: yes
- Approver chain: TBD
- Fulfillment owner: TBD
- Target SLA: TBD

## Acceptance Criteria

- DRIs are named for all operating lanes.
- Required Azure permissions are documented at the right scope.
- The access-request path is defined and testable.

