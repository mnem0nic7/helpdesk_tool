# Azure FinOps Safe Remediation Hooks

## Purpose

Safe remediation hooks let operators run allowlisted recommendation follow-up commands from the Azure Savings workspace without turning the app into a general-purpose remote shell.

This surface is intentionally conservative.

## What A Safe Hook Is

A safe hook is:

- a preconfigured command list
- selected by hook key from an allowlist
- matched to one or more recommendation categories or opportunity types
- fed structured JSON over stdin
- audited in recommendation history

A safe hook is not:

- arbitrary shell input
- a destructive auto-remediation system
- a replacement for change control

## Configuration

Environment variable:

- `AZURE_FINOPS_SAFE_SCRIPT_HOOKS_JSON`

Shape:

```json
{
  "vm_echo": {
    "label": "VM Echo",
    "description": "Dry-run starter hook for compute recommendations.",
    "command": ["python3", "/app/backend/scripts/azure_finops_safe_hook_echo.py"],
    "allowed_categories": ["compute"],
    "allowed_opportunity_types": ["rightsizing", "idle_vm_attached_cost"],
    "default_dry_run": true,
    "allow_apply": false,
    "repeatable": true,
    "timeout_seconds": 120
  }
}
```

Key fields:

- `command`
  - required
  - must be a list, not a shell string
- `allowed_categories`
  - optional
  - if present, the hook only appears for matching recommendation categories
- `allowed_opportunity_types`
  - optional
  - if present, the hook only appears for matching opportunity types
- `default_dry_run`
  - defaults to `true`
- `allow_apply`
  - defaults to `false`
- `repeatable`
  - defaults to `true`
- `timeout_seconds`
  - defaults to `120`

## Example Starter Hook

Bundled example:

- [azure_finops_safe_hook_echo.py](/workspace/altlassian/backend/scripts/azure_finops_safe_hook_echo.py)

It is a non-destructive starter hook that:

- reads the structured payload from stdin
- emits a JSON summary
- exits successfully

Use it as a smoke-test hook before wiring a real remediation workflow.

## Execution Model

Route:

- `POST /api/azure/recommendations/{id}/actions/run-safe-script`

Current request body:

```json
{
  "hook_key": "vm_echo",
  "dry_run": true,
  "note": "Preview the remediation path."
}
```

The backend:

1. validates the recommendation still exists
2. checks the action contract and admin access
3. validates that the selected hook is allowlisted and applicable
4. executes the configured command without a shell
5. passes structured JSON over stdin
6. records the result in recommendation history

## Payload Passed To Hooks

Hooks receive structured JSON with:

- `hook`
- `execution`
- `recommendation`

The recommendation payload is the persisted recommendation snapshot currently visible to the action layer.

## History Semantics

Successful dry-run:

- action type: `run_safe_script`
- action status: `dry_run`
- recommendation `action_state` stays unchanged

Successful apply-mode run:

- action type: `run_safe_script`
- action status: `completed`
- recommendation `action_state` becomes `script_executed`

Failure:

- action type: `run_safe_script`
- action status: `failed`
- recommendation `action_state` stays unchanged

Stored metadata includes:

- hook key
- hook label
- dry-run flag
- duration
- exit code
- output excerpt
- error text when applicable

## Guardrails

- Admin-only route and UI path
- No user-supplied shell fragments
- No shell execution
- Hook applicability is filtered by category and opportunity type
- Apply mode is blocked unless the hook explicitly allows it
- Dismissed recommendations still block direct actions

## Operator Workflow

1. Configure one or more allowlisted hooks in `AZURE_FINOPS_SAFE_SCRIPT_HOOKS_JSON`.
2. Start with the bundled echo hook in dry-run mode.
3. Open a recommendation in the Savings workspace.
4. Select the safe hook.
5. Keep dry-run enabled unless the hook explicitly supports apply mode.
6. Add an operator note.
7. Run the hook and review the recorded output in history.

## Troubleshooting

### No safe hook appears in the drawer

Check:

1. the environment variable is populated
2. the hook matches the recommendation category or opportunity type
3. the recommendation is not dismissed

### Apply mode stays disabled

That is expected unless the selected hook sets:

- `"allow_apply": true`

### The hook fails immediately

Check:

1. the command path exists in the runtime container
2. the executable is installed
3. the command does not rely on shell features
4. the hook can parse JSON from stdin

### The hook times out

Increase:

- `timeout_seconds`

Or reduce the amount of work done synchronously by the hook.

## Release Guidance

Treat new hooks like controlled operational automation:

- review the command list
- verify the recommendation filters are narrow enough
- start with dry-run
- only enable apply mode when the hook behavior is well understood
