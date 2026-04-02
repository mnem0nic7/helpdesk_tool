import { useDeferredValue, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import {
  api,
  type SecurityAccessReviewAssignment,
  type SecurityAccessReviewBreakGlassCandidate,
  type SecurityAccessReviewMetric,
  type SecurityAccessReviewPrincipal,
} from "../lib/api.ts";

type PrincipalFilter = "all" | "user" | "service_principal" | "group";
type RiskFilter = "all" | "critical" | "elevated" | "flagged";

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No refresh recorded";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function toneClasses(tone: "slate" | "sky" | "emerald" | "amber" | "rose"): string {
  if (tone === "sky") return "bg-sky-50 text-sky-700";
  if (tone === "emerald") return "bg-emerald-50 text-emerald-700";
  if (tone === "amber") return "bg-amber-50 text-amber-700";
  if (tone === "rose") return "bg-rose-50 text-rose-700";
  return "bg-slate-100 text-slate-600";
}

function privilegeTone(value: "critical" | "elevated" | "limited"): "rose" | "amber" | "slate" {
  if (value === "critical") return "rose";
  if (value === "elevated") return "amber";
  return "slate";
}

function principalFilterKey(principalType: string): PrincipalFilter {
  const normalized = principalType.trim().toLowerCase();
  if (normalized === "user") return "user";
  if (normalized === "serviceprincipal") return "service_principal";
  if (normalized === "group" || normalized === "foreigngroup") return "group";
  return "all";
}

function principalTypeLabel(principalType: string): string {
  const normalized = principalType.trim().toLowerCase();
  if (normalized === "serviceprincipal") return "Service principal";
  if (normalized === "foreigngroup") return "Foreign group";
  if (normalized === "group") return "Group";
  if (normalized === "user") return "User";
  return principalType || "Unknown";
}

function buildPrincipalRoute(item: { object_type: string; principal_id: string }): string {
  if (item.object_type === "user") {
    return `/users?userId=${encodeURIComponent(item.principal_id)}`;
  }
  if (item.object_type === "group") {
    return `/identity?tab=groups&objectId=${encodeURIComponent(item.principal_id)}`;
  }
  if (item.object_type === "enterprise_app") {
    return `/identity?tab=enterprise-apps&objectId=${encodeURIComponent(item.principal_id)}`;
  }
  return "";
}

function matchesSearch(haystacks: Array<string | string[]>, search: string): boolean {
  if (!search) return true;
  const normalizedSearch = search.toLowerCase();
  return haystacks
    .flatMap((item) => (Array.isArray(item) ? item : [item]))
    .some((item) => String(item || "").toLowerCase().includes(normalizedSearch));
}

