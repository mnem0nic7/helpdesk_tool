import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { TicketRow, CacheStatus } from "../lib/api.ts";
import SLAComplianceCard from "../components/SLAComplianceCard.tsx";

const PAGE_SIZE = 100;

// ---------------------------------------------------------------------------
// Priority badge color helper
// ---------------------------------------------------------------------------

function priorityColor(priority: string): string {
  switch (priority.toLowerCase()) {
    case "highest":
      return "bg-red-100 text-red-800";
    case "high":
      return "bg-orange-100 text-orange-800";
    case "medium":
      return "bg-yellow-100 text-yellow-800";
    case "low":
      return "bg-blue-100 text-blue-800";
    case "lowest":
      return "bg-gray-100 text-gray-700";
    default:
      return "bg-gray-100 text-gray-700";
  }
}

// ---------------------------------------------------------------------------
// SLA status badge helper
// ---------------------------------------------------------------------------

function slaStatusBadge(status: string): string {
  const s = status.toLowerCase();
  if (s.includes("breached")) return "bg-red-100 text-red-800";
  if (s.includes("met") || s.includes("completed")) return "bg-green-100 text-green-800";
  if (s.includes("paused")) return "bg-yellow-100 text-yellow-800";
  if (s.includes("running") || s.includes("ongoing")) return "bg-blue-100 text-blue-800";
  return "bg-gray-100 text-gray-700";
}

// ---------------------------------------------------------------------------
// Sort helpers
// ---------------------------------------------------------------------------

type SortField = "key" | "summary" | "status" | "priority" | "request_type" | "assignee" | "sla_first_response_status" | "sla_resolution_status";
type SortDir = "asc" | "desc";

const PRIORITY_ORDER: Record<string, number> = {
  highest: 0,
  high: 1,
  medium: 2,
  low: 3,
  lowest: 4,
};

function compareTickets(a: TicketRow, b: TicketRow, field: SortField, dir: SortDir): number {
  let cmp = 0;
  if (field === "priority") {
    const pa = PRIORITY_ORDER[a.priority.toLowerCase()] ?? 5;
    const pb = PRIORITY_ORDER[b.priority.toLowerCase()] ?? 5;
    cmp = pa - pb;
  } else {
    const va = (a[field] ?? "") as string;
    const vb = (b[field] ?? "") as string;
    cmp = va.localeCompare(vb);
  }
  return dir === "asc" ? cmp : -cmp;
}

// ---------------------------------------------------------------------------
// Sortable header component
// ---------------------------------------------------------------------------

function SortHeader({
  label,
  field,
  sortField,
  sortDir,
  onSort,
}: {
  label: string;
  field: SortField;
  sortField: SortField;
  sortDir: SortDir;
  onSort: (f: SortField) => void;
}) {
  const active = sortField === field;
  return (
    <th
      className="px-4 py-3 text-left text-xs font-semibold tracking-wider text-gray-600 uppercase cursor-pointer select-none hover:text-gray-900"
      onClick={() => onSort(field)}
    >
      {label}
      {active && (
        <span className="ml-1 text-gray-400">{sortDir === "asc" ? "▲" : "▼"}</span>
      )}
    </th>
  );
}

// ---------------------------------------------------------------------------
// Breached Tickets Table with sorting, filtering, infinite scroll
// ---------------------------------------------------------------------------

