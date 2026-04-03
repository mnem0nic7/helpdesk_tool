import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureSecurityDeviceCompliancePage from "../pages/AzureSecurityDeviceCompliancePage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureSecurityDeviceCompliance: vi.fn(),
    createAzureSecurityDeviceAction: vi.fn(),
    getAzureSecurityDeviceActionJob: vi.fn(),
    getAzureSecurityDeviceActionJobResults: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

function buildResponse() {
  return {
    generated_at: "2026-04-03T02:00:00Z",
    device_last_refresh: "2026-04-03T01:56:00Z",
    access_available: true,
    access_message: "Tenant-wide device compliance review is available.",
    metrics: [
      {
        key: "managed_devices",
        label: "Managed devices",
        value: 2,
        detail: "Two devices are cached.",
        tone: "sky",
      },
      {
        key: "stale_sync",
        label: "Stale sync",
        value: 1,
        detail: "One device is stale.",
        tone: "amber",
      },
    ],
    devices: [
      {
        id: "device-1",
        device_name: "Payroll Laptop",
        operating_system: "Windows",
        operating_system_version: "11",
        compliance_state: "noncompliant",
        management_state: "managed",
        owner_type: "company",
        enrollment_type: "windowsAzureADJoin",
        last_sync_date_time: "2026-04-03T01:00:00Z",
        last_sync_age_days: 0,
        azure_ad_device_id: "aad-1",
        primary_users: [
          {
            id: "user-1",
            display_name: "Ada Lovelace",
            principal_name: "ada@example.com",
            mail: "ada@example.com",
          },
        ],
        risk_level: "critical",
        finding_tags: ["noncompliant_or_grace"],
        recommended_actions: ["Run an Intune device sync and review the device's failing compliance policies."],
        action_ready: true,
        supported_actions: ["device_sync", "device_remote_lock", "device_retire", "device_wipe"],
        action_blockers: [],
      },
      {
        id: "device-2",
        device_name: "BYOD Phone",
        operating_system: "iOS",
        operating_system_version: "18",
        compliance_state: "unknown",
        management_state: "retired",
        owner_type: "personal",
        enrollment_type: "appleUserEnrollment",
        last_sync_date_time: "",
        last_sync_age_days: null,
        azure_ad_device_id: "aad-2",
        primary_users: [],
        risk_level: "high",
        finding_tags: ["unknown_or_not_evaluated", "personal_risky_device", "inactive_or_unmanaged"],
        recommended_actions: ["Personally owned device risk should be reviewed against BYOD policy and consider retire instead of broad trust."],
        action_ready: false,
        supported_actions: [],
        action_blockers: ["Device is already retired or pending deletion in Intune."],
      },
    ],
    warnings: ["Device compliance cache data is older than 2 hours, so Intune posture may be stale."],
    scope_notes: ["This lane reviews cached Intune managed-device posture across the tenant."],
  };
}

describe("AzureSecurityDeviceCompliancePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureSecurityDeviceCompliance.mockResolvedValue(buildResponse());
    mockApi.createAzureSecurityDeviceAction.mockResolvedValue({
      job_id: "job-1",
      status: "queued",
      action_type: "device_sync",
      device_ids: ["device-1"],
      device_names: ["Payroll Laptop"],
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      requested_at: "2026-04-03T02:00:00Z",
      started_at: null,
      completed_at: null,
      progress_current: 0,
      progress_total: 1,
      progress_message: "Queued",
      success_count: 0,
      failure_count: 0,
      results_ready: false,
      reason: "Compliance drift",
      error: "",
    });
    mockApi.getAzureSecurityDeviceActionJob.mockResolvedValue({
      job_id: "job-1",
      status: "completed",
      action_type: "device_sync",
      device_ids: ["device-1"],
      device_names: ["Payroll Laptop"],
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      requested_at: "2026-04-03T02:00:00Z",
      started_at: "2026-04-03T02:00:05Z",
      completed_at: "2026-04-03T02:00:10Z",
      progress_current: 1,
      progress_total: 1,
      progress_message: "Completed",
      success_count: 1,
      failure_count: 0,
      results_ready: true,
      reason: "Compliance drift",
      error: "",
    });
    mockApi.getAzureSecurityDeviceActionJobResults.mockResolvedValue([
      {
        device_id: "device-1",
        device_name: "Payroll Laptop",
        azure_ad_device_id: "aad-1",
        success: true,
        summary: "Queued device_sync for 1 device(s)",
        error: "",
        before_summary: { device_ids: ["device-1"] },
        after_summary: { action: "device_sync" },
      },
    ]);
  });

  it("renders the device compliance lane with pivots and coverage warnings", async () => {
    render(<AzureSecurityDeviceCompliancePage />);

    expect(await screen.findByRole("heading", { name: "Device Compliance Review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Bulk remediation" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Review queue" })).toBeInTheDocument();
    expect(screen.getByText("Device compliance cache data is older than 2 hours, so Intune posture may be stale.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open User Review" })).toHaveAttribute("href", "/security/user-review");
    expect(screen.getByRole("link", { name: "Open source record" })).toHaveAttribute("href", "/users?userId=user-1");
    expect(screen.getAllByRole("link", { name: "Open source record" })).toHaveLength(1);
  });

  it("filters devices and queues a bulk action", async () => {
    render(<AzureSecurityDeviceCompliancePage />);

    expect(await screen.findByRole("heading", { name: "Review queue" })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Search devices, users, tags, or recommendations..."), {
      target: { value: "Payroll" },
    });
    fireEvent.click(screen.getByLabelText("Select Payroll Laptop"));
    fireEvent.change(screen.getByPlaceholderText("Reason for this action (optional but recommended)..."), {
      target: { value: "Compliance drift" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Device sync" }));

    await waitFor(() => {
      expect(mockApi.createAzureSecurityDeviceAction).toHaveBeenCalledWith({
        action_type: "device_sync",
        device_ids: ["device-1"],
        reason: "Compliance drift",
        confirm_device_count: undefined,
        confirm_device_names: undefined,
      });
    });

    expect(await screen.findByRole("heading", { name: "Active device action job" })).toBeInTheDocument();
    await waitFor(() => {
      expect(mockApi.getAzureSecurityDeviceActionJobResults).toHaveBeenCalledWith("job-1");
    });
    expect(await screen.findByText("Queued device_sync for 1 device(s)")).toBeInTheDocument();

    expect(screen.getAllByText("Payroll Laptop").length).toBeGreaterThan(0);
    expect(screen.queryByText("BYOD Phone")).not.toBeInTheDocument();
  });
});
