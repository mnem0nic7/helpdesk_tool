import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import UsersPage from "../pages/UsersPage.tsx";
import AzureUsersPage from "../pages/AzureUsersPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getMe: vi.fn(),
    getAzureUsers: vi.fn(),
    getUserAdminCapabilities: vi.fn(),
    getUserAdminUserDetail: vi.fn(),
    getUserAdminUserGroups: vi.fn(),
    getUserAdminUserLicenses: vi.fn(),
    getUserAdminUserRoles: vi.fn(),
    getUserAdminUserMailbox: vi.fn(),
    getUserAdminUserDevices: vi.fn(),
    getUserAdminUserActivity: vi.fn(),
    getUserAdminAudit: vi.fn(),
    createUserAdminJob: vi.fn(),
    getUserAdminJob: vi.fn(),
    getUserAdminJobResults: vi.fn(),
    exportUserAdminUsersCsv: vi.fn(),
    exportUserAdminUsersExcel: vi.fn(),
    getUserExitPreflight: vi.fn(),
    createUserExitWorkflow: vi.fn(),
    getUserExitWorkflow: vi.fn(),
    retryUserExitWorkflowStep: vi.fn(),
    completeUserExitManualTask: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

const directoryUsers = [
  {
    id: "user-1",
    display_name: "Ada Lovelace",
    object_type: "user" as const,
    principal_name: "ada@contoso.com",
    mail: "ada@contoso.com",
    app_id: "",
    enabled: true,
    extra: {
      user_type: "Member",
      on_prem_domain: "MOVEDOCS",
      on_prem_netbios: "MOVEDOCS",
      on_prem_sync: "true",
      department: "Infrastructure",
      job_title: "Systems Engineer",
      company_name: "MoveDocs",
      office_location: "Los Angeles",
      created_datetime: "2024-01-15T00:00:00Z",
      last_password_change: "2026-03-10T00:00:00Z",
      proxy_addresses: "SMTP:ada@contoso.com",
      mobile_phone: "555-0100",
      business_phones: "555-0110",
      city: "Los Angeles",
      country: "USA",
      is_licensed: "true",
      license_count: "2",
      sku_part_numbers: "M365_BUSINESS_PREMIUM, EMS",
      last_interactive_utc: "2026-03-15T16:00:00Z",
      last_interactive_local: "Mar 15, 2026, 9:00 AM",
      last_noninteractive_utc: "2026-03-16T16:00:00Z",
      last_noninteractive_local: "Mar 16, 2026, 9:00 AM",
      last_successful_utc: "2026-03-17T16:00:00Z",
      last_successful_local: "Mar 17, 2026, 9:00 AM",
      on_prem_sam_account_name: "ada.l",
      on_prem_distinguished_name: "CN=Ada Lovelace,OU=Users,DC=movedocs,DC=local",
    },
  },
  {
    id: "user-2",
    display_name: "Grace Hopper",
    object_type: "user" as const,
    principal_name: "grace_external#EXT#@contoso.com",
    mail: "grace@example.com",
    app_id: "",
    enabled: false,
    extra: {
      user_type: "Guest",
      on_prem_domain: "",
      on_prem_netbios: "",
      on_prem_sync: "false",
      department: "Security",
      job_title: "Consultant",
      company_name: "Partner Co",
      office_location: "Remote",
      created_datetime: "2023-05-01T00:00:00Z",
      last_password_change: "2025-12-12T00:00:00Z",
      proxy_addresses: "SMTP:grace@example.com",
      mobile_phone: "",
      business_phones: "",
      city: "New York",
      country: "USA",
      is_licensed: "true",
      license_count: "1",
      sku_part_numbers: "M365_BUSINESS_BASIC",
      last_interactive_utc: "",
      last_interactive_local: "",
      last_noninteractive_utc: "",
      last_noninteractive_local: "",
      last_successful_utc: "",
      last_successful_local: "",
      on_prem_sam_account_name: "",
      on_prem_distinguished_name: "",
    },
  },
];

let originalIntersectionObserver: typeof IntersectionObserver | undefined;

