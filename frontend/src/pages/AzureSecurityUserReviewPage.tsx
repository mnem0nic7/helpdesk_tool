import { useDeferredValue, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import { AzureSecurityLaneHero, AzureSecurityMetricCard } from "../components/AzureSecurityLane.tsx";
import { api, type AzureDirectoryObject } from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";
import SecurityReviewPagination, { sliceSecurityReviewPage, useSecurityReviewPagination } from "../components/SecurityReviewPagination.tsx";
import {
  accountClassLabel,
  getDirectoryLabel,
  hasNoSuccessfulSignIn,
  isLicensedUser,
  isOnPremSynced,
  isSharedOrService,
  lastSuccessfulText,
  licenseCount,
  missingFieldLabel,
  priorityScore,
} from "../lib/azureSecurityUsers.ts";

type UserFocus = "all" | "priority" | "stale" | "disabled-licensed" | "guests" | "synced" | "shared-service";

const EMPTY_DIRECTORY_OBJECTS: AzureDirectoryObject[] = [];

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No refresh recorded";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function matchesSearch(parts: Array<string | string[]>, search: string): boolean {
  if (!search) return true;
  const normalizedSearch = search.toLowerCase();
  return parts
    .flatMap((part) => (Array.isArray(part) ? part : [part]))
    .some((part) => String(part || "").toLowerCase().includes(normalizedSearch));
}

function buildUserRoute(userId: string): string {
  return `/users?userId=${encodeURIComponent(userId)}`;
}

function userFlags(user: AzureDirectoryObject): string[] {
  const flags: string[] = [];
  if (user.enabled === false) flags.push("Disabled account");
  if (isLicensedUser(user)) flags.push(`${licenseCount(user)} active license${licenseCount(user) === 1 ? "" : "s"}`);
  if (hasNoSuccessfulSignIn(user)) flags.push("No successful sign-in in 30+ days");
  if (user.extra.user_type === "Guest") flags.push("Guest user");
  if (isOnPremSynced(user)) flags.push("On-prem synced");
  if (isSharedOrService(user)) flags.push("Shared / service-style account");
  if (missingFieldLabel(user)) flags.push(`Missing ${missingFieldLabel(user)}`);
  return flags;
}

function SectionFrame({
  title,
  description,
  count,
  children,
}: {
  title: string;
  description: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          <div className="mt-1 text-sm text-slate-500">{description}</div>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {count.toLocaleString()}
        </span>
      </div>
      <div className="mt-5">{children}</div>
    </section>
  );
}

