import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import HrEntraSyncPage from "../pages/HrEntraSyncPage.tsx";
import { api, type HrEntraSyncStatus } from "../lib/api.ts";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <HrEntraSyncPage />
    </QueryClientProvider>,
  );
}

function status(overrides: Partial<HrEntraSyncStatus> = {}): HrEntraSyncStatus {
  return {
    enabled: false,
    projects: ["HRD", "LIBTA"],
    retry_minutes: 15,
    poll_seconds: 60,
    lookback_minutes: 120,
    counts: { pending: 1, synced: 4, not_found: 2, ambiguous: 0, failed: 0 },
    total: 7,
    last_activity_at: "2026-10-14T12:00:00+00:00",
    mappings: [
      { jira_name: "Job Title", jira_field_id: "customfield_12866", entra_source: "title", kind: "text", active: true, note: "" },
      {
        jira_name: "FLSA Status",
        jira_field_id: "customfield_13028",
        entra_source: "employeeId",
        kind: "select",
        active: false,
        note: "Sheet maps FLSA to employeeID, which looks wrong.",
      },
    ],
    ...overrides,
  };
}

describe("HrEntraSyncPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "getHrEntraSyncStatus").mockResolvedValue(status());
    vi.spyOn(api, "getHrEntraSyncIssues").mockResolvedValue({
      issues: [
        {
          issue_key: "HRD-1",
          project_key: "HRD",
          status: "synced",
          first_seen_at: "2026-10-14T11:00:00+00:00",
          last_attempt_at: "2026-10-14T11:01:00+00:00",
          attempts: 1,
          completed_at: "2026-10-14T11:01:00+00:00",
          matched_upn: "jdoe@x.com",
          matched_via: "upn",
          fields_written: '["customfield_12866","customfield_13458"]',
          fields_skipped: '{"customfield_9":"not on screen"}',
          error: "",
        },
        {
          issue_key: "HRD-2",
          project_key: "HRD",
          status: "not_found",
          first_seen_at: "2026-10-14T10:00:00+00:00",
          last_attempt_at: "",
          attempts: 15,
          completed_at: "2026-10-14T10:15:00+00:00",
          matched_upn: "",
          matched_via: "",
          fields_written: "[]",
          fields_skipped: "{}",
          error: "Entra sync: no Entra account matched a@x.com",
        },
      ],
    });
    vi.spyOn(api, "dryRunHrEntraSync").mockResolvedValue({
      outcome: "synced",
      dry_run: true,
      emails: ["jdoe@x.com"],
      matched_upn: "jdoe@x.com",
      matched_via: "upn",
      fields_written: ["customfield_12866"],
      entra_empty: ["Home Department"],
    });
  });

  it("warns that a disabled connector is not running and shows counts", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/disabled/i));
    expect(screen.getByText("Synced").nextSibling).toHaveTextContent("4");
    expect(screen.getByText("No Entra match").nextSibling).toHaveTextContent("2");
  });

  it("shows a running banner, and a red one when tickets failed", async () => {
    vi.mocked(api.getHrEntraSyncStatus).mockResolvedValue(status({ enabled: true }));
    const { unmount } = renderPage();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Connector is running."));
    unmount();
    vi.mocked(api.getHrEntraSyncStatus).mockResolvedValue(
      status({ enabled: true, counts: { pending: 0, synced: 1, not_found: 0, ambiguous: 0, failed: 3 } }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/3 tickets failed/i));
  });

  it("lists tickets with parsed field counts and the detail message", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("HRD-1")).toBeInTheDocument());
    expect(screen.getByText("2 written, 1 rejected by Jira")).toBeInTheDocument();
    expect(screen.getByText(/no Entra account matched a@x.com/)).toBeInTheDocument();
  });

  it("passes the status filter to the issues query", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Filter by status")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "failed" } });
    await waitFor(() => expect(api.getHrEntraSyncIssues).toHaveBeenCalledWith("failed"));
  });

  it("explains disabled mappings", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Field mapping (1 of 2 active)")).toBeInTheDocument());
    expect(screen.getByText(/looks wrong/)).toBeInTheDocument();
  });

  it("runs a dry run with the ticket key upper-cased and the optional email", async () => {
    renderPage();
    const run = screen.getByRole("button", { name: /run dry run/i });
    expect(run).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Ticket key"), { target: { value: " hrd-5 " } });
    fireEvent.change(screen.getByLabelText("Email override"), { target: { value: "jdoe@x.com" } });
    fireEvent.click(run);
    await waitFor(() => expect(api.dryRunHrEntraSync).toHaveBeenCalledWith("HRD-5", "jdoe@x.com"));
    await waitFor(() => expect(screen.getByText(/Would write 1 field/)).toBeInTheDocument());
    expect(screen.getByText(/Entra has no value for: Home Department/)).toBeInTheDocument();
  });

  it("omits the email when none is entered and surfaces dry-run errors", async () => {
    vi.mocked(api.dryRunHrEntraSync).mockRejectedValue(new Error("400 bad key"));
    renderPage();
    fireEvent.change(screen.getByLabelText("Ticket key"), { target: { value: "HRD-9" } });
    fireEvent.click(screen.getByRole("button", { name: /run dry run/i }));
    await waitFor(() => expect(api.dryRunHrEntraSync).toHaveBeenCalledWith("HRD-9", undefined));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("400 bad key"));
  });
});
