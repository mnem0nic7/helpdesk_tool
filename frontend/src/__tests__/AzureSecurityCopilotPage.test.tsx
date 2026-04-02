import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureSecurityCopilotPage from "../pages/AzureSecurityCopilotPage.tsx";

const clipboardWriteText = vi.fn();

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureAIModels: vi.fn(),
    getAzureStatus: vi.fn(),
    chatAzureSecurityCopilot: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

function buildResponse(overrides: Record<string, unknown> = {}) {
  return {
    phase: "needs_input",
    assistant_message: "I need the timeframe and affected mailbox before I query sources.",
    incident: {
      lane: "mailbox_abuse",
      summary: "Shared mailbox is forwarding mail externally.",
      timeframe: "",
      affected_users: ["payroll@example.com"],
      affected_mailboxes: ["payroll@example.com"],
      affected_apps: [],
      affected_resources: [],
      alert_names: [],
      observed_artifacts: [],
      identity_query: "",
      identity_candidates: [],
      confidence: 0.8,
      missing_fields: ["timeframe", "affected_mailboxes"],
    },
    follow_up_questions: [
      {
        key: "timeframe",
        label: "Timeframe",
        prompt: "When did this start?",
        placeholder: "Since 2 AM UTC",
        required: true,
        input_type: "text",
        choices: [],
      },
      {
        key: "affected_mailboxes",
        label: "Affected mailbox",
        prompt: "Which mailbox is involved?",
        placeholder: "payroll@example.com",
        required: true,
        input_type: "email",
        choices: [],
      },
    ],
    planned_sources: [
      {
        key: "mailbox_rules",
        label: "Mailbox inbox rules",
        status: "planned",
        query_summary: "payroll@example.com",
        reason: "",
      },
      {
        key: "mailbox_delegates",
        label: "Mailbox delegates",
        status: "planned",
        query_summary: "payroll@example.com",
        reason: "",
      },
    ],
    source_results: [],
    jobs: [],
    answer: { summary: "", findings: [], next_steps: [], warnings: [] },
    citations: [],
    model_used: "qwen3.5:4b",
    generated_at: "2026-04-02T02:00:00Z",
    ...overrides,
  };
}

