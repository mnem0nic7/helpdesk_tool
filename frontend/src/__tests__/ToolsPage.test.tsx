import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import ToolsPage from "../pages/ToolsPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getMe: vi.fn(),
    searchOneDriveCopyUsers: vi.fn(),
    listOneDriveCopyJobs: vi.fn(),
    getOneDriveCopyJob: vi.fn(),
    createOneDriveCopyJob: vi.fn(),
    listLoginAudit: vi.fn(),
    listMailboxRules: vi.fn(),
    listMailboxDelegates: vi.fn(),
    listDelegateMailboxes: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

vi.mock("../lib/siteContext.ts", () => ({
  getSiteBranding: () => ({
    scope: "primary",
    appName: "OIT Helpdesk",
    dashboardName: "OIT Dashboard",
    alertPrefix: "OIT",
  }),
}));

const baseJob = {
  job_id: "job-1",
  site_scope: "primary" as const,
  status: "running" as const,
  phase: "enumerating" as const,
  requested_by_email: "tech@example.com",
  requested_by_name: "Tech User",
  source_upn: "source@example.com",
  destination_upn: "dest@example.com",
  destination_folder: "CopiedFiles",
  test_mode: false,
  test_file_limit: 25,
  exclude_system_folders: true,
  requested_at: "2026-03-26T18:00:00Z",
  started_at: "2026-03-26T18:00:10Z",
  completed_at: null,
  progress_current: 3,
  progress_total: 10,
  progress_message: "Walking the full source OneDrive tree",
  total_folders_found: 5,
  total_files_found: 12,
  folders_created: 2,
  files_dispatched: 1,
  files_failed: 0,
  error: null,
  events: [
    {
      event_id: 1,
      level: "info" as const,
      message: "Queued copy from source@example.com to dest@example.com into 'CopiedFiles'.",
      created_at: "2026-03-26T18:00:00Z",
    },
  ],
};

