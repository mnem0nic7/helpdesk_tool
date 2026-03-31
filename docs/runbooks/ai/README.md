# AI Workflow Runbooks

This directory is the shared source of truth for Altlassian AI-assisted workflows. The matching repo-local Codex skills live under `.codex/skills/` and should mirror these docs instead of inventing a second set of rules.

## Use a skill when

- You want Codex to execute a repeatable workflow end-to-end.
- You want consistent startup reads, checks, guardrails, and verification.
- You want the workflow to be callable by name or by skill path in another session.

## Use an agent playbook when

- You want to split work across the existing `default`, `explorer`, and `worker` agent types.
- You need a clear ownership boundary for a delegated task.
- You want a repeatable output format for sidecar work without creating a new platform agent type.

## Skill catalog

- `altlassian-release-cutover`
  Doc: `docs/runbooks/ai/skills/altlassian-release-cutover.md`
  Skill: `.codex/skills/altlassian-release-cutover/`
- `altlassian-incident-triage`
  Doc: `docs/runbooks/ai/skills/altlassian-incident-triage.md`
  Skill: `.codex/skills/altlassian-incident-triage/`
- `altlassian-jira-hotfix`
  Doc: `docs/runbooks/ai/skills/altlassian-jira-hotfix.md`
  Skill: `.codex/skills/altlassian-jira-hotfix/`
- `altlassian-m365-tools`
  Doc: `docs/runbooks/ai/skills/altlassian-m365-tools.md`
  Skill: `.codex/skills/altlassian-m365-tools/`
- `altlassian-closeout`
  Doc: `docs/runbooks/ai/skills/altlassian-closeout.md`
  Skill: `.codex/skills/altlassian-closeout/`
- `altlassian-sla-reporting-review`
  Doc: `docs/runbooks/ai/skills/altlassian-sla-reporting-review.md`
  Skill: `.codex/skills/altlassian-sla-reporting-review/`

## Agent playbook catalog

- `release-captain`
  Doc: `docs/runbooks/ai/agents/release-captain.md`
- `runtime-explorer`
  Doc: `docs/runbooks/ai/agents/runtime-explorer.md`
- `jira-integrations-worker`
  Doc: `docs/runbooks/ai/agents/jira-integrations-worker.md`
- `m365-tools-worker`
  Doc: `docs/runbooks/ai/agents/m365-tools-worker.md`
- `reporting-analyst-explorer`
  Doc: `docs/runbooks/ai/agents/reporting-analyst-explorer.md`

## Validation scenarios

- `altlassian-release-cutover`: normal feature release with blue/green verification
- `altlassian-incident-triage`: March 30, 2026 blue/green DuckDB lock contention outage
- `altlassian-jira-hotfix`: OIT-19526 component and admin-permission failure
- `altlassian-m365-tools`: mailbox rules permission failure plus delegate-access feature additions
- `altlassian-closeout`: memory and docs update followed by redeploy summary
- `altlassian-sla-reporting-review`: SLA accuracy or summary-format investigation

## Repo notes

- These skills are versioned in the repo so the team can review and update them together.
- Invoke them by repo path, or symlink the repo-local skill directories into `${CODEX_HOME:-~/.codex}/skills` if you want auto-discovery in a local Codex setup without breaking the repo-relative doc references.
- Keep the human docs canonical. Update the paired skill when a workflow changes enough that Codex behavior should change too.
