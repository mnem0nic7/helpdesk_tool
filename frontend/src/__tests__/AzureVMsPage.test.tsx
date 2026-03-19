import { beforeAll, describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import AzureVMsPage from "../pages/AzureVMsPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureVMs: vi.fn(),
    getAzureVMDetail: vi.fn(),
    getMe: vi.fn(),
    createAzureVMCostExportJob: vi.fn(),
    getAzureVMCostExportJob: vi.fn(),
    downloadAzureVMCostExportJob: vi.fn((jobId: string) => `/api/azure/vms/cost-export-jobs/${jobId}/download`),
    exportAzureVMCoverageExcel: vi.fn(() => "/api/azure/vms/coverage/export.xlsx"),
    exportAzureVMExcessExcel: vi.fn(() => "/api/azure/vms/excess/export.xlsx"),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

beforeAll(() => {
  globalThis.IntersectionObserver = vi.fn().mockImplementation(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
    takeRecords: vi.fn(),
    root: null,
    rootMargin: "",
    thresholds: [],
  })) as unknown as typeof IntersectionObserver;
});

const vmRow = {
  id: "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
  name: "vm-1",
  resource_type: "Microsoft.Compute/virtualMachines",
  subscription_id: "sub-1",
  subscription_name: "Prod",
  resource_group: "rg-prod",
  location: "eastus",
  kind: "",
  sku_name: "",
  vm_size: "Standard_D4s_v5",
  state: "PowerState/running",
  tags: {},
  size: "Standard_D4s_v5",
  power_state: "Running",
};

describe("AzureVMsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      writable: true,
      value: 1400,
    });
    mockApi.getMe.mockResolvedValue({
      email: "user@example.com",
      name: "Example User",
      is_admin: true,
      can_manage_users: true,
    });

    mockApi.getAzureVMs.mockResolvedValue({
      vms: [vmRow],
      matched_count: 1,
      total_count: 1,
      summary: {
        total_vms: 1,
        running_vms: 1,
        deallocated_vms: 0,
        distinct_sizes: 1,
      },
      by_size: [
        {
          label: "Standard_D4s_v5",
          region: "eastus",
          vm_count: 1,
          reserved_instance_count: 1,
          delta: 0,
          coverage_status: "balanced",
        },
      ],
      by_state: [{ label: "Running", count: 1 }],
      reservation_data_available: true,
      reservation_error: null,
    });
    mockApi.getAzureVMDetail.mockResolvedValue({
      vm: vmRow,
      associated_resources: [],
      cost: {
        lookback_days: 30,
        currency: "USD",
        cost_data_available: true,
        cost_error: null,
        total_cost: 100,
        vm_cost: 80,
        related_resource_cost: 20,
        priced_resource_count: 1,
      },
    });
    mockApi.createAzureVMCostExportJob.mockResolvedValue({
      job_id: "job-123",
      status: "queued",
      recipient_email: "user@example.com",
      scope: "filtered",
      lookback_days: 7,
      filters: { search: "wvd", subscription_id: "sub-1", location: "", state: "Running", size: "" },
      requested_at: "2026-03-18T00:00:00Z",
      started_at: null,
      completed_at: null,
      progress_current: 0,
      progress_total: 0,
      progress_message: "Queued",
      file_name: null,
      file_ready: false,
      error: null,
    });
    mockApi.getAzureVMCostExportJob.mockResolvedValue({
      job_id: "job-123",
      status: "completed",
      recipient_email: "user@example.com",
      scope: "filtered",
      lookback_days: 7,
      filters: { search: "wvd", subscription_id: "sub-1", location: "", state: "Running", size: "" },
      requested_at: "2026-03-18T00:00:00Z",
      started_at: "2026-03-18T00:01:00Z",
      completed_at: "2026-03-18T00:02:00Z",
      progress_current: 2,
      progress_total: 2,
      progress_message: "Export ready",
      file_name: "azure_vm_costs.xlsx",
      file_ready: true,
      error: null,
    });
  });

  it("lets the VM detail drawer resize, expand, and restore", async () => {
    render(<AzureVMsPage />);

    await screen.findByText("vm-1");
    fireEvent.click(screen.getByText("vm-1"));

    const drawer = await screen.findByTestId("azure-vm-detail-drawer");
    const resizer = await screen.findByTestId("azure-vm-detail-resizer");
    expect(drawer).toHaveStyle({ width: "960px" });

    fireEvent.pointerDown(resizer, { clientX: 440 });
    fireEvent.mouseMove(window, { clientX: 280 });
    fireEvent.mouseUp(window);

    await waitFor(() => {
      expect(drawer).toHaveStyle({ width: "1120px" });
    });

    fireEvent.click(screen.getByRole("button", { name: "Expand" }));

    await waitFor(() => {
      expect(drawer).toHaveStyle({ width: "1368px" });
    });

    fireEvent.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() => {
      expect(drawer).toHaveStyle({ width: "960px" });
    });
  });

  it("starts a filtered VM cost export job with the selected range", async () => {
    render(<AzureVMsPage />);

    await screen.findByText("vm-1");
    fireEvent.change(screen.getByPlaceholderText("Search VM name, size, tag..."), {
      target: { value: "wvd" },
    });
    await screen.findByText("vm-1");

    fireEvent.click(screen.getByRole("button", { name: "Export VM Costs" }));
    await screen.findByText(/Build a live Azure workbook/i);

    fireEvent.click(screen.getAllByRole("radio")[1]);
    fireEvent.click(screen.getByRole("button", { name: "Last 7 days" }));
    fireEvent.click(screen.getByRole("button", { name: "Start export" }));

    await waitFor(() => {
      expect(mockApi.createAzureVMCostExportJob).toHaveBeenCalledWith({
        scope: "filtered",
        lookback_days: 7,
        filters: {
          search: "wvd",
          subscription_id: "",
          location: "",
          state: "",
          size: "",
        },
      });
    });
  });
});
