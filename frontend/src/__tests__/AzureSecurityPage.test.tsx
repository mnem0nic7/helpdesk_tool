import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import AzureSecurityPage from "../pages/AzureSecurityPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureOverview: vi.fn(),
    getAzureStatus: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

describe("AzureSecurityPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
          last_refresh: "2026-04-01T20:30:00Z",
        },
        {
          key: "alerts",
          label: "Alerts",
          configured: true,
          refreshing: false,
          interval_minutes: 30,
          item_count: 20,
          last_refresh: "2026-04-01T20:30:00Z",
        },
      ],
      last_refresh: "2026-04-01T20:30:00Z",
    });
    mockApi.getAzureStatus.mockResolvedValue({
      configured: true,
      initialized: true,
      refreshing: false,
      last_refresh: "2026-04-01T20:31:00Z",
      datasets: [
        {
          key: "directory",
          label: "Directory",
          configured: true,
          refreshing: false,
          interval_minutes: 30,
          item_count: 100,
          last_refresh: "2026-04-01T20:31:00Z",
        },
        {
          key: "alerts",
          label: "Alerts",
          configured: true,
          refreshing: false,
          interval_minutes: 30,
          item_count: 20,
          last_refresh: "2026-04-01T20:31:00Z",
        },
      ],
    });
  });

  it("renders the security workspace with starter tools", async () => {
    render(<AzureSecurityPage />);

    expect(await screen.findByText("Azure Security")).toBeInTheDocument();
    expect(screen.getByText("Security Control Planes")).toBeInTheDocument();
    expect(screen.getByText("Starter Security Tools")).toBeInTheDocument();
    expect(screen.getByText("Identity Review Lane")).toBeInTheDocument();
    expect(screen.getByText("2/2 configured datasets healthy")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Alert Desk" })).toHaveAttribute("href", "/alerts");
    expect(screen.getByRole("link", { name: "Microsoft Defender" })).toHaveAttribute("href", "https://security.microsoft.com/");
  });

  it("falls back to overview datasets when the live status call is unavailable", async () => {
    mockApi.getAzureStatus.mockRejectedValueOnce(new Error("status unavailable"));

    render(<AzureSecurityPage />);

    expect(await screen.findByText("Azure Security")).toBeInTheDocument();
    expect(screen.getByText("2/2 configured datasets healthy")).toBeInTheDocument();
  });
});
