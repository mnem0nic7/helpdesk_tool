import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type {
  ReportFilters,
  ChartDataRequest,
  ChartTimeseriesRequest,
  ChartDataResponse,
  ChartTimeseriesResponse,
} from "../lib/api.ts";
import TicketFilters, {
  emptyFilters,
} from "../components/TicketFilters.tsx";
import type { TicketFilterValues } from "../components/TicketFilters.tsx";
import ChartRenderer from "../components/charts/ChartRenderer.tsx";
import type {
  GroupedChartType,
  TimeseriesChartType,
} from "../components/charts/ChartRenderer.tsx";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

type Mode = "grouped" | "timeseries";

const GROUPED_CHART_TYPES: { value: GroupedChartType; label: string }[] = [
  { value: "bar", label: "Bar" },
  { value: "horizontal_bar", label: "H-Bar" },
  { value: "pie", label: "Pie" },
  { value: "donut", label: "Donut" },
];

const TIMESERIES_CHART_TYPES: { value: TimeseriesChartType; label: string }[] = [
  { value: "line", label: "Line" },
  { value: "area", label: "Area" },
];

const GROUP_BY_OPTIONS = [
  { value: "status", label: "Status" },
  { value: "status_category", label: "Status Category" },
  { value: "priority", label: "Priority" },
  { value: "assignee", label: "Assignee" },
  { value: "reporter", label: "Reporter" },
  { value: "issue_type", label: "Issue Type" },
  { value: "resolution", label: "Resolution" },
  { value: "request_type", label: "Request Type" },
];

const METRIC_OPTIONS = [
  { value: "count", label: "Count" },
  { value: "open", label: "Open" },
  { value: "resolved", label: "Resolved" },
  { value: "avg_ttr", label: "Avg TTR (h)" },
  { value: "median_ttr", label: "Median TTR (h)" },
  { value: "avg_age", label: "Avg Age (d)" },
];

// ---------------------------------------------------------------------------
// Preset definitions
// ---------------------------------------------------------------------------

interface Preset {
  name: string;
  description: string;
  icon: string;
  accent: string;
  mode: Mode;
  // Grouped
  group_by?: string;
  metric?: string;
  chart_type?: GroupedChartType;
  // Timeseries
  ts_chart_type?: TimeseriesChartType;
  time_bucket?: string;
}

const PRESETS: Preset[] = [
  {
    name: "Tickets by Status",
    description: "Distribution of tickets across statuses",
    icon: "pie",
    accent: "sky",
    mode: "grouped",
    group_by: "status",
    metric: "count",
    chart_type: "pie",
  },
  {
    name: "Tickets by Priority",
    description: "Ticket volume by priority level",
    icon: "bar",
    accent: "rose",
    mode: "grouped",
    group_by: "priority",
    metric: "count",
    chart_type: "horizontal_bar",
  },
  {
    name: "Assignee Workload",
    description: "Ticket count per team member",
    icon: "team",
    accent: "violet",
    mode: "grouped",
    group_by: "assignee",
    metric: "count",
    chart_type: "bar",
  },
  {
    name: "Resolution Times",
    description: "Average TTR by priority",
    icon: "clock",
    accent: "amber",
    mode: "grouped",
    group_by: "priority",
    metric: "avg_ttr",
    chart_type: "bar",
  },
  {
    name: "Age by Status",
    description: "Average ticket age by status",
    icon: "age",
    accent: "orange",
    mode: "grouped",
    group_by: "status",
    metric: "avg_age",
    chart_type: "bar",
  },
  {
    name: "Weekly Trend",
    description: "Created vs resolved per week",
    icon: "trend",
    accent: "emerald",
    mode: "timeseries",
    ts_chart_type: "line",
    time_bucket: "week",
  },
  {
    name: "Monthly Trend",
    description: "Full monthly volume history",
    icon: "area",
    accent: "indigo",
    mode: "timeseries",
    ts_chart_type: "area",
    time_bucket: "month",
  },
];

// ---------------------------------------------------------------------------
// Accent color map
// ---------------------------------------------------------------------------

const ACCENT_CLASSES: Record<
  string,
  { bg: string; border: string; text: string; icon: string; activeBg: string; activeBorder: string; activeText: string }
