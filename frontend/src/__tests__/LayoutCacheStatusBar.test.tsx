import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";
import { screen } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import Layout from "../components/Layout.tsx";

type MockScope = "primary" | "oasisdev" | "azure" | "security" | "hrapp";

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
  getSiteBranding: () => ({
    scope: mockBrandingScope,
    appName: "Test App",
    dashboardName: "Test Dashboard",
    alertPrefix: "Test",
  }),
}));

vi.mock("../components/CacheStatusBar.tsx", () => ({
  default: () => <div data-testid="cache-status-bar" />,
}));

vi.mock("../components/AzureStatusBar.tsx", () => ({
  default: () => <div data-testid="azure-status-bar" />,
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
        <Route path="*" element={<div>Page content</div>} />
      </Route>
    </Routes>,
  );
}

describe("Layout cache status bar scoping", () => {
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

  it("renders the Jira cache status bar on the primary helpdesk host", async () => {
    renderLayoutAt("/", "primary");
    await screen.findByText("Page content");
    expect(screen.getByTestId("cache-status-bar")).toBeInTheDocument();
  });

  it("does not render the Jira cache status bar on the azure host", async () => {
    renderLayoutAt("/", "azure");
    await screen.findByText("Page content");
    expect(screen.queryByTestId("cache-status-bar")).not.toBeInTheDocument();
  });

  it("does not render the Jira cache status bar on the hrapp host", async () => {
    renderLayoutAt("/askhr-bot", "hrapp");
    await screen.findByText("Page content");
    expect(screen.queryByTestId("cache-status-bar")).not.toBeInTheDocument();
    // hrapp also has no Azure status widget — it gets neither.
    expect(screen.queryByTestId("azure-status-bar")).not.toBeInTheDocument();
  });
});
