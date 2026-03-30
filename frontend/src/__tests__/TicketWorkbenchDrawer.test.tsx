import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import TicketWorkbenchDrawer from "../components/TicketWorkbenchDrawer.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getTicket: vi.fn(),
    getTicketComponents: vi.fn(),
    getFilterOptions: vi.fn(),
    getAssignees: vi.fn(),
    searchUsers: vi.fn(),
    getPriorities: vi.fn(),
    getRequestTypes: vi.fn(),
    getTransitions: vi.fn(),
    getTechnicianScores: vi.fn(),
    getMe: vi.fn(),
    fetchAttachmentPreviewBlob: vi.fn(),
    fetchAttachmentPreviewText: vi.fn(),
    syncTicketRequestor: vi.fn(),
    updateTicket: vi.fn(),
    transitionTicket: vi.fn(),
    addTicketComment: vi.fn(),
    removeOasisDevLabel: vi.fn(),
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
  reporter_account_id: "acct-grace",
  created: "2026-03-01T10:00:00Z",
  updated: "2026-03-02T12:00:00Z",
  resolved: "",
  request_type: "Hardware",
  request_type_id: "1",
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
  response_followup_status: "Running",
  first_response_2h_status: "Running",
  daily_followup_status: "Running",
  last_support_touch_date: "",
  support_touch_count: 0,
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
  requestor_identity: {
    extracted_email: "grace.hopper@example.com",
    directory_match: true,
    jira_account_id: "",
    jira_status: "match_pending",
    message: "Exact Office 365 directory match found.",
    match_source: "reporter_email",
  },
  raw_issue: {},
};

const historyComments = [
  {
    id: "c-3",
    author: "Ada Lovelace",
    created: "2026-03-03T10:00:00Z",
    updated: "2026-03-03T10:00:00Z",
    body: "We reset the print queue and the printer is back online.",
    public: true,
  },
  {
    id: "c-2",
    author: "Grace Hopper",
    created: "2026-03-02T14:00:00Z",
    updated: "2026-03-02T14:00:00Z",
    body: "Printer issue acknowledged by support and under investigation.",
    public: false,
  },
  {
    id: "c-1",
    author: "Support Bot",
    created: "2026-03-01T09:00:00Z",
    updated: "2026-03-01T09:00:00Z",
    body: "Initial customer report captured from the service portal.",
    public: true,
  },
];

