import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type AzureDirectoryObject } from "../lib/api.ts";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import { AzureSecurityLaneHero } from "../components/AzureSecurityLane.tsx";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";
import {
  buildSecurityFindingExceptionIndex,
  DIRECTORY_USER_EXCEPTION_SCOPE,
  hasSecurityFindingException,
} from "../lib/securityFindingExceptions.ts";

// ── Helpers ───────────────────────────────────────────────────────────────────

function daysSince(iso: string): number {
  if (!iso) return 0;
  const dt = new Date(iso);
  if (isNaN(dt.getTime())) return 0;
  return Math.floor((Date.now() - dt.getTime()) / 86_400_000);
}

function formatDate(iso: string): string {
  if (!iso) return "—";
  const dt = new Date(iso);
  return isNaN(dt.getTime())
    ? "—"
    : dt.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No refresh recorded";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function portalUrl(id: string): string {
  return `https://portal.azure.com/#view/Microsoft_AAD_IAM/UserDetailsMenuBlade/~/Profile/userId/${encodeURIComponent(id)}`;
}

function getDirectoryLabel(user: AzureDirectoryObject): string {
  if (user.extra.on_prem_domain) return user.extra.on_prem_domain;
  if (user.extra.user_type === "Guest") return "External";
  return "Cloud";
}

function accountClassLabel(user: AzureDirectoryObject): string {
  if (user.extra.account_class === "shared_or_service") return "Shared / Service";
  if (user.extra.account_class === "guest_external") return "Guest";
  if (user.extra.account_class === "person_synced") return "Person (On-Prem Synced)";
  return "Person";
}

function priorityScore(user: AzureDirectoryObject): number {
  return Number(user.extra.priority_score || 0);
}

function isSharedOrService(user: AzureDirectoryObject): boolean {
  return user.extra.account_class === "shared_or_service";
}

function missingFieldLabel(user: AzureDirectoryObject): string {
  return user.extra.missing_profile_fields || "";
}

// ── Guide card ────────────────────────────────────────────────────────────────

