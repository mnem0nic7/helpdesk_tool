import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type AzureSavingsOpportunity } from "../lib/api.ts";
import AzureSourceBadge from "../components/AzureSourceBadge.tsx";
import AzureSavingsHighlightsSection, { formatAzureCurrency } from "../components/AzureSavingsHighlightsSection.tsx";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";

type SavingsSortKey =
  | "title"
  | "category"
  | "subscription"
  | "resource_group"
  | "effort"
  | "risk"
  | "confidence"
  | "estimated_monthly_savings";

const effortOptions = ["low", "medium", "high"] as const;
const confidenceOptions = ["high", "medium", "low"] as const;

function StatCard({
  label,
  value,
  sub,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${tone}`}>{value}</div>
      {sub ? <div className="mt-1 text-xs text-slate-400">{sub}</div> : null}
    </div>
  );
}

function toneBadgeClass(value: string, tone: "effort" | "risk" | "confidence"): string {
  const normalized = value.toLowerCase();
  if (tone === "confidence") {
    if (normalized === "high") return "bg-emerald-100 text-emerald-700";
    if (normalized === "medium") return "bg-amber-100 text-amber-700";
    return "bg-slate-100 text-slate-600";
  }
  if (normalized === "low") return "bg-emerald-100 text-emerald-700";
  if (normalized === "medium") return "bg-amber-100 text-amber-700";
  return "bg-rose-100 text-rose-700";
}

function ToneBadge({ label, value, tone }: { label: string; value: string; tone: "effort" | "risk" | "confidence" }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${toneBadgeClass(value, tone)}`}>
      {label}: {value}
    </span>
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
        active
          ? "bg-sky-700 text-white"
          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
      }`}
    >
      {label}
    </button>
  );
}

function OpportunityDrawer({
  opportunity,
  onClose,
}: {
  opportunity: AzureSavingsOpportunity | null;
  onClose: () => void;
}) {
  if (!opportunity) return null;

  return (
    <aside className="fixed inset-y-0 right-0 z-30 w-full max-w-2xl overflow-y-auto border-l border-slate-200 bg-white shadow-2xl">
      <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-slate-200 bg-white px-6 py-5">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{opportunity.category}</div>
          <h2 className="mt-1 text-2xl font-semibold text-slate-900">{opportunity.title}</h2>
          <p className="mt-2 text-sm text-slate-600">{opportunity.summary}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
        >
          Close
        </button>
      </div>

      <div className="space-y-6 px-6 py-6">
        <div className="grid gap-4 md:grid-cols-3">
          <StatCard
            label="Estimated Savings"
            value={opportunity.quantified ? formatAzureCurrency(opportunity.estimated_monthly_savings, opportunity.currency) : "Unquantified"}
            tone={opportunity.quantified ? "text-emerald-700" : "text-slate-900"}
          />
          <StatCard
            label="Current Monthly Cost"
            value={formatAzureCurrency(opportunity.current_monthly_cost, opportunity.currency)}
          />
          <StatCard
            label="Scope"
            value={opportunity.resource_name || opportunity.resource_type || "Tenant-wide"}
            sub={opportunity.subscription_name || opportunity.subscription_id || undefined}
          />
        </div>

        <section className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Triage</div>
          <div className="mt-3 flex flex-wrap gap-2">
            <ToneBadge label="Effort" value={opportunity.effort} tone="effort" />
            <ToneBadge label="Risk" value={opportunity.risk} tone="risk" />
            <ToneBadge label="Confidence" value={opportunity.confidence} tone="confidence" />
          </div>
          <div className="mt-4 grid gap-3 text-sm text-slate-600 md:grid-cols-2">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Estimate basis</div>
              <div className="mt-1">{opportunity.estimate_basis}</div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Follow-up page</div>
              <div className="mt-1">
                <Link to={opportunity.follow_up_route} className="text-sky-700 hover:text-sky-800">
                  {opportunity.follow_up_route}
                </Link>
              </div>
            </div>
          </div>
        </section>

        <section>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence</div>
          <div className="mt-3 overflow-hidden rounded-2xl border border-slate-200">
            <table className="min-w-full text-left text-sm">
              <tbody>
                {opportunity.evidence.map((row, index) => (
                  <tr key={`${row.label}-${index}`} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/70"}>
                    <td className="w-48 px-4 py-3 font-medium text-slate-700">{row.label}</td>
                    <td className="px-4 py-3 text-slate-600">{row.value}</td>
                  </tr>
                ))}
                <tr className={opportunity.evidence.length % 2 === 0 ? "bg-white" : "bg-slate-50/70"}>
                  <td className="w-48 px-4 py-3 font-medium text-slate-700">Resource ID</td>
                  <td className="px-4 py-3 break-all text-slate-600">{opportunity.resource_id || "—"}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recommended Steps</div>
          <ol className="mt-3 space-y-2 text-sm text-slate-700">
            {opportunity.recommended_steps.map((step, index) => (
              <li key={`${opportunity.id}-step-${index}`} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                <span className="font-semibold text-slate-900">{index + 1}.</span> {step}
              </li>
            ))}
          </ol>
        </section>

        <section className="flex flex-wrap gap-3">
          <a
            href={opportunity.portal_url}
            target="_blank"
            rel="noreferrer"
            className="rounded-xl bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800"
          >
            Open in Azure Portal
          </a>
          <Link
            to={opportunity.follow_up_route}
            className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Open follow-up page
          </Link>
        </section>
      </div>
    </aside>
  );
}

export default function AzureSavingsPage() {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [opportunityType, setOpportunityType] = useState("");
  const [subscriptionId, setSubscriptionId] = useState("");
  const [resourceGroup, setResourceGroup] = useState("");
  const [effort, setEffort] = useState("");
  const [risk, setRisk] = useState("");
  const [confidence, setConfidence] = useState("");
  const [quantifiedOnly, setQuantifiedOnly] = useState(false);
  const [selectedOpportunityId, setSelectedOpportunityId] = useState("");
  const { sortKey, sortDir, toggleSort } = useTableSort<SavingsSortKey>("estimated_monthly_savings", "desc");

  const summaryQuery = useQuery({
    queryKey: ["azure", "savings", "summary"],
    queryFn: () => api.getAzureSavingsSummary(),
    refetchInterval: 60_000,
  });

  const opportunitiesQuery = useQuery({
    queryKey: ["azure", "savings", "opportunities", { search, category, opportunityType, subscriptionId, resourceGroup, effort, risk, confidence, quantifiedOnly }],
    queryFn: () => api.getAzureSavingsOpportunities({
      search,
      category,
      opportunity_type: opportunityType,
      subscription_id: subscriptionId,
      resource_group: resourceGroup,
      effort,
      risk,
      confidence,
      quantified_only: quantifiedOnly,
    }),
    refetchInterval: 60_000,
  });

  const summary = summaryQuery.data;
  const opportunities = opportunitiesQuery.data ?? [];
  const actionableRows = opportunities.filter((item) => !(item.category === "commitment" && !item.quantified));
  const commitmentRows = opportunities.filter((item) => item.category === "commitment" && !item.quantified);
  const selectedOpportunity = opportunities.find((item) => item.id === selectedOpportunityId) ?? null;

  const sortedActionableRows = sortRows(actionableRows, sortKey, sortDir, (item, key) => {
    if (key === "subscription") return item.subscription_name || item.subscription_id;
    if (key === "estimated_monthly_savings") return item.estimated_monthly_savings;
    if (key === "effort" || key === "risk") {
      return { low: 0, medium: 1, high: 2 }[item[key]] ?? 99;
    }
    if (key === "confidence") {
      return { high: 0, medium: 1, low: 2 }[item.confidence] ?? 99;
    }
    return (item as unknown as Record<string, string | number | null | undefined>)[key];
  });
  const scrollKey = [search, category, opportunityType, subscriptionId, resourceGroup, effort, risk, confidence, String(quantifiedOnly), sortKey, sortDir].join("|");
  const { visibleCount, hasMore, sentinelRef } = useInfiniteScrollCount(sortedActionableRows.length, 20, scrollKey);
  const visibleRows = sortedActionableRows.slice(0, visibleCount);

  const categoryOptions = (summary?.by_category ?? []).map((item) => item.label);
  const opportunityTypeOptions = Array.from(new Set(opportunities.map((item) => item.opportunity_type))).sort();
  const subscriptionOptions = Array.from(new Set(opportunities.map((item) => item.subscription_name || item.subscription_id).filter(Boolean))).sort();
  const resourceGroupOptions = Array.from(new Set(opportunities.map((item) => item.resource_group).filter(Boolean))).sort();

  if (summaryQuery.isLoading || opportunitiesQuery.isLoading) {
    return <div className="text-sm text-slate-500">Loading Azure savings opportunities...</div>;
  }

  if (summaryQuery.isError || opportunitiesQuery.isError || !summary) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Azure savings data.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Savings</h1>
          <p className="mt-1 text-sm text-slate-500">
            Ranked Azure cost-cutting opportunities across compute, storage, network cleanup, and reservation strategy.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <AzureSourceBadge
              label="Heuristic operational guidance"
              description="Savings opportunities blend cached Azure data, Advisor signals, and app heuristics; this page is for operator triage."
              tone="amber"
            />
            <AzureSourceBadge
              label="Not invoice-grade reporting"
              description="Use the governed reporting handoff on Azure Overview for shared finance and showback reporting."
              tone="emerald"
            />
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          <a
            href={api.exportAzureSavingsCsv({
              search,
              category,
              opportunity_type: opportunityType,
              subscription_id: subscriptionId,
              resource_group: resourceGroup,
              effort,
              risk,
              confidence,
              quantified_only: quantifiedOnly,
            })}
            className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Export CSV
          </a>
          <a
            href={api.exportAzureSavingsExcel({
              search,
              category,
              opportunity_type: opportunityType,
              subscription_id: subscriptionId,
              resource_group: resourceGroup,
              effort,
              risk,
              confidence,
              quantified_only: quantifiedOnly,
            })}
            className="rounded-xl bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800"
          >
            Export Excel
          </a>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Quantified Savings"
          value={formatAzureCurrency(summary.quantified_monthly_savings, summary.currency)}
          sub="Monthly proxy from cached Azure cost data"
          tone="text-emerald-700"
        />
        <StatCard
          label="Quick Wins"
          value={summary.quick_win_count.toLocaleString()}
          sub={`${formatAzureCurrency(summary.quick_win_monthly_savings, summary.currency)} quantified`}
          tone="text-sky-700"
        />
        <StatCard
          label="Total Opportunities"
          value={summary.total_opportunities.toLocaleString()}
          sub={`${summary.quantified_opportunities.toLocaleString()} quantified`}
        />
        <StatCard
          label="Commitment Strategy"
          value={summary.unquantified_opportunity_count.toLocaleString()}
          sub="Unquantified reservation and commitment follow-up"
        />
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search resource, summary, recommendation..."
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
          />
          <select value={category} onChange={(event) => setCategory(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option value="">All categories</option>
            {categoryOptions.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
          <select value={opportunityType} onChange={(event) => setOpportunityType(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option value="">All opportunity types</option>
            {opportunityTypeOptions.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
          <select value={subscriptionId} onChange={(event) => setSubscriptionId(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option value="">All subscriptions</option>
            {subscriptionOptions.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
          <select value={resourceGroup} onChange={(event) => setResourceGroup(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option value="">All resource groups</option>
            {resourceGroupOptions.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Effort</span>
          <FilterChip label="All" active={!effort} onClick={() => setEffort("")} />
          {effortOptions.map((value) => (
            <FilterChip key={value} label={value} active={effort === value} onClick={() => setEffort(value)} />
          ))}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Risk</span>
          <FilterChip label="All" active={!risk} onClick={() => setRisk("")} />
          {effortOptions.map((value) => (
            <FilterChip key={value} label={value} active={risk === value} onClick={() => setRisk(value)} />
          ))}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Confidence</span>
          <FilterChip label="All" active={!confidence} onClick={() => setConfidence("")} />
          {confidenceOptions.map((value) => (
            <FilterChip key={value} label={value} active={confidence === value} onClick={() => setConfidence(value)} />
          ))}
          <button
            type="button"
            onClick={() => setQuantifiedOnly((value) => !value)}
            className={`ml-3 rounded-full px-3 py-1.5 text-xs font-semibold transition ${
              quantifiedOnly
                ? "bg-emerald-600 text-white"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            Quantified only
          </button>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Actionable Savings Opportunities</h2>
            <p className="mt-1 text-sm text-slate-500">
              Quantified cleanup wins and non-commitment follow-up items, ranked by savings and implementation friction.
            </p>
          </div>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
            {sortedActionableRows.length.toLocaleString()} results
          </span>
        </div>

        {visibleRows.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-slate-400">No savings opportunities matched the current filters.</div>
        ) : (
          <div className="max-h-[70vh] overflow-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <SortHeader col="title" label="Recommendation" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="category" label="Category" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="subscription" label="Subscription" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="resource_group" label="Resource Group" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="effort" label="Effort" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="risk" label="Risk" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="confidence" label="Confidence" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="estimated_monthly_savings" label="Est. Monthly Savings" right sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((item, index) => (
                  <tr
                    key={item.id}
                    className={`${index % 2 === 0 ? "bg-white" : "bg-slate-50/50"} cursor-pointer hover:bg-sky-50/60`}
                    onClick={() => setSelectedOpportunityId(item.id)}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">{item.title}</div>
                      <div className="mt-1 line-clamp-2 text-xs text-slate-500">{item.summary}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{item.category}</td>
                    <td className="px-4 py-3 text-slate-700">{item.subscription_name || item.subscription_id || "—"}</td>
                    <td className="px-4 py-3 text-slate-700">{item.resource_group || "—"}</td>
                    <td className="px-4 py-3"><ToneBadge label="Effort" value={item.effort} tone="effort" /></td>
                    <td className="px-4 py-3"><ToneBadge label="Risk" value={item.risk} tone="risk" /></td>
                    <td className="px-4 py-3"><ToneBadge label="Confidence" value={item.confidence} tone="confidence" /></td>
                    <td className="px-4 py-3 text-right font-semibold text-emerald-700">
                      {item.quantified ? formatAzureCurrency(item.estimated_monthly_savings, item.currency) : "Unquantified"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {hasMore ? (
              <div ref={sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
                Showing {visibleRows.length.toLocaleString()} of {sortedActionableRows.length.toLocaleString()} results — scroll for more
              </div>
            ) : null}
          </div>
        )}
      </section>

      <AzureSavingsHighlightsSection
        title="Commitment Strategy"
        description="Reservation coverage gaps and excesses need review, but they are intentionally kept out of the quantified totals until pricing is validated."
        opportunities={commitmentRows}
        emptyMessage="No unquantified reservation strategy items are active in the current filtered view."
        maxItems={8}
      />

      <section className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Top Categories</h2>
          <div className="mt-4 space-y-3">
            {summary.by_category.map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
                <span className="text-sm font-medium text-slate-800">{item.label}</span>
                <span className="text-sm font-semibold text-slate-900">
                  {item.count.toLocaleString()} · {formatAzureCurrency(item.estimated_monthly_savings, summary.currency)}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Top Subscriptions</h2>
          <div className="mt-4 space-y-3">
            {summary.top_subscriptions.map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
                <span className="text-sm font-medium text-slate-800">{item.label}</span>
                <span className="text-sm font-semibold text-slate-900">
                  {item.count.toLocaleString()} · {formatAzureCurrency(item.estimated_monthly_savings, summary.currency)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <OpportunityDrawer opportunity={selectedOpportunity} onClose={() => setSelectedOpportunityId("")} />
    </div>
  );
}
