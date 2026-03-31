# Altlassian M365 Tools

Use this workflow for Graph and Exchange-backed features on the shared Tools page, especially mailbox rules, delegate access, Emailgistics helper automation, permission translation, and runtime dependency work.

## Trigger conditions

- A new Microsoft 365 tool needs to be added to `it-app` or `azure`.
- A mailbox-rules or delegate-access tool is failing.
- The Emailgistics helper needs to grant mailbox access or run the shared-mailbox sync path.
- The Emailgistics `Sync Now` action needs to rerun only `syncUsers.ps1` for a shared mailbox.
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
- When a Tools action performs write operations, gate it explicitly if it is admin-only instead of assuming the whole Tools surface is admin-only.
- When an Exchange-backed scan can run for tens of seconds or minutes, prefer a durable server-side job plus per-user history over a page-local spinner so navigation does not lose progress.
- When an Exchange-backed scan is durable and long-running, support explicit user cancellation when the backend dependency can be interrupted safely instead of forcing people to wait for timeout.
- When durable job history accumulates, prefer explicit `Clear finished` actions that remove completed, failed, or cancelled history without deleting queued or running jobs.
- Verify runtime dependencies when touching Exchange-backed features so deploys do not succeed with a broken backend image.
- If a helper chains Exchange permission changes with a downstream Emailgistics or external sync, preflight the downstream dependency before changing mailbox permissions so you do not leave partial state behind on failure.
- Keep the sync-only Emailgistics action truly sync-only. It should reuse the targeted `syncUsers.ps1` path without silently reintroducing mailbox permission or group-membership changes.

## Invariants and gotchas

- Microsoft Graph mailbox rule access depends on the right application permissions and admin consent.
- Exchange-backed delegate access requires a working Exchange runtime path, not only Graph.
- The Emailgistics helper depends on extra runtime config beyond the shared Entra app: `EMAILGISTICS_TOKEN_VALID_URL`, `EMAILGISTICS_USER_SYNC_URL`, and `EMAILGISTICS_AUTH_TOKEN`.
- The Emailgistics `Sync Now` action should accept only a shared mailbox and should still return a readable result payload even though there is no resolved user context.
- `scripts/syncUsers/customerData.json` is local sensitive material and must stay out of git and out of the backend image. Prefer environment variables for runtime Emailgistics settings.
- Org-wide delegate scans are not instant. Expect roughly 20 to 90 seconds in normal cases and 5 to 10 minutes in larger tenants, so UX copy and polling should set that expectation.
- Delegate scan cancellation has to reach the server-side job and the live Exchange call. Avoid UI-only cancel states that leave the background work running.
- If you add a clear-history action, keep its scope obvious. Shared job cards should not clear running work, and per-user job cards should only clear that user's finished history unless product requirements intentionally say otherwise.
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
- Update `backend/.env.example` when a Tools feature introduces new required runtime settings.
- Mention any external permission dependency that still needs tenant-admin action.

## Validation scenario

- Dry-run against the mailbox rules permission failure and the delegate-access feature additions.
