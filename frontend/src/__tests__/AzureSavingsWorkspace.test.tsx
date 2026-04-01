import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../App.tsx";
import AzureCostPage from "../pages/AzureCostPage.tsx";
import AzureComputeOptimizationPage from "../pages/AzureComputeOptimizationPage.tsx";
import AzureStoragePage from "../pages/AzureStoragePage.tsx";
import AzureResourcesPage from "../pages/AzureResourcesPage.tsx";
import AzureCopilotPage from "../pages/AzureCopilotPage.tsx";
import AzureSavingsPage from "../pages/AzureSavingsPage.tsx";
import { render } from "../test-utils.tsx";

const baseOpportunities = [
  {
    id: "opp-disk",
    category: "storage" as const,
    opportunity_type: "unattached_managed_disk",
    source: "heuristic" as const,
    title: "Review unattached managed disk disk-1",
    summary: "Disk is unattached and still costing money.",
    subscription_id: "sub-1",
    subscription_name: "Prod",
    resource_group: "rg-prod",
    location: "eastus",
    resource_id: "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/disks/disk-1",
    resource_name: "disk-1",
    resource_type: "Microsoft.Compute/disks",
    current_monthly_cost: 12,
    estimated_monthly_savings: 12,
    currency: "USD",
    quantified: true,
    estimate_basis: "Amortized disk cost normalized to a 30-day monthly proxy.",
    effort: "low" as const,
    risk: "low" as const,
    confidence: "high" as const,
    recommended_steps: ["Confirm the disk is no longer needed.", "Delete or reattach it."],
    evidence: [{ label: "Disk state", value: "Unattached" }],
    portal_url: "https://portal.azure.com/#resource/disk-1",
    follow_up_route: "/storage",
  },
  {
    id: "opp-snapshot",
    category: "storage" as const,
    opportunity_type: "stale_snapshot",
    source: "heuristic" as const,
    title: "Review stale snapshot snap-1",
    summary: "Snapshot is older than the stale threshold.",
    subscription_id: "sub-1",
    subscription_name: "Prod",
    resource_group: "rg-prod",
    location: "eastus",
    resource_id: "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/snapshots/snap-1",
    resource_name: "snap-1",
    resource_type: "Microsoft.Compute/snapshots",
    current_monthly_cost: 4,
    estimated_monthly_savings: 4,
    currency: "USD",
    quantified: true,
    estimate_basis: "Amortized snapshot cost normalized to a 30-day monthly proxy.",
    effort: "low" as const,
    risk: "medium" as const,
    confidence: "high" as const,
    recommended_steps: ["Validate retention requirements.", "Delete stale snapshots."],
    evidence: [{ label: "Age", value: "75 days" }],
    portal_url: "https://portal.azure.com/#resource/snap-1",
    follow_up_route: "/storage",
  },
  {
    id: "opp-idle-vm",
    category: "compute" as const,
    opportunity_type: "idle_vm_attached_cost",
    source: "heuristic" as const,
    title: "Clean up attached costs for idle VM vm-1",
    summary: "Stopped VM still has billed attached resources.",
    subscription_id: "sub-1",
    subscription_name: "Prod",
    resource_group: "rg-prod",
    location: "eastus",
    resource_id: "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
    resource_name: "vm-1",
    resource_type: "Microsoft.Compute/virtualMachines",
    current_monthly_cost: 20,
    estimated_monthly_savings: 20,
    currency: "USD",
    quantified: true,
    estimate_basis: "Amortized attached-resource cost normalized to a 30-day monthly proxy.",
    effort: "low" as const,
    risk: "medium" as const,
    confidence: "high" as const,
    recommended_steps: ["Confirm the VM is no longer needed.", "Delete billed attachments."],
    evidence: [{ label: "Power state", value: "Deallocated" }],
    portal_url: "https://portal.azure.com/#resource/vm-1",
    follow_up_route: "/compute",
  },
  {
    id: "opp-pip",
    category: "network" as const,
    opportunity_type: "unattached_public_ip",
    source: "heuristic" as const,
    title: "Release unattached public IP pip-1",
    summary: "Public IP is not referenced by a VM or NIC.",
    subscription_id: "sub-1",
    subscription_name: "Prod",
    resource_group: "rg-prod",
    location: "eastus",
    resource_id: "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/publicIPAddresses/pip-1",
    resource_name: "pip-1",
    resource_type: "Microsoft.Network/publicIPAddresses",
    current_monthly_cost: 5,
    estimated_monthly_savings: 5,
    currency: "USD",
    quantified: true,
    estimate_basis: "Amortized public IP cost normalized to a 30-day monthly proxy.",
    effort: "low" as const,
    risk: "low" as const,
    confidence: "high" as const,
    recommended_steps: ["Release the IP if it is no longer needed."],
    evidence: [{ label: "Reference status", value: "Unused" }],
    portal_url: "https://portal.azure.com/#resource/pip-1",
    follow_up_route: "/resources",
  },
  {
    id: "opp-reservation",
    category: "commitment" as const,
    opportunity_type: "reservation_coverage_gap",
    source: "heuristic" as const,
    title: "Increase reservation coverage for Standard_D4s_v5 in eastus",
    summary: "Running VM demand exceeds current reservation coverage.",
    subscription_id: "",
    subscription_name: "",
    resource_group: "",
    location: "eastus",
    resource_id: "",
    resource_name: "Standard_D4s_v5 (eastus)",
    resource_type: "Microsoft.Capacity/reservations",
    current_monthly_cost: null,
    estimated_monthly_savings: null,
    currency: "USD",
    quantified: false,
    estimate_basis: "Reservation coverage mismatch from cached VM inventory and reservation counts.",
    effort: "medium" as const,
    risk: "low" as const,
    confidence: "medium" as const,
    recommended_steps: ["Validate stable demand.", "Review reservation options."],
    evidence: [{ label: "Coverage delta", value: "1" }],
    portal_url: "https://portal.azure.com/",
    follow_up_route: "/compute",
  },
];

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureSavingsSummary: vi.fn(),
    getAzureSavingsOpportunities: vi.fn(),
    exportAzureSavingsCsv: vi.fn((params?: Record<string, unknown>) => `/api/azure/savings/export.csv?${new URLSearchParams(Object.entries(params ?? {}).map(([k, v]) => [k, String(v)])).toString()}`),
    exportAzureSavingsExcel: vi.fn((params?: Record<string, unknown>) => `/api/azure/savings/export.xlsx?${new URLSearchParams(Object.entries(params ?? {}).map(([k, v]) => [k, String(v)])).toString()}`),
    getAzureRecommendationsSummary: vi.fn(),
    getAzureRecommendations: vi.fn(),
    getAzureRecommendation: vi.fn(),
    getAzureRecommendationActionContract: vi.fn(),
    getAzureRecommendationHistory: vi.fn(),
    dismissAzureRecommendation: vi.fn(),
    reopenAzureRecommendation: vi.fn(),
    updateAzureRecommendationActionState: vi.fn(),
    createAzureRecommendationTicket: vi.fn(),
    sendAzureRecommendationAlert: vi.fn(),
    runAzureRecommendationSafeScript: vi.fn(),
    exportAzureRecommendationsCsv: vi.fn((params?: Record<string, unknown>) => `/api/azure/recommendations/export.csv?${new URLSearchParams(Object.entries(params ?? {}).map(([k, v]) => [k, String(v)])).toString()}`),
    exportAzureRecommendationsExcel: vi.fn((params?: Record<string, unknown>) => `/api/azure/recommendations/export.xlsx?${new URLSearchParams(Object.entries(params ?? {}).map(([k, v]) => [k, String(v)])).toString()}`),
    getAzureCostSummary: vi.fn(),
    getAzureCostTrend: vi.fn(),
    getAzureCostBreakdown: vi.fn(),
    getAzureAdvisor: vi.fn(),
    getAzureComputeOptimization: vi.fn(),
    getAzureStorage: vi.fn(),
    getAzureResources: vi.fn(),
    getAzureAIModels: vi.fn(),
    askAzureCostCopilot: vi.fn(),
    getMe: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