describe("TicketWorkbenchDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(globalThis.URL, "createObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(() => "blob:preview-object-url"),
    });
    Object.defineProperty(globalThis.URL, "revokeObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      writable: true,
      value: 1400,
    });
    mockApi.getTicket.mockResolvedValue(ticketDetail);
    mockApi.getTicketComponents.mockResolvedValue(["Portal", "VPN", "Underwriting"]);
    mockApi.getFilterOptions.mockResolvedValue({
      statuses: [],
      priorities: [],
      issue_types: [],
      labels: [],
      components: ["Portal", "VPN"],
      work_categories: ["Support", "Identity"],
    });
    mockApi.getAssignees.mockResolvedValue([]);
    mockApi.searchUsers.mockResolvedValue([]);
    mockApi.getPriorities.mockResolvedValue([{ id: "1", name: "High" }]);
    mockApi.getRequestTypes.mockResolvedValue([{ id: "1", name: "Hardware", description: "" }]);
    mockApi.getTransitions.mockResolvedValue([]);
    mockApi.getTechnicianScores.mockResolvedValue([]);
    mockApi.fetchAttachmentPreviewBlob.mockResolvedValue(new Blob(["preview"], { type: "image/png" }));
    mockApi.fetchAttachmentPreviewText.mockResolvedValue("preview text");
    mockApi.getMe.mockResolvedValue({
      email: "test@example.com",
      name: "Test User",
      is_admin: true,
      jira_auth: { connected: false, mode: "fallback_it_app", site_url: "", account_name: "", configured: true },
    });
    mockApi.syncTicketRequestor.mockResolvedValue({
      updated: true,
      message: "Reporter synced to Grace Hopper.",
      detail: {
        ...ticketDetail,
        requestor_identity: {
          ...ticketDetail.requestor_identity,
          jira_account_id: "acct-grace",
          jira_status: "updated_reporter",
          message: "Reporter synced to Grace Hopper.",
          match_source: "reporter_email",
        },
      },
    });
  });

  it("resizes wider when the drag handle is moved left", async () => {
    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Ticket Actions");

    const drawer = screen.getByTestId("ticket-workbench-drawer");
    const resizer = screen.getByTestId("ticket-workbench-resizer");

    expect(drawer).toHaveStyle({ width: "768px" });

    fireEvent.pointerDown(resizer, { clientX: 632 });

    await waitFor(() => {
      expect(document.body).toHaveStyle({ cursor: "col-resize" });
    });

    fireEvent.mouseMove(window, { clientX: 500 });

    await waitFor(() => {
      expect(drawer).toHaveStyle({ width: "900px" });
    });

    fireEvent.mouseUp(window);
  });

  it("toggles between default and expanded drawer widths", async () => {
    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Ticket Actions");

    const drawer = screen.getByTestId("ticket-workbench-drawer");
    expect(drawer).toHaveStyle({ width: "768px" });

    fireEvent.click(screen.getByRole("button", { name: "Expand" }));

    await waitFor(() => {
      expect(drawer).toHaveStyle({ width: "1368px" });
    });

    fireEvent.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() => {
      expect(drawer).toHaveStyle({ width: "768px" });
    });
  });

  it("opens a history popout with the full notes and communication timeline", async () => {
    mockApi.getTicket.mockResolvedValue({
      ...ticketDetail,
      comments: historyComments,
    });

    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByRole("button", { name: "See History" });

    expect(
      screen.queryByText("Initial customer report captured from the service portal."),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "See History" }));

    await screen.findByRole("dialog");
    expect(screen.getByText("Ticket History")).toBeInTheDocument();
    expect(
      screen.getByText("Initial customer report captured from the service portal."),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Customer Reply").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Internal Note").length).toBeGreaterThan(0);
  });

  it("shows friendly attachment names and previews supported files in-site", async () => {
    mockApi.getTicket.mockResolvedValue({
      ...ticketDetail,
      attachments: [
        {
          id: "att-1",
          filename: "10875238511763560924.png",
          raw_filename: "10875238511763560924.png",
          display_name: "OIT-1 - Image - 2026-03-03 10-14.png",
          extension: ".png",
          mime_type: "image/png",
          size: 12288,
          created: "2026-03-03T17:14:00Z",
          author: "Ada Lovelace",
          content_url: "/api/tickets/OIT-1/attachments/att-1/download",
          download_url: "/api/tickets/OIT-1/attachments/att-1/download",
          preview_url: "/api/tickets/OIT-1/attachments/att-1/preview",
          converted_preview_url: "",
          preview_kind: "image",
          preview_available: true,
          thumbnail_url: "/api/tickets/OIT-1/attachments/att-1/preview",
        },
      ],
    });

    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Attachments");

    expect(screen.getByText("OIT-1 - Image - 2026-03-03 10-14.png")).toBeInTheDocument();
    expect(screen.getByText("Jira file: 10875238511763560924.png")).toBeInTheDocument();
    expect(screen.getByAltText("OIT-1 - Image - 2026-03-03 10-14.png")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await screen.findByRole("dialog");
    await waitFor(() => {
      expect(mockApi.fetchAttachmentPreviewBlob).toHaveBeenCalledWith("/api/tickets/OIT-1/attachments/att-1/preview");
    });
    expect(screen.getAllByAltText("OIT-1 - Image - 2026-03-03 10-14.png").length).toBeGreaterThan(0);
  });

  it("shows requestor reconciliation status and lets admins trigger a sync", async () => {
    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Requestor Reconciliation");
    expect(screen.getByText("Match Pending")).toBeInTheDocument();
    expect(screen.getByText(/grace\.hopper@example\.com/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sync Requestor" }));

    await waitFor(() => {
      expect(mockApi.syncTicketRequestor).toHaveBeenCalledWith("OIT-1");
    });
    expect((await screen.findAllByText("Reporter synced to Grace Hopper.")).length).toBeGreaterThan(0);
  });

  it("shows ignored mailbox requestors as manual review instead of a synced match", async () => {
    mockApi.getTicket.mockResolvedValue({
      ...ticketDetail,
      reporter: "Email Quarantine",
      requestor_identity: {
        extracted_email: "emailquarantine@librasolutionsgroup.com",
        directory_match: false,
        jira_account_id: "",
        jira_status: "ignored_requestor_email",
        message:
          "emailquarantine@librasolutionsgroup.com is on the ignored requestor list. Reporter was left unchanged. Use the reporter search to set it manually.",
        match_source: "reporter_email",
      },
    });

    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={{ ...ticketRow, reporter: "Email Quarantine" }}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Requestor Reconciliation");
    expect(screen.getByText("Ignored Mailbox")).toBeInTheDocument();
    expect(screen.getAllByText(/emailquarantine@librasolutionsgroup\.com/i).length).toBeGreaterThan(0);
    expect(screen.queryByText("Office 365 Match")).not.toBeInTheDocument();
    expect(screen.getAllByText(/Reporter was left unchanged\. Use the reporter search/i).length).toBeGreaterThan(0);
  });

  it("renders office previews from the same-origin preview URL instead of a blob iframe", async () => {
    mockApi.getTicket.mockResolvedValue({
      ...ticketDetail,
      attachments: [
        {
          id: "att-2",
          filename: "10875238511763560924.xlsx",
          raw_filename: "10875238511763560924.xlsx",
          display_name: "OIT-1 - Office Document - 2026-03-03 10-14.xlsx",
          extension: ".xlsx",
          mime_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          size: 20480,
          created: "2026-03-03T17:14:00Z",
          author: "Ada Lovelace",
          content_url: "/api/tickets/OIT-1/attachments/att-2/download",
          download_url: "/api/tickets/OIT-1/attachments/att-2/download",
          preview_url: "/api/tickets/OIT-1/attachments/att-2/preview-converted",
          converted_preview_url: "/api/tickets/OIT-1/attachments/att-2/preview-converted",
          preview_kind: "office",
          preview_available: true,
          thumbnail_url: "",
        },
      ],
    });

    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Attachments");

    fireEvent.click(screen.getByRole("button", { name: "Preview Document" }));

    const iframe = await screen.findByTitle("OIT-1 - Office Document - 2026-03-03 10-14.xlsx preview");
    expect(iframe).toHaveAttribute("src", "/api/tickets/OIT-1/attachments/att-2/preview-converted");
    expect(mockApi.fetchAttachmentPreviewBlob).not.toHaveBeenCalled();
  });

  it("lets the user manually change the reporter before saving", async () => {
    mockApi.searchUsers.mockResolvedValue([
      { account_id: "acct-raza", display_name: "Raza Abidi", email_address: "raza@example.com" },
    ]);
    mockApi.updateTicket.mockResolvedValue({
      ...ticketDetail,
      ticket: {
        ...ticketRow,
        reporter: "Raza Abidi",
        reporter_account_id: "acct-raza",
      },
    });

    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Ticket Actions");

    fireEvent.change(screen.getByLabelText("Reporter"), {
      target: { value: "Raza Abidi" },
    });

    await waitFor(() => {
      expect(mockApi.searchUsers).toHaveBeenCalledWith("Raza Abidi");
    });

    fireEvent.change(screen.getByRole("combobox", { name: "Reporter Matches" }), {
      target: { value: "acct-raza" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Ticket Details" }));

    await waitFor(() => {
      expect(mockApi.updateTicket).toHaveBeenCalledWith("OIT-1", {
        reporter_account_id: "acct-raza",
        reporter_display_name: "Raza Abidi",
      });
    });
  });

  it("lets the user update application and operational categorization before saving", async () => {
    mockApi.updateTicket.mockResolvedValue({
      ...ticketDetail,
      ticket: {
        ...ticketRow,
        components: ["Portal", "VPN"],
      },
      work_category: "Identity",
    });

    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Ticket Actions");

    fireEvent.change(screen.getByPlaceholderText("Portal, Outlook, VPN"), {
      target: { value: "Portal, VPN" },
    });
    fireEvent.change(screen.getByPlaceholderText("Identity"), {
      target: { value: "Identity" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Ticket Details" }));

    await waitFor(() => {
      expect(mockApi.updateTicket).toHaveBeenCalledWith("OIT-1", {
        components: ["Portal", "VPN"],
        work_category: "Identity",
      });
    });
  });

  it("shows Jira editable components in the application suggestions", async () => {
    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Ticket Actions");

    await waitFor(() => {
      expect(mockApi.getTicketComponents).toHaveBeenCalledWith("OIT-1");
    });

    const options = document.querySelectorAll("#ticket-application-options option");
    expect(Array.from(options).map((option) => option.getAttribute("value"))).toEqual([
      "Portal",
      "Underwriting",
      "VPN",
    ]);
  });

  it("uses a wrapping summary editor and normalizes pasted line breaks before saving", async () => {
    mockApi.updateTicket.mockResolvedValue({
      ...ticketDetail,
      ticket: {
        ...ticketRow,
        summary: "Printer is offline please investigate asap",
      },
    });

    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    const summaryField = await screen.findByLabelText("Summary");
    expect(summaryField.tagName).toBe("TEXTAREA");
    await screen.findByDisplayValue("Printer is offline");

    fireEvent.change(summaryField, {
      target: { value: "Printer is offline\nplease investigate asap" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Ticket Details" }));

    await waitFor(() => {
      expect(mockApi.updateTicket).toHaveBeenCalledWith("OIT-1", {
        summary: "Printer is offline please investigate asap",
      });
    });
  });

  it("shows the current request type in the drawer when live detail loses it", async () => {
    mockApi.getTicket.mockResolvedValue({
      ...ticketDetail,
      ticket: {
        ...ticketRow,
        request_type: "",
        request_type_id: "",
      },
      request_type: "",
    });
    mockApi.getRequestTypes.mockResolvedValue([
      { id: "2", name: "Account access", description: "" },
    ]);

    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Ticket Actions");

    expect(screen.getByRole("combobox", { name: /request type/i })).toHaveDisplayValue("Hardware");
  });

  it("does not render the legacy update reporter button", async () => {
    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Ticket Actions");
    expect(screen.queryByRole("button", { name: "Update Reporter" })).not.toBeInTheDocument();
  });

  it("shows the technician QA scorecard at the bottom of the drawer", async () => {
    mockApi.getTechnicianScores.mockResolvedValue([
      {
        key: "OIT-1",
        communication_score: 4,
        communication_notes: "The customer got a clear and timely update.",
        documentation_score: 3,
        documentation_notes: "Resolution notes could be more specific.",
        overall_score: 3.5,
        score_summary: "Good customer communication with average documentation.",
        model_used: "qwen2.5:7b",
        created_at: "2026-03-04T12:00:00+00:00",
        ticket_summary: ticketRow.summary,
        ticket_status: ticketRow.status,
        ticket_assignee: ticketRow.assignee,
        ticket_resolved: "",
      },
    ]);

    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={ticketRow}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Technician QA");

    expect(mockApi.getTechnicianScores).toHaveBeenCalledWith({ key: "OIT-1" });
    expect(screen.getByText("3.5/5")).toBeInTheDocument();
    expect(screen.getByText("The customer got a clear and timely update.")).toBeInTheDocument();
    expect(screen.getByText("Resolution notes could be more specific.")).toBeInTheDocument();
    expect(screen.getByText("Good customer communication with average documentation.")).toBeInTheDocument();
  });

  it("hides duplicate status labels in the drawer transition list", async () => {
    mockApi.getTicket.mockResolvedValue({
      ...ticketDetail,
      ticket: {
        ...ticketRow,
        status: "Acknowledged",
      },
    });
    mockApi.getTransitions.mockResolvedValue([
      { id: "11", name: "Keep Acknowledged", to_status: "Acknowledged" },
      { id: "21", name: "Start Work", to_status: "In Progress" },
      { id: "22", name: "Begin Investigation", to_status: "In Progress" },
      { id: "31", name: "Wait on Customer", to_status: "Waiting for customer" },
    ]);

    render(
      <TicketWorkbenchDrawer
        ticketKey="OIT-1"
        initialTicket={{ ...ticketRow, status: "Acknowledged" }}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Ticket Actions");

    const statusLabel = screen.getByText("Status").closest("label");
    expect(statusLabel).not.toBeNull();

    const statusSelect = within(statusLabel as HTMLLabelElement).getByRole("combobox");
    const optionLabels = within(statusSelect)
      .getAllByRole("option")
      .map((option) => option.textContent);

    expect(optionLabels).toEqual([
      "Acknowledged",
      "In Progress",
      "Waiting for customer",
    ]);
  });
});
