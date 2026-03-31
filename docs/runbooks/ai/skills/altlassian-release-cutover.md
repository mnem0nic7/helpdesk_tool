# Altlassian Release Cutover

Use this workflow for commit, push, redeploy, blue/green cutover, or post-release verification work.

## Trigger conditions

- The user asks to commit, push, redeploy, or release a change.
- A hotfix is ready and needs live validation.
- A blue/green runtime color change or rollback decision is part of the task.

## Required first reads

- `CLAUDE.md`
- `README.md`
- `release.sh`
- `deploy.sh`

## Commands and checks to run first

- Inspect `git status --short` and confirm the intended diff is isolated.
- Pick focused backend, frontend, or build checks for the touched areas before release.
- Confirm the affected hosts and expected site scopes before you deploy.

## Workflow

- Verify the worktree state, changed files, and requested rollout scope.
- Run the smallest meaningful pre-release verification set.
- Use `./release.sh -m "message"` for standard releases unless the task explicitly requires a different path.
- Verify live `/api/health` and `/api/health/ready` responses on the affected hosts, including `leader_ready=true` when expected.
- Confirm the active runtime color and that the expected host is serving the new version.
- End with a clean worktree and a concise summary that includes commit, tests, health, runtime color, and unresolved risk.

## Invariants and gotchas

- Treat blue/green color and leader readiness as critical-path signals, not nice-to-have checks.
- Keep Azure FinOps DuckDB color scoping intact when touching runtime configuration.
- Do not claim success from container logs alone. Verify the public host responses.
- Keep scope-aware behavior intact: `oasisdev` is not the same surface as `it-app`, and `azure` has a different route set.

## Required verification

- Focused automated checks for touched areas.
- Public health checks for each affected host.
- Runtime color confirmation after release.
- `git status --short` is clean after commit and deploy work.

## Closeout checklist

- Update `CLAUDE.md` if the release changed recurring operational knowledge.
- Update `README.md` or a runbook if the operator workflow changed materially.
- Include commit hash, deploy color, verification run, and health status in the final summary.

## Validation scenario

- Dry-run against a normal feature release with blue/green verification and no rollback.
