import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import QuarantineReleaseTool from "../components/QuarantineReleaseTool.tsx";

const mockApi = vi.hoisted(() => ({
  getQuarantineReleaseStatus: vi.fn(),
  getQuarantineReleaseRuns: vi.fn(),
  getQuarantineReleaseReleases: vi.fn(),
  patchQuarantineReleaseSettings: vi.fn(),
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

describe("QuarantineReleaseTool", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getQuarantineReleaseStatus.mockResolvedValue({
      enabled: false,
      allowed_domains: ["complexlegal.com"],
      last_run: {
        run_hour: "2026-09-01T14:00:00Z",
        ran_at: "2026-09-01T14:02:00+00:00",
        domains_checked: "complexlegal.com",
        checked_count: 3,
        released_count: 3,
        failed_count: 0,
      },
    });
    mockApi.getQuarantineReleaseRuns.mockResolvedValue({
      items: [
        {
          run_hour: "2026-09-01T14:00:00Z",
          ran_at: "2026-09-01T14:02:00+00:00",
          domains_checked: "complexlegal.com",
          checked_count: 3,
          released_count: 3,
          failed_count: 0,
        },
      ],
      total: 1,
    });
    mockApi.getQuarantineReleaseReleases.mockResolvedValue({
      items: [
        {
          id: "r1",
          run_hour: "2026-09-01T14:00:00Z",
          message_identity: "msg-1",
          sender_address: "billing@complexlegal.com",
          recipient_address: "ap@example.com",
          subject: "Invoice",
          received_at: "2026-09-01T14:00:00Z",
          quarantine_reason: "Spam",
          status: "released",
          error: null,
          released_at: "2026-09-01T14:02:00Z",
        },
      ],
      total: 1,
    });
    mockApi.patchQuarantineReleaseSettings.mockResolvedValue({
      enabled: true,
      allowed_domains: ["complexlegal.com"],
      last_run: null,
    });
  });

  it("renders the toggle, last-run summary, and releases table", async () => {
    render(<QuarantineReleaseTool />);

    await waitFor(() => expect(screen.getByRole("switch")).toBeInTheDocument());
    expect(await screen.findByText(/3 released/i)).toBeInTheDocument();
    expect(await screen.findByText("billing@complexlegal.com")).toBeInTheDocument();
  });

  it("toggles the job on and calls the settings patch", async () => {
    render(<QuarantineReleaseTool />);

    const toggle = await screen.findByRole("switch");
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(mockApi.patchQuarantineReleaseSettings).toHaveBeenCalledWith({ enabled: true }),
    );
  });

  it("saves an edited domain list", async () => {
    render(<QuarantineReleaseTool />);

    const input = await screen.findByLabelText(/trusted domains/i);
    fireEvent.change(input, { target: { value: "complexlegal.com, partner.org" } });
    fireEvent.click(screen.getByRole("button", { name: /save domains/i }));

    await waitFor(() =>
      expect(mockApi.patchQuarantineReleaseSettings).toHaveBeenCalledWith({
        allowed_domains: ["complexlegal.com", "partner.org"],
      }),
    );
  });

  it("surfaces an inline error when the settings patch fails", async () => {
    mockApi.patchQuarantineReleaseSettings.mockRejectedValue(new Error("Not authorized"));

    render(<QuarantineReleaseTool />);

    const toggle = await screen.findByRole("switch");
    fireEvent.click(toggle);

    expect(await screen.findByText("Not authorized")).toBeInTheDocument();
  });
});
