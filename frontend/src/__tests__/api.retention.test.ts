import { describe, expect, it, vi, beforeEach } from "vitest";
import { api } from "../lib/api.ts";

describe("retention API client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("getRetentionConnectionStatus fetches the status endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: null, last_error: null }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.getRetentionConnectionStatus();

    expect(fetchMock).toHaveBeenCalledWith("/api/retention/connection/status");
    expect(result.status).toBe("connected");
  });

  it("createRetentionPolicy posts the body and returns the created policy", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: "p1", team_id: "t1", team_name: "Eng", channel_id: "c1", channel_name: "General",
        retention_days: 30, status: "pending_preview", created_by: "x", created_at: "now", updated_at: "now",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.createRetentionPolicy({
      team_id: "t1", team_name: "Eng", channel_id: "c1", channel_name: "General", retention_days: 30,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/retention/policies",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.status).toBe("pending_preview");
  });
});
