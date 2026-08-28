/**
 * Tools-page card: upload an ADP/Workday-style HR export CSV and bulk-update
 * the on-prem AD `employeeNumber` attribute. Matching runs first and produces
 * a preview; nothing is written to Active Directory until an admin confirms.
 */
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type AdEmployeeNumberImportJobDetail,
  type AdEmployeeNumberImportJobSummary,
  type AdEmployeeNumberImportRowAction,
} from "../lib/api.ts";
import { resolvePollingIntervalMs } from "../lib/queryPolling.ts";

const IN_PROGRESS_STATUSES = new Set(["queued", "matching", "applying"]);

const ROW_FILTERS: { value: AdEmployeeNumberImportRowAction; label: string }[] = [
  { value: "update", label: "Will update" },
  { value: "no_change", label: "No change" },
  { value: "not_found", label: "Not found in AD" },
  { value: "skipped_blank", label: "Skipped (blank value)" },
  { value: "skipped_duplicate", label: "Skipped (duplicate email)" },
];

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function statusLabel(status: AdEmployeeNumberImportJobSummary["status"]): string {
  return status.replaceAll("_", " ");
}

export default function AdEmployeeNumberImportTool() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [rowFilter, setRowFilter] = useState<AdEmployeeNumberImportRowAction>("update");
  const [excludedRowIds, setExcludedRowIds] = useState<Set<string>>(new Set());
  const [uploadError, setUploadError] = useState("");

  const jobsQuery = useQuery({
    queryKey: ["ad-employee-number-import", "jobs"],
    queryFn: () => api.listAdEmployeeNumberImportJobs(50),
    refetchInterval: (query) => {
      const jobs = query.state.data as AdEmployeeNumberImportJobSummary[] | undefined;
      return resolvePollingIntervalMs(jobs?.some((job) => IN_PROGRESS_STATUSES.has(job.status)) ? 3_000 : 60_000);
    },
  });

  const activeJobQuery = useQuery({
    queryKey: ["ad-employee-number-import", "jobs", activeJobId, rowFilter],
    queryFn: () => api.getAdEmployeeNumberImportJob(activeJobId as string, { action: rowFilter, limit: 200 }),
    enabled: !!activeJobId,
    refetchInterval: (query) => {
      const job = query.state.data as AdEmployeeNumberImportJobDetail | undefined;
      return resolvePollingIntervalMs(3_000, Boolean(job && IN_PROGRESS_STATUSES.has(job.status)));
    },
  });

  const createJobMutation = useMutation({
    mutationFn: (file: File) => api.createAdEmployeeNumberImportJob(file),
    onSuccess: (result) => {
      setUploadError("");
      setExcludedRowIds(new Set());
      setRowFilter("update");
      setActiveJobId(result.job_id);
      queryClient.invalidateQueries({ queryKey: ["ad-employee-number-import", "jobs"] });
    },
    onError: (error: unknown) => {
      setUploadError(error instanceof Error ? error.message : "Upload failed");
    },
  });

  const confirmMutation = useMutation({
    mutationFn: () => api.confirmAdEmployeeNumberImportJob(activeJobId as string, Array.from(excludedRowIds)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ad-employee-number-import", "jobs", activeJobId] });
      queryClient.invalidateQueries({ queryKey: ["ad-employee-number-import", "jobs"] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelAdEmployeeNumberImportJob(activeJobId as string),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ad-employee-number-import", "jobs", activeJobId] });
      queryClient.invalidateQueries({ queryKey: ["ad-employee-number-import", "jobs"] });
    },
  });

  function handleUpload() {
    if (!selectedFile) return;
    createJobMutation.mutate(selectedFile);
  }

  function toggleRow(rowId: string) {
    setExcludedRowIds((prev) => {
      const next = new Set(prev);
      if (next.has(rowId)) {
        next.delete(rowId);
      } else {
        next.add(rowId);
      }
      return next;
    });
  }

  const job = activeJobQuery.data;
  const isUploading = createJobMutation.isPending;
  const isInProgress = !!job && IN_PROGRESS_STATUSES.has(job.status);
  const isAwaitingConfirmation = job?.status === "awaiting_confirmation";
  const isFinished =
    !!job && (job.status === "completed" || job.status === "completed_with_errors" || job.status === "failed" || job.status === "cancelled");
  const updateRowsIncluded = job ? Math.max(job.update_count - excludedRowIds.size, 0) : 0;

  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Active Directory</div>
          <h2 className="mt-1 text-2xl font-semibold text-slate-900">AD employee number import</h2>
          <p className="mt-1 text-sm text-slate-500">
            Upload an HR export CSV to bulk-update the <code>employeeNumber</code> attribute in Active Directory.
            Nothing is written until you review and confirm the changes below.
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label htmlFor="ad-employee-number-import-file" className="sr-only">
          HR export CSV
        </label>
        <input
          id="ad-employee-number-import-file"
          aria-label="HR export CSV"
          ref={fileInputRef}
          type="file"
          accept=".csv"
          onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
          className="text-sm text-slate-700"
        />
        <button
          type="button"
          onClick={handleUpload}
          disabled={!selectedFile || isUploading}
          className="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isUploading ? "Uploading..." : "Upload & preview"}
        </button>
      </div>
      {uploadError ? <p className="mt-2 text-sm text-red-600">{uploadError}</p> : null}

      {activeJobId ? (
        <div className="mt-6 space-y-4">
          {isInProgress && !isAwaitingConfirmation ? (
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              {job?.status === "applying" ? "Applying confirmed changes..." : "Matching CSV rows against Active Directory..."}
            </div>
          ) : null}

          {isAwaitingConfirmation && job ? (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-5">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-center">
                  <div className="text-lg font-semibold text-slate-900">{job.total_rows}</div>
                  <div className="text-[11px] uppercase tracking-wide text-slate-500">Total rows</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-center">
                  <div className="text-lg font-semibold text-slate-900">{job.update_count}</div>
                  <div className="text-[11px] uppercase tracking-wide text-slate-500">Will update</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-center">
                  <div className="text-lg font-semibold text-slate-900">{job.no_change_count}</div>
                  <div className="text-[11px] uppercase tracking-wide text-slate-500">No change</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-center">
                  <div className="text-lg font-semibold text-slate-900">{job.not_found_count}</div>
                  <div className="text-[11px] uppercase tracking-wide text-slate-500">Not found</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-center">
                  <div className="text-lg font-semibold text-slate-900">{job.skipped_count}</div>
                  <div className="text-[11px] uppercase tracking-wide text-slate-500">Skipped</div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <label htmlFor="ad-employee-number-import-filter" className="text-sm text-slate-600">
                  Show:
                </label>
                <select
                  id="ad-employee-number-import-filter"
                  value={rowFilter}
                  onChange={(event) => setRowFilter(event.target.value as AdEmployeeNumberImportRowAction)}
                  className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
                >
                  {ROW_FILTERS.map((filter) => (
                    <option key={filter.value} value={filter.value}>
                      {filter.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="overflow-x-auto rounded-2xl border border-slate-200">
                <table className="min-w-full divide-y divide-slate-200 text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      {rowFilter === "update" ? <th className="px-3 py-2 text-left">Apply</th> : null}
                      <th className="px-3 py-2 text-left">CSV email</th>
                      <th className="px-3 py-2 text-left">Matched AD user</th>
                      <th className="px-3 py-2 text-left">Current employeeNumber</th>
                      <th className="px-3 py-2 text-left">New employeeNumber</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {job.rows.map((row) => (
                      <tr key={row.id}>
                        {rowFilter === "update" ? (
                          <td className="px-3 py-2">
                            <input
                              type="checkbox"
                              aria-label={row.source_email}
                              checked={!excludedRowIds.has(row.id)}
                              onChange={() => toggleRow(row.id)}
                            />
                          </td>
                        ) : null}
                        <td className="px-3 py-2">{row.source_email}</td>
                        <td className="px-3 py-2">{row.ad_display_name || row.ad_sam || "—"}</td>
                        <td className="px-3 py-2">{row.current_employee_number || "—"}</td>
                        <td className="px-3 py-2">{row.new_employee_number || "—"}</td>
                      </tr>
                    ))}
                    {job.rows.length === 0 ? (
                      <tr>
                        <td className="px-3 py-4 text-center text-slate-500" colSpan={5}>
                          No rows match this filter.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>

              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => confirmMutation.mutate()}
                  disabled={job.update_count === 0 || updateRowsIncluded === 0 || confirmMutation.isPending}
                  className="rounded-full bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {confirmMutation.isPending ? "Applying..." : `Apply ${updateRowsIncluded} update${updateRowsIncluded === 1 ? "" : "s"}`}
                </button>
                <button
                  type="button"
                  onClick={() => cancelMutation.mutate()}
                  disabled={cancelMutation.isPending}
                  className="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700"
                >
                  Cancel job
                </button>
              </div>
            </div>
          ) : null}

          {isFinished && job ? (
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-700">
              <div className="font-semibold">Job {statusLabel(job.status)}</div>
              <p className="mt-1 text-slate-600">
                {job.applied_count} applied, {job.apply_failed_count} failed.
                {job.error ? ` ${job.error}` : ""}
              </p>
              <a
                className="mt-2 inline-block text-sm font-semibold text-indigo-600 hover:underline"
                href={api.adEmployeeNumberImportJobCsvUrl(job.job_id)}
              >
                Download CSV report
              </a>
            </div>
          ) : null}
        </div>
      ) : null}

      {jobsQuery.data && jobsQuery.data.length > 0 ? (
        <div className="mt-6">
          <h3 className="text-sm font-semibold text-slate-700">Recent jobs</h3>
          <ul className="mt-2 divide-y divide-slate-100 rounded-2xl border border-slate-200">
            {jobsQuery.data.map((recentJob) => (
              <li key={recentJob.job_id}>
                <button
                  type="button"
                  onClick={() => {
                    setActiveJobId(recentJob.job_id);
                    setRowFilter("update");
                    setExcludedRowIds(new Set());
                  }}
                  className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-2 text-left text-sm hover:bg-slate-50"
                >
                  <span className="font-medium text-slate-900">{recentJob.filename}</span>
                  <span className="text-slate-500">{statusLabel(recentJob.status)}</span>
                  <span className="text-xs text-slate-400">{formatDateTime(recentJob.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
