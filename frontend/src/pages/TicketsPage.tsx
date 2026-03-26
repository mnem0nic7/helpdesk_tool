import { startTransition, useState, useCallback, useEffect, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api.ts";
import type { TicketQueryParams, TicketRow } from "../lib/api.ts";
import TicketFilters from "../components/TicketFilters.tsx";
import type { TicketFilterValues } from "../components/TicketFilters.tsx";
import TicketTable from "../components/TicketTable.tsx";
import TicketKanbanBoard from "../components/TicketKanbanBoard.tsx";
import Pagination from "../components/Pagination.tsx";
import TicketWorkbenchDrawer from "../components/TicketWorkbenchDrawer.tsx";
import TicketViewToggle, { type TicketListView } from "../components/TicketViewToggle.tsx";
import { getSiteBranding } from "../lib/siteContext.ts";
import { activeTicketListQueryOptions } from "../lib/ticketQueryOptions.ts";

const PAGE_SIZE = 250;

/** Derive initial filter values from URL search params. */
function filtersFromParams(sp: URLSearchParams): TicketFilterValues {
  return {
    search: sp.get("search") ?? "",
    status: sp.get("status") ?? "",
    priority: sp.get("priority") ?? "",
    issue_type: sp.get("issue_type") ?? "",
    label: sp.get("label") ?? "",
    libra_support: (sp.get("libra_support") as TicketFilterValues["libra_support"]) ?? "all",
    open_only: sp.get("open_only") !== "false",
    stale_only: sp.get("stale_only") === "true",
    created_after: sp.get("created_after") ?? "",
    created_before: sp.get("created_before") ?? "",
    assignee: sp.get("assignee") ?? "",
  };
}

export default function TicketsPage() {
  const branding = getSiteBranding();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();

  const filterParamsKey = useMemo(() => {
    const next = new URLSearchParams(searchParams);
    next.delete("ticket");
    next.delete("view");
    return next.toString();
  }, [searchParams]);
  const ticketKey = searchParams.get("ticket");
  const view: TicketListView = searchParams.get("view") === "kanban" ? "kanban" : "table";

  const [filters, setFilters] = useState<TicketFilterValues>(() => filtersFromParams(searchParams));
  const [page, setPage] = useState(1);
  const [openTicket, setOpenTicket] = useState<TicketRow | null>(null);

  // Reset filters when navigating to /tickets with new filter params.
  useEffect(() => {
    setFilters(filtersFromParams(new URLSearchParams(filterParamsKey)));
    setPage(1);
  }, [filterParamsKey]);

  const handleFilterChange = useCallback((next: TicketFilterValues) => {
    startTransition(() => {
      setFilters(next);
      setPage(1);
    });
  }, []);

  const openLocalTicket = useCallback(
    (ticket: TicketRow) => {
      setOpenTicket(ticket);
      const next = new URLSearchParams(searchParams);
      next.set("ticket", ticket.key);
      setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );

  const closeLocalTicket = useCallback(() => {
    setOpenTicket(null);
    const next = new URLSearchParams(searchParams);
    next.delete("ticket");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const buildTicketHref = useCallback(
    (key: string) => {
      const next = new URLSearchParams(searchParams);
      next.set("ticket", key);
      const query = next.toString();
      return query ? `/tickets?${query}` : "/tickets";
    },
    [searchParams],
  );

  const handleViewChange = useCallback(
    (nextView: TicketListView) => {
      const next = new URLSearchParams(searchParams);
      if (nextView === "kanban") {
        next.set("view", "kanban");
      } else {
        next.delete("view");
      }
      startTransition(() => {
        setSearchParams(next, { replace: true });
      });
    },
    [searchParams, setSearchParams],
  );

  // Build query params from state
  const queryParams: TicketQueryParams = {
    ...(filters.search ? { search: filters.search } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.priority ? { priority: filters.priority } : {}),
    ...(filters.issue_type ? { issue_type: filters.issue_type } : {}),
    ...(filters.label ? { label: filters.label } : {}),
    ...(filters.libra_support !== "all" ? { libra_support: filters.libra_support } : {}),
    ...(filters.open_only ? { open_only: true } : {}),
    ...(filters.stale_only ? { stale_only: true } : {}),
    ...(filters.created_after ? { created_after: filters.created_after } : {}),
    ...(filters.created_before ? { created_before: filters.created_before } : {}),
    ...(filters.assignee ? { assignee: filters.assignee } : {}),
    offset: (page - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
  };

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["tickets", queryParams],
    queryFn: () => api.getTickets(queryParams),
    ...activeTicketListQueryOptions,
  });

  const tickets = data?.tickets ?? [];
  const matchedCount = data?.matched_count ?? tickets.length;
  const totalCount = data?.total_count;
  const hasMore = page * PAGE_SIZE < matchedCount;
  const hasFilters = !!(
    filters.search ||
    filters.status ||
    filters.priority ||
    filters.issue_type ||
    filters.label ||
    filters.libra_support !== "all" ||
    filters.stale_only ||
    filters.assignee ||
    filters.created_after ||
    filters.created_before
  );

  const refreshVisibleMutation = useMutation({
    mutationFn: (keys: string[]) => api.refreshVisibleTickets(keys),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["ticket-detail"] });
      queryClient.invalidateQueries({ queryKey: ["filter-options"] });
      queryClient.invalidateQueries({ queryKey: ["metrics"] });
      queryClient.invalidateQueries({ queryKey: ["sla-summary"] });
      queryClient.invalidateQueries({ queryKey: ["sla-breaches"] });
      queryClient.invalidateQueries({ queryKey: ["cache-status"] });
    },
  });

  useEffect(() => {
    if (!ticketKey) {
      setOpenTicket(null);
      return;
    }
    const matchingTicket = tickets.find((ticket) => ticket.key === ticketKey);
    if (matchingTicket) {
      setOpenTicket(matchingTicket);
      return;
    }
    setOpenTicket((current) => (current?.key === ticketKey ? current : null));
  }, [ticketKey, tickets]);

  const handleRefreshVisible = useCallback(() => {
    if (!tickets.length) return;
    refreshVisibleMutation.mutate(tickets.map((ticket) => ticket.key));
  }, [refreshVisibleMutation, tickets]);

  const isRefreshingVisible = refreshVisibleMutation.isPending;
  const headerCountContent = isLoading ? (
    <span className="inline-flex items-center gap-2 text-slate-400">
      <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-slate-200" />
      Loading ticket count...
    </span>
  ) : hasFilters && totalCount !== undefined ? (
    <span>
      <span className="font-semibold text-slate-800">{matchedCount.toLocaleString()}</span>
      {" "}matched of {totalCount.toLocaleString()} tickets
    </span>
  ) : (
    <span>
      <span className="font-semibold text-slate-800">{matchedCount.toLocaleString()}</span>
      {" "}tickets
    </span>
  );
  const feedbackMessage = isError
    ? `Failed to load tickets: ${error instanceof Error ? error.message : "Unknown error"}`
    : refreshVisibleMutation.isError
      ? `Failed to refresh displayed tickets: ${refreshVisibleMutation.error instanceof Error ? refreshVisibleMutation.error.message : "Unknown error"}`
      : "";

  return (
    <div className="space-y-4">
      {/* Page header */}
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Tickets</h1>
          <p className="mt-1 text-sm text-gray-500">
            Browse and search {branding.appName} tickets. Showing open tickets by default.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 xl:max-w-[52rem]">
          <div className="flex min-h-9 min-w-[15rem] items-center justify-end text-right text-sm text-slate-500">
            {headerCountContent}
          </div>
          <button
            type="button"
            onClick={handleRefreshVisible}
            disabled={isRefreshingVisible || isLoading || tickets.length === 0}
            className="inline-flex min-w-[10.75rem] items-center justify-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            title="Re-fetch the tickets currently shown on this page from Jira"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className={`${isRefreshingVisible ? "animate-spin" : ""} h-4 w-4`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m14.836 2A8.001 8.001 0 005.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-14.837-2m14.837 2H15" />
            </svg>
            {isRefreshingVisible ? "Refreshing..." : "Refresh Visible"}
          </button>
          <TicketViewToggle value={view} onChange={handleViewChange} />
          <a
            href={api.exportAll()}
            className="inline-flex min-w-[8.5rem] items-center justify-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Export All
          </a>
        </div>
      </div>

      {/* Filters */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <TicketFilters filters={filters} onFilterChange={handleFilterChange} />
      </div>

      <div className="min-h-[3.25rem]">
        {feedbackMessage && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {feedbackMessage}
          </div>
        )}
      </div>

      {/* Ticket list */}
      <div className="min-h-[24rem]">
        {view === "kanban" ? (
          <TicketKanbanBoard
            data={tickets}
            loading={isLoading}
            onRowOpen={openLocalTicket}
            ticketHrefBuilder={buildTicketHref}
          />
        ) : (
          <TicketTable
            data={tickets}
            loading={isLoading}
            onRowOpen={openLocalTicket}
            ticketHrefBuilder={buildTicketHref}
          />
        )}
      </div>

      <div className="min-h-10">
        <Pagination page={page} hasMore={hasMore} onPageChange={setPage} />
      </div>

      <TicketWorkbenchDrawer
        ticketKey={ticketKey}
        initialTicket={openTicket}
        onClose={closeLocalTicket}
      />
    </div>
  );
}
