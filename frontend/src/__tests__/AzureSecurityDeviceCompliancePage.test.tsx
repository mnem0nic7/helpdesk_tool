import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureSecurityDeviceCompliancePage from "../pages/AzureSecurityDeviceCompliancePage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureSecurityDeviceCompliance: vi.fn(),
    createAzureSecurityDeviceAction: vi.fn(),
    previewAzureSecurityDeviceFixPlan: vi.fn(),
    executeAzureSecurityDeviceFixPlan: vi.fn(),
    getAzureSecurityDeviceActionJob: vi.fn(),
    getAzureSecurityDeviceActionJobResults: vi.fn(),
    getAzureSecurityDeviceActionBatch: vi.fn(),
    getAzureSecurityDeviceActionBatchResults: vi.fn(),
    getAzureUsers: vi.fn(),
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
        recommended_fix_action: "device_sync",
        recommended_fix_label: "Device sync",
        recommended_fix_reason: "Run an Intune sync first so compliance state refreshes.",
        recommended_fix_requires_user_picker: false,
        action_ready: true,
        supported_actions: ["device_sync", "device_remote_lock", "device_retire", "device_wipe", "device_reassign_primary_user"],
        action_blockers: [],
      },
      {
        id: "device-2",
        device_name: "BYOD Phone",
        operating_system: "iOS",
        operating_system_version: "18",
        compliance_state: "unknown",
        management_state: "managed",
        owner_type: "personal",
        enrollment_type: "appleUserEnrollment",
        last_sync_date_time: "",
        last_sync_age_days: null,
        azure_ad_device_id: "aad-2",
        primary_users: [],
        risk_level: "high",
        finding_tags: ["unknown_or_not_evaluated", "personal_risky_device", "no_primary_user"],
        recommended_actions: ["Personally owned device risk should be reviewed against BYOD policy and consider retire instead of broad trust."],
        recommended_fix_action: "device_reassign_primary_user",
        recommended_fix_label: "Assign primary user",
        recommended_fix_reason: "Assign a primary user before broader remediation because the device currently has no resolved owner.",
        recommended_fix_requires_user_picker: true,
        action_ready: true,
        supported_actions: ["device_sync", "device_remote_lock", "device_retire", "device_wipe", "device_reassign_primary_user"],
        action_blockers: [],
      },
    ],
    warnings: ["Device compliance cache data is older than 2 hours, so Intune posture may be stale."],
    scope_notes: ["This lane reviews cached Intune managed-device posture across the tenant."],
  };
}

