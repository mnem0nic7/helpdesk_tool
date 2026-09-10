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
});