function MetricCard({ metric }: { metric: SecurityAccessReviewMetric }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{metric.label}</div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${toneClasses(metric.tone)}`}>{metric.label}</span>
      </div>
      <div className="mt-3 text-3xl font-semibold text-slate-900">{metric.value.toLocaleString()}</div>
      <p className="mt-2 text-sm leading-6 text-slate-600">{metric.detail}</p>
    </section>
  );
}

function PrincipalCard({ principal }: { principal: SecurityAccessReviewPrincipal }) {
  const route = buildPrincipalRoute(principal);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-900">{principal.display_name}</h3>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${toneClasses(privilegeTone(principal.highest_privilege))}`}>
              {principal.highest_privilege === "critical" ? "Critical" : "Elevated"}
            </span>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
              {principalTypeLabel(principal.principal_type)}
            </span>
          </div>
          <div className="mt-2 text-sm text-slate-500">{principal.principal_name || principal.principal_id}</div>
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
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Assignments</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">{principal.assignment_count.toLocaleString()}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Scopes</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">{principal.scope_count.toLocaleString()}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Last successful sign-in</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{formatTimestamp(principal.last_successful_utc)}</div>
        </div>
      </div>

      <div className="mt-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Roles</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {principal.role_names.map((roleName) => (
            <span key={`${principal.principal_id}-${roleName}`} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
              {roleName}
            </span>
          ))}
        </div>
      </div>

      {principal.flags.length > 0 ? (
        <div className="mt-4 space-y-2">
          {principal.flags.map((flag) => (
            <div key={`${principal.principal_id}-${flag}`} className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {flag}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function BreakGlassCard({ candidate }: { candidate: SecurityAccessReviewBreakGlassCandidate }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-slate-900">{candidate.display_name}</h3>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${candidate.has_privileged_access ? "bg-rose-50 text-rose-700" : "bg-slate-100 text-slate-600"}`}>
              {candidate.has_privileged_access ? "Privileged access" : "Watchlist"}
            </span>
          </div>
          <div className="mt-1 text-sm text-slate-500">{candidate.principal_name || candidate.user_id}</div>
        </div>
        <Link
          to={`/users?userId=${encodeURIComponent(candidate.user_id)}`}
          className="inline-flex items-center rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          Open user
        </Link>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {candidate.matched_terms.map((term) => (
          <span key={`${candidate.user_id}-${term}`} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
            {term}
          </span>
        ))}
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Privileged assignments</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">{candidate.privileged_assignment_count.toLocaleString()}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Last successful sign-in</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{formatTimestamp(candidate.last_successful_utc)}</div>
        </div>
      </div>

      {candidate.flags.length > 0 ? (
        <div className="mt-4 space-y-2">
          {candidate.flags.map((flag) => (
            <div key={`${candidate.user_id}-${flag}`} className="rounded-xl bg-sky-50 px-4 py-3 text-sm text-sky-800">
              {flag}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export default function AzureSecurityAccessReviewPage() {
  const [search, setSearch] = useState("");
  const [principalFilter, setPrincipalFilter] = useState<PrincipalFilter>("all");
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("all");
  const deferredSearch = useDeferredValue(search);

  const query = useQuery({
    queryKey: ["azure", "security", "access-review"],
    queryFn: () => api.getAzureSecurityAccessReview(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const filteredAssignments = useMemo(() => {
    const rows = query.data?.assignments ?? [];
    return rows.filter((item) => {
      if (principalFilter !== "all" && principalFilterKey(item.principal_type) !== principalFilter) {
        return false;
      }
      if (riskFilter === "critical" && item.privilege_level !== "critical") return false;
      if (riskFilter === "elevated" && item.privilege_level !== "elevated") return false;
      if (riskFilter === "flagged" && item.flags.length === 0) return false;
      return matchesSearch(
        [item.display_name, item.principal_name, item.role_name, item.scope, item.subscription_name, item.flags],
        deferredSearch,
      );
    });
  }, [deferredSearch, principalFilter, query.data?.assignments, riskFilter]);

  const filteredPrincipals = useMemo(() => {
    const rows = query.data?.flagged_principals ?? [];
    return rows.filter((item) => {
      if (principalFilter !== "all" && principalFilterKey(item.principal_type) !== principalFilter) {
        return false;
      }
      if (riskFilter === "critical" && item.highest_privilege !== "critical") return false;
      if (riskFilter === "elevated" && item.highest_privilege !== "elevated") return false;
      if (riskFilter === "flagged" && item.flags.length === 0) return false;
      return matchesSearch([item.display_name, item.principal_name, item.role_names, item.flags], deferredSearch);
    });
  }, [deferredSearch, principalFilter, query.data?.flagged_principals, riskFilter]);

  const filteredBreakGlass = useMemo(() => {
    const rows = query.data?.break_glass_candidates ?? [];
    return rows.filter((item) =>
      matchesSearch([item.display_name, item.principal_name, item.matched_terms, item.flags], deferredSearch),
    );
  }, [deferredSearch, query.data?.break_glass_candidates]);

  if (query.isLoading) {
    return <AzurePageSkeleton titleWidth="w-64" subtitleWidth="w-[42rem]" statCount={6} sectionCount={4} />;
  }

  if (query.isError || !query.data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load the privileged access review: {query.error instanceof Error ? query.error.message : "Unknown error"}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-sky-50 p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <div className="text-xs font-semibold uppercase tracking-[0.24em] text-sky-700">Azure Security</div>
            <h1 className="mt-3 text-3xl font-bold text-slate-900">Privileged Access Review</h1>
            <p className="mt-3 text-sm leading-7 text-slate-600">
              Review elevated Azure RBAC assignments, surface risky guest or stale privileged accounts, and keep a watchlist of emergency or
              break-glass identities from the same Azure data already cached in this workspace.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              to="/security"
              className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Back to Security workspace
            </Link>
            <Link
              to="/security/copilot"
              className="inline-flex items-center rounded-lg bg-sky-700 px-3 py-2 text-sm font-medium text-white transition hover:bg-sky-800"
            >
              Open Security Copilot
            </Link>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2">
          <div className="rounded-2xl border border-white/70 bg-white/80 px-4 py-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Inventory refresh</div>
            <div className="mt-1 text-sm font-medium text-slate-900">{formatTimestamp(query.data.inventory_last_refresh)}</div>
          </div>
          <div className="rounded-2xl border border-white/70 bg-white/80 px-4 py-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Directory refresh</div>
            <div className="mt-1 text-sm font-medium text-slate-900">{formatTimestamp(query.data.directory_last_refresh)}</div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-3 md:grid-cols-2">
        {query.data.metrics.map((metric) => (
          <MetricCard key={metric.key} metric={metric} />
        ))}
      </section>

      {query.data.warnings.length > 0 ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-amber-900">Review warnings</h2>
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
            <div className="mt-1 text-sm text-slate-500">Tune the assignment list to the principals and risk tiers you want to review right now.</div>
          </div>
          <div className="text-sm text-slate-500">{filteredAssignments.length.toLocaleString()} matching privileged assignment(s)</div>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_180px]">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search principals, roles, scopes, or flags..."
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
          />
          <select
            value={principalFilter}
            onChange={(event) => setPrincipalFilter(event.target.value as PrincipalFilter)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
          >
            <option value="all">All principals</option>
            <option value="user">Users</option>
            <option value="service_principal">Service principals</option>
            <option value="group">Groups</option>
          </select>
          <select
            value={riskFilter}
            onChange={(event) => setRiskFilter(event.target.value as RiskFilter)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
          >
            <option value="all">All risk tiers</option>
            <option value="critical">Critical only</option>
            <option value="elevated">Elevated only</option>
            <option value="flagged">Flagged only</option>
          </select>
        </div>

        <div className="mt-4 grid gap-2">
          {query.data.scope_notes.map((note) => (
            <div key={note} className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
              {note}
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Flagged principals</h2>
            <div className="mt-1 text-sm text-slate-500">Highest-signal principals with privileged Azure RBAC access and the reasons they deserve review.</div>
          </div>
          <div className="text-sm text-slate-500">{filteredPrincipals.length.toLocaleString()} principal(s) in view</div>
        </div>

        {filteredPrincipals.length === 0 ? (
          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-10 text-center text-sm text-slate-500 shadow-sm">
            No privileged principals match the current filters.
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {filteredPrincipals.slice(0, 12).map((principal) => (
              <PrincipalCard key={principal.principal_id} principal={principal} />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Break-glass watchlist</h2>
            <div className="mt-1 text-sm text-slate-500">
              Accounts whose naming suggests emergency or administrative use, prioritized when they also hold privileged Azure RBAC access.
            </div>
          </div>
          <div className="text-sm text-slate-500">{filteredBreakGlass.length.toLocaleString()} candidate account(s)</div>
        </div>

        {filteredBreakGlass.length === 0 ? (
          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-10 text-center text-sm text-slate-500 shadow-sm">
            No break-glass candidates matched the current search.
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {filteredBreakGlass.map((candidate) => (
              <BreakGlassCard key={candidate.user_id} candidate={candidate} />
            ))}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-slate-900">Privileged assignment table</h2>
          <div className="mt-1 text-sm text-slate-500">Searchable Azure RBAC assignments in the current review scope.</div>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Principal</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Scope</th>
                <th className="px-4 py-3">Flags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white">
              {filteredAssignments.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-sm text-slate-500">
                    No privileged assignments match the current filters.
                  </td>
                </tr>
              ) : null}
              {filteredAssignments.map((assignment: SecurityAccessReviewAssignment) => {
                const route = buildPrincipalRoute(assignment);
                return (
                  <tr key={assignment.assignment_id}>
                    <td className="px-4 py-4 align-top">
                      <div className="font-medium text-slate-900">{assignment.display_name}</div>
                      <div className="mt-1 text-xs text-slate-500">{assignment.principal_name || assignment.principal_id}</div>
                      {route ? (
                        <Link to={route} className="mt-2 inline-flex text-xs font-medium text-sky-700 hover:text-sky-800">
                          Open source record
                        </Link>
                      ) : null}
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="flex flex-col gap-2">
                        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
                          {principalTypeLabel(assignment.principal_type)}
                        </span>
                        {assignment.user_type ? <span className="text-xs text-slate-500">{assignment.user_type}</span> : null}
                      </div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="font-medium text-slate-900">{assignment.role_name}</div>
                      <span className={`mt-2 inline-flex rounded-full px-3 py-1 text-xs font-semibold ${toneClasses(privilegeTone(assignment.privilege_level))}`}>
                        {assignment.privilege_level === "critical" ? "Critical" : "Elevated"}
                      </span>
                    </td>
                    <td className="px-4 py-4 align-top">
                      <div className="font-medium text-slate-900">{assignment.subscription_name || assignment.subscription_id}</div>
                      <div className="mt-1 break-all text-xs text-slate-500">{assignment.scope}</div>
                    </td>
                    <td className="px-4 py-4 align-top">
                      {assignment.flags.length === 0 ? (
                        <span className="text-xs text-slate-400">No extra flags</span>
                      ) : (
                        <div className="space-y-2">
                          {assignment.flags.map((flag) => (
                            <div key={`${assignment.assignment_id}-${flag}`} className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
                              {flag}
                            </div>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
