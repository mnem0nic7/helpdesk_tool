import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureSecurityUserReviewPage from "../pages/AzureSecurityUserReviewPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureUsers: vi.fn(),
    getAzureStatus: vi.fn(),
    getAzureSecurityFindingExceptions: vi.fn(),
    createAzureSecurityFindingException: vi.fn(),
    restoreAzureSecurityFindingException: vi.fn(),
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
      on_prem_domain: "",
      on_prem_sync: "",
      is_licensed: "false",
      license_count: "0",
      last_successful_utc: "2026-04-01T00:00:00Z",
      last_successful_local: "Apr 1, 2026, 12:00 AM",
      account_class: "person_cloud",
      priority_band: "high",
      priority_score: "80",
      priority_reason: "High-signal user.",
      missing_profile_fields: "",
      department: "IT",
      job_title: "Engineer",
    },
    ...overrides,
  };
}

function buildLargeUserResponse(count = 60) {
  return Array.from({ length: count }, (_, index) =>
    buildUser({
      id: `user-${index + 1}`,
      display_name: `Bulk User ${index + 1}`,
      principal_name: `bulk.user.${index + 1}@example.com`,
      mail: `bulk.user.${index + 1}@example.com`,
      extra: {
        user_type: "Member",
        on_prem_domain: "",
        on_prem_sync: "",
        is_licensed: "false",
        license_count: "0",
        last_successful_utc: "",
        last_successful_local: "",
        account_class: "person_cloud",
        priority_band: "critical",
        priority_score: "90",
        priority_reason: "Bulk priority user.",
        missing_profile_fields: "",
        department: "IT",
        job_title: "Engineer",
      },
    }),
  );
}

