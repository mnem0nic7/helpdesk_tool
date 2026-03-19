import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "../test-utils.tsx";
import UsersPage from "../pages/UsersPage.tsx";
import AzureUsersPage from "../pages/AzureUsersPage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureUsers: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

const directoryUsers = [
  {
    id: "user-1",
    display_name: "Ada Lovelace",
    object_type: "user" as const,
    principal_name: "ada@contoso.com",
    mail: "ada@contoso.com",
    app_id: "",
    enabled: true,
    extra: {
      user_type: "Member",
      on_prem_domain: "MOVEDOCS",
      on_prem_netbios: "MOVEDOCS",
      on_prem_sync: "true",
      department: "Infrastructure",
      job_title: "Systems Engineer",
      company_name: "MoveDocs",
      office_location: "Los Angeles",
      created_datetime: "2024-01-15T00:00:00Z",
      last_password_change: "2026-03-10T00:00:00Z",
      proxy_addresses: "SMTP:ada@contoso.com",
      mobile_phone: "555-0100",
      business_phones: "555-0110",
      city: "Los Angeles",
      country: "USA",
    },
  },
  {
    id: "user-2",
    display_name: "Grace Hopper",
    object_type: "user" as const,
    principal_name: "grace_external#EXT#@contoso.com",
    mail: "grace@example.com",
    app_id: "",
    enabled: false,
    extra: {
      user_type: "Guest",
      on_prem_domain: "",
      on_prem_netbios: "",
      on_prem_sync: "false",
      department: "Security",
      job_title: "Consultant",
      company_name: "Partner Co",
      office_location: "Remote",
      created_datetime: "2023-05-01T00:00:00Z",
      last_password_change: "2025-12-12T00:00:00Z",
      proxy_addresses: "SMTP:grace@example.com",
      mobile_phone: "",
      business_phones: "",
      city: "New York",
      country: "USA",
    },
  },
];

let originalIntersectionObserver: typeof IntersectionObserver | undefined;

beforeAll(() => {
  originalIntersectionObserver = globalThis.IntersectionObserver;
  globalThis.IntersectionObserver = vi.fn().mockImplementation(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
    takeRecords: vi.fn(),
    root: null,
    rootMargin: "",
    thresholds: [],
  })) as unknown as typeof IntersectionObserver;
});

afterAll(() => {
  globalThis.IntersectionObserver = originalIntersectionObserver as typeof IntersectionObserver;
});

describe("Users directory pages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      writable: true,
      value: 1440,
    });
    mockApi.getAzureUsers.mockImplementation(async (search = "") => {
      const normalizedSearch = search.trim().toLowerCase();
      if (!normalizedSearch) {
        return directoryUsers;
      }
      return directoryUsers.filter((user) => {
        const haystack = [
          user.display_name,
          user.mail,
          user.principal_name,
          user.extra.department,
          user.extra.job_title,
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(normalizedSearch);
      });
    });
  });

  it("renders the shared Entra directory on it-app and shows disabled management placeholders", async () => {
    const user = userEvent.setup();

    render(<UsersPage />);

    expect(await screen.findByRole("heading", { name: "Users" })).toBeInTheDocument();
    expect(screen.getByText("Entra user directory — status, department, job title, and account details.")).toBeInTheDocument();
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Grace Hopper")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Search name, email, department..."), "grace");

    await waitFor(() => {
      expect(mockApi.getAzureUsers).toHaveBeenLastCalledWith("grace");
      expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Grace Hopper")).toBeInTheDocument();

    await user.clear(screen.getByPlaceholderText("Search name, email, department..."));

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();

    await user.click(screen.getByText("Ada Lovelace"));

    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disable User" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reset Password" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Revoke Sessions" })).toBeDisabled();
    expect(screen.getByText("Coming soon on it-app.")).toBeInTheDocument();
  });

  it("renders the shared Azure directory view without primary-only management controls", async () => {
    const user = userEvent.setup();

    render(<AzureUsersPage />);

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Guests" }));

    await waitFor(() => {
      expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Grace Hopper")).toBeInTheDocument();

    await user.click(screen.getByText("Grace Hopper"));

    expect(await screen.findByRole("heading", { name: "Grace Hopper" })).toBeInTheDocument();
    expect(screen.queryByText("Management")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disable User" })).not.toBeInTheDocument();
  });
});
