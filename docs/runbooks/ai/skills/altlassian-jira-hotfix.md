# Altlassian Jira Hotfix

Use this workflow for Jira-integrated ticket bugs, component/application edit failures, permission mismatches, and fallback-vs-connected identity issues.

## Trigger conditions

- Ticket editing fails in the drawer or bulk action flow.
- Jira returns component, application, permission, or validation errors.
- The user needs a fast Jira-integrated hotfix with targeted regression coverage.

## Required first reads

- `CLAUDE.md`
- `backend/routes_tickets.py`
- `backend/jira_client.py`
- `backend/jira_write_service.py`
- `frontend/src/components/TicketWorkbenchDrawer.tsx`
- `docs/runbooks/jira-followup-and-atlassian-oauth.md`

## Commands and checks to run first

- Reproduce the failing workflow and capture the exact user-facing error.
- Inspect the backend write path and whether the request uses a connected Jira identity or the fallback account.
- Check Jira `editmeta` or other project metadata before assuming a frontend mapping problem.
- Run the smallest backend and frontend regression tests that cover the touched path.

## Workflow

- Confirm the failing field, route, and identity mode before making changes.
- Prefer Jira-supported ids and editable metadata over cached display-name guesses.
- Keep error messages user-readable and specific enough to explain whether the problem is app logic or Jira policy.
- Update backend and frontend together when the write contract or validation behavior changes.
- Add focused regression tests for the exact failure path.

## Invariants and gotchas

- Connected Atlassian OAuth behavior and fallback shared-account behavior are not interchangeable.
- Existing Jira project permissions may be the real constraint; do not hide them with vague error text.
- Keep OasisDev and primary host behavior aligned unless the issue is explicitly scope-specific.
- Do not broaden Jira permissions in-app unless the user explicitly asks for that policy change.

## Required verification

- Focused backend tests for the route and Jira client behavior.
- Focused frontend tests for the drawer, API helper, or error banner when touched.
- Live health verification if the fix is released.

## Closeout checklist

- Note the failing ticket or scenario in the summary.
- Record whether the fix changed identity behavior, Jira validation handling, or UI error handling.
- Update `CLAUDE.md` when the fix changes a recurring Jira workflow.

## Validation scenario

- Dry-run against the OIT-19526 component and admin-permission failure.
