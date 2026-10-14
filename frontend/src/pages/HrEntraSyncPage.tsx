import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type HrEntraSyncIssue } from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";

const STATUS_FILTERS = ["pending", "synced", "not_found", "ambiguous", "failed"] as const;

const STATUS_STYLES: Record<HrEntraSyncIssue["status"], string> = {
  pending: "bg-amber-50 text-amber-700",
  synced: "bg-emerald-50 text-emerald-700",
  not_found: "bg-slate-100 text-slate-600",
  ambiguous: "bg-orange-50 text-orange-700",
  failed: "bg-rose-50 text-rose-700",
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function parseList(raw: string): string[] {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.map(String);
    if (parsed && typeof parsed === "object") return Object.keys(parsed);
  } catch {
    /* not JSON: fall through */
  }
  return [];
}

export default function HrEntraSyncPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [issueKey, setIssueKey] = useState("");
  const [testEmail, setTestEmail] = useState("");

  const statusQuery = useQuery({
    queryKey: ["hr-entra-sync", "status"],
    queryFn: () => api.getHrEntraSyncStatus(),
    ...getPollingQueryOptions("slow_5m"),
  });

  const issuesQuery = useQuery({
    queryKey: ["hr-entra-sync", "issues", statusFilter],
    queryFn: () => api.getHrEntraSyncIssues(statusFilter || undefined),
    ...getPollingQueryOptions("slow_5m"),
  });

  const dryRun = useMutation({
    mutationFn: (target: { key: string; email?: string }) => api.dryRunHrEntraSync(target.key, target.email),
  });

  const status = statusQuery.data;
  const counts = status?.counts;
  const issues = issuesQuery.data?.issues ?? [];
  const mappings = status?.mappings ?? [];
  const activeCount = mappings.filter((m) => m.active).length;
  const failed = counts?.failed ?? 0;

  function handleDryRun() {
    const key = issueKey.trim().toUpperCase();
    if (!key) return;
    dryRun.mutate({ key, email: testEmail.trim() || undefined });
  }

  const tiles: Array<{ label: string; value: number | undefined; tone: string }> = [
    { label: "Pending", value: counts?.pending, tone: "text-amber-700" },
    { label: "Synced", value: counts?.synced, tone: "text-emerald-700" },
    { label: "No Entra match", value: counts?.not_found, tone: "text-slate-700" },
    { label: "Ambiguous", value: counts?.ambiguous, tone: "text-orange-700" },
    { label: "Failed", value: counts?.failed, tone: "text-rose-700" },
  ];

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">HR</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-900">Entra → Jira Sync</h1>
        <p className="mt-1 text-sm text-slate-500">
          Fills newly created {status?.projects.join(" and ") || "HRD and LIBTA"} tickets with the employee&apos;s
          Entra attributes, matched by the work or personal email on the ticket, or the reporter&apos;s email when the
          ticket has none (service accounts and automation are ignored). Editing either email on a ticket re-runs it.
        </p>
      </div>

      {statusQuery.isError ? (
        <div role="alert" className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          Could not load connector status.
        </div>
      ) : null}

      {status ? (
        <div
          role="status"
          className={`mt-4 rounded-2xl border px-4 py-3 text-sm ${
            !status.enabled
              ? "border-amber-200 bg-amber-50 text-amber-800"
              : failed > 0
                ? "border-rose-200 bg-rose-50 text-rose-700"
                : "border-emerald-200 bg-emerald-50 text-emerald-800"
          }`}
        >
          {!status.enabled
            ? "Connector is disabled — it is not reading or writing any tickets. Set HR_ENTRA_SYNC_ENABLED=true to turn it on."
            : failed > 0
              ? `Connector is running, but ${failed} ticket${failed === 1 ? "" : "s"} failed. Check the ticket list below.`
              : "Connector is running."}
          <span className="ml-2 text-xs opacity-80">Last activity: {formatDateTime(status.last_activity_at)}</span>
        </div>
      ) : null}

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {tiles.map((tile) => (
          <div key={tile.label} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="text-xs text-slate-500">{tile.label}</div>
            <div className={`mt-1 text-2xl font-semibold ${tile.tone}`}>{tile.value ?? "—"}</div>
          </div>
        ))}
      </div>

      {status ? (
        <p className="mt-3 text-xs text-slate-500">
          Checks every {status.poll_seconds}s for tickets created in the last {status.lookback_minutes} minutes; retries
          a ticket with no Entra match for {status.retry_minutes} minutes, then adds an internal note. Entra values
          overwrite existing Jira values.
        </p>
      ) : null}

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-slate-700">Test a ticket (dry run)</h2>
        <p className="mt-1 text-xs text-slate-500">
          Shows which fields would be written without changing the ticket. Enter an email to use instead of the
          ticket&apos;s own — handy for tickets that carry none.
        </p>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="entra-sync-key" className="text-sm font-medium text-slate-700">
              Ticket key
            </label>
            <input
              id="entra-sync-key"
              aria-label="Ticket key"
              value={issueKey}
              onChange={(event) => setIssueKey(event.target.value)}
              placeholder="HRD-1234"
              className="mt-1 w-40 rounded-xl border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label htmlFor="entra-sync-email" className="text-sm font-medium text-slate-700">
              Email (optional)
            </label>
            <input
              id="entra-sync-email"
              aria-label="Email override"
              value={testEmail}
              onChange={(event) => setTestEmail(event.target.value)}
              placeholder="name@librasolutionsgroup.com"
              className="mt-1 w-72 rounded-xl border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <button
            type="button"
            onClick={handleDryRun}
            disabled={dryRun.isPending || !issueKey.trim()}
            className="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            Run dry run
          </button>
        </div>
        {dryRun.isError ? (
          <div role="alert" className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {(dryRun.error as Error).message}
          </div>
        ) : null}
        {dryRun.data ? (
          <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
            <div>
              Result: <strong>{dryRun.data.outcome}</strong>
              {dryRun.data.matched_upn
                ? ` — matched ${dryRun.data.matched_upn} (${dryRun.data.matched_via}${dryRun.data.email_source ? `, from ${dryRun.data.email_source}` : ""})`
                : ""}
            </div>
            {dryRun.data.outcome === "no_email" ? <div>No work or personal email was found on this ticket.</div> : null}
            {dryRun.data.outcome === "no_match" ? (
              <div>No Entra account matched {dryRun.data.emails.join(", ")}.</div>
            ) : null}
            {dryRun.data.outcome === "ambiguous" ? (
              <div>More than one Entra account matches: {(dryRun.data.candidates ?? []).join(", ")}.</div>
            ) : null}
            {dryRun.data.fields_written ? (
              <div className="mt-1">
                Would write {dryRun.data.fields_written.length} field(s):{" "}
                {dryRun.data.fields_written.join(", ") || "none"}
                {dryRun.data.entra_empty && dryRun.data.entra_empty.length > 0
                  ? ` · Entra has no value for: ${dryRun.data.entra_empty.join(", ")}`
                  : ""}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="mt-6">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-700">Tickets</h2>
          <select
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="rounded-xl border border-slate-300 px-3 py-1.5 text-sm"
          >
            <option value="">All statuses</option>
            {STATUS_FILTERS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div className="mt-2 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left">Ticket</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-left">First seen</th>
                <th className="px-3 py-2 text-left">Attempts</th>
                <th className="px-3 py-2 text-left">Matched</th>
                <th className="px-3 py-2 text-left">Fields</th>
                <th className="px-3 py-2 text-left">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {issues.map((row) => {
                const skipped = parseList(row.fields_skipped);
                return (
                  <tr key={row.issue_key}>
                    <td className="px-3 py-2 font-medium">{row.issue_key}</td>
                    <td className="px-3 py-2">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_STYLES[row.status]}`}>
                        {row.status}
                      </span>
                    </td>
                    <td className="px-3 py-2">{formatDateTime(row.first_seen_at)}</td>
                    <td className="px-3 py-2">{row.attempts}</td>
                    <td className="px-3 py-2">{row.matched_upn
                        ? `${row.matched_upn} (${row.matched_via}${row.email_source ? `, from ${row.email_source}` : ""})`
                        : "—"}</td>
                    <td className="px-3 py-2">
                      {row.status === "synced"
                        ? `${parseList(row.fields_written).length} written${skipped.length ? `, ${skipped.length} rejected by Jira` : ""}`
                        : "—"}
                    </td>
                    <td className="max-w-xs truncate px-3 py-2 text-slate-500" title={row.error}>
                      {row.error || "—"}
                    </td>
                  </tr>
                );
              })}
              {issues.length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-center text-slate-500" colSpan={7}>
                    {issuesQuery.isLoading ? "Loading…" : "No tickets yet."}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-slate-700">
          Field mapping ({activeCount} of {mappings.length} active)
        </h2>
        <div className="mt-2 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left">Jira field</th>
                <th className="px-3 py-2 text-left">Entra source</th>
                <th className="px-3 py-2 text-left">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {mappings.map((m) => (
                <tr key={m.jira_name}>
                  <td className="px-3 py-2">
                    {m.jira_name}
                    {m.jira_field_id ? <span className="ml-2 text-xs text-slate-400">{m.jira_field_id}</span> : null}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{m.entra_source ?? "—"}</td>
                  <td className="px-3 py-2">
                    {m.active ? (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                        active
                      </span>
                    ) : (
                      <span title={m.note}>
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
                          disabled
                        </span>
                        {m.note ? <span className="ml-2 text-xs text-slate-500">{m.note}</span> : null}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
