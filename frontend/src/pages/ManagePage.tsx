import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { TicketQueryParams } from "../lib/api.ts";
import TicketFilters, {
  emptyFilters,
} from "../components/TicketFilters.tsx";
import type { TicketFilterValues } from "../components/TicketFilters.tsx";
import TicketTable from "../components/TicketTable.tsx";
import BulkActionsToolbar from "../components/BulkActionsToolbar.tsx";

// Quick-filter preset definitions
type QuickFilter = "triage" | "all_open" | null;

export default function ManagePage() {
  const queryClient = useQueryClient();

  const [filters, setFilters] = useState<TicketFilterValues>({
    ...emptyFilters,
    open_only: true,
  });
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [activeQuickFilter, setActiveQuickFilter] = useState<QuickFilter>("all_open");

  // When filters change, clear selection
  const handleFilterChange = useCallback((next: TicketFilterValues) => {
    setFilters(next);
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
    setSelectedKeys(new Set());
    setActiveQuickFilter("triage");
  }

  function handleAllOpen() {
    const next: TicketFilterValues = {
      ...emptyFilters,
      open_only: true,
    };
    setFilters(next);
    setSelectedKeys(new Set());
    setActiveQuickFilter("all_open");
  }

  function handleClearQuickFilter() {
    setFilters({ ...emptyFilters });
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
  };

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["manage-tickets", queryParams],
    queryFn: () => api.getTickets(queryParams),
  });

  const tickets = data?.tickets ?? [];

  // Bulk action completed: refresh cache, clear selection, refetch
  function handleActionComplete() {
    setSelectedKeys(new Set());
    api.refreshCacheIncremental().then(() => {
      queryClient.invalidateQueries({ queryKey: ["manage-tickets"] });
      queryClient.invalidateQueries({ queryKey: ["metrics"] });
      queryClient.invalidateQueries({ queryKey: ["sla-summary"] });
      queryClient.invalidateQueries({ queryKey: ["sla-breaches"] });
      queryClient.invalidateQueries({ queryKey: ["cache-status"] });
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
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Manage Tickets</h1>
        <p className="mt-1 text-sm text-gray-500">
          Select tickets and apply bulk operations.
        </p>
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
      />
    </div>
  );
}
