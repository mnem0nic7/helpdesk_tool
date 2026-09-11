import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import RetentionImportExportPage from "../pages/RetentionImportExportPage.tsx";
import { api } from "../lib/api.ts";

function renderWithClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RetentionImportExportPage />
    </QueryClientProvider>,
  );
}

function uploadFile() {
  const file = new File(["dummy"], "channels.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  fireEvent.change(screen.getByLabelText("Import file"), { target: { files: [file] } });
  return file;
}

describe("RetentionImportExportPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("links the export button at the export endpoint", () => {
    renderWithClient();
    const link = screen.getByText("Export channels (.xlsx)") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/api/retention/export");
  });

  it("previews an uploaded file and shows action counts and rows", async () => {
    const previewSpy = vi.spyOn(api, "previewRetentionImport").mockResolvedValue({
      rows: [
        {
          team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
          current_status: "active", current_retention_days: 30, retention_days: 45, action: "update", error: null,
        },
        {
          team_id: "t2", team_name: "Sales", channel_id: "c2", channel_name: "Random",
          current_status: null, current_retention_days: null, retention_days: 60, action: "create", error: null,
        },
        {
          team_id: "t3", team_name: "Bad", channel_id: "c3", channel_name: "Bad",
          current_status: null, current_retention_days: null, retention_days: null, action: "error",
          error: "retention_days must be between 1 and 365",
        },
      ],
    });

    renderWithClient();
    const file = uploadFile();
    fireEvent.click(screen.getByText("Preview"));

    await waitFor(() => expect(previewSpy).toHaveBeenCalledWith(file));
    expect(await screen.findByText(/1 to create, 1 to update, 0 skipped, 1 with/i)).toBeInTheDocument();
    expect(screen.getByText("Engineering")).toBeInTheDocument();
    expect(screen.getByText("retention_days must be between 1 and 365")).toBeInTheDocument();
    expect(screen.getByText("Apply & activate 2 changes")).toBeEnabled();
  });

  it("disables Apply when there are no actionable rows", async () => {
    vi.spyOn(api, "previewRetentionImport").mockResolvedValue({
      rows: [{
        team_id: "t1", team_name: "Eng", channel_id: "c1", channel_name: "General",
        current_status: null, current_retention_days: null, retention_days: null, action: "skip", error: null,
      }],
    });

    renderWithClient();
    uploadFile();
    fireEvent.click(screen.getByText("Preview"));

    expect(await screen.findByText("Apply & activate 0 changes")).toBeDisabled();
  });

  it("applies the same file, runs a live preview per row, and shows the resulting counts", async () => {
    vi.spyOn(api, "previewRetentionImport").mockResolvedValue({
      rows: [{
        team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
        current_status: null, current_retention_days: null, retention_days: 45, action: "create", error: null,
      }],
    });
    const applySpy = vi.spyOn(api, "applyRetentionImport").mockResolvedValue({
      rows: [{
        team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
        current_status: null, current_retention_days: null, retention_days: 45, action: "create", error: null,
        result: "created", preview_messages_count: 12, preview_attachments_count: 3, preview_oldest_message_at: "2025-01-01",
      }],
    });

    renderWithClient();
    const file = uploadFile();
    fireEvent.click(screen.getByText("Preview"));
    await screen.findByText("Apply & activate 1 change");

    fireEvent.click(screen.getByText("Apply & activate 1 change"));

    await waitFor(() => expect(applySpy).toHaveBeenCalledWith(file));
    expect(await screen.findByText("created")).toBeInTheDocument();
    expect(screen.getByText("12 msg(s), 3 attachment(s)")).toBeInTheDocument();
    // The action-count summary bar (and its Apply button) only apply to the preview
    // phase and must not linger once results are shown.
    expect(screen.queryByText(/to create,/i)).not.toBeInTheDocument();
  });

  it("shows a preview_failed row as still pending, without fabricating live counts", async () => {
    // The row's policy was created/updated but the live Graph preview that would
    // confirm it to active failed (e.g. disconnected service account) — it must
    // read as unresolved, not silently dropped or shown as if it were armed.
    vi.spyOn(api, "previewRetentionImport").mockResolvedValue({
      rows: [{
        team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
        current_status: null, current_retention_days: null, retention_days: 45, action: "create", error: null,
      }],
    });
    vi.spyOn(api, "applyRetentionImport").mockResolvedValue({
      rows: [{
        team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
        current_status: null, current_retention_days: null, retention_days: 45, action: "create",
        result: "preview_failed", error: "Saved as pending_preview, but the live preview failed: not connected",
      }],
    });

    renderWithClient();
    uploadFile();
    fireEvent.click(screen.getByText("Preview"));
    await screen.findByText("Apply & activate 1 change");
    fireEvent.click(screen.getByText("Apply & activate 1 change"));

    expect(await screen.findByText("preview_failed")).toBeInTheDocument();
    expect(screen.getByText(/live preview failed: not connected/i)).toBeInTheDocument();
    const previewCells = screen.getAllByText("—");
    expect(previewCells.length).toBeGreaterThan(0);
  });

  it("surfaces a preview failure", async () => {
    vi.spyOn(api, "previewRetentionImport").mockRejectedValue(new Error("Missing required column(s): retention_days"));

    renderWithClient();
    uploadFile();
    fireEvent.click(screen.getByText("Preview"));

    expect(await screen.findByText("Missing required column(s): retention_days")).toBeInTheDocument();
  });
});
