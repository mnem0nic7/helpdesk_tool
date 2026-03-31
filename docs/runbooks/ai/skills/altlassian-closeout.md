# Altlassian Closeout

Use this workflow after substantial fixes, feature additions, or hotfixes when the user wants the change wrapped up cleanly with docs, verification, release, and status reporting.

## Trigger conditions

- The user asks to update memory and documentation.
- The user asks to commit, push, redeploy, or summarize the release.
- A change is complete and needs a release-quality closeout.

## Required first reads

- `git status --short`
- `CLAUDE.md`
- `README.md`
- Any touched runbook under `docs/runbooks/`

## Commands and checks to run first

- Review the final diff and confirm no unrelated changes are mixed in.
- Run the focused tests, builds, or lint checks that support the final summary.
- Confirm whether a deploy is required and which hosts need post-release validation.

## Workflow

- Update repo memory and docs for any recurring operator or product change.
- Run the focused verification set and record exactly what was or was not run.
- Create an intentional commit message, push the branch, and release only if the task calls for it.
- Confirm live health, active runtime color, and clean worktree state after deploy work.
- Summarize the change in outcome-first language with exact commit and verification details.

## Invariants and gotchas

- Do not claim tests, deploys, or live smoke checks that did not happen.
- Include exact commit hashes and runtime colors when you mention a release.
- Keep `CLAUDE.md` focused on durable working memory, not one-off chatter.
- Update the closest existing doc instead of creating redundant notes.

## Required verification

- Focused tests or builds for touched areas.
- Clean `git status --short` after commit and release work.
- Public health checks for affected hosts when a deploy occurred.

## Closeout checklist

- Mention docs and memory updates explicitly.
- Mention commit, push, deploy, and health results explicitly.
- Call out any live check you could not perform.

## Validation scenario

- Dry-run against a memory and docs update followed by commit, push, redeploy, and health confirmation.
