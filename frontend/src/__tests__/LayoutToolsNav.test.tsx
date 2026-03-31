import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";
import { screen } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import Layout from "../components/Layout.tsx";

type MockScope = "primary" | "azure" | "oasisdev";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getMe: vi.fn(),
    logout: vi.fn(),
  },
}));

let mockBrandingScope: MockScope = "primary";

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

vi.mock("../lib/siteContext.ts", () => ({
  getSiteBranding: () => {
    if (mockBrandingScope === "azure") {
      return {
        scope: "azure",
        appName: "Azure Control Center",
        dashboardName: "Azure Dashboard",
        alertPrefix: "Azure",
      };
    }
    return {
      scope: mockBrandingScope,
      appName: "OIT Helpdesk",
      dashboardName: "OIT Dashboard",
      alertPrefix: "OIT",
    };
  },
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

function renderLayoutAt(pathname: string, scope: MockScope) {
  mockBrandingScope = scope;
  window.history.replaceState({}, "", pathname);
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
    mockBrandingScope = "primary";
    mockApi.getMe.mockResolvedValue({
      email: "tech@example.com",
      name: "Tech User",
      is_admin: true,
      can_manage_users: true,
      can_access_tools: true,
    });
  });

  it("shows Tools on the primary host", async () => {
    renderLayoutAt("/", "primary");
    expect(await screen.findByRole("link", { name: /Tools/ })).toBeInTheDocument();
  });

  it("shows Tools on the azure host", async () => {
    renderLayoutAt("/", "azure");
    expect(await screen.findByRole("link", { name: /Tools/ })).toBeInTheDocument();
  });

  it("hides Tools on oasisdev", async () => {
    renderLayoutAt("/", "oasisdev");
    await screen.findByText("Page content");
    expect(screen.queryByRole("link", { name: /Tools/ })).not.toBeInTheDocument();
  });

  it("shows Tools even if the legacy tools-access flag is false", async () => {
    mockApi.getMe.mockResolvedValueOnce({
      email: "someone@example.com",
      name: "Someone",
      is_admin: true,
      can_manage_users: true,
      can_access_tools: false,
    });

    renderLayoutAt("/", "primary");

    expect(await screen.findByRole("link", { name: /Tools/ })).toBeInTheDocument();
  });
});
