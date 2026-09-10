// frontend/src/__tests__/RetentionTeamsPage.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import RetentionTeamsPage from "../pages/RetentionTeamsPage.tsx";
import { api } from "../lib/api.ts";

function renderWithClient() {
  // retry: false so the error-path tests resolve immediately instead of waiting
  // out React Query's default exponential backoff.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
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

  it("never offers Confirm & Enable when the preview call fails", async () => {
    // A failed preview used to fall through to the success branch, rendering a
    // fabricated "0 message(s) / 0 attachment(s)" next to a live red Confirm
    // button — clicking it would arm a policy that purges the real backlog on the
    // next hourly pass, defeating the pending_preview -> active safety gate.
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
    vi.spyOn(api, "getRetentionPolicyPreview").mockRejectedValue(new Error("Graph GET messages failed: 403 Forbidden"));

    renderWithClient();

    fireEvent.click(await screen.findByText("Engineering"));
    fireEvent.click(await screen.findByText("Configure retention"));
    fireEvent.click(screen.getByText("Preview"));

    await waitFor(() => expect(screen.getByText(/Unable to compute preview/i)).toBeInTheDocument());
    expect(screen.getByText(/403 Forbidden/)).toBeInTheDocument();
    expect(screen.queryByText("Confirm & Enable")).not.toBeInTheDocument();
    expect(screen.queryByText(/approximately/i)).not.toBeInTheDocument();
    // Recovery paths are offered instead.
    expect(screen.getByText("Retry")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
  });

  it("retries the preview from the error branch", async () => {
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
    vi.spyOn(api, "getRetentionPolicyPreview")
      .mockRejectedValueOnce(new Error("throttled"))
      .mockResolvedValue({ messages_count: 7, attachments_count: 2, oldest_message_at: "2026-01-01" });

    renderWithClient();

    fireEvent.click(await screen.findByText("Engineering"));
    fireEvent.click(await screen.findByText("Configure retention"));
    fireEvent.click(screen.getByText("Preview"));

    await waitFor(() => expect(screen.getByText(/Unable to compute preview/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText("Retry"));

    await waitFor(() => expect(screen.getByText(/approximately/i)).toBeInTheDocument());
    expect(screen.getByText("Confirm & Enable")).toBeInTheDocument();
  });

  it("renders an error banner when the teams list fails to load", async () => {
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    vi.spyOn(api, "getRetentionTeams").mockRejectedValue(new Error("Retention Graph connection is disconnected"));

    renderWithClient();

    await waitFor(() =>
      expect(screen.getByText(/Retention Graph connection is disconnected/i)).toBeInTheDocument(),
    );
  });

  it("renders an inline error when an expanded team's channels fail to load", async () => {
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    vi.spyOn(api, "getRetentionTeams").mockResolvedValue({ items: [{ id: "t1", name: "Engineering", policy_count: 0 }], total: 1 });
    vi.spyOn(api, "getRetentionChannels").mockRejectedValue(new Error("Graph channels lookup failed: 429"));

    renderWithClient();

    fireEvent.click(await screen.findByText("Engineering"));

    await waitFor(() => expect(screen.getByText(/Graph channels lookup failed: 429/i)).toBeInTheDocument());
  });

  it("paginates the teams list with Previous/Next controls", async () => {
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    const teamsSpy = vi.spyOn(api, "getRetentionTeams").mockResolvedValue({
      items: [{ id: "t1", name: "Engineering", policy_count: 0 }], total: 120,
    });

    renderWithClient();

    await screen.findByText("Engineering");
    expect(teamsSpy).toHaveBeenCalledWith(50, 0, "");
    const prevButtons = screen.getAllByText("Previous");
    expect(prevButtons[0]).toBeDisabled();

    fireEvent.click(screen.getAllByText("Next")[0]);

    await waitFor(() => expect(teamsSpy).toHaveBeenCalledWith(50, 50, ""));
  });

  it("paginates the channels list and resets to the first page when switching teams", async () => {
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    vi.spyOn(api, "getRetentionTeams").mockResolvedValue({
      items: [
        { id: "t1", name: "Engineering", policy_count: 0 },
        { id: "t2", name: "Sales", policy_count: 0 },
      ],
      total: 2,
    });
    const channelsSpy = vi.spyOn(api, "getRetentionChannels").mockResolvedValue({
      items: [{ id: "c1", name: "General", policy: null }], total: 80,
    });

    renderWithClient();

    fireEvent.click(await screen.findByText("Engineering"));
    // Wait for the channel row to actually render, not just for the queryFn to have
    // been invoked — until channelsQuery.data resolves, the pagination controls fall
    // back to total=0 and render disabled regardless of which button they are.
    await screen.findByText("General");

    // Two "Next" controls are visible once a team is expanded: the channels list's
    // own pagination (rendered first, nested inside the expanded team) and the
    // teams list's pagination below it.
    fireEvent.click(screen.getAllByText("Next")[0]);
    await waitFor(() => expect(channelsSpy).toHaveBeenCalledWith("t1", 50, 50, ""));

    fireEvent.click(screen.getByText("Sales"));
    await waitFor(() => expect(channelsSpy).toHaveBeenCalledWith("t2", 50, 0, ""));
  });

  it("searches teams and channels, resetting to the first page on each change", async () => {
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    const teamsSpy = vi.spyOn(api, "getRetentionTeams").mockResolvedValue({
      items: [{ id: "t1", name: "Engineering", policy_count: 0 }], total: 1,
    });
    const channelsSpy = vi.spyOn(api, "getRetentionChannels").mockResolvedValue({
      items: [{ id: "c1", name: "General", policy: null }], total: 1,
    });

    renderWithClient();

    await screen.findByText("Engineering");
    fireEvent.change(screen.getByLabelText("Search teams"), { target: { value: "eng" } });
    await waitFor(() => expect(teamsSpy).toHaveBeenCalledWith(50, 0, "eng"));
    await screen.findByText("Engineering");

    fireEvent.click(screen.getByText("Engineering"));
    await screen.findByText("General");
    fireEvent.change(screen.getByLabelText("Search channels"), { target: { value: "gen" } });
    await waitFor(() => expect(channelsSpy).toHaveBeenCalledWith("t1", 50, 0, "gen"));
    await screen.findByText("General");
  });

  it("renders the configure-retention panel next to the clicked channel, not at the bottom of the page", async () => {
    // Regression: the panel used to render once, unconditionally, after the whole
    // teams list and its pagination controls — with many teams paginated above it,
    // clicking Configure retention looked like nothing happened unless the operator
    // scrolled all the way down.
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    vi.spyOn(api, "getRetentionTeams").mockResolvedValue({
      items: [
        { id: "t1", name: "Engineering", policy_count: 0 },
        { id: "t2", name: "Sales", policy_count: 0 },
      ],
      total: 2,
    });
    vi.spyOn(api, "getRetentionChannels").mockImplementation(async (teamId) => ({
      items: teamId === "t1"
        ? [{ id: "c1", name: "General", policy: null }, { id: "c2", name: "Standup", policy: null }]
        : [{ id: "c3", name: "General", policy: null }],
      total: 1,
    }));

    renderWithClient();

    fireEvent.click(await screen.findByText("Engineering"));
    await screen.findByText("Standup");
    const configureButtons = screen.getAllByText("Configure retention");
    fireEvent.click(configureButtons[0]); // the "General" channel under Engineering

    const heading = await screen.findByText("Configure retention for General (Engineering)");
    // The panel must be a near sibling of the clicked channel's row, not detached at
    // the end of the document — walk up to the shared channel-list container (panel
    // div -> per-channel wrapper -> list container) and confirm the still-visible
    // "Standup" channel (a sibling row) sits right next to it, not far below.
    const channelListContainer = heading.closest("div")?.parentElement?.parentElement;
    expect(channelListContainer?.textContent).toContain("Standup");

    // Only one panel exists, scoped to the exact channel that was clicked.
    expect(screen.queryByText("Configure retention for Standup (Engineering)")).not.toBeInTheDocument();
  });

  it("surfaces a create-policy failure next to the Preview button", async () => {
    vi.spyOn(api, "getRetentionConnectionStatus").mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    vi.spyOn(api, "getRetentionTeams").mockResolvedValue({ items: [{ id: "t1", name: "Engineering", policy_count: 0 }], total: 1 });
    vi.spyOn(api, "getRetentionChannels").mockResolvedValue({
      items: [{ id: "c1", name: "General", policy: null }], total: 1,
    });
    vi.spyOn(api, "createRetentionPolicy").mockRejectedValue(new Error("A policy already exists for this channel"));

    renderWithClient();

    fireEvent.click(await screen.findByText("Engineering"));
    fireEvent.click(await screen.findByText("Configure retention"));
    fireEvent.click(screen.getByText("Preview"));

    await waitFor(() =>
      expect(screen.getByText(/A policy already exists for this channel/i)).toBeInTheDocument(),
    );
  });
});
