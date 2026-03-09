import { useState, useCallback, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
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

const PAGE_SIZE = 250;

/** Derive initial filter values from URL search params. */
function filtersFromParams(sp: URLSearchParams): TicketFilterValues {
  return {
    search: sp.get("search") ?? "",
    status: sp.get("status") ?? "",
    priority: sp.get("priority") ?? "",
    issue_type: sp.get("issue_type") ?? "",
    open_only: sp.get("open_only") !== "false",
    stale_only: sp.get("stale_only") === "true",
    created_after: sp.get("created_after") ?? "",
    created_before: sp.get("created_before") ?? "",
    assignee: sp.get("assignee") ?? "",
  };
}

export default function TicketsPage() {
  const [searchParams, setSearchParams] = useSearchParams();

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
    setFilters(next);
    setPage(1);
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
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  // Build query params from state
  const queryParams: TicketQueryParams = {
    ...(filters.search ? { search: filters.search } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.priority ? { priority: filters.priority } : {}),
    ...(filters.issue_type ? { issue_type: filters.issue_type } : {}),
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
  });

  const tickets = data?.tickets ?? [];
  const matchedCount = data?.matched_count ?? tickets.length;
  const totalCount = data?.total_count;
  const hasMore = page * PAGE_SIZE < matchedCount;
  const hasFilters = !!(filters.search || filters.status || filters.priority || filters.issue_type || filters.stale_only || filters.assignee || filters.created_after || filters.created_before);

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

  return (
    <div className="space-y-4">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Tickets</h1>
          <p className="mt-1 text-sm text-gray-500">
            Browse and search OIT helpdesk tickets. Showing open tickets by default.
          </p>
        </div>
        <div className="flex items-center gap-4">
          {!isLoading && (
            <div className="text-sm text-slate-500">
              {hasFilters && totalCount !== undefined ? (
                <span>
                  <span className="font-semibold text-slate-800">{matchedCount.toLocaleString()}</span>
                  {" "}matched of {totalCount.toLocaleString()} tickets
                </span>
              ) : (
                <span>
                  <span className="font-semibold text-slate-800">{matchedCount.toLocaleString()}</span>
                  {" "}tickets
                </span>
              )}
            </div>
          )}
          <TicketViewToggle value={view} onChange={handleViewChange} />
          <a
            href={api.exportAll()}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Export All
          </a>
        </div>
      </div>

      {/* Filters */}
      <TicketFilters filters={filters} onFilterChange={handleFilterChange} />

      {/* Error state */}
      {isError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load tickets: {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {/* Ticket list */}
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

      <Pagination page={page} hasMore={hasMore} onPageChange={setPage} />

      <TicketWorkbenchDrawer
        ticketKey={ticketKey}
        initialTicket={openTicket}
        onClose={closeLocalTicket}
      />
    </div>
  );
}
