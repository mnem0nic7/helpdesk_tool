# OasisDev Tools Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `/tools` route available on the OasisDev scope showing only the password expiry lookup section.

**Architecture:** Three targeted frontend edits — remove the `primaryOnly` gate from the Tools nav item, register the `/tools` route for `oasisdev` in the router, and gate all non-password-expiry sections in `ToolsPage` behind `!isOasisDev`. No backend changes needed.

**Tech Stack:** React 19, React Router 7, React Query 5, Tailwind CSS 4, Vitest + Testing Library

---

## File Map

| File | Change |
|---|---|
| `frontend/src/__tests__/LayoutToolsNav.test.tsx` | Update "hides Tools on oasisdev" test to assert Tools IS shown |
| `frontend/src/__tests__/ToolsPage.oasisdev.test.tsx` | New test file: assert only password expiry renders on oasisdev |
| `frontend/src/components/Layout.tsx` | Remove `primaryOnly: true` from Tools nav item |
| `frontend/src/App.tsx` | Register `/tools` route for `oasisdev` scope |
| `frontend/src/pages/ToolsPage.tsx` | Gate non-password-expiry sections behind `!isOasisDev` |

---

### Task 1: Write failing tests

**Files:**
- Modify: `frontend/src/__tests__/LayoutToolsNav.test.tsx:162-166`
- Create: `frontend/src/__tests__/ToolsPage.oasisdev.test.tsx`

- [ ] **Step 1: Update the existing LayoutToolsNav test that asserts Tools is hidden on oasisdev**

Open `frontend/src/__tests__/LayoutToolsNav.test.tsx`. Find the test at around line 162:

```ts
it("hides Tools on oasisdev", async () => {
  renderLayoutAt("/", "oasisdev");
  await screen.findByText("Page content");
  expect(screen.queryByRole("link", { name: /Tools/ })).not.toBeInTheDocument();
});
```

Change it to assert the opposite (Tools IS visible on oasisdev after our change):

