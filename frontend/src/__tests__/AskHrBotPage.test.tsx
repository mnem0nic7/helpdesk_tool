import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import AskHrBotPage from "../pages/AskHrBotPage.tsx";
import { api } from "../lib/api.ts";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AskHrBotPage />
    </QueryClientProvider>,
  );
}

describe("AskHrBotPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "getAskHrBotStatus").mockResolvedValue({
      enabled: false,
      poll_interval_seconds: 120,
      lookback_minutes: 15,
      askhr_checkpoint_at: "",
      benefits_checkpoint_at: "",
      trusted_domains: ["librasolutionsgroup.com"],
      trusted_domains_refreshed_at: "2026-09-03T00:00:00+00:00",
      domain_refresh_interval_seconds: 3600,
      reporter_mode: "unset",
      last_runs: { askhr: null, benefits: null },
    });
    vi.spyOn(api, "getAskHrBotRuns").mockResolvedValue({ items: [], total: 0 });
    vi.spyOn(api, "getAskHrBotMessages").mockResolvedValue({
      items: [
        {
          internet_message_id: "<m1@mail.example.com>",
          mailbox: "askhr",
          graph_message_id: "g1",
          subject: "Need help",
          sender_email: "outsider@example.com",
          received_at: "2026-09-03T11:00:00+00:00",
          status: "failed",
          jira_issue_key: "HRD-1",
          error: "attachment failed: boom",
          processed_at: "2026-09-03T11:01:00+00:00",
        },
      ],
      total: 1,
    });
    vi.spyOn(api, "patchAskHrBotSettings").mockResolvedValue({
      enabled: true,
      poll_interval_seconds: 120,
      lookback_minutes: 15,
      askhr_checkpoint_at: "",
      benefits_checkpoint_at: "",
      trusted_domains: [],
      trusted_domains_refreshed_at: "",
      domain_refresh_interval_seconds: 3600,
      reporter_mode: "unset",
      last_runs: { askhr: null, benefits: null },
    });
    vi.spyOn(api, "retryAskHrBotMessage").mockResolvedValue({
      internet_message_id: "<m1@mail.example.com>",
      mailbox: "askhr",
      status: "created",
      jira_issue_key: "HRD-1",
      error: null,
    });
  });

  it("shows the disabled toggle and the failed message with a retry button", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("switch")).toBeInTheDocument());
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    await waitFor(() => expect(screen.getByText("Need help")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("calls retry with the row's mailbox so it can never hit the other mailbox's copy", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: /^retry$/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^retry$/i }));
    await waitFor(() =>
      expect(api.retryAskHrBotMessage).toHaveBeenCalledWith("<m1@mail.example.com>", "askhr"),
    );
  });

  it("toggles enabled via the settings mutation", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("switch")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(api.patchAskHrBotSettings).toHaveBeenCalledWith({ enabled: true }));
  });
});
