import { useEffect, useState, useDeferredValue } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AppLoginAuditEvent, type OneDriveCopyJobStatus, type OneDriveCopyUserOption } from "../lib/api.ts";
import { getSiteBranding } from "../lib/siteContext.ts";

const EXCLUDED_ROOT_FOLDERS = [
  "Apps",
  "Attachments",
  "Microsoft Teams Chat Files",
  "Microsoft Copilot Chat Files",
  "Recordings",
  "Videos",
];

function formatDateTime(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function statusTone(status: OneDriveCopyJobStatus["status"]): string {
  switch (status) {
    case "completed":
      return "bg-emerald-100 text-emerald-700";
    case "failed":
      return "bg-red-100 text-red-700";
    case "running":
      return "bg-amber-100 text-amber-700";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function phaseLabel(phase: OneDriveCopyJobStatus["phase"]): string {
  switch (phase) {
    case "resolving_drives":
      return "Resolving drives";
    case "enumerating":
      return "Enumerating";
    case "creating_folders":
      return "Creating folders";
    case "dispatching_copy":
      return "Dispatching copy";
    default:
      return phase.replace(/_/g, " ");
  }
}

function inputClass() {
  return "w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-sky-500";
}

function buttonClass(kind: "primary" | "secondary" = "secondary", disabled = false) {
  if (disabled) {
    return "rounded-xl border border-slate-200 bg-slate-100 px-4 py-2 text-sm font-medium text-slate-400";
  }
  if (kind === "primary") {
    return "rounded-xl border border-sky-600 bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700";
  }
  return "rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-400 hover:bg-slate-50";
}

function CountCard({ label, value, tone = "text-slate-900" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function LoginAuditPanel({ events }: { events: AppLoginAuditEvent[] }) {
  return (
    <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Login audit</div>
        <h2 className="mt-1 text-2xl font-semibold text-slate-900">Recent app sign-ins</h2>
        <p className="mt-2 text-sm text-slate-600">
          This tracks successful MoveDocs logins across the shared app hosts so we can see who signed in, where they landed, and which auth provider they used.
        </p>
      </div>

      {events.length > 0 ? (
        <div className="space-y-3">
          {events.map((event) => (
            <div key={event.event_id} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="font-medium text-slate-900">{event.name || event.email}</div>
                  <div className="text-sm text-slate-500">{event.email}</div>
                </div>
                <div className="text-right text-xs text-slate-500">
                  <div>{formatDateTime(event.created_at)}</div>
                  <div>{event.site_scope}</div>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-slate-200 px-2.5 py-1 font-semibold uppercase tracking-wide text-slate-700">
                  {event.auth_provider}
                </span>
                {event.source_ip ? (
                  <span className="rounded-full bg-white px-2.5 py-1 text-slate-600">IP {event.source_ip}</span>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">No successful sign-ins have been recorded yet.</div>
      )}
    </section>
  );
}

function DirectoryTypeaheadField({
  label,
  value,
  onChange,
  query,
  loading,
  options,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  query: string;
  loading: boolean;
  options: OneDriveCopyUserOption[] | undefined;
  placeholder: string;
}) {
  const [focused, setFocused] = useState(false);
  const trimmedQuery = query.trim();
  const showDropdown = focused && trimmedQuery.length >= 2;

  return (
    <label className="block space-y-2">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      <div className="relative">
        <input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => window.setTimeout(() => setFocused(false), 150)}
          className={inputClass()}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
        />
        {showDropdown ? (
          <div className="absolute z-10 mt-2 max-h-64 w-full overflow-auto rounded-2xl border border-slate-200 bg-white p-2 shadow-xl">
            {loading ? (
              <div className="px-3 py-2 text-sm text-slate-500">Searching directory...</div>
            ) : options && options.length > 0 ? (
              options.map((option) => {
                const preferredValue = option.principal_name || option.mail;
                return (
                  <button
                    key={option.id}
                    type="button"
                    className="flex w-full flex-col rounded-xl px-3 py-2 text-left transition hover:bg-slate-50"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => onChange(preferredValue)}
                  >
                    <span className="text-sm font-medium text-slate-900">{option.display_name || preferredValue}</span>
                    <span className="text-xs text-slate-500">
                      {option.principal_name || option.mail || "No directory email"}
                      {option.enabled === false ? " - disabled" : ""}
                    </span>
                  </button>
                );
              })
            ) : (
              <div className="px-3 py-2 text-sm text-slate-500">No cached match found. You can still paste a UPN manually.</div>
            )}
          </div>
        ) : null}
      </div>
    </label>
  );
}

function OneDriveCopyJobDetail({ job }: { job: OneDriveCopyJobStatus }) {
  const percent = job.progress_total > 0 ? Math.round((job.progress_current / job.progress_total) * 100) : 0;

  return (
    <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected job</div>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">{job.destination_folder}</h2>
          <p className="mt-1 text-sm text-slate-500">
            {job.source_upn} to {job.destination_upn}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${statusTone(job.status)}`}>
            {job.status}
          </span>
          <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-sky-700">
            {phaseLabel(job.phase)}
          </span>
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500">
          <span>Dispatch progress</span>
          <span>
            {job.progress_current}/{job.progress_total}
          </span>
        </div>
        <div className="h-3 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-sky-600 transition-all" style={{ width: `${percent}%` }} />
        </div>
        <p className="mt-2 text-sm text-slate-600">{job.progress_message}</p>
      </div>

      <div className="grid gap-3 md:grid-cols-5">
        <CountCard label="Folders Found" value={job.total_folders_found.toLocaleString()} />
        <CountCard label="Files Found" value={job.total_files_found.toLocaleString()} />
        <CountCard label="Folders Created" value={job.folders_created.toLocaleString()} />
        <CountCard label="Dispatched" value={job.files_dispatched.toLocaleString()} tone="text-emerald-700" />
        <CountCard label="Failed" value={job.files_failed.toLocaleString()} tone={job.files_failed > 0 ? "text-red-700" : "text-slate-900"} />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Requested By</div>
          <div className="mt-1 font-medium text-slate-900">{job.requested_by_name || job.requested_by_email}</div>
          <div className="text-xs text-slate-500">{job.requested_by_email}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Timing</div>
          <div className="mt-1">Requested: {formatDateTime(job.requested_at)}</div>
          <div>Started: {formatDateTime(job.started_at)}</div>
          <div>Completed: {formatDateTime(job.completed_at)}</div>
        </div>
      </div>

      <div className="rounded-2xl border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-sky-900">
        Graph copy requests finish server-side. A completed job means MoveDocs successfully dispatched the copy work, but OneDrive can continue materializing files in the background for a few more minutes.
      </div>

      {job.error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{job.error}</div>
      ) : null}

      <div className="space-y-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Event log</div>
        {job.events.length > 0 ? (
          <div className="space-y-2">
            {job.events.map((event) => (
              <div
                key={event.event_id}
                className={[
                  "rounded-2xl border px-4 py-3 text-sm",
                  event.level === "error"
                    ? "border-red-200 bg-red-50 text-red-700"
                    : event.level === "warning"
                      ? "border-amber-200 bg-amber-50 text-amber-800"
                      : "border-slate-200 bg-slate-50 text-slate-700",
                ].join(" ")}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-semibold uppercase tracking-wide">{event.level}</span>
                  <span className="text-xs opacity-80">{formatDateTime(event.created_at)}</span>
                </div>
                <div className="mt-1 break-words">{event.message}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">No job events recorded yet.</div>
        )}
      </div>
    </section>
  );
}

export default function ToolsPage() {
  const branding = getSiteBranding();
  const queryClient = useQueryClient();
  const [sourceUpn, setSourceUpn] = useState("");
  const [destinationUpn, setDestinationUpn] = useState("");
  const [destinationFolder, setDestinationFolder] = useState("");
  const [testMode, setTestMode] = useState(false);
  const [testFileLimit, setTestFileLimit] = useState("25");
  const [excludeSystemFolders, setExcludeSystemFolders] = useState(true);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [formError, setFormError] = useState("");
  const deferredSourceSearch = useDeferredValue(sourceUpn);
  const deferredDestinationSearch = useDeferredValue(destinationUpn);

  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.getMe(),
    staleTime: 60_000,
  });
  const canAccessTools = !!meQuery.data?.can_access_tools;

  const sourceSearchQuery = useQuery({
    queryKey: ["onedrive-copy", "users", deferredSourceSearch],
    queryFn: () => api.searchOneDriveCopyUsers(deferredSourceSearch.trim(), 8),
    enabled: canAccessTools && deferredSourceSearch.trim().length >= 2,
    staleTime: 30_000,
  });

  const destinationSearchQuery = useQuery({
    queryKey: ["onedrive-copy", "users", deferredDestinationSearch],
    queryFn: () => api.searchOneDriveCopyUsers(deferredDestinationSearch.trim(), 8),
    enabled: canAccessTools && deferredDestinationSearch.trim().length >= 2,
    staleTime: 30_000,
  });

  const jobsQuery = useQuery({
    queryKey: ["onedrive-copy", "jobs"],
    queryFn: () => api.listOneDriveCopyJobs(100),
    enabled: canAccessTools,
    refetchInterval: (query) => {
      const jobs = query.state.data as OneDriveCopyJobStatus[] | undefined;
      return jobs?.some((job) => job.status === "queued" || job.status === "running") ? 3_000 : 15_000;
    },
  });

  useEffect(() => {
    if (!activeJobId && jobsQuery.data?.length) {
      setActiveJobId(jobsQuery.data[0].job_id);
    }
  }, [activeJobId, jobsQuery.data]);

  const activeJobQuery = useQuery({
    queryKey: ["onedrive-copy", "jobs", activeJobId],
    queryFn: () => api.getOneDriveCopyJob(activeJobId as string),
    enabled: canAccessTools && !!activeJobId,
    refetchInterval: (query) => {
      const job = query.state.data as OneDriveCopyJobStatus | undefined;
      return job && (job.status === "queued" || job.status === "running") ? 3_000 : false;
    },
  });

  const loginAuditQuery = useQuery({
    queryKey: ["onedrive-copy", "login-audit"],
    queryFn: () => api.listLoginAudit(50),
    enabled: canAccessTools,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const createJobMutation = useMutation({
    mutationFn: () =>
      api.createOneDriveCopyJob({
        source_upn: sourceUpn.trim(),
        destination_upn: destinationUpn.trim(),
        destination_folder: destinationFolder.trim(),
        test_mode: testMode,
        test_file_limit: Math.max(1, Number.parseInt(testFileLimit, 10) || 25),
        exclude_system_folders: excludeSystemFolders,
      }),
    onSuccess: async (job) => {
      setFormError("");
      setActiveJobId(job.job_id);
      await queryClient.invalidateQueries({ queryKey: ["onedrive-copy", "jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["onedrive-copy", "jobs", job.job_id] });
    },
    onError: (error) => {
      setFormError(error instanceof Error ? error.message : "Failed to queue the OneDrive copy job.");
    },
  });

  function submitJob() {
    if (!canAccessTools) {
      setFormError("Tools access is restricted.");
      return;
    }
    if (!sourceUpn.trim() || !destinationUpn.trim() || !destinationFolder.trim()) {
      setFormError("Source UPN, destination UPN, and destination folder are all required.");
      return;
    }
    if (sourceUpn.trim().toLowerCase() === destinationUpn.trim().toLowerCase()) {
      setFormError("Source and destination UPNs must be different.");
      return;
    }
    createJobMutation.mutate();
  }

  return (
    <div className="space-y-6">
      {meQuery.isLoading ? (
        <section className="rounded-3xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500 shadow-sm">
          Loading tools access...
        </section>
      ) : null}
      {!meQuery.isLoading && !canAccessTools ? (
        <section className="rounded-3xl border border-amber-200 bg-amber-50 p-8 text-center shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Restricted</div>
          <h1 className="mt-2 text-2xl font-semibold text-amber-950">Tools access is limited</h1>
          <p className="mt-2 text-sm text-amber-900">
            This page is currently limited to the approved operator accounts for OneDrive copy and login-audit workflows.
          </p>
        </section>
      ) : null}
      {canAccessTools ? (
        <>
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Tools</p>
            <h1 className="mt-1 text-3xl font-bold text-slate-900">{branding.scope === "azure" ? "Azure Tools" : "Helpdesk Tools"}</h1>
            <p className="mt-2 max-w-3xl text-sm text-slate-600">
              Long-running operator tools for Microsoft 365 and Azure tasks. The OneDrive Copy tool mirrors the existing Graph-based handoff script and keeps a shared job history visible to everyone signed in on this host.
            </p>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <div className="space-y-6">
          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">OneDrive Copy</div>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">Copy a full OneDrive to another user</h2>
                <p className="mt-2 text-sm text-slate-600">
                  This uses app-level Microsoft Graph access to enumerate the source tree, recreate folders, and dispatch server-side copy requests with rename-on-conflict behavior.
                </p>
              </div>
              <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-sky-700">Async background job</span>
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-2">
              <DirectoryTypeaheadField
                label="Source user UPN"
                value={sourceUpn}
                onChange={setSourceUpn}
                query={deferredSourceSearch}
                loading={sourceSearchQuery.isLoading}
                options={sourceSearchQuery.data}
                placeholder="dahrens@example.com"
              />
              <DirectoryTypeaheadField
                label="Destination user UPN"
                value={destinationUpn}
                onChange={setDestinationUpn}
                query={deferredDestinationSearch}
                loading={destinationSearchQuery.isLoading}
                options={destinationSearchQuery.data}
                placeholder="sstutsman@example.com"
              />
            </div>

            <div className="mt-4">
              <label className="block space-y-2">
                <span className="text-sm font-medium text-slate-700">Destination folder name</span>
                <input
                  value={destinationFolder}
                  onChange={(event) => setDestinationFolder(event.target.value)}
                  className={inputClass()}
                  placeholder="DaveAhrensFilesFull_V4"
                />
              </label>
            </div>

            <details className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <summary className="cursor-pointer list-none text-sm font-semibold text-slate-800">Advanced options</summary>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <label className="flex items-start gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3">
                  <input
                    type="checkbox"
                    checked={testMode}
                    onChange={(event) => setTestMode(event.target.checked)}
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
                  />
                  <span>
                    <span className="block text-sm font-medium text-slate-800">Test mode</span>
                    <span className="block text-xs text-slate-500">Dispatch only the first few files instead of the full OneDrive.</span>
                  </span>
                </label>
                <label className="block space-y-2">
                  <span className="text-sm font-medium text-slate-700">Test file limit</span>
                  <input
                    value={testFileLimit}
                    onChange={(event) => setTestFileLimit(event.target.value)}
                    inputMode="numeric"
                    className={inputClass()}
                    disabled={!testMode}
                  />
                </label>
                <label className="flex items-start gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 md:col-span-2">
                  <input
                    type="checkbox"
                    checked={excludeSystemFolders}
                    onChange={(event) => setExcludeSystemFolders(event.target.checked)}
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
                  />
                  <span>
                    <span className="block text-sm font-medium text-slate-800">Exclude system-managed root folders</span>
                    <span className="block text-xs text-slate-500">
                      {EXCLUDED_ROOT_FOLDERS.join(" | ")}
                    </span>
                  </span>
                </label>
              </div>
            </details>

            {formError ? (
              <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{formError}</div>
            ) : null}

            <div className="mt-6 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={submitJob}
                disabled={createJobMutation.isPending}
                className={buttonClass("primary", createJobMutation.isPending)}
              >
                {createJobMutation.isPending ? "Queueing..." : "Queue OneDrive Copy"}
              </button>
              <span className="text-sm text-slate-500">
                If the destination folder name already exists, Microsoft Graph will auto-rename the new folder.
              </span>
            </div>
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Shared job history</div>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">Recent OneDrive copy jobs</h2>
              </div>
              <button type="button" onClick={() => jobsQuery.refetch()} className={buttonClass("secondary", jobsQuery.isFetching)}>
                Refresh
              </button>
            </div>

            <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Requested By</th>
                    <th className="px-4 py-3">Source</th>
                    <th className="px-4 py-3">Destination</th>
                    <th className="px-4 py-3">Folder</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Phase</th>
                    <th className="px-4 py-3">Counts</th>
                    <th className="px-4 py-3">Started</th>
                    <th className="px-4 py-3">Completed</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {jobsQuery.data && jobsQuery.data.length > 0 ? (
                    jobsQuery.data.map((job) => (
                      <tr
                        key={job.job_id}
                        className={[
                          "cursor-pointer transition hover:bg-slate-50",
                          activeJobId === job.job_id ? "bg-sky-50/60" : "",
                        ].join(" ")}
                        onClick={() => setActiveJobId(job.job_id)}
                      >
                        <td className="px-4 py-3 text-slate-700">
                          <div className="font-medium text-slate-900">{job.requested_by_name || job.requested_by_email}</div>
                          <div className="text-xs text-slate-500">{job.requested_by_email}</div>
                        </td>
                        <td className="px-4 py-3 text-slate-700">{job.source_upn}</td>
                        <td className="px-4 py-3 text-slate-700">{job.destination_upn}</td>
                        <td className="px-4 py-3 text-slate-700">{job.destination_folder}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${statusTone(job.status)}`}>
                            {job.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-700">{phaseLabel(job.phase)}</td>
                        <td className="px-4 py-3 text-xs text-slate-600">
                          {job.files_dispatched} ok / {job.files_failed} failed
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-600">{formatDateTime(job.started_at)}</td>
                        <td className="px-4 py-3 text-xs text-slate-600">{formatDateTime(job.completed_at)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={9} className="px-4 py-8 text-center text-sm text-slate-500">
                        No OneDrive copy jobs have been submitted yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <div className="space-y-6">
          {activeJobQuery.data ? (
            <OneDriveCopyJobDetail job={activeJobQuery.data} />
          ) : (
            <section className="rounded-3xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
              Select a job from the table to inspect progress, counts, and the event log.
            </section>
          )}
          <LoginAuditPanel events={loginAuditQuery.data ?? []} />
        </div>
      </section>
        </>
      ) : null}
    </div>
  );
}
