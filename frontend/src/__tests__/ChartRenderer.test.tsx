import { describe, it, expect, vi, beforeAll } from "vitest";
import { render } from "../test-utils.tsx";
import ChartRenderer from "../components/charts/ChartRenderer.tsx";
import type { ChartDataPoint, ChartTimeseriesPoint } from "../lib/api.ts";

// ---------------------------------------------------------------------------
// Mock ResizeObserver (recharts needs it)
// ---------------------------------------------------------------------------

beforeAll(() => {
  globalThis.ResizeObserver = vi.fn().mockImplementation(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
  }));
});

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const groupedData: ChartDataPoint[] = [
  { label: "Open", value: 10 },
  { label: "Closed", value: 20 },
  { label: "In Progress", value: 5 },
];

const timeseriesData: ChartTimeseriesPoint[] = [
  { period: "2026-02-24", created: 5, resolved: 3, net_flow: 2 },
  { period: "2026-03-03", created: 8, resolved: 6, net_flow: 2 },
];

// ---------------------------------------------------------------------------
// Tests
//
// Note: Recharts ResponsiveContainer requires real DOM dimensions which jsdom
// doesn't provide, so SVG elements won't render. We verify:
// 1. Component renders without error
// 2. "No data to display" is NOT shown (data path was taken)
// 3. Empty data DOES show the empty state message
// ---------------------------------------------------------------------------

describe("ChartRenderer — grouped charts", () => {
  it("renders bar chart without error", () => {
    const { queryByText } = render(
      <ChartRenderer type="bar" data={groupedData} />
    );
    expect(queryByText("No data to display")).toBeNull();
  });

  it("renders horizontal_bar chart without error", () => {
    const { queryByText } = render(
      <ChartRenderer type="horizontal_bar" data={groupedData} />
    );
    expect(queryByText("No data to display")).toBeNull();
  });

  it("renders pie chart without error", () => {
    const { queryByText } = render(
      <ChartRenderer type="pie" data={groupedData} />
    );
    expect(queryByText("No data to display")).toBeNull();
  });

  it("renders donut chart without error", () => {
    const { queryByText } = render(
      <ChartRenderer type="donut" data={groupedData} />
    );
    expect(queryByText("No data to display")).toBeNull();
  });

  it("shows empty state for grouped with no data", () => {
    const { getByText } = render(
      <ChartRenderer type="bar" data={[]} />
    );
    expect(getByText("No data to display")).toBeInTheDocument();
  });
});

describe("ChartRenderer — timeseries charts", () => {
  it("renders line chart without error", () => {
    const { queryByText } = render(
      <ChartRenderer type="line" data={timeseriesData} />
    );
    expect(queryByText("No data to display")).toBeNull();
  });

  it("renders area chart without error", () => {
    const { queryByText } = render(
      <ChartRenderer type="area" data={timeseriesData} />
    );
    expect(queryByText("No data to display")).toBeNull();
  });

  it("shows empty state for timeseries with no data", () => {
    const { getByText } = render(
      <ChartRenderer type="line" data={[]} />
    );
    expect(getByText("No data to display")).toBeInTheDocument();
  });
});
