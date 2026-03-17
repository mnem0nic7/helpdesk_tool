import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api.ts";

function formatCurrency(value: number): string {
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function tooltipCurrency(value: number | string | undefined): string {
  const numeric = typeof value === "number" ? value : Number(value || 0);
  return formatCurrency(numeric);
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Cost</h1>
        <p className="mt-1 text-sm text-slate-500">
          Spend trend, top cost drivers, and Advisor savings opportunities from cached Azure data.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Total Spend</div>
          <div className="mt-2 text-3xl font-semibold text-slate-900">{formatCurrency(summary.data.total_cost)}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top Service</div>
          <div className="mt-2 text-2xl font-semibold text-sky-700">{summary.data.top_service || "—"}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top Subscription</div>
          <div className="mt-2 text-2xl font-semibold text-sky-700">{summary.data.top_subscription || "—"}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Potential Savings</div>
          <div className="mt-2 text-3xl font-semibold text-emerald-700">{formatCurrency(summary.data.potential_monthly_savings)}</div>
        </div>
      </div>

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
                <Line type="monotone" dataKey="cost" stroke="#0f766e" strokeWidth={2.5} dot={false} />
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

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Advisor Savings Opportunities</h2>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
            {(advisor.data ?? []).length.toLocaleString()} recommendations
          </span>
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Recommendation</th>
                <th className="px-4 py-3">Subscription</th>
                <th className="px-4 py-3">Impact</th>
                <th className="px-4 py-3 text-right">Monthly Savings</th>
              </tr>
            </thead>
            <tbody>
              {(advisor.data ?? []).map((item, index) => (
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
        </div>
      </section>
    </div>
  );
}
