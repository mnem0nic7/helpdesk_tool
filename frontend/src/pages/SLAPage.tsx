import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type {
  SLAMetricsResponse, SLATicketRow, SLATimerStats, SLATarget,
  SLASettings, CacheStatus,
} from "../lib/api.ts";

const PAGE_SIZE = 100;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function priorityColor(priority: string): string {
  switch (priority.toLowerCase()) {
    case "highest": return "bg-red-100 text-red-800";
    case "high": return "bg-orange-100 text-orange-800";
    case "medium": return "bg-yellow-100 text-yellow-800";
    case "low": return "bg-blue-100 text-blue-800";
    case "lowest": return "bg-gray-100 text-gray-700";
    default: return "bg-gray-100 text-gray-700";
  }
}

function slaStatusBadge(status: string): { bg: string; label: string } {
  switch (status) {
    case "met": return { bg: "bg-green-100 text-green-800", label: "Met" };
    case "breached": return { bg: "bg-red-100 text-red-800", label: "Breached" };
    case "running": return { bg: "bg-blue-100 text-blue-800", label: "Running" };
    default: return { bg: "bg-gray-100 text-gray-700", label: status };
  }
}

function formatMinutes(m: number): string {
  if (m < 60) return `${Math.round(m)}m`;
  const h = Math.floor(m / 60);
  const rm = Math.round(m % 60);
  if (h < 24) return rm > 0 ? `${h}h ${rm}m` : `${h}h`;
  const d = Math.floor(h / 24);
  const rh = h % 24;
  return rh > 0 ? `${d}d ${rh}h` : `${d}d`;
}

type SortField = "key" | "summary" | "status" | "priority" | "assignee" | "fr_status" | "fr_elapsed" | "res_status" | "res_elapsed";
type SortDir = "asc" | "desc";

const PRIORITY_ORDER: Record<string, number> = {
  highest: 0, high: 1, medium: 2, low: 3, lowest: 4,
};

function compareTickets(a: SLATicketRow, b: SLATicketRow, field: SortField, dir: SortDir): number {
  let cmp = 0;
  if (field === "priority") {
    cmp = (PRIORITY_ORDER[a.priority.toLowerCase()] ?? 5) - (PRIORITY_ORDER[b.priority.toLowerCase()] ?? 5);
  } else if (field === "fr_status") {
    cmp = (a.sla_first_response?.status ?? "").localeCompare(b.sla_first_response?.status ?? "");
  } else if (field === "fr_elapsed") {
    cmp = (a.sla_first_response?.elapsed_minutes ?? 0) - (b.sla_first_response?.elapsed_minutes ?? 0);
  } else if (field === "res_status") {
    cmp = (a.sla_resolution?.status ?? "").localeCompare(b.sla_resolution?.status ?? "");
  } else if (field === "res_elapsed") {
    cmp = (a.sla_resolution?.elapsed_minutes ?? 0) - (b.sla_resolution?.elapsed_minutes ?? 0);
  } else {
    const va = (a[field as keyof SLATicketRow] ?? "") as string;
    const vb = (b[field as keyof SLATicketRow] ?? "") as string;
    cmp = va.localeCompare(vb);
  }
  return dir === "asc" ? cmp : -cmp;
}

// ---------------------------------------------------------------------------
// SLA Summary Card
// ---------------------------------------------------------------------------

