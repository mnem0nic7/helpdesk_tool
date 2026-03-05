import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import type { SortingState } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import api from "../lib/api.ts";
import type { TicketRow } from "../lib/api.ts";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatTTR(hours: number | null): string {
  if (hours == null) return "\u2014";
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours <= 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

function formatAge(days: number | null): string {
  if (days == null) return "\u2014";
  return `${days.toFixed(1)}d`;
}

function formatDate(iso: string): string {
  if (!iso) return "\u2014";
  return iso.slice(0, 10);
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + "\u2026";
}

// ---------------------------------------------------------------------------
// Status / Priority / SLA badge helpers
// ---------------------------------------------------------------------------

function statusBadgeClass(status: string): string {
  const s = status.toLowerCase();
  if (s === "done" || s === "resolved" || s === "closed")
    return "bg-green-100 text-green-800";
  if (s === "in progress" || s === "acknowledged")
    return "bg-blue-100 text-blue-800";
  if (s.startsWith("waiting"))
    return "bg-yellow-100 text-yellow-800";
  return "bg-gray-100 text-gray-700";
}

function priorityClass(priority: string): string {
  const p = priority.toLowerCase();
  if (p === "highest" || p === "high") return "text-red-600 font-semibold";
  if (p === "medium") return "text-yellow-600 font-medium";
  return "text-gray-500";
}

function slaBadgeClass(sla: string): string {
  const s = sla.toLowerCase();
  if (s === "breached") return "bg-red-100 text-red-800";
  if (s === "met") return "bg-green-100 text-green-800";
  if (s === "running" || s === "ongoing") return "bg-blue-100 text-blue-800";
  if (s === "paused") return "bg-yellow-100 text-yellow-800";
  return "bg-gray-100 text-gray-600";
}

// ---------------------------------------------------------------------------
// Column definitions
// ---------------------------------------------------------------------------

const colHelper = createColumnHelper<TicketRow>();

function buildColumns(
  selectable: boolean,
  selectedKeys: Set<string>,
  onToggle: (key: string) => void,
  onToggleAll: (allKeys: string[]) => void,
  allKeys: string[],
  jiraBaseUrl?: string,
) {
  const cols = [];

  if (selectable) {
    cols.push(
      colHelper.display({
        id: "select",
        header: () => (
          <input
            type="checkbox"
            checked={allKeys.length > 0 && allKeys.every((k) => selectedKeys.has(k))}
            onChange={() => onToggleAll(allKeys)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600"
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            checked={selectedKeys.has(row.original.key)}
            onChange={() => onToggle(row.original.key)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600"
          />
        ),
        size: 40,
      }),
    );
  }

  cols.push(
    colHelper.accessor("key", {
      header: "Key",
      cell: (info) => {
        const key = info.getValue();
        if (jiraBaseUrl) {
          return (
            <a
              href={`${jiraBaseUrl}/browse/${key}`}
              target="_blank"
              rel="noopener noreferrer"
              className="whitespace-nowrap font-mono text-xs text-blue-700 underline hover:text-blue-900"
            >
              {key}
            </a>
          );
        }
        return (
          <span className="whitespace-nowrap font-mono text-xs text-blue-700">
            {key}
          </span>
        );
      },
      size: 100,
    }),
    colHelper.accessor("summary", {
      header: "Summary",
      cell: (info) => {
        const full = info.getValue();
        return (
          <span title={full} className="text-gray-900">
            {truncate(full, 60)}
          </span>
        );
      },
      size: 320,
    }),
    colHelper.accessor("issue_type", {
      header: "Type",
      cell: (info) => <span className="text-gray-600">{info.getValue()}</span>,
      size: 100,
    }),
    colHelper.accessor("request_type", {
      header: "Request Type",
      cell: (info) => <span className="text-gray-600">{info.getValue() || "—"}</span>,
      size: 160,
    }),
    colHelper.accessor("status", {
      header: "Status",
      cell: (info) => {
        const val = info.getValue();
        return (
          <span
            className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${statusBadgeClass(val)}`}
          >
            {val}
          </span>
        );
      },
      size: 130,
    }),
    colHelper.accessor("priority", {
      header: "Priority",
      cell: (info) => {
        const val = info.getValue();
        return <span className={`text-sm ${priorityClass(val)}`}>{val}</span>;
      },
      size: 90,
    }),
    colHelper.accessor("assignee", {
      header: "Assignee",
      cell: (info) => {
        const val = info.getValue();
        return (
          <span className="text-gray-700">{val || "\u2014"}</span>
        );
      },
      size: 140,
    }),
    colHelper.accessor("created", {
      header: "Created",
      cell: (info) => (
        <span className="whitespace-nowrap text-gray-500 text-xs">
          {formatDate(info.getValue())}
        </span>
      ),
      size: 100,
    }),
    colHelper.accessor("calendar_ttr_hours", {
      header: "TTR",
      cell: (info) => (
        <span className="whitespace-nowrap text-gray-600 text-xs">
          {formatTTR(info.getValue())}
        </span>
      ),
      size: 70,
    }),
    colHelper.accessor("age_days", {
      header: "Age",
      cell: (info) => (
        <span className="whitespace-nowrap text-gray-600 text-xs">
          {formatAge(info.getValue())}
        </span>
      ),
      size: 70,
    }),
    colHelper.accessor("sla_resolution_status", {
      header: "SLA",
      cell: (info) => {
        const val = info.getValue();
        if (!val) return <span className="text-gray-400">{"\u2014"}</span>;
        return (
          <span
            className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${slaBadgeClass(val)}`}
          >
            {val}
          </span>
        );
      },
      size: 90,
    }),
  );

  return cols;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface TicketTableProps {
  data: TicketRow[];
  loading: boolean;
  selectable?: boolean;
  onSelectionChange?: (selected: Set<string>) => void;
  selectedKeys?: Set<string>;
}

export default function TicketTable({
  data,
  loading,
  selectable = false,
  onSelectionChange,
  selectedKeys = new Set(),
}: TicketTableProps) {
  const { data: cacheStatus } = useQuery({
    queryKey: ["cache-status"],
    queryFn: () => api.getCacheStatus(),
    staleTime: Infinity,
  });
  const jiraBaseUrl = cacheStatus?.jira_base_url;

  const allKeys = useMemo(() => data.map((r) => r.key), [data]);

  function handleToggle(key: string) {
    if (!onSelectionChange) return;
    const next = new Set(selectedKeys);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onSelectionChange(next);
  }

  function handleToggleAll(keys: string[]) {
    if (!onSelectionChange) return;
    const allSelected = keys.every((k) => selectedKeys.has(k));
    if (allSelected) {
      onSelectionChange(new Set());
    } else {
      onSelectionChange(new Set(keys));
    }
  }

  const [sorting, setSorting] = useState<SortingState>([]);

  const columns = useMemo(
    () => buildColumns(selectable, selectedKeys, handleToggle, handleToggleAll, allKeys, jiraBaseUrl),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectable, selectedKeys, allKeys, jiraBaseUrl],
  );

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

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
    <div className="overflow-x-auto rounded-lg border border-gray-200 shadow-sm">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((header) => {
                const canSort = header.column.getCanSort();
                const sorted = header.column.getIsSorted();
                return (
                  <th
                    key={header.id}
                    className={[
                      "whitespace-nowrap px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-gray-500",
                      canSort ? "cursor-pointer select-none hover:text-gray-700" : "",
                    ].join(" ")}
                    style={{ width: header.getSize() }}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {header.isPlaceholder ? null : (
                      <span className="inline-flex items-center gap-1">
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {canSort && (
                          <span className="text-gray-400">
                            {sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : "⇅"}
                          </span>
                        )}
                      </span>
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {table.getRowModel().rows.map((row, idx) => (
            <tr
              key={row.id}
              className={[
                "transition-colors hover:bg-blue-50",
                idx % 2 === 1 ? "bg-gray-50/50" : "",
              ].join(" ")}
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-3 py-2">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
