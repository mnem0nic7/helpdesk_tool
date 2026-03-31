# M365 Tools Worker

Use this playbook with the built-in `worker` agent type for shared Tools-page features that depend on Graph, Exchange, or mailbox-provider logic.

## Ownership boundary

- Own Tools routes, mailbox and Exchange provider logic, API type updates, and Tools page card behavior.
- Own focused route, provider, and Tools page tests for the affected feature.

## Expected inputs

- Target tool or failing user flow.
- Whether the work is Graph-only, Exchange-backed, or UI-only.
- Allowed write scope across backend provider code and frontend Tools files.

## Expected output

- Changed files.
- Dependency or permission assumptions.
- Tests and builds run.
- Any remaining tenant-admin or runtime prerequisite.

## Must not touch

- Jira ticket flows.
- Host-scope rules that expose Tools on unsupported surfaces.
- Unrelated dashboard or report pages.

## Wait vs keep working

- Keep working inside the assigned feature lane until backend, frontend, and error handling agree.
- Escalate if the requested behavior depends on tenant permissions or runtime capabilities that the app does not have.

## Validation scenario

- Mailbox rules permission troubleshooting or Exchange delegate-access additions.
