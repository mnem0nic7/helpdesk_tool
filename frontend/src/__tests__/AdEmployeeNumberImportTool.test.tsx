/**
 * Tests for the AD employee-number bulk import card (Tools page).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import AdEmployeeNumberImportTool from "../components/AdEmployeeNumberImportTool.tsx";
import type { AdEmployeeNumberImportJobDetail, AdEmployeeNumberImportJobSummary } from "../lib/api.ts";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    createAdEmployeeNumberImportJob: vi.fn(),
    listAdEmployeeNumberImportJobs: vi.fn(),
    getAdEmployeeNumberImportJob: vi.fn(),
    confirmAdEmployeeNumberImportJob: vi.fn(),
    cancelAdEmployeeNumberImportJob: vi.fn(),
    adEmployeeNumberImportJobCsvUrl: vi.fn(),
  },
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

function baseJob(overrides: Partial<AdEmployeeNumberImportJobSummary> = {}): AdEmployeeNumberImportJobSummary {
  return {
    job_id: "job-1",
    requested_by: "admin@example.com",
    filename: "hr.csv",
    status: "awaiting_confirmation",
    total_rows: 3,
    update_count: 1,
    no_change_count: 1,
    not_found_count: 1,
    skipped_count: 0,
    applied_count: 0,
    apply_failed_count: 0,
    error: "",
    created_at: "2026-08-01T00:00:00+00:00",
    updated_at: "2026-08-01T00:00:00+00:00",
    completed_at: null,
    ...overrides,
  };
}

function jobDetail(overrides: Partial<AdEmployeeNumberImportJobDetail> = {}): AdEmployeeNumberImportJobDetail {
  return {
    ...baseJob(),
    rows: [
      {
        id: "row-1",
        job_id: "job-1",
        row_index: 0,
        source_email: "jane@example.com",
        ad_sam: "jdoe",
        ad_display_name: "Jane Doe",
        current_employee_number: "OLD1",
        new_employee_number: "NEW1",
        action: "update",
        applied: false,
        apply_error: "",
      },
    ],
    rows_total: 1,
    ...overrides,
  };
}

describe("AdEmployeeNumberImportTool", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.listAdEmployeeNumberImportJobs.mockResolvedValue([]);
    mockApi.getAdEmployeeNumberImportJob.mockResolvedValue(jobDetail());
    mockApi.adEmployeeNumberImportJobCsvUrl.mockReturnValue("/api/tools/ad-employee-number-import/jobs/job-1/csv");
  });

  it("renders the upload card", async () => {
    render(<AdEmployeeNumberImportTool />);

    expect(await screen.findByText("AD employee number import")).toBeInTheDocument();
  });

  it("uploads a CSV and shows the update-filtered preview with the row pre-checked", async () => {
    mockApi.createAdEmployeeNumberImportJob.mockResolvedValue({ job_id: "job-1", status: "queued" });
    mockApi.getAdEmployeeNumberImportJob.mockResolvedValue(jobDetail());

    render(<AdEmployeeNumberImportTool />);

    const file = new File(["emails_work_value,ENT_employeeNumber\njane@example.com,NEW1\n"], "hr.csv", {
      type: "text/csv",
    });
    const input = screen.getByLabelText("HR export CSV");
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload & preview" }));

    await waitFor(() => expect(mockApi.createAdEmployeeNumberImportJob).toHaveBeenCalledWith(file));

    expect(await screen.findByText("jane@example.com")).toBeInTheDocument();
    const checkbox = screen.getByRole("checkbox", { name: /jane@example.com/i });
    expect(checkbox).toBeChecked();
  });

  it("excludes an unchecked row from the confirm payload", async () => {
    mockApi.createAdEmployeeNumberImportJob.mockResolvedValue({ job_id: "job-1", status: "queued" });
    mockApi.getAdEmployeeNumberImportJob.mockResolvedValue(
      jobDetail({
        update_count: 2,
        rows: [
          {
            id: "row-1",
            job_id: "job-1",
            row_index: 0,
            source_email: "jane@example.com",
            ad_sam: "jdoe",
            ad_display_name: "Jane Doe",
            current_employee_number: "OLD1",
            new_employee_number: "NEW1",
            action: "update",
            applied: false,
            apply_error: "",
          },
          {
            id: "row-2",
            job_id: "job-1",
            row_index: 1,
            source_email: "bob@example.com",
            ad_sam: "bsmith",
            ad_display_name: "Bob Smith",
            current_employee_number: "OLD2",
            new_employee_number: "NEW2",
            action: "update",
            applied: false,
            apply_error: "",
          },
        ],
        rows_total: 2,
      }),
    );
    mockApi.confirmAdEmployeeNumberImportJob.mockResolvedValue({ job_id: "job-1", status: "applying" });

    render(<AdEmployeeNumberImportTool />);

    const file = new File(["x"], "hr.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("HR export CSV"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload & preview" }));

    const checkbox = await screen.findByRole("checkbox", { name: /jane@example.com/i });
    fireEvent.click(checkbox);
    expect(checkbox).not.toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: /Apply 1 update/ }));

    await waitFor(() =>
      expect(mockApi.confirmAdEmployeeNumberImportJob).toHaveBeenCalledWith("job-1", ["row-1"]),
    );
  });
});
