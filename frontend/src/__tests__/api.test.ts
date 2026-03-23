import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "../lib/api.ts";

const logClientError = vi.fn();

vi.mock("../lib/errorLogging.ts", () => ({
  logClientError,
}));

// ---------------------------------------------------------------------------
// Mock fetch
// ---------------------------------------------------------------------------

const originalFetch = globalThis.fetch;

function mockFetch(response: unknown, status = 200) {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 400,
    status,
    json: () => Promise.resolve(response),
    text: () => Promise.resolve(JSON.stringify(response)),
    blob: () => Promise.resolve(new Blob()),
    headers: new Headers({ "content-type": "application/json" }),
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  logClientError.mockClear();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("api.getMetrics", () => {
  it("calls /api/metrics", async () => {
    const mockData = { headline: {}, weekly_volumes: [] };
    mockFetch(mockData);
    await api.getMetrics();
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/metrics");
  });

  it("passes date params as query string", async () => {
    mockFetch({});
    await api.getMetrics({ date_from: "2026-01-01", date_to: "2026-02-01" });
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("date_from=2026-01-01");
    expect(url).toContain("date_to=2026-02-01");
  });
});

describe("api.getTickets", () => {
  it("passes filters as query params", async () => {
    mockFetch({ tickets: [] });
    await api.getTickets({ status: "Open", priority: "High" });
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("status=Open");
    expect(url).toContain("priority=High");
  });

  it("skips empty params", async () => {
    mockFetch({ tickets: [] });
    await api.getTickets({ status: "" });
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).not.toContain("status");
  });
});

describe("api.getUsers", () => {
  it("calls /api/users", async () => {
    mockFetch([]);
    await api.getUsers();
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/users");
  });
});

describe("api POST methods", () => {
  it("sends POST body for chart data", async () => {
    mockFetch({ data: [], group_by: "status", metric: "count" });
    await api.getChartData({ group_by: "status", metric: "count" });
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/chart/data");
    expect(call[1].method).toBe("POST");
    const body = JSON.parse(call[1].body);
    expect(body.group_by).toBe("status");
  });

  it("sends correct body for bulkStatus", async () => {
    mockFetch([]);
    await api.bulkStatus(["OIT-1", "OIT-2"], "31");
    const body = JSON.parse(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body
    );
    expect(body.keys).toEqual(["OIT-1", "OIT-2"]);
    expect(body.transition_id).toBe("31");
  });

  it("sends correct body for refreshVisibleTickets", async () => {
    mockFetch({
      requested_count: 2,
      visible_count: 2,
      refreshed_count: 2,
      refreshed_keys: ["OIT-1", "OIT-2"],
      skipped_keys: [],
      missing_keys: [],
    });
    await api.refreshVisibleTickets(["OIT-1", "OIT-2"]);
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/tickets/refresh-visible");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({ keys: ["OIT-1", "OIT-2"] });
  });
});

describe("error handling", () => {
  it("throws on 4xx/5xx", async () => {
    mockFetch({ detail: "Not found" }, 404);
    await expect(api.getMetrics()).rejects.toThrow("failed (404)");
  });

  it("logs auth bootstrap failures and still returns null", async () => {
    mockFetch({ detail: "Server error" }, 500);
    await expect(api.getMe()).resolves.toBeNull();
    expect(logClientError).toHaveBeenCalledWith(
      "Auth bootstrap failed",
      expect.any(Error),
      { url: "/api/auth/me" },
    );
  });
});

describe("api.exportExcel", () => {
  it("returns URL string", () => {
    const url = api.exportExcel();
    expect(url).toBe("/api/export/excel");
  });

  it("returns Azure VM coverage export URLs", () => {
    expect(api.exportAzureVMCoverageCsv()).toBe("/api/azure/vms/coverage/export.csv");
    expect(api.exportAzureVMCoverageExcel()).toBe("/api/azure/vms/coverage/export.xlsx");
  });

  it("returns primary user export URLs with filters", () => {
    expect(
      api.exportUserAdminUsersCsv({
        search: "ada",
        status: "disabled",
        report_filter: "disabled_licensed",
        scope: "filtered",
      }),
    ).toContain("/api/user-admin/users/export.csv");
    expect(
      api.exportUserAdminUsersCsv({
        search: "ada",
        status: "disabled",
        report_filter: "disabled_licensed",
        scope: "filtered",
      }),
    ).toContain("report_filter=disabled_licensed");
    expect(api.exportUserAdminUsersExcel({ scope: "all" })).toContain("/api/user-admin/users/export.xlsx");
    expect(api.exportUserAdminUsersExcel({ scope: "all" })).toContain("scope=all");
  });
});

