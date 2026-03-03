import { useQuery } from "@tanstack/react-query";
import api from "../lib/api.ts";
import type { AssigneeStats } from "../lib/api.ts";
import MetricCard from "../components/MetricCard.tsx";
import MonthlyTrendChart from "../components/charts/MonthlyTrendChart.tsx";
import AgingPieChart from "../components/charts/AgingPieChart.tsx";
import TTRDistributionChart from "../components/charts/TTRDistributionChart.tsx";
import PriorityBarChart from "../components/charts/PriorityBarChart.tsx";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format hours into a human-friendly duration string. */
function formatHours(hours: number): string {
  if (hours < 1) {
    const minutes = Math.round(hours * 60);
    return `${minutes}m`;
  }
  if (hours < 24) {
    return `${hours.toFixed(1)}h`;
  }
  const days = hours / 24;
  return `${days.toFixed(1)}d`;
}

/** Count stale tickets (those unresolved longer than 30 days). */
function computeStale(ageBuckets: { bucket: string; count: number }[]): number {
  const stale = ageBuckets.find(
    (b) => b.bucket === "30+d" || b.bucket.includes("30+")
  );
  return stale?.count ?? 0;
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function LoadingSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-24 animate-pulse rounded-lg bg-gray-200"
          />
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-[360px] animate-pulse rounded-lg bg-gray-200"
          />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Assignees table
// ---------------------------------------------------------------------------

function AssigneesTable({ rows }: { rows: AssigneeStats[] }) {
  if (!rows || rows.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-gray-400">
        No assignee data available
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg bg-white shadow">
      <table className="min-w-full text-left text-sm">
        <thead>
          <tr className="border-b border-gray-200 bg-gray-50 text-xs font-semibold uppercase tracking-wider text-gray-500">
            <th className="px-4 py-3">Assignee</th>
            <th className="px-4 py-3 text-right">Resolved</th>
            <th className="px-4 py-3 text-right">Open</th>
            <th className="px-4 py-3 text-right">Median TTR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr
              key={row.name}
              className={[
                "border-b border-gray-100 transition-colors hover:bg-blue-50",
                idx % 2 === 0 ? "bg-white" : "bg-gray-50/50",
              ].join(" ")}
            >
              <td className="px-4 py-3 font-medium text-gray-900">
                {row.name || "Unassigned"}
              </td>
              <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                {row.resolved.toLocaleString()}
              </td>
              <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                {row.open.toLocaleString()}
              </td>
              <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                {formatHours(row.median_ttr)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["metrics"],
    queryFn: api.getMetrics,
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="mt-1 text-sm text-gray-500">
            Loading metrics...
          </p>
        </div>
        <LoadingSkeleton />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="text-sm font-medium text-red-800">
            Failed to load metrics
          </p>
          <p className="mt-1 text-xs text-red-600">
            {error instanceof Error ? error.message : "Unknown error"}
          </p>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { headline, weekly_volumes, age_buckets, ttr_distribution, priority_counts, assignee_stats } =
    data;

  const staleCount = computeStale(age_buckets);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-1 text-sm text-gray-500">
          Overview of OIT helpdesk metrics and KPIs
        </p>
      </div>

      {/* Headline metric cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard
          label="Total Tickets"
          value={headline.total_tickets.toLocaleString()}
          color="blue"
        />
        <MetricCard
          label="Open Backlog"
          value={headline.open_backlog.toLocaleString()}
          color="yellow"
          subtitle={`${((headline.open_backlog / headline.total_tickets) * 100).toFixed(1)}% of total`}
        />
        <MetricCard
          label="Resolved"
          value={headline.resolved.toLocaleString()}
          color="green"
        />
        <MetricCard
          label="Median TTR"
          value={formatHours(headline.median_ttr_hours)}
          color="blue"
          subtitle="Time to resolution"
        />
        <MetricCard
          label="P90 TTR"
          value={formatHours(headline.p90_ttr_hours)}
          color="red"
          subtitle="90th percentile"
        />
        <MetricCard
          label="Stale Tickets"
          value={staleCount.toLocaleString()}
          color={staleCount > 0 ? "red" : "green"}
          subtitle="Open > 30 days"
        />
      </div>

      {/* Charts grid */}
      <div className="grid gap-6 lg:grid-cols-2">
        <MonthlyTrendChart data={weekly_volumes} />
        <AgingPieChart data={age_buckets} />
        <TTRDistributionChart data={ttr_distribution} />
        <PriorityBarChart data={priority_counts} />
      </div>

      {/* Top Assignees */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-gray-800">
          Top Assignees
        </h2>
        <AssigneesTable rows={assignee_stats} />
      </div>
    </div>
  );
}
