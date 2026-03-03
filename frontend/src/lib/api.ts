/**
 * API client for the OIT Helpdesk Dashboard backend.
 *
 * All requests are proxied through Vite's dev-server to http://localhost:8000
 * so we use relative URLs starting with /api.
 */

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GET ${url} failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${url} failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// TypeScript interfaces – mirror the backend Pydantic models
// ---------------------------------------------------------------------------

/** Top-level headline KPIs shown on the dashboard. */
export interface HeadlineMetrics {
  total_tickets: number;
  open_backlog: number;
  resolved: number;
  resolution_rate: number;
  median_ttr_hours: number;
  p90_ttr_hours: number;
  p95_ttr_hours: number;
  stale_count: number;
  excluded_count: number;
}

/** Weekly volume data point for the trend chart. */
export interface WeeklyVolume {
  week: string;
  created: number;
  resolved: number;
  net_flow: number;
}

/** Bucket for the ticket-age distribution chart. */
export interface AgeBucket {
  bucket: string;
  count: number;
}

/** Bucket for time-to-resolution distribution. */
export interface TTRBucket {
  bucket: string;
  count: number;
  percent: number;
  cumulative_percent: number;
}

/** Priority breakdown count. */
export interface PriorityCount {
  priority: string;
  total: number;
  open: number;
}

/** Per-assignee statistics. */
export interface AssigneeStats {
  name: string;
  resolved: number;
  open: number;
  median_ttr: number;
  p90_ttr: number;
  stale: number;
}

/** Full metrics payload returned by GET /api/metrics. */
export interface MetricsResponse {
  headline: HeadlineMetrics;
  weekly_volumes: WeeklyVolume[];
  age_buckets: AgeBucket[];
  ttr_distribution: TTRBucket[];
  priority_counts: PriorityCount[];
  assignee_stats: AssigneeStats[];
}

/** A single row in the tickets table. */
export interface TicketRow {
  key: string;
  summary: string;
  issue_type: string;
  status: string;
  status_category: string;
  priority: string;
  resolution: string;
  assignee: string;
  assignee_account_id: string;
  reporter: string;
  created: string;
  updated: string;
  resolved: string;
  request_type: string;
  calendar_ttr_hours: number | null;
  age_days: number | null;
  days_since_update: number | null;
  excluded: boolean;
  sla_first_response_status: string;
  sla_resolution_status: string;
  labels: string[];
}

/** Paginated tickets response from GET /api/tickets. */
export interface TicketsResponse {
  tickets: TicketRow[];
  has_more: boolean;
  page: number;
  page_size: number;
}

/** SLA timer summary for a single timer type. */
export interface SLATimerSummary {
  timer_name: string;
  total: number;
  met: number;
  breached: number;
  running: number;
  paused: number;
  met_rate: number;
  breach_rate: number;
  compliance_pct: number;
}

/** Assignee option for dropdowns. */
export interface Assignee {
  account_id: string;
  display_name: string;
}

/** Available status transition for an issue. */
export interface Transition {
  id: string;
  name: string;
  to_status: string;
}

/** Result of a bulk operation on one ticket. */
export interface BulkResult {
  key: string;
  success: boolean;
  error?: string;
}

/** Request bodies for bulk operations. */
export interface BulkStatusRequest {
  keys: string[];
  transition_id: string;
}

export interface BulkAssignRequest {
  keys: string[];
  account_id: string;
}

export interface BulkPriorityRequest {
  keys: string[];
  priority: string;
}

export interface BulkCommentRequest {
  keys: string[];
  comment: string;
}

/** Cache status returned by GET /api/cache/status. */
export interface CacheStatus {
  initialized: boolean;
  refreshing: boolean;
  issue_count: number;
  filtered_count: number;
  last_refresh: string | null;
}

// ---------------------------------------------------------------------------
// Query-parameter helpers
// ---------------------------------------------------------------------------

