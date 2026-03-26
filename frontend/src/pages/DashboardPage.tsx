import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "../lib/api.ts";
import type { AssigneeStats, LibraSupportFilterMode, MetricsQueryParams } from "../lib/api.ts";
import MetricCard from "../components/MetricCard.tsx";
import DateRangeSelector from "../components/DateRangeSelector.tsx";
import type { DateRange } from "../components/DateRangeSelector.tsx";
import MonthlyTrendChart from "../components/charts/MonthlyTrendChart.tsx";
import AgingPieChart from "../components/charts/AgingPieChart.tsx";
import TTRDistributionChart from "../components/charts/TTRDistributionChart.tsx";
import PriorityBarChart from "../components/charts/PriorityBarChart.tsx";
import { getSiteBranding } from "../lib/siteContext.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format hours into a human-friendly duration string. */
function formatHours(hours: number | null | undefined): string {
  if (hours == null) return "—";
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

/** Add 7 days to a YYYY-MM-DD string. */
function weekEnd(weekStart: string): string {
  const d = new Date(weekStart + "T00:00:00");
  d.setDate(d.getDate() + 6);
  return d.toISOString().slice(0, 10);
}

/** Map an age bucket label to created_after/created_before filters.
 *  A ticket in "30+d" was created > 30 days ago, so created_before = today - 30. */
function ageBucketToDateFilters(bucket: string): Record<string, string> {
  const today = new Date();
  function daysAgo(n: number): string {
    const d = new Date(today);
    d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
  }
  const map: Record<string, Record<string, string>> = {
    "0-2d":   { created_after: daysAgo(2) },
    "3-7d":   { created_after: daysAgo(7),  created_before: daysAgo(3) },
    "8-14d":  { created_after: daysAgo(14), created_before: daysAgo(8) },
    "15-30d": { created_after: daysAgo(30), created_before: daysAgo(15) },
    "30+d":   { created_before: daysAgo(30) },
  };
  return map[bucket] ?? {};
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

interface AssigneesTableProps {
  rows: AssigneeStats[];
  onRowClick?: (name: string) => void;
}

function AssigneesTable({ rows, onRowClick }: AssigneesTableProps) {
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
                onRowClick ? "cursor-pointer" : "",
              ].join(" ")}
              onClick={onRowClick ? () => onRowClick(row.name) : undefined}
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
  const branding = getSiteBranding();
  const showLibraSupportFilter = branding.scope === "primary";
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // Read date range from URL search params
  const dateRange: DateRange = {
    date_from: searchParams.get("date_from") ?? undefined,
    date_to: searchParams.get("date_to") ?? undefined,
  };
  const libraSupport = (searchParams.get("libra_support") as LibraSupportFilterMode | null) ?? "all";

  const metricsParams: MetricsQueryParams = {
    date_from: dateRange.date_from,
    date_to: dateRange.date_to,
    ...(showLibraSupportFilter && libraSupport !== "all" ? { libra_support: libraSupport } : {}),
  };

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["metrics", metricsParams],
    queryFn: () => api.getMetrics(metricsParams),
    staleTime: 5 * 60 * 1000, // treat as fresh for 5 minutes — prevents refetch on tab focus
  });

  // Update URL when date range changes
  const handleDateRangeChange = useCallback(
    (range: DateRange) => {
      const params = new URLSearchParams();
      if (range.date_from) params.set("date_from", range.date_from);
      if (range.date_to) params.set("date_to", range.date_to);
      if (showLibraSupportFilter && libraSupport !== "all") {
        params.set("libra_support", libraSupport);
      }
      setSearchParams(params, { replace: true });
    },
    [libraSupport, setSearchParams, showLibraSupportFilter]
  );

  const handleLibraSupportChange = useCallback(
    (nextValue: LibraSupportFilterMode) => {
      const params = new URLSearchParams(searchParams);
      if (nextValue === "all") {
        params.delete("libra_support");
      } else {
        params.set("libra_support", nextValue);
      }
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  // Navigate to /tickets with filters pre-populated
  const drillDown = useCallback(
    (filters: Record<string, string>) => {
      const params = new URLSearchParams(filters);
      // Carry date range as created_after/created_before
      if (dateRange.date_from && !params.has("created_after")) {
        params.set("created_after", dateRange.date_from);
      }
      if (dateRange.date_to && !params.has("created_before")) {
        params.set("created_before", dateRange.date_to);
      }
      if (showLibraSupportFilter && libraSupport !== "all") {
        params.set("libra_support", libraSupport);
      }
      navigate(`/tickets?${params.toString()}`);
    },
    [navigate, dateRange, libraSupport, showLibraSupportFilter]
  );

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

  const staleCount = headline.stale_count;

  return (
    <div className="space-y-6">
      {/* Page header + date range selector */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="mt-1 text-sm text-gray-500">
            Overview of {branding.appName} metrics and KPIs
          </p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          {showLibraSupportFilter ? (
            <select
              value={libraSupport}
              onChange={(e) => handleLibraSupportChange(e.target.value as LibraSupportFilterMode)}
              className="h-10 rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="all">All Libra Support</option>
              <option value="libra_support">Libra Support</option>
              <option value="non_libra_support">Non Libra Support</option>
            </select>
          ) : null}
          <DateRangeSelector value={dateRange} onChange={handleDateRangeChange} />
        </div>
      </div>

      {/* Headline metric cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard
          label="Total Tickets"
          value={headline.total_tickets.toLocaleString()}
          color="blue"
          onClick={() => drillDown({})}
        />
        <MetricCard
          label="Open Backlog"
          value={headline.open_backlog.toLocaleString()}
          color="yellow"
          subtitle={headline.total_tickets > 0 ? `${((headline.open_backlog / headline.total_tickets) * 100).toFixed(1)}% of total` : undefined}
          onClick={() => drillDown({ open_only: "true" })}
        />
        <MetricCard
          label="Resolved"
          value={headline.resolved.toLocaleString()}
          color="green"
          onClick={() => drillDown({ status: "Resolved" })}
        />
        <MetricCard
          label="Median TTR"
          value={formatHours(headline.median_ttr_hours)}
          color="blue"
          subtitle="Time to resolution"
          onClick={() => drillDown({ status: "Resolved" })}
        />
        <MetricCard
          label="P90 TTR"
          value={formatHours(headline.p90_ttr_hours)}
          color="red"
          subtitle="90th percentile"
          onClick={() => drillDown({ status: "Resolved" })}
        />
        <MetricCard
          label="Stale Tickets"
          value={staleCount.toLocaleString()}
          color={staleCount > 0 ? "red" : "green"}
          subtitle="Not updated in 1+ day"
          onClick={() => drillDown({ stale_only: "true" })}
        />
      </div>

      {/* Charts grid */}
      <div className="grid gap-6 lg:grid-cols-2">
        <MonthlyTrendChart
          data={weekly_volumes}
          onPointClick={(ws) =>
            drillDown({ created_after: ws, created_before: weekEnd(ws) })
          }
        />
        <AgingPieChart
          data={age_buckets}
          onSliceClick={(bucket) => {
            drillDown({ open_only: "true", ...ageBucketToDateFilters(bucket) });
          }}
        />
        <TTRDistributionChart
          data={ttr_distribution}
          onBarClick={() => drillDown({ status: "Resolved" })}
        />
        <PriorityBarChart
          data={priority_counts}
          onBarClick={(priority) => drillDown({ priority })}
        />
      </div>

      {/* Top Assignees */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-gray-800">
          Top Assignees
        </h2>
        <AssigneesTable
          rows={assignee_stats}
          onRowClick={(name) => drillDown({ assignee: name })}
        />
      </div>
    </div>
  );
}
