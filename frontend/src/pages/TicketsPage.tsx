import { startTransition, useState, useCallback, useEffect, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api.ts";
import type { PriorityOption, RequestTypeOption, TicketCreatePayload, TicketQueryParams, TicketRow } from "../lib/api.ts";
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
const EMPTY_CREATE_FORM: TicketCreatePayload = {
  summary: "",
  description: "",
  priority: "",
  request_type_id: "",
};

interface CreateTicketModalProps {
  isOpen: boolean;
  form: TicketCreatePayload;
  priorities: PriorityOption[];
  requestTypes: RequestTypeOption[];
  isLoadingOptions: boolean;
  isSubmitting: boolean;
  errorText: string;
  onChange: (field: keyof TicketCreatePayload, value: string) => void;
  onClose: () => void;
  onSubmit: () => void;
}

function CreateTicketModal({
  isOpen,
  form,
  priorities,
  requestTypes,
  isLoadingOptions,
  isSubmitting,
  errorText,
  onChange,
  onClose,
  onSubmit,
}: CreateTicketModalProps) {
  if (!isOpen) return null;

  const isSubmitDisabled =
    isSubmitting ||
    isLoadingOptions ||
    !form.summary.trim() ||
    !form.priority.trim() ||
    !form.request_type_id.trim();

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/45 p-5" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-ticket-title"
        className="w-full max-w-3xl rounded-2xl bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="border-b border-slate-200 px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id="create-ticket-title" className="text-xl font-semibold text-slate-900">
                Create Ticket
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Create a new OIT service request without leaving it-app.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Close
            </button>
          </div>
        </div>

        <div className="space-y-5 px-6 py-5">
          {errorText && (
            <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {errorText}
            </div>
          )}

          <div className="space-y-2">
            <label htmlFor="create-ticket-summary" className="text-sm font-medium text-slate-700">
              Summary
            </label>
            <input
              id="create-ticket-summary"
              type="text"
              value={form.summary}
              onChange={(event) => onChange("summary", event.target.value)}
              placeholder="Brief description of the request"
              className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              disabled={isSubmitting}
              autoFocus
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label htmlFor="create-ticket-priority" className="text-sm font-medium text-slate-700">
                Priority
              </label>
              <select
                id="create-ticket-priority"
                value={form.priority}
                onChange={(event) => onChange("priority", event.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                disabled={isSubmitting || isLoadingOptions}
              >
                <option value="">{isLoadingOptions ? "Loading priorities..." : "Select priority"}</option>
                {priorities.map((priority) => (
                  <option key={priority.id || priority.name} value={priority.name}>
                    {priority.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <label htmlFor="create-ticket-request-type" className="text-sm font-medium text-slate-700">
                Request Type
              </label>
              <select
                id="create-ticket-request-type"
                value={form.request_type_id}
                onChange={(event) => onChange("request_type_id", event.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                disabled={isSubmitting || isLoadingOptions}
              >
                <option value="">{isLoadingOptions ? "Loading request types..." : "Select request type"}</option>
                {requestTypes.map((requestType) => (
                  <option key={requestType.id} value={requestType.id}>
                    {requestType.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-2">
            <label htmlFor="create-ticket-description" className="text-sm font-medium text-slate-700">
              Description
            </label>
            <textarea
              id="create-ticket-description"
              value={form.description}
              onChange={(event) => onChange("description", event.target.value)}
              placeholder="Add any helpful background, symptoms, or requested action."
              rows={8}
              className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              disabled={isSubmitting}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-slate-200 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={isSubmitDisabled}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
          >
            {isSubmitting ? "Creating..." : "Create Ticket"}
          </button>
        </div>
      </div>
    </div>
  );
}

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
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [createForm, setCreateForm] = useState<TicketCreatePayload>(EMPTY_CREATE_FORM);

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
  const { data: me } = useQuery({
    queryKey: ["me", "tickets-create"],
    queryFn: () => api.getMe(),
    staleTime: 60_000,
    enabled: branding.scope === "primary",
  });
  const canCreateTicket = branding.scope === "primary" && !!me?.is_admin;
  const { data: priorities = [], isLoading: isLoadingPriorities } = useQuery({
    queryKey: ["priorities", "tickets-create"],
    queryFn: () => api.getPriorities(),
    staleTime: 5 * 60 * 1000,
    enabled: canCreateTicket && isCreateModalOpen,
  });
  const { data: requestTypes = [], isLoading: isLoadingRequestTypes } = useQuery({
    queryKey: ["request-types", "tickets-create"],
    queryFn: () => api.getRequestTypes(),
    staleTime: 5 * 60 * 1000,
    enabled: canCreateTicket && isCreateModalOpen,
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
  const createTicketMutation = useMutation({
    mutationFn: (payload: TicketCreatePayload) => api.createTicket(payload),
    onSuccess: (response) => {
      queryClient.setQueryData(["ticket-detail", response.created_key], response.detail);
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["ticket-detail"] });
      queryClient.invalidateQueries({ queryKey: ["filter-options"] });
      setCreateForm(EMPTY_CREATE_FORM);
      setIsCreateModalOpen(false);
      setOpenTicket(response.detail.ticket);
      const next = new URLSearchParams(searchParams);
      next.set("ticket", response.created_key);
      setSearchParams(next);
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

  const handleCreateFieldChange = useCallback((field: keyof TicketCreatePayload, value: string) => {
    setCreateForm((current) => ({ ...current, [field]: value }));
  }, []);

  const handleCreateModalClose = useCallback(() => {
    if (createTicketMutation.isPending) return;
    setIsCreateModalOpen(false);
    setCreateForm(EMPTY_CREATE_FORM);
    createTicketMutation.reset();
  }, [createTicketMutation]);

  const handleCreateTicket = useCallback(() => {
    createTicketMutation.mutate({
      summary: createForm.summary.trim(),
      description: createForm.description,
      priority: createForm.priority.trim(),
      request_type_id: createForm.request_type_id.trim(),
    });
  }, [createForm, createTicketMutation]);

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
          {canCreateTicket && (
            <button
              type="button"
              onClick={() => {
                createTicketMutation.reset();
                setIsCreateModalOpen(true);
              }}
              className="inline-flex min-w-[9rem] items-center justify-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              Create Ticket
            </button>
          )}
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
      <CreateTicketModal
        isOpen={isCreateModalOpen}
        form={createForm}
        priorities={priorities}
        requestTypes={requestTypes}
        isLoadingOptions={isLoadingPriorities || isLoadingRequestTypes}
        isSubmitting={createTicketMutation.isPending}
        errorText={createTicketMutation.error instanceof Error ? createTicketMutation.error.message : ""}
        onChange={handleCreateFieldChange}
        onClose={handleCreateModalClose}
        onSubmit={handleCreateTicket}
      />
    </div>
  );
}
