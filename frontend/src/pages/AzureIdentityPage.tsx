import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";

function DirectorySection({
  search,
  title,
  rows,
}: {
  search: string;
  title: string;
  rows: Awaited<ReturnType<typeof api.getAzureUsers>>;
}) {
  const { visibleCount, hasMore, sentinelRef } = useInfiniteScrollCount(rows.length, 20, `${title}|${search}`);
  const visibleRows = rows.slice(0, visibleCount);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {rows.length.toLocaleString()}
        </span>
      </div>
      <div className="mt-4 max-h-[38rem] space-y-3 overflow-y-auto">
        {visibleRows.map((item) => (
          <div key={item.id} className="rounded-xl border border-slate-200 p-3">
            <div className="font-medium text-slate-900">{item.display_name || "(Unnamed)"}</div>
            <div className="mt-1 text-xs text-slate-500">
              {[item.principal_name, item.mail, item.app_id].filter(Boolean).join(" | ") || item.id}
            </div>
          </div>
        ))}
        {rows.length === 0 && (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">
            No matching entries.
          </div>
        )}
        {hasMore ? (
          <div ref={sentinelRef} className="py-2 text-center text-xs text-slate-400">
            Showing {visibleRows.length.toLocaleString()} of {rows.length.toLocaleString()} — scroll for more
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default function AzureIdentityPage() {
  const [search, setSearch] = useState("");

  const users = useQuery({
    queryKey: ["azure", "identity", "users", search],
    queryFn: () => api.getAzureUsers(search),
    refetchInterval: 60_000,
  });
  const groups = useQuery({
    queryKey: ["azure", "identity", "groups", search],
    queryFn: () => api.getAzureGroups(search),
    refetchInterval: 60_000,
  });
  const enterpriseApps = useQuery({
    queryKey: ["azure", "identity", "enterprise-apps", search],
    queryFn: () => api.getAzureEnterpriseApps(search),
    refetchInterval: 60_000,
  });
  const appRegistrations = useQuery({
    queryKey: ["azure", "identity", "app-registrations", search],
    queryFn: () => api.getAzureAppRegistrations(search),
    refetchInterval: 60_000,
  });
  const roles = useQuery({
    queryKey: ["azure", "identity", "roles", search],
    queryFn: () => api.getAzureDirectoryRoles(search),
    refetchInterval: 60_000,
  });

  const loading = [users, groups, enterpriseApps, appRegistrations, roles].some((query) => query.isLoading);
  const failure = [users, groups, enterpriseApps, appRegistrations, roles].find((query) => query.isError);

  if (loading) {
    return <div className="text-sm text-slate-500">Loading Entra directory data...</div>;
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
          Cached Microsoft Entra users, groups, enterprise apps, app registrations, and roles.
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search users, apps, groups, roles..."
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <DirectorySection search={search} title="Users" rows={users.data ?? []} />
        <DirectorySection search={search} title="Groups" rows={groups.data ?? []} />
        <DirectorySection search={search} title="Enterprise Apps" rows={enterpriseApps.data ?? []} />
        <DirectorySection search={search} title="App Registrations" rows={appRegistrations.data ?? []} />
        <DirectorySection search={search} title="Directory Roles" rows={roles.data ?? []} />
      </div>
    </div>
  );
}
