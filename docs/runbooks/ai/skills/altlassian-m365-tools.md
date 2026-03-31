# Altlassian M365 Tools

Use this workflow for Graph and Exchange-backed features on the shared Tools page, especially mailbox rules, delegate access, permission translation, and runtime dependency work.

## Trigger conditions

- A new Microsoft 365 tool needs to be added to `it-app` or `azure`.
- A mailbox-rules or delegate-access tool is failing.
- The work touches Graph permissions, Exchange Online access, or Tools page UX.

## Required first reads

- `CLAUDE.md`
- `backend/routes_tools.py`
- `backend/user_admin_providers.py`
- `backend/exchange_online_client.py`
- `frontend/src/pages/ToolsPage.tsx`
- `README.md`

## Commands and checks to run first

- Confirm the host scope. Tools are shared on `it-app` and `azure`, not `oasisdev`.
- Identify whether the failure is app logic, Graph permissioning, Exchange permissioning, or runtime packaging.
- Inspect the provider response and translate raw dependency errors into actionable UI errors.
- Run focused backend route and provider tests, then frontend Tools page tests if the UI changes.

## Workflow

- Keep the backend provider contract, route response, and frontend card behavior aligned.
- Prefer read-only behavior unless the requested tool explicitly needs write access.
- Preserve the current signed-in access model for Tools on primary and Azure hosts.
- Keep tool actions on the left and logs or history on the right unless a new design decision supersedes it.
- When an Exchange-backed scan can run for tens of seconds or minutes, prefer a durable server-side job plus per-user history over a page-local spinner so navigation does not lose progress.
- Verify runtime dependencies when touching Exchange-backed features so deploys do not succeed with a broken backend image.

## Invariants and gotchas

- Microsoft Graph mailbox rule access depends on the right application permissions and admin consent.
- Exchange-backed delegate access requires a working Exchange runtime path, not only Graph.
- Org-wide delegate scans are not instant. Expect roughly 20 to 90 seconds in normal cases and 5 to 10 minutes in larger tenants, so UX copy and polling should set that expectation.
- Friendly user-facing errors matter because raw Graph and Exchange responses are not operator-friendly.
- Do not accidentally expose Tools routes on `oasisdev`.

## Required verification

- Focused backend tests for providers and routes.
- Focused frontend tests for the Tools page or API types when touched.
- Frontend lint and build when the page layout or components change.
- Host health checks on `it-app` and `azure` after release.

## Closeout checklist

- State which dependency surface changed: Graph, Exchange, runtime image, or UI only.
- Update `README.md` and `CLAUDE.md` when Tools capabilities or access rules change.
- Mention any external permission dependency that still needs tenant-admin action.

## Validation scenario

- Dry-run against the mailbox rules permission failure and the delegate-access feature additions.
