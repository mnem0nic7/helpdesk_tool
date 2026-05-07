import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import PasswordExpiryNotifierPage from "../pages/PasswordExpiryNotifierPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getMe: vi.fn(),
    getPasswordExpiryStatus: vi.fn(),
    getPasswordExpiryRuns: vi.fn(),
    getPasswordExpiryNotifications: vi.fn(),
    patchPasswordExpirySettings: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({ api: mockApi, default: mockApi }));

const baseStatus = {
  enabled: false,
  last_run: null,
  config: { max_age_days: 90, days_before: 14 },
};

const adminMe = { email: "admin@corp.com", name: "Admin", is_admin: true };
const staffMe = { email: "staff@corp.com", name: "Staff", is_admin: false };

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.getMe.mockResolvedValue(adminMe);
  mockApi.getPasswordExpiryStatus.mockResolvedValue(baseStatus);
  mockApi.getPasswordExpiryRuns.mockResolvedValue({ items: [], total: 0 });
  mockApi.getPasswordExpiryNotifications.mockResolvedValue({ items: [], total: 0 });
});

describe("PasswordExpiryNotifierPage", () => {
  it("shows TEST badge when enabled=false", async () => {
    render(<PasswordExpiryNotifierPage />);
    await waitFor(() => expect(screen.getByText("TEST")).toBeInTheDocument());
  });

  it("shows LIVE badge when enabled=true", async () => {
    mockApi.getPasswordExpiryStatus.mockResolvedValue({ ...baseStatus, enabled: true });
    render(<PasswordExpiryNotifierPage />);
    await waitFor(() => expect(screen.getByText("LIVE")).toBeInTheDocument());
  });

  it("toggle is disabled for non-admin users", async () => {
    mockApi.getMe.mockResolvedValue(staffMe);
    render(<PasswordExpiryNotifierPage />);
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: /enable live emails/i })).toBeDisabled();
    });
  });

  it("toggle is enabled for admin users", async () => {
    render(<PasswordExpiryNotifierPage />);
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: /enable live emails/i })).not.toBeDisabled();
    });
  });

  it("clicking Notification Log tab shows the notifications table", async () => {
    const user = userEvent.setup();
    render(<PasswordExpiryNotifierPage />);
    await waitFor(() => screen.getByText("Notification Log"));
    await user.click(screen.getByText("Notification Log"));
    await waitFor(() => expect(mockApi.getPasswordExpiryNotifications).toHaveBeenCalled());
  });
});
