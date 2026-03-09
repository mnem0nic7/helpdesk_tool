import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import AlertsPage from "../pages/AlertsPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAlertRules: vi.fn(),
    getAlertTriggerTypes: vi.fn(),
    getAlertHistory: vi.fn(),
    getFilterOptions: vi.fn(),
    getAssignees: vi.fn(),
    getRequestTypes: vi.fn(),
    createAlertRule: vi.fn(),
    updateAlertRule: vi.fn(),
    deleteAlertRule: vi.fn(),
    toggleAlertRule: vi.fn(),
    testAlertRule: vi.fn(),
    sendAlertRule: vi.fn(),
    runAlerts: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

describe("AlertsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAlertRules.mockResolvedValue([]);
    mockApi.getAlertTriggerTypes.mockResolvedValue([
      { value: "stale", label: "Stale Tickets" },
      { value: "new_ticket", label: "New Tickets" },
    ]);
    mockApi.getAlertHistory.mockResolvedValue([]);
    mockApi.getFilterOptions.mockResolvedValue({
      statuses: [],
      priorities: ["Highest", "High"],
      issue_types: [],
      labels: [],
    });
    mockApi.getAssignees.mockResolvedValue([
      { account_id: "acct-1", display_name: "Ada Lovelace" },
    ]);
    mockApi.getRequestTypes.mockResolvedValue([
      { id: "rt-1", name: "Security Alert", description: "" },
      { id: "rt-2", name: "Hardware", description: "" },
    ]);
    mockApi.createAlertRule.mockResolvedValue({
      id: 1,
      name: "Security Intake",
      enabled: true,
      trigger_type: "new_ticket",
      trigger_config: {},
      frequency: "immediate",
      schedule_time: "08:00",
      schedule_days: "0,1,2,3,4",
      recipients: "security@example.com",
      cc: "",
      custom_subject: "",
      custom_message: "",
      filters: {
        priorities: ["High"],
        assignees: ["Ada Lovelace"],
        request_types: ["Security Alert"],
      },
      last_run: null,
      last_sent: null,
      created_at: "2026-03-09T12:00:00Z",
      updated_at: "2026-03-09T12:00:00Z",
    });
  });

  it("uses dropdown filters in the alert rule modal", async () => {
    const user = userEvent.setup();

    render(<AlertsPage />);

    await user.click(await screen.findByRole("button", { name: "+ New Alert Rule" }));

    expect(screen.queryByPlaceholderText("Highest, High")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("John Doe")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Security Alert, Business Application Support")).not.toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("e.g. Daily Stale Ticket Alert"), "Security Intake");
    await user.type(screen.getByPlaceholderText("alice@example.com, bob@example.com"), "security@example.com");

    await user.click(screen.getByRole("button", { name: "Any priority ▼" }));
    await user.click(await screen.findByRole("checkbox", { name: "High" }));

    await user.click(screen.getByRole("button", { name: "Any assignee ▼" }));
    await user.click(await screen.findByRole("checkbox", { name: "Ada Lovelace" }));

    await user.click(screen.getByRole("button", { name: "Any request type ▼" }));
    await user.click(await screen.findByRole("checkbox", { name: "Security Alert" }));

    await user.click(screen.getByRole("button", { name: "Create Rule" }));

    await waitFor(() => {
      expect(mockApi.createAlertRule).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Security Intake",
          recipients: "security@example.com",
          filters: {
            priorities: ["High"],
            assignees: ["Ada Lovelace"],
            request_types: ["Security Alert"],
          },
        }),
      );
    });
  });
});