```ts
it("shows Tools on oasisdev", async () => {
  renderLayoutAt("/", "oasisdev");
  await screen.findByText("Page content");
  expect(await screen.findByRole("link", { name: /Tools/ })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the updated LayoutToolsNav test to confirm it fails**

```bash
cd /workspace/atlassian/frontend && npm run test:run -- LayoutToolsNav
```

Expected: FAIL — "Unable to find role=link with name /Tools/" (Tools is still hidden on oasisdev because we haven't changed the code yet).

- [ ] **Step 3: Create the new ToolsPage.oasisdev.test.tsx file**

Create `frontend/src/__tests__/ToolsPage.oasisdev.test.tsx` with this content:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import ToolsPage from "../pages/ToolsPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getMe: vi.fn(),
    searchOneDriveCopyUsers: vi.fn(),
    listOneDriveCopyJobs: vi.fn(),
    clearFinishedOneDriveCopyJobs: vi.fn(),
    getOneDriveCopyJob: vi.fn(),
    createOneDriveCopyJob: vi.fn(),
    listLoginAudit: vi.fn(),
    listMailboxRules: vi.fn(),
    listMailboxDelegates: vi.fn(),
    listDelegateMailboxes: vi.fn(),
    listDelegateMailboxJobs: vi.fn(),
    clearFinishedDelegateMailboxJobs: vi.fn(),
    getDelegateMailboxJob: vi.fn(),
    createDelegateMailboxJob: vi.fn(),
    cancelDelegateMailboxJob: vi.fn(),
    runEmailgisticsHelper: vi.fn(),
    lookupPasswordExpiry: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

vi.mock("../lib/siteContext.ts", () => ({
  getSiteBranding: () => ({
    scope: "oasisdev",
    appName: "OIT Helpdesk",
    dashboardName: "OIT Dashboard",
    alertPrefix: "OIT",
  }),
}));

describe("ToolsPage (oasisdev scope)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/tools");
    mockApi.getMe.mockResolvedValue({
      email: "gallison@movedocs.com",
      name: "Gallison",
      is_admin: false,
      can_manage_users: false,
      can_access_tools: true,
    });
    mockApi.listOneDriveCopyJobs.mockResolvedValue([]);
    mockApi.listLoginAudit.mockResolvedValue([]);
    mockApi.listDelegateMailboxJobs.mockResolvedValue([]);
    mockApi.searchOneDriveCopyUsers.mockResolvedValue([]);
  });

  it("shows the password expiry lookup section", async () => {
    render(<ToolsPage />);
    expect(
      await screen.findByText("Look up when a user's password expires")
    ).toBeInTheDocument();
  });

  it("hides the OneDrive Copy section", async () => {
    render(<ToolsPage />);
    await screen.findByText("Look up when a user's password expires");
    expect(
      screen.queryByText("Copy a full OneDrive to another user")
    ).not.toBeInTheDocument();
  });

  it("hides the List Inbox Rules section", async () => {
    render(<ToolsPage />);
    await screen.findByText("Look up when a user's password expires");
    expect(
      screen.queryByText("List Inbox rules for a provided mailbox")
    ).not.toBeInTheDocument();
  });

  it("hides the mailbox delegate sections", async () => {
    render(<ToolsPage />);
    await screen.findByText("Look up when a user's password expires");
    expect(
      screen.queryByText("List mailbox delegate access for a mailbox")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Find mailboxes where a user has delegate access")
    ).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run the new test to confirm it fails**

```bash
cd /workspace/atlassian/frontend && npm run test:run -- ToolsPage.oasisdev
```

Expected: FAIL — tests for "shows the password expiry lookup section" will fail because the OasisDev scope currently has no `/tools` route. Tests for the hidden sections may also fail since the page isn't loaded at all yet.

---

### Task 2: Implement the three changes

**Files:**
- Modify: `frontend/src/components/Layout.tsx:30`
- Modify: `frontend/src/App.tsx:131`
- Modify: `frontend/src/pages/ToolsPage.tsx` (multiple locations)

- [ ] **Step 1: Remove `primaryOnly: true` from the Tools nav item in Layout.tsx**

In `frontend/src/components/Layout.tsx`, find line 30:

```ts
  { to: "/tools", label: "Tools", icon: "⚒", primaryOnly: true },
```

Change to:

```ts
  { to: "/tools", label: "Tools", icon: "⚒" },
```

- [ ] **Step 2: Register the `/tools` route for oasisdev in App.tsx**

In `frontend/src/App.tsx`, find line 131:

```tsx
                {branding.scope === "primary" ? <Route path="tools" element={<ToolsPage />} /> : null}
```

Change to:

```tsx
                {(branding.scope === "primary" || branding.scope === "oasisdev") ? <Route path="tools" element={<ToolsPage />} /> : null}
```

- [ ] **Step 3: Add the `isOasisDev` variable in ToolsPage.tsx**

In `frontend/src/pages/ToolsPage.tsx`, find this line (around line 1218):

```ts
  const branding = getSiteBranding();
```

Add the `isOasisDev` constant immediately after it:

```ts
  const branding = getSiteBranding();
  const isOasisDev = branding.scope === "oasisdev";
```

- [ ] **Step 4: Gate the page header section**

In `frontend/src/pages/ToolsPage.tsx`, find (around line 1867):

```tsx
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Tools</p>
            <h1 className="mt-1 text-3xl font-bold text-slate-900">{branding.scope === "azure" ? "Azure Tools" : "Helpdesk Tools"}</h1>
```

Wrap the entire header `<section>` block (lines 1867–1877) with `{!isOasisDev && (...)}`:

```tsx
      {!isOasisDev && (
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Tools</p>
            <h1 className="mt-1 text-3xl font-bold text-slate-900">{branding.scope === "azure" ? "Azure Tools" : "Helpdesk Tools"}</h1>
            <p className="mt-2 max-w-3xl text-sm text-slate-600">
              Shared tools for Microsoft 365 and Azure tasks. The OneDrive Copy tool mirrors the existing Graph-based handoff script, and the mailbox cards use the shared app registration to inspect Inbox rules plus Exchange delegate access for Send on behalf, Send As, and Full Access.
            </p>
          </div>
        </div>
      </section>
      )}
