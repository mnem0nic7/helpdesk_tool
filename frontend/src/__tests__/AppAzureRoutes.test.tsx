import { render, screen } from "@testing-library/react";
import { Outlet } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
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

vi.mock("../pages/AzureSecurityGuestAccessReviewPage.tsx", () => ({
  default: () => <div>Guest Access Review Page</div>,
}));

vi.mock("../pages/AzureSecurityDlpReviewPage.tsx", () => ({
  default: () => <div>DLP Findings Review Page</div>,
}));

describe("App azure security routes", () => {
  it("redirects the legacy account-health route to the new security lane", async () => {
    window.history.replaceState({}, "", "/account-health");
    render(<App />);
    expect(await screen.findByText("Security Account Health Page")).toBeInTheDocument();
  });

  it("renders the guest access review security lane on its dedicated route", async () => {
    window.history.replaceState({}, "", "/security/guest-access-review");
    render(<App />);
    expect(await screen.findByText("Guest Access Review Page")).toBeInTheDocument();
  });

  it("renders the dlp findings review lane on its dedicated route", async () => {
    window.history.replaceState({}, "", "/security/dlp-review");
    render(<App />);
    expect(await screen.findByText("DLP Findings Review Page")).toBeInTheDocument();
  });
});