function SLASummaryCard({ title, stats }: { title: string; stats: SLATimerStats }) {
  const completed = stats.met + stats.breached;
  const metPct = completed > 0 ? (stats.met / completed) * 100 : 0;
  const breachedPct = completed > 0 ? (stats.breached / completed) * 100 : 0;
  const runningPct = stats.total > 0 ? (stats.running / stats.total) * 100 : 0;

  return (
    <div className="rounded-lg bg-white px-5 py-5 shadow">
      <h3 className="text-sm font-semibold tracking-wide text-gray-700 uppercase">{title}</h3>
      <div className="mt-3 flex items-baseline gap-4">
        <div>
          <span className="text-3xl font-bold text-green-600">{stats.compliance_pct.toFixed(1)}%</span>
          <span className="ml-1 text-xs text-gray-500">Compliance</span>
        </div>
        {stats.avg_elapsed_minutes > 0 && (
          <div>
            <span className="text-lg font-semibold text-gray-700">{formatMinutes(stats.avg_elapsed_minutes)}</span>
            <span className="ml-1 text-xs text-gray-500">Avg</span>
          </div>
        )}
      </div>
      <div className="mt-4 flex h-4 w-full overflow-hidden rounded-full bg-gray-100">
        {metPct > 0 && <div className="bg-green-500 transition-all" style={{ width: `${metPct}%` }} title={`Met: ${stats.met}`} />}
        {runningPct > 0 && <div className="bg-blue-500 transition-all" style={{ width: `${runningPct}%` }} title={`Running: ${stats.running}`} />}
        {breachedPct > 0 && <div className="bg-red-500 transition-all" style={{ width: `${breachedPct}%` }} title={`Breached: ${stats.breached}`} />}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-600">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-500" />Met: {stats.met}</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-red-500" />Breached: {stats.breached}</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-blue-500" />Running: {stats.running}</span>
        <span className="text-gray-400">Total: {stats.total}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sortable Header
// ---------------------------------------------------------------------------

function SortHeader({ label, field, sortField, sortDir, onSort }: {
  label: string; field: SortField; sortField: SortField; sortDir: SortDir;
  onSort: (f: SortField) => void;
}) {
  return (
    <th
      className="px-4 py-3 text-left text-xs font-semibold tracking-wider text-gray-600 uppercase cursor-pointer select-none hover:text-gray-900"
      onClick={() => onSort(field)}
    >
      {label}
      {sortField === field && <span className="ml-1 text-gray-400">{sortDir === "asc" ? "\u25B2" : "\u25BC"}</span>}
    </th>
  );
}

// ---------------------------------------------------------------------------
// Settings Modal
// ---------------------------------------------------------------------------

function SLASettingsModal({ settings, targets, onClose }: {
  settings: SLASettings; targets: SLATarget[]; onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [localSettings, setLocalSettings] = useState(settings);
  const [saving, setSaving] = useState(false);

  // New target form
  const [newType, setNewType] = useState<"first_response" | "resolution">("first_response");
  const [newDim, setNewDim] = useState<"default" | "priority" | "request_type">("default");
  const [newDimVal, setNewDimVal] = useState("*");
  const [newHours, setNewHours] = useState("");

  const TIMEZONES = [
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Phoenix", "America/Anchorage", "Pacific/Honolulu", "UTC",
  ];

  const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const activeDays = new Set(localSettings.business_days.split(",").map(Number));

  function toggleDay(d: number) {
    const next = new Set(activeDays);
    if (next.has(d)) next.delete(d); else next.add(d);
    setLocalSettings({ ...localSettings, business_days: [...next].sort().join(",") });
  }

  async function saveSettings() {
    setSaving(true);
    try {
      await api.updateSLASettings(localSettings);
      queryClient.invalidateQueries({ queryKey: ["sla-metrics"] });
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  }

  async function addTarget() {
    const mins = parseFloat(newHours) * 60;
    if (!mins || mins <= 0) return;
    try {
      await api.setSLATarget({
        sla_type: newType,
        dimension: newDim,
        dimension_value: newDim === "default" ? "*" : newDimVal,
        target_minutes: Math.round(mins),
      });
      queryClient.invalidateQueries({ queryKey: ["sla-metrics"] });
      setNewHours("");
      setNewDimVal("*");
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  async function deleteTarget(id: number) {
    try {
      await api.deleteSLATarget(id);
      queryClient.invalidateQueries({ queryKey: ["sla-metrics"] });
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">SLA Settings</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>

        <div className="space-y-6 p-6">
          {/* Business Hours */}
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Business Hours</h3>
            <div className="grid grid-cols-2 gap-4">
              <label className="block">
                <span className="text-xs text-gray-500">Start Time</span>
                <input type="time" value={localSettings.business_hours_start}
                  onChange={(e) => setLocalSettings({ ...localSettings, business_hours_start: e.target.value })}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm" />
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">End Time</span>
                <input type="time" value={localSettings.business_hours_end}
                  onChange={(e) => setLocalSettings({ ...localSettings, business_hours_end: e.target.value })}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm" />
              </label>
            </div>
            <label className="mt-3 block">
              <span className="text-xs text-gray-500">Timezone</span>
              <select value={localSettings.business_timezone}
                onChange={(e) => setLocalSettings({ ...localSettings, business_timezone: e.target.value })}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm">
                {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
              </select>
            </label>
            <div className="mt-3">
              <span className="text-xs text-gray-500">Working Days</span>
              <div className="mt-1 flex gap-1">
                {DAY_NAMES.map((name, i) => (
                  <button key={i} onClick={() => toggleDay(i)}
                    className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                      activeDays.has(i) ? "bg-blue-100 text-blue-700 border border-blue-300" : "bg-gray-100 text-gray-400 border border-gray-200"
                    }`}>
                    {name}
                  </button>
                ))}
              </div>
            </div>
            <button onClick={saveSettings} disabled={saving}
              className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {saving ? "Saving..." : "Save Business Hours"}
            </button>
          </div>

          {/* SLA Targets */}
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-3">SLA Targets</h3>
            <div className="rounded-lg border border-gray-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2 text-left text-xs text-gray-500">Type</th>
                    <th className="px-3 py-2 text-left text-xs text-gray-500">Dimension</th>
                    <th className="px-3 py-2 text-left text-xs text-gray-500">Value</th>
                    <th className="px-3 py-2 text-left text-xs text-gray-500">Target</th>
                    <th className="px-3 py-2 text-right text-xs text-gray-500"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {targets.map((t) => (
                    <tr key={t.id}>
                      <td className="px-3 py-2">{t.sla_type === "first_response" ? "First Response" : "Resolution"}</td>
                      <td className="px-3 py-2 capitalize">{t.dimension === "default" ? "Default" : t.dimension.replace("_", " ")}</td>
                      <td className="px-3 py-2">{t.dimension_value === "*" ? "All" : t.dimension_value}</td>
                      <td className="px-3 py-2">{formatMinutes(t.target_minutes)}</td>
                      <td className="px-3 py-2 text-right">
                        <button onClick={() => deleteTarget(t.id)} className="text-red-500 hover:text-red-700 text-xs">Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Add Target */}
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <label className="block">
                <span className="text-xs text-gray-500">Type</span>
                <select value={newType} onChange={(e) => setNewType(e.target.value as "first_response" | "resolution")}
                  className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm">
                  <option value="first_response">First Response</option>
                  <option value="resolution">Resolution</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Dimension</span>
                <select value={newDim} onChange={(e) => { setNewDim(e.target.value as "default" | "priority" | "request_type"); if (e.target.value === "default") setNewDimVal("*"); }}
                  className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm">
                  <option value="default">Default</option>
                  <option value="priority">Priority</option>
                  <option value="request_type">Request Type</option>
                </select>
              </label>
              {newDim !== "default" && (
                <label className="block">
                  <span className="text-xs text-gray-500">Value</span>
                  <input type="text" value={newDimVal} onChange={(e) => setNewDimVal(e.target.value)}
                    placeholder={newDim === "priority" ? "e.g. High" : "e.g. IT Help"}
                    className="mt-1 block w-32 rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
                </label>
              )}
              <label className="block">
                <span className="text-xs text-gray-500">Target (hours)</span>
                <input type="number" step="0.5" min="0.5" value={newHours} onChange={(e) => setNewHours(e.target.value)}
                  placeholder="e.g. 2"
                  className="mt-1 block w-20 rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
              </label>
              <button onClick={addTarget}
                className="rounded-lg bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700">
                Add
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SLA Page
// ---------------------------------------------------------------------------

export default function SLAPage() {
  // Date range state
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [showSettings, setShowSettings] = useState(false);

  const { data: cacheStatus } = useQuery<CacheStatus>({
    queryKey: ["cache-status"],
    queryFn: () => api.getCacheStatus(),
    staleTime: Infinity,
  });
  const jiraBaseUrl = cacheStatus?.jira_base_url;

  const { data, isLoading, error } = useQuery<SLAMetricsResponse>({
    queryKey: ["sla-metrics", dateFrom, dateTo],
    queryFn: () => api.getSLAMetrics(dateFrom || undefined, dateTo || undefined),
  });

  // Filter / sort state
  const [search, setSearch] = useState("");
  const [filterPriority, setFilterPriority] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterAssignee, setFilterAssignee] = useState("");
  const [filterSLA, setFilterSLA] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const [staleOnly, setStaleOnly] = useState(false);
  const [sortField, setSortField] = useState<SortField>("key");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  function handleSort(field: SortField) {
    if (sortField === field) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortField(field); setSortDir("asc"); }
  }

  const tickets = data?.tickets ?? [];

  const priorities = useMemo(() => [...new Set(tickets.map((t) => t.priority).filter(Boolean))].sort(), [tickets]);
  const statuses = useMemo(() => [...new Set(tickets.map((t) => t.status).filter(Boolean))].sort(), [tickets]);
  const assignees = useMemo(() => [...new Set(tickets.map((t) => t.assignee).filter(Boolean))].sort(), [tickets]);

  const processed = useMemo(() => {
    let list = tickets;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((t) =>
        t.key.toLowerCase().includes(q) ||
        t.summary.toLowerCase().includes(q) ||
        (t.assignee ?? "").toLowerCase().includes(q));
    }
    if (filterPriority) list = list.filter((t) => t.priority === filterPriority);
    if (filterStatus) list = list.filter((t) => t.status === filterStatus);
    if (filterAssignee) list = list.filter((t) => t.assignee === filterAssignee);
    if (filterSLA === "fr_breached") list = list.filter((t) => t.sla_first_response?.status === "breached");
    if (filterSLA === "fr_met") list = list.filter((t) => t.sla_first_response?.status === "met");
    if (filterSLA === "res_breached") list = list.filter((t) => t.sla_resolution?.status === "breached");
    if (filterSLA === "res_met") list = list.filter((t) => t.sla_resolution?.status === "met");
    if (filterSLA === "any_breached") list = list.filter((t) => t.sla_first_response?.status === "breached" || t.sla_resolution?.status === "breached");
    if (openOnly) list = list.filter((t) => t.status_category !== "Done");
    if (staleOnly) list = list.filter((t) => t.status_category !== "Done" && (t.days_since_update ?? 0) >= 1);
    return [...list].sort((a, b) => compareTickets(a, b, sortField, sortDir));
  }, [tickets, search, filterPriority, filterStatus, filterAssignee, filterSLA, openOnly, staleOnly, sortField, sortDir]);

  // Infinite scroll
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setVisibleCount(PAGE_SIZE); }, [processed.length]);

  const loadMore = useCallback(() => {
    setVisibleCount((prev) => Math.min(prev + PAGE_SIZE, processed.length));
  }, [processed.length]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) loadMore(); },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loadMore, visibleCount]);

  const visible = processed.slice(0, visibleCount);
  const hasMore = visibleCount < processed.length;
  const hasFilters = !!(search || filterPriority || filterStatus || filterAssignee || filterSLA || openOnly || staleOnly);

  // Loading
  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
        <p className="mt-4 text-sm text-gray-500">Computing SLA metrics...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6">
        <h2 className="text-lg font-semibold text-red-800">Failed to load SLA data</h2>
        <p className="mt-2 text-sm text-red-700">{(error as Error)?.message}</p>
      </div>
    );
  }

  const summary = data!.summary;

  return (
    <div className="space-y-6">
      {/* Header row */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">SLA Tracker</h1>
          <p className="mt-1 text-sm text-gray-500">
            Custom SLA compliance based on business hours.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Date controls */}
          <label className="block">
            <span className="text-xs text-gray-500">From</span>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
              className="mt-1 block rounded-md border border-gray-300 px-3 py-1.5 text-sm" />
          </label>
          <label className="block">
            <span className="text-xs text-gray-500">To</span>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
              className="mt-1 block rounded-md border border-gray-300 px-3 py-1.5 text-sm" />
          </label>
          {(dateFrom || dateTo) && (
            <button onClick={() => { setDateFrom(""); setDateTo(""); }}
              className="mt-5 text-xs text-gray-500 hover:text-gray-700 underline">Clear</button>
          )}
          <button onClick={() => setShowSettings(true)}
            className="mt-5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 shadow-sm">
            Settings
          </button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <SLASummaryCard title="First Response" stats={summary.first_response} />
        <SLASummaryCard title="Resolution" stats={summary.resolution} />
      </div>

      {/* Tickets table */}
      <div className="rounded-lg bg-white shadow">
        <div className="flex items-center gap-3 border-b border-gray-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Tickets</h2>
          <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700">
            {processed.length}
          </span>
        </div>

        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-3 border-b border-gray-100 px-5 py-3">
          <input type="text" placeholder="Search key, summary, assignee..." value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400 w-64" />
          <select value={filterPriority} onChange={(e) => setFilterPriority(e.target.value)}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm">
            <option value="">All Priorities</option>
            {priorities.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm">
            <option value="">All Statuses</option>
            {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={filterAssignee} onChange={(e) => setFilterAssignee(e.target.value)}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm">
            <option value="">All Assignees</option>
            {assignees.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <select value={filterSLA} onChange={(e) => setFilterSLA(e.target.value)}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm">
            <option value="">All SLA Status</option>
            <option value="any_breached">Any Breached</option>
            <option value="fr_breached">FR Breached</option>
            <option value="fr_met">FR Met</option>
            <option value="res_breached">Res Breached</option>
            <option value="res_met">Res Met</option>
          </select>
          <button onClick={() => setOpenOnly((v) => !v)}
            className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
              openOnly ? "border-blue-500 bg-blue-50 text-blue-700" : "border-gray-300 bg-white text-gray-600 hover:bg-gray-50"
            }`}>Open Only</button>
          <button onClick={() => setStaleOnly((v) => !v)}
            className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
              staleOnly ? "border-amber-500 bg-amber-50 text-amber-700" : "border-gray-300 bg-white text-gray-600 hover:bg-gray-50"
            }`}>Stale (1d+)</button>
          {hasFilters && (
            <button onClick={() => { setSearch(""); setFilterPriority(""); setFilterStatus(""); setFilterAssignee(""); setFilterSLA(""); setOpenOnly(false); setStaleOnly(false); }}
              className="text-xs text-gray-500 hover:text-gray-700 underline">Clear filters</button>
          )}
        </div>

        {/* Table */}
        {processed.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-500">
            {hasFilters ? "No tickets match filters." : "No tickets found in date range."}
          </p>
        ) : (
          <div className="max-h-[60vh] overflow-y-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="sticky top-0 bg-gray-50">
                <tr>
                  <SortHeader label="Key" field="key" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Summary" field="summary" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Priority" field="priority" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Status" field="status" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Assignee" field="assignee" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="FR Status" field="fr_status" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="FR Time" field="fr_elapsed" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Res Status" field="res_status" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Res Time" field="res_elapsed" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {visible.map((t) => {
                  const fr = t.sla_first_response;
                  const res = t.sla_resolution;
                  const frBadge = fr ? slaStatusBadge(fr.status) : null;
                  const resBadge = res ? slaStatusBadge(res.status) : null;
                  return (
                    <tr key={t.key} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-3 font-medium">
                        {jiraBaseUrl ? (
                          <a href={`${jiraBaseUrl}/browse/${t.key}`} target="_blank" rel="noopener noreferrer"
                            className="text-blue-600 hover:underline">{t.key}</a>
                        ) : <span className="text-blue-700">{t.key}</span>}
                      </td>
                      <td className="max-w-xs truncate px-4 py-3 text-gray-800" title={t.summary}>{t.summary}</td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${priorityColor(t.priority)}`}>{t.priority}</span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-gray-700">{t.status}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-gray-700">{t.assignee || "Unassigned"}</td>
                      <td className="whitespace-nowrap px-4 py-3">
                        {frBadge ? <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${frBadge.bg}`}>{frBadge.label}</span> : <span className="text-gray-300">N/A</span>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-600">
                        {fr ? <span title={`Target: ${formatMinutes(fr.target_minutes)}`}>{formatMinutes(fr.elapsed_minutes)}</span> : "\u2014"}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        {resBadge ? <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${resBadge.bg}`}>{resBadge.label}</span> : <span className="text-gray-300">N/A</span>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-600">
                        {res ? <span title={`Target: ${formatMinutes(res.target_minutes)}`}>{formatMinutes(res.elapsed_minutes)}</span> : "\u2014"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {hasMore && (
              <div ref={sentinelRef} className="px-4 py-3 text-center text-xs text-gray-400">
                Showing {visibleCount} of {processed.length} tickets — scroll for more
              </div>
            )}
          </div>
        )}
      </div>

      {/* Settings modal */}
      {showSettings && data && (
        <SLASettingsModal
          settings={data.settings}
          targets={data.targets}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}
