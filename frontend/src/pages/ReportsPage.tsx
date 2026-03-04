import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { ReportConfig, ReportPreviewResponse } from "../lib/api.ts";
import TicketFilters, {
  emptyFilters,
} from "../components/TicketFilters.tsx";
import type { TicketFilterValues } from "../components/TicketFilters.tsx";

// ---------------------------------------------------------------------------
// Field metadata — all 21 TicketRow fields
// ---------------------------------------------------------------------------

const FIELD_META: Record<string, { label: string; description: string }> = {
  key: { label: "Key", description: "Jira issue key" },
  summary: { label: "Summary", description: "Issue title" },
  issue_type: { label: "Type", description: "Issue type" },
  status: { label: "Status", description: "Current status" },
  status_category: { label: "Status Category", description: "Status category" },
  priority: { label: "Priority", description: "Priority level" },
  resolution: { label: "Resolution", description: "Resolution type" },
  assignee: { label: "Assignee", description: "Assigned team member" },
  assignee_account_id: { label: "Assignee ID", description: "Atlassian account ID" },
  reporter: { label: "Reporter", description: "Ticket creator" },
  created: { label: "Created", description: "Creation date" },
  updated: { label: "Updated", description: "Last update date" },
  resolved: { label: "Resolved", description: "Resolution date" },
  request_type: { label: "Request Type", description: "JSM request type" },
  calendar_ttr_hours: { label: "TTR (h)", description: "Time-to-resolution in hours" },
  age_days: { label: "Age (d)", description: "Age of open tickets in days" },
  days_since_update: { label: "Days Since Update", description: "Days since last update" },
  excluded: { label: "Excluded", description: "Excluded from metrics" },
  sla_first_response_status: { label: "SLA Response", description: "First-response SLA status" },
  sla_resolution_status: { label: "SLA Resolution", description: "Resolution SLA status" },
  labels: { label: "Labels", description: "Issue labels" },
};

const ALL_FIELDS = Object.keys(FIELD_META);

const DEFAULT_COLUMNS = [
  "key", "summary", "issue_type", "status", "priority",
  "assignee", "created", "resolved", "calendar_ttr_hours",
];

// Sortable fields (exclude array fields)
const SORTABLE_FIELDS = ALL_FIELDS.filter((f) => f !== "labels");

// Groupable fields
const GROUPABLE_FIELDS = [
  "status", "status_category", "priority", "assignee", "reporter",
  "issue_type", "resolution", "request_type", "excluded",
  "sla_first_response_status", "sla_resolution_status",
];

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

interface Preset {
  name: string;
  filters: Partial<TicketFilterValues>;
  columns: string[];
  sort_field: string;
  sort_dir: "asc" | "desc";
  group_by: string | null;
  include_excluded: boolean;
}

