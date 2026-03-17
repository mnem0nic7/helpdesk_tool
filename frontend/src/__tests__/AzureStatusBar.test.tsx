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

    fireEvent.click(screen.getByRole("button", { name: "Refresh Azure" }));

    await waitFor(() => {
      expect(mockApi.refreshAzure).toHaveBeenCalledTimes(1);
    });
  });
});
