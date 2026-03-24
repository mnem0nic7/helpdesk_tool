import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import AzureAICostPage from "../pages/AzureAICostPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureAICostSummary: vi.fn(),
    getAzureAICostTrend: vi.fn(),
    getAzureAICostBreakdown: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

describe("AzureAICostPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureAICostSummary.mockResolvedValue({
      lookback_days: 30,
      usage_record_count: 4,
      request_count: 12,
      input_tokens: 800,
      output_tokens: 400,
      estimated_tokens: 1200,
      estimated_cost: 0,
      currency: "USD",
      top_model: "qwen2.5:7b",
      top_feature: "azure_cost_copilot",
      window_start: "2026-03-20",
      window_end: "2026-03-23",
    });
    mockApi.getAzureAICostTrend.mockResolvedValue([
      {
        date: "2026-03-20",
        request_count: 3,
        input_tokens: 200,
        output_tokens: 80,
        estimated_tokens: 280,
        estimated_cost: 0,
        currency: "USD",
      },
    ]);
    mockApi.getAzureAICostBreakdown.mockImplementation((groupBy: string) => {
      if (groupBy === "provider") {
        return Promise.resolve([
          { label: "ollama", request_count: 12, estimated_tokens: 1200, estimated_cost: 0, currency: "USD", share: 1 },
        ]);
      }
      if (groupBy === "team") {
        return Promise.resolve([
          { label: "FinOps", request_count: 7, estimated_tokens: 700, estimated_cost: 0, currency: "USD", share: 0.58 },
        ]);
      }
      return Promise.resolve([
        { label: "qwen2.5:7b", request_count: 12, estimated_tokens: 1200, estimated_cost: 0, currency: "USD", share: 1 },
      ]);
    });
  });

  it("renders the Ollama-only AI cost workspace", async () => {
    render(<AzureAICostPage />);

    expect(await screen.findByText("AI Cost")).toBeInTheDocument();
    expect(screen.getByText("Ollama-only runtime confirmed")).toBeInTheDocument();
    expect(screen.getByText("qwen2.5:7b")).toBeInTheDocument();
    expect(screen.getByText("azure_cost_copilot")).toBeInTheDocument();
    expect(screen.getByText("By Team")).toBeInTheDocument();
    expect(screen.getByText("FinOps")).toBeInTheDocument();
  });
});
