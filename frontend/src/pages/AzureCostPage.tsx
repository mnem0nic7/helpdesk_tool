import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type AzureFinopsValidationCheck } from "../lib/api.ts";
import AzureSourceBadge from "../components/AzureSourceBadge.tsx";
import AzureSavingsHighlightsSection from "../components/AzureSavingsHighlightsSection.tsx";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";

type AdvisorSortKey = "title" | "subscription_name" | "impact" | "monthly_savings";

function formatCurrency(value: number): string {
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function tooltipCurrency(value: number | string | undefined): string {
  const numeric = typeof value === "number" ? value : Number(value || 0);
  return formatCurrency(numeric);
}

function formatCoverageWindow(start?: string | null, end?: string | null): string {
  if (!start || !end) return "";
  if (start === end) return start;
  return `${start} to ${end}`;
}

function formatPercent(value: number | undefined): string {
  return `${((value ?? 0) * 100).toFixed(1)}%`;
}

function formatHours(value: number | null | undefined): string {
  if (value == null) return "Unavailable";
  if (value < 1) return `${Math.round(value * 60)} min`;
  return `${value.toFixed(1)} hr`;
}

function formatValidationValue(check: AzureFinopsValidationCheck, value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "number") {
    if (check.unit === "currency") return formatCurrency(value);
    if (check.unit === "ratio") return formatPercent(value);
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value);
}

function getValidationTone(state: string): { badge: string; text: string } {
  if (state === "pass") return { badge: "bg-emerald-50 text-emerald-700", text: "text-emerald-700" };
  if (state === "fail") return { badge: "bg-red-50 text-red-700", text: "text-red-700" };
  if (state === "warning") return { badge: "bg-amber-50 text-amber-700", text: "text-amber-700" };
  return { badge: "bg-slate-100 text-slate-700", text: "text-slate-700" };
}