const PRESETS: Preset[] = [
  {
    name: "Open by Priority",
    filters: { open_only: true },
    columns: ["key", "summary", "priority", "status", "assignee", "age_days", "days_since_update"],
    sort_field: "priority",
    sort_dir: "asc",
    group_by: "priority",
    include_excluded: false,
  },
  {
    name: "Resolution by Assignee",
    filters: {},
    columns: ["key", "summary", "assignee", "status", "resolved", "calendar_ttr_hours"],
    sort_field: "resolved",
    sort_dir: "desc",
    group_by: "assignee",
    include_excluded: false,
  },
  {
    name: "Last 30 Days",
    filters: {
      created_after: new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10),
    },
    columns: ["key", "summary", "issue_type", "status", "priority", "assignee", "created", "resolved", "calendar_ttr_hours"],
    sort_field: "created",
    sort_dir: "desc",
    group_by: null,
    include_excluded: false,
  },
  {
    name: "SLA Breaches",
    filters: {},
    columns: ["key", "summary", "status", "priority", "assignee", "sla_first_response_status", "sla_resolution_status", "created"],
    sort_field: "created",
    sort_dir: "desc",
    group_by: null,
    include_excluded: false,
  },
  {
    name: "Stale Open Tickets",
    filters: { open_only: true, stale_only: true },
    columns: ["key", "summary", "status", "priority", "assignee", "age_days", "days_since_update", "updated"],
    sort_field: "days_since_update",
    sort_dir: "desc",
    group_by: null,
    include_excluded: false,
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function filtersToReport(f: TicketFilterValues): ReportConfig["filters"] {
  return {
    status: f.status || undefined,
    priority: f.priority || undefined,
    assignee: f.assignee || undefined,
    issue_type: f.issue_type || undefined,
    search: f.search || undefined,
    open_only: f.open_only || undefined,
    stale_only: f.stale_only || undefined,
    created_after: f.created_after || undefined,
    created_before: f.created_before || undefined,
  };
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return String(Math.round(value * 10) / 10);
  if (Array.isArray(value)) return value.join(", ") || "—";
  return String(value);
}

// ---------------------------------------------------------------------------
// Icons (inline SVG)
// ---------------------------------------------------------------------------

function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ReportsPage() {
  // Config state
  const [filters, setFilters] = useState<TicketFilterValues>({ ...emptyFilters });
  const [columns, setColumns] = useState<string[]>([...DEFAULT_COLUMNS]);
  const [sortField, setSortField] = useState("created");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [groupBy, setGroupBy] = useState<string | null>(null);
  const [includeExcluded, setIncludeExcluded] = useState(false);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  // Build config object for API
  const config: ReportConfig = useMemo(() => ({
    filters: filtersToReport(filters),
    columns,
    sort_field: sortField,
    sort_dir: sortDir,
    group_by: groupBy,
    include_excluded: includeExcluded,
  }), [filters, columns, sortField, sortDir, groupBy, includeExcluded]);

  // Debounced config for preview queries
  const [debouncedConfig, setDebouncedConfig] = useState(config);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedConfig(config);
    }, 400);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [config]);

  // Preview query
  const { data: preview, isLoading, isError } = useQuery<ReportPreviewResponse>({
    queryKey: ["report-preview", debouncedConfig],
    queryFn: () => api.previewReport(debouncedConfig),
  });

  // Preset handler
  const applyPreset = useCallback((preset: Preset) => {
    setFilters({ ...emptyFilters, ...preset.filters });
    setColumns([...preset.columns]);
    setSortField(preset.sort_field);
    setSortDir(preset.sort_dir);
    setGroupBy(preset.group_by);
    setIncludeExcluded(preset.include_excluded);
    setActivePreset(preset.name);
  }, []);

  // Column toggle
  function toggleColumn(field: string) {
    setActivePreset(null);
    setColumns((prev) =>
      prev.includes(field) ? prev.filter((c) => c !== field) : [...prev, field]
    );
  }

  // Export
  async function handleExport() {
    setExporting(true);
    try {
      await api.exportReport(config);
    } catch (err) {
      console.error("Export failed:", err);
    } finally {
      setExporting(false);
    }
  }

  // Determine which columns to show in the preview table
  const previewColumns = groupBy
    ? ["group", "count", "open", "avg_ttr_hours"]
    : columns;
  const previewHeaders = groupBy
    ? [
        FIELD_META[groupBy]?.label ?? groupBy,
        "Count",
        "Open",
        "Avg TTR (h)",
      ]
    : columns.map((c) => FIELD_META[c]?.label ?? c);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
        <p className="mt-1 text-sm text-gray-500">
          Build custom reports with filters, column selection, sorting, and grouping.
        </p>
      </div>

      {/* Presets */}
      <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
          Quick Presets
        </h2>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.name}
              onClick={() => applyPreset(p)}
              className={[
                "rounded-full border px-3 py-1.5 text-sm font-medium transition-colors",
                activePreset === p.name
                  ? "border-blue-600 bg-blue-600 text-white"
                  : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50",
              ].join(" ")}
            >
              {p.name}
            </button>
          ))}
        </div>
      </section>

      {/* Filters */}
      <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
          Filters
        </h2>
        <div className="flex flex-wrap items-center gap-3">
          <TicketFilters
            filters={filters}
            onFilterChange={(f) => { setFilters(f); setActivePreset(null); }}
          />
          <label className="ml-2 flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={includeExcluded}
              onChange={(e) => { setIncludeExcluded(e.target.checked); setActivePreset(null); }}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Include excluded
          </label>
        </div>
      </section>

      {/* Columns */}
      <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
            Columns ({columns.length} selected)
          </h2>
          <div className="flex gap-2">
            <button
              onClick={() => { setColumns([...ALL_FIELDS]); setActivePreset(null); }}
              className="text-xs font-medium text-blue-600 hover:text-blue-800"
            >
              Select All
            </button>
            <button
              onClick={() => { setColumns(["key"]); setActivePreset(null); }}
              className="text-xs font-medium text-blue-600 hover:text-blue-800"
            >
              Deselect All
            </button>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3 lg:grid-cols-4">
          {ALL_FIELDS.map((field) => (
            <label
              key={field}
              className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer hover:text-gray-900"
              title={FIELD_META[field]?.description}
            >
              <input
                type="checkbox"
                checked={columns.includes(field)}
                onChange={() => toggleColumn(field)}
                className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              {FIELD_META[field]?.label ?? field}
            </label>
          ))}
        </div>
      </section>

      {/* Sort & Group */}
      <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
          Sort & Group
        </h2>
        <div className="flex flex-wrap items-center gap-4">
          {/* Sort field */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">Sort by</span>
            <select
              value={sortField}
              onChange={(e) => { setSortField(e.target.value); setActivePreset(null); }}
              className="h-9 rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {SORTABLE_FIELDS.map((f) => (
                <option key={f} value={f}>{FIELD_META[f]?.label ?? f}</option>
              ))}
            </select>
            <button
              onClick={() => { setSortDir((d) => d === "asc" ? "desc" : "asc"); setActivePreset(null); }}
              className="h-9 rounded-md border border-gray-300 bg-white px-3 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
              title={sortDir === "asc" ? "Ascending" : "Descending"}
            >
              {sortDir === "asc" ? "↑ Asc" : "↓ Desc"}
            </button>
          </div>

          {/* Group by */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">Group by</span>
            <select
              value={groupBy ?? ""}
              onChange={(e) => { setGroupBy(e.target.value || null); setActivePreset(null); }}
              className="h-9 rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">None</option>
              {GROUPABLE_FIELDS.map((f) => (
                <option key={f} value={f}>{FIELD_META[f]?.label ?? f}</option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {/* Preview */}
      <section className="rounded-lg border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
            Preview
          </h2>
          {preview && (
            <span className="text-xs text-gray-400">
              Showing {Math.min(preview.rows.length, 100)} of{" "}
              {preview.total_count.toLocaleString()}{" "}
              {preview.grouped ? "groups" : "tickets"}
            </span>
          )}
        </div>
        <div className="overflow-x-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <svg className="h-6 w-6 animate-spin text-blue-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="ml-2 text-sm text-gray-500">Loading preview...</span>
            </div>
          ) : isError ? (
            <div className="py-12 text-center text-sm text-red-500">
              Failed to load preview. Check your filters and try again.
            </div>
          ) : preview && preview.rows.length === 0 ? (
            <div className="py-12 text-center text-sm text-gray-400">
              No matching tickets found.
            </div>
          ) : preview ? (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  {previewHeaders.map((h, i) => (
                    <th
                      key={i}
                      className="whitespace-nowrap px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-500"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {preview.rows.map((row, ri) => (
                  <tr key={ri} className="hover:bg-gray-50">
                    {previewColumns.map((col, ci) => (
                      <td
                        key={ci}
                        className={[
                          "whitespace-nowrap px-4 py-2 text-gray-700",
                          col === "summary" ? "max-w-xs truncate" : "",
                        ].join(" ")}
                        title={col === "summary" ? String(row[col] ?? "") : undefined}
                      >
                        {formatCellValue(row[col])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      </section>

      {/* Export buttons */}
      <section className="flex items-center gap-4">
        <button
          onClick={handleExport}
          disabled={exporting}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {exporting ? (
            <>
              <svg className="h-5 w-5 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Exporting...
            </>
          ) : (
            <>
              <DownloadIcon className="h-5 w-5" />
              Export to Excel
            </>
          )}
        </button>
        <a
          href={api.exportExcel()}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm font-medium text-gray-500 underline hover:text-gray-700"
        >
          Export All (legacy)
        </a>
      </section>
    </div>
  );
}
