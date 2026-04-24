import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, type AzureDirectoryObject } from "../lib/api.ts";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";

// Inactive tabs: fetched once, never polled until the user switches back.
const INACTIVE_DIRECTORY_OPTIONS = {
  staleTime: 5 * 60_000,
  refetchInterval: false as const,
  refetchIntervalInBackground: false as const,
  refetchOnWindowFocus: false as const,
  refetchOnReconnect: false as const,
};
import { sortRows, useTableSort } from "../lib/tableSort.tsx";

type IdentityTab = "users" | "groups" | "enterprise-apps" | "app-registrations" | "roles";

const TAB_LABELS: Record<IdentityTab, string> = {
  users: "Users",
  groups: "Groups",
  "enterprise-apps": "Enterprise Apps",
  "app-registrations": "App Registrations",
  roles: "Directory Roles",
};

function summaryValue(rows: AzureDirectoryObject[] | undefined): string {
  return (rows?.length ?? 0).toLocaleString();
}

function DetailRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm text-slate-800">{value}</div>
    </div>
  );
}

function IdentityDetailDrawer({
  item,
  onClose,
}: {
  item: AzureDirectoryObject | null;
  onClose: () => void;
}) {
  if (!item) return null;
  const extraEntries = Object.entries(item.extra ?? {}).filter(([, value]) => value);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/35" onClick={onClose}>
      <aside className="flex h-full w-full max-w-2xl flex-col overflow-hidden bg-white shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="border-b border-slate-200 px-6 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {item.object_type.replaceAll("_", " ")}
              </div>
              <h2 className="mt-1 text-2xl font-semibold text-slate-900">{item.display_name || "(Unnamed)"}</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {item.enabled === true ? (
                  <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700">Enabled</span>
                ) : null}
                {item.enabled === false ? (
                  <span className="rounded-full bg-red-100 px-2.5 py-1 text-xs font-semibold text-red-700">Disabled</span>
                ) : null}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
            >
              Close
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          <section className="grid gap-3 md:grid-cols-2">
            <DetailRow label="Display Name" value={item.display_name} />
            <DetailRow label="Principal Name" value={item.principal_name} />
            <DetailRow label="Mail" value={item.mail} />
            <DetailRow label="App ID" value={item.app_id} />
            <DetailRow label="Object ID" value={item.id} />
            <DetailRow label="Object Type" value={item.object_type.replaceAll("_", " ")} />
          </section>

          {extraEntries.length ? (
            <section>
              <h3 className="text-lg font-semibold text-slate-900">Directory Metadata</h3>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {extraEntries.map(([key, value]) => (
                  <DetailRow key={key} label={key.replaceAll("_", " ")} value={value} />
                ))}
              </div>
            </section>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function DirectorySection({
  activeTab,
  rows,
  search,
  selectedId,
  onSelect,
}: {
  activeTab: IdentityTab;
  rows: AzureDirectoryObject[];
  search: string;
  selectedId: string;
  onSelect: (item: AzureDirectoryObject) => void;
}) {
  const { sortKey, sortDir, toggleSort } = useTableSort<"display_name">("display_name");
  const sorted = sortRows(rows, sortKey, sortDir);
  const { visibleCount, hasMore, sentinelRef } = useInfiniteScrollCount(sorted.length, 25, `${activeTab}|${search}|${sortDir}`);
  const visibleRows = sorted.slice(0, visibleCount);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">{TAB_LABELS[activeTab]}</h2>
            <div className="mt-1 text-sm text-slate-500">
              Click a row to inspect cached directory metadata without leaving the portal.
            </div>
          </div>
          <button
            type="button"
            onClick={() => toggleSort("display_name")}
            className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
          >
            Name {sortDir === "asc" ? "↑" : "↓"}
          </button>
        </div>
      </div>

      <div className="divide-y divide-slate-200">
        {visibleRows.length === 0 ? (
          <div className="px-5 py-12 text-center text-sm text-slate-500">No matching entries.</div>
        ) : null}
        {visibleRows.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item)}
            className={[
              "flex w-full items-start justify-between gap-4 px-5 py-4 text-left transition hover:bg-sky-50",
              selectedId === item.id ? "bg-sky-50" : "bg-white",
            ].join(" ")}
          >
            <div className="min-w-0">
              <div className="font-medium text-slate-900">{item.display_name || "(Unnamed)"}</div>
              <div className="mt-1 truncate text-xs text-slate-500">
                {[item.principal_name, item.mail, item.app_id].filter(Boolean).join(" | ") || item.id}
              </div>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {item.object_type.replaceAll("_", " ")}
            </span>
          </button>
        ))}
      </div>
      {hasMore ? (
        <div ref={sentinelRef} className="border-t border-slate-200 px-5 py-3 text-center text-xs text-slate-400">
          Showing {visibleRows.length.toLocaleString()} of {rows.length.toLocaleString()} — scroll for more
        </div>
      ) : null}
    </section>
  );
}