export default function AzureSecurityUserReviewPage() {
  const [search, setSearch] = useState("");
  const [focus, setFocus] = useState<UserFocus>("priority");
  const deferredSearch = useDeferredValue(search);

  const usersQuery = useQuery({
    queryKey: ["azure", "users", { search: "" }],
    queryFn: () => api.getAzureUsers(""),
    ...getPollingQueryOptions("slow_5m"),
  });
  const statusQuery = useQuery({
    queryKey: ["azure", "status"],
    queryFn: () => api.getAzureStatus(),
    ...getPollingQueryOptions("slow_5m"),
  });

  const users = usersQuery.data ?? EMPTY_DIRECTORY_OBJECTS;

  const disabledLicensedCount = useMemo(
    () => users.filter((user) => user.enabled === false && isLicensedUser(user)).length,
    [users],
  );
  const staleSignInCount = useMemo(() => users.filter((user) => hasNoSuccessfulSignIn(user)).length, [users]);
  const guestCount = useMemo(() => users.filter((user) => user.extra.user_type === "Guest").length, [users]);
  const onPremCount = useMemo(() => users.filter((user) => isOnPremSynced(user)).length, [users]);
  const sharedServiceCount = useMemo(() => users.filter((user) => isSharedOrService(user)).length, [users]);

  const priorityQueue = useMemo(
    () =>
      [...users]
        .filter((user) => priorityScore(user) >= 60)
        .sort((left, right) => priorityScore(right) - priorityScore(left) || left.display_name.localeCompare(right.display_name))
        .slice(0, 8),
    [users],
  );

  const filteredUsers = useMemo(() => {
    const sorted = [...users].sort(
      (left, right) => priorityScore(right) - priorityScore(left) || left.display_name.localeCompare(right.display_name),
    );
    return sorted.filter((user) => {
      if (focus === "priority" && priorityScore(user) < 60) return false;
      if (focus === "stale" && !hasNoSuccessfulSignIn(user)) return false;
      if (focus === "disabled-licensed" && !(user.enabled === false && isLicensedUser(user))) return false;
      if (focus === "guests" && user.extra.user_type !== "Guest") return false;
      if (focus === "synced" && !isOnPremSynced(user)) return false;
      if (focus === "shared-service" && !isSharedOrService(user)) return false;
      return matchesSearch(
        [
          user.display_name,
          user.principal_name,
          user.mail,
          user.extra.department,
          user.extra.job_title,
          user.extra.priority_reason,
          userFlags(user),
        ],
        deferredSearch,
      );
    });
  }, [deferredSearch, focus, users]);
  const reviewPagination = useSecurityReviewPagination(
    `${deferredSearch}|${focus}|${filteredUsers.length}`,
    filteredUsers.length,
  );
  const visibleUsers = useMemo(
    () => sliceSecurityReviewPage(filteredUsers, reviewPagination.pageStart, reviewPagination.pageSize),
    [filteredUsers, reviewPagination.pageSize, reviewPagination.pageStart],
  );

  if (usersQuery.isLoading) {
    return <AzurePageSkeleton titleWidth="w-56" subtitleWidth="w-[42rem]" statCount={6} sectionCount={3} />;
  }

  if (usersQuery.isError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load user review: {usersQuery.error instanceof Error ? usersQuery.error.message : "Unknown error"}
      </div>
    );
  }

  const directoryDataset = statusQuery.data?.datasets?.find((dataset) => dataset.key === "directory");

  return (
    <div className="space-y-6">
      <AzureSecurityLaneHero
        title="User Review"
        description="Review stale sign-ins, disabled licensed accounts, guest users, synced identities, and shared/service-style accounts from one security-native lane. Use the hidden raw user page only when you need the admin drawer or direct action surface."
        refreshLabel="Directory refresh"
        refreshValue={formatTimestamp(directoryDataset?.last_refresh ?? statusQuery.data?.last_refresh)}
        actions={[
          { label: "Back to Security workspace", to: "/security", tone: "secondary" },
          { label: "Open Account Health", to: "/security/account-health" },
          { label: "Open raw user inventory", to: "/users", tone: "secondary" },
        ]}
      />

      <section className="grid gap-4 xl:grid-cols-3 md:grid-cols-2">
        <AzureSecurityMetricCard
          label="Priority queue"
          value={priorityQueue.length}
          detail="High-signal users derived from cached account priority and hygiene heuristics."
          tone="rose"
        />
        <AzureSecurityMetricCard
          label="Stale sign-ins"
          value={staleSignInCount}
          detail="Enabled users with no successful sign-in in the last 30 days."
          tone="amber"
        />
        <AzureSecurityMetricCard
          label="Disabled + licensed"
          value={disabledLicensedCount}
          detail="Disabled users still holding paid licenses that likely need cleanup."
          tone="rose"
        />
        <AzureSecurityMetricCard
          label="Guest users"
          value={guestCount}
          detail="External identities currently cached in the tenant directory."
          tone="violet"
        />
        <AzureSecurityMetricCard
          label="On-prem synced"
          value={onPremCount}
          detail="Users sourced from on-premises AD that often need different remediation paths."
          tone="sky"
        />
        <AzureSecurityMetricCard
          label="Shared / service"
          value={sharedServiceCount}
          detail="Accounts classified from naming and employee-type markers as shared or service-style."
          tone="emerald"
        />
      </section>

      <SectionFrame
        title="Priority queue"
        description="Highest-signal user records based on stale credentials, guest age, licensing waste, and missing profile data."
        count={priorityQueue.length}
      >
        {priorityQueue.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">No priority users were identified from the current cached directory snapshot.</div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {priorityQueue.map((user) => (
              <section key={user.id} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-lg font-semibold text-slate-900">{user.display_name}</h3>
                      <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
                        {user.extra.priority_band || "review"}
                      </span>
                    </div>
                    <div className="mt-1 text-sm text-slate-500">{user.principal_name || user.mail || user.id}</div>
                  </div>
                  <Link
                    to={buildUserRoute(user.id)}
                    className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                  >
                    Open source record
                  </Link>
                </div>
                <div className="mt-4 rounded-xl bg-white px-4 py-3 text-sm text-slate-700">{user.extra.priority_reason}</div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {userFlags(user).map((flag) => (
                    <span key={`${user.id}-${flag}`} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                      {flag}
                    </span>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </SectionFrame>

      <SectionFrame
        title="Review queue"
        description="Filter the cached user inventory into the cohort you want to review, then pivot into the raw user page for deeper admin work."
        count={filteredUsers.length}
      >
        <div className="mb-5 grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search users, departments, risk reasons, or flags..."
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
          />
          <select
            value={focus}
            onChange={(event) => setFocus(event.target.value as UserFocus)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
          >
            <option value="priority">Priority queue</option>
            <option value="all">All users</option>
            <option value="stale">Stale sign-ins</option>
            <option value="disabled-licensed">Disabled + licensed</option>
            <option value="guests">Guest users</option>
            <option value="synced">On-prem synced</option>
            <option value="shared-service">Shared / service</option>
          </select>
        </div>

        <div className="mb-5">
          <SecurityReviewPagination
            count={filteredUsers.length}
            currentPage={reviewPagination.currentPage}
            pageSize={reviewPagination.pageSize}
            setCurrentPage={reviewPagination.setCurrentPage}
            setPageSize={reviewPagination.setPageSize}
            totalPages={reviewPagination.totalPages}
            noun="matching user record(s)"
          />
        </div>

        {filteredUsers.length === 0 ? (
          <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">No users match the current review filters.</div>
        ) : (
          <div className="overflow-auto rounded-xl border border-slate-200">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">User</th>
                  <th className="px-4 py-3">Account class</th>
                  <th className="px-4 py-3">Directory</th>
                  <th className="px-4 py-3">Last successful sign-in</th>
                  <th className="px-4 py-3">Review flags</th>
                  <th className="px-4 py-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {visibleUsers.map((user, index) => (
                  <tr key={user.id} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">{user.display_name}</div>
                      <div className="mt-1 text-xs text-slate-500">{user.principal_name || user.mail || user.id}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{accountClassLabel(user)}</td>
                    <td className="px-4 py-3 text-slate-700">{getDirectoryLabel(user)}</td>
                    <td className="px-4 py-3 text-slate-700">{lastSuccessfulText(user)}</td>
                    <td className="px-4 py-3">
                      <div className="flex max-w-xl flex-wrap gap-2">
                        {userFlags(user).map((flag) => (
                          <span key={`${user.id}-${flag}`} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                            {flag}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        to={buildUserRoute(user.id)}
                        className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                      >
                        Open source record
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionFrame>
    </div>
  );
}
