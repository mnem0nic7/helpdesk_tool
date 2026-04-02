import { render, screen } from "@testing-library/react";
import { Outlet } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.tsx";

vi.mock("../components/Layout.tsx", () => ({
  default: () => <Outlet />,
}));

vi.mock("../lib/siteContext.ts", () => ({
  getSiteBranding: () => ({
    scope: "azure",
    appName: "Azure Control Center",
    dashboardName: "Azure Dashboard",
    alertPrefix: "Azure",
  }),
}));

vi.mock("../pages/AzureAccountHealthPage.tsx", () => ({
  default: () => <div>Security Account Health Page</div>,
}));

describe("App azure security routes", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/account-health");
  });

  it("redirects the legacy account-health route to the new security lane", async () => {
    render(<App />);
    expect(await screen.findByText("Security Account Health Page")).toBeInTheDocument();
  });
});
