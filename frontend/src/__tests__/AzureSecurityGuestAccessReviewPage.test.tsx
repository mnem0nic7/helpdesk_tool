import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureSecurityGuestAccessReviewPage from "../pages/AzureSecurityGuestAccessReviewPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureUsers: vi.fn(),
    getAzureGroups: vi.fn(),
    getAzureAppRegistrations: vi.fn(),
    getAzureStatus: vi.fn(),
    getAzureSecurityFindingExceptions: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 86_400_000).toISOString();
}

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
      user_type: "Guest",
      created_datetime: isoDaysAgo(400),
      last_successful_utc: "",
      last_successful_local: "",
      priority_score: "80",
      priority_reason: "Needs guest review",
      account_class: "guest_external",
      is_licensed: "false",
      license_count: "0",
      missing_profile_fields: "",
      department: "",
      job_title: "",
    },
    ...overrides,
  };
}

function buildDirectoryObject(overrides: Record<string, unknown>) {
  return {
    id: "object-1",
    display_name: "Object",
    object_type: "group",
    principal_name: "",
    mail: "",
    app_id: "",
    enabled: true,
    extra: {},
    ...overrides,
  };
}

describe("AzureSecurityGuestAccessReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureUsers.mockResolvedValue([
      buildUser({
        id: "guest-1",
        display_name: "Guest Vendor",
        principal_name: "guest.vendor@example.com",
        mail: "guest.vendor@example.com",
        extra: {
          user_type: "Guest",
          created_datetime: isoDaysAgo(420),
          last_successful_utc: "",
          last_successful_local: "",
          priority_score: "90",
          priority_reason: "Guest account is old and has no successful sign-in.",
          account_class: "guest_external",
          is_licensed: "false",
          license_count: "0",
          missing_profile_fields: "",
          department: "",
          job_title: "",
        },
      }),
      buildUser({
        id: "guest-2",
        display_name: "Recent Guest",
        principal_name: "recent.guest@example.com",
        mail: "recent.guest@example.com",
        extra: {
          user_type: "Guest",
          created_datetime: isoDaysAgo(30),
          last_successful_utc: isoDaysAgo(5),
          last_successful_local: "recent",
          priority_score: "20",
          priority_reason: "Recently active guest.",
          account_class: "guest_external",
          is_licensed: "false",
          license_count: "0",
          missing_profile_fields: "",
          department: "",
          job_title: "",
        },
      }),
      buildUser({
        id: "guest-3",
        display_name: "Disabled Guest",
        principal_name: "disabled.guest@example.com",
        mail: "disabled.guest@example.com",
        enabled: false,
        extra: {
          user_type: "Guest",
          created_datetime: isoDaysAgo(220),
          last_successful_utc: isoDaysAgo(120),
          last_successful_local: "old",
          priority_score: "70",
          priority_reason: "Disabled guest still present.",
          account_class: "guest_external",
          is_licensed: "false",
          license_count: "0",
          missing_profile_fields: "",
          department: "",
          job_title: "",
        },
      }),
    ]);
    mockApi.getAzureGroups.mockResolvedValue([
      buildDirectoryObject({
        id: "group-1",
        display_name: "Partner Collaboration",
        object_type: "group",
        mail: "partners@example.com",
        enabled: true,
        extra: { group_types: "Unified" },
      }),
    ]);
    mockApi.getAzureAppRegistrations.mockResolvedValue([
      buildDirectoryObject({
        id: "app-1",
        display_name: "Vendor Portal",
        object_type: "app_registration",
        app_id: "11111111-2222-3333-4444-555555555555",
        enabled: null,
        extra: {
          sign_in_audience: "AzureADMultipleOrgs",
          owner_names: "Ada Lovelace",
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

  it("renders the guest access review lane with raw pivots", async () => {
    render(<AzureSecurityGuestAccessReviewPage />);

    expect(await screen.findByRole("heading", { name: "Guest Access Review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Priority guest queue" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Guest identity review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Collaboration surfaces" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "External application surfaces" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open User Review" })).toHaveAttribute("href", "/security/user-review");
    expect(screen.getByRole("link", { name: "Open raw user inventory" })).toHaveAttribute("href", "/users");
    expect(screen.getAllByRole("link", { name: "Open source record" })[0]).toHaveAttribute("href", "/users?userId=guest-1");
    expect(screen.getByRole("link", { name: "Open raw group" })).toHaveAttribute("href", "/identity?tab=groups&objectId=group-1");
    expect(screen.getByRole("link", { name: "Open raw inventory" })).toHaveAttribute("href", "/identity?tab=app-registrations&objectId=app-1");
  });

  it("filters the guest review queue to stale guests", async () => {
    render(<AzureSecurityGuestAccessReviewPage />);

    const reviewHeading = await screen.findByRole("heading", { name: "Guest identity review" });
    const reviewSection = reviewHeading.closest("section");
    expect(reviewSection).not.toBeNull();

    fireEvent.change(screen.getByPlaceholderText("Search guest users, risk reasons, or flags..."), {
      target: { value: "Guest" },
    });
    fireEvent.change(screen.getByDisplayValue("Priority queue"), {
      target: { value: "stale-guests" },
    });

    const scoped = within(reviewSection as HTMLElement);
    expect(scoped.getAllByText("Guest Vendor").length).toBeGreaterThan(0);
    expect(scoped.queryByText("Disabled Guest")).not.toBeInTheDocument();
    expect(scoped.queryByText("Recent Guest")).not.toBeInTheDocument();
  });

  it("hides approved user exceptions from the guest lane", async () => {
    mockApi.getAzureSecurityFindingExceptions.mockResolvedValue([
      {
        exception_id: "exception-1",
        scope: "directory_user",
        finding_key: "guest-user",
        finding_label: "Guest users",
        entity_id: "guest-1",
        entity_label: "Guest Vendor",
        entity_subtitle: "guest.vendor@example.com",
        reason: "Approved guest exception.",
        status: "active",
        created_at: "2026-04-03T03:00:00Z",
        updated_at: "2026-04-03T03:00:00Z",
        created_by_email: "reviewer@example.com",
        created_by_name: "Review User",
        updated_by_email: "reviewer@example.com",
        updated_by_name: "Review User",
      },
    ]);

    render(<AzureSecurityGuestAccessReviewPage />);

    expect(await screen.findByRole("heading", { name: "Guest Access Review" })).toBeInTheDocument();
    expect(screen.getByText(/approved finding exception/i)).toBeInTheDocument();
    expect(screen.queryByText("Guest Vendor")).not.toBeInTheDocument();
  });
});
