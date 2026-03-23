import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import AzureVirtualDesktopsPage from "../pages/AzureVirtualDesktopsPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureVirtualDesktopRemovalCandidates: vi.fn(),
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

describe("AzureVirtualDesktopsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureVirtualDesktopRemovalCandidates.mockResolvedValue({
      desktops: [
        {
          id: "vm-1",
          name: "avd-vm-1",
          resource_type: "Microsoft.Compute/virtualMachines",
          subscription_id: "sub-1",
          subscription_name: "Prod",
          resource_group: "rg-avd",
          location: "eastus",
          kind: "",
          sku_name: "",
          vm_size: "Standard_D4s_v5",
          state: "PowerState/deallocated",
          created_time: "",
          tags: {},
          size: "Standard_D4s_v5",
          power_state: "Deallocated",
          cost: null,
          currency: "USD",
          assigned_user_display_name: "Ada Lovelace",
          assigned_user_principal_name: "ada@example.com",
          assigned_user_enabled: false,
          assigned_user_licensed: true,
          assigned_user_last_successful_utc: "2026-02-18T00:00:00+00:00",
          assigned_user_last_successful_local: "2026-02-17 04:00 PM PST",
          assignment_source: "session-host",
          assignment_status: "resolved",
          host_pool_name: "hostpool-1",
          session_host_name: "hostpool-1/avd-vm-1.contoso.local",
          last_power_signal_utc: "2026-02-20T00:00:00+00:00",
          last_power_signal_local: "2026-02-19 04:00 PM PST",
          days_since_power_signal: 32,
          days_since_assigned_user_login: 34,
          power_signal_stale: true,
          power_signal_pending: false,
          user_signin_stale: true,
          mark_for_removal: true,
          mark_account_for_follow_up: true,
          account_action: "Already disabled",
          removal_reasons: [
            "No running signal in 14+ days",
            "Assigned user is disabled",
          ],
        },
      ],
      matched_count: 1,
      total_count: 1,
      summary: {
        threshold_days: 14,
        tracked_desktops: 1,
        removal_candidates: 1,
        stale_power_signals: 1,
        disabled_or_unlicensed_assignments: 1,
        stale_assigned_user_signins: 1,
        assignment_review_required: 0,
        power_signal_pending: 0,
        account_follow_up_count: 1,
      },
      generated_at: "2026-03-23T00:00:00+00:00",
    });
  });

  it("renders removal candidates and refetches when search changes", async () => {
    render(<AzureVirtualDesktopsPage />);

    await screen.findByText("avd-vm-1");
    expect(screen.getByText("Assigned user is disabled")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Search desktop, assigned user/i), {
      target: { value: "ada" },
    });

    await screen.findByDisplayValue("ada");
    await waitFor(() => {
      expect(mockApi.getAzureVirtualDesktopRemovalCandidates).toHaveBeenLastCalledWith({
        search: "ada",
        removal_only: true,
      });
    });
  });
});