describe("AzureSecurityUserReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureUsers.mockResolvedValue([
      buildUser({
        id: "user-1",
        display_name: "Emergency Admin",
        principal_name: "emergency.admin@example.com",
        mail: "emergency.admin@example.com",
        extra: {
          user_type: "Member",
          on_prem_domain: "",
          on_prem_sync: "",
          is_licensed: "true",
          license_count: "1",
          last_successful_utc: "",
          last_successful_local: "",
          account_class: "person_cloud",
          priority_band: "critical",
          priority_score: "95",
          priority_reason: "Enabled cloud account has a stale password.",
          missing_profile_fields: "Department",
          department: "",
          job_title: "Administrator",
        },
      }),
      buildUser({
        id: "user-2",
        display_name: "Guest Vendor",
        principal_name: "guest.vendor@example.com",
        mail: "guest.vendor@example.com",
        extra: {
          user_type: "Guest",
          on_prem_domain: "",
          on_prem_sync: "",
          is_licensed: "false",
          license_count: "0",
          last_successful_utc: "2026-04-01T00:00:00Z",
          last_successful_local: "Apr 1, 2026, 12:00 AM",
          account_class: "guest_external",
          priority_band: "medium",
          priority_score: "60",
          priority_reason: "Guest account is more than one year old.",
          missing_profile_fields: "",
          department: "",
          job_title: "",
        },
      }),
      buildUser({
        id: "user-3",
        display_name: "Shared Intake",
        principal_name: "shared-intake@example.com",
        mail: "shared-intake@example.com",
        extra: {
          user_type: "Member",
          on_prem_domain: "contoso.local",
          on_prem_sync: "true",
          is_licensed: "false",
          license_count: "0",
          last_successful_utc: "2026-04-01T00:00:00Z",
          last_successful_local: "Apr 1, 2026, 12:00 AM",
          account_class: "shared_or_service",
          priority_band: "low",
          priority_score: "35",
          priority_reason: "Shared or service-style account.",
          missing_profile_fields: "",
          department: "Operations",
          job_title: "Mailbox",
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
    mockApi.createAzureSecurityFindingException.mockImplementation(async (body: Record<string, unknown>) => ({
      exception_id: "exception-1",
      scope: "directory_user",
      entity_id: String(body.entity_id || ""),
      entity_label: String(body.entity_label || ""),
      entity_subtitle: String(body.entity_subtitle || ""),
      reason: String(body.reason || ""),
      status: "active",
      created_at: "2026-04-03T03:00:00Z",
      updated_at: "2026-04-03T03:00:00Z",
      created_by_email: "reviewer@example.com",
      created_by_name: "Review User",
      updated_by_email: "reviewer@example.com",
      updated_by_name: "Review User",
    }));
    mockApi.restoreAzureSecurityFindingException.mockResolvedValue({
      exception_id: "exception-1",
      scope: "directory_user",
      entity_id: "user-1",
      entity_label: "Emergency Admin",
      entity_subtitle: "emergency.admin@example.com",
      reason: "Expected stale emergency account.",
      status: "restored",
      created_at: "2026-04-03T03:00:00Z",
      updated_at: "2026-04-03T04:00:00Z",
      created_by_email: "reviewer@example.com",
      created_by_name: "Review User",
      updated_by_email: "reviewer@example.com",
      updated_by_name: "Review User",
    });
  });

  it("renders the user review lane with raw user pivots", async () => {
    render(<AzureSecurityUserReviewPage />);

    expect(await screen.findByRole("heading", { name: "User Review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Priority queue" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Review queue" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Account Health" })).toHaveAttribute("href", "/security/account-health");
    expect(screen.getByRole("link", { name: "Open raw user inventory" })).toHaveAttribute("href", "/users");
    expect(screen.getAllByText("Emergency Admin").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Open source record" })[0]).toHaveAttribute("href", "/users?userId=user-1");
  });

  it("filters the review queue to guest users", async () => {
    render(<AzureSecurityUserReviewPage />);

    const reviewHeading = await screen.findByRole("heading", { name: "Review queue" });
    const reviewSection = reviewHeading.closest("section");
    expect(reviewSection).not.toBeNull();

    fireEvent.change(screen.getByPlaceholderText("Search users, departments, risk reasons, or flags..."), {
      target: { value: "Guest" },
    });
    fireEvent.change(screen.getByDisplayValue("Priority queue"), {
      target: { value: "guests" },
    });

    const scoped = within(reviewSection as HTMLElement);
    expect(scoped.getAllByText("Guest Vendor").length).toBeGreaterThan(0);
    expect(scoped.queryByText("Emergency Admin")).not.toBeInTheDocument();
  });

  it("pages large review queues instead of rendering every user at once", async () => {
    mockApi.getAzureUsers.mockResolvedValue(buildLargeUserResponse());

    render(<AzureSecurityUserReviewPage />);

    const reviewHeading = await screen.findByRole("heading", { name: "Review queue" });
    const reviewSection = reviewHeading.closest("section");
    expect(reviewSection).not.toBeNull();

    const scoped = within(reviewSection as HTMLElement);
    expect(scoped.getByText("Showing 1-50 of 60 matching user record(s)")).toBeInTheDocument();
    expect(scoped.getAllByText("Bulk User 1").length).toBeGreaterThan(0);
    expect(scoped.queryByText("Bulk User 60")).not.toBeInTheDocument();

    fireEvent.click(scoped.getByRole("button", { name: "Next" }));

    expect(await scoped.findByText("Showing 51-60 of 60 matching user record(s)")).toBeInTheDocument();
    expect(scoped.getAllByText("Bulk User 60").length).toBeGreaterThan(0);
  });

  it("opens the exception editor in a drawer and lets operators cancel it", async () => {
    render(<AzureSecurityUserReviewPage />);

    expect(await screen.findByRole("heading", { name: "User Review" })).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Mark exception" })[0]);

    const drawer = await screen.findByRole("dialog", { name: "Mark finding as exception" });
    expect(within(drawer).getByText("Emergency Admin")).toBeInTheDocument();
    expect(within(drawer).getByPlaceholderText(/Document why this finding is expected/i)).toBeInTheDocument();

    fireEvent.click(within(drawer).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog", { name: "Mark finding as exception" })).not.toBeInTheDocument();
  });

  it("lets operators mark and restore approved finding exceptions", async () => {
    mockApi.getAzureSecurityFindingExceptions
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          exception_id: "exception-1",
          scope: "directory_user",
          entity_id: "user-1",
          entity_label: "Emergency Admin",
          entity_subtitle: "emergency.admin@example.com",
          reason: "Expected stale emergency account.",
          status: "active",
          created_at: "2026-04-03T03:00:00Z",
          updated_at: "2026-04-03T03:00:00Z",
          created_by_email: "reviewer@example.com",
          created_by_name: "Review User",
          updated_by_email: "reviewer@example.com",
          updated_by_name: "Review User",
        },
      ])
      .mockResolvedValueOnce([]);

    render(<AzureSecurityUserReviewPage />);

    expect(await screen.findByRole("heading", { name: "User Review" })).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Mark exception" })[0]);
    const drawer = await screen.findByRole("dialog", { name: "Mark finding as exception" });
    fireEvent.change(within(drawer).getByPlaceholderText(/Document why this finding is expected/i), {
      target: { value: "Expected stale emergency account." },
    });
    fireEvent.click(within(drawer).getByRole("button", { name: "Save exception" }));

    expect(await screen.findByText(/is now an active exception/i)).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Mark finding as exception" })).not.toBeInTheDocument();
    expect(mockApi.createAzureSecurityFindingException).toHaveBeenCalledWith(
      expect.objectContaining({
        entity_id: "user-1",
        reason: "Expected stale emergency account.",
      }),
    );

    expect(await screen.findByRole("heading", { name: "Active exceptions" })).toBeInTheDocument();
    expect(screen.getByText("Expected stale emergency account.")).toBeInTheDocument();
    const prioritySection = screen.getByRole("heading", { name: "Priority queue" }).closest("section");
    const reviewSection = screen.getByRole("heading", { name: "Review queue" }).closest("section");
    expect(prioritySection).not.toBeNull();
    expect(reviewSection).not.toBeNull();
    expect(within(prioritySection as HTMLElement).queryByText("Emergency Admin")).not.toBeInTheDocument();
    expect(within(reviewSection as HTMLElement).queryByText("Emergency Admin")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Restore finding" }));

    expect(await screen.findByText(/was restored to the security review queues/i)).toBeInTheDocument();
    expect(mockApi.restoreAzureSecurityFindingException).toHaveBeenCalledWith("exception-1");
  });
});
