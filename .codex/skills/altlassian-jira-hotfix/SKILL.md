---
name: altlassian-jira-hotfix
description: Jira-integrated hotfix workflow for ticket edit failures, component and application issues, Jira permission mismatches, and connected-vs-fallback identity bugs. Use when a ticket flow breaks in the backend write path or ticket workbench UI and needs a focused fix with regression coverage.
---

# Altlassian Jira Hotfix

If you are using this skill from the repo, read `../../../docs/runbooks/ai/skills/altlassian-jira-hotfix.md`, `../../../CLAUDE.md`, and `../../../docs/runbooks/jira-followup-and-atlassian-oauth.md` first. If those files are not available from your current skill location, use this file as the operating guide.

## Workflow

1. Reproduce the failing ticket flow and capture the exact user-facing error.
2. Inspect whether the write path uses a connected Jira identity or the fallback shared account.
3. Prefer Jira-supported ids and editable metadata over cached display-name guesses.
4. Update backend and frontend together when the write contract or error handling changes.
5. Add focused regression tests for the exact failure path.

## Guardrails

- Keep connected OAuth behavior and fallback shared-account behavior explicit.
- Do not hide Jira policy constraints behind vague error messages.
- Avoid broad permission changes unless the user explicitly asks for them.
- Keep OasisDev and primary behavior aligned unless the bug is truly scope-specific.

## Verification

- Run focused backend tests for the route and Jira client behavior.
- Run focused frontend tests when the ticket drawer or API helpers change.
- If released, verify the live host health and the repaired user flow.
