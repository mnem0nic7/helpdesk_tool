// frontend/src/__tests__/RetentionTeamsPage.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import RetentionTeamsPage from "../pages/RetentionTeamsPage.tsx";
import { api } from "../lib/api.ts";

vi.mock("../lib/api.ts", () => ({
  api: {
    getRetentionConnectionStatus: vi.fn(),
    getRetentionTeams: vi.fn(),
    getRetentionChannels: vi.fn(),
    createRetentionPolicy: vi.fn(),
    getRetentionPolicyPreview: vi.fn(),
    confirmRetentionPolicy: vi.fn(),
  },
}));

function renderWithClient() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <RetentionTeamsPage />
    </QueryClientProvider>,
  );
}

describe("RetentionTeamsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a connect banner when the service account is disconnected", async () => {
    (api.getRetentionConnectionStatus as any).mockResolvedValue({
      status: "disconnected", service_account_upn: "", last_refreshed_at: null, last_error: "not set up",
    });

    renderWithClient();

    await waitFor(() => expect(screen.getByText(/Service account not connected/i)).toBeInTheDocument());
  });

  it("lists teams and channels, then previews and confirms a new policy", async () => {
    (api.getRetentionConnectionStatus as any).mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    (api.getRetentionTeams as any).mockResolvedValue({ items: [{ id: "t1", name: "Engineering", policy_count: 0 }], total: 1 });
    (api.getRetentionChannels as any).mockResolvedValue({
      items: [{ id: "c1", name: "General", policy: null }], total: 1,
    });
    (api.createRetentionPolicy as any).mockResolvedValue({
      id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
      retention_days: 30, status: "pending_preview", created_by: "x", created_at: "now", updated_at: "now",
    });
    (api.getRetentionPolicyPreview as any).mockResolvedValue({ messages_count: 5, attachments_count: 1, oldest_message_at: "2026-01-01" });
    (api.confirmRetentionPolicy as any).mockResolvedValue({
      id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
      retention_days: 30, status: "active", created_by: "x", created_at: "now", updated_at: "now",
    });

    renderWithClient();

    fireEvent.click(await screen.findByText("Engineering"));
    fireEvent.click(await screen.findByText("Configure retention"));
    fireEvent.click(screen.getByText("Preview"));

    await waitFor(() => expect(screen.getByText(/approximately/i)).toBeInTheDocument());
    expect(screen.getByText(/5/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Confirm & Enable"));

    await waitFor(() => expect(api.confirmRetentionPolicy).toHaveBeenCalledWith("p1"));
  });
});
