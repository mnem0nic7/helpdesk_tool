import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "../lib/api.ts";

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