beforeAll(() => {
  originalIntersectionObserver = globalThis.IntersectionObserver;
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

afterAll(() => {
  globalThis.IntersectionObserver = originalIntersectionObserver as typeof IntersectionObserver;
});

describe("Users directory pages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      writable: true,
      value: 1440,
    });

    mockApi.getMe.mockResolvedValue({
      email: "tech@example.com",
      name: "Tech User",
      is_admin: true,
      can_manage_users: true,
    });

    mockApi.getAzureUsers.mockImplementation(async (search = "") => {
      const normalizedSearch = search.trim().toLowerCase();
      if (!normalizedSearch) return directoryUsers;
      return directoryUsers.filter((user) =>
        [user.display_name, user.mail, user.principal_name, user.extra.department, user.extra.job_title]
          .join(" ")
          .toLowerCase()
          .includes(normalizedSearch),
      );
    });

    mockApi.getUserAdminCapabilities.mockResolvedValue({
      can_manage_users: true,
      enabled_providers: { entra: true, mailbox: false, device_management: true },
      supported_actions: [
        "disable_sign_in",
        "enable_sign_in",
        "reset_password",
        "revoke_sessions",
        "reset_mfa",
        "update_usage_location",
        "update_profile",
        "set_manager",
        "add_group_membership",
        "remove_group_membership",
        "assign_license",
        "remove_license",
        "add_directory_role",
        "remove_directory_role",
        "device_sync",
        "device_retire",
        "device_wipe",
        "device_remote_lock",
        "device_reassign_primary_user",
      ],
      license_catalog: [{ sku_id: "sku-1", sku_part_number: "M365_BUSINESS_PREMIUM", display_name: "M365 Business Premium" }],
      group_catalog: [{ id: "group-1", display_name: "CA Exceptions", principal_name: "", mail: "" }],
      role_catalog: [{ id: "role-1", display_name: "User Administrator", principal_name: "", mail: "" }],
      conditional_access_exception_groups: [{ id: "group-1", display_name: "CA Exceptions", principal_name: "", mail: "" }],
    });

    mockApi.getUserAdminUserDetail.mockResolvedValue({
      id: "user-1",
      display_name: "Ada Lovelace",
      principal_name: "ada@contoso.com",
      mail: "ada@contoso.com",
      enabled: true,
      user_type: "Member",
      department: "Infrastructure",
      job_title: "Systems Engineer",
      office_location: "Los Angeles",
      company_name: "MoveDocs",
      city: "Los Angeles",
      country: "USA",
      mobile_phone: "555-0100",
      business_phones: ["555-0110"],
      created_datetime: "2024-01-15T00:00:00Z",
      last_password_change: "2026-03-10T00:00:00Z",
      on_prem_sync: true,
      on_prem_domain: "MOVEDOCS",
      on_prem_netbios: "MOVEDOCS",
      on_prem_sam_account_name: "ada.l",
      on_prem_distinguished_name: "CN=Ada Lovelace,OU=Users,DC=movedocs,DC=local",
      usage_location: "US",
      employee_id: "",
      employee_type: "",
      preferred_language: "en-US",
      proxy_addresses: ["SMTP:ada@contoso.com"],
      is_licensed: true,
      license_count: 2,
      sku_part_numbers: ["M365_BUSINESS_PREMIUM", "EMS"],
      last_interactive_utc: "2026-03-15T16:00:00Z",
      last_interactive_local: "Mar 15, 2026, 9:00 AM",
      last_noninteractive_utc: "2026-03-16T16:00:00Z",
      last_noninteractive_local: "Mar 16, 2026, 9:00 AM",
      last_successful_utc: "2026-03-17T16:00:00Z",
      last_successful_local: "Mar 17, 2026, 9:00 AM",
      manager: null,
      source_directory: "MOVEDOCS",
    });
    mockApi.getUserAdminUserGroups.mockResolvedValue([
      {
        id: "group-1",
        display_name: "CA Exceptions",
        mail: "",
        security_enabled: true,
        group_types: [],
        object_type: "group",
      },
    ]);
    mockApi.getUserAdminUserLicenses.mockResolvedValue([
      {
        sku_id: "sku-1",
        sku_part_number: "M365_BUSINESS_PREMIUM",
        display_name: "M365 Business Premium",
        state: "active",
        disabled_plans: [],
        assigned_by_group: false,
      },
    ]);
    mockApi.getUserAdminUserRoles.mockResolvedValue([
      {
        id: "role-1",
        display_name: "User Administrator",
        description: "Manage users",
        assignment_type: "direct",
      },
    ]);
    mockApi.getUserAdminUserMailbox.mockResolvedValue({
      primary_address: "ada@contoso.com",
      aliases: ["ada@alias.contoso.com"],
      forwarding_enabled: false,
      forwarding_address: "",
      mailbox_type: "user",
      delegate_delivery_mode: "",
      delegates: [],
      automatic_replies_status: "disabled",
      provider_enabled: true,
      management_supported: false,
      note: "Mailbox management will unlock when the Exchange provider adapter is configured.",
    });
    mockApi.getUserAdminUserDevices.mockResolvedValue([
      {
        id: "device-1",
        device_name: "Ada-Laptop",
        operating_system: "Windows",
        operating_system_version: "11",
        compliance_state: "compliant",
        management_state: "managed",
        owner_type: "company",
        enrollment_type: "windowsAzureADJoin",
        last_sync_date_time: "2026-03-19T00:00:00Z",
        azure_ad_device_id: "aad-device-1",
        primary_users: [],
      },
    ]);
    mockApi.getUserAdminUserActivity.mockResolvedValue([
      {
        audit_id: "audit-1",
        job_id: "job-1",
        actor_email: "tech@example.com",
        actor_name: "Tech User",
        target_user_id: "user-1",
        target_display_name: "Ada Lovelace",
        provider: "entra",
        action_type: "revoke_sessions",
        params_summary: {},
        before_summary: {},
        after_summary: { sessions_revoked: true },
        status: "success",
        error: "",
        created_at: "2026-03-19T00:00:00Z",
      },
    ]);
    mockApi.getUserAdminAudit.mockResolvedValue([
      {
        audit_id: "audit-global-1",
        job_id: "job-global-1",
        actor_email: "tech@example.com",
        actor_name: "Tech User",
        target_user_id: "user-1",
        target_display_name: "Ada Lovelace",
        provider: "entra",
        action_type: "disable_sign_in",
        params_summary: {},
        before_summary: { enabled: true },
        after_summary: { enabled: false },
        status: "success",
        error: "",
        created_at: "2026-03-19T01:00:00Z",
      },
    ]);
    mockApi.createUserAdminJob.mockResolvedValue({
      job_id: "job-123",
      status: "queued",
      action_type: "disable_sign_in",
      provider: "entra",
      target_user_ids: ["user-1"],
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      requested_at: "2026-03-19T00:00:00Z",
      started_at: null,
      completed_at: null,
      progress_current: 0,
      progress_total: 1,
      progress_message: "Queued",
      success_count: 0,
      failure_count: 0,
      results_ready: false,
      error: "",
      one_time_results_available: false,
    });
    mockApi.getUserAdminJob.mockResolvedValue({
      job_id: "job-123",
      status: "completed",
      action_type: "disable_sign_in",
      provider: "entra",
      target_user_ids: ["user-1"],
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      requested_at: "2026-03-19T00:00:00Z",
      started_at: "2026-03-19T00:01:00Z",
      completed_at: "2026-03-19T00:02:00Z",
      progress_current: 1,
      progress_total: 1,
      progress_message: "Completed",
      success_count: 1,
      failure_count: 0,
      results_ready: true,
      error: "",
      one_time_results_available: false,
    });
    mockApi.getUserAdminJobResults.mockResolvedValue([
      {
        target_user_id: "user-1",
        target_display_name: "Ada Lovelace",
        provider: "entra",
        success: true,
        summary: "Disabled sign-in",
        error: "",
        before_summary: { enabled: true },
        after_summary: { enabled: false },
        one_time_secret: null,
      },
    ]);
    mockApi.exportUserAdminUsersCsv.mockImplementation((params?: { scope?: string }) =>
      `/api/user-admin/users/export.csv?scope=${params?.scope || "filtered"}`,
    );
    mockApi.exportUserAdminUsersExcel.mockImplementation((params?: { scope?: string }) =>
      `/api/user-admin/users/export.xlsx?scope=${params?.scope || "filtered"}`,
    );
    mockApi.getUserExitPreflight.mockResolvedValue({
      user_id: "user-1",
      user_display_name: "Ada Lovelace",
      user_principal_name: "ada@contoso.com",
      profile_key: "oasis",
      profile_label: "Oasis",
      scope_summary: "Hybrid exit workflow (Oasis)",
      on_prem_required: true,
      requires_on_prem_username_override: false,
      on_prem_sam_account_name: "ada.l",
      on_prem_distinguished_name: "CN=Ada Lovelace,OU=Users,DC=movedocs,DC=local",
      mailbox_expected: true,
      direct_license_count: 1,
      direct_licenses: [
        {
          sku_id: "sku-1",
          sku_part_number: "M365_BUSINESS_PREMIUM",
          display_name: "M365 Business Premium",
          state: "active",
          disabled_plans: [],
          assigned_by_group: false,
        },
      ],
      managed_devices: [
        {
          id: "device-1",
          device_name: "Ada-Laptop",
          operating_system: "Windows",
          operating_system_version: "11",
          compliance_state: "compliant",
          management_state: "managed",
          owner_type: "company",
          enrollment_type: "windowsAzureADJoin",
          last_sync_date_time: "2026-03-19T00:00:00Z",
          azure_ad_device_id: "aad-device-1",
          primary_users: [],
        },
      ],
      manual_tasks: [
        {
          task_id: "task-1",
          label: "RingCentral",
          status: "pending",
          notes: "",
          completed_at: null,
          completed_by_email: "",
          completed_by_name: "",
        },
      ],
      steps: [
        { step_key: "disable_sign_in", label: "Disable Entra Sign-In", provider: "entra", will_run: true, reason: "" },
        { step_key: "exit_on_prem_deprovision", label: "Run On-Prem AD Deprovisioning", provider: "windows_agent", will_run: true, reason: "" },
      ],
      warnings: [],
      active_workflow: null,
    });
    const pendingExitWorkflow = {
      workflow_id: "workflow-1",
      user_id: "user-1",
      user_display_name: "Ada Lovelace",
      user_principal_name: "ada@contoso.com",
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      status: "awaiting_manual",
      profile_key: "oasis",
      on_prem_required: true,
      requires_on_prem_username_override: false,
      on_prem_sam_account_name: "ada.l",
      on_prem_distinguished_name: "CN=Ada Lovelace,OU=Users,DC=movedocs,DC=local",
      created_at: "2026-03-19T00:00:00Z",
      started_at: "2026-03-19T00:01:00Z",
      completed_at: null,
      error: "",
      steps: [
        {
          step_id: "step-1",
          step_key: "disable_sign_in",
          label: "Disable Entra Sign-In",
          provider: "entra",
          status: "completed",
          order_index: 1,
          profile_key: "",
          summary: "Disabled sign-in",
          error: "",
          before_summary: {},
          after_summary: {},
          created_at: "2026-03-19T00:00:00Z",
          started_at: "2026-03-19T00:01:00Z",
          completed_at: "2026-03-19T00:02:00Z",
          retry_count: 0,
        },
      ],
      manual_tasks: [
        {
          task_id: "task-1",
          label: "RingCentral",
          status: "pending",
          notes: "",
          completed_at: null,
          completed_by_email: "",
          completed_by_name: "",
        },
      ],
    };
    mockApi.createUserExitWorkflow.mockResolvedValue(pendingExitWorkflow);
    mockApi.getUserExitWorkflow.mockResolvedValue(pendingExitWorkflow);
    mockApi.retryUserExitWorkflowStep.mockResolvedValue({
      workflow_id: "workflow-1",
      user_id: "user-1",
      user_display_name: "Ada Lovelace",
      user_principal_name: "ada@contoso.com",
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      status: "running",
      profile_key: "oasis",
      on_prem_required: true,
      requires_on_prem_username_override: false,
      on_prem_sam_account_name: "ada.l",
      on_prem_distinguished_name: "CN=Ada Lovelace,OU=Users,DC=movedocs,DC=local",
      created_at: "2026-03-19T00:00:00Z",
      started_at: "2026-03-19T00:01:00Z",
      completed_at: null,
      error: "",
      steps: [],
      manual_tasks: [],
    });
    mockApi.completeUserExitManualTask.mockResolvedValue({
      workflow_id: "workflow-1",
      user_id: "user-1",
      user_display_name: "Ada Lovelace",
      user_principal_name: "ada@contoso.com",
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      status: "completed",
      profile_key: "oasis",
      on_prem_required: true,
      requires_on_prem_username_override: false,
      on_prem_sam_account_name: "ada.l",
      on_prem_distinguished_name: "CN=Ada Lovelace,OU=Users,DC=movedocs,DC=local",
      created_at: "2026-03-19T00:00:00Z",
      started_at: "2026-03-19T00:01:00Z",
      completed_at: "2026-03-19T00:10:00Z",
      error: "",
      steps: [],
      manual_tasks: [
        {
          task_id: "task-1",
          label: "RingCentral",
          status: "completed",
          notes: "Handled",
          completed_at: "2026-03-19T00:10:00Z",
          completed_by_email: "tech@example.com",
          completed_by_name: "Tech User",
        },
      ],
    });
  });

  it("renders the primary users workspace with bulk actions, confirm flow, and job progress", async () => {
    const user = userEvent.setup();

    render(<UsersPage />);

    expect(await screen.findByRole("heading", { name: "Users" })).toBeInTheDocument();
    expect(screen.getByText(/admin workspace/i)).toBeInTheDocument();
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Licensed")).toBeInTheDocument();
    expect(screen.getByText("No Success 30d")).toBeInTheDocument();
    expect(screen.getByText("Recent Activity")).toBeInTheDocument();
    expect(screen.getByText("Bulk Actions")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Export Filtered CSV" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disabled + Licensed" })).toBeInTheDocument();

    await user.click(screen.getByLabelText("Select Ada Lovelace"));
    expect(screen.getByText("1 selected. Bulk actions are the fastest path for identity admin work on it-app.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Review Bulk Action" }));

    expect(await screen.findByRole("heading", { name: /Disable Sign-In for 1 user/i })).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Type CONFIRM to continue/i), "CONFIRM");
    await user.click(screen.getByRole("button", { name: /Queue Disable Sign-In/i }));

    await waitFor(() => {
      expect(mockApi.createUserAdminJob).toHaveBeenCalledWith({
        action_type: "disable_sign_in",
        target_user_ids: ["user-1"],
        params: {},
      });
    });

    expect(await screen.findByText("Latest Job")).toBeInTheDocument();
    expect(await screen.findByText("Disabled sign-in")).toBeInTheDocument();
  });

  it("renders the primary drawer tabs and live data sections", async () => {
    const user = userEvent.setup();

    render(<UsersPage />);

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    await user.click(screen.getByText("Ada Lovelace"));

    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Access" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Groups" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Licenses" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Roles" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mailbox" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Devices" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activity" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exit" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Access" }));
    expect(await screen.findByRole("button", { name: "Disable User" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset Password" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revoke Sessions" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Devices" }));
    expect(await screen.findByText("Ada-Laptop")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Mailbox" }));
    expect(await screen.findByText(/Mailbox management will unlock/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Exit" }));
    expect(await screen.findByText("Start Exit Workflow")).toBeInTheDocument();
    expect(screen.getByText("Hybrid exit workflow (Oasis)")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("ada@contoso.com"), "ada@contoso.com");
    await user.click(screen.getByRole("button", { name: "Start Exit Workflow" }));

    await waitFor(() => {
      expect(mockApi.createUserExitWorkflow).toHaveBeenCalledWith({
        user_id: "user-1",
        typed_upn_confirmation: "ada@contoso.com",
        on_prem_sam_account_name_override: "",
      });
    });

    expect(await screen.findByText("Workflow Timeline")).toBeInTheDocument();
    expect(screen.getByText("Manual Checklist")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mark Complete" })).toBeInTheDocument();
  });

  it("renders the shared Azure directory view without the primary admin workspace", async () => {
    const user = userEvent.setup();

    render(<AzureUsersPage />);

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.queryByText("Bulk Actions")).not.toBeInTheDocument();
    expect(screen.queryByText("Recent Activity")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Export Filtered CSV" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Guests" }));

    await waitFor(() => {
      expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Grace Hopper")).toBeInTheDocument();

    await user.click(screen.getByText("Grace Hopper"));

    expect(await screen.findByRole("heading", { name: "Grace Hopper" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Overview" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disable User" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Exit" })).not.toBeInTheDocument();
  });
});
