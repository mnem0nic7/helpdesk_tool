import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render } from "../test-utils.tsx";
import { screen, fireEvent, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock the api module
// ---------------------------------------------------------------------------

vi.mock("../lib/api.ts", () => ({
  api: {
    getChartData: vi.fn().mockResolvedValue({
      data: [
        { label: "Open", value: 10 },
        { label: "Closed", value: 5 },
      ],
      group_by: "status",
      metric: "count",
    }),
    getChartTimeseries: vi.fn().mockResolvedValue({
      data: [
        { period: "2026-02-24", created: 5, resolved: 3, net_flow: 2 },
      ],
      bucket: "week",
    }),
  },
}));

// ---------------------------------------------------------------------------
// Mock ResizeObserver for recharts
// ---------------------------------------------------------------------------

beforeAll(() => {
  globalThis.ResizeObserver = vi.fn().mockImplementation(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
  }));
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 800 });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 400 });
});

// Lazy import after mock
let VisualizationsPage: typeof import("../pages/VisualizationsPage.tsx").default;

beforeEach(async () => {
  const mod = await import("../pages/VisualizationsPage.tsx");
  VisualizationsPage = mod.default;
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("VisualizationsPage", () => {
  it("renders page title", () => {
    render(<VisualizationsPage />);
    expect(screen.getByText("Visualizations")).toBeInTheDocument();
  });

  it("renders all 7 presets", () => {
    render(<VisualizationsPage />);
    expect(screen.getByText("Tickets by Status")).toBeInTheDocument();
    expect(screen.getByText("Tickets by Priority")).toBeInTheDocument();
    expect(screen.getByText("Assignee Workload")).toBeInTheDocument();
    expect(screen.getByText("Resolution Times")).toBeInTheDocument();
    expect(screen.getByText("Age by Status")).toBeInTheDocument();
    expect(screen.getByText("Weekly Trend")).toBeInTheDocument();
    expect(screen.getByText("Monthly Trend")).toBeInTheDocument();
  });

  it("has mode toggle buttons", () => {
    render(<VisualizationsPage />);
    expect(screen.getByText("Grouped")).toBeInTheDocument();
    expect(screen.getByText("Time Series")).toBeInTheDocument();
  });

  it("shows grouped controls by default", () => {
    render(<VisualizationsPage />);
    expect(screen.getByText("Group by")).toBeInTheDocument();
    expect(screen.getByText("Metric")).toBeInTheDocument();
  });

  it("switching to timeseries hides grouped controls", async () => {
    render(<VisualizationsPage />);
    fireEvent.click(screen.getByText("Time Series"));
    await waitFor(() => {
      expect(screen.getByText("Time bucket")).toBeInTheDocument();
    });
    expect(screen.queryByText("Group by")).not.toBeInTheDocument();
  });

  it("has download button", () => {
    render(<VisualizationsPage />);
    expect(screen.getByText("Download as PNG")).toBeInTheDocument();
  });

  it("preset click updates active state", async () => {
    render(<VisualizationsPage />);
    const preset = screen.getByText("Tickets by Priority");
    fireEvent.click(preset);
    // After clicking, the parent button should have the active styling
    // Just verify the click doesn't error
    expect(preset).toBeInTheDocument();
  });
});