vi.mock("../lib/deployVersion.ts", () => ({
  hasNewFrontendBuild: vi.fn(async () => false),
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

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return rtlRender(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

function filterOpportunities(params?: Record<string, unknown>) {
  const source = [...baseOpportunities];
  return source.filter((item) => {
    if (params?.category && item.category !== params.category) return false;
    if (params?.opportunity_type && item.opportunity_type !== params.opportunity_type) return false;
    if (params?.subscription_id && item.subscription_id !== params.subscription_id) return false;
    if (params?.resource_group && item.resource_group !== params.resource_group) return false;
    if (params?.effort && item.effort !== params.effort) return false;
    if (params?.risk && item.risk !== params.risk) return false;
    if (params?.confidence && item.confidence !== params.confidence) return false;
    if (params?.quantified_only && !item.quantified) return false;
    if (params?.search) {
      const needle = String(params.search).toLowerCase();
      const haystack = [item.title, item.summary, item.resource_name, item.resource_group, item.subscription_name].join(" ").toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  document.documentElement.dataset.siteHostname = "azure.movedocs.com";
  window.history.replaceState({}, "", "/");

  mockApi.getMe.mockResolvedValue({
    email: "user@example.com",
    name: "Azure User",
    is_admin: true,
    can_manage_users: true,
  });
  mockApi.getAzureSavingsSummary.mockResolvedValue({
    currency: "USD",
    total_opportunities: 5,
    quantified_opportunities: 4,
    quantified_monthly_savings: 41,
    quick_win_count: 3,
    quick_win_monthly_savings: 17,
    unquantified_opportunity_count: 1,
    by_category: [
      { label: "compute", count: 1, estimated_monthly_savings: 20 },
      { label: "storage", count: 2, estimated_monthly_savings: 16 },
      { label: "network", count: 1, estimated_monthly_savings: 5 },
      { label: "commitment", count: 1, estimated_monthly_savings: 0 },
    ],
    by_opportunity_type: [],
    by_effort: [{ label: "low", count: 4 }],
    by_risk: [{ label: "low", count: 2 }, { label: "medium", count: 3 }],
    by_confidence: [{ label: "high", count: 4 }, { label: "medium", count: 1 }],
    top_subscriptions: [{ label: "Prod", count: 4, estimated_monthly_savings: 41 }],
    top_resource_groups: [{ label: "Prod / rg-prod", count: 4, estimated_monthly_savings: 41 }],
  });
  mockApi.getAzureSavingsOpportunities.mockImplementation(async (params?: Record<string, unknown>) => filterOpportunities(params));
  mockApi.getAzureRecommendationsSummary.mockResolvedValue({
    currency: "USD",
    total_opportunities: 5,
    quantified_opportunities: 4,
    quantified_monthly_savings: 41,
    quick_win_count: 3,
    quick_win_monthly_savings: 17,
    unquantified_opportunity_count: 1,
    by_category: [
      { label: "compute", count: 1, estimated_monthly_savings: 20 },
      { label: "storage", count: 2, estimated_monthly_savings: 16 },
      { label: "network", count: 1, estimated_monthly_savings: 5 },
      { label: "commitment", count: 1, estimated_monthly_savings: 0 },
    ],
    by_opportunity_type: [],
    by_effort: [{ label: "low", count: 4 }],
    by_risk: [{ label: "low", count: 2 }, { label: "medium", count: 3 }],
    by_confidence: [{ label: "high", count: 4 }, { label: "medium", count: 1 }],
    top_subscriptions: [{ label: "Prod", count: 4, estimated_monthly_savings: 41 }],
    top_resource_groups: [{ label: "Prod / rg-prod", count: 4, estimated_monthly_savings: 41 }],
  });
  mockApi.getAzureRecommendations.mockImplementation(async (params?: Record<string, unknown>) => filterOpportunities(params));
  mockApi.getAzureRecommendation.mockImplementation(async (recommendationId: string) => {
    const match = baseOpportunities.find((item) => item.id === recommendationId);
    if (!match) throw new Error("Not found");
    return { ...match, lifecycle_status: "open", action_state: "none", dismissed_reason: "" };
  });
  mockApi.getAzureRecommendationActionContract.mockImplementation(async (recommendationId: string) => ({
    recommendation_id: recommendationId,
    lifecycle_status: "open",
    current_action_state: "none",
    generated_at: "2026-03-23T12:00:00+00:00",
    actions: [
      {
        action_type: "create_ticket",
        label: "Create Jira ticket",
        description: "Create a Jira follow-up for the recommendation and persist the linked workflow state.",
        category: "jira",
        status: "available",
        can_execute: true,
        requires_admin: true,
        repeatable: false,
        pending_action_state: "ticket_pending",
        completed_action_state: "ticket_created",
        current_action_state: "none",
        blocked_reason: "",
        note_placeholder: "Add an operator note for the Jira follow-up.",
        metadata_fields: [],
        latest_event: {},
      },
      {
        action_type: "send_alert",
        label: "Send Teams alert",
        description: "Send a Teams or operator-facing alert using the existing alert plumbing and persist the alert workflow state.",
        category: "teams",
        status: "available",
        can_execute: true,
        requires_admin: true,
        repeatable: true,
        pending_action_state: "alert_pending",
        completed_action_state: "alert_sent",
        current_action_state: "none",
        blocked_reason: "",
        note_placeholder: "Add an operator note for the Teams alert.",
        metadata_fields: [],
        options: [],
        latest_event: {},
      },
      {
        action_type: "run_safe_script",
        label: "Run safe script",
        description: "Run an allowlisted safe remediation hook with explicit guardrails.",
        category: "script",
        status: "available",
        can_execute: true,
        requires_admin: true,
        repeatable: true,
        pending_action_state: "script_pending",
        completed_action_state: "script_executed",
        current_action_state: "none",
        blocked_reason: "",
        note_placeholder: "Add an operator note for the safe remediation hook run.",
        metadata_fields: [],
        options: [
          {
            key: "vm_echo",
            label: "VM Echo",
            description: "Preview the VM remediation path.",
            default_dry_run: true,
            allow_apply: false,
            repeatable: true,
          },
        ],
        latest_event: {},
      },
    ],
  }));
  mockApi.getAzureRecommendationHistory.mockResolvedValue([
    {
      event_id: "evt-1",
      recommendation_id: "opp-disk",
      action_type: "state_change",
      action_status: "completed",
      actor_type: "user",
      actor_id: "user@example.com",
      note: "Reviewed by FinOps.",
      metadata: {},
      created_at: "2026-03-23T12:00:00+00:00",
    },
  ]);
  mockApi.dismissAzureRecommendation.mockImplementation(async (recommendationId: string, reason = "") => {
    const match = baseOpportunities.find((item) => item.id === recommendationId);
    if (!match) throw new Error("Not found");
    return { ...match, lifecycle_status: "dismissed", action_state: "none", dismissed_reason: reason };
  });
  mockApi.reopenAzureRecommendation.mockImplementation(async (recommendationId: string) => {
    const match = baseOpportunities.find((item) => item.id === recommendationId);
    if (!match) throw new Error("Not found");
    return { ...match, lifecycle_status: "open", action_state: "none", dismissed_reason: "" };
  });
  mockApi.updateAzureRecommendationActionState.mockImplementation(async (recommendationId: string, body: Record<string, unknown>) => {
    const match = baseOpportunities.find((item) => item.id === recommendationId);
    if (!match) throw new Error("Not found");
    return { ...match, lifecycle_status: "open", action_state: String(body.action_state ?? "none"), dismissed_reason: "" };
  });
  mockApi.createAzureRecommendationTicket.mockImplementation(async (recommendationId: string, body: Record<string, unknown>) => {
    const match = baseOpportunities.find((item) => item.id === recommendationId);
    if (!match) throw new Error("Not found");
    return {
      recommendation: { ...match, lifecycle_status: "open", action_state: "ticket_created", dismissed_reason: "" },
      ticket_key: "OIT-123",
      ticket_url: "https://example.atlassian.net/browse/OIT-123",
      jira_issue_id: "10001",
      project_key: String(body.project_key ?? "OIT"),
      issue_type: String(body.issue_type ?? "Task"),
      summary: String(body.summary ?? `[FinOps] ${match.title}`),
    };
  });
  mockApi.sendAzureRecommendationAlert.mockImplementation(async (recommendationId: string, body: Record<string, unknown>) => {
    const match = baseOpportunities.find((item) => item.id === recommendationId);
    if (!match) throw new Error("Not found");
    return {
      recommendation: { ...match, lifecycle_status: "open", action_state: "alert_sent", dismissed_reason: "" },
      alert_status: "sent",
      delivery_channel: String(body.channel ?? "FinOps"),
      sent_at: "2026-03-23T12:30:00+00:00",
    };
  });
  mockApi.runAzureRecommendationSafeScript.mockImplementation(async (recommendationId: string, body: Record<string, unknown>) => {
    const match = baseOpportunities.find((item) => item.id === recommendationId);
    if (!match) throw new Error("Not found");
    return {
      recommendation: { ...match, lifecycle_status: "open", action_state: "none", dismissed_reason: "" },
      hook_key: String(body.hook_key ?? "vm_echo"),
      hook_label: "VM Echo",
      action_status: body.dry_run === false ? "completed" : "dry_run",
      dry_run: body.dry_run !== false,
      started_at: "2026-03-23T12:30:00+00:00",
      completed_at: "2026-03-23T12:30:02+00:00",
      duration_ms: 2000,
      exit_code: 0,
      output_excerpt: "VM Echo completed in dry run mode for disk-1.",
    };
  });
  mockApi.getAzureCostSummary.mockResolvedValue({
    lookback_days: 30,
    total_cost: 500,
    currency: "USD",
    top_service: "Virtual Machines",
    top_subscription: "Prod",
    top_resource_group: "rg-prod",
    recommendation_count: 2,
    potential_monthly_savings: 30,
  });
  mockApi.getAzureCostTrend.mockResolvedValue([{ date: "2026-03-01", cost: 100, currency: "USD" }]);
  mockApi.getAzureCostBreakdown.mockResolvedValue([{ label: "Virtual Machines", amount: 300, currency: "USD", share: 60 }]);
  mockApi.getAzureAdvisor.mockResolvedValue([]);
  mockApi.getAzureComputeOptimization.mockResolvedValue({
    summary: {
      total_vms: 1,
      running_vms: 1,
      idle_vms: 0,
      total_running_cost: 20,
      total_advisor_savings: 0,
      ri_gap_count: 1,
    },
    idle_vms: [],
    top_cost_vms: [],
    ri_coverage_gaps: [],
    advisor_recommendations: [],
    cost_available: true,
    reservation_data_available: true,
  });
  mockApi.getAzureStorage.mockResolvedValue({
    storage_accounts: [],
    managed_disks: [],
    snapshots: [],
    summary: {
      total_storage_accounts: 1,
      total_managed_disks: 1,
      total_snapshots: 1,
      unattached_disks: 1,
      total_storage_cost: 16,
      total_disk_gb: 128,
      total_snapshot_gb: 32,
      total_provisioned_gb: 160,
      avg_cost_per_gb: 0.1,
    },
    disk_by_sku: { Premium_LRS: 1 },
    disk_by_state: { Unattached: 1 },
    accounts_by_kind: { StorageV2: 1 },
    accounts_by_tier: { Standard: 1 },
    storage_services_cost: [{ label: "Managed Disks", amount: 16, currency: "USD" }],
    cost_available: true,
    cost_basis: "amortized",
  });
  mockApi.getAzureResources.mockResolvedValue({
    resources: [
      {
        id: "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Network/publicIPAddresses/pip-1",
        name: "pip-1",
        resource_type: "Microsoft.Network/publicIPAddresses",
        subscription_id: "sub-1",
        subscription_name: "Prod",
        resource_group: "rg-prod",
        location: "eastus",
        kind: "",
        sku_name: "Standard",
        vm_size: "",
        state: "Succeeded",
        created_time: "",
        tags: {},
      },
    ],
    matched_count: 1,
    total_count: 1,
  });
  mockApi.getAzureAIModels.mockResolvedValue([{ id: "qwen2.5:7b", name: "qwen2.5:7b", provider: "ollama" }]);
  mockApi.askAzureCostCopilot.mockResolvedValue({
    answer: "Start with unattached disks and idle VM cleanup.",
    model_used: "qwen2.5:7b",
    generated_at: "2026-03-19T00:00:00Z",
    citations: [{ source_type: "savings", label: "Savings opportunities", detail: "5 ranked items" }],
  });
});

describe("Azure savings workspace", () => {
  it("renders the savings page, refilters results, opens the drawer, and updates export URLs", async () => {
    render(<AzureSavingsPage />);

    await screen.findByText("Quantified Savings");
    expect(screen.getByText("Persisted recommendation workspace")).toBeInTheDocument();
    expect(screen.getByText("Actionable Savings Opportunities")).toBeInTheDocument();
    expect(await screen.findByText("Clean up attached costs for idle VM vm-1")).toBeInTheDocument();

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "storage" },
    });

    await waitFor(() => {
      expect(mockApi.getAzureRecommendations).toHaveBeenLastCalledWith(expect.objectContaining({ category: "storage" }));
    });

    fireEvent.click(await screen.findByText("Review unattached managed disk disk-1"));
    expect(await screen.findByText("Estimate basis")).toBeInTheDocument();
    expect(screen.getByText("Confirm the disk is no longer needed.")).toBeInTheDocument();
    expect(await screen.findByText("Action History")).toBeInTheDocument();

    const csvLink = screen.getByRole("link", { name: "Export CSV" });
    expect(csvLink.getAttribute("href")).toContain("/api/azure/recommendations/export.csv");
    expect(csvLink.getAttribute("href")).toContain("category=storage");
  });

  it("creates a linked Jira ticket from the recommendation drawer", async () => {
    render(<AzureSavingsPage />);

    fireEvent.click(await screen.findByText("Review unattached managed disk disk-1"));
    await screen.findByText("Create Jira Follow-Up");

    fireEvent.change(screen.getByPlaceholderText("Project key (optional)"), { target: { value: "FINOPS" } });
    fireEvent.change(screen.getByPlaceholderText("Issue type (optional)"), { target: { value: "Task" } });
    fireEvent.change(screen.getByPlaceholderText("Ticket summary"), { target: { value: "[FinOps] Disk cleanup follow-up" } });
    fireEvent.change(screen.getByPlaceholderText("Add an operator note for the Jira follow-up."), {
      target: { value: "Please route this to the storage owner." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Jira Ticket" }));

    await waitFor(() => {
      expect(mockApi.createAzureRecommendationTicket).toHaveBeenCalledWith("opp-disk", {
        project_key: "FINOPS",
        issue_type: "Task",
        summary: "[FinOps] Disk cleanup follow-up",
        note: "Please route this to the storage owner.",
      });
    });
  });

  it("sends a Teams alert from the recommendation drawer", async () => {
    render(<AzureSavingsPage />);

    fireEvent.click(await screen.findByText("Review unattached managed disk disk-1"));
    await screen.findByRole("button", { name: "Send Teams Alert" });

    fireEvent.change(screen.getByPlaceholderText("Channel label (optional)"), { target: { value: "FinOps Watch" } });
    fireEvent.change(screen.getByPlaceholderText("Teams webhook override (optional)"), {
      target: { value: "https://hooks.example.test/abc" },
    });
    fireEvent.change(screen.getByPlaceholderText("Add an operator note for the Teams alert."), {
      target: { value: "Escalate this cleanup in the daily standup." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send Teams Alert" }));

    await waitFor(() => {
      expect(mockApi.sendAzureRecommendationAlert).toHaveBeenCalledWith("opp-disk", {
        channel: "FinOps Watch",
        teams_webhook_url: "https://hooks.example.test/abc",
        note: "Escalate this cleanup in the daily standup.",
      });
    });
  });

  it("renders the savings sections across the Azure pages", async () => {
    render(<AzureCostPage />);
    expect(await screen.findByText("Cached app data")).toBeInTheDocument();
    expect(await screen.findByText("Top Savings Opportunities")).toBeInTheDocument();
    expect(await screen.findByText("Clean up attached costs for idle VM vm-1")).toBeInTheDocument();

    render(<AzureComputeOptimizationPage />);
    expect(await screen.findByText("Compute Savings Actions")).toBeInTheDocument();
    expect(screen.getByText("Reservation Strategy")).toBeInTheDocument();

    render(<AzureStoragePage />);
    expect(await screen.findByText("Unattached Disk Savings")).toBeInTheDocument();
    expect(screen.getByText("Stale Snapshot Savings")).toBeInTheDocument();

    render(<AzureResourcesPage />);
    expect(await screen.findByText("Network Cleanup")).toBeInTheDocument();
    expect(screen.getAllByText("Release unattached public IP pip-1").length).toBeGreaterThan(0);
  });

  it("sends Azure resource search terms to the backend", async () => {
    render(<AzureResourcesPage />);

    await screen.findByText("Resources");
    fireEvent.change(screen.getByPlaceholderText("Search name, group, tag..."), {
      target: { value: "pip-1" },
    });

    await waitFor(() => {
      expect(mockApi.getAzureResources).toHaveBeenLastCalledWith({
        search: "pip-1",
        subscription_id: "",
        resource_type: "",
        location: "",
        state: "",
      });
    });
  });

  it("sends Azure storage and compute search terms to the backend", async () => {
    render(<AzureStoragePage />);

    await screen.findByText("Storage");
    fireEvent.change(screen.getByPlaceholderText("Search by name, kind, SKU, location, subscription…"), {
      target: { value: "disk-1" },
    });

    await waitFor(() => {
      expect(mockApi.getAzureStorage).toHaveBeenLastCalledWith({
        account_search: "disk-1",
        disk_search: "",
        snapshot_search: "",
        disk_unattached_only: false,
      });
    });

    render(<AzureComputeOptimizationPage />);

    await screen.findByText("Compute Optimization");
    fireEvent.change(screen.getByPlaceholderText("Search by name, subscription, resource group…"), {
      target: { value: "vm-1" },
    });

    await waitFor(() => {
      expect(mockApi.getAzureComputeOptimization).toHaveBeenLastCalledWith({
        idle_vm_search: "vm-1",
      });
    });
  });

  it("renders the savings route and nav on the Azure host", async () => {
    document.documentElement.dataset.siteHostname = "azure.movedocs.com";
    window.history.replaceState({}, "", "/savings");

    renderApp();

    expect(await screen.findByRole("heading", { name: "Savings" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Savings" })).toBeInTheDocument();
  });

  it("shows savings-grounded Azure Copilot prompts", async () => {
    render(<AzureCopilotPage />);

    expect(await screen.findByText("What are the highest-confidence savings opportunities right now?")).toBeInTheDocument();
    expect(screen.getByText("Which quick wins should we tackle first to save money in Azure?")).toBeInTheDocument();
  });
});
