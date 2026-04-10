import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import SLAPage from "../pages/SLAPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getSLAMetrics: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

beforeAll(() => {
  globalThis.ResizeObserver = vi.fn().mockImplementation(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
  }));
  globalThis.IntersectionObserver = vi.fn().mockImplementation(() => ({
    observe: vi.fn(),
    disconnect: vi.fn(),
    unobserve: vi.fn(),
    takeRecords: vi.fn(),
    root: null,
    rootMargin: "",
    thresholds: [],
  })) as unknown as typeof IntersectionObserver;
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 960 });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 480 });
});

const baseTicket = {
  issue_type: "Incident",
  resolution: "",
  assignee: "Ada Lovelace",
  assignee_account_id: "acct-1",
  reporter: "Grace Hopper",
  created: "2026-03-01T10:00:00Z",
  updated: "2026-03-02T12:00:00Z",
  resolved: "",
  request_type: "Security Alert",
  calendar_ttr_hours: null,
  age_days: 2,
  days_since_update: 1,
  excluded: false,
  sla_first_response_status: "running",
  sla_first_response_breach_time: "",
  sla_first_response_remaining_millis: null,
  sla_first_response_elapsed_millis: null,
  sla_first_response_goal_millis: null,
  sla_resolution_status: "running",
  sla_resolution_breach_time: "",
  sla_resolution_remaining_millis: null,
  sla_resolution_elapsed_millis: null,
  sla_resolution_goal_millis: null,
  labels: [],
  components: [],
  work_category: "Security",
  organizations: [],
  attachment_count: 0,
};

const slaMetricsResponse = {
  summary: {
    first_response: {
      total: 2,
      met: 1,
      breached: 1,
      running: 0,
      compliance_pct: 50,
      avg_elapsed_minutes: 110,
      p95_elapsed_minutes: 200,
      distribution: [
        { label: "<30m", count: 1 },
        { label: "30m–1h", count: 0 },
        { label: "1–2h", count: 0 },
        { label: "2–4h", count: 1 },
        { label: "4–8h", count: 0 },
        { label: "8h+", count: 0 },
      ],
    },
    resolution: {
      total: 3,
      met: 1,
      breached: 0,
      running: 2,
      compliance_pct: 100,
      avg_elapsed_minutes: 360,
      p95_elapsed_minutes: 840,
      distribution: [
        { label: "<2h", count: 1 },
        { label: "2–4h", count: 1 },
        { label: "4–8h", count: 0 },
        { label: "1 day", count: 0 },
        { label: "1–2d", count: 1 },
        { label: "2–5d", count: 0 },
        { label: "5d+", count: 0 },
      ],
    },
  },
  tickets: [
    {
      ...baseTicket,
      key: "OIT-1",
      summary: "Phishing report from employee mailbox",
      status: "Open",
      status_category: "To Do",
      priority: "High",
      sla_first_response: {
        status: "met",
        elapsed_minutes: 20,
        target_minutes: 30,
        breach_time: "2026-03-01T10:30:00Z",
      },
      sla_resolution: {
        status: "running",
        elapsed_minutes: 180,
        target_minutes: 480,
        breach_time: "2026-03-01T18:00:00Z",
      },
    },
    {
      ...baseTicket,
      key: "OIT-2",
      summary: "Suspicious link clicked on shared workstation",
      status: "In Progress",
      status_category: "In Progress",
      priority: "Highest",
      sla_first_response: {
        status: "breached",
        elapsed_minutes: 180,
        target_minutes: 60,
        breach_time: "2026-03-01T11:00:00Z",
      },
      sla_resolution: {
        status: "met",
        elapsed_minutes: 840,
        target_minutes: 1440,
        breach_time: "2026-03-02T10:00:00Z",
      },
    },
    {
      ...baseTicket,
      key: "OIT-3",
      summary: "Awaiting follow-up details from reporting team",
      status: "Waiting for customer",
      status_category: "In Progress",
      priority: "Medium",
      sla_first_response: null,
      sla_resolution: {
        status: "running",
        elapsed_minutes: 60,
        target_minutes: 480,
        breach_time: "2026-03-02T18:00:00Z",
      },
    },
  ],
  settings: {
    business_hours_start: "08:00",
    business_hours_end: "17:00",
    business_timezone: "America/Los_Angeles",
    business_days: "0,1,2,3,4",
    integration_reporters: "",
  },
  targets: [],
};

describe("SLAPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.pushState({}, "", "/sla");
    mockApi.getSLAMetrics.mockResolvedValue(slaMetricsResponse);
  });

  it("filters the ticket list when a summary status pill is clicked", async () => {
    const user = userEvent.setup();

    render(<SLAPage />);

    await screen.findByText("SLA Tracker");
    await user.click(screen.getByRole("button", { name: "Filter First Response Breached" }));

    await waitFor(() => {
      expect(screen.getByText("OIT-2")).toBeInTheDocument();
      expect(screen.queryByText("OIT-1")).not.toBeInTheDocument();
    });
  });

  it("filters the ticket list when a distribution bucket is clicked", async () => {
    const user = userEvent.setup();

    render(<SLAPage />);

    await screen.findByText("First Response Distribution");
    const bucketButton = await screen.findByRole("button", {
      name: "Filter First Response Distribution bucket <30m",
    }, {
      timeout: 5000,
    });
    await user.click(bucketButton);

    await waitFor(() => {
      expect(screen.getByText("OIT-1")).toBeInTheDocument();
      expect(screen.queryByText("OIT-2")).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /clear bucket: first response: <30m/i }));

    await waitFor(() => {
      expect(screen.getByText("OIT-1")).toBeInTheDocument();
      expect(screen.getByText("OIT-2")).toBeInTheDocument();
    });
  });

  it("filters the ticket list when a summary total metric is clicked", async () => {
    const user = userEvent.setup();

    render(<SLAPage />);

    await screen.findByText("SLA Tracker");
    await user.click(screen.getByRole("button", { name: "Filter First Response Total" }));

    await waitFor(() => {
      expect(screen.getByText("OIT-1")).toBeInTheDocument();
      expect(screen.getByText("OIT-2")).toBeInTheDocument();
      expect(screen.queryByText("OIT-3")).not.toBeInTheDocument();
    });
  });

  it("requests server-filtered tickets when the search box changes", async () => {
    const user = userEvent.setup();

    mockApi.getSLAMetrics.mockImplementation(async (params?: { search?: string }) => {
      if (params?.search === "printer") {
        return {
          ...slaMetricsResponse,
          tickets: slaMetricsResponse.tickets.filter((ticket) => ticket.summary.toLowerCase().includes("printer")),
        };
      }
      return slaMetricsResponse;
    });

    render(<SLAPage />);

    await screen.findByText("SLA Tracker");
    await user.type(screen.getByPlaceholderText("Search key, summary, assignee..."), "printer");

    await waitFor(() => {
      expect(mockApi.getSLAMetrics).toHaveBeenLastCalledWith({ date_from: undefined, date_to: undefined, search: "printer" });
      expect(screen.queryByText("OIT-2")).not.toBeInTheDocument();
    });
  });
});
