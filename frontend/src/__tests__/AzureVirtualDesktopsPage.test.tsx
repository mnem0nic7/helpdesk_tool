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
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      writable: true,
      value: 1400,
    });
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
          assignment_source: "avd:assigned-user",
          assignment_status: "resolved",
          assigned_user_source: "avd_assigned",
          assigned_user_source_label: "AVD assigned user",
          assigned_user_observed_utc: "",
          assigned_user_observed_local: "",
          owner_history_status: "available",
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
        explicit_avd_assignments: 1,
        fallback_session_history_assignments: 0,
        owner_history_unavailable: 0,
      },
      generated_at: "2026-03-23T00:00:00+00:00",
    });
  });

  it("opens a resizable detail drawer when a cleanup row is clicked", async () => {
    render(<AzureVirtualDesktopsPage />);

    const row = (await screen.findByText("avd-vm-1")).closest("tr");
    expect(row).not.toBeNull();
    fireEvent.click(row!);

    const drawer = await screen.findByTestId("avd-cleanup-detail-drawer");
    const resizer = await screen.findByTestId("avd-cleanup-detail-resizer");
    expect(drawer).toHaveStyle({ width: "960px" });
    expect(screen.getByText("Desktop Detail")).toBeInTheDocument();
    expect(screen.getByText("Signals & Cleanup Evaluation")).toBeInTheDocument();
    expect(screen.getByText("Resource ID")).toBeInTheDocument();

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

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => {
      expect(screen.queryByTestId("avd-cleanup-detail-drawer")).not.toBeInTheDocument();
    });
  });

  it("renders removal candidates and refetches when search changes", async () => {
    render(<AzureVirtualDesktopsPage />);

    await screen.findByText("avd-vm-1");
    expect(screen.getByText("Assigned User")).toBeInTheDocument();
    expect(screen.getByText("User Status")).toBeInTheDocument();
    expect(screen.getByText("Last Interactive User Sign-In")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(screen.getByText("Licensed")).toBeInTheDocument();
    expect(screen.getByText("2026-02-17 04:00 PM PST")).toBeInTheDocument();
    expect(screen.getByText("34d ago")).toBeInTheDocument();
    expect(screen.getByText("Assigned user is disabled")).toBeInTheDocument();
    expect(screen.getByText("AVD assigned user")).toBeInTheDocument();
    expect(screen.getByText("hostpool-1/avd-vm-1.contoso.local")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Search desktop, assigned user/i), {
      target: { value: "ada" },
    });

    await screen.findByDisplayValue("ada");
    await waitFor(() => {
      expect(mockApi.getAzureVirtualDesktopRemovalCandidates).toHaveBeenLastCalledWith({
        search: "ada",
        removal_only: false,
      });
    });
  });

  it("renders fallback owner provenance and unavailable history notes", async () => {
    mockApi.getAzureVirtualDesktopRemovalCandidates.mockResolvedValueOnce({
      desktops: [
        {
          id: "vm-2",
          name: "avd-vm-2",
          resource_type: "Microsoft.Compute/virtualMachines",
          subscription_id: "sub-1",
          subscription_name: "Prod",
          resource_group: "rg-avd",
          location: "eastus",
          kind: "",
          sku_name: "",
          vm_size: "Standard_D4s_v5",
          state: "PowerState/running",
          created_time: "",
          tags: {},
          size: "Standard_D4s_v5",
          power_state: "Running",
          cost: null,
          currency: "USD",
          assigned_user_display_name: "Linus Example",
          assigned_user_principal_name: "linus@example.com",
          assigned_user_enabled: true,
          assigned_user_licensed: true,
          assigned_user_last_successful_utc: "2026-03-22T00:00:00+00:00",
          assigned_user_last_successful_local: "2026-03-21 05:00 PM PDT",
          assignment_source: "avd:last-session",
          assignment_status: "resolved",
          assigned_user_source: "avd_last_session",
          assigned_user_source_label: "Last AVD session user",
          assigned_user_observed_utc: "2026-03-23T04:00:00+00:00",
          assigned_user_observed_local: "2026-03-22 09:00 PM PDT",
          owner_history_status: "available",
          host_pool_name: "hostpool-2",
          session_host_name: "avd-vm-2.contoso.local",
          last_power_signal_utc: "2026-03-23T00:00:00+00:00",
          last_power_signal_local: "2026-03-22 05:00 PM PDT",
          days_since_power_signal: 0,
          days_since_assigned_user_login: 1,
          power_signal_stale: false,
          power_signal_pending: false,
          user_signin_stale: false,
          mark_for_removal: false,
          mark_account_for_follow_up: false,
          account_action: "",
          removal_reasons: [],
        },
        {
          id: "vm-3",
          name: "avd-vm-3",
          resource_type: "Microsoft.Compute/virtualMachines",
          subscription_id: "sub-1",
          subscription_name: "Prod",
          resource_group: "rg-avd",
          location: "eastus",
          kind: "",
          sku_name: "",
          vm_size: "Standard_D4s_v5",
          state: "PowerState/running",
          created_time: "",
          tags: {},
          size: "Standard_D4s_v5",
          power_state: "Running",
          cost: null,
          currency: "USD",
          assigned_user_display_name: "Unassigned",
          assigned_user_principal_name: "",
          assigned_user_enabled: null,
          assigned_user_licensed: null,
          assigned_user_last_successful_utc: "",
          assigned_user_last_successful_local: "",
          assignment_source: "avd:session-host",
          assignment_status: "missing",
          assigned_user_source: "unassigned",
          assigned_user_source_label: "Unassigned",
          assigned_user_observed_utc: "",
          assigned_user_observed_local: "",
          owner_history_status: "missing_diagnostics",
          host_pool_name: "hostpool-3",
          session_host_name: "avd-vm-3.contoso.local",
          last_power_signal_utc: "2026-03-23T00:00:00+00:00",
          last_power_signal_local: "2026-03-22 05:00 PM PDT",
          days_since_power_signal: 0,
          days_since_assigned_user_login: null,
          power_signal_stale: false,
          power_signal_pending: false,
          user_signin_stale: false,
          mark_for_removal: false,
          mark_account_for_follow_up: false,
          account_action: "",
          removal_reasons: [],
        },
      ],
      matched_count: 2,
      total_count: 2,
      summary: {
        threshold_days: 14,
        tracked_desktops: 2,
        removal_candidates: 0,
        stale_power_signals: 0,
        disabled_or_unlicensed_assignments: 0,
        stale_assigned_user_signins: 0,
        assignment_review_required: 1,
        power_signal_pending: 0,
        account_follow_up_count: 0,
        explicit_avd_assignments: 0,
        fallback_session_history_assignments: 1,
        owner_history_unavailable: 1,
      },
      generated_at: "2026-03-23T00:00:00+00:00",
    });

    render(<AzureVirtualDesktopsPage />);

    await screen.findByText("Linus Example");
    expect(screen.getByText("Last AVD session user")).toBeInTheDocument();
    expect(screen.getByText("Observed 2026-03-22 09:00 PM PDT")).toBeInTheDocument();
    expect(screen.getByText("AVD connection diagnostics are not configured for fallback owner history")).toBeInTheDocument();
    expect(screen.getByText("No interactive Entra sign-in recorded")).toBeInTheDocument();
  });
});
