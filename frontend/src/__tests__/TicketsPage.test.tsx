import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import TicketsPage from "../pages/TicketsPage.tsx";

const { mockApi, mockGetSiteBranding } = vi.hoisted(() => ({
  mockApi: {
    getTickets: vi.fn(),
    refreshVisibleTickets: vi.fn(),
    getFilterOptions: vi.fn(),
    getAssignees: vi.fn(),
    getCacheStatus: vi.fn(),
    getTicket: vi.fn(),
    getPriorities: vi.fn(),
    getRequestTypes: vi.fn(),
    getTransitions: vi.fn(),
    updateTicket: vi.fn(),
    createTicket: vi.fn(),
    transitionTicket: vi.fn(),
    addTicketComment: vi.fn(),
    exportAll: vi.fn(() => "/api/export/all"),
    getMe: vi.fn(),
  },
  mockGetSiteBranding: vi.fn(),
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

vi.mock("../lib/siteContext.ts", () => ({
  getSiteBranding: mockGetSiteBranding,
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

describe("TicketsPage", () => {
  const originalIntersectionObserver = globalThis.IntersectionObserver;

  beforeEach(() => {
    vi.clearAllMocks();
    globalThis.IntersectionObserver = vi.fn().mockImplementation(() => ({
      observe: vi.fn(),
      disconnect: vi.fn(),
      unobserve: vi.fn(),
      takeRecords: vi.fn(() => []),
      root: null,
      rootMargin: "",
      thresholds: [],
    })) as unknown as typeof IntersectionObserver;
    window.history.pushState({}, "", "/tickets");
    mockGetSiteBranding.mockReturnValue({
      scope: "primary",
      appName: "OIT Helpdesk",
      dashboardName: "OIT Dashboard",
      alertPrefix: "OIT",
    });
    mockApi.getTickets.mockResolvedValue({
      tickets: [ticketRow],
      matched_count: 1,
      total_count: 1,
    });
    mockApi.refreshVisibleTickets.mockResolvedValue({
      requested_count: 1,
      visible_count: 1,
      refreshed_count: 1,
      refreshed_keys: ["OIT-1"],
      skipped_keys: [],
      missing_keys: [],
    });
    mockApi.getFilterOptions.mockResolvedValue({
      statuses: ["Open"],
      priorities: ["High"],
      issue_types: ["Incident"],
      labels: ["hardware"],
    });
    mockApi.getAssignees.mockResolvedValue([]);
    mockApi.getCacheStatus.mockResolvedValue({
      jira_base_url: "https://jira.example.com",
    });
    mockApi.getTicket.mockResolvedValue(ticketDetail);
    mockApi.getPriorities.mockResolvedValue([{ id: "1", name: "High" }]);
    mockApi.getRequestTypes.mockResolvedValue([{ id: "1", name: "Hardware", description: "" }]);
    mockApi.getTransitions.mockResolvedValue([]);
    mockApi.createTicket.mockResolvedValue({
      created_key: "OIT-500",
      created_id: "100500",
      detail: {
        ...ticketDetail,
        ticket: {
          ...ticketRow,
          key: "OIT-500",
          summary: "Newly created ticket",
          priority: "High",
          request_type: "Hardware",
        },
      },
    });
    mockApi.getMe.mockResolvedValue({
      email: "test@example.com",
      name: "Test User",
      is_admin: true,
      can_manage_users: true,
      jira_auth: { connected: false, mode: "fallback_it_app", site_url: "", account_name: "", configured: true },
    });
  });

  afterEach(() => {
    globalThis.IntersectionObserver = originalIntersectionObserver;
  });

  it("opens the local ticket view when the key link is clicked", async () => {
    const user = userEvent.setup();

    render(<TicketsPage />);

    const ticketLink = await screen.findByRole("link", { name: "OIT-1" });
    expect(ticketLink).toHaveAttribute("href", "/tickets?ticket=OIT-1");

    await user.click(ticketLink);

    await waitFor(() => {
      expect(window.location.search).toBe("?ticket=OIT-1");
    });
    await screen.findByText("Ticket Actions");
    expect(mockApi.getTicket).toHaveBeenCalledWith("OIT-1");
  });

  it("supports a kanban view that preserves local ticket links", async () => {
    const user = userEvent.setup();

    render(<TicketsPage />);

    await user.click(screen.getByRole("button", { name: "Kanban" }));

    await waitFor(() => {
      expect(window.location.search).toBe("?view=kanban");
    });

    await screen.findByText("To Do");
    const ticketLink = await screen.findByRole("link", { name: "OIT-1" });
    expect(ticketLink.getAttribute("href")).toContain("view=kanban");
    expect(ticketLink.getAttribute("href")).toContain("ticket=OIT-1");

    await user.click(ticketLink);

    await waitFor(() => {
      expect(window.location.search).toBe("?view=kanban&ticket=OIT-1");
    });
    await screen.findByText("Ticket Actions");
    expect(mockApi.getTicket).toHaveBeenCalledWith("OIT-1");
  });

  it("refreshes the displayed tickets from Jira", async () => {
    const user = userEvent.setup();

    render(<TicketsPage />);

    const refreshButton = await screen.findByRole("button", { name: "Refresh Visible" });
    await user.click(refreshButton);

    await waitFor(() => {
      expect(mockApi.refreshVisibleTickets).toHaveBeenCalledWith(["OIT-1"]);
    });
  });

  it("shows a create ticket button on it-app for Jira write users", async () => {
    render(<TicketsPage />);

    expect(await screen.findByRole("button", { name: "Create Ticket" })).toBeInTheDocument();
  });

  it("does not show the create ticket button on non-primary hosts", async () => {
    mockGetSiteBranding.mockReturnValue({
      scope: "azure",
      appName: "MoveDocs Azure Portal",
      dashboardName: "Azure Control Center",
      alertPrefix: "Azure",
    });

    render(<TicketsPage />);

    await screen.findByRole("link", { name: "OIT-1" });
    expect(screen.queryByRole("button", { name: "Create Ticket" })).not.toBeInTheDocument();
  });

  it("creates a ticket and opens it in the drawer", async () => {
    const user = userEvent.setup();

    render(<TicketsPage />);

    await user.click(await screen.findByRole("button", { name: "Create Ticket" }));
    const dialog = await screen.findByRole("dialog", { name: "Create Ticket" });
    const dialogScope = within(dialog);

    const submitButton = dialogScope.getByRole("button", { name: "Create Ticket" });
    expect(submitButton).toBeDisabled();

    await user.type(dialogScope.getByLabelText("Summary"), "Newly created ticket");
    await user.selectOptions(dialogScope.getByLabelText("Priority"), "High");
    await user.selectOptions(dialogScope.getByLabelText("Request Type"), "1");
    await user.type(dialogScope.getByLabelText("Description"), "Created from MoveDocs.");

    expect(dialogScope.getByRole("button", { name: "Create Ticket" })).toBeEnabled();
    await user.click(dialogScope.getByRole("button", { name: "Create Ticket" }));

    await waitFor(() => {
      expect(mockApi.createTicket).toHaveBeenCalledWith({
        summary: "Newly created ticket",
        description: "Created from MoveDocs.",
        priority: "High",
        request_type_id: "1",
      });
    });
    await waitFor(() => {
      expect(window.location.search).toBe("?ticket=OIT-500");
    });
    await screen.findByText("Ticket Actions");
  });

  it("renders large ticket pages progressively", async () => {
    const manyTickets = Array.from({ length: 90 }, (_, index) => ({
      ...ticketRow,
      key: `OIT-${index + 1}`,
      summary: `Printer issue ${index + 1}`,
    }));
    mockApi.getTickets.mockResolvedValue({
      tickets: manyTickets,
      matched_count: manyTickets.length,
      total_count: manyTickets.length,
    });

    render(<TicketsPage />);

    await screen.findByText("Showing 75 of 90 tickets on this page — scroll for more");
    expect(screen.getByRole("link", { name: "OIT-75" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "OIT-90" })).not.toBeInTheDocument();
  });

  it("stays stable when tickets resolve after an initial loading render", async () => {
    type TicketListResult = {
      tickets: Array<typeof ticketRow>;
      matched_count: number;
      total_count: number;
    };
    let resolveTickets: ((value: TicketListResult) => void) | undefined;
    mockApi.getTickets.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveTickets = resolve;
        }),
    );

    render(<TicketsPage />);
    await screen.findByText("Loading ticket count...");

    if (!resolveTickets) {
      throw new Error("Ticket resolver was not captured");
    }

    resolveTickets({
      tickets: [ticketRow],
      matched_count: 1,
      total_count: 1,
    });

    await screen.findByRole("link", { name: "OIT-1" });
    expect(screen.getAllByText((_, element) => element?.textContent === "1 tickets").length).toBeGreaterThan(0);
  });
});
