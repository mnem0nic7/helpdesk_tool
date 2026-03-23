import { useDeferredValue, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type AzureVirtualDesktopRow } from "../lib/api.ts";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";

type DesktopSortKey =
  | "name"
  | "assigned_user"
  | "host_pool"
  | "power_state"
  | "power_signal"
  | "user_login"
  | "subscription";

function StatCard({
  label,
  value,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function flagBadge(active: boolean, activeLabel: string, inactiveLabel: string, tone: "red" | "amber" | "emerald") {
  if (!active) {
    return (
      <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">
        {inactiveLabel}
      </span>
    );
  }

  const styles = {
    red: "bg-red-100 text-red-700",
    amber: "bg-amber-100 text-amber-700",
    emerald: "bg-emerald-100 text-emerald-700",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${styles[tone]}`}>
      {activeLabel}
    </span>
  );
}

function assignmentBadge(status: AzureVirtualDesktopRow["assignment_status"]) {
  if (status === "resolved") {
    return flagBadge(true, "Resolved", "Resolved", "emerald");
  }
  if (status === "missing") {
    return flagBadge(true, "Missing", "Missing", "amber");
  }
  return flagBadge(true, "Unresolved", "Unresolved", "amber");
}

function signalText(days: number | null, localText: string, emptyLabel: string): string {
  if (days === null) return emptyLabel;
  if (days <= 0) return "Today";
  return `${days}d ago${localText ? ` · ${localText}` : ""}`;
}

function reasonBadges(reasons: string[]) {
  if (reasons.length === 0) {
    return (
      <span className="inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">
        Healthy
      </span>
    );
  }
  return (
    <div className="flex flex-wrap gap-1">
      {reasons.map((reason) => (
        <span
          key={reason}
          className="inline-block rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700"
        >
          {reason}
        </span>
      ))}
    </div>
  );
}

export default function AzureVirtualDesktopsPage() {
  const [search, setSearch] = useState("");
  const [removalOnly, setRemovalOnly] = useState(true);
  const deferredSearch = useDeferredValue(search.trim());
  const { sortKey, sortDir, toggleSort } = useTableSort<DesktopSortKey>("power_signal", "desc");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["azure", "virtual-desktops", "cleanup", deferredSearch, removalOnly],
    queryFn: () =>
      api.getAzureVirtualDesktopRemovalCandidates({
        search: deferredSearch,
        removal_only: removalOnly,
      }),
  });

  const rows = data?.desktops ?? [];
  const summary = data?.summary;
  const sorted = sortRows(rows, sortKey, sortDir, (row, key) => {
    if (key === "assigned_user") return row.assigned_user_display_name || row.assigned_user_principal_name;
    if (key === "host_pool") return row.host_pool_name;
    if (key === "power_signal") return row.days_since_power_signal ?? -1;
    if (key === "user_login") return row.days_since_assigned_user_login ?? -1;
    if (key === "subscription") return row.subscription_name || row.subscription_id;
    return (row as unknown as Record<string, string | number | null>)[key] ?? "";
  });
  const scroll = useInfiniteScrollCount(sorted.length, 50, `${deferredSearch}|${removalOnly}|${sortKey}|${sortDir}`);
  const visible = sorted.slice(0, scroll.visibleCount);

  if (isLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          <span>Loading desktop cleanup tracker...</span>
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-red-700 shadow-sm">
        <h1 className="text-lg font-semibold text-red-900">Desktop cleanup tracker unavailable</h1>
        <p className="mt-2 text-sm">{error instanceof Error ? error.message : "Unknown error"}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Azure Virtual Desktop Cleanup</h1>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Track personal desktops that should be removed when they have gone inactive, their assigned user is
              disabled or unlicensed, or the assigned user has not signed in recently.
            </p>
          </div>
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <div className="font-semibold">Signal note</div>
            <div className="mt-1 max-w-sm text-amber-800">
              Power activity currently uses the last time this app observed the VM in a <span className="font-semibold">Running</span> state.
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Tracked Desktops" value={(summary?.tracked_desktops ?? 0).toLocaleString()} />
        <StatCard
          label="Removal Candidates"
          value={(summary?.removal_candidates ?? 0).toLocaleString()}
          tone="text-red-700"
        />
        <StatCard
          label="Disabled / Unlicensed"
          value={(summary?.disabled_or_unlicensed_assignments ?? 0).toLocaleString()}
          tone="text-amber-700"
        />
        <StatCard
          label="Stale User Sign-Ins"
          value={(summary?.stale_assigned_user_signins ?? 0).toLocaleString()}
          tone="text-amber-700"
        />
        <StatCard
          label="Pending Power History"
          value={(summary?.power_signal_pending ?? 0).toLocaleString()}
          tone="text-sky-700"
        />
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Removal Tracker</h2>
            <p className="mt-1 text-sm text-slate-500">
              Threshold: {summary?.threshold_days ?? 14} days. Search by desktop, user, host pool, reason, or action.
            </p>
          </div>
          <label className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              checked={removalOnly}
              onChange={(event) => setRemovalOnly(event.target.checked)}
            />
            Removal only
          </label>
        </div>

        <input
          className="mt-4 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm placeholder-slate-400 focus:border-blue-500 focus:outline-none"
          placeholder="Search desktop, assigned user, host pool, or reason..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />

        {visible.length === 0 ? (
          <p className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-6 text-center text-sm font-medium text-emerald-700">
            No desktops match the current cleanup filters.
          </p>
        ) : (
          <div className="mt-4 overflow-auto rounded-2xl border border-slate-200">
            <table className="min-w-full text-left text-sm">
              <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <SortHeader col="name" label="Desktop" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader
                    col="assigned_user"
                    label="Assigned User"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                  <SortHeader col="host_pool" label="Host Pool" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader
                    col="power_state"
                    label="Power State"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                  <SortHeader
                    col="power_signal"
                    label="Last Running Signal"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                  <SortHeader
                    col="user_login"
                    label="User Sign-In"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                  <th className="px-4 py-3">Reasons</th>
                  <th className="px-4 py-3">Account Action</th>
                  <SortHeader
                    col="subscription"
                    label="Subscription"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                </tr>
              </thead>
              <tbody>
                {visible.map((desktop, index) => (
                  <tr key={desktop.id} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/40"}>
                    <td className="px-4 py-3 align-top">
                      <div className="font-medium text-slate-900">{desktop.name || desktop.id}</div>
                      <div className="mt-1 text-xs text-slate-500">{desktop.resource_group || "No resource group"}</div>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <div className="font-medium text-slate-900">{desktop.assigned_user_display_name}</div>
                      <div className="mt-1 text-xs text-slate-500">{desktop.assigned_user_principal_name || "—"}</div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {assignmentBadge(desktop.assignment_status)}
                        {flagBadge(desktop.assigned_user_enabled === false, "Disabled", "Enabled / Unknown", "red")}
                        {flagBadge(desktop.assigned_user_licensed === false, "Unlicensed", "Licensed / Unknown", "amber")}
                      </div>
                    </td>
                    <td className="px-4 py-3 align-top text-slate-600">
                      <div>{desktop.host_pool_name || "—"}</div>
                      <div className="mt-1 text-xs text-slate-500">{desktop.assignment_source || "—"}</div>
                    </td>
                    <td className="px-4 py-3 align-top">
                      {flagBadge(desktop.mark_for_removal, desktop.power_state || "Unknown", desktop.power_state || "Unknown", desktop.mark_for_removal ? "red" : "emerald")}
                    </td>
                    <td className="px-4 py-3 align-top text-slate-600">
                      {desktop.power_signal_pending ? (
                        <span className="text-xs font-medium text-sky-700">Awaiting first running observation</span>
                      ) : (
                        signalText(
                          desktop.days_since_power_signal,
                          desktop.last_power_signal_local,
                          "No running signal recorded",
                        )
                      )}
                    </td>
                    <td className="px-4 py-3 align-top text-slate-600">
                      {signalText(
                        desktop.days_since_assigned_user_login,
                        desktop.assigned_user_last_successful_local,
                        "No successful Entra sign-in recorded",
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">{reasonBadges(desktop.removal_reasons)}</td>
                    <td className="px-4 py-3 align-top">
                      {desktop.account_action ? (
                        <span className="inline-block rounded-lg bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">
                          {desktop.account_action}
                        </span>
                      ) : (
                        <span className="text-xs text-slate-400">No account action</span>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top text-slate-600">
                      {desktop.subscription_name || desktop.subscription_id || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {scroll.hasMore ? (
              <div
                ref={scroll.sentinelRef}
                className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400"
              >
                Showing {visible.length} of {sorted.length} tracked desktops
              </div>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}
