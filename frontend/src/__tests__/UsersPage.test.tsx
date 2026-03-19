import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import UsersPage from "../pages/UsersPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getUsers: vi.fn(),
    getMetrics: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

describe("UsersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getUsers.mockResolvedValue([
      {
        account_id: "acct-1",
        display_name: "Ada Lovelace",
        email_address: "ada@example.com",
      },
      {
        account_id: "acct-2",
        display_name: "Grace Hopper",
        email_address: "grace@example.com",
      },
    ]);
    mockApi.getMetrics.mockResolvedValue({
      headline: {},
      weekly_volumes: [],
      age_buckets: [],
      ttr_distribution: [],
      priority_counts: [],
      assignee_stats: [
        {
          name: "Ada Lovelace",
          resolved: 14,
          open: 3,
          median_ttr: 4.5,
          p90_ttr: 12,
          stale: 1,
        },
      ],
    });
  });

  it("renders Jira users with workload stats and filters by search", async () => {
    const user = userEvent.setup();

    render(<UsersPage />);

    expect(await screen.findByRole("heading", { name: "Users" })).toBeInTheDocument();
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(await screen.findByText("grace@example.com")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "3" })).toHaveAttribute(
      "href",
      "/tickets?assignee=Ada+Lovelace&open_only=true",
    );
    expect(await screen.findByText("4.5h")).toBeInTheDocument();
    expect(await screen.findByText("12.0h")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Search users..."), "grace");

    await waitFor(() => {
      expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Grace Hopper")).toBeInTheDocument();
  });
});