export interface TicketQueryParams {
  page?: number;
  page_size?: number;
  status?: string;
  priority?: string;
  assignee?: string;
  issue_type?: string;
  search?: string;
  open_only?: boolean;
  stale_only?: boolean;
  created_after?: string;
  created_before?: string;
}

export interface MetricsQueryParams {
  date_from?: string;
  date_to?: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildQuery(params: any): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") {
      qs.set(k, String(v));
    }
  }
  const str = qs.toString();
  return str ? `?${str}` : "";
}

// ---------------------------------------------------------------------------
// API object
// ---------------------------------------------------------------------------

export const api = {
  /** Fetch aggregate dashboard metrics, optionally filtered by date range. */
  getMetrics(params: MetricsQueryParams = {}): Promise<MetricsResponse> {
    return fetchJSON<MetricsResponse>(`/api/metrics${buildQuery(params)}`);
  },

  /** Fetch a paginated, filterable list of tickets. */
  getTickets(params: TicketQueryParams = {}): Promise<TicketsResponse> {
    return fetchJSON<TicketsResponse>(`/api/tickets${buildQuery(params)}`);
  },

  /** Fetch a single ticket by its Jira key (e.g. "OIT-1234"). */
  getTicket(key: string): Promise<TicketRow> {
    return fetchJSON<TicketRow>(`/api/tickets/${encodeURIComponent(key)}`);
  },

  /** Fetch SLA timer summary across all timers. */
  getSLASummary(): Promise<SLATimerSummary[]> {
    return fetchJSON<SLATimerSummary[]>("/api/sla/summary");
  },

  /** Fetch list of tickets currently breaching SLA. */
  getSLABreaches(): Promise<TicketRow[]> {
    return fetchJSON<TicketRow[]>("/api/sla/breaches");
  },

  /** Fetch assignable users for the project. */
  getAssignees(): Promise<Assignee[]> {
    return fetchJSON<Assignee[]>("/api/assignees");
  },

  /** Fetch available status transitions for a given issue. */
  getTransitions(key: string): Promise<Transition[]> {
    return fetchJSON<Transition[]>(
      `/api/statuses/${encodeURIComponent(key)}`
    );
  },

  /** Bulk-transition tickets to a new status. */
  bulkStatus(keys: string[], transitionId: string): Promise<BulkResult[]> {
    const body: BulkStatusRequest = { keys, transition_id: transitionId };
    return postJSON<BulkResult[]>("/api/tickets/bulk/status", body);
  },

  /** Bulk-assign tickets to a user. */
  bulkAssign(keys: string[], accountId: string): Promise<BulkResult[]> {
    const body: BulkAssignRequest = { keys, account_id: accountId };
    return postJSON<BulkResult[]>("/api/tickets/bulk/assign", body);
  },

  /** Bulk-update ticket priority. */
  bulkPriority(keys: string[], priority: string): Promise<BulkResult[]> {
    const body: BulkPriorityRequest = { keys, priority };
    return postJSON<BulkResult[]>("/api/tickets/bulk/priority", body);
  },

  /** Bulk-add a comment to tickets. */
  bulkComment(keys: string[], comment: string): Promise<BulkResult[]> {
    const body: BulkCommentRequest = { keys, comment };
    return postJSON<BulkResult[]>("/api/tickets/bulk/comment", body);
  },

  /** Return the URL for the Excel export endpoint (browser navigates to it). */
  exportExcel(): string {
    return "/api/export/excel";
  },

  /** Fetch current cache status. */
  getCacheStatus(): Promise<CacheStatus> {
    return fetchJSON<CacheStatus>("/api/cache/status");
  },

  /** Trigger a full cache refresh (returns when complete). */
  refreshCache(): Promise<CacheStatus> {
    return postJSON<CacheStatus>("/api/cache/refresh", {});
  },

  /** Trigger an incremental cache refresh (last 10 min of changes). */
  refreshCacheIncremental(): Promise<CacheStatus> {
    return postJSON<CacheStatus>("/api/cache/refresh/incremental", {});
  },
};

export default api;
