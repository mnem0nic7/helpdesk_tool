import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureSecurityDirectoryRoleReviewPage from "../pages/AzureSecurityDirectoryRoleReviewPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureSecurityDirectoryRoleReview: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

function buildResponse() {
  return {
    generated_at: "2026-04-02T02:00:00Z",
    directory_last_refresh: "2026-04-02T01:56:00Z",
    access_available: true,
    access_message: "Live direct role review is available.",
    metrics: [
      {
        key: "roles_with_members",
        label: "Roles with direct members",
        value: 2,
        detail: "Two roles currently have direct members.",
        tone: "sky",
      },
      {
        key: "flagged_memberships",
        label: "Flagged memberships",
        value: 2,
        detail: "Two direct memberships need review.",
        tone: "amber",
      },
    ],
    roles: [
      {
        role_id: "role-1",
        display_name: "Global Administrator",
        description: "Full tenant access.",
        privilege_level: "critical",
        member_count: 2,
        flagged_member_count: 2,
        flags: ["Membership list was truncated to the first 100 results."],
      },
      {
        role_id: "role-2",
        display_name: "User Administrator",
        description: "Can manage users.",
        privilege_level: "elevated",
        member_count: 1,
        flagged_member_count: 0,
        flags: [],
      },
    ],
    memberships: [
      {
        role_id: "role-1",
        role_name: "Global Administrator",
        role_description: "Full tenant access.",
        privilege_level: "critical",
        principal_id: "user-1",
        principal_type: "User",
        object_type: "user",
        display_name: "Ada Guest",
        principal_name: "ada.guest@example.com",
        enabled: true,
        user_type: "Guest",
        last_successful_utc: "2026-03-01T00:00:00Z",
        assignment_type: "direct",
        status: "critical",
        flags: [
          "Guest user holds a direct Entra directory role.",
          "No successful sign-in is recorded in the last 30 days.",
        ],
      },
      {
        role_id: "role-1",
        role_name: "Global Administrator",
        role_description: "Full tenant access.",
        privilege_level: "critical",
        principal_id: "sp-1",
        principal_type: "ServicePrincipal",
        object_type: "enterprise_app",
        display_name: "Payroll Automator",
        principal_name: "11111111-2222-3333-4444-555555555555",
        enabled: true,
        user_type: "",
        last_successful_utc: "",
        assignment_type: "direct",
        status: "critical",
        flags: ["Service principal holds a direct Entra directory role."],
      },
      {
        role_id: "role-2",
        role_name: "User Administrator",
        role_description: "Can manage users.",
        privilege_level: "elevated",
        principal_id: "group-1",
        principal_type: "Group",
        object_type: "group",
        display_name: "Privileged Operators",
        principal_name: "privileged.operators@example.com",
        enabled: true,
        user_type: "",
        last_successful_utc: "",
        assignment_type: "direct",
        status: "warning",
        flags: ["Group-based direct directory role membership needs separate member review."],
      },
    ],
    warnings: ["Membership list was truncated to the first 100 results."],
    scope_notes: [
      "This lane reviews direct Microsoft Entra directory-role memberships with live Graph membership lookup per role.",
    ],
  };
}

describe("AzureSecurityDirectoryRoleReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureSecurityDirectoryRoleReview.mockResolvedValue(buildResponse());
  });

  it("renders the directory role review lane with source pivots", async () => {
    render(<AzureSecurityDirectoryRoleReviewPage />);

    expect(await screen.findByRole("heading", { name: "Directory Role Membership Review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Role summary" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Direct membership review queue" })).toBeInTheDocument();
    expect(screen.getAllByText(/Membership list was truncated/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Open Identity Review" })).toHaveAttribute("href", "/security/identity-review");
    expect(screen.getAllByRole("link", { name: "Open source record" })[0]).toHaveAttribute("href", "/users?userId=user-1");
  });

  it("filters the review queue by principal type and flagged status", async () => {
    render(<AzureSecurityDirectoryRoleReviewPage />);

    const queueHeading = await screen.findByRole("heading", { name: "Direct membership review queue" });
    const queueSection = queueHeading.closest("section");
    expect(queueSection).not.toBeNull();

    fireEvent.change(screen.getByPlaceholderText("Search roles, principals, or flags..."), {
      target: { value: "Payroll" },
    });
    fireEvent.change(screen.getByDisplayValue("All principals"), {
      target: { value: "service_principal" },
    });
    fireEvent.change(screen.getByDisplayValue("All role levels"), {
      target: { value: "flagged" },
    });

    const scoped = within(queueSection as HTMLElement);
    expect(scoped.getAllByText("Payroll Automator").length).toBeGreaterThan(0);
    expect(scoped.queryByText("Ada Guest")).not.toBeInTheDocument();
    expect(scoped.queryByText("Privileged Operators")).not.toBeInTheDocument();
  });
});
