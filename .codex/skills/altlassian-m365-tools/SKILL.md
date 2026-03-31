---
name: altlassian-m365-tools
description: Microsoft 365 Tools workflow for Graph and Exchange-backed features in the shared Tools page. Use when adding or debugging mailbox rules, delegate access, app-registration permission handling, Exchange runtime support, or user-facing Tools error translation on the primary or Azure hosts.
---

# Altlassian M365 Tools

If you are using this skill from the repo, read `../../../docs/runbooks/ai/skills/altlassian-m365-tools.md` and `../../../CLAUDE.md` first. If those files are not available from your current skill location, use this file as the operating guide.

## Workflow

1. Confirm the target host and remember that Tools belongs on `it-app` and `azure`, not `oasisdev`.
2. Identify whether the problem is app logic, Graph permissions, Exchange permissions, or runtime packaging.
3. Keep the provider contract, route response, and Tools page card behavior aligned.
4. Translate raw Graph and Exchange failures into user-readable guidance.
5. Verify backend, frontend, and runtime assumptions before closing the task.

## Guardrails

- Preserve the current signed-in access model for Tools on supported hosts.
- Prefer read-only behavior unless the requested tool explicitly needs write access.
- Keep tool cards on the left and logs or history on the right unless the product direction changes.
- Do not accidentally expose Tools routes on `oasisdev`.

## Verification

- Run focused backend route and provider tests.
- Run focused frontend Tools page tests when the UI changes.
- Run frontend lint and build when layout or component behavior changes.
- If released, verify public health on `it-app` and `azure`.
