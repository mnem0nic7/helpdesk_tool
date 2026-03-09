import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import ManagePage from "../pages/ManagePage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getTickets: vi.fn(),
    getFilterOptions: vi.fn(),
    getAssignees: vi.fn(),
    getCacheStatus: vi.fn(),
    getTicket: vi.fn(),
    getPriorities: vi.fn(),
    getRequestTypes: vi.fn(),
    getTransitions: vi.fn(),
    updateTicket: vi.fn(),
    transitionTicket: vi.fn(),
    addTicketComment: vi.fn(),
    refreshCacheIncremental: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

const ticketRow = {
  key: "OIT-1",
  summary: "Suspicious login attempt reported",
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
  request_type: "Security Alert",
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
  description: "Security team needs to review this report.",
  steps_to_recreate: "",
  request_type: "Security Alert",
  work_category: "Security",
  comments: [],
  attachments: [],
  issue_links: [],
  jira_url: "https://jira.example.com/browse/OIT-1",
  portal_url: "https://portal.example.com/requests/OIT-1",
  raw_issue: {},
};

describe("ManagePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.pushState({}, "", "/manage");
    mockApi.getTickets.mockResolvedValue({
      tickets: [ticketRow],
      matched_count: 1,
      total_count: 1,
    });
    mockApi.getFilterOptions.mockResolvedValue({
      statuses: ["Open"],
      priorities: ["High"],
      issue_types: ["Incident"],
    });
    mockApi.getAssignees.mockResolvedValue([]);
    mockApi.getCacheStatus.mockResolvedValue({
      jira_base_url: "https://jira.example.com",
    });
    mockApi.getTicket.mockResolvedValue(ticketDetail);
    mockApi.getPriorities.mockResolvedValue([{ id: "1", name: "High" }]);
    mockApi.getRequestTypes.mockResolvedValue([{ id: "1", name: "Security Alert", description: "" }]);
    mockApi.getTransitions.mockResolvedValue([]);
    mockApi.refreshCacheIncremental.mockResolvedValue(undefined);
  });

  it("supports a kanban view that still opens the local ticket drawer", async () => {
    const user = userEvent.setup();

    render(<ManagePage />);

    await user.click(screen.getByRole("button", { name: "Kanban" }));

    await waitFor(() => {
      expect(window.location.search).toBe("?view=kanban");
    });

    await screen.findByText("To Do");
    const ticketLink = await screen.findByRole("link", { name: "OIT-1" });
    expect(ticketLink.getAttribute("href")).toContain("/manage?");
    expect(ticketLink.getAttribute("href")).toContain("view=kanban");
    expect(ticketLink.getAttribute("href")).toContain("ticket=OIT-1");

    await user.click(ticketLink);

    await waitFor(() => {
      expect(window.location.search).toBe("?view=kanban&ticket=OIT-1");
    });
    await screen.findByText("Ticket Actions");
    expect(mockApi.getTicket).toHaveBeenCalledWith("OIT-1");
  });
});
