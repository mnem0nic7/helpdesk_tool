---
name: altlassian-closeout
description: Closeout workflow for Altlassian fixes and features. Use when the user asks to update memory and documentation, commit and push changes, redeploy, or produce a release-quality summary with exact verification and health details.
---

# Altlassian Closeout

If you are using this skill from the repo, read `../../../docs/runbooks/ai/skills/altlassian-closeout.md`, `../../../CLAUDE.md`, and `../../../README.md` first. If those files are not available from your current skill location, use this file as the operating guide.

## Workflow

1. Inspect the final diff and confirm no unrelated changes are mixed in.
2. Update durable repo memory and the nearest operator-facing docs for any recurring workflow change.
3. Run the focused verification set and record exactly what was and was not run.
4. Commit, push, and release only if the task calls for those actions.
5. End with health status, runtime color, worktree cleanliness, and a concise outcome-first summary.

## Guardrails

- Do not claim tests, deploys, or live checks that did not happen.
- Include exact commit hashes and runtime colors when summarizing a release.
- Keep `CLAUDE.md` focused on durable working memory.
- Prefer updating the closest existing doc over creating duplicate notes.

## Verification

- Run focused tests or builds for touched areas.
- Check `git status --short` after commit and deploy work.
- If deployed, verify public health for affected hosts.
