# OasisDev Tools Page — Design Spec

**Date:** 2026-05-13
**Status:** Approved

## Summary

Add a Tools page to the OasisDev site scope that exposes only the password expiry lookup tool. No new files or backend changes are needed — three targeted edits to existing frontend files make the `/tools` route available on OasisDev and restrict its content to the one relevant section.

---

## Architecture

No new files. Changes are additions or edits to three existing frontend modules:

| Module | Change |
|---|---|
| `frontend/src/components/Layout.tsx` | Remove `primaryOnly: true` from the Tools nav item |
| `frontend/src/App.tsx` | Register the `/tools` route for `oasisdev` scope |
| `frontend/src/pages/ToolsPage.tsx` | Render only the password expiry section when scope is `oasisdev` |

---

## Changes

### 1. `frontend/src/components/Layout.tsx`

The `helpdeskNavItems` array contains a Tools entry gated with `primaryOnly: true`:

```ts
{ to: "/tools", label: "Tools", icon: "⚒", primaryOnly: true },
```

Remove `primaryOnly: true`. The nav filter `(!item.primaryOnly || branding.scope === "primary")` will then pass the item for both `primary` and `oasisdev` scopes.

### 2. `frontend/src/App.tsx`

The Tools route is currently registered only when `branding.scope === "primary"`:

```tsx
{branding.scope === "primary" ? <Route path="tools" element={<ToolsPage />} /> : null}
```

Change to include `oasisdev`:

```tsx
{(branding.scope === "primary" || branding.scope === "oasisdev") ? <Route path="tools" element={<ToolsPage />} /> : null}
```

### 3. `frontend/src/pages/ToolsPage.tsx`

At the top of the page body, read the current scope:

```ts
const { scope } = getSiteBranding();
const isOasisDev = scope === "oasisdev";
```

Wrap every section other than the password expiry lookup in `{!isOasisDev && (...)}`. The password expiry section renders unconditionally (it already has no admin gate and is available to all signed-in users).

---

## Sections hidden on OasisDev

- OneDrive copy job
- Login audit lookup
- List Inbox rules
- Mailbox delegate lookups (Send on Behalf, Send As, Full Access)
- Emailgistics Helper (admin-only)

---

## No backend changes

`GET /api/tools/password-expiry` is protected by `_require_tools_session`, which is satisfied by any signed-in session on either scope. No route-level scope gating is needed.

---

## Testing

Add a Vitest test in `frontend/src/__tests__/ToolsPage.oasisdev.test.tsx`:

- Force `document.documentElement.dataset.siteHostname` to the OasisDev hostname.
- Assert the password expiry section heading renders.
- Assert that sections for OneDrive copy, login audit, inbox rules, and delegate lookups do not render.
