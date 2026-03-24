import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import AzureAllocationPage from "../pages/AzureAllocationPage.tsx";

const baseRun = {
  run_id: "run-1",
  run_label: "March allocation snapshot",
  trigger_type: "manual",
  triggered_by: "finops@example.com",
  note: "Initial team/application cut",
  status: "completed",
  target_dimensions: ["team", "application"],
  policy_version: 1,
  source_record_count: 120,
  created_at: "2026-03-23T16:00:00Z",
  completed_at: "2026-03-23T16:00:02Z",
  dimensions: [
    {
      target_dimension: "team",
      source_record_count: 120,
      source_actual_cost: 1000,
      source_amortized_cost: 980,
      source_usage_quantity: 1,
      direct_allocated_actual_cost: 850,
      direct_allocated_amortized_cost: 830,
      direct_allocated_usage_quantity: 1,
      residual_actual_cost: 150,
      residual_amortized_cost: 150,
      residual_usage_quantity: 0,
      total_allocated_actual_cost: 1000,
      total_allocated_amortized_cost: 980,
      total_allocated_usage_quantity: 1,
      coverage_pct: 1,
      created_at: "2026-03-23T16:00:02Z",
    },
    {
      target_dimension: "application",
      source_record_count: 120,
      source_actual_cost: 1000,
      source_amortized_cost: 980,
      source_usage_quantity: 1,
      direct_allocated_actual_cost: 920,
      direct_allocated_amortized_cost: 900,
      direct_allocated_usage_quantity: 1,
      residual_actual_cost: 80,
      residual_amortized_cost: 80,
      residual_usage_quantity: 0,
      total_allocated_actual_cost: 1000,
      total_allocated_amortized_cost: 980,
      total_allocated_usage_quantity: 1,
      coverage_pct: 1,
      created_at: "2026-03-23T16:00:02Z",
    },
  ],
  rule_versions: [],
};

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getMe: vi.fn(),
    getAzureAllocationStatus: vi.fn(),
    getAzureAllocationRules: vi.fn(),
    getAzureAllocationRuns: vi.fn(),
    getAzureAllocationRun: vi.fn(),
    getAzureAllocationResults: vi.fn(),
    getAzureAllocationResiduals: vi.fn(),
    runAzureAllocation: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

describe("AzureAllocationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getMe.mockResolvedValue({
      email: "finops@example.com",
      name: "FinOps User",
      is_admin: true,
      can_manage_users: true,
    });
    mockApi.getAzureAllocationStatus.mockResolvedValue({
      available: true,
      policy: {
        version: 1,
        target_dimensions: [
          {
            dimension: "team",
            label: "Team",
            fallback_bucket: "Unassigned Team",
            shared_bucket: "Shared Team Costs",
            description: "Team ownership view.",
          },
          {
            dimension: "application",
            label: "Application",
            fallback_bucket: "Unassigned Application",
            shared_bucket: "Shared Application Costs",
            description: "Application ownership view.",
          },
          {
            dimension: "product",
            label: "Product",
            fallback_bucket: "Unassigned Product",
            shared_bucket: "Shared Product Costs",
            description: "Product ownership view.",
          },
        ],
        shared_cost_posture: {
          mode: "showback_named_shared_buckets",
          description: "Shared costs stay visible.",
        },
        supported_rule_types: ["tag", "regex", "percentage", "shared"],
        supported_match_fields: ["resource_group", "subscription_name", "tags.team"],
      },
      rule_version_count: 3,
      active_rule_count: 2,
      inactive_rule_count: 1,
      run_count: 1,
      last_run_at: "2026-03-23T16:00:02Z",
      latest_run: baseRun,
    });
    mockApi.getAzureAllocationRules.mockResolvedValue([
      {
        rule_id: "rule-team",
        rule_version: 1,
        name: "Tag team owner",
        description: "Map team tag to a named team bucket.",
        rule_type: "tag",
        target_dimension: "team",
        priority: 10,
        enabled: true,
        condition: { tag_key: "team", tag_value: "Platform" },
        allocation: { value: "Platform Team" },
        created_by: "finops@example.com",
        created_at: "2026-03-23T15:59:00Z",
        superseded_at: "",
      },
      {
        rule_id: "rule-app",
        rule_version: 1,
        name: "Tag application owner",
        description: "Map app tag to application bucket.",
        rule_type: "tag",
        target_dimension: "application",
        priority: 10,
        enabled: true,
        condition: { tag_key: "application", tag_value: "Billing" },
        allocation: { value: "Billing App" },
        created_by: "finops@example.com",
        created_at: "2026-03-23T15:59:00Z",
        superseded_at: "",
      },
    ]);
    mockApi.getAzureAllocationRuns.mockResolvedValue([baseRun]);
    mockApi.getAzureAllocationRun.mockResolvedValue(baseRun);
    mockApi.getAzureAllocationResults.mockImplementation((_runId: string, dimension: string) => {
      if (dimension === "team") {
        return Promise.resolve([
          {
            allocation_value: "Platform Team",
            bucket_type: "direct",
            allocation_method: "tag",
            source_record_count: 70,
            allocated_actual_cost: 850,
            allocated_amortized_cost: 830,
            allocated_usage_quantity: 1,
          },
          {
            allocation_value: "Unassigned Team",
            bucket_type: "fallback",
            allocation_method: "fallback",
            source_record_count: 50,
            allocated_actual_cost: 150,
            allocated_amortized_cost: 150,
            allocated_usage_quantity: 0,
          },
        ]);
      }
      return Promise.resolve([
        {
          allocation_value: "Billing App",
          bucket_type: "direct",
          allocation_method: "tag",
          source_record_count: 90,
          allocated_actual_cost: 920,
          allocated_amortized_cost: 900,
          allocated_usage_quantity: 1,
        },
        {
          allocation_value: "Unassigned Application",
          bucket_type: "fallback",
          allocation_method: "fallback",
          source_record_count: 30,
          allocated_actual_cost: 80,
          allocated_amortized_cost: 80,
          allocated_usage_quantity: 0,
        },
      ]);
    });
    mockApi.getAzureAllocationResiduals.mockImplementation((_runId: string, dimension: string) => {
      if (dimension === "team") {
        return Promise.resolve([
          {
            allocation_value: "Unassigned Team",
            bucket_type: "fallback",
            allocation_method: "fallback",
            source_record_count: 50,
            allocated_actual_cost: 150,
            allocated_amortized_cost: 150,
            allocated_usage_quantity: 0,
          },
        ]);
      }
      return Promise.resolve([
        {
          allocation_value: "Unassigned Application",
          bucket_type: "fallback",
          allocation_method: "fallback",
          source_record_count: 30,
          allocated_actual_cost: 80,
          allocated_amortized_cost: 80,
          allocated_usage_quantity: 0,
        },
      ]);
    });
    mockApi.runAzureAllocation.mockResolvedValue(baseRun);
  });

  it("renders the team and application allocation workspace", async () => {
    render(<AzureAllocationPage />);

    expect(await screen.findByText("Allocation")).toBeInTheDocument();
    expect(screen.getByText("Cost by Team")).toBeInTheDocument();
    expect(screen.getByText("Cost by Application")).toBeInTheDocument();
    expect(screen.getByText("Platform Team")).toBeInTheDocument();
    expect(screen.getByText("Billing App")).toBeInTheDocument();
    expect(screen.getByText("Unassigned Team")).toBeInTheDocument();
    expect(screen.getByText("Active Rules")).toBeInTheDocument();
  });
});
