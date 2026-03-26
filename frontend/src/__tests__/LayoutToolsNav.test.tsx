import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";
import { screen } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import Layout from "../components/Layout.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getMe: vi.fn(),
    logout: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

vi.mock("../components/CacheStatusBar.tsx", () => ({
  default: () => null,
}));

vi.mock("../components/AzureStatusBar.tsx", () => ({
  default: () => null,
}));

vi.mock("../components/AzureQuickJump.tsx", () => ({
  default: () => null,
}));

vi.mock("../lib/deployVersion.ts", () => ({
  hasNewFrontendBuild: vi.fn().mockResolvedValue(false),
}));

vi.mock("../lib/errorLogging.ts", () => ({
  logClientError: vi.fn(),
}));

function renderLayoutAt(url: string) {
  window.history.replaceState({}, "", url);
  return render(
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<div>Page content</div>} />
      </Route>
    </Routes>,
  );
}

describe("Layout tools navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getMe.mockResolvedValue({
      email: "tech@example.com",
      name: "Tech User",
      is_admin: true,
      can_manage_users: true,
      can_access_tools: true,
    });
  });

  it("shows Tools on the primary host", async () => {
    renderLayoutAt("https://it-app.movedocs.com/");
    expect(await screen.findByRole("link", { name: "Tools" })).toBeInTheDocument();
  });

  it("shows Tools on the azure host", async () => {
    renderLayoutAt("https://azure.movedocs.com/");
    expect(await screen.findByRole("link", { name: "Tools" })).toBeInTheDocument();
  });

  it("hides Tools on oasisdev", async () => {
    renderLayoutAt("https://oasisdev.movedocs.com/");
    await screen.findByText("Page content");
    expect(screen.queryByRole("link", { name: "Tools" })).not.toBeInTheDocument();
  });

  it("hides Tools when the user is not allowed to access that surface", async () => {
    mockApi.getMe.mockResolvedValueOnce({
      email: "someone@example.com",
      name: "Someone",
      is_admin: true,
      can_manage_users: true,
      can_access_tools: false,
    });

    renderLayoutAt("https://it-app.movedocs.com/");

    await screen.findByText("Page content");
    expect(screen.queryByRole("link", { name: "Tools" })).not.toBeInTheDocument();
  });
});
