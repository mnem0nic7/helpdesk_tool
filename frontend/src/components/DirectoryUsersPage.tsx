import { useEffect, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  api,
  type AzureDirectoryObject,
  type UserAdminActionType,
  type UserAdminAuditEntry,
  type UserAdminCapabilities,
  type UserAdminDevice,
  type UserAdminGroupMembership,
  type UserAdminJobResult,
  type UserAdminJobStatus,
  type UserAdminLicense,
  type UserAdminMailbox,
  type UserAdminRole,
  type UserAdminUserDetail,
  type UserExitPreflight,
  type UserExitWorkflow,
  type UserExitWorkflowStep,
} from "../lib/api.ts";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";

type UserColKey =
  | "display_name"
  | "principal_name"
  | "mail"
  | "department"
  | "job_title"
  | "created_datetime"
  | "on_prem_domain"
  | "is_licensed"
  | "last_successful_utc";

type DirectoryUsersPageMode = "primary" | "azure";
type StatusFilter = "all" | "enabled" | "disabled";
type TypeFilter = "all" | "member" | "guest";
type LicenseFilter = "all" | "licensed";
type ActivityFilter = "all" | "no_success_30d";
type SyncFilter = "all" | "on_prem_synced";
type SummaryPresetKey =
  | "total"
  | "enabled"
  | "disabled"
  | "licensed"
  | "disabled_licensed"
  | "no_success_30d"
  | "members"
  | "guests"
  | "on_prem_synced";
type UserDrawerTab = "overview" | "access" | "groups" | "licenses" | "roles" | "mailbox" | "devices" | "activity" | "exit";

interface PendingAction {
  actionType: UserAdminActionType;
  targetUserIds: string[];
  targetNames: string[];
  params: Record<string, unknown>;
  title: string;
  description: string;
  warning: string;
}

const DEFAULT_DRAWER_WIDTH = 760;
const DRAWER_MIN_WIDTH = 540;
const DRAWER_VIEWPORT_MARGIN = 32;
const CONFIRM_PHRASE = "CONFIRM";

const ACTION_LABELS: Record<UserAdminActionType, string> = {
  disable_sign_in: "Disable Sign-In",
  enable_sign_in: "Enable Sign-In",
  reset_password: "Reset Password",
  revoke_sessions: "Revoke Sessions",
  reset_mfa: "Reset MFA",
  unblock_sign_in: "Unblock Sign-In",
  update_usage_location: "Update Usage Location",
  update_profile: "Update Profile",
  set_manager: "Set Manager",
  add_group_membership: "Add To Group",
  remove_group_membership: "Remove From Group",
  assign_license: "Assign License",
  remove_license: "Remove License",
  add_directory_role: "Add Directory Role",
  remove_directory_role: "Remove Directory Role",
  mailbox_add_alias: "Add Mailbox Alias",
  mailbox_remove_alias: "Remove Mailbox Alias",
  mailbox_set_forwarding: "Set Mail Forwarding",
  mailbox_clear_forwarding: "Clear Mail Forwarding",
  mailbox_convert_type: "Convert Mailbox Type",
  mailbox_set_delegates: "Set Mailbox Delegates",
  device_sync: "Sync Device",
  device_retire: "Retire Device",
  device_wipe: "Wipe Device",
  device_remote_lock: "Remote Lock Device",
  device_reassign_primary_user: "Reassign Primary User",
  exit_group_cleanup: "Remove Direct Cloud Group Memberships",
  exit_on_prem_deprovision: "On-Prem AD Deprovision",
  exit_remove_all_licenses: "Remove Direct M365 Licenses",
  exit_manual_task_complete: "Exit Manual Task Complete",
};

const DANGEROUS_ACTIONS = new Set<UserAdminActionType>([
  "disable_sign_in",
  "reset_password",
  "revoke_sessions",
  "reset_mfa",
  "remove_group_membership",
  "remove_license",
  "remove_directory_role",
  "device_retire",
  "device_wipe",
  "device_remote_lock",
]);

const BULK_ACTION_OPTIONS: Array<{
  value: UserAdminActionType;
  description: string;
}> = [
  { value: "disable_sign_in", description: "Block sign-in for the selected users." },
  { value: "enable_sign_in", description: "Restore sign-in access for the selected users." },
  { value: "revoke_sessions", description: "Force the selected users to reauthenticate." },
  { value: "reset_mfa", description: "Clear MFA registrations for the selected users." },
  { value: "reset_password", description: "Generate one-time passwords for the selected users." },
  { value: "update_usage_location", description: "Update usage location for the selected users." },
  { value: "add_group_membership", description: "Add the selected users to a security or M365 group." },
  { value: "remove_group_membership", description: "Remove the selected users from a group." },
  { value: "assign_license", description: "Assign a license to the selected users." },
  { value: "remove_license", description: "Remove a license from the selected users." },
  { value: "add_directory_role", description: "Add a direct directory role assignment." },
  { value: "remove_directory_role", description: "Remove a direct directory role assignment." },
];

const DRAWER_TABS: Array<{ id: UserDrawerTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "access", label: "Access" },
  { id: "groups", label: "Groups" },
  { id: "licenses", label: "Licenses" },
  { id: "roles", label: "Roles" },
  { id: "mailbox", label: "Mailbox" },
  { id: "devices", label: "Devices" },
  { id: "activity", label: "Activity" },
  { id: "exit", label: "Exit" },
];

function getDirectoryLabel(user: AzureDirectoryObject): string {
  if (user.extra.on_prem_domain) return user.extra.on_prem_domain;
  if (user.extra.user_type === "Guest") return "External";
  return "Cloud";
}

function clampDrawerWidth(width: number): number {
  if (typeof window === "undefined") return DEFAULT_DRAWER_WIDTH;
  const maxWidth = Math.max(400, window.innerWidth - DRAWER_VIEWPORT_MARGIN);
  const minWidth = Math.min(DRAWER_MIN_WIDTH, maxWidth);
  return Math.min(Math.max(width, minWidth), maxWidth);
}

function getExpandedDrawerWidth(): number {
  if (typeof window === "undefined") return DEFAULT_DRAWER_WIDTH;
  return clampDrawerWidth(window.innerWidth - DRAWER_VIEWPORT_MARGIN);
}

function isLicensedUser(user: AzureDirectoryObject): boolean {
  return String(user.extra.is_licensed || "").toLowerCase() === "true";
}

function licenseCount(user: AzureDirectoryObject): number {
  const raw = Number(user.extra.license_count || "0");
  return Number.isFinite(raw) ? raw : 0;
}

function lastSuccessfulIso(user: AzureDirectoryObject): string {
  return user.extra.last_successful_utc || "";
}

function hasNoSuccessfulSignIn30d(user: AzureDirectoryObject): boolean {
  if (user.enabled !== true) return false;
  const iso = lastSuccessfulIso(user);
  if (!iso) return true;
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return true;
  return Date.now() - time >= 30 * 24 * 60 * 60 * 1000;
}

function isOnPremSynced(user: AzureDirectoryObject): boolean {
  return String(user.extra.on_prem_sync || "").toLowerCase() === "true";
}

function lastSuccessfulText(user: AzureDirectoryObject): string {
  return user.extra.last_successful_local || formatDateTime(user.extra.last_successful_utc);
}

