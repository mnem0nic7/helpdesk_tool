import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type AzureAICostBreakdownItem } from "../lib/api.ts";

const LOOKBACK_OPTIONS = [7, 30, 90];

function formatCurrency(value: number, currency = "USD"): string {
  const maximumFractionDigits = value > 0 && value < 1 ? 6 : 2;
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits,
  }).format(value);
}

function formatInteger(value: number): string {
  return value.toLocaleString();
}

function formatShare(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function formatWindow(start?: string, end?: string): string {
  if (!start || !end) return "";
  if (start === end) return start;
  return `${start} to ${end}`;
}

function BreakdownList({
  title,
  rows,
  currency,
}: {
  title: string;
  rows: AzureAICostBreakdownItem[];
  currency: string;
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {rows.length.toLocaleString()} rows
        </span>
      </div>
      <div className="mt-4 space-y-3">
        {rows.length ? rows.slice(0, 8).map((item) => (
          <div key={`${title}-${item.label}`} className="rounded-xl bg-slate-50 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-900">{item.label}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {formatInteger(item.request_count)} requests • {formatInteger(item.estimated_tokens)} est. tokens
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm font-semibold text-slate-900">
                  {formatCurrency(item.estimated_cost, item.currency || currency)}
                </div>
                <div className="mt-1 text-xs text-slate-500">{formatShare(item.share)}</div>
              </div>
            </div>
          </div>
        )) : (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
            No AI usage has been recorded for this grouping yet.
          </div>
        )}
      </div>
    </section>
  );
}

export default function AzureAICostPage() {
  const [lookbackDays, setLookbackDays] = useState(30);

  const summary = useQuery({
    queryKey: ["azure", "ai-costs", "summary", lookbackDays],
    queryFn: () => api.getAzureAICostSummary(lookbackDays),
    refetchInterval: 60_000,
  });
  const trend = useQuery({
    queryKey: ["azure", "ai-costs", "trend", lookbackDays],
    queryFn: () => api.getAzureAICostTrend(lookbackDays),
    refetchInterval: 60_000,
  });
  const byProvider = useQuery({
    queryKey: ["azure", "ai-costs", "breakdown", "provider", lookbackDays],
    queryFn: () => api.getAzureAICostBreakdown("provider", lookbackDays),
    refetchInterval: 60_000,
  });
  const byModel = useQuery({
    queryKey: ["azure", "ai-costs", "breakdown", "model", lookbackDays],
    queryFn: () => api.getAzureAICostBreakdown("model", lookbackDays),
    refetchInterval: 60_000,
  });
  const byApp = useQuery({
    queryKey: ["azure", "ai-costs", "breakdown", "app", lookbackDays],
    queryFn: () => api.getAzureAICostBreakdown("app", lookbackDays),
    refetchInterval: 60_000,
  });
  const byTeam = useQuery({
    queryKey: ["azure", "ai-costs", "breakdown", "team", lookbackDays],
    queryFn: () => api.getAzureAICostBreakdown("team", lookbackDays),
    refetchInterval: 60_000,
  });

  const loading = [summary, trend, byProvider, byModel, byApp, byTeam].some((query) => query.isLoading);
  const failure = [summary, trend, byProvider, byModel, byApp, byTeam].find((query) => query.isError);

  if (loading) {
    return <div className="text-sm text-slate-500">Loading Azure AI cost data...</div>;
  }

  if (failure || !summary.data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Azure AI cost data: {failure?.error instanceof Error ? failure.error.message : "Unknown error"}
      </div>
    );
  }

  const currency = summary.data.currency || "USD";
  const windowLabel = formatWindow(summary.data.window_start, summary.data.window_end);
  const providerRows = byProvider.data ?? [];
  const onlyOllamaProviders =
    providerRows.length === 0 || providerRows.every((item) => item.label.trim().toLowerCase() === "ollama");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">AI Cost</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Local AI usage and estimated cost across the Azure portal surfaces. This deployment is expected to use Ollama
            for all AI calls, and the provider breakdown below makes that visible.
          </p>
          {windowLabel ? (
            <div className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-500">
              Coverage window: {windowLabel}
            </div>
          ) : null}
        </div>
        <label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm">
          <span className="font-medium text-slate-600">Lookback</span>
          <select
            value={lookbackDays}
            onChange={(event) => setLookbackDays(Number(event.target.value))}
            className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
          >
            {LOOKBACK_OPTIONS.map((days) => (
              <option key={days} value={days}>
                {days} days
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className={`rounded-2xl border px-5 py-4 shadow-sm ${onlyOllamaProviders ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
        <div className="text-sm font-semibold text-slate-900">
          {onlyOllamaProviders ? "Ollama-only runtime confirmed" : "Provider mix needs attention"}
        </div>
        <div className="mt-1 text-sm text-slate-600">
          {onlyOllamaProviders
            ? "All recorded AI usage in the current window is attributed to Ollama-backed local models."
            : "A non-Ollama provider appeared in the AI usage breakdown. Since this deployment is meant to be Ollama-only, treat that as a regression."}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Estimated Cost</div>
          <div className="mt-2 text-3xl font-semibold text-slate-900">{formatCurrency(summary.data.estimated_cost, currency)}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Requests</div>
          <div className="mt-2 text-3xl font-semibold text-sky-700">{formatInteger(summary.data.request_count)}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Estimated Tokens</div>
          <div className="mt-2 text-3xl font-semibold text-indigo-700">{formatInteger(summary.data.estimated_tokens)}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top Model</div>
          <div className="mt-2 text-xl font-semibold text-slate-900">{summary.data.top_model || "—"}</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top Feature</div>
          <div className="mt-2 text-xl font-semibold text-slate-900">{summary.data.top_feature || "—"}</div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.3fr,1fr]">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Estimated Cost Trend</h2>
          <div className="mt-4 h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trend.data ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip formatter={(value: number | string | undefined) => formatCurrency(Number(value || 0), currency)} />
                <Line type="monotone" dataKey="estimated_cost" stroke="#0f766e" strokeWidth={2.5} dot={false} name="Estimated cost" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Request Volume</h2>
          <div className="mt-4 h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={trend.data ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip formatter={(value: number | string | undefined) => formatInteger(Number(value || 0))} />
                <Bar dataKey="request_count" fill="#2563eb" radius={[6, 6, 0, 0]} name="Requests" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <BreakdownList title="By Provider" rows={providerRows} currency={currency} />
        <BreakdownList title="By Model" rows={byModel.data ?? []} currency={currency} />
        <BreakdownList title="By App Surface" rows={byApp.data ?? []} currency={currency} />
        <BreakdownList title="By Team" rows={byTeam.data ?? []} currency={currency} />
      </div>
    </div>
  );
}
