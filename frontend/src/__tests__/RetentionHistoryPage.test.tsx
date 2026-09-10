import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import RetentionHistoryPage from "../pages/RetentionHistoryPage.tsx";
import { api } from "../lib/api.ts";

function renderWithClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RetentionHistoryPage />
    </QueryClientProvider>,
  );
}

describe("RetentionHistoryPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "getRetentionPolicies").mockResolvedValue({
      items: [{
        id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
        retention_days: 30, status: "active", created_by: "x", created_at: "now", updated_at: "now",
      }],
      total: 1,
    });
    vi.spyOn(api, "getRetentionRuns").mockResolvedValue({
      items: [{
        id: "r1", policy_id: "p1", started_at: "2026-09-10T00:00:00Z", finished_at: "2026-09-10T00:01:00Z",
        outcome: "ok", messages_deleted: 3, attachments_deleted: 1, error: null,
      }],
      total: 1,
    });
    vi.spyOn(api, "getRetentionDeletions").mockResolvedValue({
      items: [{
        id: "d1", run_id: "r1", item_type: "message", item_id: "m1", sender_or_author: "Alice",
        original_created_at: "2026-08-01T00:00:00Z", deleted_at: "2026-09-10T00:00:30Z", status: "deleted", error: null,
      }],
      total: 1,
    });
  });

  it("shows run history and drills into deletions for a selected run", async () => {
    renderWithClient();

    await waitFor(() => expect(screen.getByText("2026-09-10T00:00:00Z")).toBeInTheDocument());

    fireEvent.click(screen.getByText("2026-09-10T00:00:00Z"));

    await waitFor(() => expect(api.getRetentionDeletions).toHaveBeenCalledWith("r1", 100, 0));
    expect(await screen.findByText("Alice")).toBeInTheDocument();
  });

  it("paginates runs and deletions, and resets the deletions page when a new run is selected", async () => {
    const runsSpy = vi.spyOn(api, "getRetentionRuns").mockResolvedValue({
      items: [{
        id: "r1", policy_id: "p1", started_at: "2026-09-10T00:00:00Z", finished_at: "2026-09-10T00:01:00Z",
        outcome: "ok", messages_deleted: 3, attachments_deleted: 1, error: null,
      }],
      total: 200,
    });
    const deletionsSpy = vi.spyOn(api, "getRetentionDeletions").mockResolvedValue({
      items: [{
        id: "d1", run_id: "r1", item_type: "message", item_id: "m1", sender_or_author: "Alice",
        original_created_at: "2026-08-01T00:00:00Z", deleted_at: "2026-09-10T00:00:30Z", status: "deleted", error: null,
      }],
      total: 300,
    });

    renderWithClient();
    // Wait for the row to actually render, not just for the queryFn to have been
    // invoked — until the query resolves, the pagination controls fall back to
    // total=0 and render disabled regardless of which button they are.
    await screen.findByText("2026-09-10T00:00:00Z");

    fireEvent.click(screen.getByText("2026-09-10T00:00:00Z"));
    await screen.findByText("Alice");

    // Two "Next" controls exist once a run is selected: runs pagination (rendered
    // first, right after the runs table) and deletions pagination (second).
    const nextButtons = screen.getAllByText("Next");
    fireEvent.click(nextButtons[0]);
    await waitFor(() => expect(runsSpy).toHaveBeenCalledWith(undefined, 50, 50));

    fireEvent.click(screen.getAllByText("Next")[1]);
    await waitFor(() => expect(deletionsSpy).toHaveBeenCalledWith("r1", 100, 100));
  });
});