```

- [ ] **Step 5: Gate the OneDrive Copy section**

In `frontend/src/pages/ToolsPage.tsx`, the OneDrive Copy section starts at the first `<section>` inside the left column div (around line 1881). It ends at its closing `</section>` tag around line 1992.

Find the opening tag:

```tsx
          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">OneDrive Copy</div>
```

Wrap the entire OneDrive Copy `<section>...</section>` block with `{!isOasisDev && (...)}`:

```tsx
          {!isOasisDev && (
          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">OneDrive Copy</div>
                {/* ... rest of section unchanged ... */}
              </div>
            </div>
          </section>
          )}
```

The closing looks like:
```tsx
          </section>
```
becomes:
```tsx
          </section>
          )}
```

- [ ] **Step 6: Gate the two mailbox delegate sections**

Both delegate sections follow the same pattern. Find the first one:

```tsx
          <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mailbox Delegation</div>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">List mailbox delegate access for a mailbox</h2>
```

Wrap both delegate `<section>` blocks (lines ~1994–2038 and ~2039–~2280) individually with `{!isOasisDev && (...)}`. They are the two consecutive sections with the `Mailbox Delegation` label. Each wrapping is:

```tsx
          {!isOasisDev && (
          <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            ...
          </section>
          )}
```

- [ ] **Step 7: Gate the Emailgistics Helper conditional**

Find (around line 2281):

```tsx
          {canUseEmailgisticsHelper ? (
```

Change to:

```tsx
          {!isOasisDev && canUseEmailgisticsHelper ? (
```

- [ ] **Step 8: Gate the Inbox Rules section**

Find (around line 2347):

```tsx
          <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mailbox Rules</div>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">List Inbox rules for a provided mailbox</h2>
```

Wrap this section block with `{!isOasisDev && (...)}`:

```tsx
          {!isOasisDev && (
          <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mailbox Rules</div>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">List Inbox rules for a provided mailbox</h2>
                {/* ... rest of section unchanged ... */}
              </div>
            </div>
          </section>
          )}
```

- [ ] **Step 9: Gate the entire right column**

Find the right column div (around line 2442) — it starts immediately after the left column's closing `</div>` at line 2440:

```tsx
        <div className="space-y-6">
          {activeJobQuery.data ? (
            <OneDriveCopyJobDetail job={activeJobQuery.data} />
```

Wrap the entire right column `<div className="space-y-6">...</div>` block (lines ~2442–2686) with `{!isOasisDev && (...)}`:

```tsx
        {!isOasisDev && (
        <div className="space-y-6">
          {activeJobQuery.data ? (
            <OneDriveCopyJobDetail job={activeJobQuery.data} />
          ) : (
            ...
          )}
          ...
          <LoginAuditPanel events={loginAuditQuery.data ?? []} />
        </div>
        )}
```

- [ ] **Step 10: Run the failing tests to confirm they now pass**

```bash
cd /workspace/atlassian/frontend && npm run test:run -- LayoutToolsNav
```

Expected: All tests in LayoutToolsNav PASS (including the updated "shows Tools on oasisdev" test).

```bash
cd /workspace/atlassian/frontend && npm run test:run -- ToolsPage.oasisdev
```

Expected: All 4 tests PASS.

- [ ] **Step 11: Run the full frontend test suite to check for regressions**

```bash
cd /workspace/atlassian/frontend && npm run test:run
```

Expected: No new failures. Pre-existing failures (if any) remain unchanged.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/__tests__/LayoutToolsNav.test.tsx \
        frontend/src/__tests__/ToolsPage.oasisdev.test.tsx \
        frontend/src/components/Layout.tsx \
        frontend/src/App.tsx \
        frontend/src/pages/ToolsPage.tsx
git commit -m "feat: add Tools page to OasisDev scope with password expiry lookup only"
```