> = {
  sky:     { bg: "bg-sky-50/60",     border: "border-sky-200/60",     text: "text-sky-700",     icon: "text-sky-500",     activeBg: "bg-sky-600",     activeBorder: "border-sky-600",     activeText: "text-white" },
  rose:    { bg: "bg-rose-50/60",    border: "border-rose-200/60",    text: "text-rose-700",    icon: "text-rose-500",    activeBg: "bg-rose-600",    activeBorder: "border-rose-600",    activeText: "text-white" },
  violet:  { bg: "bg-violet-50/60",  border: "border-violet-200/60",  text: "text-violet-700",  icon: "text-violet-500",  activeBg: "bg-violet-600",  activeBorder: "border-violet-600",  activeText: "text-white" },
  amber:   { bg: "bg-amber-50/60",   border: "border-amber-200/60",   text: "text-amber-700",   icon: "text-amber-500",   activeBg: "bg-amber-600",   activeBorder: "border-amber-600",   activeText: "text-white" },
  orange:  { bg: "bg-orange-50/60",  border: "border-orange-200/60",  text: "text-orange-700",  icon: "text-orange-500",  activeBg: "bg-orange-600",  activeBorder: "border-orange-600",  activeText: "text-white" },
  emerald: { bg: "bg-emerald-50/60", border: "border-emerald-200/60", text: "text-emerald-700", icon: "text-emerald-500", activeBg: "bg-emerald-600", activeBorder: "border-emerald-600", activeText: "text-white" },
  indigo:  { bg: "bg-indigo-50/60",  border: "border-indigo-200/60",  text: "text-indigo-700",  icon: "text-indigo-500",  activeBg: "bg-indigo-600",  activeBorder: "border-indigo-600",  activeText: "text-white" },
};

// ---------------------------------------------------------------------------
// Inline SVG Icons
// ---------------------------------------------------------------------------

function PresetIcon({ type, className }: { type: string; className?: string }) {
  const cn = className ?? "w-5 h-5";
  switch (type) {
    case "pie":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path d="M10 2a8 8 0 100 16 8 8 0 000-16zm0 1.5V10h6.5A6.5 6.5 0 0010 3.5z" />
        </svg>
      );
    case "bar":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path d="M15.5 2A1.5 1.5 0 0014 3.5v13a1.5 1.5 0 001.5 1.5h1a1.5 1.5 0 001.5-1.5v-13A1.5 1.5 0 0016.5 2h-1zM9.5 6A1.5 1.5 0 008 7.5v9A1.5 1.5 0 009.5 18h1a1.5 1.5 0 001.5-1.5v-9A1.5 1.5 0 0010.5 6h-1zM3.5 10A1.5 1.5 0 002 11.5v5A1.5 1.5 0 003.5 18h1A1.5 1.5 0 006 16.5v-5A1.5 1.5 0 004.5 10h-1z" />
        </svg>
      );
    case "team":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path d="M7 8a3 3 0 100-6 3 3 0 000 6zM14.5 9a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM1.615 16.428a1.224 1.224 0 01-.569-1.175 6.002 6.002 0 0111.908 0c.058.467-.172.92-.57 1.174A9.953 9.953 0 017 18a9.953 9.953 0 01-5.385-1.572zM14.5 16h-.106c.07-.297.088-.611.048-.933a7.47 7.47 0 00-1.588-3.755 4.502 4.502 0 015.874 2.636.818.818 0 01-.36.98A7.465 7.465 0 0114.5 16z" />
        </svg>
      );
    case "clock":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
        </svg>
      );
    case "age":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
        </svg>
      );
    case "trend":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M12 7a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0V8.414l-4.293 4.293a1 1 0 01-1.414 0L8 10.414l-4.293 4.293a1 1 0 01-1.414-1.414l5-5a1 1 0 011.414 0L11 10.586 14.586 7H12z" clipRule="evenodd" />
        </svg>
      );
    case "area":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M12 7a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0V8.414l-4.293 4.293a1 1 0 01-1.414 0L8 10.414l-4.293 4.293a1 1 0 01-1.414-1.414l5-5a1 1 0 011.414 0L11 10.586 14.586 7H12z" clipRule="evenodd" />
        </svg>
      );
    default:
      return null;
  }
}

