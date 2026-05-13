import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
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
    lookupPasswordExpiry: vi.fn(),
  },
  OFFBOARDING_LANES_VALUES: [
    "entra_disable",
    "entra_revoke",
    "entra_reset_pw",
    "entra_reset_mfa",
    "entra_group_cleanup",
    "entra_group_validate",
    "entra_license_cleanup",
    "mailbox_convert_shared",
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
    scope: "oasisdev",
    appName: "OIT Helpdesk",
    dashboardName: "OIT Dashboard",
    alertPrefix: "OIT",
  }),
}));

describe("ToolsPage (oasisdev scope)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/tools");
    mockApi.getMe.mockResolvedValue({
      email: "gallison@movedocs.com",
      name: "Gallison",
      is_admin: false,
      can_manage_users: false,
      can_access_tools: true,
    });
    mockApi.listOneDriveCopyJobs.mockResolvedValue([]);
    mockApi.listLoginAudit.mockResolvedValue([]);
    mockApi.listDelegateMailboxJobs.mockResolvedValue([]);
    mockApi.searchOneDriveCopyUsers.mockResolvedValue([]);
  });

  it("shows the password expiry lookup section", async () => {
    render(<ToolsPage />);
    expect(
      await screen.findByText("Look up when a user's password expires")
    ).toBeInTheDocument();
  });

  it("hides the OneDrive Copy section", async () => {
    render(<ToolsPage />);
    await screen.findByText("Look up when a user's password expires");
    expect(
      screen.queryByText("Copy a full OneDrive to another user")
    ).not.toBeInTheDocument();
  });

  it("hides the List Inbox Rules section", async () => {
    render(<ToolsPage />);
    await screen.findByText("Look up when a user's password expires");
    expect(
      screen.queryByText("List Inbox rules for a provided mailbox")
    ).not.toBeInTheDocument();
  });

  it("hides the mailbox delegate sections", async () => {
    render(<ToolsPage />);
    await screen.findByText("Look up when a user's password expires");
    expect(
      screen.queryByText("List mailbox delegate access for a mailbox")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Find mailboxes where a user has delegate access")
    ).not.toBeInTheDocument();
  });
});
