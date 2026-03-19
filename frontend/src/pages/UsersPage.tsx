import { useDeferredValue, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api.ts";
import type { Assignee, AssigneeStats } from "../lib/api.ts";
import MetricCard from "../components/MetricCard.tsx";

function formatHours(hours: number | null | undefined): string {
  if (hours == null) return "\u2014";
  if (hours < 1) {
    return `${Math.round(hours * 60)}m`;
  }
  if (hours < 24) {
    return `${hours.toFixed(1)}h`;
  }
  return `${(hours / 24).toFixed(1)}d`;
}

function buildUserTicketsLink(displayName: string, openOnly = false): string {
  const params = new URLSearchParams({ assignee: displayName });
  if (openOnly) {
    params.set("open_only", "true");
  }
  return `/tickets?${params.toString()}`;
}

export default function UsersPage() {
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: () => api.getUsers(),
    staleTime: 5 * 60 * 1000,
  });
  const metricsQuery = useQuery({
    queryKey: ["metrics", "users-page"],
    queryFn: () => api.getMetrics(),
    staleTime: 5 * 60 * 1000,
  });

  if (usersQuery.isLoading) {
    return <div className="text-sm text-slate-500">Loading Jira users...</div>;
  }

  if (usersQuery.isError || !usersQuery.data) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load users: {usersQuery.error instanceof Error ? usersQuery.error.message : "Unknown error"}
      </div>
    );
  }

  const users = usersQuery.data;
  const stats = metricsQuery.data?.assignee_stats ?? [];
  const statsByName: Record<string, AssigneeStats> = {};
  for (const item of stats) {
    if (item.name) {
      statsByName[item.name] = item;
    }
  }

  const normalizedSearch = deferredSearch.trim().toLowerCase();
  const filteredUsers = users.filter((user) => {
    if (!normalizedSearch) return true;
    const haystack = `${user.display_name} ${user.email_address ?? ""}`.toLowerCase();
    return haystack.includes(normalizedSearch);
  });

  const usersWithVisibleTickets = stats.filter((item) => item.name && item.open + item.resolved > 0).length;
  const openQueueOwners = stats.filter((item) => item.name && item.open > 0).length;
  const staleOwners = stats.filter((item) => item.name && item.stale > 0).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Users</h1>
          <p className="mt-1 text-sm text-slate-500">
            Active Jira users for OIT, with workload metrics based on tickets visible in this site.
          </p>
        </div>
        <div className="text-sm text-slate-500">
          <span className="font-semibold text-slate-900">{filteredUsers.length.toLocaleString()}</span>
          {" "}shown of {users.length.toLocaleString()}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard label="Total Users" value={users.length.toLocaleString()} color="blue" />
        <MetricCard
          label="With Visible Tickets"
          value={metricsQuery.isLoading ? "..." : usersWithVisibleTickets.toLocaleString()}
          color="green"
        />
        <MetricCard
          label="Open Queue Owners"
          value={metricsQuery.isLoading ? "..." : openQueueOwners.toLocaleString()}
          color="yellow"
        />
        <MetricCard
          label="Stale Queue Owners"
          value={metricsQuery.isLoading ? "..." : staleOwners.toLocaleString()}
          color="red"
        />
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Directory
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Search by name or email, then jump directly into that user&apos;s assigned tickets.
            </p>
          </div>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search users..."
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200 sm:max-w-xs"
          />
        </div>

        {metricsQuery.isError ? (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Workload metrics are temporarily unavailable. User directory data is still shown.
          </div>
        ) : null}

        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3 text-right">Open</th>
                <th className="px-4 py-3 text-right">Resolved</th>
                <th className="px-4 py-3 text-right">Stale</th>
                <th className="px-4 py-3 text-right">Median TTR</th>
                <th className="px-4 py-3 text-right">P90 TTR</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-sm text-slate-500">
                    No users matched the current search.
                  </td>
                </tr>
              ) : (
                filteredUsers.map((user: Assignee, index) => {
                  const stat = statsByName[user.display_name];
                  return (
                    <tr
                      key={user.account_id}
                      className={[
                        "border-b border-slate-100",
                        index % 2 === 0 ? "bg-white" : "bg-slate-50/60",
                      ].join(" ")}
                    >
                      <td className="px-4 py-3">
                        <Link
                          to={buildUserTicketsLink(user.display_name)}
                          className="font-medium text-slate-900 hover:text-blue-700 hover:underline"
                        >
                          {user.display_name}
                        </Link>
                        <div className="text-xs text-slate-500">
                          {user.email_address || "Email unavailable"}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {stat && stat.open > 0 ? (
                          <Link
                            to={buildUserTicketsLink(user.display_name, true)}
                            className="font-medium text-blue-700 hover:underline"
                          >
                            {stat.open.toLocaleString()}
                          </Link>
                        ) : (
                          <span className="text-slate-600">{stat?.open?.toLocaleString() ?? "0"}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-700">
                        {stat?.resolved?.toLocaleString() ?? "0"}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-700">
                        {stat?.stale?.toLocaleString() ?? "0"}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-700">
                        {formatHours(stat?.median_ttr)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-700">
                        {formatHours(stat?.p90_ttr)}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
