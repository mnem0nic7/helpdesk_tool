# DATA-001 Landing Zone Access Model

**Status:** Draft
**Owner:** Azure Platform + Data Engineering
**Related roadmap item:** `DATA-001`

## Purpose

Document the v1 access model for Azure cost export deliveries so the repo, runbooks, and Azure-side provisioning all point at the same landing-zone shape.

## Decision Summary

For v1, the landing zone is treated as a filesystem-first path contract. The repo assumes export deliveries can be read from a mounted or synced filesystem path that mirrors the canonical ADLS layout, with the option to switch to direct ADLS SDK access later if the team needs it.

## Decision Record

| Field | Value |
|------|-------|
| v1 access model | Filesystem-first, mounted or synced landing zone |
| Canonical landing zone | ADLS Gen2 path mirrored into a local or mounted filesystem root |
| Direct ADLS SDK required for v1 | No |
| Mounted/synced filesystem supported | Yes |
| Canonical delivery key | `dataset/scope/delivery_date=YYYY-MM-DD/run=RUN_ID/raw` |
| Staging area | `_staging` or equivalent filesystem-backed output |
| Quarantine area | `_quarantine` or equivalent filesystem-backed output |
| Manifest store | SQLite-backed local store |
| Future access model changes | Allowed after v1 if operational scale requires it |

## Why This Choice

- It matches the current repo implementation, which discovers deliveries from canonical filesystem paths and stages snapshots locally.
- It keeps the v1 integration simple for smoke tests and handoff, because the same path contract works in dev, test, and a mounted production landing zone.
- It avoids forcing Azure SDK dependencies into the repo before the Azure provisioning work is stable.

## Operational Implications

- Export deliveries must land in the canonical directory layout before ingestion starts.
- The delivery directory itself is the idempotency key for processing.
- Manifest, staging, and quarantine artifacts are stored separately from raw deliveries.
- RBAC still needs to protect the real ADLS location, even if the repo consumes a mounted or synced view of it.

## Acceptance Criteria

- The filesystem-first/mounted-or-synced choice is explicitly recorded for v1.
- The canonical landing-zone path format is fixed.
- The manifest, staging, and quarantine responsibilities are documented.
- The decision is understandable by both Azure operators and repo maintainers without reading code first.

