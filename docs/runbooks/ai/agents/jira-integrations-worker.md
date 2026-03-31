# Jira Integrations Worker

Use this playbook with the built-in `worker` agent type for bounded Jira write-path and ticket-workbench fixes.

## Ownership boundary

- Own backend Jira route, client, and write-service changes.
- Own paired frontend ticket-workbench or API-helper changes when the contract changes.
- Own focused tests for the affected Jira flow.

## Expected inputs

- Failing ticket scenario or error message.
- Specific write path or UI surface involved.
- Allowed write scope, such as ticket routes, Jira client logic, and drawer UI.

## Expected output

- Changed files.
- What behavior was fixed.
- Tests run and what they covered.
- Any remaining Jira-side policy constraint.

## Must not touch

- Release infrastructure or unrelated Azure surfaces.
- Large UI redesigns unrelated to the Jira flow.
- Reverting unrelated work from other contributors.

## Wait vs keep working

- Keep working until the Jira flow and tests are coherent inside the assigned write scope.
- Escalate back quickly if the real blocker is a Jira project policy change instead of app behavior.

## Validation scenario

- OIT-19526 component or application edit failure.
