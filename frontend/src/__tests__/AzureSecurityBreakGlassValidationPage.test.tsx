import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureSecurityBreakGlassValidationPage from "../pages/AzureSecurityBreakGlassValidationPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureSecurityBreakGlassValidation: vi.fn(),
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
        key: "matched_accounts",
        label: "Matched accounts",
        value: 2,
        detail: "Two accounts matched the naming rules.",
        tone: "sky",
      },
      {
        key: "validation_due",
        label: "Validation due",
        value: 1,
        detail: "One account still needs review.",
        tone: "amber",
      },
    ],
    accounts: [
      {
        user_id: "user-1",
        display_name: "Emergency Admin",
        principal_name: "emergency-admin@example.com",
        enabled: true,
        user_type: "Member",
        account_class: "person_cloud",
        matched_terms: ["Emergency naming", "Admin naming"],
        has_privileged_access: true,
        privileged_assignment_count: 1,
        last_successful_utc: "2026-04-01T03:00:00Z",
        days_since_last_successful: 1,
        last_password_change: "2026-03-01T00:00:00Z",
        days_since_password_change: 32,
        is_licensed: false,
        license_count: 0,
        on_prem_sync: false,
        status: "healthy",
        flags: ["Account currently holds 1 privileged Azure RBAC assignment."],
      },
      {
        user_id: "user-2",
        display_name: "Break Glass Backup",
        principal_name: "break-glass-backup@example.com",
        enabled: true,
        user_type: "Member",
        account_class: "person_cloud",
        matched_terms: ["Break-glass naming"],
        has_privileged_access: false,
        privileged_assignment_count: 0,
        last_successful_utc: "",
        days_since_last_successful: null,
        last_password_change: "2025-01-01T00:00:00Z",
        days_since_password_change: 450,
        is_licensed: true,
        license_count: 1,
        on_prem_sync: false,
        status: "critical",
        flags: [
          "No successful sign-in is recorded for this account in the cached directory dataset.",
          "Cloud-managed password has not changed in over a year.",
        ],
      },
    ],
    warnings: ["MFA registration posture is not cached in this workspace yet."],
    scope_notes: ["This lane reuses the same break-glass naming heuristics as the Privileged Access Review lane."],
  };
}

describe("AzureSecurityBreakGlassValidationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureSecurityBreakGlassValidation.mockResolvedValue(buildResponse());
  });

  it("renders the break-glass validation lane", async () => {
    render(<AzureSecurityBreakGlassValidationPage />);

    expect(await screen.findByText("Break-glass Account Validation")).toBeInTheDocument();
    expect(screen.getByText("Validation queue")).toBeInTheDocument();
    expect(screen.getByText(/MFA registration posture is not cached/i)).toBeInTheDocument();
    expect(screen.getAllByText("Emergency Admin").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Break Glass Backup").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Open Access Review" })).toHaveAttribute("href", "/security/access-review");
  });

  it("filters the validation queue by search and privileged status", async () => {
    render(<AzureSecurityBreakGlassValidationPage />);

    expect(await screen.findByText("Validation queue")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Search names, UPNs, matched terms, or flags..."), {
      target: { value: "Emergency" },
    });
    fireEvent.change(screen.getByDisplayValue("All candidates"), {
      target: { value: "privileged" },
    });

    expect(screen.getAllByText("Emergency Admin").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("Break Glass Backup")).toHaveLength(0);
  });
});