export default function AzureCostPage() {
  const summary = useQuery({
    queryKey: ["azure", "cost", "summary"],
    queryFn: () => api.getAzureCostSummary(),
    refetchInterval: 60_000,
  });
  const trend = useQuery({
    queryKey: ["azure", "cost", "trend"],
    queryFn: () => api.getAzureCostTrend(),
    refetchInterval: 60_000,
  });
  const byService = useQuery({
    queryKey: ["azure", "cost", "breakdown", "service"],
    queryFn: () => api.getAzureCostBreakdown("service"),
    refetchInterval: 60_000,
  });
  const bySubscription = useQuery({
    queryKey: ["azure", "cost", "breakdown", "subscription"],
    queryFn: () => api.getAzureCostBreakdown("subscription"),
    refetchInterval: 60_000,
  });
  const byResourceGroup = useQuery({
    queryKey: ["azure", "cost", "breakdown", "resource_group"],
    queryFn: () => api.getAzureCostBreakdown("resource_group"),
    refetchInterval: 60_000,
  });
  const advisor = useQuery({
    queryKey: ["azure", "advisor"],
    queryFn: () => api.getAzureAdvisor(),
    refetchInterval: 60_000,
  });
  const savings = useQuery({
    queryKey: ["azure", "savings", "cost-page"],
    queryFn: () => api.getAzureSavingsOpportunities({ quantified_only: true }),
    refetchInterval: 60_000,
  });
  const validation = useQuery({
    queryKey: ["azure", "finops", "validation"],
    queryFn: () => api.getAzureFinopsValidation(),
    refetchInterval: 60_000,
  });
  const advisorRows = advisor.data ?? [];
  const topSavingsRows = (savings.data ?? []).slice(0, 6);
  const { sortKey: advSortKey, sortDir: advSortDir, toggleSort: toggleAdvSort } = useTableSort<AdvisorSortKey>("monthly_savings", "desc");
  const sortedAdvisor = sortRows(advisorRows, advSortKey, advSortDir, (item, key) => {
    if (key === "subscription_name") return item.subscription_name || item.subscription_id;
    return (item as unknown as Record<string, unknown>)[key] as string | number;
  });
  const advisorScroll = useInfiniteScrollCount(sortedAdvisor.length, 20, `advisor|${advSortKey}|${advSortDir}`);
  const visibleAdvisorRows = sortedAdvisor.slice(0, advisorScroll.visibleCount);

  const loading = [summary, trend, byService, bySubscription, byResourceGroup, advisor].some((query) => query.isLoading);
  const failure = [summary, trend, byService, bySubscription, byResourceGroup, advisor].find((query) => query.isError);

  if (loading) {
    return <div className="text-sm text-slate-500">Loading Azure cost data...</div>;
  }

  if (failure || !summary.data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Azure cost data: {failure?.error instanceof Error ? failure.error.message : "Unknown error"}
      </div>
    );
  }

  const totalActual = summary.data.total_actual_cost ?? summary.data.total_cost;
  const totalAmortized = summary.data.total_amortized_cost ?? summary.data.total_cost;
  const sourceLabel = summary.data.source_label ?? (summary.data.export_backed ? "Export-backed local analytics" : "Cached app data");
  const coverageWindow = formatCoverageWindow(summary.data.window_start, summary.data.window_end);
  const validationTone = getValidationTone(validation.data?.overall_state || "unavailable");
  const validationChecks = validation.data?.checks ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Cost</h1>
        <p className="mt-1 text-sm text-slate-500">
          Spend trend, top cost drivers, and Advisor savings opportunities using the current app source of truth for Azure cost data.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <AzureSourceBadge
            label={sourceLabel}
            description={
              summary.data.export_backed
                ? "This page is using local export-backed analytics built from parsed Azure Cost Management deliveries."
                : "This page is an operational summary built from cached Azure Cost Management query results in the app."
            }
          />
          <AzureSourceBadge
            label="Use governed reporting for finance"
            description="Shared finance and showback reporting should come from the governed reporting handoff on Azure Overview."
            tone="emerald"
          />
        </div>
        {coverageWindow ? (
          <div className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-500">
            Coverage window: {coverageWindow}
          </div>
        ) : null}
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Actual Spend</div>
          <div className="mt-2 text-3xl font-semibold text-slate-900">{formatCurrency(totalActual)}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Amortized Spend</div>
          <div className="mt-2 text-3xl font-semibold text-indigo-700">{formatCurrency(totalAmortized)}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top Service</div>
          <div className="mt-2 text-2xl font-semibold text-sky-700">{summary.data.top_service || "—"}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Potential Savings</div>
          <div className="mt-2 text-3xl font-semibold text-emerald-700">{formatCurrency(summary.data.potential_monthly_savings)}</div>
        </div>
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">FinOps Validation</h2>
            <p className="mt-1 max-w-3xl text-sm text-slate-500">
              Live-validation checks compare staged export summaries, DuckDB totals, and the cache-backed portal summary so we can
              sign off the export lane with real Azure deliveries.
            </p>
          </div>
          {validation.data ? (
            <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ${validationTone.badge}`}>
              {validation.data.overall_label}
            </span>
          ) : null}
        </div>

        {validation.isLoading ? (
          <div className="mt-4 text-sm text-slate-500">Loading validation checks...</div>
        ) : validation.isError ? (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700">
            Could not load the FinOps validation report: {validation.error instanceof Error ? validation.error.message : "Unknown error"}
          </div>
        ) : validation.data ? (
          <>
            <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-xl bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Signoff</div>
                <div className={`mt-2 text-lg font-semibold ${validation.data.signoff_ready ? "text-emerald-700" : validationTone.text}`}>
                  {validation.data.signoff_ready ? "Ready" : "Not Ready"}
                </div>
                <div className="mt-1 text-sm text-slate-600">{validation.data.signoff_reason}</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Latest Import Age</div>
                <div className="mt-2 text-lg font-semibold text-slate-900">
                  {formatHours(validation.data.latest_import_age_hours)}
                </div>
                <div className="mt-1 text-sm text-slate-600">
                  {validation.data.latest_import?.dataset || "No dataset"} {validation.data.latest_import?.delivery_key ? `· ${validation.data.latest_import.delivery_key}` : ""}
                </div>
              </div>
              <div className="rounded-xl bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Checks</div>
                <div className="mt-2 text-lg font-semibold text-slate-900">
                  {(validation.data.check_counts.pass ?? 0).toLocaleString()} pass / {(validation.data.check_counts.warning ?? 0).toLocaleString()} warning / {(validation.data.check_counts.fail ?? 0).toLocaleString()} fail
                </div>
                <div className="mt-1 text-sm text-slate-600">Drift checks stay visible here even before the live signoff window.</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Key Drift</div>
                <div className="mt-2 text-lg font-semibold text-slate-900">
                  {formatCurrency(Number(validation.data.drift_summary?.delivery_actual_cost_delta ?? 0))}
                </div>
                <div className="mt-1 text-sm text-slate-600">
                  Delivery actual cost delta
                  {validation.data.export_health?.state ? ` · Export health ${validation.data.export_health.state}` : ""}
                </div>
              </div>
            </div>

            <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Check</th>
                    <th className="px-4 py-3">State</th>
                    <th className="px-4 py-3">Observed</th>
                    <th className="px-4 py-3">Expected</th>
                    <th className="px-4 py-3">Delta</th>
                  </tr>
                </thead>
                <tbody>
                  {validationChecks.map((check, index) => {
                    const tone = getValidationTone(check.state);
                    return (
                      <tr key={check.key} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/40"}>
                        <td className="px-4 py-3">
                          <div className="font-medium text-slate-900">{check.label}</div>
                          <div className="mt-1 text-xs text-slate-500">{check.detail}</div>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${tone.badge}`}>
                            {check.state}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-700">{formatValidationValue(check, check.actual)}</td>
                        <td className="px-4 py-3 text-slate-700">{formatValidationValue(check, check.expected)}</td>
                        <td className="px-4 py-3 text-slate-700">{formatValidationValue(check, check.delta)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </section>

      <div className="grid gap-4 xl:grid-cols-[1.5fr,1fr]">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Daily Spend Trend</h2>
          <div className="mt-4 h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trend.data ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip formatter={tooltipCurrency} />
                <Line type="monotone" dataKey="actual_cost" stroke="#0f766e" strokeWidth={2.5} dot={false} name="Actual" />
                <Line type="monotone" dataKey="amortized_cost" stroke="#4f46e5" strokeWidth={2.5} dot={false} name="Amortized" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Top Services</h2>
          <div className="mt-4 h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={(byService.data ?? []).slice(0, 8)} layout="vertical" margin={{ left: 40 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis dataKey="label" type="category" width={120} tick={{ fontSize: 12 }} />
                <Tooltip formatter={tooltipCurrency} />
                <Bar dataKey="amount" fill="#2563eb" radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Top Subscriptions</h2>
          <div className="mt-4 space-y-3">
            {(bySubscription.data ?? []).slice(0, 10).map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
                <span className="text-sm font-medium text-slate-800">{item.label}</span>
                <span className="text-sm font-semibold text-slate-900">{formatCurrency(item.amount)}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Top Resource Groups</h2>
          <div className="mt-4 space-y-3">
            {(byResourceGroup.data ?? []).slice(0, 10).map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
                <span className="text-sm font-medium text-slate-800">{item.label}</span>
                <span className="text-sm font-semibold text-slate-900">{formatCurrency(item.amount)}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <AzureSavingsHighlightsSection
        title="Top Savings Opportunities"
        description="The highest-value quantified actions across cleanup, rightsizing, and other synthesized Azure savings signals."
        opportunities={topSavingsRows}
        emptyMessage="No quantified Azure savings opportunities are available yet."
        maxItems={6}
      />

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Advisor Savings Opportunities</h2>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
            {advisorRows.length.toLocaleString()} recommendations
          </span>
        </div>
        <div className="mt-4 max-h-[70vh] overflow-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <SortHeader col="title" label="Recommendation" sortKey={advSortKey} sortDir={advSortDir} onSort={toggleAdvSort} />
                <SortHeader col="subscription_name" label="Subscription" sortKey={advSortKey} sortDir={advSortDir} onSort={toggleAdvSort} />
                <SortHeader col="impact" label="Impact" sortKey={advSortKey} sortDir={advSortDir} onSort={toggleAdvSort} />
                <SortHeader col="monthly_savings" label="Monthly Savings" right sortKey={advSortKey} sortDir={advSortDir} onSort={toggleAdvSort} />
              </tr>
            </thead>
            <tbody>
              {visibleAdvisorRows.map((item, index) => (
                <tr key={item.id} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{item.title}</div>
                    <div className="mt-1 text-xs text-slate-500">{item.description}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-700">{item.subscription_name || item.subscription_id}</td>
                  <td className="px-4 py-3 text-slate-700">{item.impact || "—"}</td>
                  <td className="px-4 py-3 text-right font-semibold text-emerald-700">{formatCurrency(item.monthly_savings)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {advisorScroll.hasMore ? (
            <div ref={advisorScroll.sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
              Showing {visibleAdvisorRows.length.toLocaleString()} of {advisorRows.length.toLocaleString()} recommendations — scroll for more
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