function Guide({
  icon,
  issue,
  why,
  action,
  tone = "blue",
}: {
  icon: string;
  issue: string;
  why: string;
  action: string;
  tone?: "amber" | "red" | "blue" | "violet";
}) {
  const colors = {
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    red:   "border-red-200 bg-red-50 text-red-900",
    blue:  "border-sky-200 bg-sky-50 text-sky-900",
    violet:"border-violet-200 bg-violet-50 text-violet-900",
  };
  return (
    <div className={`rounded-xl border px-4 py-4 text-sm ${colors[tone]}`}>
      <div className="font-semibold">{icon} {issue}</div>
      <div className="mt-1 opacity-80">{why}</div>
      <div className="mt-2 font-medium">→ {action}</div>
    </div>
  );
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({
  id,
  title,
  count,
  children,
  defaultOpen = true,
}: {
  id: string;
  title: string;
  count: number;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section id={id} className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-4 text-left"
      >
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
            count === 0 ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"
          }`}>
            {count.toLocaleString()}
          </span>
        </div>
        <span className="text-slate-400 text-lg leading-none">{open ? "−" : "+"}</span>
      </button>
      {open ? <div className="border-t border-slate-200 px-5 pb-5 pt-4 space-y-4">{children}</div> : null}
    </section>
  );
}

// ── Manage link ───────────────────────────────────────────────────────────────

function ManageLink({ id }: { id: string }) {
  return (
    <a
      href={portalUrl(id)}
      target="_blank"
      rel="noreferrer"
      onClick={(e) => e.stopPropagation()}
      className="rounded-lg border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs font-semibold text-sky-700 hover:bg-sky-100 transition whitespace-nowrap"
    >
      Manage in Entra
    </a>
  );
}

// ── Section 1: Disabled accounts ─────────────────────────────────────────────

type DisabledSortKey = "display_name" | "principal_name" | "directory" | "user_type";

function DisabledSection({ users }: { users: AzureDirectoryObject[] }) {
  const disabled = users.filter((u) => u.enabled === false);
  const { sortKey, sortDir, toggleSort } = useTableSort<DisabledSortKey>("display_name");
  const sorted = sortRows(disabled, sortKey, sortDir, (u, key) => {
    if (key === "directory") return getDirectoryLabel(u);
    if (key === "user_type") return u.extra.user_type;
    return (u as unknown as Record<string, unknown>)[key] as string;
  });
  const scroll = useInfiniteScrollCount(sorted.length, 50, `disabled|${sortKey}|${sortDir}`);
  const visible = sorted.slice(0, scroll.visibleCount);

  return (
    <Section id="disabled" title="Disabled Accounts" count={disabled.length}>
      <Guide
        tone="amber"
        icon="⚠"
        issue="These accounts are disabled in Entra ID."
        why="Disabled accounts that are no longer needed clutter the directory and represent an unnecessary attack surface. Cloud-only accounts can be deleted directly in Entra. Accounts synced from on-premises AD must be managed from the source directory."
        action="Review each account. Delete unused cloud accounts via the Manage in Entra link. For on-prem synced accounts, remove or disable from the source Active Directory."
      />
      {disabled.length === 0 ? (
        <p className="text-sm text-emerald-700 font-medium">✓ No disabled accounts found.</p>
      ) : (
        <div className="overflow-auto rounded-xl border border-slate-200">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <SortHeader col="display_name" label="Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="principal_name" label="UPN" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="directory" label="Directory" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="user_type" label="Type" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((u, idx) => (
                <tr key={u.id} className={idx % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                  <td className="px-4 py-2 font-medium text-slate-900">{u.display_name}</td>
                  <td className="px-4 py-2 text-xs text-slate-500 font-mono">{u.principal_name}</td>
                  <td className="px-4 py-2 text-slate-600 text-xs">{getDirectoryLabel(u)}</td>
                    <td className="px-4 py-2 text-slate-600">{accountClassLabel(u)}</td>
                  <td className="px-4 py-2"><ManageLink id={u.id} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {scroll.hasMore ? (
            <div ref={scroll.sentinelRef} className="border-t border-slate-200 px-4 py-2 text-center text-xs text-slate-400">
              Showing {visible.length} of {disabled.length} — scroll for more
            </div>
          ) : null}
        </div>
      )}
    </Section>
  );
}

// ── Section 2: Stale passwords ────────────────────────────────────────────────

type StaleSortKey = "display_name" | "principal_name" | "department" | "last_password_change" | "days";

function StalePasswordSection({ users, threshold }: { users: AzureDirectoryObject[]; threshold: number }) {
  const stale = users.filter((u) => {
    if (!u.enabled) return false;
    if (u.extra.on_prem_sync === "true") return false;  // on-prem passwords managed in AD
    if (u.extra.user_type === "Guest") return false;
    const pw = u.extra.last_password_change;
    if (!pw) return false;
    return daysSince(pw) >= threshold;
  });
  const { sortKey, sortDir, toggleSort } = useTableSort<StaleSortKey>("days", "desc");
  const sorted = sortRows(stale, sortKey, sortDir, (u, key) => {
    if (key === "department") return u.extra.department;
    if (key === "last_password_change") return u.extra.last_password_change;
    if (key === "days") return daysSince(u.extra.last_password_change);
    return (u as unknown as Record<string, unknown>)[key] as string;
  });
  const scroll = useInfiniteScrollCount(sorted.length, 50, `stale|${sortKey}|${sortDir}|${threshold}`);
  const visible = sorted.slice(0, scroll.visibleCount);

  return (
    <Section id="stale-passwords" title="Stale Passwords" count={stale.length}>
      <Guide
        tone="red"
        icon="🔑"
        issue={`Cloud accounts with no password change in ${threshold}+ days.`}
        why="Old, unchanged passwords are a primary credential compromise risk. On-prem synced accounts are excluded here since their passwords are managed in Active Directory. Guest accounts use their home-tenant credentials and are excluded."
        action="Enforce a password reset via Entra ID or your password policy. Consider enabling SSPR (Self-Service Password Reset) or requiring MFA to mitigate credential risk."
      />
      {stale.length === 0 ? (
        <p className="text-sm text-emerald-700 font-medium">✓ No accounts with stale passwords found.</p>
      ) : (
        <div className="overflow-auto rounded-xl border border-slate-200">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <SortHeader col="display_name" label="Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="principal_name" label="UPN" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="department" label="Department" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="last_password_change" label="Last Changed" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="days" label="Days Since" right sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((u, idx) => {
                const days = daysSince(u.extra.last_password_change);
                const tone = days > 365 ? "text-red-700 font-semibold" : days > 180 ? "text-amber-700 font-semibold" : "text-slate-700";
                return (
                  <tr key={u.id} className={idx % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                    <td className="px-4 py-2 font-medium text-slate-900">{u.display_name}</td>
                    <td className="px-4 py-2 text-xs text-slate-500 font-mono">{u.principal_name}</td>
                    <td className="px-4 py-2 text-slate-600">{u.extra.department || "—"}</td>
                    <td className="px-4 py-2 text-slate-600">{formatDate(u.extra.last_password_change)}</td>
                    <td className={`px-4 py-2 text-right ${tone}`}>{days.toLocaleString()}</td>
                    <td className="px-4 py-2"><ManageLink id={u.id} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {scroll.hasMore ? (
            <div ref={scroll.sentinelRef} className="border-t border-slate-200 px-4 py-2 text-center text-xs text-slate-400">
              Showing {visible.length} of {stale.length} — scroll for more
            </div>
          ) : null}
        </div>
      )}
    </Section>
  );
}

// ── Section 3: Old guest accounts ─────────────────────────────────────────────

type GuestSortKey = "display_name" | "principal_name" | "directory" | "created_datetime" | "days";

function OldGuestSection({ users, threshold }: { users: AzureDirectoryObject[]; threshold: number }) {
  const oldGuests = users.filter((u) => {
    if (u.extra.user_type !== "Guest") return false;
    if (!u.extra.created_datetime) return false;
    return daysSince(u.extra.created_datetime) >= threshold;
  });
  const { sortKey, sortDir, toggleSort } = useTableSort<GuestSortKey>("days", "desc");
  const sorted = sortRows(oldGuests, sortKey, sortDir, (u, key) => {
    if (key === "directory") return getDirectoryLabel(u);
    if (key === "created_datetime") return u.extra.created_datetime;
    if (key === "days") return daysSince(u.extra.created_datetime);
    return (u as unknown as Record<string, unknown>)[key] as string;
  });
  const scroll = useInfiniteScrollCount(sorted.length, 50, `guests|${sortKey}|${sortDir}|${threshold}`);
  const visible = sorted.slice(0, scroll.visibleCount);

  return (
    <Section id="old-guests" title="Old Guest Accounts" count={oldGuests.length}>
      <Guide
        tone="violet"
        icon="👤"
        issue={`Guest accounts created ${threshold}+ days ago that may no longer need access.`}
        why="Guest accounts represent external users (vendors, contractors, partners) invited to your Entra tenant. Old guest accounts that are no longer active can be removed to reduce your tenant's external exposure and keep licensing clean."
        action="Verify with account owners whether each external user still needs access. Remove unnecessary guests via the Manage in Entra link. Consider setting an access review policy to automate this."
      />
      {oldGuests.length === 0 ? (
        <p className="text-sm text-emerald-700 font-medium">✓ No old guest accounts found.</p>
      ) : (
        <div className="overflow-auto rounded-xl border border-slate-200">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <SortHeader col="display_name" label="Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="principal_name" label="UPN" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="directory" label="External Tenant" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="created_datetime" label="Invited" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="days" label="Days Old" right sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((u, idx) => {
                const days = daysSince(u.extra.created_datetime);
                const tone = days > 365 ? "text-red-700 font-semibold" : days > 270 ? "text-amber-700 font-semibold" : "text-slate-700";
                return (
                  <tr key={u.id} className={idx % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                    <td className="px-4 py-2 font-medium text-slate-900">{u.display_name}</td>
                    <td className="px-4 py-2 text-xs text-slate-500 font-mono">{u.principal_name}</td>
                    <td className="px-4 py-2 text-slate-600 text-xs">{getDirectoryLabel(u)}</td>
                    <td className="px-4 py-2 text-slate-600">{formatDate(u.extra.created_datetime)}</td>
                    <td className={`px-4 py-2 text-right ${tone}`}>{days.toLocaleString()}</td>
                    <td className="px-4 py-2"><ManageLink id={u.id} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {scroll.hasMore ? (
            <div ref={scroll.sentinelRef} className="border-t border-slate-200 px-4 py-2 text-center text-xs text-slate-400">
              Showing {visible.length} of {oldGuests.length} — scroll for more
            </div>
          ) : null}
        </div>
      )}
    </Section>
  );
}

// ── Section 4: Incomplete profiles ────────────────────────────────────────────

type ProfileSortKey = "display_name" | "principal_name" | "directory" | "missing";

function IncompleteProfileSection({ users }: { users: AzureDirectoryObject[] }) {
  const [missingFieldFilter, setMissingFieldFilter] = useState<"all" | "department" | "job_title" | "both">("all");
  const incomplete = users.filter((u) => {
    if (!u.enabled) return false;
    if (u.extra.user_type === "Guest") return false;
    return !u.extra.department || !u.extra.job_title;
  });
  const filteredIncomplete = incomplete.filter((user) => {
    const missing = missingFieldLabel(user);
    if (missingFieldFilter === "department") return missing === "Department";
    if (missingFieldFilter === "job_title") return missing === "Job Title";
    if (missingFieldFilter === "both") return missing.includes("Department") && missing.includes("Job Title");
    return true;
  });
  const { sortKey, sortDir, toggleSort } = useTableSort<ProfileSortKey>("display_name");
  const sorted = sortRows(filteredIncomplete, sortKey, sortDir, (u, key) => {
    if (key === "directory") return getDirectoryLabel(u);
    if (key === "missing") return missingFieldLabel(u);
    return (u as unknown as Record<string, unknown>)[key] as string;
  });
  const scroll = useInfiniteScrollCount(sorted.length, 50, `profile|${sortKey}|${sortDir}|${missingFieldFilter}`);
  const visible = sorted.slice(0, scroll.visibleCount);

  return (
    <Section id="incomplete-profiles" title="Incomplete Profiles" count={incomplete.length}>
      <Guide
        tone="blue"
        icon="📋"
        issue="Enabled employee accounts missing department or job title."
        why="Complete profiles are required for accurate ticket routing, reporting, and user lookup. Missing department and job title also interfere with dynamic group membership rules and automated workflows."
        action="Update the missing fields directly in Entra ID via the Manage in Entra link, or coordinate with HR to sync profile data from your identity source. On-prem synced accounts should be updated in Active Directory."
      />
      <div className="flex flex-wrap gap-2">
        {([
          ["all", "All incomplete"],
          ["department", "Missing Department"],
          ["job_title", "Missing Job Title"],
          ["both", "Missing Both"],
        ] as const).map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setMissingFieldFilter(value)}
            className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
              missingFieldFilter === value
                ? "bg-sky-600 text-white"
                : "bg-white text-slate-600 hover:bg-slate-100"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {incomplete.length === 0 ? (
        <p className="text-sm text-emerald-700 font-medium">✓ All enabled employee profiles are complete.</p>
      ) : (
        <div className="overflow-auto rounded-xl border border-slate-200">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <SortHeader col="display_name" label="Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="principal_name" label="UPN" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="directory" label="Directory" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="missing" label="Missing Fields" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((u, idx) => {
                const missing: string[] = [];
                if (!u.extra.department) missing.push("Department");
                if (!u.extra.job_title) missing.push("Job Title");
                return (
                  <tr key={u.id} className={idx % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                    <td className="px-4 py-2 font-medium text-slate-900">{u.display_name}</td>
                    <td className="px-4 py-2 text-xs text-slate-500 font-mono">{u.principal_name}</td>
                    <td className="px-4 py-2 text-slate-600 text-xs">{getDirectoryLabel(u)}</td>
                    <td className="px-4 py-2">
                      {missing.map((f) => (
                        <span key={f} className="mr-1 rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700">
                          {f}
                        </span>
                      ))}
                    </td>
                    <td className="px-4 py-2"><ManageLink id={u.id} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {scroll.hasMore ? (
            <div ref={scroll.sentinelRef} className="border-t border-slate-200 px-4 py-2 text-center text-xs text-slate-400">
              Showing {visible.length} of {incomplete.length} — scroll for more
            </div>
          ) : null}
        </div>
      )}
    </Section>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AzureAccountHealthPage() {
  const [staleThreshold, setStaleThreshold] = useState(90);
  const [guestThreshold, setGuestThreshold] = useState(180);
  const [includeSharedService, setIncludeSharedService] = useState(false);

  const { data: users = [], isLoading, isError, error } = useQuery({
    queryKey: ["azure", "users", { search: "" }],
    queryFn: () => api.getAzureUsers(""),
    ...getPollingQueryOptions("slow_5m"),
  });
  const statusQuery = useQuery({
    queryKey: ["azure", "status"],
    queryFn: () => api.getAzureStatus(),
    ...getPollingQueryOptions("slow_5m"),
  });
  const exceptionsQuery = useQuery({
    queryKey: ["azure", "security", "finding-exceptions", DIRECTORY_USER_EXCEPTION_SCOPE],
    queryFn: () => api.getAzureSecurityFindingExceptions(DIRECTORY_USER_EXCEPTION_SCOPE),
    ...getPollingQueryOptions("slow_5m"),
  });

  if (isLoading) {
    return <AzurePageSkeleton titleWidth="w-56" subtitleWidth="w-[40rem]" statCount={5} sectionCount={5} />;
  }
  if (isError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load users: {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }

  const exceptionIndex = buildSecurityFindingExceptionIndex(exceptionsQuery.data ?? []);
  const visibleUsers = users.filter((user) => !hasSecurityFindingException(exceptionIndex, user.id, "all-findings"));
  const scopedUsers = includeSharedService
    ? visibleUsers.filter((user) => !hasSecurityFindingException(exceptionIndex, user.id, "shared-service"))
    : visibleUsers.filter((user) => !isSharedOrService(user));
  const disabledCount   = scopedUsers.filter((u) => u.enabled === false && !(String(u.extra.is_licensed || "").toLowerCase() === "true" && hasSecurityFindingException(exceptionIndex, u.id, "disabled-licensed"))).length;
  const staleCount      = scopedUsers.filter((u) => u.enabled && u.extra.on_prem_sync !== "true" && u.extra.user_type !== "Guest" && u.extra.last_password_change && daysSince(u.extra.last_password_change) >= staleThreshold).length;
  const oldGuestCount   = visibleUsers.filter((u) => u.extra.user_type === "Guest" && !hasSecurityFindingException(exceptionIndex, u.id, "guest-user") && u.extra.created_datetime && daysSince(u.extra.created_datetime) >= guestThreshold).length;
  const incompleteCount = scopedUsers.filter((u) => u.enabled && u.extra.user_type !== "Guest" && (!u.extra.department || !u.extra.job_title)).length;
  const totalIssues     = disabledCount + staleCount + oldGuestCount + incompleteCount;
  const triageRows = [
    ...scopedUsers.filter((u) => u.enabled && u.extra.on_prem_sync !== "true" && u.extra.user_type !== "Guest" && u.extra.last_password_change && daysSince(u.extra.last_password_change) >= staleThreshold),
    ...scopedUsers.filter((u) => u.enabled === false && !(String(u.extra.is_licensed || "").toLowerCase() === "true" && hasSecurityFindingException(exceptionIndex, u.id, "disabled-licensed"))),
    ...visibleUsers.filter((u) => u.extra.user_type === "Guest" && !hasSecurityFindingException(exceptionIndex, u.id, "guest-user") && u.extra.created_datetime && daysSince(u.extra.created_datetime) >= guestThreshold),
    ...scopedUsers.filter((u) => u.enabled && u.extra.user_type !== "Guest" && (!u.extra.department || !u.extra.job_title)),
  ]
    .sort((a, b) => priorityScore(b) - priorityScore(a))
    .slice(0, 3);
  const directoryDataset = statusQuery.data?.datasets?.find((dataset) => dataset.key === "directory");

  return (
    <div className="space-y-6">
      <AzureSecurityLaneHero
        title="Account Health"
        description="Accounts that may need to be updated, disabled, or removed, with opinionated guidance for each remediation path. This is the security-native account hygiene lane, while the hidden raw user inventory stays available for direct admin work."
        accent="amber"
        refreshLabel="Directory refresh"
        refreshValue={formatTimestamp(directoryDataset?.last_refresh ?? statusQuery.data?.last_refresh)}
        actions={[
          { label: "Back to Security workspace", to: "/security", tone: "secondary" },
          { label: "Open User Review", to: "/security/user-review" },
          { label: "Open raw user inventory", to: "/users", tone: "secondary" },
        ]}
      />

      {exceptionsQuery.isError ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 shadow-sm">
          Security finding exceptions could not be loaded right now, so approved finding exceptions may temporarily reappear in this account health lane.
        </section>
      ) : (exceptionsQuery.data ?? []).some((exception) => ["all-findings", "disabled-licensed", "guest-user", "shared-service"].includes(exception.finding_key)) ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-900 shadow-sm">
          {(exceptionsQuery.data ?? []).filter((exception) => ["all-findings", "disabled-licensed", "guest-user", "shared-service"].includes(exception.finding_key)).length.toLocaleString()} approved finding exception{(exceptionsQuery.data ?? []).filter((exception) => ["all-findings", "disabled-licensed", "guest-user", "shared-service"].includes(exception.finding_key)).length === 1 ? "" : "s"} are currently shaping this account health lane.
        </section>
      ) : null}

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-4 text-sm text-slate-600">
          <label className="flex items-center gap-2">
            Stale password after
            <input
              type="number"
              min={30}
              max={730}
              value={staleThreshold}
              onChange={(e) => setStaleThreshold(Math.max(1, Number(e.target.value)))}
              className="w-16 rounded-lg border border-slate-300 px-2 py-1 text-sm text-center"
            />
            days
          </label>
          <span className="text-slate-300">|</span>
          <label className="flex items-center gap-2">
            Old guest after
            <input
              type="number"
              min={30}
              max={730}
              value={guestThreshold}
              onChange={(e) => setGuestThreshold(Math.max(1, Number(e.target.value)))}
              className="w-16 rounded-lg border border-slate-300 px-2 py-1 text-sm text-center"
            />
            days
          </label>
          <span className="text-slate-300">|</span>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={includeSharedService}
              onChange={(event) => setIncludeSharedService(event.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
            />
            Include shared / service-style accounts
          </label>
        </div>
      </section>

      {/* Summary cards */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm xl:col-span-1">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Total Issues</div>
          <div className={`mt-2 text-3xl font-semibold ${totalIssues === 0 ? "text-emerald-700" : "text-amber-700"}`}>
            {totalIssues.toLocaleString()}
          </div>
        </div>
        {[
          { label: "Disabled", count: disabledCount, href: "#disabled", tone: "text-amber-700" },
          { label: `Stale Passwords (${staleThreshold}d)`, count: staleCount, href: "#stale-passwords", tone: "text-red-700" },
          { label: `Old Guests (${guestThreshold}d)`, count: oldGuestCount, href: "#old-guests", tone: "text-violet-700" },
          { label: "Incomplete Profiles", count: incompleteCount, href: "#incomplete-profiles", tone: "text-sky-700" },
        ].map(({ label, count, href, tone }) => (
          <a key={href} href={href} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm hover:border-slate-300 transition block">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
            <div className={`mt-2 text-3xl font-semibold ${count === 0 ? "text-emerald-700" : tone}`}>
              {count.toLocaleString()}
            </div>
          </a>
        ))}
      </div>

      {totalIssues === 0 ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-5 py-6 text-center text-emerald-800">
          <div className="text-lg font-semibold">✓ All accounts look healthy</div>
          <div className="mt-1 text-sm opacity-80">No disabled, stale, old guest, or incomplete accounts found with the current thresholds.</div>
        </div>
      ) : null}

      {triageRows.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Start Here</h2>
              <p className="mt-1 text-sm text-slate-500">
                Highest-priority account hygiene issues based on licensing waste, stale credential risk, guest age, and missing profile data.
              </p>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
              {includeSharedService ? "Including shared/service" : "People accounts first"}
            </span>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {triageRows.map((user) => (
              <div key={user.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="font-medium text-slate-900">{user.display_name}</div>
                  <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-800">
                    {user.extra.priority_band}
                  </span>
                </div>
                <div className="mt-1 text-xs text-slate-500">{user.principal_name || user.mail || user.id}</div>
                <div className="mt-3 text-sm text-slate-700">{user.extra.priority_reason}</div>
                <div className="mt-3 text-xs text-slate-500">
                  {accountClassLabel(user)} • {getDirectoryLabel(user)}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* Sections */}
      <StalePasswordSection users={scopedUsers} threshold={staleThreshold} />
      <DisabledSection users={scopedUsers} />
      <OldGuestSection users={visibleUsers} threshold={guestThreshold} />
      <IncompleteProfileSection users={scopedUsers} />
    </div>
  );
}