export default function AzureIdentityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState(searchParams.get("search") || "");
  const [activeTab, setActiveTab] = useState<IdentityTab>((searchParams.get("tab") as IdentityTab) || "users");
  const [selectedObjectId, setSelectedObjectId] = useState(searchParams.get("objectId") || "");

  useEffect(() => {
    const nextSearch = searchParams.get("search") || "";
    const nextTab = (searchParams.get("tab") as IdentityTab) || "users";
    const nextObjectId = searchParams.get("objectId") || "";
    if (nextSearch !== search) setSearch(nextSearch);
    if (nextTab !== activeTab) setActiveTab(nextTab);
    if (nextObjectId !== selectedObjectId) setSelectedObjectId(nextObjectId);
  }, [activeTab, search, searchParams, selectedObjectId]);

  const users = useQuery({
    queryKey: ["azure", "users", { search }],
    queryFn: () => api.getAzureUsers(search),
    ...(activeTab === "users" ? getPollingQueryOptions("slow_5m") : INACTIVE_DIRECTORY_OPTIONS),
  });
  const groups = useQuery({
    queryKey: ["azure", "groups", { search }],
    queryFn: () => api.getAzureGroups(search),
    ...(activeTab === "groups" ? getPollingQueryOptions("slow_5m") : INACTIVE_DIRECTORY_OPTIONS),
  });
  const enterpriseApps = useQuery({
    queryKey: ["azure", "enterprise-apps", { search }],
    queryFn: () => api.getAzureEnterpriseApps(search),
    ...(activeTab === "enterprise-apps" ? getPollingQueryOptions("slow_5m") : INACTIVE_DIRECTORY_OPTIONS),
  });
  const appRegistrations = useQuery({
    queryKey: ["azure", "app-registrations", { search }],
    queryFn: () => api.getAzureAppRegistrations(search),
    ...(activeTab === "app-registrations" ? getPollingQueryOptions("slow_5m") : INACTIVE_DIRECTORY_OPTIONS),
  });
  const roles = useQuery({
    queryKey: ["azure", "directory-roles", { search }],
    queryFn: () => api.getAzureDirectoryRoles(search),
    ...(activeTab === "roles" ? getPollingQueryOptions("slow_5m") : INACTIVE_DIRECTORY_OPTIONS),
  });

  const loading = [users, groups, enterpriseApps, appRegistrations, roles].some((query) => query.isLoading);
  const failure = [users, groups, enterpriseApps, appRegistrations, roles].find((query) => query.isError);

  const rowsByTab = useMemo<Record<IdentityTab, AzureDirectoryObject[]>>(
    () => ({
      users: users.data ?? [],
      groups: groups.data ?? [],
      "enterprise-apps": enterpriseApps.data ?? [],
      "app-registrations": appRegistrations.data ?? [],
      roles: roles.data ?? [],
    }),
    [appRegistrations.data, enterpriseApps.data, groups.data, roles.data, users.data],
  );

  const selectedItem = useMemo(
    () => rowsByTab[activeTab].find((item) => item.id === selectedObjectId) ?? null,
    [activeTab, rowsByTab, selectedObjectId],
  );

  function updateRouteParams(next: { search?: string; tab?: IdentityTab; objectId?: string | null }) {
    const params = new URLSearchParams(searchParams);
    if (next.search !== undefined) {
      if (next.search) params.set("search", next.search);
      else params.delete("search");
    }
    if (next.tab !== undefined) {
      params.set("tab", next.tab);
    }
    if (next.objectId === null) {
      params.delete("objectId");
    } else if (next.objectId) {
      params.set("objectId", next.objectId);
    }
    setSearchParams(params, { replace: true });
  }

  if (loading) {
    return <AzurePageSkeleton titleWidth="w-44" subtitleWidth="w-[32rem]" statCount={5} sectionCount={2} />;
  }

  if (failure) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load directory data: {failure.error instanceof Error ? failure.error.message : "Unknown error"}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Identity</h1>
        <p className="mt-1 text-sm text-slate-500">
          Search across cached Microsoft Entra users, groups, enterprise apps, app registrations, and directory roles.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-5">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Users</div>
          <div className="mt-2 text-3xl font-semibold text-slate-900">{summaryValue(users.data)}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Groups</div>
          <div className="mt-2 text-3xl font-semibold text-slate-900">{summaryValue(groups.data)}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Enterprise Apps</div>
          <div className="mt-2 text-3xl font-semibold text-slate-900">{summaryValue(enterpriseApps.data)}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">App Registrations</div>
          <div className="mt-2 text-3xl font-semibold text-slate-900">{summaryValue(appRegistrations.data)}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Directory Roles</div>
          <div className="mt-2 text-3xl font-semibold text-slate-900">{summaryValue(roles.data)}</div>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <input
          value={search}
          onChange={(event) => {
            const nextValue = event.target.value;
            setSearch(nextValue);
            updateRouteParams({ search: nextValue, objectId: null });
          }}
          placeholder="Search users, apps, groups, or roles..."
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
        />
      </div>

      <div className="flex flex-wrap gap-2 border-b border-slate-200 pb-3">
        {(Object.keys(TAB_LABELS) as IdentityTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => {
              setActiveTab(tab);
              updateRouteParams({ tab, objectId: null });
            }}
            className={[
              "rounded-full px-4 py-2 text-sm font-medium transition",
              activeTab === tab
                ? "bg-sky-600 text-white"
                : "bg-white text-slate-600 hover:bg-slate-100",
            ].join(" ")}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      <DirectorySection
        activeTab={activeTab}
        rows={rowsByTab[activeTab]}
        search={search}
        selectedId={selectedObjectId}
        onSelect={(item) => {
          setSelectedObjectId(item.id);
          updateRouteParams({ objectId: item.id, tab: activeTab, search });
        }}
      />

      <IdentityDetailDrawer
        item={selectedItem}
        onClose={() => {
          setSelectedObjectId("");
          updateRouteParams({ objectId: null });
        }}
      />
    </div>
  );
}
