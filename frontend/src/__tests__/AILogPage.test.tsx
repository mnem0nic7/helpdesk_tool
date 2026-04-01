import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import AILogPage from "../pages/AILogPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getTriageRunStatus: vi.fn(),
    getTriageLog: vi.fn(),
    getTechnicianScores: vi.fn(),
    cancelTriageRun: vi.fn(),
    cancelTechnicianScoreRun: vi.fn(),
    runTriageAll: vi.fn(),
    runClosedTicketScoring: vi.fn(),
    getTechnicianScoreRunStatus: vi.fn(),
    getTicket: vi.fn(),
    getAssignees: vi.fn(),
    getPriorities: vi.fn(),
    getRequestTypes: vi.fn(),
    getTransitions: vi.fn(),
    updateTicket: vi.fn(),
    transitionTicket: vi.fn(),
    addTicketComment: vi.fn(),
    getMe: vi.fn(),
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
    const triageLogEntries = [
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
      {
        key: "OIT-2",
        field: "status",
        old_value: "Open",
        new_value: "Waiting on VPN reset",
        confidence: 0.78,
        model: "gpt-4.1-mini",
        source: "user",
        approved_by: "Sam Analyst",
        timestamp: "2026-03-03T12:00:00Z",
      },
    ];
    const technicianScoreEntries = [
      {
        key: "OIT-1",
        communication_score: 4,
        communication_notes: "Clear user-facing updates.",
        documentation_score: 3,
        documentation_notes: "Resolution notes were adequate.",
        overall_score: 3.5,
        score_summary: "Good communication with moderate documentation detail.",
        model_used: "gpt-4o-mini",
        created_at: "2026-03-03T11:00:00Z",
        ticket_summary: "Printer is offline",
        ticket_status: "Closed",
        ticket_assignee: "Ada Lovelace",
        ticket_resolved: "2026-03-03T09:30:00Z",
      },
      {
        key: "OIT-2",
        communication_score: 2,
        communication_notes: "Updates mentioned the VPN issue but were too brief.",
        documentation_score: 2,
        documentation_notes: "Resolution details did not explain the password reset path.",
        overall_score: 2,
        score_summary: "VPN reset resolution needs clearer documentation.",
        model_used: "gpt-4.1-mini",
        created_at: "2026-03-03T12:30:00Z",
        ticket_summary: "VPN password reset",
        ticket_status: "Closed",
        ticket_assignee: "Sam Analyst",
        ticket_resolved: "2026-03-03T12:15:00Z",
      },
    ];
    mockApi.getTriageLog.mockImplementation(async (params?: { search?: string }) => {
      const query = (params?.search || "").toLowerCase();
      if (!query) return triageLogEntries;
      return triageLogEntries.filter((entry) =>
        [entry.key, entry.field, entry.old_value, entry.new_value, entry.model, entry.approved_by || ""]
          .join(" ")
          .toLowerCase()
          .includes(query),
      );
    });
    mockApi.getTechnicianScores.mockImplementation(async (params?: { search?: string }) => {
      const query = (params?.search || "").toLowerCase();
      if (!query) return technicianScoreEntries;
      return technicianScoreEntries.filter((entry) =>
        [
          entry.key,
          entry.ticket_summary,
          entry.ticket_status,
          entry.ticket_assignee,
          entry.score_summary,
          entry.communication_notes,
          entry.documentation_notes,
          entry.model_used,
        ]
          .join(" ")
          .toLowerCase()
          .includes(query),
      );
    });
    mockApi.cancelTriageRun.mockResolvedValue({ cancelled: true });
    mockApi.cancelTechnicianScoreRun.mockResolvedValue({ cancelled: true });
    mockApi.runTriageAll.mockResolvedValue({ started: true, total_tickets: 1 });
    mockApi.runClosedTicketScoring.mockResolvedValue({ started: true, total_tickets: 1 });
    mockApi.getTechnicianScoreRunStatus.mockResolvedValue({
      running: false,
      processed: 0,
      total: 0,
      current_key: null,
      remaining_count: 1,
      processed_count: 0,
      priority_blocked: false,
      priority_message: "",
      priority_reason: "",
      priority_pending_count: 0,
      priority_running: false,
      priority_current_key: null,
    });
    mockApi.getTicket.mockResolvedValue(ticketDetail);
    mockApi.getAssignees.mockResolvedValue([]);
    mockApi.getPriorities.mockResolvedValue([{ id: "1", name: "High" }]);
    mockApi.getRequestTypes.mockResolvedValue([{ id: "1", name: "Hardware", description: "" }]);
    mockApi.getTransitions.mockResolvedValue([]);
    mockApi.getMe.mockResolvedValue({
      email: "test@example.com",
      name: "Test User",
      is_admin: true,
      jira_auth: { connected: false, mode: "fallback_it_app", site_url: "", account_name: "", configured: true },
    });
  });

  afterEach(() => {
    globalThis.IntersectionObserver = originalIntersectionObserver;
  });

  it("opens the local drawer when a ticket key in the AI log is clicked", async () => {
    const user = userEvent.setup();

    render(<AILogPage />);

    const ticketLinks = await screen.findAllByRole("link", { name: "OIT-1" });
    expect(ticketLinks).toHaveLength(1);
    expect(ticketLinks[0]).toHaveAttribute("href", "/ai-log?ticket=OIT-1");

    await user.click(ticketLinks[0]);

    await waitFor(() => {
      expect(window.location.search).toBe("?ticket=OIT-1");
    });
    await screen.findByText("Ticket Actions");
    expect(mockApi.getTicket).toHaveBeenCalledWith("OIT-1");
  });

  it("shows technician QA scores and can start scoring closed tickets", async () => {
    const user = userEvent.setup();

    render(<AILogPage />);

    await screen.findByText("Technician QA Scoring");
    expect(
      screen.getByText("Run AI reviews for closed tickets here. Open an individual ticket to view the actual technician QA score and notes."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Technician QA Scores")).not.toBeInTheDocument();
    expect(screen.queryByText("Good communication with moderate documentation detail.")).not.toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "Score Closed Tickets (1)" }));

    await waitFor(() => {
      expect(mockApi.runClosedTicketScoring).toHaveBeenCalledWith();
    });
  });

  it("disables technician QA scoring while new-ticket auto-triage has priority", async () => {
    mockApi.getTechnicianScoreRunStatus.mockResolvedValue({
      running: false,
      processed: 0,
      total: 0,
      current_key: null,
      remaining_count: 1,
      processed_count: 0,
      priority_blocked: true,
      priority_message:
        "Processing new tickets takes priority over technician QA scoring.",
      priority_reason: "auto_triage_priority",
      priority_pending_count: 3,
      priority_running: true,
      priority_current_key: "OIT-500",
    });

    render(<AILogPage />);

    expect(
      await screen.findByText("Processing new tickets takes priority over technician QA scoring."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Score Closed Tickets (1)" }),
    ).toBeDisabled();
  });

  it("filters AI change log entries with the search box", async () => {
    const user = userEvent.setup();

    render(<AILogPage />);

    await screen.findByText("Waiting on VPN reset");
    expect(screen.queryByText("High")).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox", { name: "Search AI log" }), "vpn");

    await waitFor(() => {
      expect(mockApi.getTriageLog).toHaveBeenLastCalledWith({ search: "vpn" });
      expect(screen.queryByText("High")).not.toBeInTheDocument();
      expect(screen.getByText("Waiting on VPN reset")).toBeInTheDocument();
    });
  });

  it("does not fetch technician QA score lists on the AI log page", async () => {
    render(<AILogPage />);

    await screen.findByText("AI Change Log");

    await waitFor(() => {
      expect(mockApi.getTriageLog).toHaveBeenCalled();
    });
    expect(mockApi.getTechnicianScores).not.toHaveBeenCalled();
  });
});
