import { useDeferredValue, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import { AzureSecurityLaneHero, AzureSecurityMetricCard, azureSecurityToneClasses } from "../components/AzureSecurityLane.tsx";
import SecurityReviewPagination, { sliceSecurityReviewPage, useSecurityReviewPagination } from "../components/SecurityReviewPagination.tsx";
import { api, type SecurityConditionalAccessChange, type SecurityConditionalAccessPolicy } from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";
import { formatDateTime } from "../lib/azureSecurityUsers.ts";

type ImpactFilter = "all" | "critical" | "warning" | "healthy" | "info";
type ScopeFilter = "all" | "broad" | "exceptions" | "disabled";

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No refresh recorded";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function titleCase(value: string): string {
  if (!value) return "Unknown";
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function impactTone(level: "critical" | "warning" | "healthy" | "info"): "rose" | "amber" | "emerald" | "violet" {
  if (level === "critical") return "rose";
  if (level === "warning") return "amber";
  if (level === "healthy") return "emerald";
  return "violet";
}

function matchesPolicySearch(policy: SecurityConditionalAccessPolicy, search: string): boolean {
  if (!search) return true;
  return [
    policy.display_name,
    policy.state,
    policy.user_scope_summary,
    policy.application_scope_summary,
    ...policy.grant_controls,
    ...policy.session_controls,
    ...policy.risk_tags,
  ]
    .join(" ")
    .toLowerCase()
    .includes(search.toLowerCase());
}

function matchesChangeSearch(change: SecurityConditionalAccessChange, search: string): boolean {
  if (!search) return true;
  return [
    change.activity_display_name,
    change.target_policy_name,
    change.initiated_by_display_name,
    change.initiated_by_principal_name,
    change.change_summary,
    ...change.modified_properties,
    ...change.flags,
  ]
    .join(" ")
    .toLowerCase()
    .includes(search.toLowerCase());
}

function policyMatchesScope(policy: SecurityConditionalAccessPolicy, scope: ScopeFilter): boolean {
  if (scope === "all") return true;
  if (scope === "broad") {
    return policy.risk_tags.includes("all_users_scope") || policy.risk_tags.includes("role_targeted") || policy.risk_tags.includes("guest_or_external_scope");
  }
  if (scope === "exceptions") return policy.risk_tags.includes("exception_surface");
  return policy.state.toLowerCase() === "disabled" || policy.risk_tags.includes("disabled");
}

function PolicyCard({ policy }: { policy: SecurityConditionalAccessPolicy }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-900">{policy.display_name}</h3>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${azureSecurityToneClasses(impactTone(policy.impact_level))}`}>
              {titleCase(policy.impact_level)}
            </span>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${policy.state.toLowerCase() === "enabled" ? "bg-emerald-50 text-emerald-700" : policy.state.toLowerCase() === "reportonly" ? "bg-amber-50 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
              {policy.state || "Unknown state"}
            </span>
          </div>
          <div className="mt-1 text-sm text-slate-500">Modified {policy.modified_date_time ? formatDateTime(policy.modified_date_time) : "No timestamp recorded"}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            to="/security/copilot"
            className="inline-flex items-center rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            Investigate in copilot
          </Link>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">User scope</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{policy.user_scope_summary}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">App scope</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{policy.application_scope_summary}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Grant controls</div>
          <div className="mt-1 text-sm font-medium text-slate-900">
            {policy.grant_controls.length > 0 ? policy.grant_controls.join(", ") : "No grant controls summarized"}
          </div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Session controls</div>
          <div className="mt-1 text-sm font-medium text-slate-900">
            {policy.session_controls.length > 0 ? policy.session_controls.join(", ") : "None summarized"}
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {policy.risk_tags.map((tag) => (
          <span key={`${policy.policy_id}-${tag}`} className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-800">
            {titleCase(tag)}
          </span>
        ))}
      </div>
    </section>
  );
}

function ChangeCard({ change }: { change: SecurityConditionalAccessChange }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-900">{change.target_policy_name || "Conditional Access change"}</h3>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${azureSecurityToneClasses(impactTone(change.impact_level))}`}>
              {titleCase(change.impact_level)}
            </span>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${change.initiated_by_type === "app" ? "bg-violet-50 text-violet-700" : "bg-slate-100 text-slate-600"}`}>
              {change.initiated_by_type === "app" ? "Service principal" : change.initiated_by_type === "user" ? "User" : "Unknown actor"}
            </span>
          </div>
          <div className="mt-1 text-sm text-slate-500">
            {change.activity_date_time ? formatDateTime(change.activity_date_time) : "No timestamp recorded"}
            {change.initiated_by_display_name ? ` - ${change.initiated_by_display_name}` : ""}
            {change.initiated_by_principal_name ? ` - ${change.initiated_by_principal_name}` : ""}
          </div>
        </div>
        <div className="text-sm text-slate-500">{change.result || "Success"}</div>
      </div>

      <div className="mt-4 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-700">{change.change_summary}</div>

      {change.modified_properties.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {change.modified_properties.map((property) => (
            <span key={`${change.event_id}-${property}`} className="rounded-full bg-violet-50 px-3 py-1 text-xs font-medium text-violet-800">
              {property}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-4 space-y-2">
        {change.flags.map((flag) => (
          <div
            key={`${change.event_id}-${flag}`}
            className={`rounded-xl px-4 py-3 text-sm ${
              change.impact_level === "critical"
                ? "bg-rose-50 text-rose-800"
                : change.impact_level === "warning"
                  ? "bg-amber-50 text-amber-800"
                  : "bg-slate-100 text-slate-700"
            }`}
          >
            {flag}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function AzureSecurityConditionalAccessTrackerPage() {
  const [search, setSearch] = useState("");
  const [impactFilter, setImpactFilter] = useState<ImpactFilter>("all");
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>("all");
  const deferredSearch = useDeferredValue(search);

  const query = useQuery({
    queryKey: ["azure", "security", "conditional-access-tracker"],
    queryFn: () => api.getAzureSecurityConditionalAccessTracker(),
    ...getPollingQueryOptions("slow_5m"),
  });

  const filteredPolicies = useMemo(() => {
    const rows = query.data?.policies ?? [];
    return rows.filter((policy) => {
      if (impactFilter !== "all" && policy.impact_level !== impactFilter) return false;
      if (!policyMatchesScope(policy, scopeFilter)) return false;
      return matchesPolicySearch(policy, deferredSearch);
    });
  }, [deferredSearch, impactFilter, query.data?.policies, scopeFilter]);

  const filteredChanges = useMemo(() => {
    const rows = query.data?.changes ?? [];
    return rows.filter((change) => {
      if (impactFilter !== "all" && change.impact_level !== impactFilter) return false;
      return matchesChangeSearch(change, deferredSearch);
    });
  }, [deferredSearch, impactFilter, query.data?.changes]);
  const policiesPagination = useSecurityReviewPagination(
    `${deferredSearch}|${impactFilter}|${scopeFilter}|policies|${filteredPolicies.length}`,
    filteredPolicies.length,
  );
  const changesPagination = useSecurityReviewPagination(
    `${deferredSearch}|${impactFilter}|${scopeFilter}|changes|${filteredChanges.length}`,
    filteredChanges.length,
  );
  const visiblePolicies = useMemo(
    () => sliceSecurityReviewPage(filteredPolicies, policiesPagination.pageStart, policiesPagination.pageSize),
    [filteredPolicies, policiesPagination.pageSize, policiesPagination.pageStart],
  );
  const visibleChanges = useMemo(
    () => sliceSecurityReviewPage(filteredChanges, changesPagination.pageStart, changesPagination.pageSize),
    [changesPagination.pageSize, changesPagination.pageStart, filteredChanges],
  );

  if (query.isLoading) {
    return <AzurePageSkeleton titleWidth="w-80" subtitleWidth="w-[46rem]" statCount={5} sectionCount={4} />;
  }

  if (query.isError || !query.data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Conditional Access change tracking: {query.error instanceof Error ? query.error.message : "Unknown error"}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <AzureSecurityLaneHero
        title="Conditional Access Change Tracker"
        accent="amber"
        description="Track Conditional Access policy drift, recent add or update operations, broad-scope coverage, and exclusion-based exception surfaces before they become tenant-impacting outages."
        refreshLabel="Conditional Access cache"
        refreshValue={formatTimestamp(query.data.conditional_access_last_refresh)}
        actions={[
          { label: "Back to Security workspace", to: "/security", tone: "secondary" },
          { label: "Open Security Copilot", to: "/security/copilot" },
          { label: "Open Identity Review", to: "/security/identity-review", tone: "secondary" },
        ]}
      />

      {!query.data.access_available ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-amber-900">Access required</h2>
          <div className="mt-3 text-sm text-amber-900">{query.data.access_message}</div>
        </section>
      ) : null}

      <section className="grid gap-4 xl:grid-cols-5 md:grid-cols-2">
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
            <h2 className="text-lg font-semibold text-slate-900">Policy watchlist</h2>
            <div className="mt-1 text-sm text-slate-500">Filter current Conditional Access policies by impact, scope shape, and recent drift signals.</div>
          </div>
          <div className="text-sm text-slate-500">{filteredPolicies.length.toLocaleString()} policy item(s)</div>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_180px]">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search policy names, tags, actors, or changed properties..."
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 shadow-sm focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-100"
          />
          <select
            value={impactFilter}
            onChange={(event) => setImpactFilter(event.target.value as ImpactFilter)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 shadow-sm focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-100"
          >
            <option value="all">All impact levels</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="healthy">Healthy</option>
            <option value="info">Info</option>
          </select>
          <select
            value={scopeFilter}
            onChange={(event) => setScopeFilter(event.target.value as ScopeFilter)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 shadow-sm focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-100"
          >
            <option value="all">All scope shapes</option>
            <option value="broad">Broad policies</option>
            <option value="exceptions">Exception surfaces</option>
            <option value="disabled">Disabled / report-only</option>
          </select>
        </div>
      </section>

      <section className="space-y-4">
        {filteredPolicies.length > 0 ? (
          <>
            <SecurityReviewPagination
              count={filteredPolicies.length}
              currentPage={policiesPagination.currentPage}
              pageSize={policiesPagination.pageSize}
              setCurrentPage={policiesPagination.setCurrentPage}
              setPageSize={policiesPagination.setPageSize}
              totalPages={policiesPagination.totalPages}
              noun="matching policy record(s)"
            />
            {visiblePolicies.map((policy) => <PolicyCard key={policy.policy_id} policy={policy} />)}
          </>
        ) : (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-sm text-slate-500">
            No policies match the current filter state.
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Recent policy changes</h2>
            <div className="mt-1 text-sm text-slate-500">Review recent Conditional Access adds, updates, and deletes from the cached directory audit window.</div>
          </div>
          <div className="text-sm text-slate-500">{filteredChanges.length.toLocaleString()} change event(s)</div>
        </div>
      </section>

      <section className="space-y-4">
        {filteredChanges.length > 0 ? (
          <>
            <SecurityReviewPagination
              count={filteredChanges.length}
              currentPage={changesPagination.currentPage}
              pageSize={changesPagination.pageSize}
              setCurrentPage={changesPagination.setCurrentPage}
              setPageSize={changesPagination.setPageSize}
              totalPages={changesPagination.totalPages}
              noun="matching change event(s)"
            />
            {visibleChanges.map((change) => <ChangeCard key={change.event_id} change={change} />)}
          </>
        ) : (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-sm text-slate-500">
            No change events match the current filter state.
          </div>
        )}
      </section>
    </div>
  );
}
