import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureSecurityConditionalAccessTrackerPage from "../pages/AzureSecurityConditionalAccessTrackerPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureSecurityConditionalAccessTracker: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

function buildResponse() {
  return {
    generated_at: "2026-04-03T03:00:00Z",
    conditional_access_last_refresh: "2026-04-03T02:45:00Z",
    access_available: true,
    access_message: "Conditional Access policy drift review is available.",
    metrics: [
      {
        key: "tracked_policies",
        label: "Tracked policies",
        value: 2,
        detail: "Conditional Access policies currently cached for this tenant.",
        tone: "sky",
      },
      {
        key: "high_impact_changes",
        label: "High-impact changes",
        value: 1,
        detail: "Recent changes that touched broad-scope policies or core enforcement controls.",
        tone: "violet",
      },
    ],
    policies: [
      {
        policy_id: "policy-1",
        display_name: "Require MFA for admins",
        state: "enabled",
        created_date_time: "2026-01-01T00:00:00Z",
        modified_date_time: "2026-04-03T01:00:00Z",
        user_scope_summary: "2 role target(s) - 1 exception(s)",
        application_scope_summary: "All cloud apps",
        grant_controls: ["Mfa"],
        session_controls: [],
        impact_level: "warning",
        risk_tags: ["role_targeted", "exception_surface", "grant_controls"],
      },
      {
        policy_id: "policy-2",
        display_name: "Require compliant device for all users",
        state: "enabled",
        created_date_time: "2026-02-01T00:00:00Z",
        modified_date_time: "2026-04-02T20:00:00Z",
        user_scope_summary: "All users",
        application_scope_summary: "All cloud apps",
        grant_controls: [],
        session_controls: ["Application Enforced Restrictions"],
        impact_level: "critical",
        risk_tags: ["all_users_scope", "no_grant_controls", "session_controls"],
      },
    ],
    changes: [
      {
        event_id: "event-1",
        activity_date_time: "2026-04-03T02:15:00Z",
        activity_display_name: "Update conditional access policy",
        result: "success",
        initiated_by_display_name: "Ada Lovelace",
        initiated_by_principal_name: "ada@example.com",
        initiated_by_type: "user",
        target_policy_id: "policy-2",
        target_policy_name: "Require compliant device for all users",
        impact_level: "critical",
        change_summary: "Update conditional access policy for Require compliant device for all users by Ada Lovelace",
        modified_properties: ["grantControls", "state"],
        flags: ["Change touched policy scope or enforcement controls."],
      },
      {
        event_id: "event-2",
        activity_date_time: "2026-04-02T18:00:00Z",
        activity_display_name: "Add conditional access policy",
        result: "success",
        initiated_by_display_name: "Automation App",
        initiated_by_principal_name: "0000-1111",
        initiated_by_type: "app",
        target_policy_id: "policy-1",
        target_policy_name: "Require MFA for admins",
        impact_level: "warning",
        change_summary: "Add conditional access policy for Require MFA for admins by Automation App",
        modified_properties: ["conditions"],
        flags: ["Change was initiated by an application or service principal."],
      },
    ],
    warnings: ["Conditional Access cache data is older than 4 hours, so recent policy drift may be missing."],
    scope_notes: ["This lane tracks cached Microsoft Entra Conditional Access policies and recent directory audit events tagged to policy activity."],
  };
}

function buildLargeResponse(policyCount = 60, changeCount = 60) {
  const response = buildResponse();
  return {
    ...response,
    policies: Array.from({ length: policyCount }, (_, index) => ({
      ...response.policies[0],
      policy_id: `policy-${index + 1}`,
      display_name: `Bulk Policy ${index + 1}`,
    })),
    changes: Array.from({ length: changeCount }, (_, index) => ({
      ...response.changes[0],
      event_id: `event-${index + 1}`,
      target_policy_name: `Bulk Policy ${index + 1}`,
      change_summary: `Change for Bulk Policy ${index + 1}`,
    })),
  };
}

describe("AzureSecurityConditionalAccessTrackerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureSecurityConditionalAccessTracker.mockResolvedValue(buildResponse());
  });

  it("renders the conditional access tracker lane with policy and change sections", async () => {
    render(<AzureSecurityConditionalAccessTrackerPage />);

    expect(await screen.findByRole("heading", { name: "Conditional Access Change Tracker" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Policy watchlist" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recent policy changes" })).toBeInTheDocument();
    expect(screen.getByText("Conditional Access cache data is older than 4 hours, so recent policy drift may be missing.")).toBeInTheDocument();
    expect(screen.getAllByText("Require compliant device for all users").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Open Security Copilot" })).toHaveAttribute("href", "/security/copilot");
  });

  it("filters policies and changes with the shared search box", async () => {
    render(<AzureSecurityConditionalAccessTrackerPage />);

    expect(await screen.findByRole("heading", { name: "Policy watchlist" })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Search policy names, tags, actors, or changed properties..."), {
      target: { value: "admins" },
    });

    expect(screen.getAllByText("Require MFA for admins").length).toBeGreaterThan(0);
    expect(screen.queryByText("Require compliant device for all users")).not.toBeInTheDocument();
  });

  it("pages large policy watchlists and change feeds", async () => {
    mockApi.getAzureSecurityConditionalAccessTracker.mockResolvedValue(buildLargeResponse());

    render(<AzureSecurityConditionalAccessTrackerPage />);

    expect(await screen.findByRole("heading", { name: "Policy watchlist" })).toBeInTheDocument();
    expect(screen.getByText("Showing 1-50 of 60 matching policy record(s)")).toBeInTheDocument();
    expect(screen.getAllByText("Bulk Policy 1").length).toBeGreaterThan(0);
    expect(screen.queryByText("Bulk Policy 60")).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Next" })[0]);

    expect(await screen.findByText("Showing 51-60 of 60 matching policy record(s)")).toBeInTheDocument();
    expect(screen.getAllByText("Bulk Policy 60").length).toBeGreaterThan(0);
  });
});