function formatDate(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatDateTime(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
}

function createLiveDetailFallback(user: AzureDirectoryObject): UserAdminUserDetail {
  return {
    id: user.id,
    display_name: user.display_name,
    principal_name: user.principal_name,
    mail: user.mail,
    enabled: user.enabled ?? null,
    user_type: user.extra.user_type || "Member",
    department: user.extra.department || "",
    job_title: user.extra.job_title || "",
    office_location: user.extra.office_location || "",
    company_name: user.extra.company_name || "",
    city: user.extra.city || "",
    country: user.extra.country || "",
    mobile_phone: user.extra.mobile_phone || "",
    business_phones: user.extra.business_phones ? user.extra.business_phones.split(",").map((item) => item.trim()).filter(Boolean) : [],
    created_datetime: user.extra.created_datetime || "",
    last_password_change: user.extra.last_password_change || "",
    on_prem_sync: user.extra.on_prem_sync === "true",
    on_prem_domain: user.extra.on_prem_domain || "",
    on_prem_netbios: user.extra.on_prem_netbios || "",
    on_prem_sam_account_name: user.extra.on_prem_sam_account_name || "",
    on_prem_distinguished_name: user.extra.on_prem_distinguished_name || "",
    usage_location: "",
    employee_id: "",
    employee_type: "",
    preferred_language: "",
    proxy_addresses: user.extra.proxy_addresses ? user.extra.proxy_addresses.split(",").map((item) => item.trim()).filter(Boolean) : [],
    is_licensed: isLicensedUser(user),
    license_count: licenseCount(user),
    sku_part_numbers: user.extra.sku_part_numbers
      ? user.extra.sku_part_numbers.split(",").map((item) => item.trim()).filter(Boolean)
      : [],
    last_interactive_utc: user.extra.last_interactive_utc || "",
    last_interactive_local: user.extra.last_interactive_local || "",
    last_noninteractive_utc: user.extra.last_noninteractive_utc || "",
    last_noninteractive_local: user.extra.last_noninteractive_local || "",
    last_successful_utc: user.extra.last_successful_utc || "",
    last_successful_local: user.extra.last_successful_local || "",
    manager: null,
    source_directory: getDirectoryLabel(user),
  };
}

function pillClass(active: boolean) {
  return [
    "rounded-full border px-4 py-1.5 text-sm font-medium transition",
    active
      ? "border-sky-500 bg-sky-50 text-sky-700"
      : "border-slate-300 bg-white text-slate-600 hover:border-slate-400 hover:bg-slate-50",
  ].join(" ");
}

function cardTitleClass() {
  return "text-sm font-semibold uppercase tracking-wide text-slate-500";
}

function inputClass(disabled = false) {
  return [
    "rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition",
    disabled ? "bg-slate-100 text-slate-400" : "bg-white text-slate-900 focus:border-sky-500",
  ].join(" ");
}

function buttonClass(kind: "primary" | "secondary" | "danger" = "secondary", disabled = false) {
  if (disabled) {
    return "rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-sm font-medium text-slate-400";
  }
  if (kind === "primary") {
    return "rounded-lg border border-sky-600 bg-sky-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-sky-700";
  }
  if (kind === "danger") {
    return "rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100";
  }
  return "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-400 hover:bg-slate-50";
}

function StatusChip({ enabled }: { enabled: boolean | null }) {
  if (enabled === true) {
    return <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">Enabled</span>;
  }
  if (enabled === false) {
    return <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">Disabled</span>;
  }
  return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">Unknown</span>;
}

function TypeChip({ userType }: { userType: string }) {
  if (userType === "Guest") {
    return <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">Guest</span>;
  }
  return <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-700">Member</span>;
}

function StatCard({
  label,
  value,
  tone = "text-slate-900",
  active = false,
  onClick,
}: {
  label: string;
  value: string;
  tone?: string;
  active?: boolean;
  onClick?: () => void;
}) {
  const className = [
    "w-full rounded-2xl border bg-white p-5 text-left shadow-sm transition",
    onClick
      ? active
        ? "border-sky-500 ring-2 ring-sky-200"
        : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"
      : "border-slate-200",
  ].join(" ");
  const content = (
    <>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${tone}`}>{value}</div>
    </>
  );
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={className}
        aria-pressed={active}
        aria-label={`${label} summary filter`}
      >
        {content}
      </button>
    );
  }
  return (
    <div className={className}>{content}</div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="flex flex-col gap-0.5">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="break-all text-sm text-slate-900">{value}</div>
    </div>
  );
}

function SectionCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className={cardTitleClass()}>{title}</h3>
      <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4">{children}</div>
    </section>
  );
}

function QueryState({
  isLoading,
  isError,
  error,
}: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
}) {
  if (isLoading) {
    return <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">Loading...</div>;
  }
  if (isError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load data: {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }
  return null;
}

function SummaryList({ items }: { items: string[] }) {
  if (items.length === 0) {
    return <div className="text-sm text-slate-500">None</div>;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <span key={item} className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700">
          {item}
        </span>
      ))}
    </div>
  );
}

function stringifySummary(summary: Record<string, unknown>): string {
  const entries = Object.entries(summary).filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (entries.length === 0) return "—";
  return entries
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join(" | ");
}

function ActionConfirmModal({
  action,
  onCancel,
  onConfirm,
  isSubmitting,
}: {
  action: PendingAction;
  onCancel: () => void;
  onConfirm: () => void;
  isSubmitting: boolean;
}) {
  const [typedValue, setTypedValue] = useState("");

  useEffect(() => {
    setTypedValue("");
  }, [action]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4" onClick={onCancel}>
      <div
        className="w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="text-xl font-bold text-slate-900">{action.title}</h2>
        <p className="mt-2 text-sm text-slate-600">{action.description}</p>
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">{action.warning}</div>
        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Targets</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {action.targetNames.slice(0, 8).map((name) => (
              <span key={name} className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700">
                {name}
              </span>
            ))}
            {action.targetNames.length > 8 ? (
              <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700">
                +{action.targetNames.length - 8} more
              </span>
            ) : null}
          </div>
        </div>
        <div className="mt-4 space-y-2">
          <label className="text-sm font-medium text-slate-700" htmlFor="confirm-typed-input">
            Type <span className="font-semibold text-slate-900">{CONFIRM_PHRASE}</span> to continue
          </label>
          <input
            id="confirm-typed-input"
            value={typedValue}
            onChange={(event) => setTypedValue(event.target.value)}
            className={inputClass()}
            placeholder={CONFIRM_PHRASE}
          />
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onCancel} className={buttonClass("secondary", isSubmitting)}>
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={typedValue !== CONFIRM_PHRASE || isSubmitting}
            className={buttonClass(DANGEROUS_ACTIONS.has(action.actionType) ? "danger" : "primary", typedValue !== CONFIRM_PHRASE || isSubmitting)}
          >
            {isSubmitting ? "Submitting..." : `Queue ${ACTION_LABELS[action.actionType]}`}
          </button>
        </div>
      </div>
    </div>
  );
}

function JobProgressCard({
  job,
  results,
}: {
  job: UserAdminJobStatus;
  results: UserAdminJobResult[] | null;
}) {
  const percent = job.progress_total > 0 ? Math.round((job.progress_current / job.progress_total) * 100) : 0;
  return (
    <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Latest Job</div>
          <h2 className="mt-1 text-xl font-bold text-slate-900">{ACTION_LABELS[job.action_type]}</h2>
          <p className="mt-1 text-sm text-slate-500">{job.progress_message}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-600">{job.status}</span>
          <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-sky-700">
            {job.success_count} success
          </span>
          {job.failure_count > 0 ? (
            <span className="rounded-full bg-red-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-red-700">
              {job.failure_count} failed
            </span>
          ) : null}
        </div>
      </div>
      <div>
        <div className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500">
          <span>Progress</span>
          <span>
            {job.progress_current}/{job.progress_total}
          </span>
        </div>
        <div className="h-3 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-sky-600 transition-all" style={{ width: `${percent}%` }} />
        </div>
      </div>
      {results ? (
        <div className="space-y-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Results</div>
          {results.map((result) => (
            <div
              key={`${job.job_id}-${result.target_user_id}`}
              className={[
                "rounded-xl border p-4",
                result.success ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50",
              ].join(" ")}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium text-slate-900">{result.target_display_name || result.target_user_id}</div>
                <div className={result.success ? "text-sm font-semibold text-emerald-700" : "text-sm font-semibold text-red-700"}>
                  {result.success ? "Success" : "Failed"}
                </div>
              </div>
              <div className="mt-1 text-sm text-slate-700">{result.summary || result.error || "No summary returned."}</div>
              {result.one_time_secret ? (
                <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                  Temporary password: <span className="font-mono font-semibold">{result.one_time_secret}</span>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function AuditPanel({ entries }: { entries: UserAdminAuditEntry[] }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-lg font-semibold text-slate-900">Recent Activity</h2>
        <p className="mt-1 text-sm text-slate-500">Durable audit history for user-management actions on it-app.</p>
      </div>
      <div className="divide-y divide-slate-200">
        {entries.length === 0 ? (
          <div className="px-4 py-6 text-sm text-slate-500">No management activity has been recorded yet.</div>
        ) : null}
        {entries.map((entry) => (
          <div key={entry.audit_id} className="space-y-2 px-4 py-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-medium text-slate-900">
                {entry.target_display_name || entry.target_user_id} • {ACTION_LABELS[entry.action_type]}
              </div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{formatDateTime(entry.created_at)}</div>
            </div>
            <div className="text-sm text-slate-600">
              {entry.actor_name || entry.actor_email} • {entry.provider}
            </div>
            <div className="text-sm text-slate-700">Params: {stringifySummary(entry.params_summary)}</div>
            <div className="text-sm text-slate-700">Result: {stringifySummary(entry.after_summary)}</div>
            {entry.error ? <div className="text-sm text-red-700">Error: {entry.error}</div> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function AzureUserDrawerContent({ user }: { user: AzureDirectoryObject }) {
  const { extra } = user;

  return (
    <div className="space-y-6">
      <SectionCard title="Contact">
        <DetailRow label="Email" value={user.mail} />
        <DetailRow label="Mobile Phone" value={extra.mobile_phone} />
        <DetailRow label="Business Phones" value={extra.business_phones} />
        <DetailRow label="City" value={extra.city} />
        <DetailRow label="Country" value={extra.country} />
      </SectionCard>

      <SectionCard title="Organization">
        <DetailRow label="Job Title" value={extra.job_title} />
        <DetailRow label="Department" value={extra.department} />
        <DetailRow label="Company" value={extra.company_name} />
        <DetailRow label="Office Location" value={extra.office_location} />
      </SectionCard>

      <SectionCard title="Account">
        <DetailRow label="User Type" value={extra.user_type} />
        <DetailRow label="Source Directory" value={getDirectoryLabel(user)} />
        <DetailRow label="On-Prem Domain" value={extra.on_prem_domain} />
        <DetailRow label="NetBIOS Name" value={extra.on_prem_netbios} />
        <DetailRow label="Created" value={formatDate(extra.created_datetime)} />
        <DetailRow label="Last Password Change" value={formatDate(extra.last_password_change)} />
        <DetailRow label="Proxy Addresses" value={extra.proxy_addresses} />
      </SectionCard>
    </div>
  );
}

function ExitStepStatusChip({ status }: { status: UserExitWorkflowStep["status"] | UserExitWorkflow["status"] }) {
  const tone =
    status === "completed"
      ? "bg-emerald-100 text-emerald-700"
      : status === "failed"
        ? "bg-red-100 text-red-700"
        : status === "running"
          ? "bg-sky-100 text-sky-700"
          : status === "awaiting_manual"
            ? "bg-amber-100 text-amber-700"
            : status === "skipped"
              ? "bg-slate-100 text-slate-600"
              : "bg-slate-100 text-slate-600";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${tone}`}>{status}</span>;
}

function ExitWorkflowPanel({
  user,
}: {
  user: AzureDirectoryObject;
}) {
  const queryClient = useQueryClient();
  const [typedUpn, setTypedUpn] = useState("");
  const [onPremOverride, setOnPremOverride] = useState("");
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [manualNotes, setManualNotes] = useState<Record<string, string>>({});

  const preflightQuery = useQuery<UserExitPreflight>({
    queryKey: ["user-exit", "preflight", user.id],
    queryFn: () => api.getUserExitPreflight(user.id),
  });

  const workflowQuery = useQuery<UserExitWorkflow>({
    queryKey: ["user-exit", "workflow", workflowId],
    queryFn: () => api.getUserExitWorkflow(workflowId as string),
    enabled: !!workflowId,
    refetchInterval: (query) => {
      const workflow = query.state.data as UserExitWorkflow | undefined;
      return workflow && ["completed", "failed"].includes(workflow.status) ? false : 3000;
    },
  });

  useEffect(() => {
    setTypedUpn("");
    setOnPremOverride("");
    setWorkflowId(null);
    setManualNotes({});
  }, [user.id]);

  useEffect(() => {
    if (preflightQuery.data?.active_workflow?.workflow_id) {
      setWorkflowId((current) => current || preflightQuery.data?.active_workflow?.workflow_id || null);
    }
  }, [preflightQuery.data]);

  const createWorkflowMutation = useMutation({
    mutationFn: () =>
      api.createUserExitWorkflow({
        user_id: user.id,
        typed_upn_confirmation: typedUpn,
        on_prem_sam_account_name_override: onPremOverride.trim(),
      }),
    onSuccess: async (workflow) => {
      setWorkflowId(workflow.workflow_id);
      await queryClient.invalidateQueries({ queryKey: ["user-admin", "activity", user.id] });
      await queryClient.invalidateQueries({ queryKey: ["user-admin", "audit"] });
    },
  });

  const retryStepMutation = useMutation({
    mutationFn: (stepId: string) => api.retryUserExitWorkflowStep(workflowId as string, stepId),
    onSuccess: async (workflow) => {
      setWorkflowId(workflow.workflow_id);
      await queryClient.invalidateQueries({ queryKey: ["user-admin", "activity", user.id] });
      await queryClient.invalidateQueries({ queryKey: ["user-admin", "audit"] });
    },
  });

  const completeTaskMutation = useMutation({
    mutationFn: (taskId: string) => api.completeUserExitManualTask(workflowId as string, taskId, manualNotes[taskId] || ""),
    onSuccess: async (workflow) => {
      setWorkflowId(workflow.workflow_id);
      await queryClient.invalidateQueries({ queryKey: ["user-admin", "activity", user.id] });
      await queryClient.invalidateQueries({ queryKey: ["user-admin", "audit"] });
    },
  });

  const preflight = preflightQuery.data;
  const workflow = workflowQuery.data;
  const canStartWorkflow =
    !!preflight &&
    typedUpn.trim().toLowerCase() === preflight.user_principal_name.trim().toLowerCase() &&
    (!preflight.requires_on_prem_username_override || onPremOverride.trim().length > 0) &&
    !preflight.active_workflow &&
    !workflowId;

  return (
    <div className="space-y-6">
      <QueryState isLoading={preflightQuery.isLoading} isError={preflightQuery.isError} error={preflightQuery.error} />

      {preflight ? (
        <>
          <SectionCard title="Preflight">
            <DetailRow label="Scope" value={preflight.scope_summary} />
            <DetailRow label="Directory Profile" value={preflight.profile_label || "Cloud-only"} />
            <DetailRow label="On-Prem Username" value={preflight.on_prem_sam_account_name || onPremOverride} />
            <DetailRow label="Mailbox" value={preflight.mailbox_expected ? "Mailbox detected" : "No mailbox detected"} />
            <DetailRow label="Direct Licenses" value={`${preflight.direct_license_count}`} />
            <DetailRow label="Managed Devices" value={`${preflight.managed_devices.length}`} />
            {preflight.warnings.length > 0 ? (
              <div className="space-y-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                {preflight.warnings.map((warning) => (
                  <div key={warning}>{warning}</div>
                ))}
              </div>
            ) : null}
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Manual Follow-Up</div>
              <SummaryList items={preflight.manual_tasks.map((task) => task.label)} />
            </div>
            <div className="space-y-2">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Automated Steps</div>
              {(preflight.steps || []).map((step) => (
                <div key={step.step_key} className="rounded-lg border border-slate-200 bg-white p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-medium text-slate-900">{step.label}</div>
                    <ExitStepStatusChip status={step.will_run ? "queued" : "skipped"} />
                  </div>
                  {step.reason ? <div className="mt-1 text-sm text-slate-500">{step.reason}</div> : null}
                </div>
              ))}
            </div>
          </SectionCard>

          {preflight.active_workflow ? (
            <SectionCard title="Active Workflow">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-sm text-slate-700">
                  A workflow is already active for this user. The live timeline is shown below.
                </div>
                <ExitStepStatusChip status={preflight.active_workflow.status} />
              </div>
            </SectionCard>
          ) : null}

          {!workflowId ? (
            <SectionCard title="Start Exit Workflow">
              <div className="text-sm text-slate-600">
                Type the exact UPN below to confirm the exit workflow for this user.
              </div>
              <input
                value={typedUpn}
                onChange={(event) => setTypedUpn(event.target.value)}
                className={inputClass()}
                placeholder={preflight.user_principal_name}
              />
              {preflight.requires_on_prem_username_override ? (
                <input
                  value={onPremOverride}
                  onChange={(event) => setOnPremOverride(event.target.value)}
                  className={inputClass()}
                  placeholder="On-prem SAM account name"
                />
              ) : null}
              <button
                type="button"
                className={buttonClass("danger", !canStartWorkflow || createWorkflowMutation.isPending)}
                disabled={!canStartWorkflow || createWorkflowMutation.isPending}
                onClick={() => void createWorkflowMutation.mutateAsync()}
              >
                {createWorkflowMutation.isPending ? "Starting..." : "Start Exit Workflow"}
              </button>
            </SectionCard>
          ) : null}
        </>
      ) : null}

      {workflowQuery.isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load exit workflow: {workflowQuery.error instanceof Error ? workflowQuery.error.message : "Unknown error"}
        </div>
      ) : null}

      {workflow ? (
        <>
          <SectionCard title="Workflow Timeline">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm text-slate-700">
                Requested by {workflow.requested_by_name || workflow.requested_by_email}
              </div>
              <ExitStepStatusChip status={workflow.status} />
            </div>
            {workflow.error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{workflow.error}</div> : null}
            {workflow.steps.map((step) => (
              <div key={step.step_id} className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="font-medium text-slate-900">{step.label}</div>
                    <div className="mt-1 text-sm text-slate-500">
                      {step.summary || step.error || "Waiting to run."}
                    </div>
                    {step.error ? <div className="mt-1 text-sm text-red-700">{step.error}</div> : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <ExitStepStatusChip status={step.status} />
                    {step.status === "failed" ? (
                      <button
                        type="button"
                        className={buttonClass("secondary", retryStepMutation.isPending)}
                        disabled={retryStepMutation.isPending}
                        onClick={() => void retryStepMutation.mutateAsync(step.step_id)}
                      >
                        Retry
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>
            ))}
          </SectionCard>

          <SectionCard title="Manual Checklist">
            {workflow.manual_tasks.map((task) => (
              <div key={task.task_id} className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="font-medium text-slate-900">{task.label}</div>
                    <div className="mt-1 text-sm text-slate-500">
                      {task.completed_at ? `Completed ${formatDateTime(task.completed_at)}` : "Pending"}
                    </div>
                  </div>
                  <ExitStepStatusChip status={task.status === "completed" ? "completed" : "queued"} />
                </div>
                {task.status !== "completed" ? (
                  <div className="mt-3 grid gap-3 md:grid-cols-[1fr_auto]">
                    <input
                      value={manualNotes[task.task_id] || ""}
                      onChange={(event) => setManualNotes((current) => ({ ...current, [task.task_id]: event.target.value }))}
                      className={inputClass()}
                      placeholder="Optional note"
                    />
                    <button
                      type="button"
                      className={buttonClass("primary", completeTaskMutation.isPending)}
                      disabled={completeTaskMutation.isPending}
                      onClick={() => void completeTaskMutation.mutateAsync(task.task_id)}
                    >
                      Mark Complete
                    </button>
                  </div>
                ) : (
                  <div className="mt-2 text-sm text-slate-600">{task.notes || "Completed."}</div>
                )}
              </div>
            ))}
          </SectionCard>
        </>
      ) : null}
    </div>
  );
}

function PrimaryUserDrawerContent({
  user,
  capabilities,
  onQueueAction,
}: {
  user: AzureDirectoryObject;
  capabilities: UserAdminCapabilities | undefined;
  onQueueAction: (action: PendingAction) => void;
}) {
  const [selectedTab, setSelectedTab] = useState<UserDrawerTab>("overview");
  const [profileDraft, setProfileDraft] = useState({
    display_name: user.display_name,
    department: user.extra.department || "",
    job_title: user.extra.job_title || "",
    office_location: user.extra.office_location || "",
    company_name: user.extra.company_name || "",
    mobile_phone: user.extra.mobile_phone || "",
    business_phones: user.extra.business_phones || "",
  });
  const [managerUserId, setManagerUserId] = useState("");
  const [usageLocation, setUsageLocation] = useState("");
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [selectedLicenseId, setSelectedLicenseId] = useState("");
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [devicePrimaryUserId, setDevicePrimaryUserId] = useState("");

  const detailQuery = useQuery<UserAdminUserDetail>({
    queryKey: ["user-admin", "detail", user.id],
    queryFn: () => api.getUserAdminUserDetail(user.id),
  });
  const groupsQuery = useQuery<UserAdminGroupMembership[]>({
    queryKey: ["user-admin", "groups", user.id],
    queryFn: () => api.getUserAdminUserGroups(user.id),
  });
  const licensesQuery = useQuery<UserAdminLicense[]>({
    queryKey: ["user-admin", "licenses", user.id],
    queryFn: () => api.getUserAdminUserLicenses(user.id),
  });
  const rolesQuery = useQuery<UserAdminRole[]>({
    queryKey: ["user-admin", "roles", user.id],
    queryFn: () => api.getUserAdminUserRoles(user.id),
  });
  const mailboxQuery = useQuery<UserAdminMailbox>({
    queryKey: ["user-admin", "mailbox", user.id],
    queryFn: () => api.getUserAdminUserMailbox(user.id),
  });
  const devicesQuery = useQuery<UserAdminDevice[]>({
    queryKey: ["user-admin", "devices", user.id],
    queryFn: () => api.getUserAdminUserDevices(user.id),
  });
  const activityQuery = useQuery<UserAdminAuditEntry[]>({
    queryKey: ["user-admin", "activity", user.id],
    queryFn: () => api.getUserAdminUserActivity(user.id),
  });

  const detail = detailQuery.data || createLiveDetailFallback(user);
  const groups = groupsQuery.data || [];
  const licenses = licensesQuery.data || [];
  const roles = rolesQuery.data || [];
  const mailbox = mailboxQuery.data;
  const devices = devicesQuery.data || [];
  const activity = activityQuery.data || [];

  useEffect(() => {
    setSelectedTab("overview");
    setManagerUserId("");
    setSelectedGroupId("");
    setSelectedLicenseId("");
    setSelectedRoleId("");
    setDevicePrimaryUserId("");
  }, [user.id]);

  useEffect(() => {
    const source = detailQuery.data || createLiveDetailFallback(user);
    setUsageLocation(source.usage_location || "");
    setManagerUserId(source.manager?.id || "");
    setProfileDraft({
      display_name: source.display_name,
      department: source.department,
      job_title: source.job_title,
      office_location: source.office_location,
      company_name: source.company_name,
      mobile_phone: source.mobile_phone,
      business_phones: source.business_phones.join(", "),
    });
  }, [user.id, detailQuery.data]);

  function queueAction(actionType: UserAdminActionType, params: Record<string, unknown>, description: string) {
    onQueueAction({
      actionType,
      targetUserIds: [user.id],
      targetNames: [detail.display_name || user.display_name],
      params,
      title: `${ACTION_LABELS[actionType]}: ${detail.display_name || user.display_name}`,
      description,
      warning: DANGEROUS_ACTIONS.has(actionType)
        ? "This action can interrupt access or device state immediately. Review the target carefully before continuing."
        : "This action will be queued and recorded in the user-admin audit log.",
    });
  }

  const canManageMailbox = Boolean(mailbox?.management_supported && capabilities?.supported_actions.some((action) => action.startsWith("mailbox_")));

  return (
    <div className="space-y-6">
      <div className="border-b border-slate-200">
        <div className="flex flex-wrap gap-2 pb-4">
          {DRAWER_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setSelectedTab(tab.id)}
              className={pillClass(selectedTab === tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {selectedTab === "overview" ? (
        <div className="space-y-6">
          <QueryState isLoading={detailQuery.isLoading} isError={detailQuery.isError} error={detailQuery.error} />
          <SectionCard title="Contact">
            <DetailRow label="Email" value={detail.mail} />
            <DetailRow label="Mobile Phone" value={detail.mobile_phone} />
            <DetailRow label="Business Phones" value={detail.business_phones.join(", ")} />
            <DetailRow label="City" value={detail.city} />
            <DetailRow label="Country" value={detail.country} />
          </SectionCard>

          <SectionCard title="Organization">
            <DetailRow label="Job Title" value={detail.job_title} />
            <DetailRow label="Department" value={detail.department} />
            <DetailRow label="Company" value={detail.company_name} />
            <DetailRow label="Office Location" value={detail.office_location} />
            <DetailRow label="Manager" value={detail.manager?.display_name || ""} />
          </SectionCard>

          <SectionCard title="Audit Reporting">
            <DetailRow label="Licensed" value={detail.is_licensed ? "Yes" : "No"} />
            <DetailRow label="License Count" value={`${detail.license_count}`} />
            <DetailRow label="SKU Part Numbers" value={detail.sku_part_numbers.join(", ")} />
            <DetailRow label="Last Interactive" value={detail.last_interactive_local || formatDateTime(detail.last_interactive_utc)} />
            <DetailRow label="Last Noninteractive" value={detail.last_noninteractive_local || formatDateTime(detail.last_noninteractive_utc)} />
            <DetailRow label="Last Successful" value={detail.last_successful_local || formatDateTime(detail.last_successful_utc)} />
            <DetailRow label="On-Prem SAM" value={detail.on_prem_sam_account_name} />
            <DetailRow label="On-Prem DN" value={detail.on_prem_distinguished_name} />
          </SectionCard>

          <SectionCard title="Profile Update">
            <div className="grid gap-3 md:grid-cols-2">
              <input
                value={profileDraft.display_name}
                onChange={(event) => setProfileDraft((current) => ({ ...current, display_name: event.target.value }))}
                className={inputClass()}
                placeholder="Display name"
              />
              <input
                value={profileDraft.department}
                onChange={(event) => setProfileDraft((current) => ({ ...current, department: event.target.value }))}
                className={inputClass()}
                placeholder="Department"
              />
              <input
                value={profileDraft.job_title}
                onChange={(event) => setProfileDraft((current) => ({ ...current, job_title: event.target.value }))}
                className={inputClass()}
                placeholder="Job title"
              />
              <input
                value={profileDraft.office_location}
                onChange={(event) => setProfileDraft((current) => ({ ...current, office_location: event.target.value }))}
                className={inputClass()}
                placeholder="Office location"
              />
              <input
                value={profileDraft.company_name}
                onChange={(event) => setProfileDraft((current) => ({ ...current, company_name: event.target.value }))}
                className={inputClass()}
                placeholder="Company"
              />
              <input
                value={profileDraft.mobile_phone}
                onChange={(event) => setProfileDraft((current) => ({ ...current, mobile_phone: event.target.value }))}
                className={inputClass()}
                placeholder="Mobile phone"
              />
              <input
                value={profileDraft.business_phones}
                onChange={(event) => setProfileDraft((current) => ({ ...current, business_phones: event.target.value }))}
                className={`md:col-span-2 ${inputClass()}`}
                placeholder="Business phones (comma separated)"
              />
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className={buttonClass("primary")}
                onClick={() =>
                  queueAction(
                    "update_profile",
                    profileDraft,
                    "Update the selected profile fields for this user.",
                  )
                }
              >
                Review Profile Update
              </button>
            </div>
            <div className="grid gap-3 md:grid-cols-[1fr_auto_auto]">
              <input
                value={managerUserId}
                onChange={(event) => setManagerUserId(event.target.value)}
                className={inputClass()}
                placeholder="Manager object ID"
              />
              <button
                type="button"
                className={buttonClass("secondary")}
                onClick={() =>
                  queueAction(
                    "set_manager",
                    { manager_user_id: managerUserId },
                    "Update the direct manager reference for this user.",
                  )
                }
              >
                Review Manager Change
              </button>
              <button
                type="button"
                className={buttonClass("danger")}
                onClick={() =>
                  queueAction(
                    "set_manager",
                    { manager_user_id: "" },
                    "Clear the direct manager reference for this user.",
                  )
                }
              >
                Clear Manager
              </button>
            </div>
          </SectionCard>
        </div>
      ) : null}

      {selectedTab === "access" ? (
        <div className="space-y-6">
          <QueryState isLoading={detailQuery.isLoading} isError={detailQuery.isError} error={detailQuery.error} />
          <SectionCard title="Access Controls">
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={buttonClass(detail.enabled === false ? "secondary" : "danger")}
                onClick={() => queueAction("disable_sign_in", {}, "Disable interactive sign-in for this user.")}
              >
                Disable User
              </button>
              <button
                type="button"
                className={buttonClass("secondary")}
                onClick={() => queueAction("enable_sign_in", {}, "Re-enable interactive sign-in for this user.")}
              >
                Enable User
              </button>
              <button
                type="button"
                className={buttonClass("secondary")}
                onClick={() => queueAction("reset_password", { force_change_on_next_login: true }, "Generate a one-time password and require a change on next sign-in.")}
              >
                Reset Password
              </button>
              <button
                type="button"
                className={buttonClass("secondary")}
                onClick={() => queueAction("revoke_sessions", {}, "Revoke active sessions for this user.")}
              >
                Revoke Sessions
              </button>
              <button
                type="button"
                className={buttonClass("secondary")}
                onClick={() => queueAction("reset_mfa", {}, "Clear registered MFA methods for this user.")}
              >
                Reset MFA
              </button>
            </div>
            <div className="grid gap-3 md:grid-cols-[180px_auto]">
              <input
                value={usageLocation}
                onChange={(event) => setUsageLocation(event.target.value.toUpperCase())}
                className={inputClass()}
                maxLength={2}
                placeholder="US"
              />
              <button
                type="button"
                className={buttonClass("primary", usageLocation.trim().length !== 2)}
                disabled={usageLocation.trim().length !== 2}
                onClick={() =>
                  queueAction(
                    "update_usage_location",
                    { usage_location: usageLocation.trim().toUpperCase() },
                    "Update the usage location for this user.",
                  )
                }
              >
                Review Usage Location Update
              </button>
            </div>
            <div className="text-sm text-slate-600">
              Current status: <span className="font-medium text-slate-900">{detail.enabled === false ? "Disabled" : "Enabled"}</span> | Usage location:{" "}
              <span className="font-medium text-slate-900">{detail.usage_location || "Not set"}</span>
            </div>
          </SectionCard>
        </div>
      ) : null}

      {selectedTab === "groups" ? (
        <div className="space-y-6">
          <QueryState isLoading={groupsQuery.isLoading} isError={groupsQuery.isError} error={groupsQuery.error} />
          <SectionCard title="Current Memberships">
            {groups.length === 0 ? <div className="text-sm text-slate-500">No direct groups found.</div> : null}
            {groups.map((group: UserAdminGroupMembership) => (
              <div key={group.id} className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="font-medium text-slate-900">{group.display_name}</div>
                <div className="mt-1 text-sm text-slate-500">{group.mail || group.id}</div>
              </div>
            ))}
          </SectionCard>
          <SectionCard title="Manage Membership">
            <select value={selectedGroupId} onChange={(event) => setSelectedGroupId(event.target.value)} className={inputClass()}>
              <option value="">Select a group</option>
              {(capabilities?.group_catalog || []).map((group) => (
                <option key={group.id} value={group.id}>
                  {group.display_name}
                </option>
              ))}
            </select>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className={buttonClass("primary", !selectedGroupId)}
                disabled={!selectedGroupId}
                onClick={() =>
                  queueAction(
                    "add_group_membership",
                    { group_id: selectedGroupId },
                    "Add this user to the selected group.",
                  )
                }
              >
                Review Group Add
              </button>
              <button
                type="button"
                className={buttonClass("danger", !selectedGroupId)}
                disabled={!selectedGroupId}
                onClick={() =>
                  queueAction(
                    "remove_group_membership",
                    { group_id: selectedGroupId },
                    "Remove this user from the selected group.",
                  )
                }
              >
                Review Group Removal
              </button>
            </div>
          </SectionCard>
        </div>
      ) : null}

      {selectedTab === "licenses" ? (
        <div className="space-y-6">
          <QueryState isLoading={licensesQuery.isLoading} isError={licensesQuery.isError} error={licensesQuery.error} />
          <SectionCard title="Assigned Licenses">
            {licenses.length === 0 ? <div className="text-sm text-slate-500">No direct licenses found.</div> : null}
            {licenses.map((license: UserAdminLicense) => (
              <div key={license.sku_id} className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="font-medium text-slate-900">{license.display_name || license.sku_part_number || license.sku_id}</div>
                <div className="mt-1 text-sm text-slate-500">{license.sku_part_number || license.sku_id}</div>
              </div>
            ))}
          </SectionCard>
          <SectionCard title="Manage Licenses">
            <select value={selectedLicenseId} onChange={(event) => setSelectedLicenseId(event.target.value)} className={inputClass()}>
              <option value="">Select a license</option>
              {(capabilities?.license_catalog || []).map((license) => (
                <option key={license.sku_id} value={license.sku_id}>
                  {license.display_name || license.sku_part_number}
                </option>
              ))}
            </select>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className={buttonClass("primary", !selectedLicenseId)}
                disabled={!selectedLicenseId}
                onClick={() =>
                  queueAction(
                    "assign_license",
                    { sku_id: selectedLicenseId },
                    "Assign the selected license to this user.",
                  )
                }
              >
                Review License Assignment
              </button>
              <button
                type="button"
                className={buttonClass("danger", !selectedLicenseId)}
                disabled={!selectedLicenseId}
                onClick={() =>
                  queueAction(
                    "remove_license",
                    { sku_id: selectedLicenseId },
                    "Remove the selected license from this user.",
                  )
                }
              >
                Review License Removal
              </button>
            </div>
          </SectionCard>
        </div>
      ) : null}

      {selectedTab === "roles" ? (
        <div className="space-y-6">
          <QueryState isLoading={rolesQuery.isLoading} isError={rolesQuery.isError} error={rolesQuery.error} />
          <SectionCard title="Direct Directory Roles">
            {roles.length === 0 ? <div className="text-sm text-slate-500">No direct directory roles found.</div> : null}
            {roles.map((role: UserAdminRole) => (
              <div key={role.id} className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="font-medium text-slate-900">{role.display_name}</div>
                <div className="mt-1 text-sm text-slate-500">{role.description || role.id}</div>
              </div>
            ))}
          </SectionCard>
          <SectionCard title="Manage Roles">
            <select value={selectedRoleId} onChange={(event) => setSelectedRoleId(event.target.value)} className={inputClass()}>
              <option value="">Select a directory role</option>
              {(capabilities?.role_catalog || []).map((role) => (
                <option key={role.id} value={role.id}>
                  {role.display_name}
                </option>
              ))}
            </select>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className={buttonClass("primary", !selectedRoleId)}
                disabled={!selectedRoleId}
                onClick={() =>
                  queueAction(
                    "add_directory_role",
                    { role_id: selectedRoleId },
                    "Add a direct directory role assignment for this user.",
                  )
                }
              >
                Review Role Add
              </button>
              <button
                type="button"
                className={buttonClass("danger", !selectedRoleId)}
                disabled={!selectedRoleId}
                onClick={() =>
                  queueAction(
                    "remove_directory_role",
                    { role_id: selectedRoleId },
                    "Remove a direct directory role assignment from this user.",
                  )
                }
              >
                Review Role Removal
              </button>
            </div>
          </SectionCard>
        </div>
      ) : null}

      {selectedTab === "mailbox" ? (
        <div className="space-y-6">
          <QueryState isLoading={mailboxQuery.isLoading} isError={mailboxQuery.isError} error={mailboxQuery.error} />
          {mailbox ? (
            <>
              <SectionCard title="Mailbox">
                <DetailRow label="Primary Address" value={mailbox.primary_address} />
                <DetailRow label="Mailbox Type" value={mailbox.mailbox_type} />
                <DetailRow label="Forwarding Address" value={mailbox.forwarding_address} />
                <DetailRow label="Delegate Delivery Mode" value={mailbox.delegate_delivery_mode} />
                <DetailRow label="Automatic Replies" value={mailbox.automatic_replies_status} />
                <div>
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Aliases</div>
                  <SummaryList items={mailbox.aliases} />
                </div>
              </SectionCard>
              <SectionCard title="Mailbox Management">
                <p className="text-sm text-slate-600">{mailbox.note || "Mailbox management actions will appear here when the provider is ready."}</p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" disabled={!canManageMailbox} className={buttonClass("secondary", !canManageMailbox)}>
                    Add Alias
                  </button>
                  <button type="button" disabled={!canManageMailbox} className={buttonClass("secondary", !canManageMailbox)}>
                    Remove Alias
                  </button>
                  <button type="button" disabled={!canManageMailbox} className={buttonClass("secondary", !canManageMailbox)}>
                    Set Forwarding
                  </button>
                  <button type="button" disabled={!canManageMailbox} className={buttonClass("secondary", !canManageMailbox)}>
                    Convert Mailbox
                  </button>
                </div>
              </SectionCard>
            </>
          ) : null}
        </div>
      ) : null}

      {selectedTab === "devices" ? (
        <div className="space-y-6">
          <QueryState isLoading={devicesQuery.isLoading} isError={devicesQuery.isError} error={devicesQuery.error} />
          <SectionCard title="Managed Devices">
            {devices.length === 0 ? <div className="text-sm text-slate-500">No managed devices found for this user.</div> : null}
            {devices.map((device: UserAdminDevice) => (
              <div key={device.id} className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="font-medium text-slate-900">{device.device_name || device.id}</div>
                    <div className="mt-1 text-sm text-slate-500">
                      {device.operating_system} {device.operating_system_version} | {device.compliance_state || "Unknown compliance"}
                    </div>
                    <div className="mt-1 text-sm text-slate-500">Last sync: {formatDateTime(device.last_sync_date_time)}</div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className={buttonClass("secondary")}
                      onClick={() => queueAction("device_sync", { device_ids: [device.id] }, "Request an Intune device sync for this device.")}
                    >
                      Sync
                    </button>
                    <button
                      type="button"
                      className={buttonClass("danger")}
                      onClick={() => queueAction("device_retire", { device_ids: [device.id] }, "Retire this device from management.")}
                    >
                      Retire
                    </button>
                    <button
                      type="button"
                      className={buttonClass("danger")}
                      onClick={() => queueAction("device_wipe", { device_ids: [device.id] }, "Wipe this device through device management.")}
                    >
                      Wipe
                    </button>
                    <button
                      type="button"
                      className={buttonClass("danger")}
                      onClick={() => queueAction("device_remote_lock", { device_ids: [device.id] }, "Send a remote lock command to this device.")}
                    >
                      Remote Lock
                    </button>
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-[1fr_auto]">
                  <input
                    value={devicePrimaryUserId}
                    onChange={(event) => setDevicePrimaryUserId(event.target.value)}
                    className={inputClass()}
                    placeholder="Primary user object ID"
                  />
                  <button
                    type="button"
                    className={buttonClass("secondary", !devicePrimaryUserId)}
                    disabled={!devicePrimaryUserId}
                    onClick={() =>
                      queueAction(
                        "device_reassign_primary_user",
                        { device_ids: [device.id], primary_user_id: devicePrimaryUserId },
                        "Reassign the primary user for this device.",
                      )
                    }
                  >
                    Review Primary User Reassignment
                  </button>
                </div>
              </div>
            ))}
          </SectionCard>
        </div>
      ) : null}

      {selectedTab === "activity" ? (
        <div className="space-y-6">
          <QueryState isLoading={activityQuery.isLoading} isError={activityQuery.isError} error={activityQuery.error} />
          <SectionCard title="User Activity">
            {activity.length === 0 ? <div className="text-sm text-slate-500">No recorded admin activity for this user yet.</div> : null}
            {activity.map((entry: UserAdminAuditEntry) => (
              <div key={entry.audit_id} className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium text-slate-900">{ACTION_LABELS[entry.action_type]}</div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{formatDateTime(entry.created_at)}</div>
                </div>
                <div className="mt-1 text-sm text-slate-600">{entry.actor_name || entry.actor_email}</div>
                <div className="mt-2 text-sm text-slate-700">Params: {stringifySummary(entry.params_summary)}</div>
                <div className="mt-1 text-sm text-slate-700">Result: {stringifySummary(entry.after_summary)}</div>
                {entry.error ? <div className="mt-1 text-sm text-red-700">Error: {entry.error}</div> : null}
              </div>
            ))}
          </SectionCard>
        </div>
      ) : null}

      {selectedTab === "exit" ? <ExitWorkflowPanel user={user} /> : null}
    </div>
  );
}

function UserDetailDrawer({
  mode,
  user,
  capabilities,
  onClose,
  onQueueAction,
}: {
  mode: DirectoryUsersPageMode;
  user: AzureDirectoryObject;
  capabilities?: UserAdminCapabilities;
  onClose: () => void;
  onQueueAction: (action: PendingAction) => void;
}) {
  const [drawerWidth, setDrawerWidth] = useState(() => clampDrawerWidth(DEFAULT_DRAWER_WIDTH));
  const [isResizing, setIsResizing] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleResize = () => {
      setDrawerWidth((current) => (isExpanded ? getExpandedDrawerWidth() : clampDrawerWidth(current)));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [isExpanded]);

  useEffect(() => {
    if (!isResizing) return undefined;

    const previousUserSelect = document.body.style.userSelect;
    const previousCursor = document.body.style.cursor;
    const updateWidth = (clientX: number) => {
      setDrawerWidth(clampDrawerWidth(window.innerWidth - clientX));
    };

    const handlePointerMove = (event: PointerEvent) => {
      event.preventDefault();
      updateWidth(event.clientX);
    };

    const handleMouseMove = (event: MouseEvent) => {
      event.preventDefault();
      updateWidth(event.clientX);
    };

    const stopResizing = () => setIsResizing(false);

    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("pointerup", stopResizing);
    window.addEventListener("mouseup", stopResizing);

    return () => {
      document.body.style.userSelect = previousUserSelect;
      document.body.style.cursor = previousCursor;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("pointerup", stopResizing);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [isResizing]);

  function handleResizeStart(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setIsExpanded(false);
    setIsResizing(true);
  }

  function toggleExpanded() {
    setIsExpanded((current) => {
      const next = !current;
      setDrawerWidth(next ? getExpandedDrawerWidth() : clampDrawerWidth(DEFAULT_DRAWER_WIDTH));
      return next;
    });
  }

  const portalUrl = `https://portal.azure.com/#view/Microsoft_AAD_IAM/UserDetailsMenuBlade/~/Profile/userId/${user.id}`;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/35" onClick={onClose}>
      <aside
        className="relative flex h-full max-w-full flex-col overflow-hidden bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        style={{ width: `${drawerWidth}px` }}
      >
        <div
          role="separator"
          aria-label="Resize user detail drawer"
          aria-orientation="vertical"
          className={[
            "absolute inset-y-0 left-0 z-10 w-3 -translate-x-1/2 cursor-col-resize touch-none",
            isResizing ? "bg-blue-200/70" : "bg-transparent hover:bg-slate-200/60",
          ].join(" ")}
          onPointerDown={handleResizeStart}
          onDoubleClick={() => {
            setIsExpanded(false);
            setDrawerWidth(clampDrawerWidth(DEFAULT_DRAWER_WIDTH));
          }}
        >
          <div className="absolute left-1/2 top-1/2 h-14 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-300" />
        </div>

        <div className="border-b border-slate-200 px-6 py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-sky-100 text-base font-bold text-sky-700">
                {initials(user.display_name) || "?"}
              </div>
              <div className="min-w-0">
                <h2 className="truncate text-xl font-bold text-slate-900">{user.display_name || "—"}</h2>
                <div className="mt-0.5 truncate text-sm text-slate-500">{user.principal_name}</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  <StatusChip enabled={user.enabled ?? null} />
                  <TypeChip userType={user.extra.user_type || "Member"} />
                </div>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <a
                href={portalUrl}
                target="_blank"
                rel="noreferrer"
                onClick={(event) => event.stopPropagation()}
                className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 transition hover:bg-sky-100"
              >
                Open in Azure Portal
              </a>
              <button type="button" onClick={toggleExpanded} className={buttonClass("secondary")}>
                {isExpanded ? "Restore" : "Expand"}
              </button>
              <button type="button" onClick={onClose} className={buttonClass("secondary")}>
                Close
              </button>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {mode === "primary" ? (
            <PrimaryUserDrawerContent user={user} capabilities={capabilities} onQueueAction={onQueueAction} />
          ) : (
            <AzureUserDrawerContent user={user} />
          )}
        </div>
      </aside>
    </div>
  );
}

export default function DirectoryUsersPage({ mode }: { mode: DirectoryUsersPageMode }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState(searchParams.get("search") || "");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [licenseFilter, setLicenseFilter] = useState<LicenseFilter>("all");
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>("all");
  const [syncFilter, setSyncFilter] = useState<SyncFilter>("all");
  const [directoryFilter, setDirectoryFilter] = useState("");
  const [selectedUser, setSelectedUser] = useState<AzureDirectoryObject | null>(null);
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [bulkActionType, setBulkActionType] = useState<UserAdminActionType>("disable_sign_in");
  const [bulkUsageLocation, setBulkUsageLocation] = useState("");
  const [bulkGroupId, setBulkGroupId] = useState("");
  const [bulkLicenseId, setBulkLicenseId] = useState("");
  const [bulkRoleId, setBulkRoleId] = useState("");
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeJobResults, setActiveJobResults] = useState<UserAdminJobResult[] | null>(null);
  const [lastHandledJobId, setLastHandledJobId] = useState<string | null>(null);
  const { sortKey, sortDir, toggleSort } = useTableSort<UserColKey>("display_name");

  useEffect(() => {
    const nextSearch = searchParams.get("search") || "";
    if (nextSearch !== search) {
      setSearch(nextSearch);
    }
  }, [search, searchParams]);

  const { data: me } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.getMe(),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  const { data: capabilities } = useQuery<UserAdminCapabilities>({
    queryKey: ["user-admin", "capabilities"],
    queryFn: () => api.getUserAdminCapabilities(),
    enabled: mode === "primary",
    staleTime: 5 * 60 * 1000,
  });

  const { data: users = [], isLoading, isError, error } = useQuery<AzureDirectoryObject[]>({
    queryKey: ["directory", "users", mode, { search }],
    queryFn: () => api.getAzureUsers(search),
    refetchInterval: 60_000,
  });

  const { data: auditEntries = [] } = useQuery<UserAdminAuditEntry[]>({
    queryKey: ["user-admin", "audit"],
    queryFn: () => api.getUserAdminAudit(25),
    enabled: mode === "primary",
    refetchInterval: activeJobId ? 15_000 : 60_000,
  });

  const createJobMutation = useMutation({
    mutationFn: (body: { action_type: UserAdminActionType; target_user_ids: string[]; params: Record<string, unknown> }) =>
      api.createUserAdminJob(body),
    onSuccess: (job) => {
      setActiveJobId(job.job_id);
      setActiveJobResults(null);
      setLastHandledJobId(null);
      setSelectedUserIds([]);
    },
  });

  const activeJobQuery = useQuery<UserAdminJobStatus>({
    queryKey: ["user-admin", "job", activeJobId],
    queryFn: () => api.getUserAdminJob(activeJobId as string),
    enabled: !!activeJobId,
    refetchInterval: (query) => {
      const job = query.state.data as UserAdminJobStatus | undefined;
      return job && ["completed", "failed"].includes(job.status) ? false : 2000;
    },
  });

  useEffect(() => {
    const job = activeJobQuery.data;
    if (!activeJobId || !job || !job.results_ready || activeJobResults) return;
    let cancelled = false;
    void api.getUserAdminJobResults(activeJobId).then((results) => {
      if (!cancelled) {
        setActiveJobResults(results);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [activeJobId, activeJobQuery.data, activeJobResults]);

  useEffect(() => {
    const job = activeJobQuery.data;
    if (!job || !activeJobId || lastHandledJobId === activeJobId) return;
    if (!["completed", "failed"].includes(job.status)) return;
    setLastHandledJobId(activeJobId);
    void queryClient.invalidateQueries({ queryKey: ["directory", "users"] });
    void queryClient.invalidateQueries({ queryKey: ["user-admin"] });
  }, [activeJobId, activeJobQuery.data, lastHandledJobId, queryClient]);

  const totalCount = users.length;
  const enabledCount = users.filter((user) => user.enabled === true).length;
  const disabledCount = users.filter((user) => user.enabled === false).length;
  const licensedCount = users.filter(isLicensedUser).length;
  const disabledLicensedCount = users.filter((user) => user.enabled === false && isLicensedUser(user)).length;
  const noSuccess30dCount = users.filter(hasNoSuccessfulSignIn30d).length;
  const memberCount = users.filter((user) => user.extra.user_type !== "Guest").length;
  const guestCount = users.filter((user) => user.extra.user_type === "Guest").length;
  const onPremCount = users.filter(isOnPremSynced).length;
  const directoryOptions = Array.from(new Set(users.map(getDirectoryLabel))).sort();

  function applySummaryPreset(preset: SummaryPresetKey) {
    if (preset === "total") {
      setStatusFilter("all");
      setTypeFilter("all");
      setLicenseFilter("all");
      setActivityFilter("all");
      setSyncFilter("all");
      return;
    }
    if (preset === "enabled") {
      setStatusFilter("enabled");
      setTypeFilter("all");
      setLicenseFilter("all");
      setActivityFilter("all");
      setSyncFilter("all");
      return;
    }
    if (preset === "disabled") {
      setStatusFilter("disabled");
      setTypeFilter("all");
      setLicenseFilter("all");
      setActivityFilter("all");
      setSyncFilter("all");
      return;
    }
    if (preset === "licensed") {
      setStatusFilter("all");
      setTypeFilter("all");
      setLicenseFilter("licensed");
      setActivityFilter("all");
      setSyncFilter("all");
      return;
    }
    if (preset === "disabled_licensed") {
      setStatusFilter("disabled");
      setTypeFilter("all");
      setLicenseFilter("licensed");
      setActivityFilter("all");
      setSyncFilter("all");
      return;
    }
    if (preset === "no_success_30d") {
      setStatusFilter("all");
      setTypeFilter("all");
      setLicenseFilter("all");
      setActivityFilter("no_success_30d");
      setSyncFilter("all");
      return;
    }
    if (preset === "members") {
      setStatusFilter("all");
      setTypeFilter("member");
      setLicenseFilter("all");
      setActivityFilter("all");
      setSyncFilter("all");
      return;
    }
    if (preset === "guests") {
      setStatusFilter("all");
      setTypeFilter("guest");
      setLicenseFilter("all");
      setActivityFilter("all");
      setSyncFilter("all");
      return;
    }
    setStatusFilter("all");
    setTypeFilter("all");
    setLicenseFilter("all");
    setActivityFilter("all");
    setSyncFilter("on_prem_synced");
  }

  function activeSummaryPreset(): SummaryPresetKey | null {
    if (
      statusFilter === "all" &&
      typeFilter === "all" &&
      licenseFilter === "all" &&
      activityFilter === "all" &&
      syncFilter === "all"
    ) {
      return "total";
    }
    if (
      statusFilter === "enabled" &&
      typeFilter === "all" &&
      licenseFilter === "all" &&
      activityFilter === "all" &&
      syncFilter === "all"
    ) {
      return "enabled";
    }
    if (
      statusFilter === "disabled" &&
      typeFilter === "all" &&
      licenseFilter === "all" &&
      activityFilter === "all" &&
      syncFilter === "all"
    ) {
      return "disabled";
    }
    if (
      statusFilter === "all" &&
      typeFilter === "all" &&
      licenseFilter === "licensed" &&
      activityFilter === "all" &&
      syncFilter === "all"
    ) {
      return "licensed";
    }
    if (
      statusFilter === "disabled" &&
      typeFilter === "all" &&
      licenseFilter === "licensed" &&
      activityFilter === "all" &&
      syncFilter === "all"
    ) {
      return "disabled_licensed";
    }
    if (
      statusFilter === "all" &&
      typeFilter === "all" &&
      licenseFilter === "all" &&
      activityFilter === "no_success_30d" &&
      syncFilter === "all"
    ) {
      return "no_success_30d";
    }
    if (
      statusFilter === "all" &&
      typeFilter === "member" &&
      licenseFilter === "all" &&
      activityFilter === "all" &&
      syncFilter === "all"
    ) {
      return "members";
    }
    if (
      statusFilter === "all" &&
      typeFilter === "guest" &&
      licenseFilter === "all" &&
      activityFilter === "all" &&
      syncFilter === "all"
    ) {
      return "guests";
    }
    if (
      statusFilter === "all" &&
      typeFilter === "all" &&
      licenseFilter === "all" &&
      activityFilter === "all" &&
      syncFilter === "on_prem_synced"
    ) {
      return "on_prem_synced";
    }
    return null;
  }

  const activeSummary = activeSummaryPreset();

  const filtered = sortRows<AzureDirectoryObject>(
    users.filter((user) => {
      if (statusFilter === "enabled" && user.enabled !== true) return false;
      if (statusFilter === "disabled" && user.enabled !== false) return false;
      if (typeFilter === "member" && user.extra.user_type === "Guest") return false;
      if (typeFilter === "guest" && user.extra.user_type !== "Guest") return false;
      if (licenseFilter === "licensed" && !isLicensedUser(user)) return false;
      if (activityFilter === "no_success_30d" && !hasNoSuccessfulSignIn30d(user)) return false;
      if (syncFilter === "on_prem_synced" && !isOnPremSynced(user)) return false;
      if (directoryFilter && getDirectoryLabel(user) !== directoryFilter) return false;
      return true;
    }),
    sortKey,
    sortDir,
    (user, key) => {
      if (key === "department") return user.extra.department;
      if (key === "job_title") return user.extra.job_title;
      if (key === "created_datetime") return user.extra.created_datetime;
      if (key === "on_prem_domain") return getDirectoryLabel(user);
      if (key === "is_licensed") return isLicensedUser(user) ? 1 : 0;
      if (key === "last_successful_utc") return lastSuccessfulIso(user);
      return (user as unknown as Record<string, unknown>)[key] as string;
    },
  );

  const filteredExportParams = {
    search,
    status: statusFilter,
    type: typeFilter,
    license: licenseFilter,
    activity: activityFilter,
    sync: syncFilter,
    directory: directoryFilter,
    scope: "filtered" as const,
  };
  const allExportParams = { scope: "all" as const };

  const filterKey = [mode, search, statusFilter, typeFilter, licenseFilter, activityFilter, syncFilter, directoryFilter, sortKey, sortDir].join("|");
  const scroll = useInfiniteScrollCount(filtered.length, 50, filterKey);
  const visibleUsers = filtered.slice(0, scroll.visibleCount);
  const allVisibleSelected = visibleUsers.length > 0 && visibleUsers.every((user) => selectedUserIds.includes(user.id));

  function toggleSelectedUser(userId: string) {
    setSelectedUserIds((current) =>
      current.includes(userId) ? current.filter((item) => item !== userId) : [...current, userId],
    );
  }

  function toggleSelectAllVisible() {
    if (allVisibleSelected) {
      setSelectedUserIds((current) => current.filter((userId) => !visibleUsers.some((user) => user.id === userId)));
      return;
    }
    setSelectedUserIds((current) => {
      const next = [...current];
      for (const user of visibleUsers) {
        if (!next.includes(user.id)) next.push(user.id);
      }
      return next;
    });
  }

  function buildPendingBulkAction(): PendingAction | null {
    if (selectedUserIds.length === 0) return null;

    const selectedUsers = users.filter((user) => selectedUserIds.includes(user.id));
    const targetNames = selectedUsers.map((user) => user.display_name || user.principal_name || user.id);
    const option = BULK_ACTION_OPTIONS.find((item) => item.value === bulkActionType);
    let params: Record<string, unknown> = {};

    if (bulkActionType === "update_usage_location") {
      if (bulkUsageLocation.trim().length !== 2) return null;
      params = { usage_location: bulkUsageLocation.trim().toUpperCase() };
    }
    if (bulkActionType === "add_group_membership" || bulkActionType === "remove_group_membership") {
      if (!bulkGroupId) return null;
      params = { group_id: bulkGroupId };
    }
    if (bulkActionType === "assign_license" || bulkActionType === "remove_license") {
      if (!bulkLicenseId) return null;
      params = { sku_id: bulkLicenseId };
    }
    if (bulkActionType === "add_directory_role" || bulkActionType === "remove_directory_role") {
      if (!bulkRoleId) return null;
      params = { role_id: bulkRoleId };
    }
    if (bulkActionType === "reset_password") {
      params = { force_change_on_next_login: true };
    }

    return {
      actionType: bulkActionType,
      targetUserIds: selectedUserIds,
      targetNames,
      params,
      title: `${ACTION_LABELS[bulkActionType]} for ${selectedUserIds.length} user${selectedUserIds.length === 1 ? "" : "s"}`,
      description: option?.description || "Review the selected action before it is queued.",
      warning: DANGEROUS_ACTIONS.has(bulkActionType)
        ? "This action can change access, credentials, or device state for multiple users. Double-check the target list before submitting."
        : "This action will be queued and recorded in the user-admin audit log.",
    };
  }

  async function confirmPendingAction() {
    if (!pendingAction) return;
    await createJobMutation.mutateAsync({
      action_type: pendingAction.actionType,
      target_user_ids: pendingAction.targetUserIds,
      params: pendingAction.params,
    });
    setPendingAction(null);
  }

  useEffect(() => {
    const targetUserId = searchParams.get("userId");
    if (!targetUserId) return;
    const matched = users.find((user) => user.id === targetUserId);
    if (matched && matched.id !== selectedUser?.id) {
      setSelectedUser(matched);
    }
  }, [searchParams, selectedUser?.id, users]);

  if (isLoading) {
    return <div className="text-sm text-slate-500">Loading Entra users...</div>;
  }

  if (isError || !users) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load users: {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }

  function updateRouteParams(next: { search?: string; userId?: string | null }) {
    setSearchParams((currentParams) => {
      const params = new URLSearchParams(currentParams);
      if (next.search !== undefined) {
        if (next.search) params.set("search", next.search);
        else params.delete("search");
      }
      if (next.userId === null) {
        params.delete("userId");
      } else if (next.userId) {
        params.set("userId", next.userId);
      }
      return params;
    }, { replace: true });
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Users</h1>
        <p className="mt-1 text-sm text-slate-500">
          {mode === "primary"
            ? "Entra user directory and admin workspace for identity, license, role, mailbox, and device operations."
            : "Entra user directory — status, department, job title, and account details."}
        </p>
      </div>

      {mode === "primary" && activeJobId && activeJobQuery.data ? <JobProgressCard job={activeJobQuery.data} results={activeJobResults} /> : null}

      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-9">
        <StatCard
          label="Total"
          value={totalCount.toLocaleString()}
          active={activeSummary === "total"}
          onClick={() => applySummaryPreset("total")}
        />
        <StatCard
          label="Enabled"
          value={enabledCount.toLocaleString()}
          tone="text-emerald-700"
          active={activeSummary === "enabled"}
          onClick={() => applySummaryPreset("enabled")}
        />
        <StatCard
          label="Disabled"
          value={disabledCount.toLocaleString()}
          tone="text-red-700"
          active={activeSummary === "disabled"}
          onClick={() => applySummaryPreset("disabled")}
        />
        <StatCard
          label="Licensed"
          value={licensedCount.toLocaleString()}
          tone="text-sky-700"
          active={activeSummary === "licensed"}
          onClick={() => applySummaryPreset("licensed")}
        />
        <StatCard
          label="Disabled + Licensed"
          value={disabledLicensedCount.toLocaleString()}
          tone="text-amber-700"
          active={activeSummary === "disabled_licensed"}
          onClick={() => applySummaryPreset("disabled_licensed")}
        />
        <StatCard
          label="No Success 30d"
          value={noSuccess30dCount.toLocaleString()}
          tone="text-rose-700"
          active={activeSummary === "no_success_30d"}
          onClick={() => applySummaryPreset("no_success_30d")}
        />
        <StatCard
          label="Members"
          value={memberCount.toLocaleString()}
          tone="text-sky-700"
          active={activeSummary === "members"}
          onClick={() => applySummaryPreset("members")}
        />
        <StatCard
          label="Guests"
          value={guestCount.toLocaleString()}
          tone="text-amber-700"
          active={activeSummary === "guests"}
          onClick={() => applySummaryPreset("guests")}
        />
        <StatCard
          label="On-Prem Synced"
          value={onPremCount.toLocaleString()}
          tone="text-violet-700"
          active={activeSummary === "on_prem_synced"}
          onClick={() => applySummaryPreset("on_prem_synced")}
        />
      </div>

      <div className="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
        The summary boxes above are clickable filter shortcuts. Use them to jump straight into disabled, licensed, stale-sign-in, guest, or synced account slices.
      </div>

      <div className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <input
            value={search}
            onChange={(event) => {
              const nextValue = event.target.value;
              setSearch(nextValue);
              updateRouteParams({ search: nextValue, userId: null });
            }}
            placeholder="Search name, email, department..."
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="self-center text-xs font-semibold uppercase tracking-wide text-slate-400">Status</span>
          {(["all", "enabled", "disabled"] as StatusFilter[]).map((value) => (
            <button key={value} type="button" onClick={() => setStatusFilter(value)} className={pillClass(statusFilter === value)}>
              {value === "all" ? "All" : value === "enabled" ? "Enabled" : "Disabled"}
            </button>
          ))}
          <span className="mx-2 self-center text-slate-300">|</span>
          <span className="self-center text-xs font-semibold uppercase tracking-wide text-slate-400">Type</span>
          {(["all", "member", "guest"] as TypeFilter[]).map((value) => (
            <button key={value} type="button" onClick={() => setTypeFilter(value)} className={pillClass(typeFilter === value)}>
              {value === "all" ? "All" : value === "member" ? "Members" : "Guests"}
            </button>
          ))}
          <span className="mx-2 self-center text-slate-300">|</span>
          <span className="self-center text-xs font-semibold uppercase tracking-wide text-slate-400">License</span>
          {(["all", "licensed"] as LicenseFilter[]).map((value) => (
            <button key={value} type="button" onClick={() => setLicenseFilter(value)} className={pillClass(licenseFilter === value)}>
              {value === "all" ? "All" : "Licensed"}
            </button>
          ))}
          <span className="mx-2 self-center text-slate-300">|</span>
          <span className="self-center text-xs font-semibold uppercase tracking-wide text-slate-400">Activity</span>
          {(["all", "no_success_30d"] as ActivityFilter[]).map((value) => (
            <button key={value} type="button" onClick={() => setActivityFilter(value)} className={pillClass(activityFilter === value)}>
              {value === "all" ? "All" : "No Success 30d"}
            </button>
          ))}
          <span className="mx-2 self-center text-slate-300">|</span>
          <span className="self-center text-xs font-semibold uppercase tracking-wide text-slate-400">Sync</span>
          {(["all", "on_prem_synced"] as SyncFilter[]).map((value) => (
            <button key={value} type="button" onClick={() => setSyncFilter(value)} className={pillClass(syncFilter === value)}>
              {value === "all" ? "All" : "On-Prem Synced"}
            </button>
          ))}
          {directoryOptions.length > 1 ? (
            <>
              <span className="mx-2 self-center text-slate-300">|</span>
              <span className="self-center text-xs font-semibold uppercase tracking-wide text-slate-400">Directory</span>
              <select
                value={directoryFilter}
                onChange={(event) => setDirectoryFilter(event.target.value)}
                className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 hover:border-slate-400"
              >
                <option value="">All</option>
                {directoryOptions.map((directory) => (
                  <option key={directory} value={directory}>
                    {directory}
                  </option>
                ))}
              </select>
            </>
          ) : null}
        </div>
        {mode === "primary" && me?.can_manage_users ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="self-center text-xs font-semibold uppercase tracking-wide text-slate-400">Exports</span>
            <a href={api.exportUserAdminUsersCsv(filteredExportParams)} className={buttonClass("secondary")}>
              Export Filtered CSV
            </a>
            <a href={api.exportUserAdminUsersExcel(filteredExportParams)} className={buttonClass("secondary")}>
              Export Filtered XLSX
            </a>
            <a href={api.exportUserAdminUsersCsv(allExportParams)} className={buttonClass("secondary")}>
              Export All CSV
            </a>
            <a href={api.exportUserAdminUsersExcel(allExportParams)} className={buttonClass("secondary")}>
              Export All XLSX
            </a>
          </div>
        ) : null}
      </div>

      {mode === "primary" && me?.can_manage_users ? (
        <section className="sticky top-0 z-20 rounded-2xl border border-slate-200 bg-white/95 p-4 shadow-sm backdrop-blur">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Bulk Actions</div>
              <div className="mt-1 text-sm text-slate-700">
                {selectedUserIds.length} selected. Bulk actions are the fastest path for identity admin work on it-app.
              </div>
            </div>
            <div className="flex flex-1 flex-col gap-3 xl:flex-row xl:items-center xl:justify-end">
              <select value={bulkActionType} onChange={(event) => setBulkActionType(event.target.value as UserAdminActionType)} className={inputClass()}>
                {BULK_ACTION_OPTIONS.filter((item) => capabilities?.supported_actions.includes(item.value) ?? true).map((item) => (
                  <option key={item.value} value={item.value}>
                    {ACTION_LABELS[item.value]}
                  </option>
                ))}
              </select>
              {bulkActionType === "update_usage_location" ? (
                <input
                  value={bulkUsageLocation}
                  onChange={(event) => setBulkUsageLocation(event.target.value.toUpperCase())}
                  className={inputClass()}
                  maxLength={2}
                  placeholder="US"
                />
              ) : null}
              {bulkActionType === "add_group_membership" || bulkActionType === "remove_group_membership" ? (
                <select value={bulkGroupId} onChange={(event) => setBulkGroupId(event.target.value)} className={inputClass()}>
                  <option value="">Select a group</option>
                  {(capabilities?.group_catalog || []).map((group) => (
                    <option key={group.id} value={group.id}>
                      {group.display_name}
                    </option>
                  ))}
                </select>
              ) : null}
              {bulkActionType === "assign_license" || bulkActionType === "remove_license" ? (
                <select value={bulkLicenseId} onChange={(event) => setBulkLicenseId(event.target.value)} className={inputClass()}>
                  <option value="">Select a license</option>
                  {(capabilities?.license_catalog || []).map((license) => (
                    <option key={license.sku_id} value={license.sku_id}>
                      {license.display_name || license.sku_part_number}
                    </option>
                  ))}
                </select>
              ) : null}
              {bulkActionType === "add_directory_role" || bulkActionType === "remove_directory_role" ? (
                <select value={bulkRoleId} onChange={(event) => setBulkRoleId(event.target.value)} className={inputClass()}>
                  <option value="">Select a role</option>
                  {(capabilities?.role_catalog || []).map((role) => (
                    <option key={role.id} value={role.id}>
                      {role.display_name}
                    </option>
                  ))}
                </select>
              ) : null}
              <button
                type="button"
                className={buttonClass(DANGEROUS_ACTIONS.has(bulkActionType) ? "danger" : "primary", !buildPendingBulkAction())}
                disabled={!buildPendingBulkAction()}
                onClick={() => setPendingAction(buildPendingBulkAction())}
              >
                Review Bulk Action
              </button>
            </div>
          </div>
        </section>
      ) : null}

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-4 py-3 text-sm text-slate-500">
          Showing <span className="font-semibold text-slate-900">{visibleUsers.length.toLocaleString()}</span> of{" "}
          {filtered.length.toLocaleString()} filtered
          <span className="text-slate-400"> | </span>
          {totalCount.toLocaleString()} total users
        </div>
        <div className="max-h-[70vh] overflow-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                {mode === "primary" && me?.can_manage_users ? (
                  <th className="w-12 px-4 py-3">
                    <input
                      type="checkbox"
                      aria-label="Select visible users"
                      checked={allVisibleSelected}
                      onChange={toggleSelectAllVisible}
                    />
                  </th>
                ) : null}
                <SortHeader col="display_name" label="Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="principal_name" label="UPN" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="mail" label="Email" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="department" label="Department" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="job_title" label="Job Title" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="is_licensed" label="Licensed" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="last_successful_utc" label="Last Successful Sign-In" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="on_prem_domain" label="Directory" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Type</th>
                <SortHeader col="created_datetime" label="Created" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={mode === "primary" && me?.can_manage_users ? 12 : 11} className="px-4 py-8 text-center text-sm text-slate-500">
                    No users matched the current filters.
                  </td>
                </tr>
              ) : null}
              {visibleUsers.map((user, index) => (
                <tr
                  key={user.id}
                  onClick={() => {
                    setSelectedUser(user);
                    updateRouteParams({ search, userId: user.id });
                  }}
                  className={[
                    "cursor-pointer transition hover:bg-sky-50/60",
                    selectedUser?.id === user.id ? "bg-sky-50" : index % 2 === 0 ? "bg-white" : "bg-slate-50/50",
                  ].join(" ")}
                >
                  {mode === "primary" && me?.can_manage_users ? (
                    <td className="px-4 py-3" onClick={(event) => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${user.display_name}`}
                        checked={selectedUserIds.includes(user.id)}
                        onChange={() => toggleSelectedUser(user.id)}
                      />
                    </td>
                  ) : null}
                  <td className="px-4 py-3 font-medium text-slate-900">{user.display_name}</td>
                  <td className="max-w-[280px] truncate px-4 py-3 text-xs text-slate-500" title={user.principal_name}>{user.principal_name}</td>
                  <td className="max-w-[280px] truncate px-4 py-3 text-slate-700" title={user.mail || ""}>{user.mail || "—"}</td>
                  <td className="px-4 py-3 text-slate-700">{user.extra.department || "—"}</td>
                  <td className="px-4 py-3 text-slate-700">{user.extra.job_title || "—"}</td>
                  <td className="px-4 py-3 text-slate-700">{isLicensedUser(user) ? `Yes${licenseCount(user) > 0 ? ` (${licenseCount(user)})` : ""}` : "No"}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-700">{lastSuccessfulText(user)}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">{getDirectoryLabel(user)}</td>
                  <td className="px-4 py-3">
                    <StatusChip enabled={user.enabled ?? null} />
                  </td>
                  <td className="px-4 py-3">
                    <TypeChip userType={user.extra.user_type || "Member"} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-700">{formatDate(user.extra.created_datetime)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {scroll.hasMore ? (
            <div ref={scroll.sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
              Showing {visibleUsers.length.toLocaleString()} of {filtered.length.toLocaleString()} users — scroll for more
            </div>
          ) : null}
        </div>
      </section>

      {mode === "primary" ? <AuditPanel entries={auditEntries} /> : null}

      {selectedUser ? (
        <UserDetailDrawer
          mode={mode}
          user={selectedUser}
          capabilities={capabilities}
          onClose={() => {
            setSelectedUser(null);
            updateRouteParams({ userId: null });
          }}
          onQueueAction={(action) => setPendingAction(action)}
        />
      ) : null}

      {pendingAction ? (
        <ActionConfirmModal
          action={pendingAction}
          onCancel={() => setPendingAction(null)}
          onConfirm={confirmPendingAction}
          isSubmitting={createJobMutation.isPending}
        />
      ) : null}
    </div>
  );
}
