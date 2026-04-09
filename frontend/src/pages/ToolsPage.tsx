import { useEffect, useState, useDeferredValue } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type AppLoginAuditEvent,
  type DeactivateUserToolResult,
  type DelegateMailboxJobStatus,
  type EmailgisticsHelperStatus,
  type MailboxDelegatesStatus,
  type MailboxRulesStatus,
  type OneDriveCopyJobStatus,
  type OneDriveCopyUserOption,
} from "../lib/api.ts";
import {
  getPollingQueryOptions,
  resolvePollingIntervalMs,
} from "../lib/queryPolling.ts";
import { getSiteBranding } from "../lib/siteContext.ts";

const EXCLUDED_ROOT_FOLDERS = [
  "Apps",
  "Attachments",
  "Microsoft Teams Chat Files",
  "Microsoft Copilot Chat Files",
  "Recordings",
  "Videos",
];

const UPN_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/i;
const DELEGATE_PERMISSION_TYPES = ["send_on_behalf", "send_as", "full_access"] as const;
type JobStatusTone = "queued" | "running" | "completed" | "failed" | "cancelled";

type PickerOptionSource = OneDriveCopyUserOption["source"] | "manual";

interface ToolUserPickerOption extends Omit<OneDriveCopyUserOption, "source"> {
  canonical_upn: string;
  source: PickerOptionSource;
  synthetic?: boolean;
}

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

