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

vi.mock("../pages/AzureSecurityBreakGlassValidationPage.tsx", () => ({
  default: () => <div>Break-glass Account Validation Page</div>,
}));

vi.mock("../pages/AzureSecurityConditionalAccessTrackerPage.tsx", () => ({
  default: () => <div>Conditional Access Change Tracker Page</div>,
}));

vi.mock("../pages/AzureSecurityDeviceCompliancePage.tsx", () => ({
  default: () => <div>Device Compliance Review Page</div>,
}));

vi.mock("../pages/AzureSecurityDirectoryRoleReviewPage.tsx", () => ({
  default: () => <div>Directory Role Membership Review Page</div>,
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

  it("renders the break-glass validation lane on its dedicated route", async () => {
    window.history.replaceState({}, "", "/security/break-glass-validation");
    render(<App />);
    expect(await screen.findByText("Break-glass Account Validation Page")).toBeInTheDocument();
  });

  it("renders the conditional access tracker lane on its dedicated route", async () => {
    window.history.replaceState({}, "", "/security/conditional-access-tracker");
    render(<App />);
    expect(await screen.findByText("Conditional Access Change Tracker Page")).toBeInTheDocument();
  });

  it("renders the device compliance lane on its dedicated route", async () => {
    window.history.replaceState({}, "", "/security/device-compliance");
    render(<App />);
    expect(await screen.findByText("Device Compliance Review Page")).toBeInTheDocument();
  });

  it("renders the directory role review lane on its dedicated route", async () => {
    window.history.replaceState({}, "", "/security/directory-role-review");
    render(<App />);
    expect(await screen.findByText("Directory Role Membership Review Page")).toBeInTheDocument();
  });
});
