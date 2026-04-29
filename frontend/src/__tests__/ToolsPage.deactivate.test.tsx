/**
 * Tests for the offboarding section of ToolsPage.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import ToolsPage from "../pages/ToolsPage.tsx";

const { mockApi, OFFBOARDING_LANES_VALUES } = vi.hoisted(() => ({
  mockApi: {
    getMe: vi.fn(),
    searchOneDriveCopyUsers: vi.fn(),
    listOneDriveCopyJobs: vi.fn(),
    clearFinishedOneDriveCopyJobs: vi.fn(),
    getOneDriveCopyJob: vi.fn(),
    createOneDriveCopyJob: vi.fn(),
    listLoginAudit: vi.fn(),
    listMailboxRules: vi.fn(),
    listMailboxDelegates: vi.fn(),
    listDelegateMailboxes: vi.fn(),
    listDelegateMailboxJobs: vi.fn(),
    clearFinishedDelegateMailboxJobs: vi.fn(),
    getDelegateMailboxJob: vi.fn(),
    createDelegateMailboxJob: vi.fn(),
    cancelDelegateMailboxJob: vi.fn(),
    runEmailgisticsHelper: vi.fn(),
    createOffboardingRun: vi.fn(),
    getOffboardingRun: vi.fn(),
    listOffboardingRuns: vi.fn(),
    retryOffboardingLane: vi.fn(),
    launchExitWorkflowFromTools: vi.fn(),
    offboardingRunCsvUrl: vi.fn(),
    setAutoReply: vi.fn(),
    getAutoReply: vi.fn(),
  },
  OFFBOARDING_LANES_VALUES: [
    "entra_disable",
    "entra_revoke",
    "entra_reset_pw",
    "entra_group_cleanup",
    "entra_group_validate",
    "entra_license_cleanup",
    "ad_disable",
    "ad_reset_pw",
    "ad_group_cleanup",
    "ad_attribute_cleanup",
    "ad_move_ou",
  ] as const,
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
  OFFBOARDING_LANES: OFFBOARDING_LANES_VALUES,
}));

vi.mock("../lib/siteContext.ts", () => ({
  getSiteBranding: () => ({
    scope: "primary",
    appName: "OIT Helpdesk",
    dashboardName: "OIT Dashboard",
    alertPrefix: "OIT",
  }),
}));

const userWithAD = {
  id: "user-1",
  display_name: "Jane Doe",
  principal_name: "jane@example.com",
  mail: "jane@example.com",
  enabled: true,
  source: "entra" as const,
  on_prem_sam: "jdoe",
};

const userWithoutAD = {
  id: "user-2",
  display_name: "Cloud Only",
  principal_name: "cloud@example.com",
  mail: "cloud@example.com",
  enabled: true,
  source: "entra" as const,
  on_prem_sam: "",
};

function setupDefaultMocks() {
  mockApi.getMe.mockResolvedValue({
    email: "admin@example.com",
    name: "Admin",
    is_admin: true,
    can_manage_users: true,
    can_access_tools: true,
  });
  mockApi.searchOneDriveCopyUsers.mockResolvedValue([]);
  mockApi.listOneDriveCopyJobs.mockResolvedValue([]);
  mockApi.clearFinishedOneDriveCopyJobs.mockResolvedValue({ deleted_count: 0 });
  mockApi.getOneDriveCopyJob.mockResolvedValue(null);
  mockApi.createOneDriveCopyJob.mockResolvedValue(null);
  mockApi.listLoginAudit.mockResolvedValue([]);
  mockApi.listMailboxRules.mockResolvedValue({
    mailbox: "",
    display_name: "",
    principal_name: "",
    primary_address: "",
    provider_enabled: true,
    note: "",
    rule_count: 0,
    rules: [],
  });
  mockApi.listMailboxDelegates.mockResolvedValue({
    mailbox: "",
    display_name: "",
    principal_name: "",
    primary_address: "",
    provider_enabled: true,
    supported_permission_types: [],
    permission_counts: { send_on_behalf: 0, send_as: 0, full_access: 0 },
    note: "",
    delegate_count: 0,
    delegates: [],
  });
  mockApi.listDelegateMailboxes.mockResolvedValue({ mailboxes: [] });
  mockApi.listDelegateMailboxJobs.mockResolvedValue([]);
  mockApi.clearFinishedDelegateMailboxJobs.mockResolvedValue({ deleted_count: 0 });
  mockApi.getDelegateMailboxJob.mockResolvedValue(null);
  mockApi.createDelegateMailboxJob.mockResolvedValue({ job_id: "dj1", status: "queued" });
  mockApi.cancelDelegateMailboxJob.mockResolvedValue({ cancelled: true, message: "" });
  mockApi.runEmailgisticsHelper.mockResolvedValue({ status: "completed", steps: [] });
  mockApi.createOffboardingRun.mockResolvedValue({ run_id: "run-1", status: "queued" });
  mockApi.getOffboardingRun.mockResolvedValue(null);
  mockApi.listOffboardingRuns.mockResolvedValue([]);
  mockApi.retryOffboardingLane.mockResolvedValue({ run_id: "run-1", status: "requeued", lane: "entra_disable" });
  mockApi.launchExitWorkflowFromTools.mockResolvedValue({
    workflow_id: "wf-1",
    deep_link: "/users?workflow=wf-1",
  });
  mockApi.offboardingRunCsvUrl.mockReturnValue("/api/tools/offboarding-runs/run-1/csv");
  mockApi.setAutoReply.mockResolvedValue({});
  mockApi.getAutoReply.mockResolvedValue({ enabled: false, message: "" });
}

describe("ToolsPage — offboarding section", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/tools");
    setupDefaultMocks();
  });

  it("renders the Offboard user section for admins", async () => {
    render(<ToolsPage />);

    expect(await screen.findByText("Offboard user")).toBeInTheDocument();
  });

  it("hides the Offboard user section for non-admins", async () => {
    mockApi.getMe.mockResolvedValueOnce({
      email: "someone@example.com",
      name: "Someone",
      is_admin: false,
      can_manage_users: false,
      can_access_tools: true,
    });

    render(<ToolsPage />);

    await screen.findByText("Copy a full OneDrive to another user");
    expect(screen.queryByText("Offboard user")).not.toBeInTheDocument();
  });

  it("shows all 11 lane checkboxes after selecting a user with an AD account", async () => {
    mockApi.searchOneDriveCopyUsers.mockResolvedValue([userWithAD]);

    render(<ToolsPage />);

    await screen.findByText("Offboard user");

    const userInput = screen.getByLabelText("User to offboard");
    fireEvent.focus(userInput);
    fireEvent.change(userInput, { target: { value: "jane" } });
    fireEvent.click(await screen.findByRole("button", { name: /Jane Doe/i }));

    await waitFor(() => {
      // 11 lanes total — all should be visible
      // The "Lanes to execute" span is inside a header div; go up to the outer container
      const laneSection = screen.getByText("Lanes to execute").closest("div")?.parentElement;
      const laneCheckboxes = within(laneSection!).getAllByRole("checkbox");
      expect(laneCheckboxes).toHaveLength(11);
    });
  });

  it("hides AD lanes when selected user has no on_prem_sam", async () => {
    mockApi.searchOneDriveCopyUsers.mockResolvedValue([userWithoutAD]);

    render(<ToolsPage />);

    await screen.findByText("Offboard user");

    const userInput = screen.getByLabelText("User to offboard");
    fireEvent.focus(userInput);
    fireEvent.change(userInput, { target: { value: "cloud" } });
    fireEvent.click(await screen.findByRole("button", { name: /Cloud Only/i }));

    await waitFor(() => {
      const laneSection = screen.getByText("Lanes to execute").closest("div")?.parentElement;
      const laneCheckboxes = within(laneSection!).getAllByRole("checkbox");
      // Only the 6 Entra lanes visible
      expect(laneCheckboxes).toHaveLength(6);
    });
  });

  it("calls createOffboardingRun with selected lanes when Run offboarding is clicked", async () => {
    mockApi.searchOneDriveCopyUsers.mockResolvedValue([userWithAD]);

    render(<ToolsPage />);

    await screen.findByText("Offboard user");

    const userInput = screen.getByLabelText("User to offboard");
    fireEvent.focus(userInput);
    fireEvent.change(userInput, { target: { value: "jane" } });
    fireEvent.click(await screen.findByRole("button", { name: /Jane Doe/i }));

    await waitFor(() => screen.getAllByRole("checkbox").length > 0);

    fireEvent.click(screen.getByRole("button", { name: "Run offboarding" }));

    await waitFor(() => {
      expect(mockApi.createOffboardingRun).toHaveBeenCalledWith(
        expect.objectContaining({
          entra_user_id: "user-1",
          ad_sam: "jdoe",
          display_name: "Jane Doe",
          lanes: expect.arrayContaining(["entra_disable", "ad_disable"]),
        }),
      );
    });
  });

  it("polls getOffboardingRun after run is created and shows step statuses", async () => {
    mockApi.searchOneDriveCopyUsers.mockResolvedValue([userWithAD]);
    mockApi.createOffboardingRun.mockResolvedValue({ run_id: "run-1", status: "queued" });
    mockApi.getOffboardingRun.mockResolvedValue({
      run_id: "run-1",
      entra_user_id: "user-1",
      ad_sam: "jdoe",
      display_name: "Jane Doe",
      actor_email: "admin@example.com",
      lanes_requested: ["entra_disable"],
      status: "completed",
      has_errors: false,
      created_at: "2026-04-01T00:00:00Z",
      started_at: "2026-04-01T00:00:01Z",
      finished_at: "2026-04-01T00:00:05Z",
      steps: [
        {
          step_id: "s1",
          run_id: "run-1",
          lane: "entra_disable",
          sequence: 0,
          status: "ok",
          message: "Disabled sign-in",
          detail: null,
          started_at: "2026-04-01T00:00:01Z",
          finished_at: "2026-04-01T00:00:02Z",
        },
      ],
    });

    render(<ToolsPage />);

    await screen.findByText("Offboard user");

    const userInput = screen.getByLabelText("User to offboard");
    fireEvent.focus(userInput);
    fireEvent.change(userInput, { target: { value: "jane" } });
    fireEvent.click(await screen.findByRole("button", { name: /Jane Doe/i }));

    await waitFor(() => screen.getAllByRole("checkbox").length > 0);

    fireEvent.click(screen.getByRole("button", { name: "Run offboarding" }));

    expect(await screen.findByText("Disabled sign-in")).toBeInTheDocument();
    expect(screen.getAllByText("Jane Doe").length).toBeGreaterThan(0);
  });

  it("shows Download CSV button once run reaches terminal status", async () => {
    mockApi.searchOneDriveCopyUsers.mockResolvedValue([userWithAD]);
    mockApi.createOffboardingRun.mockResolvedValue({ run_id: "run-1", status: "queued" });
    mockApi.offboardingRunCsvUrl.mockReturnValue("/api/tools/offboarding-runs/run-1/csv");
    mockApi.getOffboardingRun.mockResolvedValue({
      run_id: "run-1",
      entra_user_id: "user-1",
      ad_sam: "jdoe",
      display_name: "Jane Doe",
      actor_email: "admin@example.com",
      lanes_requested: ["entra_disable"],
      status: "completed",
      has_errors: false,
      created_at: "2026-04-01T00:00:00Z",
      started_at: "2026-04-01T00:00:01Z",
      finished_at: "2026-04-01T00:00:05Z",
      steps: [],
    });

    render(<ToolsPage />);

    await screen.findByText("Offboard user");

    const userInput = screen.getByLabelText("User to offboard");
    fireEvent.focus(userInput);
    fireEvent.change(userInput, { target: { value: "jane" } });
    fireEvent.click(await screen.findByRole("button", { name: /Jane Doe/i }));

    await waitFor(() => screen.getAllByRole("checkbox").length > 0);

    fireEvent.click(screen.getByRole("button", { name: "Run offboarding" }));

    const csvLink = await screen.findByRole("link", { name: "Download CSV" });
    expect(csvLink).toHaveAttribute("href", "/api/tools/offboarding-runs/run-1/csv");
  });

  it("calls launchExitWorkflowFromTools when Launch full Exit Workflow is clicked", async () => {
    mockApi.searchOneDriveCopyUsers.mockResolvedValue([userWithAD]);

    render(<ToolsPage />);

    await screen.findByText("Offboard user");

    const userInput = screen.getByLabelText("User to offboard");
    fireEvent.focus(userInput);
    fireEvent.change(userInput, { target: { value: "jane" } });
    fireEvent.click(await screen.findByRole("button", { name: /Jane Doe/i }));

    await waitFor(() => screen.getAllByRole("checkbox").length > 0);

    fireEvent.click(screen.getByRole("button", { name: "Launch full Exit Workflow" }));

    await waitFor(() => {
      expect(mockApi.launchExitWorkflowFromTools).toHaveBeenCalledWith(
        expect.objectContaining({ entra_user_id: "user-1" }),
      );
    });
  });
});
