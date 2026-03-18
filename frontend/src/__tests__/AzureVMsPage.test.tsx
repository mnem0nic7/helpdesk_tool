import { beforeAll, describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import AzureVMsPage from "../pages/AzureVMsPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureVMs: vi.fn(),
    getAzureVMDetail: vi.fn(),
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
  });

  it("lets the VM detail drawer expand and restore", async () => {
    render(<AzureVMsPage />);

    await screen.findByText("vm-1");
    fireEvent.click(screen.getByText("vm-1"));

    const drawer = await screen.findByTestId("azure-vm-detail-drawer");
    expect(drawer).toHaveStyle({ width: "960px" });

    fireEvent.click(screen.getByRole("button", { name: "Expand" }));

    await waitFor(() => {
      expect(drawer).toHaveStyle({ width: "1368px" });
    });

    fireEvent.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() => {
      expect(drawer).toHaveStyle({ width: "960px" });
    });
  });
});
