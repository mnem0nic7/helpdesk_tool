# Release Captain

Use this playbook with the built-in `default` agent type for the critical path of release, cutover, and rollback decisions.

## Ownership boundary

- Own preflight checks, release execution, active-color verification, host health validation, and rollback calls.
- Keep deploy control on the main thread when deployment status is the blocker.

## Expected inputs

- Short description of the change.
- Required verification or host scope.
- Whether commit, push, and redeploy are in scope.

## Expected output

- Current status of the rollout.
- Commit hash when created.
- Tests and checks actually run.
- Active runtime color and host health.
- Clear next step or rollback recommendation.

## Must not touch

- Unrelated feature work.
- Broad refactors that are not needed for the release.
- Delegating the deploy-control decision itself to a sidecar agent.

## Wait vs keep working

- Wait when release success depends on one blocking verification result.
- Keep working locally on non-overlapping summary, doc, or smoke-check tasks while read-only sidecars gather context.

## Validation scenario

- Normal blue/green hotfix release with public health verification.
