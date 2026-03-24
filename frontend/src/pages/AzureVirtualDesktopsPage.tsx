import { useDeferredValue, useEffect, useState, type PointerEvent as ReactPointerEvent } from "react";
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

const DEFAULT_AVD_DRAWER_WIDTH = 960;
const AVD_DRAWER_MIN_WIDTH = 720;
const AVD_DRAWER_VIEWPORT_MARGIN = 32;

function clampAVDDrawerWidth(width: number): number {
  if (typeof window === "undefined") return DEFAULT_AVD_DRAWER_WIDTH;
  const maxWidth = Math.max(360, window.innerWidth - AVD_DRAWER_VIEWPORT_MARGIN);
  const minWidth = Math.min(AVD_DRAWER_MIN_WIDTH, maxWidth);
  return Math.min(Math.max(width, minWidth), maxWidth);
}

function getExpandedAVDDrawerWidth(): number {
  if (typeof window === "undefined") return DEFAULT_AVD_DRAWER_WIDTH;
  return clampAVDDrawerWidth(window.innerWidth - AVD_DRAWER_VIEWPORT_MARGIN);
}

function buildAzurePortalUrl(resourceId: string): string {
  return `https://portal.azure.com/#resource${resourceId}`;
}

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

function statusBadge(label: string, tone: "red" | "amber" | "emerald" | "sky" | "slate") {
  const styles = {
    red: "bg-red-100 text-red-700",
    amber: "bg-amber-100 text-amber-700",
    emerald: "bg-emerald-100 text-emerald-700",
    sky: "bg-sky-100 text-sky-700",
    slate: "bg-slate-100 text-slate-500",
  };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${styles[tone]}`}>{label}</span>;
}

function userStatusBadges(row: AzureVirtualDesktopRow) {
  const badges = [];
  if (row.assigned_user_enabled === false) {
    badges.push(statusBadge("Disabled", "red"));
  } else if (row.assigned_user_enabled === true) {
    badges.push(statusBadge("Enabled", "emerald"));
  } else {
    badges.push(statusBadge("Status unknown", "slate"));
  }

  if (row.assigned_user_licensed === false) {
    badges.push(statusBadge("Unlicensed", "amber"));
  } else if (row.assigned_user_licensed === true) {
    badges.push(statusBadge("Licensed", "sky"));
  } else {
    badges.push(statusBadge("License unknown", "slate"));
  }

  return badges;
}

function assignedUserSourceBadge(row: AzureVirtualDesktopRow) {
  if (row.assigned_user_source === "avd_assigned") {
    return statusBadge(row.assigned_user_source_label || "AVD assigned user", "sky");
  }
  if (row.assigned_user_source === "avd_last_session") {
    return statusBadge(row.assigned_user_source_label || "Last AVD session user", "amber");
  }
  return statusBadge(row.assigned_user_source_label || "Unassigned", "slate");
}

function ownerHistoryNote(row: AzureVirtualDesktopRow): string {
  if (row.assigned_user_source === "avd_last_session" && row.assigned_user_observed_local) {
    return `Observed ${row.assigned_user_observed_local}`;
  }
  if (row.assigned_user_source !== "unassigned") {
    return "";
  }
  if (row.owner_history_status === "missing_diagnostics") {
    return "AVD connection diagnostics are not configured for fallback owner history";
  }
  if (row.owner_history_status === "query_failed") {
    return "AVD session history could not be queried";
  }
  if (row.owner_history_status === "no_history") {
    return "No recent successful AVD session history found";
  }
  return "";
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

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm text-slate-700">{value || "—"}</div>
    </div>
  );
}

function AVDDetailStatCard({ label, value, tone = "text-slate-900" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function cleanupDecisionLabel(row: AzureVirtualDesktopRow): string {
  return row.mark_for_removal ? "Removal candidate" : "Tracked";
}

function cleanupDecisionTone(row: AzureVirtualDesktopRow): string {
  return row.mark_for_removal ? "text-red-700" : "text-emerald-700";
}

function powerSignalLabel(row: AzureVirtualDesktopRow): string {
  if (row.power_signal_pending) {
    return "Awaiting first running observation";
  }
  return signalText(row.days_since_power_signal, row.last_power_signal_local, "No running signal recorded");
}

function interactiveSigninLabel(row: AzureVirtualDesktopRow): string {
  if (row.days_since_assigned_user_login === null) {
    return "No interactive Entra sign-in recorded";
  }
  return row.assigned_user_last_successful_local || signalText(row.days_since_assigned_user_login, "", "Recorded interactive sign-in");
}

function AzureVirtualDesktopDetailDrawer({
  desktop,
  onClose,
}: {
  desktop: AzureVirtualDesktopRow;
  onClose: () => void;
}) {
  const [drawerWidth, setDrawerWidth] = useState(() => clampAVDDrawerWidth(DEFAULT_AVD_DRAWER_WIDTH));
  const [isResizing, setIsResizing] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const tagEntries = Object.entries(desktop.tags ?? {});

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleResize = () => {
      setDrawerWidth((current) => (isExpanded ? getExpandedAVDDrawerWidth() : clampAVDDrawerWidth(current)));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [isExpanded]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    if (!isResizing) return undefined;

    const previousUserSelect = document.body.style.userSelect;
    const previousCursor = document.body.style.cursor;
    const updateWidth = (clientX: number) => {
      setDrawerWidth(clampAVDDrawerWidth(window.innerWidth - clientX));
    };

    const handlePointerMove = (event: PointerEvent) => {
      event.preventDefault();
      updateWidth(event.clientX);
    };

    const handleMouseMove = (event: MouseEvent) => {
      event.preventDefault();
      updateWidth(event.clientX);
    };

    const stopResizing = () => {
      setIsResizing(false);
    };

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
      setDrawerWidth(next ? getExpandedAVDDrawerWidth() : clampAVDDrawerWidth(DEFAULT_AVD_DRAWER_WIDTH));
      return next;
    });
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/35" onClick={onClose}>
      <aside
        data-testid="avd-cleanup-detail-drawer"
        className="relative flex h-full max-w-full flex-col overflow-hidden bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        style={{ width: `${drawerWidth}px` }}
      >
        <div
          role="separator"
          aria-label="Resize desktop detail drawer"
          aria-orientation="vertical"
          data-testid="avd-cleanup-detail-resizer"
          className={[
            "absolute inset-y-0 left-0 z-10 w-3 -translate-x-1/2 cursor-col-resize touch-none",
            isResizing ? "bg-blue-200/70" : "bg-transparent hover:bg-slate-200/60",
          ].join(" ")}
          onPointerDown={handleResizeStart}
          onDoubleClick={() => {
            setIsExpanded(false);
            setDrawerWidth(clampAVDDrawerWidth(DEFAULT_AVD_DRAWER_WIDTH));
          }}
        >
          <div className="absolute left-1/2 top-1/2 h-14 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-300" />
        </div>

        <div className="border-b border-slate-200 px-6 py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Desktop Detail</p>
              <h2 className="mt-1 truncate text-2xl font-bold text-slate-900">{desktop.name || desktop.id}</h2>
              <div className="mt-2 flex flex-wrap gap-1">
                {statusBadge(cleanupDecisionLabel(desktop), desktop.mark_for_removal ? "red" : "emerald")}
                {assignmentBadge(desktop.assignment_status)}
                {assignedUserSourceBadge(desktop)}
              </div>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500">
                <span>{desktop.host_pool_name || "No host pool"}</span>
                <span>{desktop.session_host_name || "No session host"}</span>
                <span>{desktop.subscription_name || desktop.subscription_id || "No subscription"}</span>
                <span>{desktop.resource_group || "No resource group"}</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <a
                href={buildAzurePortalUrl(desktop.id)}
                target="_blank"
                rel="noreferrer"
                className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 transition hover:bg-sky-100"
              >
                Open in Azure
              </a>
              <button
                type="button"
                onClick={toggleExpanded}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
              >
                {isExpanded ? "Restore" : "Expand"}
              </button>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="space-y-6">
            <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <AVDDetailStatCard
                label="Removal Status"
                value={cleanupDecisionLabel(desktop)}
                tone={cleanupDecisionTone(desktop)}
              />
              <AVDDetailStatCard
                label="Last Running Signal"
                value={powerSignalLabel(desktop)}
                tone={desktop.power_signal_stale ? "text-amber-700" : "text-slate-900"}
              />
              <AVDDetailStatCard
                label="Last Interactive Sign-In"
                value={interactiveSigninLabel(desktop)}
                tone={desktop.user_signin_stale ? "text-amber-700" : "text-slate-900"}
              />
              <AVDDetailStatCard
                label="Account Action"
                value={desktop.account_action || "No account action"}
                tone={desktop.account_action ? "text-amber-700" : "text-slate-900"}
              />
            </section>

            <section className="rounded-2xl border border-slate-200 p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-semibold text-slate-900">Assigned User</h3>
                  <p className="mt-1 text-sm text-slate-500">
                    Resolved owner, AVD source, and Entra account status used by cleanup decisions.
                  </p>
                </div>
                <div className="flex flex-wrap gap-1">
                  {userStatusBadges(desktop).map((badge, index) => (
                    <span key={`${desktop.id}-drawer-status-${index}`}>{badge}</span>
                  ))}
                </div>
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <DetailField label="Display Name" value={desktop.assigned_user_display_name || "Unassigned"} />
                <DetailField label="UPN" value={desktop.assigned_user_principal_name || "—"} />
                <DetailField label="Assignment Source" value={desktop.assignment_source || "—"} />
                <DetailField label="Owner Provenance" value={desktop.assigned_user_source_label || "Unassigned"} />
                <DetailField
                  label="Observed Owner Time"
                  value={desktop.assigned_user_observed_local || desktop.assigned_user_observed_utc || "—"}
                />
                <DetailField label="Owner History Status" value={desktop.owner_history_status.replaceAll("_", " ")} />
              </div>
              {ownerHistoryNote(desktop) ? (
                <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                  {ownerHistoryNote(desktop)}
                </div>
              ) : null}
            </section>

            <section className="rounded-2xl border border-slate-200 p-5">
              <h3 className="text-lg font-semibold text-slate-900">Desktop Context</h3>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <DetailField label="Subscription" value={desktop.subscription_name || desktop.subscription_id || "—"} />
                <DetailField label="Resource Group" value={desktop.resource_group || "—"} />
                <DetailField label="Location" value={desktop.location || "—"} />
                <DetailField label="VM Size" value={desktop.vm_size || desktop.size || "—"} />
                <DetailField label="Power State" value={desktop.power_state || desktop.state || "—"} />
                <DetailField label="Created" value={desktop.created_time || "—"} />
                <DetailField label="Host Pool" value={desktop.host_pool_name || "—"} />
                <DetailField label="Session Host" value={desktop.session_host_name || "—"} />
                <div className="md:col-span-2">
                  <DetailField label="Resource ID" value={desktop.id || "—"} />
                </div>
              </div>
            </section>

            <section className="rounded-2xl border border-slate-200 p-5">
              <h3 className="text-lg font-semibold text-slate-900">Signals & Cleanup Evaluation</h3>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <DetailField
                  label="Running Signal"
                  value={desktop.last_power_signal_local || desktop.last_power_signal_utc || "No running signal recorded"}
                />
                <DetailField
                  label="Running Signal Age"
                  value={desktop.power_signal_pending ? "Awaiting first running observation" : powerSignalLabel(desktop)}
                />
                <DetailField
                  label="Interactive Sign-In"
                  value={
                    desktop.assigned_user_last_successful_local ||
                    desktop.assigned_user_last_successful_utc ||
                    "No interactive Entra sign-in recorded"
                  }
                />
                <DetailField
                  label="Interactive Sign-In Age"
                  value={signalText(desktop.days_since_assigned_user_login, "", "No interactive Entra sign-in recorded")}
                />
                <DetailField
                  label="Removal Recommended"
                  value={desktop.mark_for_removal ? "Yes" : "No"}
                />
                <DetailField
                  label="Account Follow-Up"
                  value={desktop.mark_account_for_follow_up ? "Recommended" : "Not needed"}
                />
              </div>
              <div className="mt-4">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Reasons</div>
                <div className="mt-2">{reasonBadges(desktop.removal_reasons)}</div>
              </div>
            </section>

            {tagEntries.length > 0 ? (
              <section className="rounded-2xl border border-slate-200 p-5">
                <h3 className="text-lg font-semibold text-slate-900">Tags</h3>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  {tagEntries.map(([key, value]) => (
                    <div key={key} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{key}</div>
                      <div className="mt-1 break-words text-sm text-slate-700">{String(value)}</div>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}
          </div>
        </div>
      </aside>
    </div>
  );
}

export default function AzureVirtualDesktopsPage() {
  const [search, setSearch] = useState("");
  const [removalOnly, setRemovalOnly] = useState(false);
  const [selectedDesktop, setSelectedDesktop] = useState<AzureVirtualDesktopRow | null>(null);
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
  const activeDesktop = selectedDesktop ? sorted.find((row) => row.id === selectedDesktop.id) ?? selectedDesktop : null;

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
              Track personal AVD desktops that should be removed when they have gone inactive, their assigned user is
              disabled or unlicensed, or the resolved user has not signed in recently. Owner resolution uses Azure
              Virtual Desktop assignment first, then falls back to the most recent successful AVD session user.
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

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        <StatCard label="Tracked Desktops" value={(summary?.tracked_desktops ?? 0).toLocaleString()} />
        <StatCard
          label="Removal Candidates"
          value={(summary?.removal_candidates ?? 0).toLocaleString()}
          tone="text-red-700"
        />
        <StatCard
          label="Explicit AVD Owners"
          value={(summary?.explicit_avd_assignments ?? 0).toLocaleString()}
          tone="text-sky-700"
        />
        <StatCard
          label="Last Session Owners"
          value={(summary?.fallback_session_history_assignments ?? 0).toLocaleString()}
          tone="text-amber-700"
        />
        <StatCard
          label="Owner History Unavailable"
          value={(summary?.owner_history_unavailable ?? 0).toLocaleString()}
          tone="text-slate-700"
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
                  <th className="px-4 py-3">User Status</th>
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
                    label="Last Interactive User Sign-In"
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
                  <tr
                    key={desktop.id}
                    tabIndex={0}
                    aria-label={`Open details for ${desktop.name || desktop.id}`}
                    className={[
                      index % 2 === 0 ? "bg-white" : "bg-slate-50/40",
                      "cursor-pointer transition hover:bg-sky-50 focus:bg-sky-50 focus:outline-none",
                      activeDesktop?.id === desktop.id ? "bg-sky-50" : "",
                    ].join(" ")}
                    onClick={() => setSelectedDesktop(desktop)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedDesktop(desktop);
                      }
                    }}
                  >
                    <td className="px-4 py-3 align-top">
                      <div className="font-medium text-slate-900">{desktop.name || desktop.id}</div>
                      <div className="mt-1 text-xs text-slate-500">{desktop.resource_group || "No resource group"}</div>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <div className="font-medium text-slate-900">{desktop.assigned_user_display_name}</div>
                      <div className="mt-1 text-xs text-slate-500">{desktop.assigned_user_principal_name || "—"}</div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {assignmentBadge(desktop.assignment_status)}
                        {assignedUserSourceBadge(desktop)}
                      </div>
                      {ownerHistoryNote(desktop) ? (
                        <div className="mt-2 text-xs text-slate-500">{ownerHistoryNote(desktop)}</div>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <div className="flex flex-wrap gap-1">
                        {userStatusBadges(desktop).map((badge, badgeIndex) => (
                          <span key={`${desktop.id}-status-${badgeIndex}`}>{badge}</span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 align-top text-slate-600">
                      <div>{desktop.host_pool_name || "—"}</div>
                      <div className="mt-1 text-xs text-slate-500">{desktop.session_host_name || "—"}</div>
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
                      {desktop.days_since_assigned_user_login === null ? (
                        <span className="text-xs font-medium text-amber-700">No interactive Entra sign-in recorded</span>
                      ) : (
                        <div>
                          <div className="font-medium text-slate-900">
                            {desktop.assigned_user_last_successful_local || "Recorded interactive sign-in"}
                          </div>
                          <div className="mt-1 text-xs text-slate-500">
                            {signalText(desktop.days_since_assigned_user_login, "", "No interactive Entra sign-in recorded")}
                          </div>
                        </div>
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

      {activeDesktop ? <AzureVirtualDesktopDetailDrawer desktop={activeDesktop} onClose={() => setSelectedDesktop(null)} /> : null}
    </div>
  );
}