describe("ToolsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/tools");
    mockApi.getMe.mockResolvedValue({
      email: "gallison@movedocs.com",
      name: "Gallison",
      is_admin: true,
      can_manage_users: true,
      can_access_tools: true,
    });
    mockApi.searchOneDriveCopyUsers.mockImplementation(async (search: string) => {
      const query = search.trim().toLowerCase();
      if (!query) return [];
      if (query.includes("source")) {
        return [
          {
            id: "user-source",
            display_name: "Source User",
            principal_name: "source@example.com",
            mail: "source@example.com",
            enabled: true,
            source: "entra" as const,
          },
        ];
      }
      if (query.includes("dest")) {
        return [
          {
            id: "saved:dest@example.com",
            display_name: "Dest User",
            principal_name: "dest@example.com",
            mail: "",
            enabled: null,
            source: "saved" as const,
          },
        ];
      }
      if (query.includes("ada")) {
        return [
          {
            id: "user-ada",
            display_name: "Ada Mailbox",
            principal_name: "ada@example.com",
            mail: "ada@example.com",
            enabled: true,
            source: "entra" as const,
          },
        ];
      }
      return [];
    });
    mockApi.listOneDriveCopyJobs.mockResolvedValue([baseJob]);
    mockApi.getOneDriveCopyJob.mockResolvedValue(baseJob);
    mockApi.listLoginAudit.mockResolvedValue([
      {
        event_id: 9,
        email: "gallison@movedocs.com",
        name: "Gallison",
        auth_provider: "atlassian",
        site_scope: "primary",
        source_ip: "10.0.0.1",
        user_agent: "Vitest",
        created_at: "2026-03-26T19:00:00Z",
      },
    ]);
    mockApi.listMailboxRules.mockResolvedValue({
      mailbox: "ada@example.com",
      display_name: "Ada Mailbox",
      principal_name: "ada@example.com",
      primary_address: "ada@example.com",
      provider_enabled: true,
      note: "Rules are listed read-only from the mailbox Inbox.",
      rule_count: 1,
      rules: [
        {
          id: "rule-1",
          display_name: "Move GitHub alerts",
          sequence: 1,
          is_enabled: true,
          has_error: false,
          stop_processing_rules: true,
          conditions_summary: ["From addresses: alerts@github.com"],
          exceptions_summary: [],
          actions_summary: ["Move to folder: GitHub", "Stop processing more rules"],
        },
      ],
    });
    mockApi.listMailboxDelegates.mockResolvedValue({
      mailbox: "shared@example.com",
      display_name: "Shared Mailbox",
      principal_name: "shared@example.com",
      primary_address: "shared@example.com",
      provider_enabled: true,
      supported_permission_types: ["send_on_behalf", "send_as", "full_access"],
      permission_counts: {
        send_on_behalf: 1,
        send_as: 1,
        full_access: 1,
      },
      note: "Mailbox delegates are listed read-only from Exchange Online for Send on behalf, Send As, and Full Access.",
      delegate_count: 2,
      delegates: [
        {
          identity: "delegate@example.com",
          display_name: "Delegate User",
          principal_name: "delegate@example.com",
          mail: "delegate@example.com",
          permission_types: ["send_on_behalf", "send_as"],
        },
        {
          identity: "ops@example.com",
          display_name: "Ops User",
          principal_name: "ops@example.com",
          mail: "ops@example.com",
          permission_types: ["full_access"],
        },
      ],
    });
    mockApi.listDelegateMailboxes.mockResolvedValue({
      user: "delegate@example.com",
      display_name: "Delegate User",
      principal_name: "delegate@example.com",
      primary_address: "delegate@example.com",
      provider_enabled: true,
      supported_permission_types: ["send_on_behalf", "send_as", "full_access"],
      permission_counts: {
        send_on_behalf: 1,
        send_as: 1,
        full_access: 1,
      },
      note: "Scanned 10 mailboxes for Send on behalf, Send As, and Full Access.",
      mailbox_count: 1,
      scanned_mailbox_count: 10,
      mailboxes: [
        {
          identity: "shared@example.com",
          display_name: "Shared Mailbox",
          principal_name: "shared@example.com",
          primary_address: "shared@example.com",
          permission_types: ["send_on_behalf", "send_as", "full_access"],
        },
      ],
    });
    mockApi.createOneDriveCopyJob.mockResolvedValue({
      ...baseJob,
      status: "queued",
      phase: "queued",
      progress_current: 0,
      progress_total: 0,
      progress_message: "Queued",
      events: [],
    });
  });

  it("renders the OneDrive copy tool and shared job details", async () => {
    render(<ToolsPage />);

    expect(await screen.findByText("Copy a full OneDrive to another user")).toBeInTheDocument();
    expect(screen.getByText("List mailbox delegate access for a mailbox")).toBeInTheDocument();
    expect(screen.getByText("Find mailboxes where a user has delegate access")).toBeInTheDocument();
    expect(screen.getByText("List Inbox rules for a provided mailbox")).toBeInTheDocument();
    expect(screen.getByText("Recent OneDrive copy jobs")).toBeInTheDocument();
    expect(await screen.findByText(/Graph copy requests finish server-side/i)).toBeInTheDocument();
    expect(screen.getByText("Recent app sign-ins")).toBeInTheDocument();
    expect(screen.getAllByText("Tech User").length).toBeGreaterThan(0);
    expect(screen.getByText("source@example.com to dest@example.com")).toBeInTheDocument();
  });

  it("submits the create-job request with the expected default advanced options", async () => {
    render(<ToolsPage />);

    await screen.findByText("Copy a full OneDrive to another user");

    const sourceInput = screen.getByLabelText("Source user UPN");
    fireEvent.focus(sourceInput);
    fireEvent.change(sourceInput, { target: { value: "source@example.com" } });
    fireEvent.click(await screen.findByRole("button", { name: /Source User/i }));
    const destinationInput = screen.getByLabelText("Destination user UPN");
    fireEvent.focus(destinationInput);
    fireEvent.change(destinationInput, { target: { value: "dest@example.com" } });
    fireEvent.click(await screen.findByRole("button", { name: /Dest User/i }));
    fireEvent.change(screen.getByLabelText("Destination folder name"), { target: { value: "CopiedFiles" } });
    fireEvent.click(screen.getByRole("button", { name: "Queue OneDrive Copy" }));

    await waitFor(() => {
      expect(mockApi.createOneDriveCopyJob).toHaveBeenCalledWith({
        source_upn: "source@example.com",
        destination_upn: "dest@example.com",
        destination_folder: "CopiedFiles",
        test_mode: false,
        test_file_limit: 25,
        exclude_system_folders: true,
      });
    });
  });

  it("loads mailbox rules for the selected mailbox", async () => {
    render(<ToolsPage />);

    await screen.findByText("List Inbox rules for a provided mailbox");

    const mailboxInputs = screen.getAllByLabelText("Mailbox UPN or email");
    fireEvent.focus(mailboxInputs[1]);
    fireEvent.change(mailboxInputs[1], { target: { value: "ada@example.com" } });
    fireEvent.click(await screen.findByRole("button", { name: /Ada Mailbox/i }));
    fireEvent.click(screen.getByRole("button", { name: "Load mailbox rules" }));

    await waitFor(() => {
      expect(mockApi.listMailboxRules).toHaveBeenCalledWith("ada@example.com");
    });

    expect(await screen.findByText("Move GitHub alerts")).toBeInTheDocument();
    expect(screen.getByText("From addresses: alerts@github.com")).toBeInTheDocument();
  });

  it("loads mailbox delegates for the selected mailbox", async () => {
    render(<ToolsPage />);

    await screen.findByText("List mailbox delegate access for a mailbox");

    const mailboxInputs = screen.getAllByLabelText("Mailbox UPN or email");
    fireEvent.focus(mailboxInputs[0]);
    fireEvent.change(mailboxInputs[0], { target: { value: "shared@example.com" } });
    fireEvent.click(await screen.findByRole("button", { name: /Use and save "shared@example.com"/i }));
    fireEvent.click(screen.getByRole("button", { name: "Load mailbox delegates" }));

    await waitFor(() => {
      expect(mockApi.listMailboxDelegates).toHaveBeenCalledWith("shared@example.com");
    });

    expect(await screen.findByText("Delegate User")).toBeInTheDocument();
    expect(screen.getByText("Ops User")).toBeInTheDocument();
    expect(screen.getAllByText("Full Access").length).toBeGreaterThan(0);
  });

  it("scans for mailboxes where the selected user has delegate access", async () => {
    render(<ToolsPage />);

    await screen.findByText("Find mailboxes where a user has delegate access");

    const userInput = screen.getByLabelText("User UPN or email");
    fireEvent.focus(userInput);
    fireEvent.change(userInput, { target: { value: "delegate@example.com" } });
    fireEvent.click(await screen.findByRole("button", { name: /Use and save "delegate@example.com"/i }));
    fireEvent.click(screen.getByRole("button", { name: "Find delegate mailboxes" }));

    await waitFor(() => {
      expect(mockApi.listDelegateMailboxes).toHaveBeenCalledWith("delegate@example.com");
    });

    expect(await screen.findByText("Scanned 10 mailboxes for Send on behalf, Send As, and Full Access.")).toBeInTheDocument();
    expect(screen.getAllByText("Shared Mailbox").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Send As").length).toBeGreaterThan(0);
  });

  it("renders tools for signed-in users even if the legacy tools-access flag is false", async () => {
    mockApi.getMe.mockResolvedValueOnce({
      email: "someone@example.com",
      name: "Someone",
      is_admin: false,
      can_manage_users: false,
      can_access_tools: false,
    });

    render(<ToolsPage />);

    expect(await screen.findByText("Copy a full OneDrive to another user")).toBeInTheDocument();
    expect(screen.queryByText("Tools access is limited")).not.toBeInTheDocument();
  });
});