function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
    </svg>
  );
}

function ChevronIcon({ open, className }: { open: boolean; className?: string }) {
  return (
    <svg
      className={`${className ?? "w-4 h-4"} transition-transform duration-200 ${open ? "rotate-180" : ""}`}
      viewBox="0 0 20 20"
      fill="currentColor"
    >
      <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Collapsible section
// ---------------------------------------------------------------------------

function Section({
  title,
  badge,
  defaultOpen = true,
  children,
}: {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-gray-50/60 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <ChevronIcon open={open} className="w-4 h-4 text-gray-400" />
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-500">
            {title}
          </h2>
          {badge && (
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-600">
              {badge}
            </span>
          )}
        </div>
      </button>
      {open && (
        <div className="border-t border-gray-100 px-5 py-4">
          {children}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function filtersToApi(f: TicketFilterValues): ReportFilters {
  return {
    status: f.status || undefined,
    priority: f.priority || undefined,
    assignee: f.assignee || undefined,
    issue_type: f.issue_type || undefined,
    search: f.search || undefined,
    open_only: f.open_only || undefined,
    stale_only: f.stale_only || undefined,
    created_after: f.created_after || undefined,
    created_before: f.created_before || undefined,
  };
}

// ---------------------------------------------------------------------------
// PNG Export
// ---------------------------------------------------------------------------

function exportChartAsPng(containerId: string) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const svg = container.querySelector("svg");
  if (!svg) return;

  const svgData = new XMLSerializer().serializeToString(svg);
  const svgBlob = new Blob([svgData], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);

  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement("canvas");
    const scale = 2; // retina
    canvas.width = img.width * scale;
    canvas.height = img.height * scale;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(scale, scale);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, img.width, img.height);
    ctx.drawImage(img, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const a = document.createElement("a");
      const blobUrl = URL.createObjectURL(blob);
      a.href = blobUrl;
      a.download = "chart.png";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    }, "image/png");
    URL.revokeObjectURL(url);
  };
  img.src = url;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function VisualizationsPage() {
  // Chart config state
  const [mode, setMode] = useState<Mode>("grouped");
  const [groupBy, setGroupBy] = useState("status");
  const [metric, setMetric] = useState("count");
  const [chartType, setChartType] = useState<GroupedChartType>("bar");
  const [tsChartType, setTsChartType] = useState<TimeseriesChartType>("line");
  const [timeBucket, setTimeBucket] = useState("week");

  // Filter state
  const [filters, setFilters] = useState<TicketFilterValues>({ ...emptyFilters, open_only: true });
  const [includeExcluded, setIncludeExcluded] = useState(false);
  const [activePreset, setActivePreset] = useState<string | null>(null);

  // Debounce config changes
  const configKey = useMemo(
    () => ({ mode, groupBy, metric, chartType, tsChartType, timeBucket, filters, includeExcluded }),
    [mode, groupBy, metric, chartType, tsChartType, timeBucket, filters, includeExcluded],
  );

  const [debouncedKey, setDebouncedKey] = useState(configKey);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedKey(configKey), 400);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [configKey]);

  // Build request objects
  const groupedReq: ChartDataRequest = useMemo(() => ({
    filters: filtersToApi(debouncedKey.filters),
    group_by: debouncedKey.groupBy,
    metric: debouncedKey.metric,
    include_excluded: debouncedKey.includeExcluded,
  }), [debouncedKey]);

  const timeseriesReq: ChartTimeseriesRequest = useMemo(() => ({
    filters: filtersToApi(debouncedKey.filters),
    bucket: debouncedKey.timeBucket,
    include_excluded: debouncedKey.includeExcluded,
  }), [debouncedKey]);

  // Queries
  const groupedQuery = useQuery<ChartDataResponse>({
    queryKey: ["chart-grouped", groupedReq],
    queryFn: () => api.getChartData(groupedReq),
    enabled: debouncedKey.mode === "grouped",
  });

  const timeseriesQuery = useQuery<ChartTimeseriesResponse>({
    queryKey: ["chart-timeseries", timeseriesReq],
    queryFn: () => api.getChartTimeseries(timeseriesReq),
    enabled: debouncedKey.mode === "timeseries",
  });

  const isLoading = mode === "grouped" ? groupedQuery.isLoading : timeseriesQuery.isLoading;
  const isFetching = mode === "grouped" ? groupedQuery.isFetching : timeseriesQuery.isFetching;
  const isError = mode === "grouped" ? groupedQuery.isError : timeseriesQuery.isError;

  // Preset handler
  const applyPreset = useCallback((preset: Preset) => {
    setMode(preset.mode);
    if (preset.mode === "grouped") {
      setGroupBy(preset.group_by ?? "status");
      setMetric(preset.metric ?? "count");
      setChartType(preset.chart_type ?? "bar");
    } else {
      setTsChartType(preset.ts_chart_type ?? "line");
      setTimeBucket(preset.time_bucket ?? "week");
    }
    setFilters({ ...emptyFilters });
    setIncludeExcluded(false);
    setActivePreset(preset.name);
  }, []);

  const metricLabel = METRIC_OPTIONS.find((m) => m.value === metric)?.label ?? metric;

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Visualizations</h1>
          <p className="mt-1 text-sm text-gray-500">
            Build custom charts to explore your ticket data.
          </p>
        </div>
        <button
          onClick={() => exportChartAsPng("chart-container")}
          className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-all hover:bg-slate-700 active:scale-[0.98]"
        >
          <DownloadIcon className="h-4 w-4" />
          Download as PNG
        </button>
      </div>

      {/* Presets */}
      <div className="grid grid-cols-4 gap-3 lg:grid-cols-7">
        {PRESETS.map((p) => {
          const active = activePreset === p.name;
          const accent = ACCENT_CLASSES[p.accent] ?? ACCENT_CLASSES.sky;
          return (
            <button
              key={p.name}
              onClick={() => applyPreset(p)}
              className={[
                "group relative flex flex-col items-start gap-1.5 rounded-lg border p-3 text-left transition-all",
                active
                  ? `${accent.activeBg} ${accent.activeBorder} ${accent.activeText} shadow-md`
                  : `${accent.bg} ${accent.border} hover:shadow-sm`,
              ].join(" ")}
            >
              <div className={`${active ? accent.activeText : accent.icon} transition-colors`}>
                <PresetIcon type={p.icon} className="w-5 h-5" />
              </div>
              <div>
                <div className={`text-xs font-semibold leading-tight ${active ? accent.activeText : accent.text}`}>
                  {p.name}
                </div>
                <div className={`mt-0.5 text-[10px] leading-snug ${active ? "text-white/80" : "text-gray-500"}`}>
                  {p.description}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Chart Type & Data */}
      <Section title="Chart Type & Data" defaultOpen={true}>
        <div className="space-y-4">
          {/* Mode toggle */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-gray-500">Mode</span>
            <div className="inline-flex rounded-md border border-gray-200 bg-gray-50 p-0.5">
              {(["grouped", "timeseries"] as Mode[]).map((m) => (
                <button
                  key={m}
                  onClick={() => { setMode(m); setActivePreset(null); }}
                  className={[
                    "rounded px-3 py-1.5 text-xs font-medium transition-all",
                    mode === m
                      ? "bg-white text-gray-900 shadow-sm"
                      : "text-gray-500 hover:text-gray-700",
                  ].join(" ")}
                >
                  {m === "grouped" ? "Grouped" : "Time Series"}
                </button>
              ))}
            </div>
          </div>

          {/* Chart type buttons */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-gray-500">Chart</span>
            <div className="inline-flex rounded-md border border-gray-200 bg-gray-50 p-0.5">
              {mode === "grouped"
                ? GROUPED_CHART_TYPES.map((ct) => (
                    <button
                      key={ct.value}
                      onClick={() => { setChartType(ct.value); setActivePreset(null); }}
                      className={[
                        "rounded px-3 py-1.5 text-xs font-medium transition-all",
                        chartType === ct.value
                          ? "bg-white text-gray-900 shadow-sm"
                          : "text-gray-500 hover:text-gray-700",
                      ].join(" ")}
                    >
                      {ct.label}
                    </button>
                  ))
                : TIMESERIES_CHART_TYPES.map((ct) => (
                    <button
                      key={ct.value}
                      onClick={() => { setTsChartType(ct.value); setActivePreset(null); }}
                      className={[
                        "rounded px-3 py-1.5 text-xs font-medium transition-all",
                        tsChartType === ct.value
                          ? "bg-white text-gray-900 shadow-sm"
                          : "text-gray-500 hover:text-gray-700",
                      ].join(" ")}
                    >
                      {ct.label}
                    </button>
                  ))}
            </div>
          </div>

          {/* Grouped-specific options */}
          {mode === "grouped" && (
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-500">Group by</span>
                <select
                  value={groupBy}
                  onChange={(e) => { setGroupBy(e.target.value); setActivePreset(null); }}
                  className="h-8 rounded-md border border-gray-200 bg-white px-2.5 text-xs text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
                >
                  {GROUP_BY_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-500">Metric</span>
                <select
                  value={metric}
                  onChange={(e) => { setMetric(e.target.value); setActivePreset(null); }}
                  className="h-8 rounded-md border border-gray-200 bg-white px-2.5 text-xs text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
                >
                  {METRIC_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {/* Timeseries-specific options */}
          {mode === "timeseries" && (
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-gray-500">Time bucket</span>
              <div className="inline-flex rounded-md border border-gray-200 bg-gray-50 p-0.5">
                {["week", "month"].map((b) => (
                  <button
                    key={b}
                    onClick={() => { setTimeBucket(b); setActivePreset(null); }}
                    className={[
                      "rounded px-3 py-1.5 text-xs font-medium transition-all capitalize",
                      timeBucket === b
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-500 hover:text-gray-700",
                    ].join(" ")}
                  >
                    {b}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </Section>

      {/* Filters */}
      <Section title="Filters" defaultOpen={false}>
        <div className="flex flex-wrap items-center gap-3">
          <TicketFilters
            filters={filters}
            onFilterChange={(f) => { setFilters(f); setActivePreset(null); }}
          />
          <label className="ml-2 flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-600 cursor-pointer hover:bg-gray-100 transition-colors select-none">
            <input
              type="checkbox"
              checked={includeExcluded}
              onChange={(e) => { setIncludeExcluded(e.target.checked); setActivePreset(null); }}
              className="h-3.5 w-3.5 rounded border-gray-300 text-slate-700 focus:ring-slate-500"
            />
            Include excluded
          </label>
        </div>
      </Section>

      {/* Chart Preview */}
      <section className="rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
        <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50/80 px-5 py-2.5">
          <div className="flex items-center gap-3">
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-500">
              Chart Preview
            </h2>
            {isFetching && (
              <svg className="h-3.5 w-3.5 animate-spin text-slate-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
          </div>
          {mode === "grouped" && groupedQuery.data && (
            <span className="text-[11px] tabular-nums text-gray-400">
              <span className="font-semibold text-gray-600">{groupedQuery.data.data.length}</span> groups
            </span>
          )}
          {mode === "timeseries" && timeseriesQuery.data && (
            <span className="text-[11px] tabular-nums text-gray-400">
              <span className="font-semibold text-gray-600">{timeseriesQuery.data.data.length}</span> periods
            </span>
          )}
        </div>

        <div id="chart-container" className="h-[400px] p-4">
          {isLoading ? (
            <div className="flex h-full flex-col items-center justify-center gap-3">
              <svg className="h-8 w-8 animate-spin text-slate-300" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-xs text-gray-400">Loading chart...</span>
            </div>
          ) : isError ? (
            <div className="flex h-full flex-col items-center justify-center gap-2">
              <svg className="w-8 h-8 text-red-300" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
              <span className="text-xs text-red-400">Failed to load chart data</span>
            </div>
          ) : mode === "grouped" && groupedQuery.data ? (
            <ChartRenderer
              type={chartType}
              data={groupedQuery.data.data}
              metricLabel={metricLabel}
            />
          ) : mode === "timeseries" && timeseriesQuery.data ? (
            <ChartRenderer
              type={tsChartType}
              data={timeseriesQuery.data.data}
            />
          ) : null}
        </div>
      </section>
    </div>
  );
}
