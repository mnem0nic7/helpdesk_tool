---
name: altlassian-release-cutover
description: Release, cutover, and post-deploy verification workflow for the Altlassian repo. Use when asked to commit, push, redeploy, switch the active blue/green runtime, verify live health, or decide whether to continue or roll back after a release.
---

# Altlassian Release Cutover

If you are using this skill from the repo, read `../../../docs/runbooks/ai/skills/altlassian-release-cutover.md` and `../../../CLAUDE.md` first. If those files are not available from your current skill location, use this file as the operating guide.

## Workflow

1. Inspect `git status --short`, the intended diff, and the requested rollout scope.
2. Run the smallest meaningful backend, frontend, or build verification set before release.
3. Use `./release.sh -m "message"` for standard repo releases unless the task explicitly requires another path.
4. Verify live `/api/health` and `/api/health/ready` responses for the affected hosts.
5. Confirm the active runtime color, `leader_ready` state, and clean worktree before closing out.

## Guardrails

- Treat blue/green color and leader readiness as critical-path checks.
- Verify public host responses, not only local container state.
- Keep Azure FinOps DuckDB color scoping intact when touching runtime configuration.
- Update `CLAUDE.md`, `README.md`, or a runbook when the release changes recurring operator knowledge.

## Verification

- Run focused automated checks for touched areas.
- Check affected public hosts after deploy.
- Record commit hash, runtime color, and any unresolved risk in the summary.
