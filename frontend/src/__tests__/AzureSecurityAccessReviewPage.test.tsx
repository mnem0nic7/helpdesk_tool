import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureSecurityAccessReviewPage from "../pages/AzureSecurityAccessReviewPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureSecurityAccessReview: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

function buildResponse() {
  return {
    generated_at: "2026-04-02T02:00:00Z",
    inventory_last_refresh: "2026-04-02T01:50:00Z",
    directory_last_refresh: "2026-04-02T01:51:00Z",
    metrics: [
      {
        key: "privileged_principals",
        label: "Privileged principals",
        value: 3,
        detail: "Unique principals with privileged Azure RBAC access.",
        tone: "sky",
      },
      {
        key: "critical_assignments",
        label: "Critical assignments",
        value: 2,
        detail: "Critical control-plane access.",
        tone: "rose",
      },
    ],
    flagged_principals: [
      {
        principal_id: "user-1",
        principal_type: "User",
        object_type: "user",
        display_name: "Emergency Admin",
        principal_name: "emergency-admin@example.com",
        enabled: true,
        user_type: "Member",
        last_successful_utc: "2026-04-01T03:00:00Z",
        role_names: ["Owner"],
        assignment_count: 1,
        scope_count: 1,
        highest_privilege: "critical",
        flags: ["Assignment is scoped at the subscription root."],
        subscriptions: ["Prod"],
      },
      {
        principal_id: "sp-1",
        principal_type: "ServicePrincipal",
        object_type: "enterprise_app",
        display_name: "Automation SP",
        principal_name: "11111111-2222-3333-4444-555555555555",
        enabled: true,
        user_type: "",
        last_successful_utc: "",
        role_names: ["Contributor"],
        assignment_count: 1,
        scope_count: 1,
        highest_privilege: "elevated",
        flags: ["Service principal holds privileged Azure RBAC access."],
        subscriptions: ["Prod"],
      },
    ],
    assignments: [
      {
        assignment_id: "assignment-1",
        principal_id: "user-1",
        principal_type: "User",
        object_type: "user",
        display_name: "Emergency Admin",
        principal_name: "emergency-admin@example.com",
        role_definition_id: "owner-role",
        role_name: "Owner",
        privilege_level: "critical",
        scope: "/subscriptions/sub-1",
        subscription_id: "sub-1",
        subscription_name: "Prod",
        enabled: true,
        user_type: "Member",
        last_successful_utc: "2026-04-01T03:00:00Z",
        flags: ["Assignment is scoped at the subscription root."],
      },
      {
        assignment_id: "assignment-2",
        principal_id: "sp-1",
        principal_type: "ServicePrincipal",
        object_type: "enterprise_app",
        display_name: "Automation SP",
        principal_name: "11111111-2222-3333-4444-555555555555",
        role_definition_id: "contributor-role",
        role_name: "Contributor",
        privilege_level: "elevated",
        scope: "/subscriptions/sub-1/resourceGroups/rg-apps",
        subscription_id: "sub-1",
        subscription_name: "Prod",
        enabled: true,
        user_type: "",
        last_successful_utc: "",
        flags: ["Service principal holds privileged Azure RBAC access."],
      },
    ],
    break_glass_candidates: [
      {
        user_id: "user-1",
        display_name: "Emergency Admin",
        principal_name: "emergency-admin@example.com",
        enabled: true,
        last_successful_utc: "2026-04-01T03:00:00Z",
        matched_terms: ["Emergency naming", "Admin naming"],
        privileged_assignment_count: 1,
        has_privileged_access: true,
        flags: ["Account currently holds privileged Azure RBAC access."],
      },
    ],
    warnings: ["Azure RBAC role names could not be refreshed live. Some assignments may show raw role IDs until the next successful lookup."],
    scope_notes: [
      "This v1 review focuses on Azure RBAC role assignments from the cached inventory dataset.",
      "User freshness, guest status, and break-glass heuristics come from the cached directory dataset.",
    ],
  };
}

describe("AzureSecurityAccessReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureSecurityAccessReview.mockResolvedValue(buildResponse());
  });

  it("renders the privileged access review shell", async () => {
    render(<AzureSecurityAccessReviewPage />);

    expect(await screen.findByText("Privileged Access Review")).toBeInTheDocument();
    expect(screen.getByText("Flagged principals")).toBeInTheDocument();
    expect(screen.getByText("Break-glass watchlist")).toBeInTheDocument();
    expect(screen.getByText("Privileged assignment table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Security workspace" })).toHaveAttribute("href", "/security");
    expect(screen.getByRole("link", { name: "Open Security Copilot" })).toHaveAttribute("href", "/security/copilot");
    expect(screen.getByText(/could not be refreshed live/i)).toBeInTheDocument();
    expect(screen.getAllByText("Emergency Admin").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Automation SP").length).toBeGreaterThan(0);
  });

  it("filters the assignment table by search and principal type", async () => {
    render(<AzureSecurityAccessReviewPage />);

    expect(await screen.findByText("Privileged assignment table")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Search principals, roles, scopes, or flags..."), {
      target: { value: "Automation" },
    });
    fireEvent.change(screen.getByDisplayValue("All principals"), {
      target: { value: "service_principal" },
    });

    expect(screen.getAllByText("Automation SP").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("Emergency Admin")).toHaveLength(0);
    expect(screen.getAllByText("Contributor").length).toBeGreaterThan(0);
  });
});
