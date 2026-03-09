import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { TicketQueryParams, TicketRow } from "../lib/api.ts";
import TicketFilters, {
  emptyFilters,
} from "../components/TicketFilters.tsx";
import type { TicketFilterValues } from "../components/TicketFilters.tsx";
import TicketTable from "../components/TicketTable.tsx";
import BulkActionsToolbar from "../components/BulkActionsToolbar.tsx";
import Pagination from "../components/Pagination.tsx";
import TicketWorkbenchDrawer from "../components/TicketWorkbenchDrawer.tsx";

// Quick-filter preset definitions
type QuickFilter = "triage" | "all_open" | null;
const PAGE_SIZE = 250;

export default function ManagePage() {
  const queryClient = useQueryClient();

  const [filters, setFilters] = useState<TicketFilterValues>({
    ...emptyFilters,
    open_only: true,
  });
  const [page, setPage] = useState(1);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [activeQuickFilter, setActiveQuickFilter] = useState<QuickFilter>("all_open");
  const [openTicket, setOpenTicket] = useState<TicketRow | null>(null);

  // When filters change, clear selection
  const handleFilterChange = useCallback((next: TicketFilterValues) => {
    setFilters(next);
    setPage(1);
    setSelectedKeys(new Set());
    setActiveQuickFilter(null); // Manual filter change clears quick filter
  }, []);

  // Quick filter handlers
  function handleTriageQueue() {
    const next: TicketFilterValues = {
      ...emptyFilters,
      open_only: true,
    };
    setFilters(next);
    setPage(1);
    setSelectedKeys(new Set());
    setActiveQuickFilter("triage");
  }

  function handleAllOpen() {
    const next: TicketFilterValues = {
      ...emptyFilters,
      open_only: true,
    };
    setFilters(next);
    setPage(1);
    setSelectedKeys(new Set());
    setActiveQuickFilter("all_open");
  }

  function handleClearQuickFilter() {
    setFilters({ ...emptyFilters });
    setPage(1);
    setSelectedKeys(new Set());
    setActiveQuickFilter(null);
  }

  // Build query params
  const queryParams: TicketQueryParams = {
    ...(filters.search ? { search: filters.search } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.priority ? { priority: filters.priority } : {}),
    ...(filters.issue_type ? { issue_type: filters.issue_type } : {}),
    ...(filters.open_only ? { open_only: true } : {}),
    ...(filters.stale_only ? { stale_only: true } : {}),
    ...(filters.created_after ? { created_after: filters.created_after } : {}),
    ...(filters.created_before ? { created_before: filters.created_before } : {}),
    // For triage queue, filter to unassigned tickets
    ...(activeQuickFilter === "triage" ? { assignee: "unassigned" } : filters.assignee ? { assignee: filters.assignee } : {}),
    offset: (page - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
  };

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["manage-tickets", queryParams],
    queryFn: () => api.getTickets(queryParams),
  });

  const tickets = data?.tickets ?? [];
  const matchedCount = data?.matched_count ?? tickets.length;
  const totalCount = data?.total_count ?? tickets.length;
  const hasMore = page * PAGE_SIZE < matchedCount;

  // Bulk action completed: refresh cache, clear selection, refetch
  function handleActionComplete() {
    setSelectedKeys(new Set());
    api.refreshCacheIncremental().then(() => {
      queryClient.invalidateQueries({ queryKey: ["manage-tickets"] });
      queryClient.invalidateQueries({ queryKey: ["metrics"] });
      queryClient.invalidateQueries({ queryKey: ["sla-summary"] });
      queryClient.invalidateQueries({ queryKey: ["sla-breaches"] });
      queryClient.invalidateQueries({ queryKey: ["cache-status"] });
    }).catch(() => {
      // Still invalidate queries so UI reflects whatever state exists
      queryClient.invalidateQueries({ queryKey: ["manage-tickets"] });
    });
  }

  // Convert Set to array for the toolbar
  const selectedKeysArray = Array.from(selectedKeys);

  // Quick filter button styles
  const quickBtnBase =
    "h-9 rounded-md border px-3 text-sm font-medium shadow-sm transition-colors";
  const quickBtnActive = "border-blue-600 bg-blue-600 text-white";
  const quickBtnInactive =
    "border-gray-300 bg-white text-gray-700 hover:bg-gray-50";

  return (
    <div className="space-y-4">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Manage Tickets</h1>
          <p className="mt-1 text-sm text-gray-500">
            Review tickets, open full details, and apply ticket actions without leaving the app.
          </p>
        </div>
        {!isLoading && (
          <span className="text-sm text-slate-500">
            <span className="font-semibold text-slate-800">{matchedCount.toLocaleString()}</span>
            {" "}matched of {totalCount.toLocaleString()}
          </span>
        )}
      </div>

      {/* Bulk actions toolbar */}
      <BulkActionsToolbar
        selectedKeys={selectedKeysArray}
        onActionComplete={handleActionComplete}
      />

      {/* Quick filter buttons */}
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wider text-gray-500">
          Quick Filters:
        </span>
        <button
          type="button"
          onClick={handleTriageQueue}
          className={`${quickBtnBase} ${activeQuickFilter === "triage" ? quickBtnActive : quickBtnInactive}`}
        >
          Triage Queue
        </button>
        <button
          type="button"
          onClick={handleAllOpen}
          className={`${quickBtnBase} ${activeQuickFilter === "all_open" ? quickBtnActive : quickBtnInactive}`}
        >
          All Open
        </button>
        <button
          type="button"
          onClick={handleClearQuickFilter}
          className={`${quickBtnBase} ${activeQuickFilter === null ? quickBtnActive : quickBtnInactive}`}
        >
          Clear
        </button>
      </div>

      {/* Filters */}
      <TicketFilters filters={filters} onFilterChange={handleFilterChange} />

      {/* Error state */}
      {isError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load tickets:{" "}
          {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {/* Table with selectable checkboxes */}
      <TicketTable
        data={tickets}
        loading={isLoading}
        selectable={true}
        selectedKeys={selectedKeys}
        onSelectionChange={setSelectedKeys}
        onRowOpen={setOpenTicket}
      />

      <Pagination
        page={page}
        hasMore={hasMore}
        onPageChange={(nextPage) => {
          setPage(nextPage);
          setSelectedKeys(new Set());
        }}
      />

      <TicketWorkbenchDrawer
        ticketKey={openTicket?.key ?? null}
        initialTicket={openTicket}
        onClose={() => setOpenTicket(null)}
      />
    </div>
  );
}
