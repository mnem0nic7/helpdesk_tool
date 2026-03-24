import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import { logClientError } from "../lib/errorLogging.ts";
import type {
  Assignee,
  OasisDevWorkloadReportRequest,
  OasisDevWorkloadReportResponse,
  ReportConfig,
  ReportPreviewResponse,
  ReportTemplate,
  ReportTemplateSaveRequest,
} from "../lib/api.ts";
import TicketFilters, {
  emptyFilters,
} from "../components/TicketFilters.tsx";
import type { TicketFilterValues } from "../components/TicketFilters.tsx";
import { getSiteBranding } from "../lib/siteContext.ts";

// ---------------------------------------------------------------------------
// Field metadata — all 21 TicketRow fields with categories
// ---------------------------------------------------------------------------

interface FieldInfo {
  label: string;
  description: string;
  category: "identity" | "workflow" | "people" | "dates" | "metrics" | "sla";
}

const FIELD_META: Record<string, FieldInfo> = {
  key:                       { label: "Key",               description: "Jira issue key",                     category: "identity" },
  summary:                   { label: "Summary",           description: "Issue title",                        category: "identity" },
  description:               { label: "Description",       description: "Issue description text",             category: "identity" },
  issue_type:                { label: "Type",              description: "Issue type",                         category: "identity" },
  labels:                    { label: "Labels",            description: "Issue labels",                       category: "identity" },
  components:                { label: "Components",        description: "Issue components",                   category: "identity" },
  organizations:             { label: "Organizations",     description: "Customer organizations",             category: "identity" },
  request_type:              { label: "Request Type",      description: "JSM request type",                   category: "identity" },
  status:                    { label: "Status",            description: "Current status",                     category: "workflow" },
  status_category:           { label: "Status Category",   description: "To Do / In Progress / Done",         category: "workflow" },
  priority:                  { label: "Priority",          description: "Priority level",                     category: "workflow" },
  resolution:                { label: "Resolution",        description: "Resolution type",                    category: "workflow" },
  work_category:             { label: "Work Category",     description: "Operational categorization",         category: "workflow" },
  excluded:                  { label: "Excluded",          description: "Excluded from metrics",              category: "workflow" },
  assignee:                  { label: "Assignee",          description: "Assigned team member",               category: "people" },
  assignee_account_id:       { label: "Assignee ID",       description: "Atlassian account ID",               category: "people" },
  reporter:                  { label: "Reporter",          description: "Ticket creator",                     category: "people" },
  last_comment_author:       { label: "Last Commenter",    description: "Author of the latest comment",       category: "people" },
  created:                   { label: "Created",           description: "Creation date",                      category: "dates" },
  updated:                   { label: "Updated",           description: "Last update date",                   category: "dates" },
  resolved:                  { label: "Resolved",          description: "Resolution date",                    category: "dates" },
  last_comment_date:         { label: "Last Comment",      description: "Latest comment timestamp",           category: "dates" },
  calendar_ttr_hours:        { label: "TTR (h)",           description: "Time-to-resolution in hours",        category: "metrics" },
  age_days:                  { label: "Age (d)",           description: "Age of open tickets in days",        category: "metrics" },
  days_since_update:         { label: "Days Since Update", description: "Days since last update",             category: "metrics" },
  comment_count:             { label: "Comments",          description: "Number of comments",                 category: "metrics" },
  attachment_count:          { label: "Attachments",       description: "Number of attachments",              category: "metrics" },
  sla_first_response_status: { label: "SLA Response",      description: "First-response SLA status",          category: "sla" },
  sla_resolution_status:     { label: "SLA Resolution",    description: "Resolution SLA status",              category: "sla" },
};

const COLUMN_CATEGORIES: { key: string; label: string; icon: string }[] = [
  { key: "identity", label: "Identification", icon: "tag" },
  { key: "workflow", label: "Workflow",       icon: "flow" },
  { key: "people",   label: "People",         icon: "people" },
  { key: "dates",    label: "Dates",          icon: "calendar" },
  { key: "metrics",  label: "Metrics",        icon: "chart" },
  { key: "sla",      label: "SLA",            icon: "clock" },
];

const ALL_FIELDS = Object.keys(FIELD_META);

const DEFAULT_COLUMNS = [
  "key", "summary", "issue_type", "status", "priority",
  "assignee", "created", "resolved", "calendar_ttr_hours",
];

const SORTABLE_FIELDS = ALL_FIELDS.filter((f) => !["labels", "components", "organizations"].includes(f));

const GROUPABLE_FIELDS = [
  "status", "status_category", "priority", "assignee", "reporter",
  "issue_type", "resolution", "request_type", "work_category", "excluded",
  "sla_first_response_status", "sla_resolution_status",
];

// ---------------------------------------------------------------------------
// Presets with icons & descriptions
// ---------------------------------------------------------------------------

interface Preset {
  name: string;
  description: string;
  icon: string;
  accent: string;
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
    description: "Active tickets grouped by priority level",
    icon: "priority",
    accent: "rose",
    filters: { open_only: true },
    columns: ["key", "summary", "priority", "status", "assignee", "age_days", "days_since_update"],
    sort_field: "priority",
    sort_dir: "asc",
    group_by: "priority",
    include_excluded: false,
  },
  {
    name: "Resolution by Assignee",
    description: "Team performance and resolution metrics",
    icon: "team",
    accent: "violet",
    filters: {},
    columns: ["key", "summary", "assignee", "status", "resolved", "calendar_ttr_hours"],
    sort_field: "resolved",
    sort_dir: "desc",
    group_by: "assignee",
    include_excluded: false,
  },
  {
    name: "Last 30 Days",
    description: "Recent ticket activity and trends",
    icon: "calendar",
    accent: "sky",
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
    description: "SLA compliance and breach tracking",
    icon: "alert",
    accent: "amber",
    filters: {},
    columns: ["key", "summary", "status", "priority", "assignee", "sla_first_response_status", "sla_resolution_status", "created"],
    sort_field: "created",
    sort_dir: "desc",
    group_by: null,
    include_excluded: false,
  },
  {
    name: "Stale Open Tickets",
    description: "Aging tickets needing attention",
    icon: "stale",
    accent: "orange",
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
    label: f.label || undefined,
    search: f.search || undefined,
    open_only: f.open_only || undefined,
    stale_only: f.stale_only || undefined,
    created_after: f.created_after || undefined,
    created_before: f.created_before || undefined,
  };
}

function formatCellValue(value: unknown, field?: string): string {
  if (value === null || value === undefined || value === "") return "\u2014";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    if (field === "calendar_ttr_hours" || field === "avg_ttr_hours") {
      if (value < 1) return `${Math.round(value * 60)}m`;
      if (value < 24) return `${value.toFixed(1)}h`;
      return `${(value / 24).toFixed(1)}d`;
    }
    if (field === "age_days" || field === "days_since_update") {
      return `${value.toFixed(1)}d`;
    }
    return String(Math.round(value * 10) / 10);
  }
  if (Array.isArray(value)) return value.join(", ") || "\u2014";
  // Format date strings
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
    const d = new Date(value);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }
  return String(value);
}

