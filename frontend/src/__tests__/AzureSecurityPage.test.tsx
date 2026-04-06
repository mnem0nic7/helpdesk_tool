import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import AzureSecurityPage from "../pages/AzureSecurityPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureOverview: vi.fn(),
    getAzureStatus: vi.fn(),
    getAzureSecurityWorkspaceSummary: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

function buildWorkspaceSummary() {
  return {
    generated_at: "2026-04-04T04:10:00Z",
    workspace_last_refresh: "2026-04-04T04:00:00Z",
    lanes: [
      {
        lane_key: "security-copilot",
        status: "info",
        attention_score: 40,
        attention_count: 0,
        attention_label: "Ready for investigation",
        secondary_label: "Guided investigation across Azure and local sources.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: true,
        access_message: "Open Security Copilot to start guided incident intake.",
        warning_count: 0,
        summary_mode: "manual",
      },
      {
        lane_key: "dlp-review",
        status: "info",
        attention_score: 38,
        attention_count: 0,
        attention_label: "Ready for pasted findings",
        secondary_label: "Paste a finding to start normalized DLP review.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: true,
        access_message: "Open DLP Findings Review to normalize a pasted finding.",
        warning_count: 0,
        summary_mode: "manual",
      },
      {
        lane_key: "access-review",
        status: "critical",
        attention_score: 548,
        attention_count: 6,
        attention_label: "6 critical principals need review",
        secondary_label: "9 privileged assignments cached across 6 principals.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: true,
        access_message: "",
        warning_count: 0,
        summary_mode: "count",
      },
      {
        lane_key: "conditional-access-tracker",
        status: "warning",
        attention_score: 332,
        attention_count: 2,
        attention_label: "2 policy or changes need review",
        secondary_label: "4 policies and 2 recent changes cached.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: true,
        access_message: "Conditional Access drift review is available.",
        warning_count: 0,
        summary_mode: "count",
      },
      {
        lane_key: "break-glass-validation",
        status: "warning",
        attention_score: 316,
        attention_count: 1,
        attention_label: "1 break-glass account needs validation",
        secondary_label: "2 matched accounts, 1 privileged candidate.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: true,
        access_message: "",
        warning_count: 0,
        summary_mode: "count",
      },
      {
        lane_key: "identity-review",
        status: "warning",
        attention_score: 122,
        attention_count: 0,
        attention_label: "Cache freshness needs attention",
        secondary_label: "3 collaboration groups, 4 directory roles cached.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: true,
        access_message: "",
        warning_count: 1,
        summary_mode: "count",
      },
      {
        lane_key: "directory-role-review",
        status: "unavailable",
        attention_score: 738,
        attention_count: 0,
        attention_label: "Access limited",
        secondary_label: "3 directory roles cached for later review.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: false,
        access_message: "User administration access is required to review direct Entra directory-role memberships on this tenant.",
        warning_count: 1,
        summary_mode: "availability",
      },
      {
        lane_key: "app-hygiene",
        status: "warning",
        attention_score: 324,
        attention_count: 2,
        attention_label: "2 app registrations need hygiene review",
        secondary_label: "1 expired credential across 4 app registrations.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: true,
        access_message: "",
        warning_count: 0,
        summary_mode: "count",
      },
      {
        lane_key: "user-review",
        status: "warning",
        attention_score: 340,
        attention_count: 4,
        attention_label: "4 priority users in queue",
        secondary_label: "5 stale sign-ins and 1 disabled licensed account.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: true,
        access_message: "",
        warning_count: 0,
        summary_mode: "count",
      },
      {
        lane_key: "guest-access-review",
        status: "critical",
        attention_score: 536,
        attention_count: 2,
        attention_label: "2 guest accounts need immediate review",
        secondary_label: "1 external-audience app and 2 collaboration groups widen reach.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: true,
        access_message: "",
        warning_count: 0,
        summary_mode: "count",
      },
      {
        lane_key: "account-health",
        status: "critical",
        attention_score: 532,
        attention_count: 3,
        attention_label: "3 accounts need hygiene review",
        secondary_label: "2 stale passwords, 1 disabled account, 1 old guest, 1 incomplete profile.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: true,
        access_message: "",
        warning_count: 0,
        summary_mode: "count",
      },
      {
        lane_key: "device-compliance",
        status: "warning",
        attention_score: 336,
        attention_count: 5,
        attention_label: "5 devices need posture review",
        secondary_label: "4 devices are action-ready from cached posture.",
        refresh_at: "2026-04-04T04:00:00Z",
        access_available: true,
        access_message: "Tenant-wide device compliance review is available.",
        warning_count: 0,
        summary_mode: "count",
      },
    ],
  };
}

