import { describe, expect, it, beforeEach, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import AzureOverviewPage from "../pages/AzureOverviewPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureOverview: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

describe("AzureOverviewPage", () => {
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
      datasets: [],
      last_refresh: "2026-03-17T18:00:00Z",
    });
  });

  it("renders the existing overview without export health when the backend omits it", async () => {
    render(<AzureOverviewPage />);

    expect(await screen.findByText("Azure Overview")).toBeInTheDocument();
    expect(screen.queryByText("Cost Export Health")).not.toBeInTheDocument();
  });

  it("renders optional export health when the backend includes it", async () => {
    mockApi.getAzureOverview.mockResolvedValueOnce({
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
      datasets: [],
      last_refresh: "2026-03-17T18:00:00Z",
      cost_exports: {
        enabled: true,
        configured: true,
        running: false,
        refreshing: false,
        poll_interval_seconds: 900,
        last_sync_started_at: "2026-03-17T18:10:00Z",
        last_sync_finished_at: "2026-03-17T18:11:00Z",
        last_success_at: "2026-03-17T18:11:00Z",
        last_error: null,
        health: {
          delivery_count: 2,
          parsed_count: 2,
          quarantined_count: 0,
          staged_snapshot_count: 2,
          quarantine_artifact_count: 0,
          status_counts: { parsed: 2 },
          latest_delivery: {
            delivery_id: "delivery-1",
            landing_path: "/tmp/delivery-1",
            parse_status: "parsed",
            row_count: 4,
            manifest_path: "/tmp/delivery-1/manifest.json",
          },
          state: "healthy",
          reason: "Recent parsed delivery available",
        },
      },
    });

    render(<AzureOverviewPage />);

    expect(await screen.findByText("Cost Export Health")).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("Deliveries")).toBeInTheDocument();
    expect(screen.getByText("Parsed")).toBeInTheDocument();
    expect(screen.getByText("Quarantined")).toBeInTheDocument();
  });

  it("renders backend export health reasons for non-healthy states", async () => {
    mockApi.getAzureOverview.mockResolvedValueOnce({
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
      datasets: [],
      last_refresh: "2026-03-17T18:00:00Z",
      cost_exports: {
        enabled: true,
        configured: true,
        running: false,
        refreshing: false,
        poll_interval_seconds: 900,
        last_sync_started_at: "2026-03-17T18:10:00Z",
        last_sync_finished_at: "2026-03-17T18:11:00Z",
        last_success_at: "2026-03-17T18:11:00Z",
        last_error: null,
        health: {
          delivery_count: 3,
          parsed_count: 2,
          quarantined_count: 1,
          staged_snapshot_count: 2,
          quarantine_artifact_count: 1,
          status_counts: { parsed: 2, quarantined: 1 },
          latest_delivery: {
            delivery_id: "delivery-3",
            landing_path: "/tmp/delivery-3",
            parse_status: "quarantined",
            row_count: 0,
            manifest_path: "/tmp/delivery-3/manifest.json",
          },
          state: "stale",
          reason: "No successful delivery within 24h cadence",
        },
      },
    });

    render(<AzureOverviewPage />);

    expect(await screen.findByText("Cost Export Health")).toBeInTheDocument();
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.getByText("No successful delivery within 24h cadence")).toBeInTheDocument();
  });
});