function BreachedTicketsTable({
  tickets,
  jiraBaseUrl,
}: {
  tickets: TicketRow[];
  jiraBaseUrl?: string;
}) {
  // Filters
  const [search, setSearch] = useState("");
  const [filterPriority, setFilterPriority] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterAssignee, setFilterAssignee] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const [staleOnly, setStaleOnly] = useState(false);

  // Sorting
  const [sortField, setSortField] = useState<SortField>("key");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  function handleSort(field: SortField) {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("asc");
    }
  }

  // Unique filter options
  const priorities = useMemo(() => [...new Set(tickets.map((t) => t.priority).filter(Boolean))].sort(), [tickets]);
  const statuses = useMemo(() => [...new Set(tickets.map((t) => t.status).filter(Boolean))].sort(), [tickets]);
  const assignees = useMemo(() => [...new Set(tickets.map((t) => t.assignee).filter(Boolean))].sort(), [tickets]);

  // Filtered + sorted tickets
  const processed = useMemo(() => {
    let list = tickets;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (t) =>
          t.key.toLowerCase().includes(q) ||
          t.summary.toLowerCase().includes(q) ||
          (t.assignee ?? "").toLowerCase().includes(q),
      );
    }
    if (filterPriority) list = list.filter((t) => t.priority === filterPriority);
    if (filterStatus) list = list.filter((t) => t.status === filterStatus);
    if (filterAssignee) list = list.filter((t) => t.assignee === filterAssignee);
    if (openOnly) list = list.filter((t) => t.status_category !== "Done");
    if (staleOnly) list = list.filter((t) => t.status_category !== "Done" && (t.days_since_update ?? 0) >= 7);
    return [...list].sort((a, b) => compareTickets(a, b, sortField, sortDir));
  }, [tickets, search, filterPriority, filterStatus, filterAssignee, openOnly, staleOnly, sortField, sortDir]);

  // Infinite scroll
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [processed.length, search, filterPriority, filterStatus, filterAssignee, openOnly, staleOnly]);

  const loadMore = useCallback(() => {
    setVisibleCount((prev) => Math.min(prev + PAGE_SIZE, processed.length));
  }, [processed.length]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) loadMore();
      },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loadMore, visibleCount]);

  const visible = processed.slice(0, visibleCount);
  const hasMore = visibleCount < processed.length;

  const hasFilters = !!(search || filterPriority || filterStatus || filterAssignee || openOnly || staleOnly);

  return (
    <div>
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 border-b border-gray-100 px-5 py-3">
        <input
          type="text"
          placeholder="Search key, summary, assignee..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400 w-64"
        />
        <select
          value={filterPriority}
          onChange={(e) => setFilterPriority(e.target.value)}
          className="rounded-md border border-gray-300 px-2 py-1.5 text-sm shadow-sm focus:border-blue-400 focus:outline-none"
        >
          <option value="">All Priorities</option>
          {priorities.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="rounded-md border border-gray-300 px-2 py-1.5 text-sm shadow-sm focus:border-blue-400 focus:outline-none"
        >
          <option value="">All Statuses</option>
          {statuses.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={filterAssignee}
          onChange={(e) => setFilterAssignee(e.target.value)}
          className="rounded-md border border-gray-300 px-2 py-1.5 text-sm shadow-sm focus:border-blue-400 focus:outline-none"
        >
          <option value="">All Assignees</option>
          {assignees.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        <button
          onClick={() => setOpenOnly((v) => !v)}
          className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
            openOnly
              ? "border-blue-500 bg-blue-50 text-blue-700"
              : "border-gray-300 bg-white text-gray-600 hover:bg-gray-50"
          }`}
        >
          Open Only
        </button>
        <button
          onClick={() => setStaleOnly((v) => !v)}
          className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
            staleOnly
              ? "border-amber-500 bg-amber-50 text-amber-700"
              : "border-gray-300 bg-white text-gray-600 hover:bg-gray-50"
          }`}
        >
          Stale (7d+)
        </button>
        {hasFilters && (
          <button
            onClick={() => { setSearch(""); setFilterPriority(""); setFilterStatus(""); setFilterAssignee(""); setOpenOnly(false); setStaleOnly(false); }}
            className="text-xs text-gray-500 hover:text-gray-700 underline"
          >
            Clear filters
          </button>
        )}
        <span className="ml-auto text-xs text-gray-400">
          {processed.length} ticket{processed.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Table */}
      {processed.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-500">
          {hasFilters ? "No tickets match filters." : "No breached tickets found."}
        </p>
      ) : (
        <div className="max-h-[65vh] overflow-y-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="sticky top-0 bg-gray-50">
              <tr>
                <SortHeader label="Key" field="key" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Summary" field="summary" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Status" field="status" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Priority" field="priority" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Request Type" field="request_type" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="Assignee" field="assignee" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="SLA Response" field="sla_first_response_status" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                <SortHeader label="SLA Resolution" field="sla_resolution_status" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {visible.map((ticket) => (
                <tr key={ticket.key} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-4 py-3 font-medium">
                    {jiraBaseUrl ? (
                      <a
                        href={`${jiraBaseUrl}/browse/${ticket.key}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline"
                      >
                        {ticket.key}
                      </a>
                    ) : (
                      <span className="text-blue-700">{ticket.key}</span>
                    )}
                  </td>
                  <td className="max-w-xs truncate px-4 py-3 text-gray-800" title={ticket.summary}>
                    {ticket.summary}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-gray-700">
                    {ticket.status}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${priorityColor(ticket.priority)}`}
                    >
                      {ticket.priority}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-gray-600">
                    {ticket.request_type || "\u2014"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-gray-700">
                    {ticket.assignee || "Unassigned"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${slaStatusBadge(ticket.sla_first_response_status)}`}
                    >
                      {ticket.sla_first_response_status || "N/A"}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${slaStatusBadge(ticket.sla_resolution_status)}`}
                    >
                      {ticket.sla_resolution_status || "N/A"}
                    </span>
                  </td>
                </tr>
              ))}
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
  );
}

// ---------------------------------------------------------------------------
// SLA Page
// ---------------------------------------------------------------------------

export default function SLAPage() {
  const {
    data: timers,
    isLoading: loadingSummary,
    error: summaryError,
  } = useQuery({
    queryKey: ["sla-summary"],
    queryFn: api.getSLASummary,
  });

  const {
    data: breaches,
    isLoading: loadingBreaches,
    error: breachesError,
  } = useQuery({
    queryKey: ["sla-breaches"],
    queryFn: api.getSLABreaches,
  });

  const { data: cacheStatus } = useQuery<CacheStatus>({
    queryKey: ["cache-status"],
    queryFn: () => api.getCacheStatus(),
    staleTime: Infinity,
  });
  const jiraBaseUrl = cacheStatus?.jira_base_url;

  // ---- Loading state ----
  if (loadingSummary || loadingBreaches) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
        <p className="mt-4 text-sm text-gray-500">Loading SLA data...</p>
      </div>
    );
  }

  // ---- Error state ----
  if (summaryError || breachesError) {
    const msg =
      (summaryError as Error)?.message ||
      (breachesError as Error)?.message ||
      "Unknown error";
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6">
        <h2 className="text-lg font-semibold text-red-800">
          Failed to load SLA data
        </h2>
        <p className="mt-2 text-sm text-red-700">{msg}</p>
      </div>
    );
  }

  const timerList = timers ?? [];
  const breachList = breaches ?? [];

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">SLA Tracker</h1>
        <p className="mt-1 text-sm text-gray-500">
          Monitor SLA compliance rates and track breached tickets.
        </p>
      </div>

      {/* SLA Compliance Cards Grid */}
      {timerList.length > 0 ? (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {timerList.map((timer) => (
            <SLAComplianceCard key={timer.timer_name} timer={timer} />
          ))}
        </div>
      ) : (
        <div className="rounded-lg bg-white p-6 text-center text-sm text-gray-500 shadow">
          No SLA timer data available.
        </div>
      )}

      {/* Breached Tickets Section */}
      <div className="rounded-lg bg-white shadow">
        <div className="flex items-center gap-3 border-b border-gray-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-gray-900">
            Breached Tickets
          </h2>
          <span className="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800">
            {breachList.length}
          </span>
        </div>
        <BreachedTicketsTable tickets={breachList} jiraBaseUrl={jiraBaseUrl} />
      </div>
    </div>
  );
}
