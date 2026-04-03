import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureSecurityIdentityReviewPage from "../pages/AzureSecurityIdentityReviewPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureGroups: vi.fn(),
    getAzureEnterpriseApps: vi.fn(),
    getAzureAppRegistrations: vi.fn(),
    getAzureDirectoryRoles: vi.fn(),
    getAzureStatus: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

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

function buildLargeAppRegistrations(count = 60) {
  return Array.from({ length: count }, (_, index) =>
    buildDirectoryObject({
      id: `app-${index + 1}`,
      display_name: `Bulk App ${index + 1}`,
      object_type: "app_registration",
      app_id: `bulk-app-${index + 1}`,
      enabled: null,
      extra: {
        sign_in_audience: "AzureADandPersonalMicrosoftAccount",
        owner_count: "0",
        owner_names: "",
        owner_lookup_error: "",
        credential_count: "1",
        next_credential_expiry: "2026-04-10T00:00:00Z",
      },
    }),
  );
}

describe("AzureSecurityIdentityReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureGroups.mockResolvedValue([
      buildDirectoryObject({
        id: "group-1",
        display_name: "Finance Owners",
        object_type: "group",
        mail: "finance@example.com",
        enabled: true,
        extra: { group_types: "Unified" },
      }),
    ]);
    mockApi.getAzureEnterpriseApps.mockResolvedValue([
      buildDirectoryObject({
        id: "sp-1",
        display_name: "Salesforce SSO",
        object_type: "enterprise_app",
        enabled: true,
        app_id: "11111111-2222-3333-4444-555555555555",
        extra: { service_principal_type: "Application" },
      }),
    ]);
    mockApi.getAzureAppRegistrations.mockResolvedValue([
      buildDirectoryObject({
        id: "app-1",
        display_name: "Payroll Connector",
        object_type: "app_registration",
        app_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        enabled: null,
        extra: {
          sign_in_audience: "AzureADandPersonalMicrosoftAccount",
          owner_count: "0",
          owner_names: "",
          owner_lookup_error: "",
          credential_count: "1",
          next_credential_expiry: "2026-04-10T00:00:00Z",
        },
      }),
      buildDirectoryObject({
        id: "app-2",
        display_name: "Internal Workflow",
        object_type: "app_registration",
        app_id: "ffffffff-1111-2222-3333-444444444444",
        enabled: null,
        extra: {
          sign_in_audience: "AzureADMyOrg",
          owner_count: "2",
          owner_names: "Ada Lovelace, Grace Hopper",
          owner_lookup_error: "",
          credential_count: "1",
          next_credential_expiry: "2026-08-10T00:00:00Z",
        },
      }),
    ]);
    mockApi.getAzureDirectoryRoles.mockResolvedValue([
      buildDirectoryObject({
        id: "role-1",
        display_name: "Global Administrator",
        object_type: "directory_role",
        enabled: null,
        extra: { description: "Full access to manage the directory." },
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
  });

  it("renders the identity review lane with raw inventory pivots", async () => {
    render(<AzureSecurityIdentityReviewPage />);

    expect(await screen.findByRole("heading", { name: "Identity Review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Applications needing review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Enterprise applications" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Directory roles" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Group surfaces" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Application Hygiene" })).toHaveAttribute("href", "/security/app-hygiene");
    expect(screen.getByRole("link", { name: "Open raw identity inventory" })).toHaveAttribute("href", "/identity");
    expect(screen.getAllByRole("link", { name: "Open raw inventory" })[0]).toHaveAttribute(
      "href",
      "/identity?tab=app-registrations&objectId=app-1",
    );
  });

  it("filters to the flagged application cohort", async () => {
    render(<AzureSecurityIdentityReviewPage />);

    expect(await screen.findByRole("heading", { name: "Applications needing review" })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Search apps, roles, groups, owners, or review flags..."), {
      target: { value: "Payroll" },
    });
    fireEvent.change(screen.getByDisplayValue("All identity surfaces"), {
      target: { value: "apps-needing-review" },
    });

    expect(screen.getAllByText("Payroll Connector").length).toBeGreaterThan(0);
    expect(screen.queryByText("Internal Workflow")).not.toBeInTheDocument();
    expect(screen.queryByText("Finance Owners")).not.toBeInTheDocument();
  });

  it("pages large flagged-app cohorts instead of rendering every identity card at once", async () => {
    mockApi.getAzureAppRegistrations.mockResolvedValue(buildLargeAppRegistrations());

    render(<AzureSecurityIdentityReviewPage />);

    const sectionHeading = await screen.findByRole("heading", { name: "Applications needing review" });
    const section = sectionHeading.closest("section");
    expect(section).not.toBeNull();

    const scoped = within(section as HTMLElement);
    expect(scoped.getByText("Showing 1-50 of 60 flagged application registration(s)")).toBeInTheDocument();
    expect(scoped.getByText("Bulk App 1")).toBeInTheDocument();
    expect(scoped.queryByText("Bulk App 60")).not.toBeInTheDocument();

    fireEvent.click(scoped.getByRole("button", { name: "Next" }));

    expect(await scoped.findByText("Showing 51-60 of 60 flagged application registration(s)")).toBeInTheDocument();
    expect(scoped.getByText("Bulk App 60")).toBeInTheDocument();
  });
});
