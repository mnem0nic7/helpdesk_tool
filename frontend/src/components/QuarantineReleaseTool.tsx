/**
 * Tools-page card: admin toggle for the hourly Exchange Online quarantine
 * auto-release job, plus run history and per-message release detail.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type QuarantineReleaseRun } from "../lib/api.ts";

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export default function QuarantineReleaseTool() {
  const queryClient = useQueryClient();
  const [domainsInput, setDomainsInput] = useState("");
  const [selectedRunHour, setSelectedRunHour] = useState<string | null>(null);

  const statusQuery = useQuery({
    queryKey: ["quarantine-release", "status"],
    queryFn: () => api.getQuarantineReleaseStatus(),
  });

  const runsQuery = useQuery({
    queryKey: ["quarantine-release", "runs"],
    queryFn: () => api.getQuarantineReleaseRuns(30, 0),
  });

  const releasesQuery = useQuery({
    queryKey: ["quarantine-release", "releases", selectedRunHour],
    queryFn: () => api.getQuarantineReleaseReleases(50, 0, selectedRunHour ?? undefined),
  });

  const settingsMutation = useMutation({
    mutationFn: (body: { enabled?: boolean; allowed_domains?: string[] }) =>
      api.patchQuarantineReleaseSettings(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quarantine-release", "status"] });
    },
  });

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ["quarantine-release"] });
  }

  function handleSaveDomains() {
    const domains = domainsInput
      .split(",")
      .map((d) => d.trim())
      .filter((d) => d.length > 0);
    settingsMutation.mutate({ allowed_domains: domains });
  }

  const status = statusQuery.data;
  const enabled = status?.enabled ?? false;

  const settingsErrorMessage = settingsMutation.isError
    ? settingsMutation.error instanceof Error
      ? settingsMutation.error.message
      : "Failed to update settings"
    : null;

  const statusErrorMessage = statusQuery.isError
    ? statusQuery.error instanceof Error
      ? statusQuery.error.message
      : "Failed to load status"
    : null;

  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Exchange Online</div>
          <h2 className="mt-1 text-2xl font-semibold text-slate-900">Quarantine auto-release</h2>
          <p className="mt-1 text-sm text-slate-500">
            Hourly job that releases quarantined mail from trusted sender domains to all original recipients.
          </p>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          className="rounded border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
        >
          Refresh
        </button>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-600">Job enabled</span>
          <button
            role="switch"
            aria-checked={enabled}
            aria-label="Enable quarantine auto-release job"
            disabled={settingsMutation.isPending}
            onClick={() => settingsMutation.mutate({ enabled: !enabled })}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
              enabled ? "bg-emerald-500" : "bg-slate-300"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                enabled ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
        </div>

        <div className="h-4 w-px bg-slate-200" />

        <div className="text-sm text-slate-600">
          {statusErrorMessage ? (
            <span className="text-red-600">Unable to load status: {statusErrorMessage}</span>
          ) : status?.last_run ? (
            <>
              Last run <strong>{formatDateTime(status.last_run.ran_at)}</strong> —{" "}
              <strong>{status.last_run.checked_count}</strong> checked,{" "}
              <strong>{status.last_run.released_count} released</strong>,{" "}
              <strong>{status.last_run.failed_count}</strong> failed
            </>
          ) : (
            "No runs yet"
          )}
        </div>
      </div>

      {settingsErrorMessage ? <p className="mt-2 text-sm text-red-600">{settingsErrorMessage}</p> : null}

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div className="flex-1">
          <label htmlFor="quarantine-release-domains" className="text-sm font-medium text-slate-700">
            Trusted domains (comma-separated)
          </label>
          <input
            id="quarantine-release-domains"
            aria-label="Trusted domains"
            type="text"
            defaultValue={status?.allowed_domains.join(", ") ?? ""}
            onChange={(event) => setDomainsInput(event.target.value)}
            className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <button
          type="button"
          onClick={handleSaveDomains}
          disabled={settingsMutation.isPending}
          className="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          Save domains
        </button>
      </div>

      <div className="mt-6">
        <h3 className="text-sm font-semibold text-slate-700">Run history</h3>
        <div className="mt-2 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left">Hour</th>
                <th className="px-3 py-2 text-left">Checked</th>
                <th className="px-3 py-2 text-left">Released</th>
                <th className="px-3 py-2 text-left">Failed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(runsQuery.data?.items ?? []).map((run: QuarantineReleaseRun) => (
                <tr
                  key={run.run_hour}
                  onClick={() => setSelectedRunHour(run.run_hour)}
                  className={`cursor-pointer hover:bg-slate-50 ${selectedRunHour === run.run_hour ? "bg-sky-50" : ""}`}
                >
                  <td className="px-3 py-2">{formatDateTime(run.ran_at)}</td>
                  <td className="px-3 py-2">{run.checked_count}</td>
                  <td className="px-3 py-2">{run.released_count}</td>
                  <td className="px-3 py-2">{run.failed_count}</td>
                </tr>
              ))}
              {(runsQuery.data?.items ?? []).length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-center text-slate-500" colSpan={4}>
                    No runs yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-6">
        <h3 className="text-sm font-semibold text-slate-700">
          Released messages{selectedRunHour ? ` — ${formatDateTime(selectedRunHour)}` : ""}
        </h3>
        <div className="mt-2 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left">Sender</th>
                <th className="px-3 py-2 text-left">Recipient</th>
                <th className="px-3 py-2 text-left">Subject</th>
                <th className="px-3 py-2 text-left">Reason</th>
                <th className="px-3 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(releasesQuery.data?.items ?? []).map((release) => (
                <tr key={release.id} title={release.error ?? undefined}>
                  <td className="px-3 py-2">{release.sender_address}</td>
                  <td className="px-3 py-2">{release.recipient_address}</td>
                  <td className="px-3 py-2">{release.subject}</td>
                  <td className="px-3 py-2">{release.quarantine_reason}</td>
                  <td className={`px-3 py-2 ${release.status === "failed" ? "text-red-600" : "text-emerald-600"}`}>
                    {release.status}
                  </td>
                </tr>
              ))}
              {(releasesQuery.data?.items ?? []).length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-center text-slate-500" colSpan={5}>
                    No released messages yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
