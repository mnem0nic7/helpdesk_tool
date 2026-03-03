import { useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { TicketQueryParams } from "../lib/api.ts";
import TicketFilters, {
  emptyFilters,
} from "../components/TicketFilters.tsx";
import type { TicketFilterValues } from "../components/TicketFilters.tsx";
import TicketTable from "../components/TicketTable.tsx";
import Pagination from "../components/Pagination.tsx";

const PAGE_SIZE = 50;

export default function TicketsPage() {
  const [filters, setFilters] = useState<TicketFilterValues>({ ...emptyFilters });
  const [page, setPage] = useState(1);

  // When filters change, reset to page 1
  const handleFilterChange = useCallback((next: TicketFilterValues) => {
    setFilters(next);
    setPage(1);
  }, []);

  // Build query params from state
  const queryParams: TicketQueryParams = {
    page,
    page_size: PAGE_SIZE,
    ...(filters.search ? { search: filters.search } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.priority ? { priority: filters.priority } : {}),
    ...(filters.open_only ? { open_only: true } : {}),
    ...(filters.stale_only ? { stale_only: true } : {}),
  };

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["tickets", queryParams],
    queryFn: () => api.getTickets(queryParams),
  });

  const tickets = data?.tickets ?? [];
  const total = data?.total ?? 0;
  const totalPages = data?.total_pages ?? 1;

  return (
    <div className="space-y-4">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Tickets</h1>
        <p className="mt-1 text-sm text-gray-500">
          Browse and search all OIT helpdesk tickets.
        </p>
      </div>

      {/* Filters */}
      <TicketFilters filters={filters} onFilterChange={handleFilterChange} />

      {/* Error state */}
      {isError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load tickets: {error instanceof Error ? error.message : "Unknown error"}
        </div>
      )}

      {/* Table */}
      <TicketTable data={tickets} loading={isLoading} />

      {/* Pagination */}
      {!isLoading && tickets.length > 0 && (
        <Pagination
          page={page}
          totalPages={totalPages}
          total={total}
          onPageChange={setPage}
        />
      )}
    </div>
  );
}