describe("AzureSecurityCopilotPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    Object.defineProperty(globalThis.URL, "createObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(() => "blob:security-export"),
    });
    Object.defineProperty(globalThis.URL, "revokeObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWriteText },
    });
    mockApi.getAzureAIModels.mockResolvedValue([
      { id: "qwen3.5:4b", name: "qwen3.5:4b", provider: "ollama" },
      { id: "nemotron-3-nano:4b", name: "nemotron-3-nano:4b", provider: "ollama" },
    ]);
    mockApi.getAzureStatus.mockResolvedValue({
      configured: true,
      initialized: true,
      refreshing: false,
      last_refresh: "2026-04-02T01:59:00Z",
      datasets: [],
    });
  });

  it("renders the security copilot workspace shell", async () => {
    render(<AzureSecurityCopilotPage />);

    expect(await screen.findByText("Security Copilot")).toBeInTheDocument();
    expect(screen.getByText(/Ollama-backed incident workbench/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Investigation" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Security workspace" })).toHaveAttribute("href", "/security");
  });

  it("shows follow-up questions and planned sources after the first turn", async () => {
    mockApi.chatAzureSecurityCopilot.mockResolvedValue(buildResponse());

    render(<AzureSecurityCopilotPage />);

    fireEvent.change(
      await screen.findByPlaceholderText(/User ada@example.com reported impossible travel alerts/i),
      { target: { value: "Shared mailbox payroll@example.com is forwarding mail externally." } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Start Investigation" }));

    expect(await screen.findByText("Current Copilot Status")).toBeInTheDocument();
    expect(screen.getByText("Follow-up questions")).toBeInTheDocument();
    expect(screen.getByText("Affected mailbox")).toBeInTheDocument();
    expect(screen.getByText("Source Plan")).toBeInTheDocument();
    expect(screen.getByText("Mailbox inbox rules")).toBeInTheDocument();

    const call = mockApi.chatAzureSecurityCopilot.mock.calls[0][0];
    expect(call.message).toContain("forwarding mail externally");
    expect(call.history).toEqual([]);
  });

  it("exports the current investigation as markdown and json handoff bundles", async () => {
    const anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    mockApi.chatAzureSecurityCopilot.mockResolvedValue(
      buildResponse({
        phase: "complete",
        assistant_message: "Investigation complete.",
        follow_up_questions: [],
        planned_sources: [
          {
            key: "delegate_mailbox_scan_job",
            label: "Delegate mailbox scan job",
            status: "completed",
            query_summary: "payroll@example.com",
            reason: "",
          },
        ],
        source_results: [
          {
            key: "delegate_mailbox_scan_job",
            label: "Delegate mailbox scan job",
            status: "completed",
            query_summary: "payroll@example.com",
            item_count: 3,
            highlights: ["payroll@example.com: 3 mailbox match(es)"],
            preview: [{ job_id: "delegate-job-1", target: "payroll@example.com", status: "completed" }],
            citations: [{ source_type: "delegate_mailbox_scan", label: "Delegate mailbox scan", detail: "3 mailbox matches" }],
            reason: "",
          },
        ],
        jobs: [
          {
            job_type: "delegate_mailbox_scan",
            label: "Delegate mailbox scan",
            job_id: "delegate-job-1",
            status: "completed",
            phase: "completed",
            target: "payroll@example.com",
            summary: "3 mailbox match(es)",
            started_automatically: true,
          },
        ],
        answer: {
          summary: "Mailbox forwarding appears tied to delegate access on the shared mailbox.",
          findings: ["Delegate access exists for payroll@example.com."],
          next_steps: ["Review the delegate assignment and forwarding configuration."],
          warnings: [],
        },
        citations: [{ source_type: "delegate_mailbox_scan", label: "Delegate mailbox scan", detail: "3 mailbox matches" }],
      }),
    );

    render(<AzureSecurityCopilotPage />);

    fireEvent.change(
      await screen.findByPlaceholderText(/User ada@example.com reported impossible travel alerts/i),
      { target: { value: "Investigate payroll@example.com mailbox abuse." } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Start Investigation" }));

    expect(await screen.findByText("Investigation Export")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy Markdown" }));

    await waitFor(() => {
      expect(clipboardWriteText).toHaveBeenCalledTimes(1);
    });
    expect(clipboardWriteText.mock.calls[0][0]).toContain("# Azure Security Investigation Export");
    expect(clipboardWriteText.mock.calls[0][0]).toContain("Mailbox forwarding appears tied to delegate access on the shared mailbox.");

    fireEvent.click(screen.getByRole("button", { name: "Download Markdown" }));
    fireEvent.click(screen.getByRole("button", { name: "Download JSON" }));

    expect(globalThis.URL.createObjectURL).toHaveBeenCalledTimes(2);
    expect(anchorClickSpy).toHaveBeenCalledTimes(2);
    anchorClickSpy.mockRestore();
  });

  it("renders identity confirmation choices and submits the selected account", async () => {
    mockApi.chatAzureSecurityCopilot
      .mockResolvedValueOnce(
        buildResponse({
          assistant_message: "I found Azure user matches for Abhishek Mishra. Confirm which account I should investigate first.",
          incident: {
            lane: "identity_compromise",
            summary: "Abhishek Mishra had impossible travel in the last two weeks.",
            timeframe: "last two weeks",
            affected_users: [],
            affected_mailboxes: [],
            affected_apps: [],
            affected_resources: [],
            alert_names: [],
            observed_artifacts: [],
            identity_query: "Abhishek Mishra",
            identity_candidates: [
              {
                id: "user-1",
                display_name: "Abhishek Mishra",
                principal_name: "abhishek.mishra@example.com",
                mail: "abhishek.mishra@example.com",
                match_reason: "display_name_exact",
              },
            ],
            confidence: 0.85,
            missing_fields: ["identity_confirmation"],
          },
          follow_up_questions: [
            {
              key: "identity_confirmation",
              label: "Confirm user account",
              prompt: "I found 1 Azure user match(es) for Abhishek Mishra. Confirm which account I should investigate first.",
              placeholder: "Reply with the exact account, or click one of the matches below.",
              required: true,
              input_type: "list",
              choices: ["Abhishek Mishra <abhishek.mishra@example.com>"],
            },
          ],
          planned_sources: [],
        }),
      )
      .mockResolvedValueOnce(
        buildResponse({
          phase: "complete",
          assistant_message: "Confirmed. I investigated abhishek.mishra@example.com and found no additional alert history matches yet.",
          incident: {
            lane: "identity_compromise",
            summary: "Abhishek Mishra had impossible travel in the last two weeks.",
            timeframe: "last two weeks",
            affected_users: ["abhishek.mishra@example.com"],
            affected_mailboxes: ["abhishek.mishra@example.com"],
            affected_apps: [],
            affected_resources: [],
            alert_names: [],
            observed_artifacts: [],
            identity_query: "",
            identity_candidates: [],
            confidence: 0.92,
            missing_fields: [],
          },
          follow_up_questions: [],
          planned_sources: [],
          source_results: [],
          answer: {
            summary: "No grounded high-confidence findings yet.",
            findings: [],
            next_steps: [],
            warnings: [],
          },
        }),
      );

    render(<AzureSecurityCopilotPage />);

    fireEvent.change(
      await screen.findByPlaceholderText(/User ada@example.com reported impossible travel alerts/i),
      { target: { value: "Abhishek Mishra had impossible travel in the last two week investigate and report back with findings" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Start Investigation" }));

    expect(await screen.findByRole("button", { name: "Abhishek Mishra <abhishek.mishra@example.com>" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Abhishek Mishra <abhishek.mishra@example.com>" }));

    await waitFor(() => {
      expect(mockApi.chatAzureSecurityCopilot).toHaveBeenCalledTimes(2);
    });

    const secondCall = mockApi.chatAzureSecurityCopilot.mock.calls[1][0];
    expect(secondCall.message).toBe("Abhishek Mishra <abhishek.mishra@example.com>");
    expect(secondCall.incident.identity_candidates).toHaveLength(1);
  });

  it("polls running jobs and updates to the completed investigation summary", async () => {
    const originalSetTimeout = window.setTimeout.bind(window);
    const timeoutSpy = vi.spyOn(window, "setTimeout").mockImplementation(
      ((callback: TimerHandler, delay?: number, ...args: unknown[]) => {
        if (delay === 4000 && typeof callback === "function") {
          callback(...args);
          return 1 as unknown as number;
        }
        return originalSetTimeout(callback, delay, ...(args as []));
      }) as typeof window.setTimeout,
    );
    mockApi.chatAzureSecurityCopilot
      .mockResolvedValueOnce(
        buildResponse({
          phase: "running_jobs",
          assistant_message: "Partial results are ready while mailbox scans run.",
          follow_up_questions: [],
          planned_sources: [
            {
              key: "delegate_mailbox_scan_job",
              label: "Delegate mailbox scan job",
              status: "running",
              query_summary: "payroll@example.com",
              reason: "",
            },
          ],
          source_results: [
            {
              key: "delegate_mailbox_scan_job",
              label: "Delegate mailbox scan job",
              status: "running",
              query_summary: "payroll@example.com",
              item_count: 1,
              highlights: ["payroll@example.com: running (scanning exchange permissions)"],
              preview: [],
              citations: [],
              reason: "",
            },
          ],
          jobs: [
            {
              job_type: "delegate_mailbox_scan",
              label: "Delegate mailbox scan",
              job_id: "delegate-job-1",
              status: "running",
              phase: "scanning_exchange_permissions",
              target: "payroll@example.com",
              summary: "Scanning exchange permissions",
              started_automatically: true,
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        buildResponse({
          phase: "complete",
          assistant_message: "Investigation complete.",
          follow_up_questions: [],
          planned_sources: [
            {
              key: "delegate_mailbox_scan_job",
              label: "Delegate mailbox scan job",
              status: "completed",
              query_summary: "payroll@example.com",
              reason: "",
            },
          ],
          source_results: [
            {
              key: "delegate_mailbox_scan_job",
              label: "Delegate mailbox scan job",
              status: "completed",
              query_summary: "payroll@example.com",
              item_count: 3,
              highlights: ["payroll@example.com: 3 mailbox match(es)"],
              preview: [{ job_id: "delegate-job-1", target: "payroll@example.com", status: "completed" }],
              citations: [{ source_type: "delegate_mailbox_scan", label: "Delegate mailbox scan", detail: "3 mailbox matches" }],
              reason: "",
            },
          ],
          jobs: [
            {
              job_type: "delegate_mailbox_scan",
              label: "Delegate mailbox scan",
              job_id: "delegate-job-1",
              status: "completed",
              phase: "completed",
              target: "payroll@example.com",
              summary: "3 mailbox match(es)",
              started_automatically: true,
            },
          ],
          answer: {
            summary: "Mailbox forwarding appears tied to delegate access on the shared mailbox.",
            findings: ["Delegate access exists for payroll@example.com."],
            next_steps: ["Review the delegate assignment and forwarding configuration."],
            warnings: [],
          },
          citations: [{ source_type: "delegate_mailbox_scan", label: "Delegate mailbox scan", detail: "3 mailbox matches" }],
        }),
      );

    render(<AzureSecurityCopilotPage />);

    fireEvent.change(
      await screen.findByPlaceholderText(/User ada@example.com reported impossible travel alerts/i),
      { target: { value: "Investigate payroll@example.com mailbox abuse." } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Start Investigation" }));

    await waitFor(() => {
      expect(mockApi.chatAzureSecurityCopilot).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByText("Safe Jobs")).toBeInTheDocument();
    expect(await screen.findByText("Investigation Summary")).toBeInTheDocument();
    expect(screen.getByText("Mailbox forwarding appears tied to delegate access on the shared mailbox.")).toBeInTheDocument();

    const pollCall = mockApi.chatAzureSecurityCopilot.mock.calls[1][0];
    expect(pollCall.message).toBe("");
    expect(pollCall.jobs[0].job_id).toBe("delegate-job-1");
    timeoutSpy.mockRestore();
  }, 10000);
});
