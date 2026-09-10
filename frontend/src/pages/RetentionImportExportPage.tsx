import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type RetentionImportRow } from "../lib/api.ts";

function summarize(rows: RetentionImportRow[]) {
  const counts = { create: 0, update: 0, skip: 0, error: 0 };
  for (const row of rows) {
    counts[row.action] += 1;
  }
  return counts;
}

export default function RetentionImportExportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [previewRows, setPreviewRows] = useState<RetentionImportRow[] | null>(null);
  const [resultRows, setResultRows] = useState<RetentionImportRow[] | null>(null);

  const previewMutation = useMutation({
    mutationFn: (uploaded: File) => api.previewRetentionImport(uploaded),
    onSuccess: (data) => {
      setPreviewRows(data.rows);
      setResultRows(null);
    },
  });

  const applyMutation = useMutation({
    mutationFn: (uploaded: File) => api.applyRetentionImport(uploaded),
    onSuccess: (data) => setResultRows(data.rows),
  });

  function handleFileChange(selected: File | null) {
    setFile(selected);
    setPreviewRows(null);
    setResultRows(null);
    previewMutation.reset();
    applyMutation.reset();
  }

  const summary = previewRows ? summarize(previewRows) : null;
  const actionableCount = summary ? summary.create + summary.update : 0;
  const rowsToShow = resultRows ?? previewRows ?? [];

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold">Import / Export</h1>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">Export</h2>
        <p className="max-w-2xl text-sm text-slate-600">
          Download every known team and channel, with its current retention policy status, as an .xlsx workbook.
          Team names come from a live lookup; channel names come from the same periodically refreshed cache the
          search box uses, so a just-created channel may not appear until the next refresh.
        </p>
        <a
          href={api.retentionExportUrl}
          className="inline-block rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
        >
          Export channels (.xlsx)
        </a>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold">Import</h2>
        <p className="max-w-2xl text-sm text-slate-600">
          Upload an edited export. Only rows with a non-blank <code>retention_days</code> are touched — leave it
          blank to leave a channel alone. Every touched policy lands as <strong>pending_preview</strong>, exactly
          like creating one by hand: nothing deletes anything until it's individually previewed and confirmed from
          the Teams &amp; Channels page.
        </p>
        <div className="flex items-center gap-2">
          <input
            type="file"
            accept=".xlsx"
            aria-label="Import file"
            onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
            className="block text-sm"
          />
          <button
            type="button"
            onClick={() => file && previewMutation.mutate(file)}
            disabled={!file || previewMutation.isPending}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            Preview
          </button>
        </div>

        {previewMutation.isError && (
          <p className="text-sm text-red-700">
            {previewMutation.error instanceof Error ? previewMutation.error.message : "Failed to read the file"}
          </p>
        )}
        {applyMutation.isError && (
          <p className="text-sm text-red-700">
            {applyMutation.error instanceof Error ? applyMutation.error.message : "Failed to apply the import"}
          </p>
        )}

        {summary && !resultRows && (
          <div className="flex items-center gap-4 text-sm">
            <span className="text-slate-600">
              {summary.create} to create, {summary.update} to update, {summary.skip} skipped, {summary.error} with
              errors
            </span>
            <button
              type="button"
              onClick={() => file && applyMutation.mutate(file)}
              disabled={!file || actionableCount === 0 || applyMutation.isPending}
              className="rounded bg-red-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              Apply {actionableCount} change{actionableCount === 1 ? "" : "s"}
            </button>
          </div>
        )}

        {rowsToShow.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th className="py-1">Team</th>
                <th>Channel</th>
                <th>Current</th>
                <th>New retention_days</th>
                <th>{resultRows ? "Result" : "Action"}</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {rowsToShow.map((row, idx) => (
                <tr key={`${row.team_id}-${row.channel_id}-${idx}`} className="border-t border-slate-100">
                  <td className="py-1">{row.team_name || row.team_id}</td>
                  <td>{row.channel_name || row.channel_id}</td>
                  <td>
                    {row.current_status ? `${row.current_status}${row.current_retention_days ? `, ${row.current_retention_days}d` : ""}` : "none"}
                  </td>
                  <td>{row.retention_days ?? "—"}</td>
                  <td>{row.result ?? row.action}</td>
                  <td className="text-red-600">{row.error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
