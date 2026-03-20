import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import AzureStatusBar from "../components/AzureStatusBar.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureStatus: vi.fn(),
    refreshAzure: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

describe("AzureStatusBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureStatus.mockResolvedValue({
      configured: true,
      initialized: true,
      refreshing: false,
      last_refresh: "2026-03-17T18:00:00Z",
      datasets: [
        {
          key: "inventory",
          label: "Inventory",
          configured: true,
          refreshing: false,
          interval_minutes: 15,
          item_count: 42,
          last_refresh: "2026-03-17T18:00:00Z",
          error: null,
        },
      ],
      cost_exports: undefined,
    });
    mockApi.refreshAzure.mockResolvedValue({
      configured: true,
      initialized: true,
      refreshing: true,
      last_refresh: "2026-03-17T18:01:00Z",
      datasets: [],
    });
  });

  it("renders dataset counts and lets admins trigger refresh", async () => {
    render(<AzureStatusBar isAdmin />);

    expect(await screen.findByText("Azure cache connected")).toBeInTheDocument();
    expect(screen.getByText("Inventory: 42")).toBeInTheDocument();
    expect(screen.queryByText(/Cost exports:/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh Azure" }));

    await waitFor(() => {
      expect(mockApi.refreshAzure).toHaveBeenCalledTimes(1);
    });
  });

  it("renders export health when the backend includes cost exports", async () => {
    mockApi.getAzureStatus.mockResolvedValueOnce({
      configured: true,
      initialized: true,
      refreshing: false,
      last_refresh: "2026-03-17T18:00:00Z",
      datasets: [
        {
          key: "inventory",
          label: "Inventory",
          configured: true,
          refreshing: false,
          interval_minutes: 15,
          item_count: 42,
          last_refresh: "2026-03-17T18:00:00Z",
          error: null,
        },
      ],
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
        },
      },
    });

    render(<AzureStatusBar isAdmin />);

    expect(await screen.findByText("Cost exports: Healthy")).toBeInTheDocument();
    expect(screen.getByText("Deliveries: 2")).toBeInTheDocument();
    expect(screen.getByText("Parsed: 2")).toBeInTheDocument();
    expect(screen.getByText("Quarantined: 0")).toBeInTheDocument();
  });
});
