# Azure Cost Governance Access Request Runbook

**Applies to:** `GOV-002`
**Status:** Draft

## When To Use

Use this runbook when requesting, reviewing, or approving Azure access for cost governance work.

## Required Information

- Requester name
- DRI or team name
- Target scope
- Requested role
- Business justification
- Time bound or permanent
- Approver

## Required Roles

- Cost Management Contributor for builders
- Cost Management Reader for viewers
- Storage Account Contributor or equivalent for export targets
- Monitoring Contributor or equivalent for alert and action-group setup

## Process

1. Confirm the request maps to the canonical reporting scope.
2. Confirm the requester needs Azure-side access, not app-only access.
3. Verify the minimum role needed for the task.
4. Submit the request with justification and the target scope.
5. Record the approval and fulfillment date.
6. Revoke or review access during the next governance cycle if it is temporary.

## Validation

- Confirm the principal can read the expected scope.
- Confirm export-target permissions work if the request includes storage access.
- Confirm any alert or action-group permissions are sufficient without granting broader rights.

## Escalation

- Escalate to the Azure platform owner if the scope is unclear.
- Escalate to FinOps if the request changes the governance model.
- Use break-glass ownership only for emergency recovery.

