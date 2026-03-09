import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import AILogPage from "../pages/AILogPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getTriageRunStatus: vi.fn(),
    getTriageLog: vi.fn(),
    cancelTriageRun: vi.fn(),
    runTriageAll: vi.fn(),
    getTicket: vi.fn(),
    getAssignees: vi.fn(),
    getPriorities: vi.fn(),
    getRequestTypes: vi.fn(),
    getTransitions: vi.fn(),
    updateTicket: vi.fn(),
    transitionTicket: vi.fn(),
    addTicketComment: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

const ticketRow = {
  key: "OIT-1",
  summary: "Printer is offline",
  issue_type: "Incident",
  status: "Open",
  status_category: "To Do",
  priority: "High",
  resolution: "",
  assignee: "Ada Lovelace",
  assignee_account_id: "acct-1",
  reporter: "Grace Hopper",
  created: "2026-03-01T10:00:00Z",
  updated: "2026-03-02T12:00:00Z",
  resolved: "",
  request_type: "Hardware",
  calendar_ttr_hours: null,
  age_days: 2,
  days_since_update: 1,
  excluded: false,
  sla_first_response_status: "running",
  sla_first_response_breach_time: "",
  sla_first_response_remaining_millis: null,
  sla_resolution_status: "running",
  sla_resolution_breach_time: "",
  sla_resolution_remaining_millis: null,
  labels: [],
  components: [],
  work_category: "",
  organizations: [],
  attachment_count: 0,
};

const ticketDetail = {
  ticket: ticketRow,
  description: "Main office printer is unavailable.",
  steps_to_recreate: "",
  request_type: "Hardware",
  work_category: "Support",
  comments: [],
  attachments: [],
  issue_links: [],
  jira_url: "https://jira.example.com/browse/OIT-1",
  portal_url: "https://portal.example.com/requests/OIT-1",
  raw_issue: {},
};

describe("AILogPage", () => {
  const originalIntersectionObserver = globalThis.IntersectionObserver;

  beforeEach(() => {
    vi.clearAllMocks();
    window.history.pushState({}, "", "/ai-log");
    globalThis.IntersectionObserver = vi.fn().mockImplementation(() => ({
      observe: vi.fn(),
      disconnect: vi.fn(),
      unobserve: vi.fn(),
      takeRecords: vi.fn(),
      root: null,
      rootMargin: "",
      thresholds: [],
    })) as unknown as typeof IntersectionObserver;

    mockApi.getTriageRunStatus.mockResolvedValue({
      running: false,
      processed: 0,
      total: 0,
      current_key: null,
      remaining_count: 0,
      processed_count: 0,
    });
    mockApi.getTriageLog.mockResolvedValue([
      {
        key: "OIT-1",
        field: "priority",
        old_value: "Medium",
        new_value: "High",
        confidence: 0.93,
        model: "gpt-4o-mini",
        source: "auto",
        approved_by: null,
        timestamp: "2026-03-03T10:00:00Z",
      },
    ]);
    mockApi.cancelTriageRun.mockResolvedValue({ cancelled: true });
    mockApi.runTriageAll.mockResolvedValue({ started: true, total_tickets: 1 });
    mockApi.getTicket.mockResolvedValue(ticketDetail);
    mockApi.getAssignees.mockResolvedValue([]);
    mockApi.getPriorities.mockResolvedValue([{ id: "1", name: "High" }]);
    mockApi.getRequestTypes.mockResolvedValue([{ id: "1", name: "Hardware", description: "" }]);
    mockApi.getTransitions.mockResolvedValue([]);
  });

  afterEach(() => {
    globalThis.IntersectionObserver = originalIntersectionObserver;
  });

  it("opens the local drawer when a ticket key in the AI log is clicked", async () => {
    const user = userEvent.setup();

    render(<AILogPage />);

    const ticketLink = await screen.findByRole("link", { name: "OIT-1" });
    expect(ticketLink).toHaveAttribute("href", "/ai-log?ticket=OIT-1");

    await user.click(ticketLink);

    await waitFor(() => {
      expect(window.location.search).toBe("?ticket=OIT-1");
    });
    await screen.findByText("Ticket Actions");
    expect(mockApi.getTicket).toHaveBeenCalledWith("OIT-1");
  });
});