function toDateInputValue(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatPlainDate(value: string): string {
  if (!value) return "\u2014";
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// ---------------------------------------------------------------------------
// Inline SVG Icons
// ---------------------------------------------------------------------------

function PresetIcon({ type, className }: { type: string; className?: string }) {
  const cn = className ?? "w-5 h-5";
  switch (type) {
    case "priority":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.05 3.636a1 1 0 010 1.414 7 7 0 000 9.9 1 1 0 11-1.414 1.414 9 9 0 010-12.728 1 1 0 011.414 0zm9.9 0a1 1 0 011.414 0 9 9 0 010 12.728 1 1 0 11-1.414-1.414 7 7 0 000-9.9 1 1 0 010-1.414zM7.879 6.464a1 1 0 010 1.414 3 3 0 000 4.243 1 1 0 01-1.415 1.414 5 5 0 010-7.07 1 1 0 011.415 0zm4.242 0a1 1 0 011.415 0 5 5 0 010 7.072 1 1 0 01-1.415-1.415 3 3 0 000-4.242 1 1 0 010-1.415zM10 9a1 1 0 100 2 1 1 0 000-2z" clipRule="evenodd" />
        </svg>
      );
    case "team":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path d="M7 8a3 3 0 100-6 3 3 0 000 6zM14.5 9a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM1.615 16.428a1.224 1.224 0 01-.569-1.175 6.002 6.002 0 0111.908 0c.058.467-.172.92-.57 1.174A9.953 9.953 0 017 18a9.953 9.953 0 01-5.385-1.572zM14.5 16h-.106c.07-.297.088-.611.048-.933a7.47 7.47 0 00-1.588-3.755 4.502 4.502 0 015.874 2.636.818.818 0 01-.36.98A7.465 7.465 0 0114.5 16z" />
        </svg>
      );
    case "calendar":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.75 2a.75.75 0 01.75.75V4h7V2.75a.75.75 0 011.5 0V4h.25A2.75 2.75 0 0118 6.75v8.5A2.75 2.75 0 0115.25 18H4.75A2.75 2.75 0 012 15.25v-8.5A2.75 2.75 0 014.75 4H5V2.75A.75.75 0 015.75 2zm-1 5.5c-.69 0-1.25.56-1.25 1.25v6.5c0 .69.56 1.25 1.25 1.25h10.5c.69 0 1.25-.56 1.25-1.25v-6.5c0-.69-.56-1.25-1.25-1.25H4.75z" clipRule="evenodd" />
        </svg>
      );
    case "alert":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
        </svg>
      );
    case "stale":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
        </svg>
      );
    default:
      return null;
  }
}

function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
    </svg>
  );
}

function ChevronIcon({ open, className }: { open: boolean; className?: string }) {
  return (
    <svg
      className={`${className ?? "w-4 h-4"} transition-transform duration-200 ${open ? "rotate-180" : ""}`}
      viewBox="0 0 20 20"
      fill="currentColor"
    >
      <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
    </svg>
  );
}

function CategoryIcon({ type, className }: { type: string; className?: string }) {
  const cn = className ?? "w-3.5 h-3.5";
  switch (type) {
    case "tag":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.5 3A2.5 2.5 0 003 5.5v2.879a2.5 2.5 0 00.732 1.767l6.5 6.5a2.5 2.5 0 003.536 0l2.878-2.878a2.5 2.5 0 000-3.536l-6.5-6.5A2.5 2.5 0 008.38 3H5.5zM6 7a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
        </svg>
      );
    case "flow":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M2.5 4A1.5 1.5 0 001 5.5v2A1.5 1.5 0 002.5 9h1.382a1.5 1.5 0 001.342.829h2.764A1.5 1.5 0 009.33 9h1.34a1.5 1.5 0 001.342.829h2.764A1.5 1.5 0 0016.118 9h1.382A1.5 1.5 0 0019 7.5v-2A1.5 1.5 0 0017.5 4h-15zm0 7A1.5 1.5 0 001 12.5v2A1.5 1.5 0 002.5 16h15a1.5 1.5 0 001.5-1.5v-2a1.5 1.5 0 00-1.5-1.5h-15z" clipRule="evenodd" />
        </svg>
      );
    case "people":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path d="M7 8a3 3 0 100-6 3 3 0 000 6zM14.5 9a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM1.615 16.428a1.224 1.224 0 01-.569-1.175 6.002 6.002 0 0111.908 0c.058.467-.172.92-.57 1.174A9.953 9.953 0 017 18a9.953 9.953 0 01-5.385-1.572zM14.5 16h-.106c.07-.297.088-.611.048-.933a7.47 7.47 0 00-1.588-3.755 4.502 4.502 0 015.874 2.636.818.818 0 01-.36.98A7.465 7.465 0 0114.5 16z" />
        </svg>
      );
    case "calendar":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.75 2a.75.75 0 01.75.75V4h7V2.75a.75.75 0 011.5 0V4h.25A2.75 2.75 0 0118 6.75v8.5A2.75 2.75 0 0115.25 18H4.75A2.75 2.75 0 012 15.25v-8.5A2.75 2.75 0 014.75 4H5V2.75A.75.75 0 015.75 2zm-1 5.5c-.69 0-1.25.56-1.25 1.25v6.5c0 .69.56 1.25 1.25 1.25h10.5c.69 0 1.25-.56 1.25-1.25v-6.5c0-.69-.56-1.25-1.25-1.25H4.75z" clipRule="evenodd" />
        </svg>
      );
    case "chart":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path d="M15.5 2A1.5 1.5 0 0014 3.5v13a1.5 1.5 0 001.5 1.5h1a1.5 1.5 0 001.5-1.5v-13A1.5 1.5 0 0016.5 2h-1zM9.5 6A1.5 1.5 0 008 7.5v9A1.5 1.5 0 009.5 18h1a1.5 1.5 0 001.5-1.5v-9A1.5 1.5 0 0010.5 6h-1zM3.5 10A1.5 1.5 0 002 11.5v5A1.5 1.5 0 003.5 18h1A1.5 1.5 0 006 16.5v-5A1.5 1.5 0 004.5 10h-1z" />
        </svg>
      );
    case "clock":
      return (
        <svg className={cn} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
        </svg>
      );
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Inline badge renderers for the preview table
// ---------------------------------------------------------------------------

const PRIORITY_STYLES: Record<string, string> = {
  Highest: "bg-red-100 text-red-800 border-red-200",
  High:    "bg-orange-100 text-orange-800 border-orange-200",
  Medium:  "bg-yellow-100 text-yellow-800 border-yellow-200",
  Low:     "bg-blue-100 text-blue-800 border-blue-200",
  Lowest:  "bg-slate-100 text-slate-600 border-slate-200",
  New:     "bg-purple-100 text-purple-800 border-purple-200",
};

const SLA_STYLES: Record<string, string> = {
  Met:      "bg-emerald-100 text-emerald-800",
  BREACHED: "bg-red-100 text-red-800",
  Running:  "bg-blue-100 text-blue-800",
  Paused:   "bg-gray-100 text-gray-600",
};

