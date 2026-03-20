# Azure Cost Export Landing Zone Runbook

**Applies to:** `DATA-001`
**Status:** Draft

## When To Use

Use this runbook when provisioning, validating, or handing off the Azure cost export landing zone for FOCUS and future export-backed reporting.

## Required Inputs

- Canonical reporting scope from `GOV-001`
- Export writer identity
- Ingestion reader identity
- Break-glass owner
- Azure landing-zone root path
- Expected delivery cadence
- Retention and lifecycle policy

## Required Azure Roles

- Export writer: permission to write deliveries into the landing zone
- Ingestion reader: permission to read raw deliveries and write staging artifacts
- Storage Account Contributor or equivalent: storage setup and validation
- Monitoring Contributor or equivalent: alerting and operational notifications
- Break-glass owner: emergency recovery only

## Landing-Zone Layout

- `raw`: source deliveries
- `manifest`: delivery metadata and health records
- `staged`: normalized output used by downstream consumers
- `quarantine`: malformed or incomplete deliveries

## Provisioning Checklist

1. Create or confirm the HNS-enabled ADLS Gen2 landing zone.
2. Apply RBAC to the export writer, ingestion reader, and break-glass owner.
3. Confirm the canonical path layout matches the repo contract.
4. Apply retention and lifecycle policies for raw, staged, manifest, and quarantine areas.
5. Confirm the filesystem or mounted sync path is readable by the ingestion runtime.

## Smoke Test

1. Write one test delivery into the canonical `raw` path.
2. Confirm the landing path can be listed and read.
3. Confirm the ingestion path can discover the delivery.
4. Confirm a manifest row is recorded for the delivery.
5. Confirm a staged snapshot is produced for a good file.
6. Confirm a malformed file is routed to quarantine.
7. Confirm the health summary reports the expected delivery and parse counts.

## Operating Expectations

- Do not close `DATA-001` on config alone.
- Keep the canonical path stable once smoke tests pass.
- Treat delivery directories as immutable after ingestion.
- Keep raw, staged, manifest, and quarantine areas separate so later reporting layers stay simple.

## Handoff

1. Record the final landing-zone root path and scope.
2. Record the DRI for the export writer and ingestion reader.
3. Record the retention and lifecycle policy in the operating notes.
4. Record the last successful smoke test date and what was validated.
5. Pass ownership to the data lane before enabling downstream BI cutover work.

## Escalation

- Escalate RBAC mismatches to the Azure platform owner.
- Escalate retention or lifecycle gaps to the storage owner.
- Escalate delivery path changes to FinOps and engineering before changing the contract.

