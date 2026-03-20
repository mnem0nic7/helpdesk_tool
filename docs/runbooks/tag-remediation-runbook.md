# Tag Remediation Runbook

**Applies to:** `GOV-003`
**Status:** Draft

## When To Use

Use this runbook when required Azure cost tags are missing, invalid, or inconsistent.

## Required Inputs

- Scope under review
- Missing or invalid tag key
- Resource identifier
- Owner
- Remediation due date

## Remediation Steps

1. Confirm the canonical tag key and allowed value.
2. Identify whether the tag is missing, malformed, or using an alias.
3. Assign an owner and due date.
4. Remediate the tag at the correct scope.
5. Re-run the baseline audit.
6. Record the outcome and any exception.

## Escalation

- Escalate repeated violations to the platform owner.
- Escalate policy exceptions to FinOps for approval.
- Track unresolved items until the next weekly review.

