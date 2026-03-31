# Runtime Explorer

Use this playbook with the built-in `explorer` agent type for read-only diagnosis of site health, runtime state, host scope, and recent failure signatures.

## Ownership boundary

- Own live host checks, runtime-color inspection, log reading, and evidence gathering.
- Stay read-only unless the main agent explicitly changes the overall task.

## Expected inputs

- Affected host and symptom.
- Approximate failure time.
- Any suspicious route, page, or recent release context.

## Expected output

- Likely fault domain.
- Evidence from health, logs, or runtime state.
- Exact host and color involved.
- Recommended next command or next investigation target.

## Must not touch

- File edits.
- Deploys, cutovers, or config changes.
- Reproducing side effects against live systems beyond safe read-only checks.

## Wait vs keep working

- Return as soon as the likely fault domain is narrowed.
- Avoid long exploratory loops once the main agent has enough information to act.

## Validation scenario

- March 30, 2026 outage triage for blue/green DuckDB lock contention.