function buildFixPlan() {
  return {
    generated_at: "2026-04-03T02:05:00Z",
    device_ids: ["device-1", "device-2"],
    items: [
      {
        device_id: "device-1",
        device_name: "Payroll Laptop",
        risk_level: "critical",
        finding_tags: ["noncompliant_or_grace"],
        action_type: "device_sync",
        action_label: "Device sync",
        action_reason: "Sync first",
        requires_primary_user: false,
        primary_users: [],
        skip_reason: "",
      },
      {
        device_id: "device-2",
        device_name: "BYOD Phone",
        risk_level: "high",
        finding_tags: ["no_primary_user"],
        action_type: "device_reassign_primary_user",
        action_label: "Assign primary user",
        action_reason: "Assign owner",
        requires_primary_user: true,
        primary_users: [],
        skip_reason: "",
      },
    ],
    groups: [
      {
        action_type: "device_sync",
        action_label: "Device sync",
        device_count: 1,
        device_ids: ["device-1"],
        device_names: ["Payroll Laptop"],
        requires_confirmation: false,
      },
    ],
    devices_requiring_primary_user: [
      {
        device_id: "device-2",
        device_name: "BYOD Phone",
        risk_level: "high",
        finding_tags: ["no_primary_user"],
        action_type: "device_reassign_primary_user",
        action_label: "Assign primary user",
        action_reason: "Assign owner",
        requires_primary_user: true,
        primary_users: [],
        skip_reason: "",
      },
    ],
    skipped_devices: [],
    destructive_device_count: 0,
    destructive_device_names: [],
    requires_destructive_confirmation: false,
    warnings: [],
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
    mockApi.previewAzureSecurityDeviceFixPlan.mockResolvedValue(buildFixPlan());
    mockApi.executeAzureSecurityDeviceFixPlan.mockResolvedValue({
      batch_id: "batch-1",
      status: "queued",
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      requested_at: "2026-04-03T02:05:00Z",
      started_at: null,
      completed_at: null,
      progress_current: 0,
      progress_total: 2,
      progress_message: "Queued",
      success_count: 0,
      failure_count: 0,
      results_ready: false,
      item_count: 2,
      destructive_device_count: 0,
      destructive_device_names: [],
      child_jobs: [],
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
    mockApi.getAzureSecurityDeviceActionBatch.mockResolvedValue({
      batch_id: "batch-1",
      status: "completed",
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      requested_at: "2026-04-03T02:05:00Z",
      started_at: "2026-04-03T02:05:05Z",
      completed_at: "2026-04-03T02:05:20Z",
      progress_current: 2,
      progress_total: 2,
      progress_message: "Completed",
      success_count: 2,
      failure_count: 0,
      results_ready: true,
      item_count: 2,
      destructive_device_count: 0,
      destructive_device_names: [],
      child_jobs: [
        {
          child_job_id: "job-1",
          action_type: "device_sync",
          action_label: "Device sync",
          device_ids: ["device-1"],
          device_names: ["Payroll Laptop"],
          status: "completed",
          progress_current: 1,
          progress_total: 1,
          success_count: 1,
          failure_count: 0,
          results_ready: true,
        },
        {
          child_job_id: "job-2",
          action_type: "device_reassign_primary_user",
          action_label: "Assign primary user",
          device_ids: ["device-2"],
          device_names: ["BYOD Phone"],
          status: "completed",
          progress_current: 1,
          progress_total: 1,
          success_count: 1,
          failure_count: 0,
          results_ready: true,
        },
      ],
      error: "",
    });
    mockApi.getAzureSecurityDeviceActionBatchResults.mockResolvedValue([
      {
        device_id: "device-1",
        device_name: "Payroll Laptop",
        action_type: "device_sync",
        action_label: "Device sync",
        child_job_id: "job-1",
        status: "completed",
        success: true,
        summary: "Sync queued",
        error: "",
        assignment_user_id: "",
        assignment_user_display_name: "",
      },
      {
        device_id: "device-2",
        device_name: "BYOD Phone",
        action_type: "device_reassign_primary_user",
        action_label: "Assign primary user",
        child_job_id: "job-2",
        status: "completed",
        success: true,
        summary: "Primary user updated",
        error: "",
        assignment_user_id: "user-1",
        assignment_user_display_name: "Ada Lovelace",
      },
    ]);
    mockApi.getAzureUsers.mockResolvedValue([
      {
        id: "user-1",
        display_name: "Ada Lovelace",
        object_type: "user",
        principal_name: "ada@example.com",
        mail: "ada@example.com",
        app_id: "",
        enabled: true,
        extra: {},
      },
    ]);
  });

  it("renders the device compliance lane with warnings and remediation controls", async () => {
    render(<AzureSecurityDeviceCompliancePage />);

    expect(await screen.findByRole("heading", { name: "Device Compliance Review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Bulk remediation" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Review queue" })).toBeInTheDocument();
    expect(screen.getByText("Device compliance cache data is older than 2 hours, so Intune posture may be stale.")).toBeInTheDocument();
    expect(screen.getAllByText("Recommended fix: Device sync").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Assign primary user" }).length).toBeGreaterThan(0);
  });

  it("queues an explicit bulk action from the existing toolbar", async () => {
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
        params: undefined,
      });
    });

    expect(await screen.findByRole("heading", { name: "Active device action job" })).toBeInTheDocument();
    expect(await screen.findByText("Queued device_sync for 1 device(s)")).toBeInTheDocument();
  });

  it("supports direct primary-user assignment from a device card", async () => {
    render(<AzureSecurityDeviceCompliancePage />);

    expect(await screen.findByRole("heading", { name: "Review queue" })).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Assign primary user" })[0]);
    fireEvent.change(screen.getByPlaceholderText("Search cached users by name, UPN, or mail..."), {
      target: { value: "Ada" },
    });

    expect(await screen.findByRole("button", { name: /Ada Lovelace/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Ada Lovelace/i }));
    fireEvent.click(screen.getByRole("button", { name: "Assign Payroll Laptop" }));

    await waitFor(() => {
      expect(mockApi.createAzureSecurityDeviceAction).toHaveBeenCalledWith({
        action_type: "device_reassign_primary_user",
        device_ids: ["device-1"],
        reason: "Assign a primary user from the Device Compliance Review lane.",
        confirm_device_count: undefined,
        confirm_device_names: undefined,
        params: {
          primary_user_id: "user-1",
          primary_user_display_name: "Ada Lovelace",
        },
      });
    });
  });

  it("previews and executes a smart remediation plan", async () => {
    render(<AzureSecurityDeviceCompliancePage />);

    expect(await screen.findByRole("heading", { name: "Review queue" })).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Select Payroll Laptop"));
    fireEvent.click(screen.getByLabelText("Select BYOD Phone"));
    fireEvent.change(screen.getByPlaceholderText("Reason for this action (optional but recommended)..."), {
      target: { value: "Nightly remediation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Fix selected" }));

    await waitFor(() => {
      expect(mockApi.previewAzureSecurityDeviceFixPlan).toHaveBeenCalledWith({ device_ids: ["device-1", "device-2"] });
    });

    expect(await screen.findByRole("heading", { name: "Smart fix preview" })).toBeInTheDocument();
    fireEvent.change(screen.getAllByPlaceholderText("Search cached users by name, UPN, or mail...")[0], {
      target: { value: "Ada" },
    });
    expect(await screen.findAllByRole("button", { name: /Ada Lovelace/i })).not.toHaveLength(0);
    fireEvent.click(screen.getAllByRole("button", { name: /Ada Lovelace/i })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Use selected user" }));
    fireEvent.click(screen.getByRole("button", { name: "Execute fix plan" }));

    await waitFor(() => {
      expect(mockApi.executeAzureSecurityDeviceFixPlan).toHaveBeenCalledWith({
        device_ids: ["device-1", "device-2"],
        reason: "Nightly remediation",
        assignment_map: { "device-2": "user-1" },
        confirm_device_count: undefined,
        confirm_device_names: undefined,
      });
    });

    expect(await screen.findByRole("heading", { name: "Active fix batch" })).toBeInTheDocument();
    expect(await screen.findByText("Primary user updated")).toBeInTheDocument();
    expect(screen.getByText("Assigned user: Ada Lovelace")).toBeInTheDocument();
  });
});