const STATUS_CAT_STYLES: Record<string, string> = {
  "Done":        "bg-emerald-100 text-emerald-800",
  "In Progress": "bg-blue-100 text-blue-800",
  "To Do":       "bg-slate-100 text-slate-600",
};

function CellContent({ value, field }: { value: unknown; field: string }) {
  const str = String(value ?? "");

  // Priority badge
  if (field === "priority" && str && str !== "\u2014") {
    const style = PRIORITY_STYLES[str] ?? "bg-gray-100 text-gray-700 border-gray-200";
    return (
      <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${style}`}>
        {str}
      </span>
    );
  }

  // Status category badge
  if (field === "status_category" && str && str !== "\u2014") {
    const style = STATUS_CAT_STYLES[str] ?? "bg-gray-100 text-gray-600";
    return (
      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${style}`}>
        {str}
      </span>
    );
  }

  // SLA badges
  if ((field === "sla_first_response_status" || field === "sla_resolution_status") && str && str !== "\u2014") {
    const style = SLA_STYLES[str] ?? "bg-gray-100 text-gray-600";
    return (
      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${style}`}>
        {str === "BREACHED" ? "Breached" : str}
      </span>
    );
  }

  // Excluded boolean
  if (field === "excluded") {
    if (value === true) return <span className="inline-flex items-center rounded-full bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-600">Excluded</span>;
    return <span className="text-gray-300">\u2014</span>;
  }

  // Numeric fields — right-aligned, formatted
  if (field === "calendar_ttr_hours" || field === "age_days" || field === "days_since_update" || field === "avg_ttr_hours" || field === "count" || field === "open") {
    const formatted = formatCellValue(value, field);
    // Color code age/stale values
    if ((field === "age_days" || field === "days_since_update") && typeof value === "number") {
      const color = value > 30 ? "text-red-600" : value > 7 ? "text-amber-600" : "text-gray-700";
      return <span className={`tabular-nums ${color}`}>{formatted}</span>;
    }
    return <span className="tabular-nums text-gray-700">{formatted}</span>;
  }

  // Key — monospace
  if (field === "key") {
    return <span className="font-mono text-xs font-semibold text-slate-700">{str}</span>;
  }

  // Summary — truncated
  if (field === "summary") {
    return <span className="block max-w-xs truncate text-gray-800" title={str}>{str || "\u2014"}</span>;
  }

  // Date fields
  if ((field === "created" || field === "updated" || field === "resolved") && str && /^\d{4}-\d{2}-\d{2}T/.test(str)) {
    const d = new Date(str);
    return <span className="tabular-nums text-gray-600 text-xs">{d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>;
  }

  // Group header in aggregated view
  if (field === "group") {
    return <span className="font-semibold text-gray-900">{str || "(none)"}</span>;
  }

  return <>{formatCellValue(value, field)}</>;
}

// ---------------------------------------------------------------------------
// Collapsible section wrapper
// ---------------------------------------------------------------------------

function Section({
  title,
  badge,
  defaultOpen = true,
  children,
  actions,
}: {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
  actions?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-gray-50/60 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <ChevronIcon open={open} className="w-4 h-4 text-gray-400" />
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-500">
            {title}
          </h2>
          {badge && (
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-600">
              {badge}
            </span>
          )}
        </div>
        {actions && <div onClick={(e) => e.stopPropagation()}>{actions}</div>}
      </button>
      {open && (
        <div className="border-t border-gray-100 px-5 py-4">
          {children}
        </div>
      )}
    </section>
  );
}

function WorkloadStatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "blue" | "emerald" | "amber" | "slate";
}) {
  const accentClass =
    accent === "emerald"
      ? "text-emerald-700"
      : accent === "amber"
        ? "text-amber-700"
        : accent === "slate"
          ? "text-slate-700"
          : "text-blue-700";
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50/60 px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${accentClass}`}>{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Accent color map for presets
// ---------------------------------------------------------------------------

const ACCENT_CLASSES: Record<string, { bg: string; border: string; text: string; icon: string; activeBg: string; activeBorder: string; activeText: string }> = {
  rose:   { bg: "bg-rose-50/60",   border: "border-rose-200/60",   text: "text-rose-700",   icon: "text-rose-500",   activeBg: "bg-rose-600",   activeBorder: "border-rose-600",   activeText: "text-white" },
  violet: { bg: "bg-violet-50/60", border: "border-violet-200/60", text: "text-violet-700", icon: "text-violet-500", activeBg: "bg-violet-600", activeBorder: "border-violet-600", activeText: "text-white" },
  sky:    { bg: "bg-sky-50/60",    border: "border-sky-200/60",    text: "text-sky-700",    icon: "text-sky-500",    activeBg: "bg-sky-600",    activeBorder: "border-sky-600",    activeText: "text-white" },
  amber:  { bg: "bg-amber-50/60",  border: "border-amber-200/60",  text: "text-amber-700",  icon: "text-amber-500",  activeBg: "bg-amber-600",  activeBorder: "border-amber-600",  activeText: "text-white" },
  orange: { bg: "bg-orange-50/60", border: "border-orange-200/60", text: "text-orange-700", icon: "text-orange-500", activeBg: "bg-orange-600", activeBorder: "border-orange-600", activeText: "text-white" },
};

const READINESS_STYLES: Record<string, string> = {
  ready: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  proxy: "bg-amber-50 text-amber-700 ring-amber-200",
  gap: "bg-rose-50 text-rose-700 ring-rose-200",
  custom: "bg-slate-50 text-slate-700 ring-slate-200",
};

function applyReportTemplateConfig(
  template: ReportTemplate,
  setters: {
    setFilters: (value: TicketFilterValues) => void;
    setColumns: (value: string[]) => void;
    setSortField: (value: string) => void;
    setSortDir: (value: "asc" | "desc") => void;
    setGroupBy: (value: string | null) => void;
    setIncludeExcluded: (value: boolean) => void;
  },
) {
  const templateFilters = template.config.filters ?? {};
  setters.setFilters({
    ...emptyFilters,
    search: templateFilters.search ?? "",
    status: templateFilters.status ?? "",
    priority: templateFilters.priority ?? "",
    issue_type: templateFilters.issue_type ?? "",
    label: templateFilters.label ?? "",
    open_only: Boolean(templateFilters.open_only),
    stale_only: Boolean(templateFilters.stale_only),
    created_after: templateFilters.created_after ?? "",
    created_before: templateFilters.created_before ?? "",
    assignee: templateFilters.assignee ?? "",
  });
  setters.setColumns(
    (template.config.columns?.length ? template.config.columns : DEFAULT_COLUMNS).filter((field) => field in FIELD_META),
  );
  setters.setSortField(template.config.sort_field || "created");
  setters.setSortDir(template.config.sort_dir === "asc" ? "asc" : "desc");
  setters.setGroupBy(template.config.group_by || null);
  setters.setIncludeExcluded(Boolean(template.config.include_excluded));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ReportsPage() {
  const site = getSiteBranding();
  const isOasisDev = site.scope === "oasisdev";
  const queryClient = useQueryClient();
  const todayInput = useMemo(() => toDateInputValue(new Date()), []);
  const startOfYearInput = useMemo(() => {
    const today = new Date();
    return `${today.getFullYear()}-01-01`;
  }, []);

  // Config state
  const [filters, setFilters] = useState<TicketFilterValues>({ ...emptyFilters });
  const [columns, setColumns] = useState<string[]>([...DEFAULT_COLUMNS]);
  const [sortField, setSortField] = useState("created");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [groupBy, setGroupBy] = useState<string | null>(null);
  const [includeExcluded, setIncludeExcluded] = useState(false);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [templateName, setTemplateName] = useState("");
  const [templateDescription, setTemplateDescription] = useState("");
  const [templateCategory, setTemplateCategory] = useState("Custom");
  const [templateNotes, setTemplateNotes] = useState("");
  const [templateMessage, setTemplateMessage] = useState<{ tone: "success" | "error" | "info"; text: string } | null>(null);
  const [workloadAssignee, setWorkloadAssignee] = useState("");
  const [workloadReportStart, setWorkloadReportStart] = useState(startOfYearInput);
  const [workloadReportEnd, setWorkloadReportEnd] = useState(todayInput);
  const [workloadLastReportDate, setWorkloadLastReportDate] = useState(startOfYearInput);
  const [workloadExporting, setWorkloadExporting] = useState(false);

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
  const { data: preview, isLoading, isFetching, isError } = useQuery<ReportPreviewResponse>({
    queryKey: ["report-preview", debouncedConfig],
    queryFn: () => api.previewReport(debouncedConfig),
  });

  const {
    data: templates = [],
    isLoading: isTemplatesLoading,
  } = useQuery<ReportTemplate[]>({
    queryKey: ["report-templates", site.scope],
    queryFn: () => api.listReportTemplates(),
  });

  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === selectedTemplateId) ?? null,
    [selectedTemplateId, templates],
  );

  const workloadRequest: OasisDevWorkloadReportRequest = useMemo(
    () => ({
      assignee: workloadAssignee || undefined,
      report_start: workloadReportStart || undefined,
      report_end: workloadReportEnd || undefined,
      last_report_date: workloadLastReportDate || undefined,
    }),
    [workloadAssignee, workloadLastReportDate, workloadReportEnd, workloadReportStart],
  );

  const { data: assignees = [] } = useQuery<Assignee[]>({
    queryKey: ["assignees", isOasisDev ? "oasisdev-reports" : "reports"],
    queryFn: () => api.getAssignees(),
    enabled: isOasisDev,
  });

  const {
    data: workloadPreview,
    isLoading: isWorkloadLoading,
    isFetching: isWorkloadFetching,
    isError: isWorkloadError,
    error: workloadError,
  } = useQuery<OasisDevWorkloadReportResponse>({
    queryKey: ["oasisdev-workload-report", workloadRequest],
    queryFn: () => api.previewOasisDevWorkloadReport(workloadRequest),
    enabled: isOasisDev,
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
    setSelectedTemplateId(null);
  }, []);

  const syncTemplateEditor = useCallback((template: ReportTemplate | null) => {
    setTemplateName(template?.name ?? "");
    setTemplateDescription(template?.description ?? "");
    setTemplateCategory(template?.category || "Custom");
    setTemplateNotes(template?.notes ?? "");
  }, []);

  const createTemplateMutation = useMutation({
    mutationFn: (body: ReportTemplateSaveRequest) => api.createReportTemplate(body),
    onSuccess: (template) => {
      queryClient.invalidateQueries({ queryKey: ["report-templates", site.scope] }).catch(() => undefined);
      setSelectedTemplateId(template.id);
      syncTemplateEditor(template);
      setTemplateMessage({ tone: "success", text: `Saved template "${template.name}".` });
    },
    onError: (error) => {
      logClientError("Failed to create report template", error, { kind: "report-template-create" });
      setTemplateMessage({
        tone: "error",
        text: error instanceof Error ? error.message : "Failed to save report template.",
      });
    },
  });

  const updateTemplateMutation = useMutation({
    mutationFn: ({ templateId, body }: { templateId: string; body: ReportTemplateSaveRequest }) =>
      api.updateReportTemplate(templateId, body),
    onSuccess: (template) => {
      queryClient.invalidateQueries({ queryKey: ["report-templates", site.scope] }).catch(() => undefined);
      setSelectedTemplateId(template.id);
      syncTemplateEditor(template);
      setTemplateMessage({ tone: "success", text: `Updated template "${template.name}".` });
    },
    onError: (error) => {
      logClientError("Failed to update report template", error, { kind: "report-template-update" });
      setTemplateMessage({
        tone: "error",
        text: error instanceof Error ? error.message : "Failed to update report template.",
      });
    },
  });

  const deleteTemplateMutation = useMutation({
    mutationFn: (templateId: string) => api.deleteReportTemplate(templateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["report-templates", site.scope] }).catch(() => undefined);
      setSelectedTemplateId(null);
      syncTemplateEditor(null);
      setTemplateMessage({ tone: "success", text: "Deleted saved report template." });
    },
    onError: (error) => {
      logClientError("Failed to delete report template", error, { kind: "report-template-delete" });
      setTemplateMessage({
        tone: "error",
        text: error instanceof Error ? error.message : "Failed to delete report template.",
      });
    },
  });

  // Column toggle
  function toggleColumn(field: string) {
    setActivePreset(null);
    setColumns((prev) =>
      prev.includes(field) ? prev.filter((c) => c !== field) : [...prev, field]
    );
  }

  // Category toggle
  function toggleCategory(category: string) {
    const catFields = ALL_FIELDS.filter((f) => FIELD_META[f].category === category);
    const allSelected = catFields.every((f) => columns.includes(f));
    setActivePreset(null);
    if (allSelected) {
      setColumns((prev) => prev.filter((c) => !catFields.includes(c) || c === "key"));
    } else {
      setColumns((prev) => [...new Set([...prev, ...catFields])]);
    }
  }

  // Export
  async function handleExport() {
    setExporting(true);
    try {
      await api.exportReport(config);
    } catch (err) {
      logClientError("Export failed", err, { kind: "report" });
    } finally {
      setExporting(false);
    }
  }

  async function handleWorkloadExport() {
    setWorkloadExporting(true);
    try {
      await api.exportOasisDevWorkloadReport(workloadRequest);
    } catch (err) {
      logClientError("OasisDev workload export failed", err, { kind: "workload" });
    } finally {
      setWorkloadExporting(false);
    }
  }

  function handleLoadTemplate(template: ReportTemplate) {
    applyReportTemplateConfig(template, {
      setFilters,
      setColumns,
      setSortField,
      setSortDir,
      setGroupBy,
      setIncludeExcluded,
    });
    setActivePreset(null);
    setSelectedTemplateId(template.id);
    syncTemplateEditor(template);
    setTemplateMessage({ tone: "info", text: `Loaded template "${template.name}".` });
  }

  function handleNewTemplate() {
    setSelectedTemplateId(null);
    syncTemplateEditor(null);
    setTemplateMessage(null);
  }

  function handleSaveTemplate() {
    const trimmedName = templateName.trim();
    if (!trimmedName) {
      setTemplateMessage({ tone: "error", text: "Template name is required." });
      return;
    }
    const body: ReportTemplateSaveRequest = {
      name: trimmedName,
      description: templateDescription.trim(),
      category: templateCategory.trim() || "Custom",
      notes: templateNotes.trim(),
      config,
    };
    if (selectedTemplate && !selectedTemplate.is_seed) {
      updateTemplateMutation.mutate({ templateId: selectedTemplate.id, body });
      return;
    }
    createTemplateMutation.mutate(body);
  }

  function handleDeleteTemplate() {
    if (!selectedTemplate || selectedTemplate.is_seed) {
      return;
    }
    if (!window.confirm(`Delete the saved template "${selectedTemplate.name}"?`)) {
      return;
    }
    deleteTemplateMutation.mutate(selectedTemplate.id);
  }

  // Determine preview columns and headers
  const previewColumns = groupBy
    ? ["group", "count", "open", "avg_ttr_hours"]
    : columns;
  const previewHeaders = groupBy
    ? [FIELD_META[groupBy]?.label ?? groupBy, "Count", "Open", "Avg TTR"]
    : columns.map((c) => FIELD_META[c]?.label ?? c);

  // Numeric fields for right-alignment
  const numericFields = new Set([
    "calendar_ttr_hours", "age_days", "days_since_update",
    "comment_count", "attachment_count", "count", "open", "avg_ttr_hours",
  ]);

  const templateBusy =
    createTemplateMutation.isPending ||
    updateTemplateMutation.isPending ||
    deleteTemplateMutation.isPending;

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {isOasisDev ? "Reports" : "Report Builder"}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {isOasisDev
              ? "Run the OasisDev workload report for Dave, or build your own custom export below."
              : "Configure filters, select columns, and preview before exporting."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <a
            href={api.exportAll()}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-600 shadow-sm transition-colors hover:bg-gray-50 hover:text-gray-800"
          >
            <DownloadIcon className="h-3.5 w-3.5" />
            Export All Data
          </a>
          <button
            onClick={handleExport}
            disabled={exporting}
            className="inline-flex items-center gap-2 rounded-md bg-slate-800 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-all hover:bg-slate-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {exporting ? (
              <>
                <svg className="h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Exporting...
              </>
            ) : (
              <>
                <DownloadIcon className="h-4 w-4" />
                Export to Excel
              </>
            )}
          </button>
        </div>
      </div>

      {isOasisDev && (
        <Section
          title="Workload Report"
          badge={workloadPreview ? `${workloadPreview.since_last_report.tickets.length} tickets since last report` : undefined}
          defaultOpen={true}
          actions={
            <button
              onClick={handleWorkloadExport}
              disabled={workloadExporting}
              className="inline-flex items-center gap-1.5 rounded-md bg-slate-800 px-3 py-1.5 text-[11px] font-semibold text-white shadow-sm transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <DownloadIcon className="h-3.5 w-3.5" />
              {workloadExporting ? "Exporting..." : "Export Dave Report"}
            </button>
          }
        >
          <div className="space-y-5">
            <div className="grid gap-4 lg:grid-cols-[1.2fr_repeat(3,minmax(0,1fr))]">
              <label className="space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">
                  Assignee
                </span>
                <select
                  value={workloadAssignee}
                  onChange={(e) => setWorkloadAssignee(e.target.value)}
                  className="h-10 w-full rounded-md border border-gray-200 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
                >
                  <option value="">All assignees</option>
                  {assignees.map((assignee) => (
                    <option key={assignee.account_id} value={assignee.display_name}>
                      {assignee.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">
                  Report Start
                </span>
                <input
                  type="date"
                  value={workloadReportStart}
                  onChange={(e) => setWorkloadReportStart(e.target.value)}
                  className="h-10 w-full rounded-md border border-gray-200 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">
                  Report End
                </span>
                <input
                  type="date"
                  value={workloadReportEnd}
                  onChange={(e) => setWorkloadReportEnd(e.target.value)}
                  className="h-10 w-full rounded-md border border-gray-200 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">
                  Since Last Report
                </span>
                <input
                  type="date"
                  value={workloadLastReportDate}
                  onChange={(e) => setWorkloadLastReportDate(e.target.value)}
                  className="h-10 w-full rounded-md border border-gray-200 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
                />
              </label>
            </div>

            {isWorkloadLoading && !workloadPreview ? (
              <div className="rounded-lg border border-gray-200 bg-gray-50/60 px-4 py-10 text-center text-sm text-gray-500">
                Loading workload report...
              </div>
            ) : isWorkloadError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {workloadError instanceof Error ? workloadError.message : "Failed to load workload report."}
              </div>
            ) : workloadPreview ? (
              <>
                <div className="flex items-center justify-between gap-4 rounded-lg border border-gray-200 bg-gray-50/60 px-4 py-3 text-sm text-gray-600">
                  <div>
                    Reporting window:{" "}
                    <span className="font-semibold text-gray-800">
                      {formatPlainDate(workloadPreview.summary.report_start)}
                    </span>{" "}
                    to{" "}
                    <span className="font-semibold text-gray-800">
                      {formatPlainDate(workloadPreview.summary.report_end)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <span>Assignee:</span>
                    <span className="rounded-full bg-white px-2 py-1 font-semibold text-gray-700 shadow-sm ring-1 ring-gray-200">
                      {workloadPreview.summary.assignee}
                    </span>
                    {isWorkloadFetching && (
                      <span className="rounded-full bg-blue-50 px-2 py-1 font-medium text-blue-600 ring-1 ring-blue-200">
                        Refreshing...
                      </span>
                    )}
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <WorkloadStatCard
                    label="New Since Last Report"
                    value={workloadPreview.since_last_report.created_count.toLocaleString()}
                    accent="blue"
                  />
                  <WorkloadStatCard
                    label="Resolved Since Last Report"
                    value={workloadPreview.since_last_report.resolved_count.toLocaleString()}
                    accent="emerald"
                  />
                  <WorkloadStatCard
                    label="Still Open"
                    value={workloadPreview.since_last_report.open_count.toLocaleString()}
                    accent="amber"
                  />
                  <WorkloadStatCard
                    label="Resolution Rate"
                    value={`${workloadPreview.since_last_report.resolution_rate.toFixed(1)}%`}
                    accent="slate"
                  />
                </div>

                <div className="grid gap-5 xl:grid-cols-[1.6fr_1fr]">
                  <div className="overflow-x-auto rounded-lg border border-gray-200">
                    <table className="w-full min-w-[640px] text-left text-sm">
                      <thead>
                        <tr className="border-b border-gray-200 bg-gray-50/70">
                          <th className="px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-gray-500">
                            Status
                          </th>
                          {workloadPreview.monthly_status.months.map((month) => (
                            <th
                              key={month.key}
                              className="px-3 py-2.5 text-right text-[10px] font-semibold uppercase tracking-[0.06em] text-gray-500"
                            >
                              {month.label}
                            </th>
                          ))}
                          <th className="px-3 py-2.5 text-right text-[10px] font-semibold uppercase tracking-[0.06em] text-gray-500">
                            Total
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {workloadPreview.monthly_status.rows.map((row) => (
                          <tr key={row.status} className="border-b border-gray-100 last:border-b-0">
                            <td className="px-4 py-2.5 font-medium text-gray-800">{row.status}</td>
                            {row.counts.map((count, index) => (
                              <td key={`${row.status}-${index}`} className="px-3 py-2.5 text-right tabular-nums text-gray-700">
                                {count.toLocaleString()}
                              </td>
                            ))}
                            <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-gray-900">
                              {row.total.toLocaleString()}
                            </td>
                          </tr>
                        ))}
                        <tr className="bg-gray-50/80">
                          <td className="px-4 py-2.5 font-semibold text-gray-900">Grand Total</td>
                          {workloadPreview.monthly_status.grand_total.map((count, index) => (
                            <td key={`grand-total-${index}`} className="px-3 py-2.5 text-right font-semibold tabular-nums text-gray-900">
                              {count.toLocaleString()}
                            </td>
                          ))}
                          <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-gray-900">
                            {workloadPreview.monthly_status.grand_total_overall.toLocaleString()}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  <div className="space-y-4">
                    <div className="rounded-lg border border-gray-200">
                      <div className="border-b border-gray-100 px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">
                        Created vs Resolved
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="bg-gray-50/70">
                              <th className="px-4 py-2 text-left text-[10px] font-semibold uppercase tracking-[0.06em] text-gray-500">Month</th>
                              <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.06em] text-gray-500">Created</th>
                              <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.06em] text-gray-500">Resolved</th>
                              <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.06em] text-gray-500">Net</th>
                            </tr>
                          </thead>
                          <tbody>
                            {workloadPreview.created_vs_resolved.map((row) => (
                              <tr key={row.month_key} className="border-t border-gray-100">
                                <td className="px-4 py-2.5 font-medium text-gray-800">{row.month_label}</td>
                                <td className="px-3 py-2.5 text-right tabular-nums text-gray-700">{row.created.toLocaleString()}</td>
                                <td className="px-3 py-2.5 text-right tabular-nums text-gray-700">{row.resolved.toLocaleString()}</td>
                                <td className="px-3 py-2.5 text-right tabular-nums text-gray-700">{row.net_flow.toLocaleString()}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    <div className="rounded-lg border border-gray-200 bg-gray-50/40 px-4 py-4">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">
                        Current Status Breakdown
                      </div>
                      <div className="mt-3 space-y-2">
                        {workloadPreview.since_last_report.status_breakdown.length ? (
                          workloadPreview.since_last_report.status_breakdown.map((row) => (
                            <div key={row.status} className="flex items-center justify-between rounded-md border border-gray-200 bg-white px-3 py-2 text-sm">
                              <span className="font-medium text-gray-700">{row.status}</span>
                              <span className="tabular-nums text-gray-900">{row.count.toLocaleString()}</span>
                            </div>
                          ))
                        ) : (
                          <div className="rounded-md border border-dashed border-gray-200 bg-white px-3 py-4 text-sm text-gray-500">
                            No tickets created since the selected report date.
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="rounded-lg border border-gray-200">
                  <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50/70 px-4 py-2.5">
                    <div>
                      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">
                        Since Last Report Ticket Detail
                      </div>
                      <div className="mt-1 text-xs text-gray-500">
                        Includes the fields Dave needs for workload and reporting follow-up.
                      </div>
                    </div>
                    <div className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-gray-700 ring-1 ring-gray-200">
                      {workloadPreview.since_last_report.tickets.length.toLocaleString()} tickets
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[1120px] text-left text-sm">
                      <thead>
                        <tr className="border-b border-gray-200 bg-white">
                          {[
                            "Key",
                            "Summary",
                            "Status",
                            "Priority",
                            "Assignee",
                            "Reporter",
                            "Created",
                            "Resolved",
                            "Request Type",
                            "Application",
                            "Category",
                          ].map((header) => (
                            <th
                              key={header}
                              className="px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-gray-500"
                            >
                              {header}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {workloadPreview.since_last_report.tickets.length ? (
                          workloadPreview.since_last_report.tickets.map((ticket) => (
                            <tr key={ticket.key} className="border-t border-gray-100 align-top">
                              <td className="px-4 py-2.5 font-mono text-xs font-semibold text-slate-700">{ticket.key}</td>
                              <td className="px-4 py-2.5 text-gray-800">{ticket.summary}</td>
                              <td className="px-4 py-2.5 text-gray-700">{ticket.status || "\u2014"}</td>
                              <td className="px-4 py-2.5 text-gray-700">{ticket.priority || "\u2014"}</td>
                              <td className="px-4 py-2.5 text-gray-700">{ticket.assignee || "\u2014"}</td>
                              <td className="px-4 py-2.5 text-gray-700">{ticket.reporter || "\u2014"}</td>
                              <td className="px-4 py-2.5 text-gray-700">{formatCellValue(ticket.created, "created")}</td>
                              <td className="px-4 py-2.5 text-gray-700">{formatCellValue(ticket.resolved, "resolved")}</td>
                              <td className="px-4 py-2.5 text-gray-700">{ticket.request_type || "\u2014"}</td>
                              <td className="px-4 py-2.5 text-gray-700">{ticket.application || "\u2014"}</td>
                              <td className="px-4 py-2.5 text-gray-700">{ticket.operational_categorization || "\u2014"}</td>
                            </tr>
                          ))
                        ) : (
                          <tr>
                            <td colSpan={11} className="px-4 py-10 text-center text-sm text-gray-500">
                              No tickets were created in this reporting slice.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            ) : null}
          </div>
        </Section>
      )}

      <Section
        title="Saved Templates"
        badge={isTemplatesLoading ? "Loading..." : `${templates.length} templates`}
        defaultOpen={true}
        actions={
          <button
            type="button"
            onClick={handleNewTemplate}
            className="rounded border border-gray-200 bg-gray-50 px-2 py-1 text-[10px] font-medium text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700"
          >
            New Template
          </button>
        }
      >
        <div className="space-y-4">
          {templateMessage && (
            <div
              className={[
                "rounded-md border px-3 py-2 text-sm",
                templateMessage.tone === "error"
                  ? "border-red-200 bg-red-50 text-red-700"
                  : templateMessage.tone === "success"
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : "border-blue-200 bg-blue-50 text-blue-700",
              ].join(" ")}
            >
              {templateMessage.text}
            </div>
          )}

          {isTemplatesLoading ? (
            <div className="rounded-lg border border-gray-200 bg-gray-50/60 px-4 py-10 text-center text-sm text-gray-500">
              Loading saved templates...
            </div>
          ) : templates.length ? (
            <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
              {templates.map((template) => {
                const readinessClass = READINESS_STYLES[template.readiness] ?? READINESS_STYLES.custom;
                const active = selectedTemplateId === template.id;
                return (
                  <div
                    key={template.id}
                    className={[
                      "rounded-lg border p-4 transition-colors",
                      active ? "border-slate-400 bg-slate-50/70" : "border-gray-200 bg-white",
                    ].join(" ")}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-gray-900">{template.name}</div>
                        <div className="mt-1 text-xs text-gray-500">{template.description || "Saved report template"}</div>
                      </div>
                      <div className="flex flex-wrap items-center justify-end gap-1.5">
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ${readinessClass}`}>
                          {template.readiness === "gap" ? "Needs data" : template.readiness === "proxy" ? "Proxy" : template.readiness === "ready" ? "Ready" : "Custom"}
                        </span>
                        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-600 ring-1 ring-gray-200">
                          {template.is_seed ? "Seeded" : "Saved"}
                        </span>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                      <span className="rounded-full bg-gray-50 px-2 py-0.5 ring-1 ring-gray-200">
                        {template.category || "Uncategorized"}
                      </span>
                      <span>
                        {template.config.group_by ? `Grouped by ${FIELD_META[template.config.group_by]?.label ?? template.config.group_by}` : "Detail view"}
                      </span>
                    </div>
                    {template.notes && (
                      <div className="mt-3 rounded-md bg-gray-50 px-3 py-2 text-xs leading-5 text-gray-600">
                        {template.notes}
                      </div>
                    )}
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <div className="text-[11px] text-gray-400">
                        {template.created_by_name ? `Saved by ${template.created_by_name}` : "System template"}
                      </div>
                      <button
                        type="button"
                        onClick={() => handleLoadTemplate(template)}
                        className="rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50"
                      >
                        Load
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50/60 px-4 py-10 text-center text-sm text-gray-500">
              No saved report templates yet.
            </div>
          )}

          <div className="grid gap-4 rounded-lg border border-gray-200 bg-gray-50/50 p-4 xl:grid-cols-[1.1fr_1.4fr]">
            <div className="space-y-3">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">
                  Template Details
                </div>
                <div className="mt-1 text-xs text-gray-500">
                  Save the current builder configuration as a reusable report template for this site.
                </div>
              </div>
              <label className="block space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">Name</span>
                <input
                  type="text"
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  placeholder="Executive SLA Summary"
                  className="h-10 w-full rounded-md border border-gray-200 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">Category</span>
                <input
                  type="text"
                  value={templateCategory}
                  onChange={(e) => setTemplateCategory(e.target.value)}
                  placeholder="Operational"
                  className="h-10 w-full rounded-md border border-gray-200 bg-white px-3 text-sm text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">Description</span>
                <textarea
                  value={templateDescription}
                  onChange={(e) => setTemplateDescription(e.target.value)}
                  rows={3}
                  placeholder="Short explanation of what this report is for."
                  className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">Notes</span>
                <textarea
                  value={templateNotes}
                  onChange={(e) => setTemplateNotes(e.target.value)}
                  rows={4}
                  placeholder="Add operator guidance, caveats, or how this metric should be interpreted."
                  className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
                />
              </label>
            </div>

            <div className="space-y-4">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-500">
                  Current Builder Snapshot
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  <div className="rounded-md border border-gray-200 bg-white px-3 py-3">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-400">Filters</div>
                    <div className="mt-1 text-lg font-semibold text-gray-900">
                      {Object.entries(config.filters).filter(([, value]) => Boolean(value)).length}
                    </div>
                  </div>
                  <div className="rounded-md border border-gray-200 bg-white px-3 py-3">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-400">Columns</div>
                    <div className="mt-1 text-lg font-semibold text-gray-900">{columns.length}</div>
                  </div>
                  <div className="rounded-md border border-gray-200 bg-white px-3 py-3">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gray-400">View</div>
                    <div className="mt-1 text-sm font-semibold text-gray-900">
                      {groupBy ? `Grouped by ${FIELD_META[groupBy]?.label ?? groupBy}` : "Detail rows"}
                    </div>
                  </div>
                </div>
              </div>

              <div className="rounded-md border border-gray-200 bg-white px-4 py-3 text-xs leading-5 text-gray-600">
                {selectedTemplate ? (
                  <>
                    Editing{" "}
                    <span className="font-semibold text-gray-800">{selectedTemplate.name}</span>
                    {selectedTemplate.is_seed ? " (seed templates are read-only, so saving will create a new copy)." : "."}
                  </>
                ) : (
                  "Saving now will create a new reusable template from the current builder state."
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={handleSaveTemplate}
                  disabled={templateBusy}
                  className="rounded-md bg-slate-800 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {templateBusy ? "Saving..." : selectedTemplate && !selectedTemplate.is_seed ? "Update Template" : "Save Template"}
                </button>
                <button
                  type="button"
                  onClick={handleNewTemplate}
                  className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
                >
                  Clear Selection
                </button>
                <button
                  type="button"
                  onClick={handleDeleteTemplate}
                  disabled={!selectedTemplate || selectedTemplate.is_seed || templateBusy}
                  className="rounded-md border border-red-200 bg-white px-3 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Delete Template
                </button>
              </div>
            </div>
          </div>
        </div>
      </Section>

      {/* Presets */}
      <div className="grid grid-cols-5 gap-3">
        {PRESETS.map((p) => {
          const active = activePreset === p.name;
          const accent = ACCENT_CLASSES[p.accent] ?? ACCENT_CLASSES.sky;
          return (
            <button
              key={p.name}
              onClick={() => applyPreset(p)}
              className={[
                "group relative flex flex-col items-start gap-1.5 rounded-lg border p-3 text-left transition-all",
                active
                  ? `${accent.activeBg} ${accent.activeBorder} ${accent.activeText} shadow-md`
                  : `${accent.bg} ${accent.border} hover:shadow-sm`,
              ].join(" ")}
            >
              <div className={`${active ? accent.activeText : accent.icon} transition-colors`}>
                <PresetIcon type={p.icon} className="w-5 h-5" />
              </div>
              <div>
                <div className={`text-xs font-semibold leading-tight ${active ? accent.activeText : accent.text}`}>
                  {p.name}
                </div>
                <div className={`mt-0.5 text-[10px] leading-snug ${active ? "text-white/80" : "text-gray-500"}`}>
                  {p.description}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Filters */}
      <Section title="Filters" defaultOpen={true}>
        <div className="flex flex-wrap items-center gap-3">
          <TicketFilters
            filters={filters}
            onFilterChange={(f) => { setFilters(f); setActivePreset(null); }}
          />
          <label className="ml-2 flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-600 cursor-pointer hover:bg-gray-100 transition-colors select-none">
            <input
              type="checkbox"
              checked={includeExcluded}
              onChange={(e) => { setIncludeExcluded(e.target.checked); setActivePreset(null); }}
              className="h-3.5 w-3.5 rounded border-gray-300 text-slate-700 focus:ring-slate-500"
            />
            Include excluded
          </label>
        </div>
      </Section>

      {/* Columns */}
      <Section
        title="Columns"
        badge={`${columns.length} selected`}
        defaultOpen={true}
        actions={
          <div className="flex gap-1.5">
            <button
              onClick={() => { setColumns([...ALL_FIELDS]); setActivePreset(null); }}
              className="rounded border border-gray-200 bg-gray-50 px-2 py-1 text-[10px] font-medium text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700"
            >
              All
            </button>
            <button
              onClick={() => { setColumns([...DEFAULT_COLUMNS]); setActivePreset(null); }}
              className="rounded border border-gray-200 bg-gray-50 px-2 py-1 text-[10px] font-medium text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700"
            >
              Default
            </button>
            <button
              onClick={() => { setColumns(["key"]); setActivePreset(null); }}
              className="rounded border border-gray-200 bg-gray-50 px-2 py-1 text-[10px] font-medium text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700"
            >
              None
            </button>
          </div>
        }
      >
        <div className="grid grid-cols-2 gap-x-8 gap-y-4 sm:grid-cols-3">
          {COLUMN_CATEGORIES.map((cat) => {
            const catFields = ALL_FIELDS.filter((f) => FIELD_META[f].category === cat.key);
            const selectedCount = catFields.filter((f) => columns.includes(f)).length;
            return (
              <div key={cat.key}>
                <button
                  type="button"
                  onClick={() => toggleCategory(cat.key)}
                  className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <CategoryIcon type={cat.icon} className="w-3 h-3" />
                  {cat.label}
                  <span className="text-[9px] font-normal text-gray-300">
                    ({selectedCount}/{catFields.length})
                  </span>
                </button>
                <div className="space-y-1">
                  {catFields.map((field) => (
                    <label
                      key={field}
                      className="flex items-center gap-2 cursor-pointer group"
                      title={FIELD_META[field].description}
                    >
                      <input
                        type="checkbox"
                        checked={columns.includes(field)}
                        onChange={() => toggleColumn(field)}
                        className="h-3.5 w-3.5 rounded border-gray-300 text-slate-700 focus:ring-slate-500"
                      />
                      <span className="text-xs text-gray-600 group-hover:text-gray-900 transition-colors">
                        {FIELD_META[field].label}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      {/* Sort & Group */}
      <Section title="Sort & Group" defaultOpen={true}>
        <div className="flex flex-wrap items-center gap-5">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-gray-500">Sort by</span>
            <select
              value={sortField}
              onChange={(e) => { setSortField(e.target.value); setActivePreset(null); }}
              className="h-8 rounded-md border border-gray-200 bg-white px-2.5 text-xs text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
            >
              {SORTABLE_FIELDS.map((f) => (
                <option key={f} value={f}>{FIELD_META[f]?.label ?? f}</option>
              ))}
            </select>
            <button
              onClick={() => { setSortDir((d) => d === "asc" ? "desc" : "asc"); setActivePreset(null); }}
              className="flex h-8 items-center gap-1 rounded-md border border-gray-200 bg-white px-2.5 text-xs font-medium text-gray-600 shadow-sm transition-colors hover:bg-gray-50"
              title={sortDir === "asc" ? "Ascending" : "Descending"}
            >
              <svg className={`w-3 h-3 transition-transform ${sortDir === "desc" ? "rotate-180" : ""}`} viewBox="0 0 12 12" fill="currentColor">
                <path d="M6 2l4 4H2l4-4z" />
              </svg>
              {sortDir === "asc" ? "Ascending" : "Descending"}
            </button>
          </div>

          <div className="h-6 w-px bg-gray-200" />

          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-gray-500">Group by</span>
            <select
              value={groupBy ?? ""}
              onChange={(e) => { setGroupBy(e.target.value || null); setActivePreset(null); }}
              className="h-8 rounded-md border border-gray-200 bg-white px-2.5 text-xs text-gray-700 shadow-sm focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-400"
            >
              <option value="">None</option>
              {GROUPABLE_FIELDS.map((f) => (
                <option key={f} value={f}>{FIELD_META[f]?.label ?? f}</option>
              ))}
            </select>
          </div>
        </div>
      </Section>

      {/* Preview */}
      <section className="rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
        {/* Preview header with stats */}
        <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50/80 px-5 py-2.5">
          <div className="flex items-center gap-3">
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-500">
              Preview
            </h2>
            {isFetching && (
              <svg className="h-3.5 w-3.5 animate-spin text-slate-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
          </div>
          {preview && (
            <div className="flex items-center gap-4 text-[11px] tabular-nums">
              <span className="text-gray-400">
                Showing <span className="font-semibold text-gray-600">{Math.min(preview.rows.length, 100)}</span> of{" "}
                <span className="font-semibold text-gray-600">{preview.total_count.toLocaleString()}</span>{" "}
                {preview.grouped ? "groups" : "tickets"}
              </span>
              {!preview.grouped && preview.total_count > 100 && (
                <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 border border-amber-200/60">
                  Preview limited to 100 rows
                </span>
              )}
            </div>
          )}
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          {isLoading && !preview ? (
            <div className="flex flex-col items-center justify-center py-16 gap-3">
              <svg className="h-8 w-8 animate-spin text-slate-300" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-xs text-gray-400">Loading preview...</span>
            </div>
          ) : isError ? (
            <div className="flex flex-col items-center justify-center py-16 gap-2">
              <svg className="w-8 h-8 text-red-300" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
              <span className="text-xs text-red-400">Failed to load preview</span>
            </div>
          ) : preview && preview.rows.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-2">
              <svg className="w-8 h-8 text-gray-200" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M2 4.75A.75.75 0 012.75 4h14.5a.75.75 0 010 1.5H2.75A.75.75 0 012 4.75zM2 10a.75.75 0 01.75-.75h14.5a.75.75 0 010 1.5H2.75A.75.75 0 012 10zm0 5.25a.75.75 0 01.75-.75h14.5a.75.75 0 010 1.5H2.75a.75.75 0 01-.75-.75z" clipRule="evenodd" />
              </svg>
              <span className="text-xs text-gray-400">No matching tickets</span>
            </div>
          ) : preview ? (
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50/50">
                  {previewHeaders.map((h, i) => (
                    <th
                      key={i}
                      className={[
                        "whitespace-nowrap px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-gray-400",
                        numericFields.has(previewColumns[i]) ? "text-right" : "",
                      ].join(" ")}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row, ri) => (
                  <tr
                    key={ri}
                    className={[
                      "border-b border-gray-50 transition-colors hover:bg-slate-50/60",
                      ri % 2 === 1 ? "bg-gray-50/30" : "",
                    ].join(" ")}
                  >
                    {previewColumns.map((col, ci) => (
                      <td
                        key={ci}
                        className={[
                          "whitespace-nowrap px-4 py-2 text-gray-700",
                          numericFields.has(col) ? "text-right" : "",
                        ].join(" ")}
                      >
                        <CellContent value={row[col]} field={col} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      </section>
    </div>
  );
}