function statusTone(status: JobStatusTone): string {
  switch (status) {
    case "completed":
      return "bg-emerald-100 text-emerald-700";
    case "failed":
      return "bg-red-100 text-red-700";
    case "cancelled":
      return "bg-amber-100 text-amber-800";
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

function isFinishedJob(status: OneDriveCopyJobStatus["status"] | DelegateMailboxJobStatus["status"]): boolean {
  return status !== "queued" && status !== "running";
}

function delegateScanPhaseLabel(phase: DelegateMailboxJobStatus["phase"]): string {
  switch (phase) {
    case "resolving_user":
      return "Resolving user";
    case "scanning_send_on_behalf":
      return "Scanning send on behalf";
    case "scanning_exchange_permissions":
      return "Scanning Exchange permissions";
    case "merging_results":
      return "Finalizing results";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return "Queued";
  }
}

function helperStepTone(status: EmailgisticsHelperStatus["steps"][number]["status"]): string {
  switch (status) {
    case "completed":
      return "bg-emerald-100 text-emerald-700";
    case "already_present":
      return "bg-sky-100 text-sky-700";
    case "failed":
      return "bg-red-100 text-red-700";
    default:
      return "bg-slate-100 text-slate-700";
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

function normalizeUpn(value: string): string {
  return value.trim().toLowerCase();
}

function looksLikeUpn(value: string): boolean {
  return UPN_PATTERN.test(value.trim());
}

function optionCanonicalUpn(option: Pick<OneDriveCopyUserOption, "principal_name" | "mail">): string {
  return option.principal_name.trim() || option.mail.trim();
}

function buildPickerOptions(query: string, options: OneDriveCopyUserOption[] | undefined): ToolUserPickerOption[] {
  const trimmedQuery = query.trim();
  const normalizedQuery = normalizeUpn(trimmedQuery);
  const result: ToolUserPickerOption[] = [];
  const seen = new Set<string>();

  for (const option of options ?? []) {
    const canonicalUpn = optionCanonicalUpn(option);
    const normalizedUpn = normalizeUpn(canonicalUpn);
    if (!normalizedUpn || seen.has(normalizedUpn)) continue;
    seen.add(normalizedUpn);
    result.push({
      ...option,
      canonical_upn: canonicalUpn,
    });
  }

  if (trimmedQuery && looksLikeUpn(trimmedQuery) && !seen.has(normalizedQuery)) {
    result.push({
      id: `manual:${normalizedQuery}`,
      display_name: `Use and save "${trimmedQuery}"`,
      principal_name: trimmedQuery,
      mail: "",
      enabled: true,
      source: "manual",
      canonical_upn: trimmedQuery,
      synthetic: true,
    });
  }

  return result;
}

function optionSubtitle(option: ToolUserPickerOption): string {
  if (option.synthetic) {
    return "Not found in Entra cache. Save this UPN locally for reuse.";
  }
  const canonicalUpn = option.canonical_upn || option.mail || "No directory email";
  const segments = [canonicalUpn];
  if (option.source === "saved") {
    segments.push("Saved UPN");
  } else {
    segments.push("Entra cache");
  }
  if (option.source === "entra" && option.enabled === false) {
    segments.push("Disabled");
  }
  return segments.join(" • ");
}

function sourceBadgeClass(source: PickerOptionSource): string {
  if (source === "saved") {
    return "bg-amber-100 text-amber-800";
  }
  if (source === "manual") {
    return "bg-violet-100 text-violet-800";
  }
  return "bg-sky-100 text-sky-800";
}

function delegatePermissionLabel(permissionType: string): string {
  switch (permissionType) {
    case "send_on_behalf":
      return "Send on behalf";
    case "send_as":
      return "Send As";
    case "full_access":
      return "Full Access";
    default:
      return permissionType.replace(/_/g, " ");
  }
}

function delegatePermissionBadgeClass(permissionType: string): string {
  switch (permissionType) {
    case "send_on_behalf":
      return "border-sky-200 bg-sky-50 text-sky-900";
    case "send_as":
      return "border-violet-200 bg-violet-50 text-violet-900";
    case "full_access":
      return "border-emerald-200 bg-emerald-50 text-emerald-900";
    default:
      return "border-slate-200 bg-slate-50 text-slate-700";
  }
}

function orderedPermissionTypes(permissionTypes: string[]): string[] {
  const ordered: string[] = DELEGATE_PERMISSION_TYPES.filter((permissionType) => permissionTypes.includes(permissionType));
  for (const permissionType of permissionTypes) {
    if (!ordered.includes(permissionType)) {
      ordered.push(permissionType);
    }
  }
  return ordered;
}

function PermissionBadges({ permissionTypes }: { permissionTypes: string[] }) {
  const ordered = orderedPermissionTypes(permissionTypes);
  if (ordered.length === 0) {
    return null;
  }
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {ordered.map((permissionType) => (
        <span
          key={permissionType}
          className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${delegatePermissionBadgeClass(permissionType)}`}
        >
          {delegatePermissionLabel(permissionType)}
        </span>
      ))}
    </div>
  );
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

function RuleSummaryStrip({
  label,
  items,
  toneClass,
}: {
  label: string;
  items: string[];
  toneClass: string;
}) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="flex flex-wrap gap-2">
        {items.map((item, index) => (
          <span key={`${label}-${index}-${item}`} className={`rounded-full border px-3 py-1 text-xs ${toneClass}`}>
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function MailboxRulesResults({
  data,
  isLoading,
  errorMessage,
  onRefresh,
  isRefreshing,
}: {
  data: MailboxRulesStatus | undefined;
  isLoading: boolean;
  errorMessage: string;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  if (isLoading) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Loading mailbox rules...
      </div>
    );
  }

  if (errorMessage) {
    return <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{errorMessage}</div>;
  }

  if (!data) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Select a mailbox and load its Inbox rules to inspect enabled rules, actions, and exceptions.
      </div>
    );
  }

  const enabledCount = data.rules.filter((rule) => rule.is_enabled).length;
  const disabledCount = data.rules.filter((rule) => !rule.is_enabled).length;
  const errorCount = data.rules.filter((rule) => rule.has_error).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mailbox rules</div>
          <h2 className="mt-1 text-2xl font-semibold text-slate-900">{data.display_name || data.primary_address || data.mailbox}</h2>
          <p className="mt-1 text-sm text-slate-500">{data.primary_address || data.principal_name || data.mailbox}</p>
        </div>
        <button type="button" onClick={onRefresh} className={buttonClass("secondary", isRefreshing)}>
          Refresh
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <CountCard label="Total Rules" value={data.rule_count.toLocaleString()} />
        <CountCard label="Enabled" value={enabledCount.toLocaleString()} tone="text-emerald-700" />
        <CountCard label="Disabled" value={disabledCount.toLocaleString()} tone={disabledCount > 0 ? "text-slate-700" : "text-slate-900"} />
        <CountCard label="Errors" value={errorCount.toLocaleString()} tone={errorCount > 0 ? "text-red-700" : "text-slate-900"} />
      </div>

      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">{data.note}</div>

      {data.rules.length > 0 ? (
        <div className="space-y-3">
          {data.rules.map((rule) => (
            <div key={rule.id} className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-slate-900">{rule.display_name || "Unnamed rule"}</div>
                  <div className="mt-1 text-xs text-slate-500">
                    Sequence {rule.sequence ?? "-"} • {rule.id}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 text-xs font-semibold uppercase tracking-wide">
                  <span className={`rounded-full px-2.5 py-1 ${rule.is_enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-700"}`}>
                    {rule.is_enabled ? "Enabled" : "Disabled"}
                  </span>
                  {rule.has_error ? <span className="rounded-full bg-red-100 px-2.5 py-1 text-red-700">Error</span> : null}
                  {rule.stop_processing_rules ? <span className="rounded-full bg-amber-100 px-2.5 py-1 text-amber-700">Stop processing</span> : null}
                </div>
              </div>

              <div className="mt-4 space-y-4">
                <RuleSummaryStrip
                  label="Conditions"
                  items={rule.conditions_summary}
                  toneClass="border-sky-200 bg-sky-50 text-sky-900"
                />
                <RuleSummaryStrip
                  label="Actions"
                  items={rule.actions_summary}
                  toneClass="border-emerald-200 bg-emerald-50 text-emerald-900"
                />
                <RuleSummaryStrip
                  label="Exceptions"
                  items={rule.exceptions_summary}
                  toneClass="border-amber-200 bg-amber-50 text-amber-900"
                />
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function MailboxDelegatesResults({
  data,
  isLoading,
  errorMessage,
  onRefresh,
  isRefreshing,
}: {
  data: MailboxDelegatesStatus | undefined;
  isLoading: boolean;
  errorMessage: string;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  if (isLoading) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Loading mailbox delegates...
      </div>
    );
  }

  if (errorMessage) {
    return <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{errorMessage}</div>;
  }

  if (!data) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Select a mailbox and load its Exchange delegate access.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mailbox delegates</div>
          <h2 className="mt-1 text-2xl font-semibold text-slate-900">{data.display_name || data.primary_address || data.mailbox}</h2>
          <p className="mt-1 text-sm text-slate-500">{data.primary_address || data.principal_name || data.mailbox}</p>
        </div>
        <button type="button" onClick={onRefresh} className={buttonClass("secondary", isRefreshing)}>
          Refresh
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <CountCard label="Delegates" value={data.delegate_count.toLocaleString()} />
        <CountCard label="Send On Behalf" value={String(data.permission_counts.send_on_behalf ?? 0)} tone="text-sky-700" />
        <CountCard label="Send As" value={String(data.permission_counts.send_as ?? 0)} tone="text-violet-700" />
        <CountCard label="Full Access" value={String(data.permission_counts.full_access ?? 0)} tone="text-emerald-700" />
      </div>

      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">{data.note}</div>

      {data.delegates.length > 0 ? (
        <div className="space-y-3">
          {data.delegates.map((delegate) => (
            <div
              key={delegate.identity || delegate.mail || delegate.principal_name}
              className="rounded-2xl border border-slate-200 bg-white px-4 py-4"
            >
              <div className="text-base font-semibold text-slate-900">
                {delegate.display_name || delegate.mail || delegate.principal_name || delegate.identity}
              </div>
              <div className="mt-1 text-sm text-slate-500">{delegate.mail || delegate.principal_name || delegate.identity}</div>
              <PermissionBadges permissionTypes={delegate.permission_types} />
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function DelegateMailboxesResults({
  job,
  isLoading,
  errorMessage,
  onRefresh,
  isRefreshing,
  onCancel,
  isCancelling,
}: {
  job: DelegateMailboxJobStatus | undefined;
  isLoading: boolean;
  errorMessage: string;
  onRefresh: () => void;
  isRefreshing: boolean;
  onCancel: () => void;
  isCancelling: boolean;
}) {
  if (isLoading) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Scanning mailbox delegation...
      </div>
    );
  }

  if (errorMessage) {
    return <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{errorMessage}</div>;
  }

  if (!job) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Enter a user email to find mailboxes where they have Exchange delegate access.
      </div>
    );
  }

  const percent = job.progress_total > 0 ? Math.round((job.progress_current / job.progress_total) * 100) : 0;
  const isRunning = job.status === "queued" || job.status === "running";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Delegate mailbox matches</div>
          <h2 className="mt-1 text-2xl font-semibold text-slate-900">{job.display_name || job.primary_address || job.user}</h2>
          <p className="mt-1 text-sm text-slate-500">{job.primary_address || job.principal_name || job.user}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${statusTone(job.status)}`}>
            {job.status}
          </span>
          <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-sky-700">
            {delegateScanPhaseLabel(job.phase)}
          </span>
          {isRunning ? (
            <button type="button" onClick={onCancel} className={buttonClass("secondary", isCancelling)}>
              {isCancelling ? "Stopping..." : "Stop"}
            </button>
          ) : null}
          <button type="button" onClick={onRefresh} className={buttonClass("secondary", isRefreshing)}>
            Refresh
          </button>
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500">
          <span>Scan progress</span>
          <span>
            {job.progress_current}/{job.progress_total}
          </span>
        </div>
        <div className="h-3 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-sky-600 transition-all" style={{ width: `${percent}%` }} />
        </div>
        <p className="mt-2 text-sm text-slate-600">{job.progress_message || "Queued"}</p>
      </div>

      <div className="grid gap-3 md:grid-cols-5">
        <CountCard label="Matching Mailboxes" value={job.mailbox_count.toLocaleString()} />
        <CountCard label="Scanned Mailboxes" value={job.scanned_mailbox_count.toLocaleString()} />
        <CountCard label="Send On Behalf" value={String(job.permission_counts.send_on_behalf ?? 0)} tone="text-sky-700" />
        <CountCard label="Send As" value={String(job.permission_counts.send_as ?? 0)} tone="text-violet-700" />
        <CountCard label="Full Access" value={String(job.permission_counts.full_access ?? 0)} tone="text-emerald-700" />
      </div>

      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
        {job.note || "Most delegate scans finish in 20-90 seconds. Large tenants can take 5-10 minutes before the job times out."}
      </div>

      <div className="rounded-2xl border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-sky-900">
        Most delegate scans finish in 20-90 seconds. Large tenants can take 5-10 minutes because the app has to sweep Exchange mailbox metadata plus delegate permissions.
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

      {job.error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{job.error}</div>
      ) : null}

      {isRunning ? (
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
          This scan keeps running on the server even if you leave the page. Come back later and the latest running job or your most recent finished job will still be here.
        </div>
      ) : job.status === "cancelled" ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-6 text-sm text-amber-800">
          This scan was cancelled. You can queue another delegate mailbox search whenever you are ready.
        </div>
      ) : null}

      {job.mailboxes.length > 0 ? (
        <div className="space-y-3">
          {job.mailboxes.map((mailbox) => (
            <div
              key={mailbox.identity || mailbox.primary_address || mailbox.principal_name}
              className="rounded-2xl border border-slate-200 bg-white px-4 py-4"
            >
              <div className="text-base font-semibold text-slate-900">
                {mailbox.display_name || mailbox.primary_address || mailbox.principal_name || mailbox.identity}
              </div>
              <div className="mt-1 text-sm text-slate-500">{mailbox.primary_address || mailbox.principal_name || mailbox.identity}</div>
              <PermissionBadges permissionTypes={mailbox.permission_types} />
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function DirectoryComboboxField({
  label,
  value,
  onInputChange,
  onSelect,
  selected,
  loading,
  options,
  placeholder,
  emptyMessage,
}: {
  label: string;
  value: string;
  onInputChange: (value: string) => void;
  onSelect: (value: ToolUserPickerOption) => void;
  selected: ToolUserPickerOption | null;
  loading: boolean;
  options: ToolUserPickerOption[];
  placeholder: string;
  emptyMessage: string;
}) {
  const [focused, setFocused] = useState(false);
  const showDropdown = focused && (loading || options.length > 0 || value.trim().length > 0);
  const showLoading = loading && value.trim().length > 0;

  return (
    <label className="block space-y-2">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      <div className="relative">
        <input
          value={value}
          onChange={(event) => onInputChange(event.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => window.setTimeout(() => setFocused(false), 150)}
          className={inputClass()}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          aria-expanded={showDropdown}
          aria-autocomplete="list"
        />
        {showDropdown ? (
          <div className="absolute z-10 mt-2 max-h-64 w-full overflow-auto rounded-2xl border border-slate-200 bg-white p-2 shadow-xl">
            {showLoading ? (
              <div className="px-3 py-2 text-sm text-slate-500">Searching directory...</div>
            ) : options.length > 0 ? (
              options.map((option) => {
                return (
                  <button
                    key={option.id}
                    type="button"
                    className="flex w-full flex-col rounded-xl px-3 py-2 text-left transition hover:bg-slate-50"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => onSelect(option)}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-900">
                        {option.display_name || option.canonical_upn}
                      </span>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${sourceBadgeClass(option.source)}`}>
                        {option.source === "manual" ? "Use + save" : option.source}
                      </span>
                    </div>
                    <span className="text-xs text-slate-500">{optionSubtitle(option)}</span>
                  </button>
                );
              })
            ) : (
              <div className="px-3 py-2 text-sm text-slate-500">{emptyMessage}</div>
            )}
          </div>
        ) : null}
      </div>
      {selected ? (
        <div className="text-xs text-slate-500">
          Selected: {selected.canonical_upn}
          {selected.source === "saved" ? " • saved locally" : selected.source === "manual" ? " • will be saved locally" : " • from Entra"}
        </div>
      ) : null}
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

function DelegateMailboxJobHistory({
  jobs,
  activeJobId,
  onSelect,
  onRefresh,
  isRefreshing,
  onClearFinished,
  isClearing,
}: {
  jobs: DelegateMailboxJobStatus[];
  activeJobId: string | null;
  onSelect: (jobId: string) => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  onClearFinished: () => void;
  isClearing: boolean;
}) {
  const canClearFinished = jobs.some((job) => isFinishedJob(job.status));
  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Your job history</div>
          <h2 className="mt-1 text-2xl font-semibold text-slate-900">Recent delegate scan jobs</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={onClearFinished} disabled={!canClearFinished || isClearing} className={buttonClass("secondary", !canClearFinished || isClearing)}>
            {isClearing ? "Clearing..." : "Clear finished"}
          </button>
          <button type="button" onClick={onRefresh} className={buttonClass("secondary", isRefreshing)}>
            Refresh
          </button>
        </div>
      </div>

      <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Matches</th>
              <th className="px-4 py-3">Scanned</th>
              <th className="px-4 py-3">Requested</th>
              <th className="px-4 py-3">Completed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {jobs.length > 0 ? (
              jobs.map((job) => (
                <tr
                  key={job.job_id}
                  className={[
                    "cursor-pointer transition hover:bg-slate-50",
                    activeJobId === job.job_id ? "bg-sky-50/60" : "",
                  ].join(" ")}
                  onClick={() => onSelect(job.job_id)}
                >
                  <td className="px-4 py-3 text-slate-700">
                    <div className="font-medium text-slate-900">{job.display_name || job.primary_address || job.user}</div>
                    <div className="text-xs text-slate-500">{job.primary_address || job.principal_name || job.user}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${statusTone(job.status)}`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-700">{job.mailbox_count}</td>
                  <td className="px-4 py-3 text-slate-700">{job.scanned_mailbox_count}</td>
                  <td className="px-4 py-3 text-xs text-slate-600">{formatDateTime(job.requested_at)}</td>
                  <td className="px-4 py-3 text-xs text-slate-600">{formatDateTime(job.completed_at)}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-sm text-slate-500">
                  No delegate scan jobs have been submitted yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function EmailgisticsHelperResults({
  result,
  isRunning,
  runningLabel,
  errorMessage,
}: {
  result: EmailgisticsHelperStatus | undefined;
  isRunning: boolean;
  runningLabel: string;
  errorMessage: string;
}) {
  if (isRunning) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        {runningLabel || "Running Emailgistics action..."}
      </div>
    );
  }

  if (errorMessage) {
    return <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{errorMessage}</div>;
  }

  if (!result) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Use Emailgistics Helper to grant access and add a user to the Emailgistics group for a shared mailbox.
      </div>
    );
  }

  const sharedMailboxTitle =
    result.resolved_shared_display_name ||
    result.resolved_shared_principal_name ||
    result.shared_mailbox ||
    "All configured mailboxes";
  const sharedMailboxSubtitle = result.resolved_shared_principal_name || result.shared_mailbox || "";
  const resultTitle = result.resolved_user_display_name || result.resolved_user_principal_name || result.user_mailbox;
  const resultSubtitle = `${result.resolved_user_principal_name || result.user_mailbox} -> ${result.resolved_shared_principal_name || result.shared_mailbox}`;
  const resultLabel = "Emailgistics Helper";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{resultLabel}</div>
          <h2 className="mt-1 text-2xl font-semibold text-slate-900">{resultTitle}</h2>
          <p className="mt-1 text-sm text-slate-500">{resultSubtitle}</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${statusTone(result.status === "completed" ? "completed" : "failed")}`}>
          {result.status}
        </span>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        {result.steps.map((step) => (
          <div key={step.key} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{step.label}</div>
              <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${helperStepTone(step.status)}`}>
                {step.status === "already_present" ? "already set" : step.status}
              </span>
            </div>
            <div className="mt-2 text-sm text-slate-700">{step.message || "Pending"}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Resolved user</div>
          <div className="mt-1 font-medium text-slate-900">{result.resolved_user_display_name || result.resolved_user_principal_name || result.user_mailbox}</div>
          <div className="text-xs text-slate-500">{result.resolved_user_principal_name || result.user_mailbox}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Shared mailbox</div>
          <div className="mt-1 font-medium text-slate-900">{sharedMailboxTitle}</div>
          <div className="text-xs text-slate-500">{sharedMailboxSubtitle}</div>
        </div>
      </div>

      <div className={`rounded-2xl border px-4 py-3 text-sm ${result.status === "completed" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
        {result.note || "Emailgistics Helper finished."}
      </div>

      {result.error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{result.error}</div>
      ) : null}
    </div>
  );
}

export default function ToolsPage() {
  const branding = getSiteBranding();
  const queryClient = useQueryClient();
  const [sourceUpnInput, setSourceUpnInput] = useState("");
  const [destinationUpnInput, setDestinationUpnInput] = useState("");
  const [delegateMailboxInput, setDelegateMailboxInput] = useState("");
  const [mailboxInput, setMailboxInput] = useState("");
  const [delegateUserInput, setDelegateUserInput] = useState("");
  const [emailgisticsUserInput, setEmailgisticsUserInput] = useState("");
  const [emailgisticsSharedMailboxInput, setEmailgisticsSharedMailboxInput] = useState("");
  const [selectedSource, setSelectedSource] = useState<ToolUserPickerOption | null>(null);
  const [selectedDestination, setSelectedDestination] = useState<ToolUserPickerOption | null>(null);
  const [selectedDelegateMailbox, setSelectedDelegateMailbox] = useState<ToolUserPickerOption | null>(null);
  const [selectedMailbox, setSelectedMailbox] = useState<ToolUserPickerOption | null>(null);
  const [selectedDelegateUser, setSelectedDelegateUser] = useState<ToolUserPickerOption | null>(null);
  const [selectedEmailgisticsUser, setSelectedEmailgisticsUser] = useState<ToolUserPickerOption | null>(null);
  const [selectedEmailgisticsSharedMailbox, setSelectedEmailgisticsSharedMailbox] = useState<ToolUserPickerOption | null>(null);
  const [destinationFolder, setDestinationFolder] = useState("");
  const [testMode, setTestMode] = useState(false);
  const [testFileLimit, setTestFileLimit] = useState("25");
  const [excludeSystemFolders, setExcludeSystemFolders] = useState(true);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeDelegateMailboxLookup, setActiveDelegateMailboxLookup] = useState<string | null>(null);
  const [activeMailboxLookup, setActiveMailboxLookup] = useState<string | null>(null);
  const [activeDelegateMailboxJobId, setActiveDelegateMailboxJobId] = useState<string | null>(null);
  const [formError, setFormError] = useState("");
  const [delegateMailboxFormError, setDelegateMailboxFormError] = useState("");
  const [mailboxFormError, setMailboxFormError] = useState("");
  const [delegateUserFormError, setDelegateUserFormError] = useState("");
  const [emailgisticsHelperFormError, setEmailgisticsHelperFormError] = useState("");
  const [emailgisticsHelperResult, setEmailgisticsHelperResult] = useState<EmailgisticsHelperStatus | undefined>(undefined);
  const [deactivateUserInput, setDeactivateUserInput] = useState("");
  const [selectedDeactivateUser, setSelectedDeactivateUser] = useState<ToolUserPickerOption | null>(null);
  const [deactivateResult, setDeactivateResult] = useState<DeactivateUserToolResult | null>(null);
  const [deactivateFormError, setDeactivateFormError] = useState("");
  const deferredDeactivateSearch = useDeferredValue(deactivateUserInput);
  const deferredSourceSearch = useDeferredValue(sourceUpnInput);
  const deferredDestinationSearch = useDeferredValue(destinationUpnInput);
  const deferredDelegateMailboxSearch = useDeferredValue(delegateMailboxInput);
  const deferredMailboxSearch = useDeferredValue(mailboxInput);
  const deferredDelegateUserSearch = useDeferredValue(delegateUserInput);
  const deferredEmailgisticsUserSearch = useDeferredValue(emailgisticsUserInput);
  const deferredEmailgisticsSharedMailboxSearch = useDeferredValue(emailgisticsSharedMailboxInput);

  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.getMe(),
    staleTime: 60_000,
  });
  const hasSignedInUser = !!meQuery.data;

  const sourceSearchQuery = useQuery({
    queryKey: ["onedrive-copy", "users", deferredSourceSearch],
    queryFn: () => api.searchOneDriveCopyUsers(deferredSourceSearch.trim(), 8),
    enabled: hasSignedInUser,
    staleTime: 30_000,
  });

  const destinationSearchQuery = useQuery({
    queryKey: ["onedrive-copy", "users", deferredDestinationSearch],
    queryFn: () => api.searchOneDriveCopyUsers(deferredDestinationSearch.trim(), 8),
    enabled: hasSignedInUser,
    staleTime: 30_000,
  });

  const mailboxSearchQuery = useQuery({
    queryKey: ["mailbox-rules", "users", deferredMailboxSearch],
    queryFn: () => api.searchOneDriveCopyUsers(deferredMailboxSearch.trim(), 8),
    enabled: hasSignedInUser,
    staleTime: 30_000,
  });

  const delegateMailboxSearchQuery = useQuery({
    queryKey: ["mailbox-delegates", "users", deferredDelegateMailboxSearch],
    queryFn: () => api.searchOneDriveCopyUsers(deferredDelegateMailboxSearch.trim(), 8),
    enabled: hasSignedInUser,
    staleTime: 30_000,
  });

  const delegateUserSearchQuery = useQuery({
    queryKey: ["delegate-mailboxes", "users", deferredDelegateUserSearch],
    queryFn: () => api.searchOneDriveCopyUsers(deferredDelegateUserSearch.trim(), 8),
    enabled: hasSignedInUser,
    staleTime: 30_000,
  });
  const emailgisticsUserSearchQuery = useQuery({
    queryKey: ["emailgistics-helper", "user", deferredEmailgisticsUserSearch],
    queryFn: () => api.searchOneDriveCopyUsers(deferredEmailgisticsUserSearch.trim(), 8),
    enabled: hasSignedInUser && !!meQuery.data?.is_admin,
    staleTime: 30_000,
  });
  const deactivateUserSearchQuery = useQuery({
    queryKey: ["deactivate-user", "users", deferredDeactivateSearch],
    queryFn: () => api.searchOneDriveCopyUsers(deferredDeactivateSearch.trim(), 8),
    enabled: hasSignedInUser && !!meQuery.data?.is_admin,
    staleTime: 30_000,
  });
  const emailgisticsSharedMailboxSearchQuery = useQuery({
    queryKey: ["emailgistics-helper", "shared-mailbox", deferredEmailgisticsSharedMailboxSearch],
    queryFn: () => api.searchOneDriveCopyUsers(deferredEmailgisticsSharedMailboxSearch.trim(), 8),
    enabled: hasSignedInUser && !!meQuery.data?.is_admin,
    staleTime: 30_000,
  });

  const sourceOptions = buildPickerOptions(sourceUpnInput, sourceSearchQuery.data);
  const destinationOptions = buildPickerOptions(destinationUpnInput, destinationSearchQuery.data);
  const delegateMailboxOptions = buildPickerOptions(delegateMailboxInput, delegateMailboxSearchQuery.data);
  const mailboxOptions = buildPickerOptions(mailboxInput, mailboxSearchQuery.data);
  const delegateUserOptions = buildPickerOptions(delegateUserInput, delegateUserSearchQuery.data);
  const emailgisticsUserOptions = buildPickerOptions(emailgisticsUserInput, emailgisticsUserSearchQuery.data);
  const emailgisticsSharedMailboxOptions = buildPickerOptions(emailgisticsSharedMailboxInput, emailgisticsSharedMailboxSearchQuery.data);
  const deactivateUserOptions = buildPickerOptions(deactivateUserInput, deactivateUserSearchQuery.data);

  const jobsQuery = useQuery({
    queryKey: ["onedrive-copy", "jobs"],
    queryFn: () => api.listOneDriveCopyJobs(100),
    enabled: hasSignedInUser,
    refetchInterval: (query) => {
      const jobs = query.state.data as OneDriveCopyJobStatus[] | undefined;
      return resolvePollingIntervalMs(
        jobs?.some((job) => job.status === "queued" || job.status === "running")
          ? 3_000
          : 60_000,
      );
    },
  });

  useEffect(() => {
    const jobs = jobsQuery.data ?? [];
    if (jobs.length === 0) {
      if (activeJobId !== null) {
        setActiveJobId(null);
      }
      return;
    }
    if (activeJobId && jobs.some((job) => job.job_id === activeJobId)) {
      return;
    }
    setActiveJobId(jobs[0].job_id);
  }, [activeJobId, jobsQuery.data]);

  const activeJobQuery = useQuery({
    queryKey: ["onedrive-copy", "jobs", activeJobId],
    queryFn: () => api.getOneDriveCopyJob(activeJobId as string),
    enabled: hasSignedInUser && !!activeJobId,
    refetchInterval: (query) => {
      const job = query.state.data as OneDriveCopyJobStatus | undefined;
      return resolvePollingIntervalMs(
        3_000,
        Boolean(job && (job.status === "queued" || job.status === "running")),
      );
    },
  });

  const loginAuditQuery = useQuery({
    queryKey: ["onedrive-copy", "login-audit"],
    queryFn: () => api.listLoginAudit(50),
    enabled: hasSignedInUser,
    ...getPollingQueryOptions("slow_5m"),
  });

  const mailboxRulesQuery = useQuery({
    queryKey: ["mailbox-rules", activeMailboxLookup],
    queryFn: () => api.listMailboxRules(activeMailboxLookup as string),
    enabled: hasSignedInUser && !!activeMailboxLookup,
    retry: false,
    staleTime: 15_000,
  });

  const mailboxDelegatesQuery = useQuery({
    queryKey: ["mailbox-delegates", activeDelegateMailboxLookup],
    queryFn: () => api.listMailboxDelegates(activeDelegateMailboxLookup as string),
    enabled: hasSignedInUser && !!activeDelegateMailboxLookup,
    retry: false,
    staleTime: 15_000,
  });

  const delegateMailboxJobsQuery = useQuery({
    queryKey: ["delegate-mailboxes", "jobs"],
    queryFn: () => api.listDelegateMailboxJobs(20),
    enabled: hasSignedInUser,
    refetchInterval: (query) => {
      const jobs = query.state.data as DelegateMailboxJobStatus[] | undefined;
      return resolvePollingIntervalMs(
        jobs?.some((job) => job.status === "queued" || job.status === "running")
          ? 3_000
          : 60_000,
      );
    },
  });

  useEffect(() => {
    if (!delegateMailboxJobsQuery.data?.length) {
      if (activeDelegateMailboxJobId !== null) {
        setActiveDelegateMailboxJobId(null);
      }
      return;
    }
    if (activeDelegateMailboxJobId && delegateMailboxJobsQuery.data.some((job) => job.job_id === activeDelegateMailboxJobId)) {
      return;
    }
    const runningJob = delegateMailboxJobsQuery.data.find((job) => job.status === "queued" || job.status === "running");
    setActiveDelegateMailboxJobId((runningJob ?? delegateMailboxJobsQuery.data[0]).job_id);
  }, [activeDelegateMailboxJobId, delegateMailboxJobsQuery.data]);

  const activeDelegateMailboxJobQuery = useQuery({
    queryKey: ["delegate-mailboxes", "jobs", activeDelegateMailboxJobId],
    queryFn: () => api.getDelegateMailboxJob(activeDelegateMailboxJobId as string),
    enabled: hasSignedInUser && !!activeDelegateMailboxJobId,
    refetchInterval: (query) => {
      const job = query.state.data as DelegateMailboxJobStatus | undefined;
      return resolvePollingIntervalMs(
        3_000,
        Boolean(job && (job.status === "queued" || job.status === "running")),
      );
    },
  });

  const createJobMutation = useMutation({
    mutationFn: () =>
      api.createOneDriveCopyJob({
        source_upn: selectedSource?.canonical_upn.trim() || "",
        destination_upn: selectedDestination?.canonical_upn.trim() || "",
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

  const createDelegateMailboxJobMutation = useMutation({
    mutationFn: () =>
      api.createDelegateMailboxJob({
        user: selectedDelegateUser?.canonical_upn.trim() || delegateUserInput.trim(),
      }),
    onSuccess: async (job) => {
      setDelegateUserFormError("");
      setActiveDelegateMailboxJobId(job.job_id);
      await queryClient.invalidateQueries({ queryKey: ["delegate-mailboxes", "jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["delegate-mailboxes", "jobs", job.job_id] });
    },
    onError: (error) => {
      setDelegateUserFormError(error instanceof Error ? error.message : "Failed to queue the delegate mailbox scan.");
    },
  });
  const clearFinishedOneDriveJobsMutation = useMutation({
    mutationFn: () => api.clearFinishedOneDriveCopyJobs(),
    onSuccess: async () => {
      const jobs = jobsQuery.data ?? [];
      if (activeJobId && jobs.some((job) => job.job_id === activeJobId && isFinishedJob(job.status))) {
        const nextRunningJob = jobs.find((job) => !isFinishedJob(job.status));
        setActiveJobId(nextRunningJob?.job_id ?? null);
      }
      await queryClient.invalidateQueries({ queryKey: ["onedrive-copy", "jobs"] });
    },
    onError: (error) => {
      setFormError(error instanceof Error ? error.message : "Failed to clear finished OneDrive copy jobs.");
    },
  });
  const clearFinishedDelegateMailboxJobsMutation = useMutation({
    mutationFn: () => api.clearFinishedDelegateMailboxJobs(),
    onSuccess: async () => {
      const jobs = delegateMailboxJobsQuery.data ?? [];
      if (activeDelegateMailboxJobId && jobs.some((job) => job.job_id === activeDelegateMailboxJobId && isFinishedJob(job.status))) {
        const nextRunningJob = jobs.find((job) => !isFinishedJob(job.status));
        setActiveDelegateMailboxJobId(nextRunningJob?.job_id ?? null);
      }
      await queryClient.invalidateQueries({ queryKey: ["delegate-mailboxes", "jobs"] });
    },
    onError: (error) => {
      setDelegateUserFormError(error instanceof Error ? error.message : "Failed to clear finished delegate scan jobs.");
    },
  });
  const cancelDelegateMailboxJobMutation = useMutation({
    mutationFn: (jobId: string) => api.cancelDelegateMailboxJob(jobId),
    onSuccess: async (_, jobId) => {
      setDelegateUserFormError("");
      await queryClient.invalidateQueries({ queryKey: ["delegate-mailboxes", "jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["delegate-mailboxes", "jobs", jobId] });
    },
    onError: (error) => {
      setDelegateUserFormError(error instanceof Error ? error.message : "Failed to cancel the delegate mailbox scan.");
    },
  });
  const runEmailgisticsHelperMutation = useMutation({
    mutationFn: () =>
      api.runEmailgisticsHelper({
        user_mailbox: selectedEmailgisticsUser?.canonical_upn.trim() || emailgisticsUserInput.trim(),
        shared_mailbox:
          selectedEmailgisticsSharedMailbox?.canonical_upn.trim() || emailgisticsSharedMailboxInput.trim(),
      }),
    onMutate: () => {
      setEmailgisticsHelperFormError("");
      setEmailgisticsHelperResult(undefined);
    },
    onSuccess: (result) => {
      setEmailgisticsHelperFormError("");
      setEmailgisticsHelperResult(result);
    },
    onError: (error) => {
      setEmailgisticsHelperFormError(
        error instanceof Error ? error.message : "Emailgistics Helper failed before it could finish.",
      );
      setEmailgisticsHelperResult(undefined);
    },
  });
  const deactivateUserMutation = useMutation({
    mutationFn: () =>
      api.deactivateUser({
        entra_user_id: selectedDeactivateUser?.id.trim() || "",
        ad_sam: selectedDeactivateUser?.on_prem_sam?.trim() || "",
        display_name: selectedDeactivateUser?.display_name || deactivateUserInput.trim(),
      }),
    onMutate: () => {
      setDeactivateFormError("");
      setDeactivateResult(null);
    },
    onSuccess: (result) => {
      setDeactivateFormError("");
      setDeactivateResult(result);
    },
    onError: (error) => {
      setDeactivateFormError(error instanceof Error ? error.message : "Deactivation failed.");
      setDeactivateResult(null);
    },
  });
  const canQueueJob =
    !!selectedSource &&
    !!selectedDestination &&
    destinationFolder.trim().length > 0 &&
    !createJobMutation.isPending;

  function submitJob() {
    if (!selectedSource || !selectedDestination) {
      setFormError("Select both the source and destination users from the dropdown before queueing the job.");
      return;
    }
    if (!destinationFolder.trim()) {
      setFormError("Destination folder is required.");
      return;
    }
    if (normalizeUpn(selectedSource.canonical_upn) === normalizeUpn(selectedDestination.canonical_upn)) {
      setFormError("Source and destination UPNs must be different.");
      return;
    }
    createJobMutation.mutate();
  }

  function handleSourceInputChange(value: string) {
    setSourceUpnInput(value);
    setFormError("");
    if (selectedSource && normalizeUpn(value) !== normalizeUpn(selectedSource.canonical_upn)) {
      setSelectedSource(null);
    }
  }

  function handleDestinationInputChange(value: string) {
    setDestinationUpnInput(value);
    setFormError("");
    if (selectedDestination && normalizeUpn(value) !== normalizeUpn(selectedDestination.canonical_upn)) {
      setSelectedDestination(null);
    }
  }

  function handleSourceSelect(option: ToolUserPickerOption) {
    setSelectedSource(option);
    setSourceUpnInput(option.canonical_upn);
    setFormError("");
  }

  function handleDestinationSelect(option: ToolUserPickerOption) {
    setSelectedDestination(option);
    setDestinationUpnInput(option.canonical_upn);
    setFormError("");
  }

  function handleMailboxInputChange(value: string) {
    setMailboxInput(value);
    setMailboxFormError("");
    if (selectedMailbox && normalizeUpn(value) !== normalizeUpn(selectedMailbox.canonical_upn)) {
      setSelectedMailbox(null);
    }
  }

  function handleMailboxSelect(option: ToolUserPickerOption) {
    setSelectedMailbox(option);
    setMailboxInput(option.canonical_upn);
    setMailboxFormError("");
  }

  function handleDelegateMailboxInputChange(value: string) {
    setDelegateMailboxInput(value);
    setDelegateMailboxFormError("");
    if (selectedDelegateMailbox && normalizeUpn(value) !== normalizeUpn(selectedDelegateMailbox.canonical_upn)) {
      setSelectedDelegateMailbox(null);
    }
  }

  function handleDelegateMailboxSelect(option: ToolUserPickerOption) {
    setSelectedDelegateMailbox(option);
    setDelegateMailboxInput(option.canonical_upn);
    setDelegateMailboxFormError("");
  }

  function handleDelegateUserInputChange(value: string) {
    setDelegateUserInput(value);
    setDelegateUserFormError("");
    if (selectedDelegateUser && normalizeUpn(value) !== normalizeUpn(selectedDelegateUser.canonical_upn)) {
      setSelectedDelegateUser(null);
    }
  }

  function handleDelegateUserSelect(option: ToolUserPickerOption) {
    setSelectedDelegateUser(option);
    setDelegateUserInput(option.canonical_upn);
    setDelegateUserFormError("");
  }

  function handleEmailgisticsUserInputChange(value: string) {
    setEmailgisticsUserInput(value);
    setEmailgisticsHelperFormError("");
    if (selectedEmailgisticsUser && normalizeUpn(value) !== normalizeUpn(selectedEmailgisticsUser.canonical_upn)) {
      setSelectedEmailgisticsUser(null);
    }
  }

  function handleEmailgisticsUserSelect(option: ToolUserPickerOption) {
    setSelectedEmailgisticsUser(option);
    setEmailgisticsUserInput(option.canonical_upn);
    setEmailgisticsHelperFormError("");
  }

  function handleEmailgisticsSharedMailboxInputChange(value: string) {
    setEmailgisticsSharedMailboxInput(value);
    setEmailgisticsHelperFormError("");
    if (
      selectedEmailgisticsSharedMailbox &&
      normalizeUpn(value) !== normalizeUpn(selectedEmailgisticsSharedMailbox.canonical_upn)
    ) {
      setSelectedEmailgisticsSharedMailbox(null);
    }
  }

  function handleEmailgisticsSharedMailboxSelect(option: ToolUserPickerOption) {
    setSelectedEmailgisticsSharedMailbox(option);
    setEmailgisticsSharedMailboxInput(option.canonical_upn);
    setEmailgisticsHelperFormError("");
  }

  function submitMailboxLookup() {
    const mailbox = selectedMailbox?.canonical_upn.trim() || mailboxInput.trim();
    if (!mailbox || !looksLikeUpn(mailbox)) {
      setMailboxFormError("Select a mailbox from the dropdown or enter a valid UPN/email before loading rules.");
      return;
    }
    setMailboxFormError("");
    if (activeMailboxLookup && normalizeUpn(activeMailboxLookup) === normalizeUpn(mailbox)) {
      void mailboxRulesQuery.refetch();
      return;
    }
    setActiveMailboxLookup(mailbox);
  }

  function submitDelegateMailboxLookup() {
    const mailbox = selectedDelegateMailbox?.canonical_upn.trim() || delegateMailboxInput.trim();
    if (!mailbox || !looksLikeUpn(mailbox)) {
      setDelegateMailboxFormError("Select a mailbox from the dropdown or enter a valid UPN/email before loading delegates.");
      return;
    }
    setDelegateMailboxFormError("");
    if (activeDelegateMailboxLookup && normalizeUpn(activeDelegateMailboxLookup) === normalizeUpn(mailbox)) {
      void mailboxDelegatesQuery.refetch();
      return;
    }
    setActiveDelegateMailboxLookup(mailbox);
  }

  function submitDelegateUserLookup() {
    const user = selectedDelegateUser?.canonical_upn.trim() || delegateUserInput.trim();
    if (!user || !looksLikeUpn(user)) {
      setDelegateUserFormError("Select a user from the dropdown or enter a valid UPN/email before scanning delegates.");
      return;
    }
    setDelegateUserFormError("");
    createDelegateMailboxJobMutation.mutate();
  }

  function submitEmailgisticsHelper() {
    const userMailbox = selectedEmailgisticsUser?.canonical_upn.trim() || emailgisticsUserInput.trim();
    const sharedMailbox =
      selectedEmailgisticsSharedMailbox?.canonical_upn.trim() || emailgisticsSharedMailboxInput.trim();
    if (!userMailbox || !looksLikeUpn(userMailbox)) {
      setEmailgisticsHelperFormError("Select a valid user mailbox before running Emailgistics Helper.");
      return;
    }
    if (!sharedMailbox || !looksLikeUpn(sharedMailbox)) {
      setEmailgisticsHelperFormError("Select a valid shared mailbox before running Emailgistics Helper.");
      return;
    }
    if (normalizeUpn(userMailbox) === normalizeUpn(sharedMailbox)) {
      setEmailgisticsHelperFormError("The user mailbox and shared mailbox must be different.");
      return;
    }
    setEmailgisticsHelperFormError("");
    runEmailgisticsHelperMutation.mutate();
  }

  const mailboxApiError =
    mailboxRulesQuery.error instanceof Error &&
    activeMailboxLookup &&
    normalizeUpn(mailboxInput || activeMailboxLookup) === normalizeUpn(activeMailboxLookup)
      ? mailboxRulesQuery.error.message
      : "";
  const delegateMailboxApiError =
    mailboxDelegatesQuery.error instanceof Error &&
    activeDelegateMailboxLookup &&
    normalizeUpn(delegateMailboxInput || activeDelegateMailboxLookup) === normalizeUpn(activeDelegateMailboxLookup)
      ? mailboxDelegatesQuery.error.message
      : "";
  const delegateUserApiError =
    activeDelegateMailboxJobQuery.error instanceof Error
      ? activeDelegateMailboxJobQuery.error.message
      : "";
  const mailboxLookupError = mailboxFormError || mailboxApiError;
  const delegateMailboxLookupError = delegateMailboxFormError || delegateMailboxApiError;
  const delegateUserLookupError = delegateUserFormError || delegateUserApiError;
  const canLookupMailboxDelegates =
    (selectedDelegateMailbox !== null || looksLikeUpn(delegateMailboxInput)) && !mailboxDelegatesQuery.isFetching;
  const canLookupMailboxRules =
    (selectedMailbox !== null || looksLikeUpn(mailboxInput)) && !mailboxRulesQuery.isFetching;
  const canLookupDelegateUser =
    (selectedDelegateUser !== null || looksLikeUpn(delegateUserInput)) && !createDelegateMailboxJobMutation.isPending;
  const canUseEmailgisticsHelper = !!meQuery.data?.is_admin;
  const canUseDeactivateTool = !!meQuery.data?.is_admin;
  const canRunEmailgisticsHelper =
    canUseEmailgisticsHelper &&
    (selectedEmailgisticsUser !== null || looksLikeUpn(emailgisticsUserInput)) &&
    (selectedEmailgisticsSharedMailbox !== null || looksLikeUpn(emailgisticsSharedMailboxInput)) &&
    !runEmailgisticsHelperMutation.isPending;
  const emailgisticsRunningLabel = runEmailgisticsHelperMutation.isPending
    ? "Running Emailgistics Helper..."
    : "";

  return (
    <div className="space-y-6">
      {meQuery.isLoading ? (
        <section className="rounded-3xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500 shadow-sm">
          Loading tools...
        </section>
      ) : null}
      {hasSignedInUser ? (
        <>
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Tools</p>
            <h1 className="mt-1 text-3xl font-bold text-slate-900">{branding.scope === "azure" ? "Azure Tools" : "Helpdesk Tools"}</h1>
            <p className="mt-2 max-w-3xl text-sm text-slate-600">
              Shared tools for Microsoft 365 and Azure tasks. The OneDrive Copy tool mirrors the existing Graph-based handoff script, and the mailbox cards use the shared app registration to inspect Inbox rules plus Exchange delegate access for Send on behalf, Send As, and Full Access.
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
              <DirectoryComboboxField
                label="Source user UPN"
                value={sourceUpnInput}
                onInputChange={handleSourceInputChange}
                onSelect={handleSourceSelect}
                selected={selectedSource}
                loading={sourceSearchQuery.isLoading}
                options={sourceOptions}
                placeholder="dahrens@example.com"
                emptyMessage="No saved or Entra matches found yet. Enter a valid UPN to use and save it."
              />
              <DirectoryComboboxField
                label="Destination user UPN"
                value={destinationUpnInput}
                onInputChange={handleDestinationInputChange}
                onSelect={handleDestinationSelect}
                selected={selectedDestination}
                loading={destinationSearchQuery.isLoading}
                options={destinationOptions}
                placeholder="sstutsman@example.com"
                emptyMessage="No saved or Entra matches found yet. Enter a valid UPN to use and save it."
              />
            </div>

            <div className="mt-4">
              <label className="block space-y-2">
                <span className="text-sm font-medium text-slate-700">Destination folder name</span>
                <input
                  value={destinationFolder}
                  onChange={(event) => {
                    setDestinationFolder(event.target.value);
                    setFormError("");
                  }}
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
                disabled={!canQueueJob}
                className={buttonClass("primary", !canQueueJob)}
              >
                {createJobMutation.isPending ? "Queueing..." : "Queue OneDrive Copy"}
              </button>
              <span className="text-sm text-slate-500">
                If the destination folder name already exists, Microsoft Graph will auto-rename the new folder.
              </span>
            </div>
          </section>

          <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mailbox Delegation</div>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">List mailbox delegate access for a mailbox</h2>
                <p className="mt-2 text-sm text-slate-600">
                  Use the shared Exchange app registration to see which users currently have Send on behalf, Send As, or Full Access on a mailbox. This is read-only and reflects Exchange Online delegate permissions.
                </p>
              </div>
              <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-sky-700">Read only</span>
            </div>

            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
              <DirectoryComboboxField
                label="Mailbox UPN or email"
                value={delegateMailboxInput}
                onInputChange={handleDelegateMailboxInputChange}
                onSelect={handleDelegateMailboxSelect}
                selected={selectedDelegateMailbox}
                loading={delegateMailboxSearchQuery.isLoading}
                options={delegateMailboxOptions}
                placeholder="sharedmailbox@example.com"
                emptyMessage="No saved or Entra matches found yet. Enter a valid UPN/email to use it directly."
              />
              <button
                type="button"
                onClick={submitDelegateMailboxLookup}
                disabled={!canLookupMailboxDelegates}
                className={buttonClass("primary", !canLookupMailboxDelegates)}
              >
                {mailboxDelegatesQuery.isFetching ? "Loading delegates..." : "Load mailbox delegates"}
              </button>
            </div>

            <MailboxDelegatesResults
              data={mailboxDelegatesQuery.data}
              isLoading={mailboxDelegatesQuery.isLoading}
              errorMessage={delegateMailboxLookupError}
              onRefresh={() => {
                void mailboxDelegatesQuery.refetch();
              }}
              isRefreshing={mailboxDelegatesQuery.isFetching}
            />
          </section>

          <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mailbox Delegation</div>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">Find mailboxes where a user has delegate access</h2>
                <p className="mt-2 text-sm text-slate-600">
                  Enter a user email to queue an Exchange mailbox scan and list where that person currently has Send on behalf, Send As, or Full Access through the shared app registration. Most runs finish in 20-90 seconds, but larger tenants can take 5-10 minutes.
                </p>
              </div>
              <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-sky-700">Org scan</span>
            </div>

            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
              <DirectoryComboboxField
                label="User UPN or email"
                value={delegateUserInput}
                onInputChange={handleDelegateUserInputChange}
                onSelect={handleDelegateUserSelect}
                selected={selectedDelegateUser}
                loading={delegateUserSearchQuery.isLoading}
                options={delegateUserOptions}
                placeholder="delegate@example.com"
                emptyMessage="No saved or Entra matches found yet. Enter a valid UPN/email to use it directly."
              />
              <button
                type="button"
                onClick={submitDelegateUserLookup}
                disabled={!canLookupDelegateUser}
                className={buttonClass("primary", !canLookupDelegateUser)}
              >
                {createDelegateMailboxJobMutation.isPending ? "Queueing scan..." : "Find delegate mailboxes"}
              </button>
            </div>

            <DelegateMailboxesResults
              job={activeDelegateMailboxJobQuery.data}
              isLoading={activeDelegateMailboxJobQuery.isLoading}
              errorMessage={delegateUserLookupError}
              onRefresh={() => {
                void delegateMailboxJobsQuery.refetch();
                void activeDelegateMailboxJobQuery.refetch();
              }}
              isRefreshing={delegateMailboxJobsQuery.isFetching || activeDelegateMailboxJobQuery.isFetching}
              onCancel={() => {
                if (!activeDelegateMailboxJobQuery.data) return;
                setDelegateUserFormError("");
                cancelDelegateMailboxJobMutation.mutate(activeDelegateMailboxJobQuery.data.job_id);
              }}
              isCancelling={cancelDelegateMailboxJobMutation.isPending}
            />
          </section>

          {canUseDeactivateTool ? (
            <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">User Lifecycle</div>
                  <h2 className="mt-1 text-2xl font-semibold text-slate-900">Deactivate user</h2>
                  <p className="mt-2 text-sm text-slate-600">
                    Disable a user&apos;s Entra sign-in and/or their on-prem Active Directory account. Select a user from the directory for Entra and optionally enter their AD SAM account name.
                  </p>
                </div>
                <span className="rounded-full bg-red-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-red-700">
                  Admin only
                </span>
              </div>

              <DirectoryComboboxField
                label="User to deactivate"
                value={deactivateUserInput}
                onInputChange={(v) => { setDeactivateUserInput(v); setSelectedDeactivateUser(null); setDeactivateResult(null); }}
                onSelect={(opt) => { setSelectedDeactivateUser(opt); setDeactivateUserInput(opt.display_name || opt.canonical_upn); setDeactivateResult(null); }}
                selected={selectedDeactivateUser}
                loading={deactivateUserSearchQuery.isLoading}
                options={deactivateUserOptions}
                placeholder="Search by name or email..."
                emptyMessage="No Entra directory matches found."
              />
              {selectedDeactivateUser ? (
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full bg-sky-50 px-2.5 py-1 font-medium text-sky-700">Entra: sign-in will be disabled</span>
                  {selectedDeactivateUser.on_prem_sam ? (
                    <span className="rounded-full bg-violet-50 px-2.5 py-1 font-medium text-violet-700">AD: {selectedDeactivateUser.on_prem_sam}</span>
                  ) : (
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-500">AD: no on-prem account linked</span>
                  )}
                </div>
              ) : null}

              {deactivateFormError ? (
                <p className="rounded-xl bg-red-50 px-4 py-2 text-sm text-red-700">{deactivateFormError}</p>
              ) : null}

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  disabled={!selectedDeactivateUser || deactivateUserMutation.isPending}
                  onClick={() => {
                    if (!selectedDeactivateUser) {
                      setDeactivateFormError("Select a user from the directory first.");
                      return;
                    }
                    setDeactivateFormError("");
                    deactivateUserMutation.mutate();
                  }}
                  className={buttonClass("primary", !selectedDeactivateUser || deactivateUserMutation.isPending)}
                >
                  {deactivateUserMutation.isPending ? "Deactivating..." : "Deactivate user"}
                </button>
              </div>

              {deactivateResult ? (
                <div className="space-y-2 rounded-2xl border border-slate-100 bg-slate-50 p-4">
                  {deactivateResult.display_name ? (
                    <p className="text-sm font-semibold text-slate-800">{deactivateResult.display_name}</p>
                  ) : null}
                  {deactivateResult.entra ? (
                    <div className={`flex items-start gap-2 rounded-xl px-3 py-2 text-sm ${deactivateResult.entra.ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
                      <span className="mt-0.5 shrink-0">{deactivateResult.entra.ok ? "✓" : "✗"}</span>
                      <span><strong>Entra:</strong> {deactivateResult.entra.message}</span>
                    </div>
                  ) : null}
                  {deactivateResult.ad ? (
                    <div className={`flex items-start gap-2 rounded-xl px-3 py-2 text-sm ${deactivateResult.ad.ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
                      <span className="mt-0.5 shrink-0">{deactivateResult.ad.ok ? "✓" : "✗"}</span>
                      <span><strong>AD:</strong> {deactivateResult.ad.message}</span>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </section>
          ) : null}

          {canUseEmailgisticsHelper ? (
            <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Emailgistics Helper</div>
                  <h2 className="mt-1 text-2xl font-semibold text-slate-900">
                    Grant mailbox access for Emailgistics
                  </h2>
                  <p className="mt-2 text-sm text-slate-600">
                    Admin-only helper that grants a user Full Access and Send As on a shared mailbox, adds them to the
                    Emailgistics add-in group.
                  </p>
                </div>
                <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-amber-700">
                  Admin only
                </span>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <DirectoryComboboxField
                  label="User mailbox UPN or email"
                  value={emailgisticsUserInput}
                  onInputChange={handleEmailgisticsUserInputChange}
                  onSelect={handleEmailgisticsUserSelect}
                  selected={selectedEmailgisticsUser}
                  loading={emailgisticsUserSearchQuery.isLoading}
                  options={emailgisticsUserOptions}
                  placeholder="analyst@example.com"
                  emptyMessage="No saved or Entra matches found yet. Enter a valid UPN/email to use it directly."
                />
                <DirectoryComboboxField
                  label="Shared mailbox UPN or email"
                  value={emailgisticsSharedMailboxInput}
                  onInputChange={handleEmailgisticsSharedMailboxInputChange}
                  onSelect={handleEmailgisticsSharedMailboxSelect}
                  selected={selectedEmailgisticsSharedMailbox}
                  loading={emailgisticsSharedMailboxSearchQuery.isLoading}
                  options={emailgisticsSharedMailboxOptions}
                  placeholder="sharedmailbox@example.com"
                  emptyMessage="No saved or Entra matches found yet. Enter a valid UPN/email to use it directly."
                />
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={submitEmailgisticsHelper}
                  disabled={!canRunEmailgisticsHelper}
                  className={buttonClass("primary", !canRunEmailgisticsHelper)}
                >
                  {runEmailgisticsHelperMutation.isPending ? "Running helper..." : "Run Emailgistics Helper"}
                </button>
                <span className="text-sm text-slate-500">
                  This action only grants mailbox access and group membership. It no longer runs Emailgistics sync.
                </span>
              </div>

              <EmailgisticsHelperResults
                result={emailgisticsHelperResult}
                isRunning={runEmailgisticsHelperMutation.isPending}
                runningLabel={emailgisticsRunningLabel}
                errorMessage={emailgisticsHelperFormError}
              />
            </section>
          ) : null}

          <section className="space-y-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Mailbox Rules</div>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">List Inbox rules for a provided mailbox</h2>
                <p className="mt-2 text-sm text-slate-600">
                  Use the shared Graph connection to inspect a mailbox&apos;s Inbox rules, including rule order, enabled state, actions, and exceptions.
                </p>
              </div>
              <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-sky-700">Read only</span>
            </div>

            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
              <DirectoryComboboxField
                label="Mailbox UPN or email"
                value={mailboxInput}
                onInputChange={handleMailboxInputChange}
                onSelect={handleMailboxSelect}
                selected={selectedMailbox}
                loading={mailboxSearchQuery.isLoading}
                options={mailboxOptions}
                placeholder="alerts@example.com"
                emptyMessage="No saved or Entra matches found yet. Enter a valid UPN/email to use it directly."
              />
              <button
                type="button"
                onClick={submitMailboxLookup}
                disabled={!canLookupMailboxRules}
                className={buttonClass("primary", !canLookupMailboxRules)}
              >
                {mailboxRulesQuery.isFetching ? "Loading rules..." : "Load mailbox rules"}
              </button>
            </div>

            <MailboxRulesResults
              data={mailboxRulesQuery.data}
              isLoading={mailboxRulesQuery.isLoading}
              errorMessage={mailboxLookupError}
              onRefresh={() => {
                void mailboxRulesQuery.refetch();
              }}
              isRefreshing={mailboxRulesQuery.isFetching}
            />
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

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Shared job history</div>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">Recent OneDrive copy jobs</h2>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setFormError("");
                    clearFinishedOneDriveJobsMutation.mutate();
                  }}
                  disabled={!jobsQuery.data?.some((job) => isFinishedJob(job.status)) || clearFinishedOneDriveJobsMutation.isPending}
                  className={buttonClass("secondary", !jobsQuery.data?.some((job) => isFinishedJob(job.status)) || clearFinishedOneDriveJobsMutation.isPending)}
                >
                  {clearFinishedOneDriveJobsMutation.isPending ? "Clearing..." : "Clear finished"}
                </button>
                <button type="button" onClick={() => jobsQuery.refetch()} className={buttonClass("secondary", jobsQuery.isFetching)}>
                  Refresh
                </button>
              </div>
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

          <DelegateMailboxJobHistory
            jobs={delegateMailboxJobsQuery.data ?? []}
            activeJobId={activeDelegateMailboxJobId}
            onSelect={setActiveDelegateMailboxJobId}
            onRefresh={() => {
              void delegateMailboxJobsQuery.refetch();
            }}
            isRefreshing={delegateMailboxJobsQuery.isFetching}
            onClearFinished={() => {
              setDelegateUserFormError("");
              clearFinishedDelegateMailboxJobsMutation.mutate();
            }}
            isClearing={clearFinishedDelegateMailboxJobsMutation.isPending}
          />

          <LoginAuditPanel events={loginAuditQuery.data ?? []} />
        </div>
      </section>
        </>
      ) : null}
    </div>
  );
}
