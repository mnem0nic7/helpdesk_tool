// frontend/src/__tests__/RetentionTeamsPage.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import RetentionTeamsPage from "../pages/RetentionTeamsPage.tsx";
import { api } from "../lib/api.ts";

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
    vi.restoreAllMocks();
  });

  it("shows a connect banner when the service account is disconnected", async () => {
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "disconnected", service_account_upn: "", last_refreshed_at: null, last_error: "not set up",
    });

    renderWithClient();

    await waitFor(() => expect(screen.getByText(/Service account not connected/i)).toBeInTheDocument());
  });

  it("lists teams and channels, then previews and confirms a new policy", async () => {
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    vi.spyOn(api, "getRetentionTeams").mockResolvedValue({ items: [{ id: "t1", name: "Engineering", policy_count: 0 }], total: 1 });
    vi.spyOn(api, "getRetentionChannels").mockResolvedValue({
      items: [{ id: "c1", name: "General", policy: null }], total: 1,
    });
    vi.spyOn(api, "createRetentionPolicy").mockResolvedValue({
      id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
      retention_days: 30, status: "pending_preview", created_by: "x", created_at: "now", updated_at: "now",
    });
    vi.spyOn(api, "getRetentionPolicyPreview").mockResolvedValue({ messages_count: 5, attachments_count: 1, oldest_message_at: "2026-01-01" });
    vi.spyOn(api, "confirmRetentionPolicy").mockResolvedValue({
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

  it("disables the orphaned pending_preview policy when Cancel is clicked, and reopens Configure retention", async () => {
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    vi.spyOn(api, "getRetentionTeams").mockResolvedValue({ items: [{ id: "t1", name: "Engineering", policy_count: 0 }], total: 1 });
    vi.spyOn(api, "getRetentionChannels").mockResolvedValue({
      items: [{ id: "c1", name: "General", policy: null }], total: 1,
    });
    vi.spyOn(api, "createRetentionPolicy").mockResolvedValue({
      id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
      retention_days: 30, status: "pending_preview", created_by: "x", created_at: "now", updated_at: "now",
    });
    vi.spyOn(api, "getRetentionPolicyPreview").mockResolvedValue({ messages_count: 5, attachments_count: 1, oldest_message_at: "2026-01-01" });
    vi.spyOn(api, "patchRetentionPolicy").mockResolvedValue({
      id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
      retention_days: 30, status: "disabled", created_by: "x", created_at: "now", updated_at: "now",
    });

    renderWithClient();

    fireEvent.click(await screen.findByText("Engineering"));
    fireEvent.click(await screen.findByText("Configure retention"));
    fireEvent.click(screen.getByText("Preview"));

    await waitFor(() => expect(screen.getByText(/approximately/i)).toBeInTheDocument());

    fireEvent.click(screen.getByText("Cancel"));

    await waitFor(() => expect(api.patchRetentionPolicy).toHaveBeenCalledWith("p1", { status: "disabled" }));
    expect(api.createRetentionPolicy).toHaveBeenCalledTimes(1);
  });

  it("shows Configure retention (not a permanent lockout) for a channel with a disabled policy", async () => {
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    vi.spyOn(api, "getRetentionTeams").mockResolvedValue({ items: [{ id: "t1", name: "Engineering", policy_count: 0 }], total: 1 });
    vi.spyOn(api, "getRetentionChannels").mockResolvedValue({
      items: [{
        id: "c1", name: "General",
        policy: {
          id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
          retention_days: 30, status: "disabled", created_by: "x", created_at: "now", updated_at: "now",
        },
      }],
      total: 1,
    });

    renderWithClient();

    fireEvent.click(await screen.findByText("Engineering"));

    expect(await screen.findByText(/disabled, 30d/)).toBeInTheDocument();
    expect(screen.getByText("Configure retention")).toBeInTheDocument();
  });

  it("reconfiguring a channel with an existing disabled policy patches instead of creating", async () => {
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    vi.spyOn(api, "getRetentionTeams").mockResolvedValue({ items: [{ id: "t1", name: "Engineering", policy_count: 0 }], total: 1 });
    vi.spyOn(api, "getRetentionChannels").mockResolvedValue({
      items: [{
        id: "c1", name: "General",
        policy: {
          id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
          retention_days: 30, status: "disabled", created_by: "x", created_at: "now", updated_at: "now",
        },
      }],
      total: 1,
    });
    const patchSpy = vi.spyOn(api, "patchRetentionPolicy").mockResolvedValue({
      id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
      retention_days: 45, status: "pending_preview", created_by: "x", created_at: "now", updated_at: "now",
    });
    vi.spyOn(api, "createRetentionPolicy");
    vi.spyOn(api, "getRetentionPolicyPreview").mockResolvedValue({ messages_count: 0, attachments_count: 0, oldest_message_at: null });

    renderWithClient();

    fireEvent.click(await screen.findByText("Engineering"));
    fireEvent.click(await screen.findByText("Configure retention"));

    const input = screen.getByRole("spinbutton");
    fireEvent.change(input, { target: { value: "45" } });
    fireEvent.click(screen.getByText("Preview"));

    await waitFor(() => expect(patchSpy).toHaveBeenCalledWith("p1", { retention_days: 45 }));
    expect(api.createRetentionPolicy).not.toHaveBeenCalled();
  });
});
