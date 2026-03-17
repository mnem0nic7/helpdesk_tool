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
  if (res.status === 401) {
    window.location.href = "/api/auth/login";
    throw new Error("Not authenticated");
  }
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
  if (res.status === 401) {
    window.location.href = "/api/auth/login";
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${url} failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}

async function putJSON<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    window.location.href = "/api/auth/login";
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PUT ${url} failed (${res.status}): ${text}`);
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

/** Volume data point for the trend chart (daily/weekly/monthly). */
export interface WeeklyVolume {
  week: string;
  created: number;
  resolved: number;
  net_flow: number;
  grouping?: string;
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
  // SLA first response
  sla_first_response_status: string;
  sla_first_response_breach_time: string;
  sla_first_response_remaining_millis: number | null;
  // SLA resolution
  sla_resolution_status: string;
  sla_resolution_breach_time: string;
  sla_resolution_remaining_millis: number | null;
  // Additional fields
  labels: string[];
  components: string[];
  work_category: string;
  organizations: string[];
  attachment_count: number;
}

/** Tickets response from GET /api/tickets. */
export interface TicketsResponse {
  tickets: TicketRow[];
  matched_count?: number;
  total_count?: number;
}

export interface VisibleTicketRefreshResponse {
  requested_count: number;
  visible_count: number;
  refreshed_count: number;
  refreshed_keys: string[];
  skipped_keys: string[];
  missing_keys: string[];
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

export interface PriorityOption {
  id: string;
  name: string;
}

export interface RequestTypeOption {
  id: string;
  name: string;
  description: string;
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

export interface TicketComment {
  id: string;
  author: string;
  created: string;
  updated: string;
  body: string;
  public: boolean;
}

export interface TicketAttachment {
  id: string;
  filename: string;
  mime_type: string;
  size: number;
  created: string;
  author: string;
  content_url: string;
  thumbnail_url: string;
}

export interface TicketIssueLink {
  direction: string;
  relationship: string;
  type: string;
  key: string;
  summary: string;
  status: string;
  url: string;
}

export interface TicketDetail {
  ticket: TicketRow;
  description: string;
  steps_to_recreate: string;
  request_type: string;
  work_category: string;
  comments: TicketComment[];
  attachments: TicketAttachment[];
  issue_links: TicketIssueLink[];
  jira_url: string;
  portal_url: string;
  raw_issue: Record<string, unknown>;
}

export interface TicketUpdatePayload {
  summary?: string;
  description?: string;
  priority?: string;
  assignee_account_id?: string | null;
  request_type_id?: string;
}

/** Filters for the report builder. */
export interface ReportFilters {
  status?: string;
  priority?: string;
  assignee?: string;
  issue_type?: string;
  label?: string;
  search?: string;
  open_only?: boolean;
  stale_only?: boolean;
  created_after?: string;
  created_before?: string;
}

/** Full report builder configuration. */
export interface ReportConfig {
  filters: ReportFilters;
  columns: string[];
  sort_field: string;
  sort_dir: "asc" | "desc";
  group_by: string | null;
  include_excluded: boolean;
}

/** Response from POST /api/report/preview. */
export interface ReportPreviewResponse {
  rows: Record<string, unknown>[];
  total_count: number;
  grouped: boolean;
}

/** Request body for grouped chart data. */
export interface ChartDataRequest {
  filters?: ReportFilters;
  group_by: string;
  metric?: string;
  include_excluded?: boolean;
}

/** Request body for time series chart data. */
export interface ChartTimeseriesRequest {
  filters?: ReportFilters;
  bucket?: string;
  include_excluded?: boolean;
}

/** A single data point in a grouped chart response. */
export interface ChartDataPoint {
  label: string;
  value: number;
}

/** Response from POST /api/chart/data. */
export interface ChartDataResponse {
  data: ChartDataPoint[];
  group_by: string;
  metric: string;
}

/** A single data point in a time series chart response. */
export interface ChartTimeseriesPoint {
  period: string;
  created: number;
  resolved: number;
  net_flow: number;
}

/** Response from POST /api/chart/timeseries. */
export interface ChartTimeseriesResponse {
  data: ChartTimeseriesPoint[];
  bucket: string;
}

// ---------------------------------------------------------------------------
// AI Triage interfaces
// ---------------------------------------------------------------------------

/** AI-generated suggestion for a single ticket field. */
export interface TriageSuggestion {
  field: string;
  current_value: string;
  suggested_value: string;
  reasoning: string;
  confidence: number;
}

/** Full AI triage result for one ticket. */
export interface TriageResult {
  key: string;
  suggestions: TriageSuggestion[];
  model_used: string;
  created_at: string;
  error?: string;
}

/** A single AI triage log entry (auto or user-approved). */
export interface TriageLogEntry {
  key: string;
  field: string;
  old_value: string;
  new_value: string;
  confidence: number;
  model: string;
  source: "auto" | "user";
  approved_by: string | null;
  timestamp: string;
}

export interface TechnicianScoreEntry {
  key: string;
  communication_score: number;
  communication_notes: string;
  documentation_score: number;
  documentation_notes: string;
  overall_score: number;
  score_summary: string;
  model_used: string;
  created_at: string;
  ticket_summary: string;
  ticket_status: string;
  ticket_assignee: string;
  ticket_resolved: string;
}

/** Available AI model for triage. */
export interface AIModel {
  id: string;
  name: string;
  provider: string;
}

// ---------------------------------------------------------------------------
// Custom SLA interfaces
// ---------------------------------------------------------------------------

/** A single SLA computation result per ticket per timer. */
export interface SLATicketTimer {
  status: "met" | "breached" | "running";
  elapsed_minutes: number;
  target_minutes: number;
}

/** Per-ticket row with SLA data from GET /api/sla/metrics. */
export interface SLATicketRow extends TicketRow {
  sla_first_response: SLATicketTimer | null;
  sla_resolution: SLATicketTimer | null;
}

/** A single bucket in the elapsed-time distribution. */
export interface SLADistributionBucket {
  label: string;
  count: number;
}

/** Summary stats for a single SLA timer. */
export interface SLATimerStats {
  total: number;
  met: number;
  breached: number;
  running: number;
  compliance_pct: number;
  avg_elapsed_minutes: number;
  p95_elapsed_minutes: number;
  distribution: SLADistributionBucket[];
}

/** Full response from GET /api/sla/metrics. */
export interface SLAMetricsResponse {
  summary: {
    first_response: SLATimerStats;
    resolution: SLATimerStats;
  };
  tickets: SLATicketRow[];
  settings: SLASettings;
  targets: SLATarget[];
}

/** SLA target configuration. */
export interface SLATarget {
  id: number;
  sla_type: "first_response" | "resolution";
  dimension: "default" | "priority" | "request_type";
  dimension_value: string;
  target_minutes: number;
}

/** Business hours settings. */
export interface SLASettings {
  business_hours_start: string;
  business_hours_end: string;
  business_timezone: string;
  business_days: string;
  integration_reporters: string;
}

// ---------------------------------------------------------------------------
// Email Alert types
// ---------------------------------------------------------------------------

export interface AlertRule {
  id: number;
  name: string;
  enabled: boolean;
  trigger_type: string;
  trigger_config: Record<string, unknown>;
  frequency: string;
  schedule_time: string;
  schedule_days: string;
  recipients: string;
  cc: string;
  custom_subject: string;
  custom_message: string;
  filters: Record<string, unknown>;
  last_run: string | null;
  last_sent: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertHistoryEntry {
  id: number;
  rule_id: number;
  rule_name: string;
  trigger_type: string;
  sent_at: string;
  recipients: string;
  ticket_count: number;
  ticket_keys: string[];
  status: string;
  error: string | null;
}

export interface AlertTestResult {
  rule: AlertRule;
  matching_count: number;
  sample_keys: string[];
}

export interface AlertTriggerType {
  value: string;
  label: string;
}

/** Cache status returned by GET /api/cache/status. */
export interface CacheStatus {
  initialized: boolean;
  refreshing: boolean;
  issue_count: number;
  filtered_count: number;
  last_refresh: string | null;
  jira_base_url?: string;
  refresh_progress?: {
    phase: string;
    current: number;
    total: number;
  };
}

/** Current user info from /api/auth/me. */
export interface UserInfo {
  email: string;
  name: string;
}

export interface KnowledgeBaseArticle {
  id: number;
  slug: string;
  code: string;
  title: string;
  request_type: string;
  summary: string;
  content: string;
  source_filename: string;
  source_ticket_key: string;
  imported_from_seed: boolean;
  ai_generated: boolean;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeBaseArticleUpsertPayload {
  title: string;
  request_type: string;
  summary: string;
  content: string;
  source_ticket_key?: string;
}

export interface KnowledgeBaseDraft {
  title: string;
  request_type: string;
  summary: string;
  content: string;
  model_used: string;
  source_ticket_key: string;
  suggested_article_id: number | null;
  suggested_article_title: string;
  recommended_action: "update_existing" | "create_new";
  change_summary: string;
}

// ---------------------------------------------------------------------------
// Query-parameter helpers
// ---------------------------------------------------------------------------

export interface TicketQueryParams {
  status?: string;
  priority?: string;
  assignee?: string;
  issue_type?: string;
  label?: string;
  search?: string;
  open_only?: boolean;
  stale_only?: boolean;
  created_after?: string;
  created_before?: string;
  offset?: number;
  limit?: number;
}

export interface MetricsQueryParams {
  date_from?: string;
  date_to?: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildQuery(params: Record<string, any>): string {
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
  // -------------------------------------------------------------------------
  // Auth
  // -------------------------------------------------------------------------

  /** Fetch the current user's info (returns null if not logged in). */
  async getMe(): Promise<UserInfo | null> {
    try {
      return await fetchJSON<UserInfo>("/api/auth/me");
    } catch {
      return null;
    }
  },

  /** Log out the current user. */
  async logout(): Promise<void> {
    const res = await fetch("/api/auth/logout", { method: "POST" });
    const data = await res.json();
    if (data.redirect) {
      window.location.href = data.redirect;
    } else {
      window.location.href = "/";
    }
  },

  // -------------------------------------------------------------------------
  // Metrics
  // -------------------------------------------------------------------------

  /** Fetch aggregate dashboard metrics, optionally filtered by date range. */
  getMetrics(params: MetricsQueryParams = {}): Promise<MetricsResponse> {
    return fetchJSON<MetricsResponse>(`/api/metrics${buildQuery(params)}`);
  },

  /** Fetch a paginated, filterable list of tickets. */
  getTickets(params: TicketQueryParams = {}): Promise<TicketsResponse> {
    return fetchJSON<TicketsResponse>(`/api/tickets${buildQuery(params)}`);
  },

  /** Fetch distinct filter options (statuses, priorities, issue types) from cached data. */
  getFilterOptions(): Promise<{ statuses: string[]; priorities: string[]; issue_types: string[]; labels: string[] }> {
    return fetchJSON("/api/filter-options");
  },

  /** Fetch a single ticket by its Jira key with full detail payload. */
  getTicket(key: string): Promise<TicketDetail> {
    return fetchJSON<TicketDetail>(`/api/tickets/${encodeURIComponent(key)}`);
  },

  /** Refresh the currently displayed ticket rows from live Jira data. */
  refreshVisibleTickets(keys: string[]): Promise<VisibleTicketRefreshResponse> {
    return postJSON<VisibleTicketRefreshResponse>("/api/tickets/refresh-visible", { keys });
  },

  getPriorities(): Promise<PriorityOption[]> {
    return fetchJSON<PriorityOption[]>("/api/priorities");
  },

  getRequestTypes(): Promise<RequestTypeOption[]> {
    return fetchJSON<RequestTypeOption[]>("/api/request-types");
  },

  /** Fetch SLA timer summary across all timers. */
  getSLASummary(): Promise<SLATimerSummary[]> {
    return fetchJSON<{ timers: SLATimerSummary[] }>("/api/sla/summary").then(r => r.timers);
  },

  /** Fetch list of tickets currently breaching SLA. */
  getSLABreaches(): Promise<TicketRow[]> {
    return fetchJSON<{ breaches: TicketRow[] }>("/api/sla/breaches").then(r => r.breaches);
  },

  // -------------------------------------------------------------------------
  // Custom SLA
  // -------------------------------------------------------------------------

  /** Fetch computed SLA metrics with optional date range filter. */
  getSLAMetrics(dateFrom?: string, dateTo?: string): Promise<SLAMetricsResponse> {
    const params: Record<string, string> = {};
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    return fetchJSON<SLAMetricsResponse>(`/api/sla/metrics${buildQuery(params)}`);
  },

  /** Fetch SLA configuration (targets + settings). */
  getSLAConfig(): Promise<{ settings: SLASettings; targets: SLATarget[] }> {
    return fetchJSON("/api/sla/config");
  },

  /** Create or update an SLA target. */
  setSLATarget(target: { sla_type: string; dimension: string; dimension_value: string; target_minutes: number }): Promise<SLATarget> {
    return postJSON("/api/sla/config/targets", target);
  },

  /** Delete an SLA target. */
  async deleteSLATarget(id: number): Promise<void> {
    const res = await fetch(`/api/sla/config/targets/${id}`, { method: "DELETE" });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`DELETE failed (${res.status}): ${text}`);
    }
  },

  /** Update business hours settings. */
  updateSLASettings(settings: Partial<SLASettings>): Promise<SLASettings> {
    return fetch("/api/sla/config/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }).then(async (res) => {
      if (!res.ok) throw new Error(`PUT failed (${res.status})`);
      return res.json();
    });
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

  updateTicket(key: string, payload: TicketUpdatePayload): Promise<TicketDetail> {
    return putJSON<TicketDetail>(`/api/tickets/${encodeURIComponent(key)}`, payload);
  },

  transitionTicket(key: string, transitionId: string): Promise<TicketDetail> {
    return postJSON<TicketDetail>(`/api/tickets/${encodeURIComponent(key)}/transition`, {
      transition_id: transitionId,
    });
  },

  addTicketComment(key: string, comment: string, isPublic = false): Promise<TicketDetail> {
    return postJSON<TicketDetail>(`/api/tickets/${encodeURIComponent(key)}/comment`, {
      comment,
      public: isPublic,
    });
  },

  /** Remove the oasisdev label from a ticket and add an internal note. */
  removeOasisDevLabel(key: string): Promise<TicketDetail> {
    return postJSON<TicketDetail>(`/api/tickets/${encodeURIComponent(key)}/remove-oasisdev-label`, {});
  },

  /** Return the URL for the Excel export endpoint (browser navigates to it). */
  exportExcel(): string {
    return "/api/export/excel";
  },

  /** Return the URL for the full-data export endpoint. */
  exportAll(): string {
    return "/api/export/all";
  },

  /** Preview a report with the given config (returns up to 100 rows). */
  previewReport(config: ReportConfig): Promise<ReportPreviewResponse> {
    return postJSON<ReportPreviewResponse>("/api/report/preview", config);
  },

  /** Export a report as Excel — returns a Blob for download. */
  async exportReport(config: ReportConfig): Promise<void> {
    const res = await fetch("/api/report/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
    if (res.status === 401) {
      window.location.href = "/api/auth/login";
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Export failed (${res.status}): ${text}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    // Extract filename from Content-Disposition or use default
    const cd = res.headers.get("content-disposition");
    const match = cd?.match(/filename="?([^"]+)"?/);
    a.download = match?.[1] ?? "OIT_Report.xlsx";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  /** Fetch current cache status. */
  getCacheStatus(): Promise<CacheStatus> {
    return fetchJSON<CacheStatus>("/api/cache/status");
  },

  // -------------------------------------------------------------------------
  // Knowledge Base
  // -------------------------------------------------------------------------

  getKnowledgeBaseArticles(search = "", requestType = ""): Promise<KnowledgeBaseArticle[]> {
    return fetchJSON<KnowledgeBaseArticle[]>(
      `/api/kb/articles${buildQuery({ search, request_type: requestType })}`,
    );
  },

  getKnowledgeBaseArticle(id: number): Promise<KnowledgeBaseArticle> {
    return fetchJSON<KnowledgeBaseArticle>(`/api/kb/articles/${id}`);
  },

  createKnowledgeBaseArticle(payload: KnowledgeBaseArticleUpsertPayload): Promise<KnowledgeBaseArticle> {
    return postJSON<KnowledgeBaseArticle>("/api/kb/articles", payload);
  },

  updateKnowledgeBaseArticle(id: number, payload: KnowledgeBaseArticleUpsertPayload): Promise<KnowledgeBaseArticle> {
    return putJSON<KnowledgeBaseArticle>(`/api/kb/articles/${id}`, payload);
  },

  deleteKnowledgeBaseArticle(id: number): Promise<{ deleted: boolean }> {
    return fetch(`/api/kb/articles/${id}`, { method: "DELETE" }).then(async (res) => {
      if (!res.ok) throw new Error(`DELETE failed (${res.status}): ${await res.text()}`);
      return res.json() as Promise<{ deleted: boolean }>;
    });
  },

  reformatKnowledgeBaseArticle(id: number): Promise<{ content: string }> {
    return postJSON<{ content: string }>(`/api/kb/articles/${id}/reformat`, {});
  },

  reformatAllKnowledgeBaseArticles(): Promise<{ started: boolean; total: number }> {
    return postJSON<{ started: boolean; total: number }>("/api/kb/articles/reformat-all", {});
  },

  getReformatStatus(): Promise<{ running: boolean; processed: number; total: number; errors: number }> {
    return fetchJSON("/api/kb/reformat-status");
  },

  async draftKBArticleFromSOP(file: File): Promise<KnowledgeBaseDraft> {
    const body = new FormData();
    body.append("file", file);
    const res = await fetch("/api/kb/articles/from-sop", { method: "POST", body });
    if (res.status === 401) {
      window.location.href = "/api/auth/login";
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Upload failed (${res.status}): ${text}`);
    }
    return res.json() as Promise<KnowledgeBaseDraft>;
  },

  draftKnowledgeBaseArticleFromTicket(
    key: string,
    articleId?: number | null,
    model?: string,
  ): Promise<KnowledgeBaseDraft> {
    const body: Record<string, unknown> = { key };
    if (articleId) body.article_id = articleId;
    if (model) body.model = model;
    return postJSON<KnowledgeBaseDraft>("/api/kb/articles/draft-from-ticket", body);
  },

  /** Trigger a full cache refresh (returns when complete). */
  refreshCache(): Promise<CacheStatus> {
    return postJSON<CacheStatus>("/api/cache/refresh", {});
  },

  /** Trigger an incremental cache refresh (last 10 min of changes). */
  refreshCacheIncremental(): Promise<CacheStatus> {
    return postJSON<CacheStatus>("/api/cache/refresh/incremental", {});
  },

  /** Cancel an in-progress cache refresh. */
  cancelRefresh(): Promise<{ cancelled: boolean }> {
    return postJSON("/api/cache/refresh/cancel", {});
  },

  /** Fetch grouped chart data for bar/pie/donut charts. */
  getChartData(req: ChartDataRequest): Promise<ChartDataResponse> {
    return postJSON<ChartDataResponse>("/api/chart/data", req);
  },

  /** Fetch time series chart data for line/area charts. */
  getChartTimeseries(req: ChartTimeseriesRequest): Promise<ChartTimeseriesResponse> {
    return postJSON<ChartTimeseriesResponse>("/api/chart/timeseries", req);
  },

  // -------------------------------------------------------------------------
  // AI Triage
  // -------------------------------------------------------------------------

  /** Fetch available AI models for triage. */
  getTriageModels(): Promise<AIModel[]> {
    return fetchJSON<AIModel[]>("/api/triage/models");
  },

  /** Fetch AI triage change log. */
  getTriageLog(): Promise<TriageLogEntry[]> {
    return fetchJSON<TriageLogEntry[]>("/api/triage/log");
  },

  /** Fetch technician QA scores for closed tickets. */
  getTechnicianScores(): Promise<TechnicianScoreEntry[]> {
    return fetchJSON<TechnicianScoreEntry[]>("/api/triage/technician-scores");
  },

  /** Fetch all cached triage suggestions. */
  getTriageSuggestions(): Promise<TriageResult[]> {
    return fetchJSON<TriageResult[]>("/api/triage/suggestions");
  },

  /** Analyze tickets with a selected AI model. Use force=true to re-evaluate cached results. */
  analyzeTickets(keys: string[], model: string, force = false): Promise<TriageResult[]> {
    return postJSON<TriageResult[]>("/api/triage/analyze", { keys, model, force });
  },

  /** Apply accepted triage suggestions to a ticket (batch — legacy). */
  applyTriageSuggestion(key: string, acceptedFields: string[]): Promise<{ key: string; applied: string[]; errors: { field: string; error: string }[] }> {
    return postJSON("/api/triage/apply", { key, accepted_fields: acceptedFields });
  },

  /** Apply a single field suggestion to Jira immediately. */
  applyTriageField(key: string, field: string): Promise<{ key: string; field: string; applied: boolean; remaining_suggestions: TriageResult | null }> {
    return postJSON("/api/triage/apply-field", { key, field });
  },

  /** Dismiss all suggestions for a ticket. */
  dismissTriageSuggestion(key: string): Promise<{ key: string; dismissed: boolean }> {
    return postJSON("/api/triage/dismiss", { key });
  },

  /** Get progress of the current run-all background task. */
  getTriageRunStatus(): Promise<{ running: boolean; processed: number; total: number; current_key: string | null; remaining_count?: number; processed_count?: number }> {
    return fetchJSON("/api/triage/run-status");
  },

  /** Get progress of the current closed-ticket scoring run. */
  getTechnicianScoreRunStatus(): Promise<{ running: boolean; processed: number; total: number; current_key: string | null; remaining_count?: number; processed_count?: number }> {
    return fetchJSON("/api/triage/score-run-status");
  },

  /** Cancel the current triage run. */
  cancelTriageRun(): Promise<{ cancelled: boolean }> {
    return postJSON("/api/triage/run-cancel", {});
  },

  /** Cancel the current closed-ticket scoring run. */
  cancelTechnicianScoreRun(): Promise<{ cancelled: boolean }> {
    return postJSON("/api/triage/score-cancel", {});
  },

  /** Run auto-triage on cached tickets (background task). Optionally limit count for testing. */
  runTriageAll(model?: string, limit?: number, reset?: boolean, reprocess?: boolean): Promise<{ started: boolean; total_tickets: number }> {
    const body: Record<string, unknown> = {};
    if (model) body.model = model;
    if (limit) body.limit = limit;
    if (reset) body.reset = true;
    if (reprocess) body.reprocess = true;
    return postJSON("/api/triage/run-all", body);
  },

  /** Run technician QA scoring against already closed tickets. */
  runClosedTicketScoring(limit?: number, reset?: boolean): Promise<{ started: boolean; total_tickets: number }> {
    const body: Record<string, unknown> = {};
    if (limit) body.limit = limit;
    if (reset) body.reset = true;
    return postJSON("/api/triage/score-closed", body);
  },

  // -------------------------------------------------------------------------
  // Email Alerts
  // -------------------------------------------------------------------------

  getAlertRules(): Promise<AlertRule[]> {
    return fetchJSON<AlertRule[]>("/api/alerts/rules");
  },

  getAlertRule(id: number): Promise<AlertRule> {
    return fetchJSON<AlertRule>(`/api/alerts/rules/${id}`);
  },

  createAlertRule(data: Partial<AlertRule>): Promise<AlertRule> {
    return postJSON<AlertRule>("/api/alerts/rules", data);
  },

  updateAlertRule(id: number, data: Partial<AlertRule>): Promise<AlertRule> {
    return fetch(`/api/alerts/rules/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }).then(async (res) => {
      if (!res.ok) throw new Error(`PUT failed (${res.status})`);
      return res.json();
    });
  },

  deleteAlertRule(id: number): Promise<{ deleted: boolean }> {
    return fetch(`/api/alerts/rules/${id}`, { method: "DELETE" }).then(async (res) => {
      if (!res.ok) throw new Error(`DELETE failed (${res.status})`);
      return res.json();
    });
  },

  toggleAlertRule(id: number): Promise<AlertRule> {
    return postJSON<AlertRule>(`/api/alerts/rules/${id}/toggle`, {});
  },

  testAlertRule(id: number): Promise<AlertTestResult> {
    return postJSON<AlertTestResult>(`/api/alerts/rules/${id}/test`, {});
  },

  sendAlertRule(id: number): Promise<{ sent: boolean; matching_count: number; ticket_count?: number; reason?: string }> {
    return postJSON(`/api/alerts/rules/${id}/send`, {});
  },

  runAlerts(): Promise<{ sent_count: number }> {
    return postJSON("/api/alerts/run", {});
  },

  getAlertHistory(limit?: number, ruleId?: number): Promise<AlertHistoryEntry[]> {
    const params = new URLSearchParams();
    if (limit) params.set("limit", String(limit));
    if (ruleId) params.set("rule_id", String(ruleId));
    const qs = params.toString();
    return fetchJSON<AlertHistoryEntry[]>(`/api/alerts/history${qs ? `?${qs}` : ""}`);
  },

  getAlertTriggerTypes(): Promise<AlertTriggerType[]> {
    return fetchJSON<AlertTriggerType[]>("/api/alerts/trigger-types");
  },
};

export default api;
