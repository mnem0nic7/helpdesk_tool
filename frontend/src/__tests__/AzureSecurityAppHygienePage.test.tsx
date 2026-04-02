import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "../test-utils.tsx";
import AzureSecurityAppHygienePage from "../pages/AzureSecurityAppHygienePage.tsx";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    getAzureSecurityAppHygiene: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

function buildResponse() {
  return {
    generated_at: "2026-04-02T02:00:00Z",
    directory_last_refresh: "2026-04-02T01:51:00Z",
    metrics: [
      {
        key: "expired_credentials",
        label: "Expired credentials",
        value: 2,
        detail: "Credentials that are already expired.",
        tone: "rose",
      },
      {
        key: "apps_without_owners",
        label: "Apps without owners",
        value: 1,
        detail: "App registrations missing owner coverage.",
        tone: "amber",
      },
    ],
    flagged_apps: [
      {
        application_id: "app-1",
        app_id: "00000000-1111-2222-3333-444444444444",
        display_name: "Payroll Connector",
        sign_in_audience: "AzureADMyOrg",
        created_datetime: "2025-01-10T00:00:00Z",
        publisher_domain: "contoso.com",
        verified_publisher_name: "",
        owner_count: 0,
        owners: [],
        owner_lookup_error: "",
        credential_count: 1,
        password_credential_count: 1,
        key_credential_count: 0,
        next_credential_expiry: "2026-04-10T00:00:00Z",
        expired_credential_count: 1,
        expiring_30d_count: 0,
        expiring_90d_count: 0,
        status: "critical",
        flags: ["1 credential is already expired.", "No application owners are recorded."],
      },
      {
        application_id: "app-2",
        app_id: "55555555-6666-7777-8888-999999999999",
        display_name: "External Intake",
        sign_in_audience: "AzureADandPersonalMicrosoftAccount",
        created_datetime: "2025-02-10T00:00:00Z",
        publisher_domain: "fabrikam.com",
        verified_publisher_name: "",
        owner_count: 1,
        owners: ["Ada Lovelace"],
        owner_lookup_error: "",
        credential_count: 1,
        password_credential_count: 1,
        key_credential_count: 0,
        next_credential_expiry: "2026-04-20T00:00:00Z",
        expired_credential_count: 0,
        expiring_30d_count: 1,
        expiring_90d_count: 1,
        status: "warning",
        flags: ["1 credential expires within 30 days.", "App allows sign-ins outside the home tenant."],
      },
    ],
    credentials: [
      {
        application_id: "app-1",
        app_id: "00000000-1111-2222-3333-444444444444",
        application_display_name: "Payroll Connector",
        credential_type: "secret",
        display_name: "Prod secret",
        key_id: "secret-1",
        start_date_time: "2025-01-01T00:00:00Z",
        end_date_time: "2026-03-01T00:00:00Z",
        days_until_expiry: -10,
        status: "expired",
        owner_count: 0,
        owners: [],
        flags: ["Credential is already expired."],
      },
      {
        application_id: "app-2",
        app_id: "55555555-6666-7777-8888-999999999999",
        application_display_name: "External Intake",
        credential_type: "secret",
        display_name: "External secret",
        key_id: "secret-2",
        start_date_time: "2025-01-01T00:00:00Z",
        end_date_time: "2026-04-20T00:00:00Z",
        days_until_expiry: 5,
        status: "expiring",
        owner_count: 1,
        owners: ["Ada Lovelace"],
        flags: ["Credential expires within 30 days."],
      },
    ],
    warnings: ["Detailed app credential and owner metadata will fill in after the next Azure directory refresh under the upgraded collector."],
    scope_notes: [
      "This v1 review uses cached app registration metadata from Microsoft Graph, including password and key credential expiration data.",
      "Owner coverage comes from batched Microsoft Graph owner lookups during the Azure directory refresh.",
    ],
  };
}

describe("AzureSecurityAppHygienePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getAzureSecurityAppHygiene.mockResolvedValue(buildResponse());
  });

  it("renders the application hygiene workspace", async () => {
    render(<AzureSecurityAppHygienePage />);

    expect(await screen.findByText("Application Hygiene")).toBeInTheDocument();
    expect(screen.getByText("Flagged app registrations")).toBeInTheDocument();
    expect(screen.getByText("Credential watch table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Security workspace" })).toHaveAttribute("href", "/security");
    expect(screen.getByRole("link", { name: "Open Identity Review" })).toHaveAttribute("href", "/security/identity-review");
    expect(screen.getByRole("link", { name: "Open app inventory" })).toHaveAttribute("href", "/identity?tab=app-registrations");
    expect(screen.getAllByText("Payroll Connector").length).toBeGreaterThan(0);
    expect(screen.getAllByText("External Intake").length).toBeGreaterThan(0);
    expect(screen.getByText(/upgraded collector/i)).toBeInTheDocument();
  });

  it("filters flagged apps and credentials by search and status", async () => {
    render(<AzureSecurityAppHygienePage />);

    expect(await screen.findByText("Flagged app registrations")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Search app names, IDs, owners, publishers, or flags..."), {
      target: { value: "External" },
    });
    fireEvent.change(screen.getByDisplayValue("All app statuses"), {
      target: { value: "warning" },
    });
    fireEvent.change(screen.getByDisplayValue("All credential states"), {
      target: { value: "expiring" },
    });

    expect(screen.getAllByText("External Intake").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("Payroll Connector")).toHaveLength(0);
    expect(screen.getAllByText("External secret").length).toBeGreaterThan(0);
  });
});