describe("AzureSecurityPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mockApi.getAzureOverview.mockResolvedValue({
      subscriptions: 4,
      management_groups: 2,
      resources: 125,
      role_assignments: 15,
      users: 48,
      groups: 12,
      enterprise_apps: 9,
      app_registrations: 6,
      directory_roles: 3,
      cost: {
        lookback_days: 30,
        total_cost: 1234.56,
        currency: "USD",
        top_service: "Virtual Machines",
        top_subscription: "Prod",
        top_resource_group: "rg-prod",
        recommendation_count: 2,
        potential_monthly_savings: 321.0,
      },
      datasets: [
        {
          key: "directory",
          label: "Directory",
          configured: true,
          refreshing: false,
          interval_minutes: 30,
          item_count: 100,
          last_refresh: "2026-04-04T04:00:00Z",
        },
        {
          key: "alerts",
          label: "Alerts",
          configured: true,
          refreshing: false,
          interval_minutes: 30,
          item_count: 20,
          last_refresh: "2026-04-04T04:00:00Z",
        },
      ],
      last_refresh: "2026-04-04T04:00:00Z",
    });
    mockApi.getAzureStatus.mockResolvedValue({
      configured: true,
      initialized: true,
      refreshing: false,
      last_refresh: "2026-04-04T04:00:00Z",
      datasets: [
        {
          key: "directory",
          label: "Directory",
          configured: true,
          refreshing: false,
          interval_minutes: 30,
          item_count: 100,
          last_refresh: "2026-04-04T04:00:00Z",
        },
        {
          key: "alerts",
          label: "Alerts",
          configured: true,
          refreshing: false,
          interval_minutes: 30,
          item_count: 20,
          last_refresh: "2026-04-04T04:00:00Z",
        },
      ],
    });
    mockApi.getAzureSecurityWorkspaceSummary.mockResolvedValue(buildWorkspaceSummary());
  });

  it("renders the triage-first security workspace with live lane summaries and stable lane links", async () => {
    render(<AzureSecurityPage />);

    expect(await screen.findByRole("heading", { level: 1, name: "Azure Security" })).toBeInTheDocument();
    expect(screen.getByText("Needs Attention Now")).toBeInTheDocument();
    expect(screen.getByText("Lane Explorer")).toBeInTheDocument();
    expect(screen.getByText("Grouped Lane Catalog")).toBeInTheDocument();
    expect(screen.getByText("Support Tools")).toBeInTheDocument();
    expect(screen.getByText("Workspace summary ready")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Review top priorities/i })).toHaveAttribute("href", "#needs-attention");
    expect(screen.getByRole("link", { name: "Jump to lane explorer" })).toHaveAttribute("href", "#lane-explorer");
    expect(screen.getAllByText("Catalog lanes")[0]).toBeInTheDocument();
    expect(screen.getAllByText("6 critical principals need review")[0]).toBeInTheDocument();
    expect(screen.getAllByText("2 guest accounts need immediate review")[0]).toBeInTheDocument();
    expect(screen.getAllByText("Access limited")[0]).toBeInTheDocument();
    expect(screen.getAllByText("1 cache warning")[0]).toBeInTheDocument();

    expect(screen.getAllByRole("link", { name: "Open Security Copilot" })[0]).toHaveAttribute("href", "/security/copilot");
    expect(screen.getByRole("link", { name: "Open DLP Findings Review" })).toHaveAttribute("href", "/security/dlp-review");
    expect(screen.getByRole("link", { name: "Open Conditional Access Tracker" })).toHaveAttribute("href", "/security/conditional-access-tracker");
    expect(screen.getAllByRole("link", { name: "Open Break-glass Validation" })[0]).toHaveAttribute("href", "/security/break-glass-validation");
    expect(screen.getAllByRole("link", { name: "Open Identity Review" })[0]).toHaveAttribute("href", "/security/identity-review");
    expect(screen.getAllByRole("link", { name: "Open Directory Role Review" })[0]).toHaveAttribute("href", "/security/directory-role-review");
    expect(screen.getAllByRole("link", { name: "Open Application Hygiene" })[0]).toHaveAttribute("href", "/security/app-hygiene");
    expect(screen.getAllByRole("link", { name: "Open User Review" })[0]).toHaveAttribute("href", "/security/user-review");
    expect(screen.getAllByRole("link", { name: "Open Guest Access Review" })[0]).toHaveAttribute("href", "/security/guest-access-review");
    expect(screen.getAllByRole("link", { name: "Open Account Health" })[0]).toHaveAttribute("href", "/security/account-health");
    expect(screen.getByRole("link", { name: "Open Device Compliance Review" })).toHaveAttribute("href", "/security/device-compliance");
    expect(screen.getByRole("link", { name: "Microsoft Defender" })).toHaveAttribute("href", "https://security.microsoft.com/");
  });

  it("filters the lane catalog by search and state", async () => {
    render(<AzureSecurityPage />);

    expect(await screen.findByText("Lane Explorer")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Search incidents, privileged access, guests, devices, apps..."), {
      target: { value: "guest" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Needs attention 4" }));

    expect(screen.getAllByText("Guest Access Review")[0]).toBeInTheDocument();
    expect(screen.queryByText("Application Hygiene")).not.toBeInTheDocument();
    expect(screen.queryByText("Security Incident Copilot")).not.toBeInTheDocument();
    expect(screen.getByText('Search: "guest"')).toBeInTheDocument();
    expect(screen.getByText("State: Needs attention")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear all filters" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear all filters" }));

    expect(screen.getByText("All lanes visible")).toBeInTheDocument();
    expect(screen.queryByText('Search: "guest"')).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear all filters" })).not.toBeInTheDocument();
  });

  it("supports quick-focus presets and collapsible lane groups", async () => {
    render(<AzureSecurityPage />);

    expect(await screen.findByText("Quick focus")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "External access" }));

    expect(screen.getByText("Group: Accounts & External Access")).toBeInTheDocument();
    const groupedCatalog = screen.getByRole("heading", { level: 2, name: "Grouped Lane Catalog" }).closest("section");
    expect(groupedCatalog).not.toBeNull();
    expect(within(groupedCatalog as HTMLElement).queryByRole("button", { name: /Respond Now/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Collapse all groups" }));

    const externalAccessToggle = within(groupedCatalog as HTMLElement)
      .getAllByRole("button")
      .find((button) => button.getAttribute("aria-controls") === "security-group-accounts-external-access");

    expect(externalAccessToggle).toBeDefined();
    expect(within(groupedCatalog as HTMLElement).getByText(/This group is collapsed\./i)).toBeInTheDocument();

    fireEvent.click(externalAccessToggle as HTMLButtonElement);

    expect(screen.getAllByText("Guest Access Review")[0]).toBeInTheDocument();
    expect(screen.getByText("Catalog guidance")).toBeInTheDocument();
  });

  it("persists the workspace view locally and restores defaults on demand", async () => {
    const firstRender = render(<AzureSecurityPage />);

    expect(await screen.findByText("Lane Explorer")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Guests" }));
    fireEvent.click(screen.getByRole("button", { name: /Roadmap/i }));
    fireEvent.click(screen.getByRole("button", { name: "Collapse all groups" }));

    firstRender.unmount();

    render(<AzureSecurityPage />);

    expect(await screen.findByDisplayValue("guest")).toBeInTheDocument();
    expect(screen.getByText('Search: "guest"')).toBeInTheDocument();
    expect(screen.getByText("Emergency-account MFA posture validation")).toBeInTheDocument();
    expect(screen.getAllByText(/This group is collapsed\./i).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Restore default view" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Restore default view" }));

    expect(screen.getByPlaceholderText("Search incidents, privileged access, guests, devices, apps...")).toHaveValue("");
    expect(screen.getByText("All lanes visible")).toBeInTheDocument();
    expect(screen.queryByText('Search: "guest"')).not.toBeInTheDocument();
    expect(screen.queryByText("Emergency-account MFA posture validation")).not.toBeInTheDocument();
  });

  it("shows a non-blocking fallback when the workspace summary query fails", async () => {
    mockApi.getAzureSecurityWorkspaceSummary.mockRejectedValueOnce(new Error("summary unavailable"));

    render(<AzureSecurityPage />);

    expect(await screen.findByRole("heading", { level: 1, name: "Azure Security" })).toBeInTheDocument();
    expect(screen.getByText(/static workspace catalog/i)).toBeInTheDocument();
    expect(screen.getByText("Grouped Lane Catalog")).toBeInTheDocument();
    expect(screen.getAllByText("Security Incident Copilot")[0]).toBeInTheDocument();
  });

  it("keeps the roadmap collapsed by default and expands on demand", async () => {
    render(<AzureSecurityPage />);

    expect(await screen.findByText("Roadmap")).toBeInTheDocument();
    expect(screen.queryByText("Emergency-account MFA posture validation")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Roadmap/i }));

    expect(screen.getByText("Emergency-account MFA posture validation")).toBeInTheDocument();
  });
});
