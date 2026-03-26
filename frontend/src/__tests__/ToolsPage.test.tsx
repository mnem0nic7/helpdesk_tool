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
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
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
    window.history.replaceState({}, "", "https://it-app.movedocs.com/tools");
    mockApi.getMe.mockResolvedValue({
      email: "gallison@movedocs.com",
      name: "Gallison",
      is_admin: true,
      can_manage_users: true,
      can_access_tools: true,
    });
    mockApi.searchOneDriveCopyUsers.mockResolvedValue([]);
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
    expect(screen.getByText("Recent OneDrive copy jobs")).toBeInTheDocument();
    expect(await screen.findByText(/Graph copy requests finish server-side/i)).toBeInTheDocument();
    expect(screen.getByText("Recent app sign-ins")).toBeInTheDocument();
    expect(screen.getByText("Tech User")).toBeInTheDocument();
    expect(screen.getByText("source@example.com to dest@example.com")).toBeInTheDocument();
  });

  it("submits the create-job request with the expected default advanced options", async () => {
    render(<ToolsPage />);

    await screen.findByText("Copy a full OneDrive to another user");

    fireEvent.change(screen.getByLabelText("Source user UPN"), { target: { value: "source@example.com" } });
    fireEvent.change(screen.getByLabelText("Destination user UPN"), { target: { value: "dest@example.com" } });
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
});
