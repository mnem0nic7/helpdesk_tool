import { useDeferredValue, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import { AzureSecurityLaneHero, AzureSecurityMetricCard, azureSecurityToneClasses } from "../components/AzureSecurityLane.tsx";
import SecurityReviewPagination, { sliceSecurityReviewPage, useSecurityReviewPagination } from "../components/SecurityReviewPagination.tsx";
import {
  api,
  type SecurityDirectoryRoleReviewMembership,
  type SecurityDirectoryRoleReviewRole,
} from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";
import { formatDateTime } from "../lib/azureSecurityUsers.ts";

type PrincipalFilter = "all" | "user" | "group" | "service_principal";
type RiskFilter = "all" | "critical" | "elevated" | "flagged";

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

function privilegeTone(value: "critical" | "elevated" | "limited"): "rose" | "amber" | "slate" {
  if (value === "critical") return "rose";
  if (value === "elevated") return "amber";
  return "slate";
}

function membershipTone(value: SecurityDirectoryRoleReviewMembership["status"]): "rose" | "amber" | "emerald" {
  if (value === "critical") return "rose";
  if (value === "warning") return "amber";
  return "emerald";
}

function principalFilterKey(value: SecurityDirectoryRoleReviewMembership): PrincipalFilter {
  if (value.object_type === "user") return "user";
  if (value.object_type === "group") return "group";
  if (value.object_type === "enterprise_app") return "service_principal";
  return "all";
}

function principalTypeLabel(value: SecurityDirectoryRoleReviewMembership): string {
  if (value.object_type === "enterprise_app") return "Service principal";
  if (value.object_type === "group") return "Group";
  if (value.object_type === "user") return "User";
  return value.principal_type || "Directory object";
}

function buildPrincipalRoute(value: SecurityDirectoryRoleReviewMembership): string {
  if (value.object_type === "user") {
    return `/users?userId=${encodeURIComponent(value.principal_id)}`;
  }
  if (value.object_type === "group") {
    return `/identity?tab=groups&objectId=${encodeURIComponent(value.principal_id)}`;
  }
  if (value.object_type === "enterprise_app") {
    return `/identity?tab=enterprise-apps&objectId=${encodeURIComponent(value.principal_id)}`;
  }
  return "";
}

function RoleCard({ role }: { role: SecurityDirectoryRoleReviewRole }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-900">{role.display_name}</h3>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${azureSecurityToneClasses(privilegeTone(role.privilege_level))}`}>
              {role.privilege_level === "critical" ? "Critical role" : role.privilege_level === "elevated" ? "Elevated role" : "Limited role"}
            </span>
          </div>
          <div className="mt-2 text-sm text-slate-500">{role.description || role.role_id}</div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Direct members</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">{role.member_count.toLocaleString()}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Flagged members</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">{role.flagged_member_count.toLocaleString()}</div>
        </div>
      </div>

      {role.flags.length > 0 ? (
        <div className="mt-4 space-y-2">
          {role.flags.map((flag) => (
            <div key={`${role.role_id}-${flag}`} className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {flag}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function MembershipCard({ membership }: { membership: SecurityDirectoryRoleReviewMembership }) {
  const route = buildPrincipalRoute(membership);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-900">{membership.display_name}</h3>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${azureSecurityToneClasses(membershipTone(membership.status))}`}>
              {membership.status === "critical" ? "Action needed" : membership.status === "warning" ? "Needs review" : "Healthy"}
            </span>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
              {principalTypeLabel(membership)}
            </span>
          </div>
          <div className="mt-1 text-sm text-slate-500">{membership.principal_name || membership.principal_id}</div>
        </div>
        {route ? (
          <Link
            to={route}
            className="inline-flex items-center rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            Open source record
          </Link>
        ) : null}
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Directory role</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{membership.role_name}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Role level</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{membership.privilege_level}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Last successful sign-in</div>
          <div className="mt-1 text-sm font-medium text-slate-900">
            {membership.object_type === "user" ? (membership.last_successful_utc ? formatDateTime(membership.last_successful_utc) : "No sign-in recorded") : "Not applicable"}
          </div>
        </div>
      </div>

      {membership.flags.length > 0 ? (
        <div className="mt-4 space-y-2">
          {membership.flags.map((flag) => (
            <div
              key={`${membership.role_id}-${membership.principal_id}-${flag}`}
              className={`rounded-xl px-4 py-3 text-sm ${
                membership.status === "critical"
                  ? "bg-rose-50 text-rose-800"
                  : membership.status === "warning"
                    ? "bg-amber-50 text-amber-800"
                    : "bg-emerald-50 text-emerald-800"
              }`}
            >
              {flag}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export default function AzureSecurityDirectoryRoleReviewPage() {
  const [search, setSearch] = useState("");
  const [principalFilter, setPrincipalFilter] = useState<PrincipalFilter>("all");
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("all");
  const deferredSearch = useDeferredValue(search);

  const query = useQuery({
    queryKey: ["azure", "security", "directory-role-review"],
    queryFn: () => api.getAzureSecurityDirectoryRoleReview(),
    ...getPollingQueryOptions("slow_5m"),
  });

  const filteredMemberships = useMemo(() => {
    const rows = query.data?.memberships ?? [];
    return rows.filter((item) => {
      if (principalFilter !== "all" && principalFilterKey(item) !== principalFilter) {
        return false;
      }
      if (riskFilter === "critical" && item.privilege_level !== "critical") return false;
      if (riskFilter === "elevated" && item.privilege_level !== "elevated") return false;
      if (riskFilter === "flagged" && !(item.status !== "healthy" || item.flags.length > 0)) return false;
      return matchesSearch([item.display_name, item.principal_name, item.role_name, item.flags], deferredSearch);
    });
  }, [deferredSearch, principalFilter, query.data?.memberships, riskFilter]);

  const filteredRoles = useMemo(() => {
    const rows = query.data?.roles ?? [];
    return rows.filter((item) => matchesSearch([item.display_name, item.description, item.flags], deferredSearch));
  }, [deferredSearch, query.data?.roles]);
  const rolesPagination = useSecurityReviewPagination(
    `${deferredSearch}|${principalFilter}|${riskFilter}|roles|${filteredRoles.length}`,
    filteredRoles.length,
  );
  const membershipsPagination = useSecurityReviewPagination(
    `${deferredSearch}|${principalFilter}|${riskFilter}|memberships|${filteredMemberships.length}`,
    filteredMemberships.length,
  );
  const visibleRoles = useMemo(
    () => sliceSecurityReviewPage(filteredRoles, rolesPagination.pageStart, rolesPagination.pageSize),
    [filteredRoles, rolesPagination.pageSize, rolesPagination.pageStart],
  );
  const visibleMemberships = useMemo(
    () => sliceSecurityReviewPage(filteredMemberships, membershipsPagination.pageStart, membershipsPagination.pageSize),
    [filteredMemberships, membershipsPagination.pageSize, membershipsPagination.pageStart],
  );

  if (query.isLoading) {
    return <AzurePageSkeleton titleWidth="w-72" subtitleWidth="w-[46rem]" statCount={6} sectionCount={4} />;
  }

  if (query.isError || !query.data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load directory role membership review: {query.error instanceof Error ? query.error.message : "Unknown error"}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <AzureSecurityLaneHero
        title="Directory Role Membership Review"
        accent="violet"
        description="Review direct Microsoft Entra directory-role memberships with live role-member lookup, then ground the results against cached user freshness and principal posture before you pivot into raw identity records."
        refreshLabel="Directory refresh"
        refreshValue={formatTimestamp(query.data.directory_last_refresh)}
        actions={[
          { label: "Back to Security workspace", to: "/security", tone: "secondary" },
          { label: "Open Identity Review", to: "/security/identity-review" },
          { label: "Open Access Review", to: "/security/access-review", tone: "secondary" },
        ]}
      />

      {!query.data.access_available ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-amber-900">Access required</h2>
          <div className="mt-3 rounded-xl bg-white/70 px-4 py-3 text-sm text-amber-900">{query.data.access_message}</div>
        </section>
      ) : (
        <>
          <section className="grid gap-4 xl:grid-cols-3 md:grid-cols-2">
            {query.data.metrics.map((metric) => (
              <AzureSecurityMetricCard key={metric.key} label={metric.label} value={metric.value} detail={metric.detail} tone={metric.tone} />
            ))}
          </section>

          {query.data.warnings.length > 0 ? (
            <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
              <h2 className="text-lg font-semibold text-amber-900">Coverage warnings</h2>
              <div className="mt-3 space-y-2">
                {query.data.warnings.map((warning) => (
                  <div key={warning} className="rounded-xl bg-white/70 px-4 py-3 text-sm text-amber-900">
                    {warning}
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Scope and filters</h2>
                <div className="mt-1 text-sm text-slate-500">Search roles, principals, or flags to focus the direct membership review queue.</div>
              </div>
              <div className="text-sm text-slate-500">{filteredMemberships.length.toLocaleString()} direct membership(s)</div>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_180px]">
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search roles, principals, or flags..."
                className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
              />
              <select
                value={principalFilter}
                onChange={(event) => setPrincipalFilter(event.target.value as PrincipalFilter)}
                className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
              >
                <option value="all">All principals</option>
                <option value="user">Users</option>
                <option value="group">Groups</option>
                <option value="service_principal">Service principals</option>
              </select>
              <select
                value={riskFilter}
                onChange={(event) => setRiskFilter(event.target.value as RiskFilter)}
                className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
              >
                <option value="all">All role levels</option>
                <option value="critical">Critical roles</option>
                <option value="elevated">Elevated roles</option>
                <option value="flagged">Flagged only</option>
              </select>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Role summary</h2>
                <div className="mt-1 text-sm text-slate-500">Each directory role below is summarized with direct member counts and flagged-member totals.</div>
              </div>
              <div className="text-sm text-slate-500">{filteredRoles.length.toLocaleString()} role(s)</div>
            </div>

            <div className="mt-5 grid gap-4 xl:grid-cols-2">
              {filteredRoles.length > 0 ? (
                <>
                  <div className="xl:col-span-2">
                    <SecurityReviewPagination
                      count={filteredRoles.length}
                      currentPage={rolesPagination.currentPage}
                      pageSize={rolesPagination.pageSize}
                      setCurrentPage={rolesPagination.setCurrentPage}
                      setPageSize={rolesPagination.setPageSize}
                      totalPages={rolesPagination.totalPages}
                      noun="matching directory role(s)"
                    />
                  </div>
                  {visibleRoles.map((role) => <RoleCard key={role.role_id} role={role} />)}
                </>
              ) : (
                <div className="rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">No directory roles match the current search.</div>
              )}
            </div>
          </section>

          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Direct membership review queue</h2>
                <div className="mt-1 text-sm text-slate-500">Prioritized direct Entra role memberships with user freshness and principal-type flags.</div>
              </div>
            </div>

            {filteredMemberships.length > 0 ? (
              <div className="grid gap-4 xl:grid-cols-2">
                <div className="xl:col-span-2">
                  <SecurityReviewPagination
                    count={filteredMemberships.length}
                    currentPage={membershipsPagination.currentPage}
                    pageSize={membershipsPagination.pageSize}
                    setCurrentPage={membershipsPagination.setCurrentPage}
                    setPageSize={membershipsPagination.setPageSize}
                    totalPages={membershipsPagination.totalPages}
                    noun="matching direct membership record(s)"
                  />
                </div>
                {visibleMemberships.map((membership) => (
                  <MembershipCard key={`${membership.role_id}-${membership.principal_id}`} membership={membership} />
                ))}
              </div>
            ) : (
              <div className="rounded-2xl border border-slate-200 bg-white px-5 py-6 text-sm text-slate-500 shadow-sm">
                No direct directory-role memberships matched the current filters.
              </div>
            )}
          </section>
        </>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Scope notes</h2>
        <div className="mt-4 space-y-2">
          {query.data.scope_notes.map((note) => (
            <div key={note} className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
              {note}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
