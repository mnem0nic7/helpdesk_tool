import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureAccountHealthPage from "../pages/AzureAccountHealthPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureUsers: vi.fn(),
    getAzureStatus: vi.fn(),
    getAzureSecurityFindingExceptions: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

function buildUser(overrides: Record<string, unknown>) {
  return {
    id: "user-1",
    display_name: "User One",
    object_type: "user",
    principal_name: "user.one@example.com",
    mail: "user.one@example.com",
    app_id: "",
    enabled: true,
    extra: {
      user_type: "Member",
      on_prem_sync: "",
      on_prem_domain: "",
      last_password_change: "2025-09-01T00:00:00Z",
      created_datetime: "2025-01-01T00:00:00Z",
      department: "IT",
      job_title: "Engineer",
      priority_band: "high",
      priority_score: "80",
      priority_reason: "Needs review",
      account_class: "person_cloud",
      missing_profile_fields: "",
      is_licensed: "false",
      license_count: "0",
    },
    ...overrides,
  };
}

describe("AzureAccountHealthPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureUsers.mockResolvedValue([
      buildUser({
        id: "user-1",
        display_name: "Stale Password User",
        principal_name: "stale@example.com",
        extra: {
          user_type: "Member",
          on_prem_sync: "",
          on_prem_domain: "",
          last_password_change: "2025-09-01T00:00:00Z",
          created_datetime: "2025-01-01T00:00:00Z",
          department: "IT",
          job_title: "Engineer",
          priority_band: "high",
          priority_score: "80",
          priority_reason: "Enabled cloud account has a stale password",
          account_class: "person_cloud",
          missing_profile_fields: "",
          is_licensed: "false",
          license_count: "0",
        },
      }),
      buildUser({
        id: "user-2",
        display_name: "Disabled User",
        principal_name: "disabled@example.com",
        enabled: false,
        extra: {
          user_type: "Member",
          on_prem_sync: "",
          on_prem_domain: "",
          last_password_change: "2026-03-01T00:00:00Z",
          created_datetime: "2025-01-01T00:00:00Z",
          department: "IT",
          job_title: "Engineer",
          priority_band: "medium",
          priority_score: "55",
          priority_reason: "Disabled member account",
          account_class: "person_cloud",
          missing_profile_fields: "",
          is_licensed: "false",
          license_count: "0",
        },
      }),
      buildUser({
        id: "user-3",
        display_name: "Old Guest",
        principal_name: "guest@example.com",
        extra: {
          user_type: "Guest",
          on_prem_sync: "",
          on_prem_domain: "",
          last_password_change: "",
          created_datetime: "2025-01-01T00:00:00Z",
          department: "",
          job_title: "",
          priority_band: "medium",
          priority_score: "60",
          priority_reason: "Guest account is more than one year old",
          account_class: "guest_external",
          missing_profile_fields: "",
          is_licensed: "false",
          license_count: "0",
        },
      }),
    ]);
    mockApi.getAzureStatus.mockResolvedValue({
      configured: true,
      initialized: true,
      refreshing: false,
      last_refresh: "2026-04-02T02:15:00Z",
      datasets: [
        {
          key: "directory",
          label: "Directory",
          configured: true,
          refreshing: false,
          interval_minutes: 30,
          item_count: 100,
          last_refresh: "2026-04-02T02:15:00Z",
        },
      ],
    });
    mockApi.getAzureSecurityFindingExceptions.mockResolvedValue([]);
  });

  it("renders the account health lane inside the security shell", async () => {
    render(<AzureAccountHealthPage />);

    expect(await screen.findByRole("heading", { name: "Account Health" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Security workspace" })).toHaveAttribute("href", "/security");
    expect(screen.getByRole("link", { name: "Open User Review" })).toHaveAttribute("href", "/security/user-review");
    expect(screen.getByRole("heading", { name: "Start Here" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Stale Passwords" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Disabled Accounts" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Old Guest Accounts" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Incomplete Profiles" })).toBeInTheDocument();
  });

  it("keeps the threshold controls active in the new lane", async () => {
    render(<AzureAccountHealthPage />);

    expect(await screen.findByRole("heading", { name: "Account Health" })).toBeInTheDocument();
    expect(screen.getByText("Stale Passwords (90d)")).toBeInTheDocument();

    const staleThresholdInput = screen.getByDisplayValue("90");
    fireEvent.change(staleThresholdInput, { target: { value: "365" } });

    expect(screen.getByText("Stale Passwords (365d)")).toBeInTheDocument();
    expect(screen.getByText(/Cloud accounts with no password change in 365\+ days/i)).toBeInTheDocument();
  });

  it("hides approved user exceptions from account health counts", async () => {
    mockApi.getAzureSecurityFindingExceptions.mockResolvedValue([
      {
        exception_id: "exception-1",
        scope: "directory_user",
        entity_id: "user-1",
        entity_label: "Stale Password User",
        entity_subtitle: "stale@example.com",
        reason: "Expected exception.",
        status: "active",
        created_at: "2026-04-03T03:00:00Z",
        updated_at: "2026-04-03T03:00:00Z",
        created_by_email: "reviewer@example.com",
        created_by_name: "Review User",
        updated_by_email: "reviewer@example.com",
        updated_by_name: "Review User",
      },
    ]);

    render(<AzureAccountHealthPage />);

    expect(await screen.findByRole("heading", { name: "Account Health" })).toBeInTheDocument();
    expect(screen.getByText(/approved user exception/i)).toBeInTheDocument();
    expect(screen.getByText("Stale Passwords (90d)")).toBeInTheDocument();
    expect(screen.queryByText("Stale Password User")).not.toBeInTheDocument();
  });
});
