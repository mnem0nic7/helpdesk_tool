import { useEffect, useMemo, useState, type DragEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import api from "../lib/api.ts";
import type { TicketRow } from "../lib/api.ts";
import {
  formatAge,
  formatTTR,
  getTicketBoardColumn,
  getTicketBoardColumnForStatus,
  priorityClass,
  priorityRank,
  slaBadgeClass,
  statusBadgeClass,
  TICKET_BOARD_COLUMNS,
  truncate,
  type TicketBoardColumnId,
} from "./ticketListUtils.ts";

interface TicketKanbanBoardProps {
  data: TicketRow[];
  loading: boolean;
  selectable?: boolean;
  onSelectionChange?: (selected: Set<string>) => void;
  selectedKeys?: Set<string>;
  onRowOpen?: (ticket: TicketRow) => void;
  ticketHrefBuilder?: (key: string) => string;
}

function priorityAccentClass(priority: string): string {
  switch (priority.toLowerCase()) {
    case "highest":
      return "border-l-red-600";
    case "high":
      return "border-l-red-400";
    case "medium":
      return "border-l-amber-400";
    case "low":
    case "lowest":
      return "border-l-slate-300";
    default:
      return "border-l-slate-300";
  }
}

function sortTicketsForBoard(a: TicketRow, b: TicketRow): number {
  const priorityDiff = priorityRank(a.priority) - priorityRank(b.priority);
  if (priorityDiff !== 0) return priorityDiff;

  const ageA = a.age_days ?? -1;
  const ageB = b.age_days ?? -1;
  if (ageA !== ageB) return ageB - ageA;

  return a.key.localeCompare(b.key);
}

export default function TicketKanbanBoard({
  data,
  loading,
  selectable = false,
  onSelectionChange,
  selectedKeys = new Set(),
  onRowOpen,
  ticketHrefBuilder,
}: TicketKanbanBoardProps) {
  const queryClient = useQueryClient();
  const { data: cacheStatus } = useQuery({
    queryKey: ["cache-status"],
    queryFn: () => api.getCacheStatus(),
    staleTime: Infinity,
    enabled: !ticketHrefBuilder,
  });
  const jiraBaseUrl = cacheStatus?.jira_base_url;
  const [draggedTicketKey, setDraggedTicketKey] = useState<string | null>(null);
  const [dragOverColumn, setDragOverColumn] = useState<TicketBoardColumnId | null>(null);
  const [suppressOpenKey, setSuppressOpenKey] = useState<string | null>(null);
  const [ticketOverrides, setTicketOverrides] = useState<
    Record<string, Pick<TicketRow, "status" | "status_category">>
  >({});
  const [moveFeedback, setMoveFeedback] = useState<string | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);

  useEffect(() => {
    setTicketOverrides({});
  }, [data]);

  const displayData = useMemo(
    () =>
      data.map((ticket) =>
        ticketOverrides[ticket.key] ? { ...ticket, ...ticketOverrides[ticket.key] } : ticket,
      ),
    [data, ticketOverrides],
  );

  const moveMutation = useMutation({
    mutationFn: async ({
      ticket,
      destination,
      destinationLabel,
    }: {
      ticket: TicketRow;
      destination: TicketBoardColumnId;
      destinationLabel: string;
    }) => {
      const transitions = await api.getTransitions(ticket.key);
      const matchingTransition = transitions.find(
        (transition) => getTicketBoardColumnForStatus(transition.to_status) === destination,
      );
      if (!matchingTransition) {
        throw new Error(`No available transition to ${destinationLabel}.`);
      }
      const detail = await api.transitionTicket(ticket.key, matchingTransition.id);
      return { detail, destinationLabel };
    },
    onSuccess: ({ detail, destinationLabel }) => {
      setTicketOverrides((current) => ({
        ...current,
        [detail.ticket.key]: {
          status: detail.ticket.status,
          status_category: detail.ticket.status_category,
        },
      }));
      queryClient.setQueryData(["ticket-detail", detail.ticket.key], detail);
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["manage-tickets"] });
      queryClient.invalidateQueries({ queryKey: ["filter-options"] });
      queryClient.invalidateQueries({ queryKey: ["metrics"] });
      queryClient.invalidateQueries({ queryKey: ["sla-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["ticket-transitions", detail.ticket.key] });
      setMoveFeedback(`Moved ${detail.ticket.key} to ${destinationLabel}.`);
      setMoveError(null);
    },
    onError: (error) => {
      setMoveFeedback(null);
      setMoveError(error instanceof Error ? error.message : "Failed to move ticket.");
    },
  });

  const groupedTickets = useMemo(() => {
    const initial: Record<TicketBoardColumnId, TicketRow[]> = {
      todo: [],
      in_progress: [],
      waiting: [],
      done: [],
    };

    for (const ticket of displayData) {
      initial[getTicketBoardColumn(ticket)].push(ticket);
    }

    for (const column of TICKET_BOARD_COLUMNS) {
      initial[column.id].sort(sortTicketsForBoard);
    }

    return initial;
  }, [displayData]);

  function handleToggle(key: string) {
    if (!onSelectionChange) return;
    const next = new Set(selectedKeys);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onSelectionChange(next);
  }

  function handleDragStart(ticket: TicketRow, event: DragEvent<HTMLDivElement>) {
    setDraggedTicketKey(ticket.key);
    setSuppressOpenKey(ticket.key);
    setMoveFeedback(null);
    setMoveError(null);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", ticket.key);
  }

  function handleDragEnd() {
    setDraggedTicketKey(null);
    setDragOverColumn(null);
    window.setTimeout(() => {
      setSuppressOpenKey(null);
    }, 0);
  }

  function handleDrop(destination: TicketBoardColumnId) {
    const key = draggedTicketKey;
    setDraggedTicketKey(null);
    setDragOverColumn(null);
    if (!key || moveMutation.isPending) return;
    const ticket = displayData.find((entry) => entry.key === key);
    if (!ticket) return;
    if (getTicketBoardColumn(ticket) === destination) return;
    const destinationLabel =
      TICKET_BOARD_COLUMNS.find((column) => column.id === destination)?.label ?? "the selected column";
    moveMutation.mutate({ ticket, destination, destinationLabel });
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
        <span className="ml-3 text-sm text-gray-500">Loading tickets...</span>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="py-16 text-center text-gray-400">
        No tickets match the current filters.
      </div>
    );
  }

  return (
    <div className="space-y-3 overflow-x-auto pb-2">
      {(moveFeedback || moveError || moveMutation.isPending) && (
        <div
          className={[
            "rounded-xl border px-4 py-2 text-sm",
            moveError
              ? "border-red-200 bg-red-50 text-red-700"
              : "border-blue-200 bg-blue-50 text-blue-700",
          ].join(" ")}
        >
          {moveError ?? moveFeedback ?? "Updating ticket status..."}
        </div>
      )}

      <p className="text-xs text-slate-500">
        Drag a card into a new column to transition the ticket status.
      </p>

      <div className="grid min-w-[72rem] grid-cols-4 gap-4">
        {TICKET_BOARD_COLUMNS.map((column) => {
          const tickets = groupedTickets[column.id];
          return (
            <section
              key={column.id}
              onDragOver={(event) => {
                if (!draggedTicketKey) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
                setDragOverColumn(column.id);
              }}
              onDrop={(event) => {
                event.preventDefault();
                handleDrop(column.id);
              }}
              className={[
                "flex min-h-[32rem] flex-col rounded-2xl border shadow-sm transition-colors",
                column.tone,
                dragOverColumn === column.id ? "ring-2 ring-blue-300 ring-offset-2" : "",
              ].join(" ")}
            >
              <header className="flex items-center justify-between border-b border-black/5 px-4 py-3">
                <div>
                  <h2 className="text-sm font-semibold text-slate-900">{column.label}</h2>
                  <p className="text-xs text-slate-500">
                    {tickets.length} ticket{tickets.length === 1 ? "" : "s"}
                  </p>
                </div>
                <span className="rounded-full bg-white/90 px-2.5 py-1 text-xs font-semibold text-slate-700 shadow-sm">
                  {tickets.length}
                </span>
              </header>

              <div className="flex-1 space-y-3 overflow-y-auto p-3">
                {tickets.length === 0 && (
                  <div className="rounded-xl border border-dashed border-slate-200 bg-white/70 px-4 py-6 text-center text-sm text-slate-400">
                    No tickets in this column.
                  </div>
                )}

                {tickets.map((ticket) => {
                  const isSelected = selectedKeys.has(ticket.key);
                  const localHref = ticketHrefBuilder?.(ticket.key);
                  const externalHref = jiraBaseUrl ? `${jiraBaseUrl}/browse/${ticket.key}` : null;
                  const isDragged = draggedTicketKey === ticket.key;
                  const isMoving =
                    moveMutation.isPending && moveMutation.variables?.ticket.key === ticket.key;
                  return (
                    <div
                      key={ticket.key}
                      role={onRowOpen ? "button" : undefined}
                      tabIndex={onRowOpen ? 0 : undefined}
                      draggable={!moveMutation.isPending}
                      onDragStart={(event) => handleDragStart(ticket, event)}
                      onDragEnd={handleDragEnd}
                      onClick={() => {
                        if (suppressOpenKey === ticket.key) return;
                        onRowOpen?.(ticket);
                      }}
                      onKeyDown={(event) => {
                        if (!onRowOpen) return;
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onRowOpen(ticket);
                        }
                      }}
                      className={[
                        "rounded-2xl border border-slate-200 bg-white p-3 text-left shadow-sm transition",
                        "border-l-4 hover:-translate-y-0.5 hover:shadow-md",
                        priorityAccentClass(ticket.priority),
                        onRowOpen ? "cursor-pointer" : "",
                        isSelected ? "ring-2 ring-blue-300" : "",
                        isDragged ? "opacity-50" : "",
                        isMoving ? "opacity-60" : "",
                      ].join(" ")}
                    >
                      <div className="flex items-start gap-2">
                        {selectable && (
                          <input
                            type="checkbox"
                            aria-label={`Select ${ticket.key}`}
                            checked={isSelected}
                            onChange={() => handleToggle(ticket.key)}
                            onClick={(event) => event.stopPropagation()}
                            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600"
                          />
                        )}

                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-2">
                            {localHref ? (
                              <Link
                                to={localHref}
                                onClick={(event) => event.stopPropagation()}
                                className="font-mono text-xs text-blue-700 underline hover:text-blue-900"
                              >
                                {ticket.key}
                              </Link>
                            ) : externalHref ? (
                              <a
                                href={externalHref}
                                target="_blank"
                                rel="noopener noreferrer"
                                onClick={(event) => event.stopPropagation()}
                                className="font-mono text-xs text-blue-700 underline hover:text-blue-900"
                              >
                                {ticket.key}
                              </a>
                            ) : (
                              <span className="font-mono text-xs text-blue-700">{ticket.key}</span>
                            )}

                            <span className={`text-xs ${priorityClass(ticket.priority)}`}>
                              {ticket.priority}
                            </span>
                          </div>

                          <p className="mt-2 text-sm font-medium leading-5 text-slate-900">
                            {truncate(ticket.summary, 110)}
                          </p>

                          <div className="mt-3 flex flex-wrap gap-2">
                            <span
                              className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${statusBadgeClass(ticket.status)}`}
                            >
                              {ticket.status}
                            </span>
                            {ticket.request_type && (
                              <span className="inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                                {ticket.request_type}
                              </span>
                            )}
                            {ticket.sla_resolution_status && (
                              <span
                                className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${slaBadgeClass(ticket.sla_resolution_status)}`}
                              >
                                SLA {ticket.sla_resolution_status}
                              </span>
                            )}
                          </div>

                          <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-2 text-xs text-slate-500">
                            <div>
                              <dt className="font-medium uppercase tracking-wide text-slate-400">Assignee</dt>
                              <dd className="mt-0.5 truncate text-slate-700">
                                {ticket.assignee || "\u2014"}
                              </dd>
                            </div>
                            <div>
                              <dt className="font-medium uppercase tracking-wide text-slate-400">Age</dt>
                              <dd className="mt-0.5 text-slate-700">{formatAge(ticket.age_days)}</dd>
                            </div>
                            <div>
                              <dt className="font-medium uppercase tracking-wide text-slate-400">Type</dt>
                              <dd className="mt-0.5 truncate text-slate-700">{ticket.issue_type}</dd>
                            </div>
                            <div>
                              <dt className="font-medium uppercase tracking-wide text-slate-400">TTR</dt>
                              <dd className="mt-0.5 text-slate-700">
                                {formatTTR(ticket.calendar_ttr_hours)}
                              </dd>
                            </div>
                          </dl>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