describe("azure api methods", () => {
  it("calls the Azure resource endpoint with query params", async () => {
    mockFetch({ resources: [], matched_count: 0, total_count: 0 });
    await api.getAzureResources({ search: "vm", location: "eastus" });
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("/api/azure/resources");
    expect(url).toContain("search=vm");
    expect(url).toContain("location=eastus");
  });

  it("posts Azure copilot questions", async () => {
    mockFetch({
      answer: "Use Advisor recommendations first.",
      model_used: "gpt-4o-mini",
      generated_at: "2026-03-17T18:00:00Z",
      citations: [],
    });
    await api.askAzureCostCopilot("Where can we save?");
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/azure/ai/cost-chat");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({ question: "Where can we save?" });
  });

  it("calls the Azure VM endpoint with query params", async () => {
    mockFetch({
      vms: [],
      matched_count: 0,
      total_count: 0,
      summary: { total_vms: 0, running_vms: 0, deallocated_vms: 0, distinct_sizes: 0 },
      by_size: [],
      by_state: [],
      reservation_data_available: false,
      reservation_error: null,
    });
    await api.getAzureVMs({ search: "wvd", state: "Running", size: "Standard_E2as_v4" });
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("/api/azure/vms");
    expect(url).toContain("search=wvd");
    expect(url).toContain("state=Running");
    expect(url).toContain("size=Standard_E2as_v4");
  });

  it("returns Azure VM excess export URLs", () => {
    expect(api.exportAzureVMExcessCsv()).toBe("/api/azure/vms/excess/export.csv");
    expect(api.exportAzureVMExcessExcel()).toBe("/api/azure/vms/excess/export.xlsx");
  });

  it("calls the Azure savings endpoints with query params", async () => {
    mockFetch({
      currency: "USD",
      total_opportunities: 1,
      quantified_opportunities: 1,
      quantified_monthly_savings: 12,
      quick_win_count: 1,
      quick_win_monthly_savings: 12,
      unquantified_opportunity_count: 0,
      by_category: [],
      by_opportunity_type: [],
      by_effort: [],
      by_risk: [],
      by_confidence: [],
      top_subscriptions: [],
      top_resource_groups: [],
    });
    await api.getAzureSavingsSummary();
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/azure/savings/summary");

    mockFetch([]);
    await api.getAzureSavingsOpportunities({ category: "storage", quantified_only: true });
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("/api/azure/savings/opportunities");
    expect(url).toContain("category=storage");
    expect(url).toContain("quantified_only=true");
  });

  it("returns Azure savings export URLs", () => {
    expect(api.exportAzureSavingsCsv({ category: "network" })).toContain("/api/azure/savings/export.csv");
    expect(api.exportAzureSavingsCsv({ category: "network" })).toContain("category=network");
    expect(api.exportAzureSavingsExcel({ quantified_only: true })).toContain("/api/azure/savings/export.xlsx");
    expect(api.exportAzureSavingsExcel({ quantified_only: true })).toContain("quantified_only=true");
  });

  it("calls user exit workflow endpoints", async () => {
    mockFetch({
      user_id: "user-1",
      user_display_name: "Ada Lovelace",
      user_principal_name: "ada@example.com",
      profile_key: "oasis",
      profile_label: "Oasis",
      scope_summary: "Hybrid exit workflow (Oasis)",
      on_prem_required: true,
      requires_on_prem_username_override: false,
      on_prem_sam_account_name: "adal",
      on_prem_distinguished_name: "",
      mailbox_expected: true,
      direct_license_count: 1,
      direct_licenses: [],
      managed_devices: [],
      manual_tasks: [],
      steps: [],
      warnings: [],
      active_workflow: null,
    });
    await api.getUserExitPreflight("user-1");
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/user-exit/users/user-1/preflight");

    mockFetch({
      workflow_id: "workflow-1",
      user_id: "user-1",
      user_display_name: "Ada Lovelace",
      user_principal_name: "ada@example.com",
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      status: "running",
      profile_key: "oasis",
      on_prem_required: true,
      requires_on_prem_username_override: false,
      on_prem_sam_account_name: "adal",
      on_prem_distinguished_name: "",
      created_at: "2026-03-19T00:00:00Z",
      started_at: null,
      completed_at: null,
      error: "",
      steps: [],
      manual_tasks: [],
    });
    await api.createUserExitWorkflow({
      user_id: "user-1",
      typed_upn_confirmation: "ada@example.com",
      on_prem_sam_account_name_override: "",
    });
    let call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/user-exit/workflows");
    expect(call[1].method).toBe("POST");

    mockFetch({
      workflow_id: "workflow-1",
      user_id: "user-1",
      user_display_name: "Ada Lovelace",
      user_principal_name: "ada@example.com",
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      status: "running",
      profile_key: "oasis",
      on_prem_required: true,
      requires_on_prem_username_override: false,
      on_prem_sam_account_name: "adal",
      on_prem_distinguished_name: "",
      created_at: "2026-03-19T00:00:00Z",
      started_at: null,
      completed_at: null,
      error: "",
      steps: [],
      manual_tasks: [],
    });
    await api.retryUserExitWorkflowStep("workflow-1", "step-1");
    call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/user-exit/workflows/workflow-1/retry-step");
    expect(JSON.parse(call[1].body)).toEqual({ step_id: "step-1" });

    mockFetch({
      workflow_id: "workflow-1",
      user_id: "user-1",
      user_display_name: "Ada Lovelace",
      user_principal_name: "ada@example.com",
      requested_by_email: "tech@example.com",
      requested_by_name: "Tech User",
      status: "completed",
      profile_key: "oasis",
      on_prem_required: true,
      requires_on_prem_username_override: false,
      on_prem_sam_account_name: "adal",
      on_prem_distinguished_name: "",
      created_at: "2026-03-19T00:00:00Z",
      started_at: null,
      completed_at: "2026-03-19T00:10:00Z",
      error: "",
      steps: [],
      manual_tasks: [],
    });
    await api.completeUserExitManualTask("workflow-1", "task-1", "done");
    call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/user-exit/workflows/workflow-1/manual-tasks/task-1/complete");
    expect(JSON.parse(call[1].body)).toEqual({ notes: "done" });
  });

  it("calls the Azure VM detail endpoint with the resource id", async () => {
    mockFetch({
      vm: {
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
      },
      associated_resources: [],
      cost: {
        lookback_days: 30,
        currency: "USD",
        cost_data_available: true,
        cost_error: null,
        total_cost: 100,
        vm_cost: 80,
        related_resource_cost: 20,
        priced_resource_count: 2,
      },
    });
    await api.getAzureVMDetail("/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1");
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("/api/azure/vms/detail");
    expect(url).toContain("resource_id=%2Fsubscriptions%2Fsub-1%2FresourceGroups%2Frg-prod%2Fproviders%2FMicrosoft.Compute%2FvirtualMachines%2Fvm-1");
  });

  it("starts an Azure VM cost export job", async () => {
    mockFetch({
      job_id: "job-123",
      status: "queued",
      recipient_email: "user@example.com",
      scope: "filtered",
      lookback_days: 30,
      filters: { search: "wvd", subscription_id: "sub-1" },
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
    await api.createAzureVMCostExportJob({
      scope: "filtered",
      lookback_days: 30,
      filters: { search: "wvd", subscription_id: "sub-1" },
    });
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/azure/vms/cost-export-jobs");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({
      scope: "filtered",
      lookback_days: 30,
      filters: { search: "wvd", subscription_id: "sub-1" },
    });
  });

  it("fetches Azure VM cost export job status", async () => {
    mockFetch({
      job_id: "job-123",
      status: "running",
      recipient_email: "user@example.com",
      scope: "all",
      lookback_days: 90,
      filters: {},
      requested_at: "2026-03-18T00:00:00Z",
      started_at: "2026-03-18T00:01:00Z",
      completed_at: null,
      progress_current: 2,
      progress_total: 5,
      progress_message: "Querying Azure",
      file_name: null,
      file_ready: false,
      error: null,
    });
    await api.getAzureVMCostExportJob("job-123");
    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toBe("/api/azure/vms/cost-export-jobs/job-123");
  });

  it("returns the Azure VM cost export download URL", () => {
    expect(api.downloadAzureVMCostExportJob("job-123")).toBe("/api/azure/vms/cost-export-jobs/job-123/download");
  });
});

describe("user admin api methods", () => {
  it("fetches user-admin capabilities", async () => {
    mockFetch({
      can_manage_users: true,
      enabled_providers: { entra: true, mailbox: false, device_management: true },
      supported_actions: ["disable_sign_in"],
      license_catalog: [],
      group_catalog: [],
      role_catalog: [],
      conditional_access_exception_groups: [],
    });
    await api.getUserAdminCapabilities();
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/user-admin/capabilities");
  });

  it("starts a user-admin job", async () => {
    mockFetch({
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
    await api.createUserAdminJob({
      action_type: "disable_sign_in",
      target_user_ids: ["user-1"],
      params: {},
    });
    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/user-admin/jobs");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({
      action_type: "disable_sign_in",
      target_user_ids: ["user-1"],
      params: {},
    });
  });

  it("fetches user-admin job status and results", async () => {
    mockFetch({
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
    await api.getUserAdminJob("job-123");
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/user-admin/jobs/job-123");

    mockFetch([
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
    await api.getUserAdminJobResults("job-123");
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/user-admin/jobs/job-123/results");
  });
});
