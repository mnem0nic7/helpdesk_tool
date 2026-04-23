/**
 * API client for the OIT Helpdesk Dashboard backend.
 *
 * All requests are proxied through Vite's dev-server to http://localhost:8000
 * so we use relative URLs starting with /api.
 */

import { logClientError } from "./errorLogging.ts";

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

async function buildErrorMessage(method: string, url: string, res: Response): Promise<string> {
  const text = await res.text();
  let detail = text || res.statusText || "Request failed";
  if (text) {
    try {
      const payload = JSON.parse(text) as { detail?: unknown };
      if (typeof payload.detail === "string" && payload.detail.trim()) {
        detail = payload.detail.trim();
      }
    } catch {
      // Keep the raw response body when it is not JSON.
    }
  }
  return `${method} ${url} failed (${res.status}): ${detail}`;
}

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (res.status === 401) {
    window.location.href = "/api/auth/login";
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    throw new Error(await buildErrorMessage("GET", url, res));
  }
  return res.json() as Promise<T>;
}

async function fetchBlob(url: string): Promise<Blob> {
  const res = await fetch(url);
  if (res.status === 401) {
    window.location.href = "/api/auth/login";
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    throw new Error(await buildErrorMessage("GET", url, res));
  }
  return res.blob();
}

async function fetchText(url: string): Promise<string> {
  const res = await fetch(url);
  if (res.status === 401) {
    window.location.href = "/api/auth/login";
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    throw new Error(await buildErrorMessage("GET", url, res));
  }
  return res.text();
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
    throw new Error(await buildErrorMessage("POST", url, res));
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
    throw new Error(await buildErrorMessage("PUT", url, res));
  }
  return res.json() as Promise<T>;
}

async function deleteJSON(url: string): Promise<void> {
  const res = await fetch(url, {
    method: "DELETE",
  });
  if (res.status === 401) {
    window.location.href = "/api/auth/login";
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    throw new Error(await buildErrorMessage("DELETE", url, res));
  }
}

async function downloadPost(url: string, body: unknown, fallbackFilename: string): Promise<void> {
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
    throw new Error(await buildErrorMessage("POST", url, res));
  }
  const blob = await res.blob();
  const urlObject = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = urlObject;
  const contentDisposition = res.headers.get("content-disposition");
  const match = contentDisposition?.match(/filename="?([^"]+)"?/);
  a.download = match?.[1] ?? fallbackFilename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(urlObject);
}

interface DownloadGetOptions {
  timeoutMs?: number;
  timeoutMessage?: string;
}

async function downloadGet(
  url: string,
  fallbackFilename: string,
  options: DownloadGetOptions = {},
): Promise<void> {
  const timeoutMs = options.timeoutMs ?? 120_000;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(url, { signal: controller.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(
        options.timeoutMessage ??
          `Export timed out after ${Math.round(timeoutMs / 1000)} seconds.`,
      );
    }
    throw err;
  } finally {
    window.clearTimeout(timeoutId);
  }
  if (res.status === 401) {
    window.location.href = "/api/auth/login";
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    throw new Error(await buildErrorMessage("GET", url, res));
  }
  const blob = await res.blob();
  const urlObject = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = urlObject;
  const contentDisposition = res.headers.get("content-disposition");
  const match = contentDisposition?.match(/filename="?([^"]+)"?/);
  a.download = match?.[1] ?? fallbackFilename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(urlObject);
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
  occ_ticket_id?: string;
  issue_type: string;
  status: string;
  status_category: string;
  priority: string;
  resolution: string;
  assignee: string;
  assignee_account_id: string;
  reporter: string;
  reporter_account_id?: string;
  created: string;
  first_contact_date?: string;
  updated: string;
  resolved: string;
  request_type: string;
  request_type_id?: string;
  calendar_ttr_hours: number | null;
  age_days: number | null;
  days_since_update: number | null;
  excluded: boolean;
  // SLA first response
  sla_first_response_status: string;
  sla_first_response_breach_time: string;
  sla_first_response_remaining_millis: number | null;
  sla_first_response_elapsed_millis: number | null;
  sla_first_response_goal_millis: number | null;
  // SLA resolution
  sla_resolution_status: string;
  sla_resolution_breach_time: string;
  sla_resolution_remaining_millis: number | null;
  sla_resolution_elapsed_millis: number | null;
  sla_resolution_goal_millis: number | null;
  // Response/follow-up compliance proxy
  response_followup_status: string;
  first_response_2h_status: string;
  daily_followup_status: string;
  last_support_touch_date: string;
  support_touch_count: number;
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

export interface TicketFilterOptions {
  statuses: string[];
  priorities: string[];
  issue_types: string[];
  labels: string[];
  components?: string[];
  work_categories?: string[];
}

export interface VisibleTicketRefreshResponse {
  requested_count: number;
  visible_count: number;
  refreshed_count: number;
  refreshed_keys: string[];
  skipped_keys: string[];
  missing_keys: string[];
}

export interface SyncTicketReporterResponse {
  detail: TicketDetail;
  updated: boolean;
  message: string;
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
  email_address?: string;
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
  raw_filename: string;
  display_name: string;
  extension: string;
  mime_type: string;
  size: number;
  created: string;
  author: string;
  content_url: string;
  thumbnail_url: string;
  download_url: string;
  preview_url: string;
  converted_preview_url: string;
  preview_kind: "image" | "pdf" | "text" | "office" | "unsupported";
  preview_available: boolean;
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

export interface RequestorIdentity {
  extracted_email: string;
  directory_match: boolean;
  jira_account_id: string;
  jira_status: string;
  message: string;
  match_source?: string;
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
  requestor_identity: RequestorIdentity;
  raw_issue: Record<string, unknown>;
}

export interface TicketUpdatePayload {
  summary?: string;
  description?: string;
  priority?: string;
  assignee_account_id?: string | null;
  reporter_account_id?: string | null;
  reporter_display_name?: string;
  request_type_id?: string;
  components?: string[];
  work_category?: string;
}

export interface TicketCreatePayload {
  summary: string;
  description: string;
  priority: string;
  request_type_id: string;
}

export interface TicketCreateResponse {
  created_key: string;
  created_id: string;
  detail: TicketDetail;
}

export type LibraSupportFilterMode =
  | "all"
  | "libra_support"
  | "non_libra_support";

/** Filters for the report builder. */
export interface ReportFilters {
  status?: string;
  priority?: string;
  assignee?: string;
  issue_type?: string;
  label?: string;
  libra_support?: LibraSupportFilterMode;
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
  window_mode: "7d" | "30d" | "custom";
}

/** Response from POST /api/report/preview. */
export interface ReportPreviewResponse {
  rows: Record<string, unknown>[];
  total_count: number;
  grouped: boolean;
}

export interface ReportTemplate {
  id: string;
  site_scope: string;
  name: string;
  description: string;
  category: string;
  notes: string;
  readiness: "ready" | "proxy" | "gap" | "custom" | string;
  is_seed: boolean;
  include_in_master_export: boolean;
  created_at: string;
  updated_at: string;
  created_by_email: string;
  created_by_name: string;
  updated_by_email: string;
  updated_by_name: string;
  config: ReportConfig;
}

export interface ReportTemplateInsightPoint {
  date: string;
  count: number;
}

export interface ReportTemplateInsight {
  template_id: string;
  template_name: string;
  window_mode: "7d" | "30d" | "custom";
  window_label: string;
  window_field: string;
  window_field_label: string;
  window_start: string;
  window_end: string;
  count_in_window: number;
  p95_daily_count: number;
  trend: ReportTemplateInsightPoint[];
}

export interface ReportAISummary {
  template_id: string;
  template_name: string;
  site_scope: string;
  source: "manual" | "nightly";
  status: string;
  summary: string;
  bullets: string[];
  fallback_used: boolean;
  model_used: string;
  generated_at?: string | null;
  template_version: string;
  data_version: string;
  error: string;
}

export interface ReportAISummaryBatchStartResponse {
  batch_id: string;
  site_scope: string;
  status: string;
  item_count: number;
  requested_at: string;
}

export interface ReportAISummaryBatchItem {
  template_id: string;
  template_name: string;
  status: string;
  source: "manual" | "nightly";
  summary: string;
  bullets: string[];
  fallback_used: boolean;
  model_used: string;
  generated_at?: string | null;
  error: string;
}

export interface ReportAISummaryBatchStatus {
  batch_id: string;
  site_scope: string;
  status: string;
  item_count: number;
  requested_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  items: ReportAISummaryBatchItem[];
}

export interface ReportTemplateSaveRequest {
  name: string;
  description?: string;
  category?: string;
  notes?: string;
  include_in_master_export?: boolean;
  config: ReportConfig;
}

export interface OasisDevWorkloadReportRequest {
  assignee?: string;
  report_start?: string;
  report_end?: string;
  last_report_date?: string;
}

export interface OasisDevWorkloadMonth {
  key: string;
  label: string;
}

export interface OasisDevWorkloadStatusRow {
  status: string;
  counts: number[];
  total: number;
}

export interface OasisDevWorkloadFlowRow {
  month_key: string;
  month_label: string;
  created: number;
  resolved: number;
  net_flow: number;
}

export interface OasisDevWorkloadBreakdownRow {
  status: string;
  count: number;
}

export interface OasisDevWorkloadTicketRow {
  key: string;
  summary: string;
  status: string;
  priority: string;
  assignee: string;
  reporter: string;
  created: string;
  resolved: string;
  request_type: string;
  application: string;
  operational_categorization: string;
}

export interface OasisDevWorkloadReportResponse {
  summary: {
    assignee: string;
    report_start: string;
    report_end: string;
    last_report_date: string;
    tickets_created_in_window: number;
    tickets_resolved_in_window: number;
  };
  monthly_status: {
    months: OasisDevWorkloadMonth[];
    rows: OasisDevWorkloadStatusRow[];
    grand_total: number[];
    grand_total_overall: number;
  };
  created_vs_resolved: OasisDevWorkloadFlowRow[];
  since_last_report: {
    created_count: number;
    resolved_count: number;
    open_count: number;
    resolution_rate: number;
    status_breakdown: OasisDevWorkloadBreakdownRow[];
    tickets: OasisDevWorkloadTicketRow[];
  };
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

export interface TriageRunStatus {
  running: boolean;
  processed: number;
  total: number;
  current_key: string | null;
  remaining_count?: number;
  processed_count?: number;
  ai_processed_count?: number;
  changed_count?: number;
  no_change_count?: number;
  backfilled_count?: number;
  failed_count?: number;
  last_activity_at?: string | null;
  health?: "healthy" | "broken";
  health_message?: string;
}

export interface OllamaLaneSnapshot {
  url: string;
  label: string;       // "primary" | "secondary" | "security"
  active: number;
  active_labels: string[];
  queued: { priority: number; label: string }[];
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
  status: "met" | "breached" | "running" | "paused";
  elapsed_minutes: number;
  target_minutes: number;
  remaining_minutes: number | null;
  pct_of_target: number;
  risk_level: "ok" | "warning" | "at_risk" | "critical" | "paused" | "met" | "breached";
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
  paused: number;
  risk_ok: number;
  risk_warning: number;
  risk_at_risk: number;
  risk_critical: number;
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
  paused_status_names?: string;
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
export interface JiraAuthStatus {
  connected: boolean;
  mode: string;
  site_url: string;
  account_name: string;
  configured: boolean;
}

export interface UserInfo {
  email: string;
  name: string;
  is_admin: boolean;
  can_manage_users: boolean;
  can_access_tools?: boolean;
  jira_auth?: JiraAuthStatus;
}

export interface AzureDatasetStatus {
  key: string;
  label: string;
  configured: boolean;
  refreshing: boolean;
  interval_minutes: number;
  item_count: number;
  last_refresh: string | null;
  error?: string | null;
}

export interface AzureCostExportLatestDelivery {
  delivery_id: string | null;
  landing_path: string | null;
  parse_status: string | null;
  row_count: number | null;
  manifest_path: string | null;
}

export interface AzureCostExportHealth {
  delivery_count: number;
  parsed_count: number;
  quarantined_count: number;
  staged_snapshot_count: number;
  quarantine_artifact_count: number;
  status_counts: Record<string, number>;
  latest_delivery: AzureCostExportLatestDelivery | null;
  state: string;
  reason: string;
}

export interface AzureCostExportStatus {
  enabled: boolean;
  configured: boolean;
  running: boolean;
  refreshing: boolean;
  poll_interval_seconds: number;
  last_sync_started_at: string | null;
  last_sync_finished_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  health: AzureCostExportHealth;
}

export interface AzureReportingTarget {
  label: string;
  url: string | null;
  configured: boolean;
  description: string;
}

export interface AzureReportingSource {
  label: string;
  description: string;
}

export interface AzureReporting {
  power_bi: AzureReportingTarget;
  cost_analysis: AzureReportingTarget;
  sources: {
    overview: AzureReportingSource;
    cost: AzureReportingSource;
    savings: AzureReportingSource;
    exports: AzureReportingSource;
  };
}

export interface AzureCostContext {
  available: boolean;
  source: "exports" | "cache";
  source_label: string;
  source_description: string;
  window_start: string | null;
  window_end: string | null;
  record_count: number;
  currency: string;
  total_actual_cost: number;
  total_amortized_cost: number;
  export_backed: boolean;
}

export interface AzureStatus {
  configured: boolean;
  initialized: boolean;
  refreshing: boolean;
  last_refresh: string | null;
  datasets: AzureDatasetStatus[];
  cost_exports?: AzureCostExportStatus;
  reporting?: AzureReporting;
  finops?: {
    available: boolean;
    record_count: number;
    coverage_start?: string | null;
    coverage_end?: string | null;
    field_coverage?: Record<string, number>;
    ai_usage?: Record<string, unknown>;
    cost_context?: AzureCostContext;
  };
}

export interface AzureFinopsValidationCheck {
  key: string;
  label: string;
  state: "pass" | "warning" | "fail" | "unavailable" | "blocked";
  detail: string;
  source_a?: string;
  source_b?: string;
  metric?: string;
  actual?: number | string | null;
  expected?: number | string | null;
  delta?: number | string | null;
  tolerance?: number | string | null;
  unit?: string;
}

export interface AzureFinopsValidationReport {
  available: boolean;
  overall_state: "pass" | "warning" | "fail" | "unavailable" | "blocked";
  overall_label: string;
  signoff_ready: boolean;
  signoff_reason: string;
  latest_import?: {
    delivery_key?: string;
    dataset?: string;
    scope_key?: string;
    manifest_path?: string;
    parsed_at?: string;
    row_count?: number;
    source_updated_at?: string;
    imported_at?: string;
  } | null;
  latest_import_age_hours?: number | null;
  export_health?: {
    state?: string;
    reason?: string;
    expected_cadence_hours?: number;
    dataset_health?: Array<Record<string, unknown>>;
  };
  reconciliation?: Record<string, unknown>;
  drift_summary?: Record<string, number | string | null>;
  thresholds?: Record<string, number>;
  checks: AzureFinopsValidationCheck[];
  check_counts: Record<string, number>;
  selected_portal_outputs?: Record<string, unknown>;
}

export interface AzureCostSummary {
  lookback_days: number;
  total_cost: number;
  total_actual_cost?: number;
  total_amortized_cost?: number;
  currency: string;
  top_service: string;
  top_subscription: string;
  top_resource_group: string;
  recommendation_count: number;
  potential_monthly_savings: number;
  record_count?: number;
  window_start?: string | null;
  window_end?: string | null;
  source?: "exports" | "cache";
  source_label?: string;
  export_backed?: boolean;
}

export interface AzureOverviewResponse {
  subscriptions: number;
  management_groups: number;
  resources: number;
  role_assignments: number;
  users: number;
  groups: number;
  enterprise_apps: number;
  app_registrations: number;
  directory_roles: number;
  cost: AzureCostSummary;
  datasets: AzureDatasetStatus[];
  last_refresh: string | null;
  cost_exports?: AzureCostExportStatus;
  reporting?: AzureReporting;
  finops?: AzureStatus["finops"];
}

export interface AzureSubscription {
  subscription_id: string;
  display_name: string;
  state: string;
  tenant_id: string;
  authorization_source: string;
}

export interface AzureManagementGroup {
  id: string;
  name: string;
  display_name: string;
  parent_id: string;
  parent_display_name: string;
  group_type: string;
}

export interface AzureRoleAssignment {
  id: string;
  scope: string;
  subscription_id: string;
  principal_id: string;
  principal_type: string;
  role_definition_id: string;
  role_name: string;
}

export interface AzureResourceRow {
  id: string;
  name: string;
  resource_type: string;
  subscription_id: string;
  subscription_name: string;
  resource_group: string;
  location: string;
  kind: string;
  sku_name: string;
  vm_size: string;
  state: string;
  created_time: string;
  tags: Record<string, string>;
}

export interface AzureResourceListResponse {
  resources: AzureResourceRow[];
  matched_count: number;
  total_count: number;
}

export interface AzureCountByLabel {
  label: string;
  count: number;
}

export interface AzureVirtualMachineRow extends AzureResourceRow {
  size: string;
  power_state: string;
  cost: number | null;
  currency: string;
}

export interface AzureVirtualMachineSummary {
  total_vms: number;
  running_vms: number;
  deallocated_vms: number;
  distinct_sizes: number;
}

export interface AzureVirtualMachineSizeCoverageRow {
  label: string;
  region: string;
  vm_count: number;
  reserved_instance_count: number | null;
  delta: number | null;
  coverage_status: "needed" | "excess" | "balanced" | "unavailable";
}

export interface AzureVirtualMachineListResponse {
  vms: AzureVirtualMachineRow[];
  matched_count: number;
  total_count: number;
  summary: AzureVirtualMachineSummary;
  by_size: AzureVirtualMachineSizeCoverageRow[];
  by_state: AzureCountByLabel[];
  reservation_data_available: boolean;
  reservation_error: string | null;
  cost_available: boolean;
  cost_basis: string | null;
}

export interface AzureVirtualDesktopRow extends AzureVirtualMachineRow {
  assigned_user_display_name: string;
  assigned_user_principal_name: string;
  assigned_user_enabled: boolean | null;
  assigned_user_licensed: boolean | null;
  assigned_user_last_successful_utc: string;
  assigned_user_last_successful_local: string;
  assignment_source: string;
  assignment_status: "resolved" | "missing" | "unresolved";
  assigned_user_source: "avd_assigned" | "avd_last_session" | "unassigned";
  assigned_user_source_label: string;
  assigned_user_observed_utc: string;
  assigned_user_observed_local: string;
  owner_history_status: "available" | "missing_diagnostics" | "query_failed" | "no_history";
  host_pool_name: string;
  session_host_name: string;
  last_power_signal_utc: string;
  last_power_signal_local: string;
  days_since_power_signal: number | null;
  days_since_assigned_user_login: number | null;
  power_signal_stale: boolean;
  power_signal_pending: boolean;
  user_signin_stale: boolean;
  mark_for_removal: boolean;
  mark_account_for_follow_up: boolean;
  account_action: string;
  removal_reasons: string[];
  utilization_status: "over_utilized" | "under_utilized" | "healthy" | "unavailable";
  under_utilized: boolean;
  over_utilized: boolean;
  utilization_data_available: boolean;
  utilization_fully_evaluable: boolean;
  cpu_data_available: boolean;
  memory_data_available: boolean;
  cpu_max_percent_7d: number | null;
  cpu_time_at_full_percent_7d: number | null;
  memory_max_percent_7d: number | null;
  memory_time_at_full_percent_7d: number | null;
  utilization_reasons: string[];
  utilization_error: string;
}

export interface AzureVirtualDesktopRemovalSummary {
  threshold_days: number;
  tracked_desktops: number;
  removal_candidates: number;
  stale_power_signals: number;
  disabled_or_unlicensed_assignments: number;
  stale_assigned_user_signins: number;
  assignment_review_required: number;
  power_signal_pending: number;
  account_follow_up_count: number;
  explicit_avd_assignments: number;
  fallback_session_history_assignments: number;
  under_utilized: number;
  over_utilized: number;
  utilization_unavailable: number;
  owner_history_unavailable: number;
}

export interface AzureVirtualDesktopRemovalResponse {
  desktops: AzureVirtualDesktopRow[];
  matched_count: number;
  total_count: number;
  summary: AzureVirtualDesktopRemovalSummary;
  generated_at: string;
}

export interface AzureUtilizationSeriesPoint {
  timestamp: string;
  label: string;
  value: number;
}

export interface AzureVirtualDesktopUtilizationDetail {
  lookback_days: number;
  under_threshold_percent: number;
  over_threshold_percent: number;
  interval: string;
  status: "over_utilized" | "under_utilized" | "healthy" | "unavailable";
  under_utilized: boolean;
  over_utilized: boolean;
  utilization_data_available: boolean;
  utilization_fully_evaluable: boolean;
  cpu_data_available: boolean;
  memory_data_available: boolean;
  cpu_max_percent: number | null;
  cpu_points_at_full: number;
  cpu_total_points: number;
  cpu_time_at_full_percent: number | null;
  memory_max_percent: number | null;
  memory_points_at_full: number;
  memory_total_points: number;
  memory_time_at_full_percent: number | null;
  reasoning: string[];
  error: string;
  cpu_series?: AzureUtilizationSeriesPoint[];
  memory_series?: AzureUtilizationSeriesPoint[];
}

export interface AzureVirtualDesktopDetailResponse {
  desktop: AzureVirtualDesktopRow;
  utilization: AzureVirtualDesktopUtilizationDetail;
}

export interface AzureVirtualMachineAssociatedResource {
  id: string;
  name: string;
  resource_type: string;
  relationship: string;
  subscription_id: string;
  subscription_name: string;
  resource_group: string;
  location: string;
  state: string;
  cost: number | null;
  currency: string;
}

export interface AzureVirtualMachineCostDetails {
  lookback_days: number;
  currency: string;
  cost_data_available: boolean;
  cost_error: string | null;
  total_cost: number | null;
  vm_cost: number | null;
  related_resource_cost: number | null;
  priced_resource_count: number;
}

export interface AzureVirtualMachineDetailResponse {
  vm: AzureVirtualMachineRow;
  associated_resources: AzureVirtualMachineAssociatedResource[];
  cost: AzureVirtualMachineCostDetails;
}

export type AzureVirtualMachineCostExportScope = "all" | "filtered";
export type AzureVirtualMachineCostExportLookbackDays = 7 | 30 | 90;

export interface AzureVirtualMachineCostExportJobRequest {
  scope: AzureVirtualMachineCostExportScope;
  lookback_days: AzureVirtualMachineCostExportLookbackDays;
  filters?: AzureVirtualMachineQueryParams;
}

export interface AzureVirtualMachineCostExportJobStatus {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  recipient_email: string;
  scope: AzureVirtualMachineCostExportScope;
  lookback_days: AzureVirtualMachineCostExportLookbackDays;
  filters: AzureVirtualMachineQueryParams;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress_current: number;
  progress_total: number;
  progress_message: string;
  file_name: string | null;
  file_ready: boolean;
  error: string | null;
}

export interface OneDriveCopyUserOption {
  id: string;
  display_name: string;
  principal_name: string;
  mail: string;
  enabled: boolean | null;
  source: "entra" | "saved";
  on_prem_sam: string;
}

export interface OneDriveCopyJobRequest {
  source_upn: string;
  destination_upn: string;
  destination_folder: string;
  test_mode: boolean;
  test_file_limit: number;
  exclude_system_folders: boolean;
}

export interface OneDriveCopyJobEvent {
  event_id: number;
  level: "info" | "warning" | "error";
  message: string;
  created_at: string;
}

export interface AppLoginAuditEvent {
  event_id: number;
  email: string;
  name: string;
  auth_provider: string;
  site_scope: string;
  source_ip: string;
  user_agent: string;
  created_at: string;
}

export interface MailboxRule {
  id: string;
  display_name: string;
  sequence: number | null;
  is_enabled: boolean;
  has_error: boolean;
  stop_processing_rules: boolean;
  conditions_summary: string[];
  exceptions_summary: string[];
  actions_summary: string[];
}

export interface MailboxRulesStatus {
  mailbox: string;
  display_name: string;
  principal_name: string;
  primary_address: string;
  provider_enabled: boolean;
  note: string;
  rule_count: number;
  rules: MailboxRule[];
}

export interface AutoReplyStatus {
  mailbox: string;
  display_name: string;
  principal_name: string;
  status: string;  // "disabled" | "alwaysEnabled" | "scheduled"
  internal_message: string;
  external_message: string;
  scheduled_start: string;
  scheduled_end: string;
  external_audience: string;
  provider_enabled: boolean;
  note: string;
}

export interface SetAutoReplyRequest {
  mailbox: string;
  status: "disabled" | "alwaysEnabled" | "scheduled";
  internal_message: string;
  external_message: string;
  scheduled_start: string;
  scheduled_end: string;
  external_audience: "none" | "known" | "all";
}

// ---------------------------------------------------------------------------
// Defender autonomous agent
// ---------------------------------------------------------------------------

export interface DefenderAgentConfig {
  entity_cooldown_hours: number;
  alert_dedup_window_minutes: number;
  min_confidence: number;
  enabled: boolean;
  min_severity: "informational" | "low" | "medium" | "high" | "critical";
  tier2_delay_minutes: number;
  dry_run: boolean;
  poll_interval_seconds: number;
  teams_tier1_webhook: string;
  teams_tier2_webhook: string;
  teams_tier3_webhook: string;
  updated_at: string | null;
  updated_by: string;
}

export interface DefenderAgentBuiltinRule {
  rule_id: string;
  title_keywords: string[];
  category_keywords: string[];
  service_source_contains: string[];
  min_severity: string;
  tier: number;
  decision: string;
  action_type: string;
  action_types: string[];
  confidence_score: number;
  reason: string;
  off_hours_escalate: boolean;
  disabled: boolean;
  override_confidence: number | null;
  updated_at: string | null;
  updated_by: string;
}

export interface DefenderAgentPlaybook {
  id: string;
  name: string;
  description: string;
  actions: string[];
  enabled: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface DefenderAgentCustomRule {
  id: string;
  name: string;
  match_field: "title" | "category" | "service_source" | "severity";
  match_value: string;
  match_mode: "contains" | "exact" | "startswith";
  tier: number;
  action_type: string;
  confidence_score: number;
  enabled: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
  playbook_id?: string | null;
  playbook_name?: string | null;
}

export interface DefenderAgentRun {
  run_id: string;
  started_at: string;
  completed_at: string | null;
  alerts_fetched: number;
  alerts_new: number;
  decisions_made: number;
  actions_queued: number;
  skips: number;
  error: string;
}

export interface DefenderAgentDecision {
  decision_id: string;
  run_id: string;
  alert_id: string;
  alert_title: string;
  alert_severity: string;
  alert_category: string;
  alert_created_at: string;
  service_source: string;
  entities: Array<{
    type: string;
    id: string;
    name: string;
    // User enrichment (from Azure cache)
    enabled?: boolean;
    job_title?: string;
    department?: string;
    priority_band?: string;
    last_sign_in?: string;
    // Device enrichment (from Azure cache)
    compliance_state?: string;
    os?: string;
    last_sync?: string;
  }>;
  tier: number | null;
  decision: "execute" | "queue" | "recommend" | "skip";
  action_type: string;
  action_types: string[];
  job_ids: string[];
  reason: string;
  executed_at: string;
  not_before_at: string | null;
  cancelled: boolean;
  cancelled_at: string | null;
  cancelled_by: string;
  human_approved: boolean;
  approved_at: string | null;
  approved_by: string;
  alert_raw?: Record<string, unknown>;
  alert_written_back: boolean;
  mitre_techniques: string[];
  remediation_confirmed: boolean;
  remediation_failed: boolean;
  confirmed_at: string | null;
  confidence_score: number;
  disposition: "true_positive" | "false_positive" | "inconclusive" | null;
  disposition_note: string;
  disposition_by: string;
  disposition_at: string | null;
  investigation_notes: Array<{ text: string; by: string; at: string }>;
  watchlisted_entities: Array<{ id: string; entity_id: string; entity_name: string; entity_type: string; boost_tier: boolean; reason: string }>;
  tags: string[];
  resolved: boolean;
  resolved_at: string | null;
  resolved_by: string;
  ai_narrative: string | null;
  ai_narrative_generated_at: string | null;
}

export interface DefenderAgentWatchlistEntry {
  id: string;
  entity_type: "user" | "device";
  entity_id: string;
  entity_name: string;
  reason: string;
  boost_tier: boolean;
  created_by: string;
  created_at: string;
  active: boolean;
}

export interface DefenderAgentDecisionsResponse {
  decisions: DefenderAgentDecision[];
  total: number;
}

export interface DefenderAgentDispositionStats {
  total_actioned: number;
  reviewed: number;
  unreviewed: number;
  true_positive: number;
  false_positive: number;
  inconclusive: number;
  false_positive_rate: number;
  by_tier: Record<string, Record<string, number>>;
}

export interface DefenderAgentEntityTimeline {
  entity_id: string;
  decisions: DefenderAgentDecision[];
  total: number;
}

export interface DefenderAgentMetrics {
  period_days: number;
  total_decisions: number;
  by_tier: Record<string, number>;
  daily_volumes: Array<{ date: string; count: number }>;
  top_entities: Array<{ id: string; name: string; type: string; count: number }>;
  top_alert_titles: Array<{ title: string; count: number }>;
  disposition_summary: Record<string, number>;
  false_positive_rate: number;
  top_actions: Array<{ action: string; count: number }>;
}

export interface DefenderAgentSummary {
  enabled: boolean;
  last_run_at: string | null;
  last_run_error: string;
  total_alerts_today: number;
  total_actions_today: number;
  pending_approvals: number;
  pending_tier2: number;
  recent_decisions: DefenderAgentDecision[];
}

export interface DefenderIndicator {
  id: string;
  indicatorValue: string;
  indicatorType: string;
  action: string;
  title: string;
  severity: string;
  createdBy?: string;
  creationTimeDateTimeUtc?: string;
  description?: string;
}

export type DefenderSuppressionType = "entity_user" | "entity_device" | "alert_title" | "alert_category";

export interface DefenderAgentSuppression {
  id: string;
  suppression_type: DefenderSuppressionType;
  value: string;
  reason: string;
  created_by: string;
  created_at: string;
  expires_at: string | null;
  active: boolean;
}

export interface DefenderAgentSuppressionsResponse {
  suppressions: DefenderAgentSuppression[];
  total: number;
}

export interface MailboxDelegateEntry {
  identity: string;
  display_name: string;
  principal_name: string;
  mail: string;
  permission_types: string[];
}

export interface MailboxDelegatesStatus {
  mailbox: string;
  display_name: string;
  principal_name: string;
  primary_address: string;
  provider_enabled: boolean;
  supported_permission_types: string[];
  permission_counts: Record<string, number>;
  note: string;
  delegate_count: number;
  delegates: MailboxDelegateEntry[];
}

export interface DelegateMailboxMatch {
  identity: string;
  display_name: string;
  principal_name: string;
  primary_address: string;
  permission_types: string[];
}

export interface DelegateMailboxesStatus {
  user: string;
  display_name: string;
  principal_name: string;
  primary_address: string;
  provider_enabled: boolean;
  supported_permission_types: string[];
  permission_counts: Record<string, number>;
  note: string;
  mailbox_count: number;
  scanned_mailbox_count: number;
  mailboxes: DelegateMailboxMatch[];
}

export interface DelegateMailboxJobRequest {
  user: string;
}

export interface DelegateMailboxJobStatus {
  job_id: string;
  site_scope: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  phase: "queued" | "resolving_user" | "scanning_send_on_behalf" | "scanning_exchange_permissions" | "merging_results" | "completed" | "failed" | "cancelled";
  requested_by_email: string;
  requested_by_name: string;
  user: string;
  display_name: string;
  principal_name: string;
  primary_address: string;
  provider_enabled: boolean;
  supported_permission_types: string[];
  permission_counts: Record<string, number>;
  note: string;
  mailbox_count: number;
  scanned_mailbox_count: number;
  mailboxes: DelegateMailboxMatch[];
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress_current: number;
  progress_total: number;
  progress_message: string;
  error: string | null;
  events: OneDriveCopyJobEvent[];
}

export interface EmailgisticsHelperRequest {
  user_mailbox: string;
  shared_mailbox: string;
}

export interface EmailgisticsHelperStep {
  key: "full_access" | "send_as" | "addin_group";
  label: string;
  status: "pending" | "completed" | "already_present" | "failed";
  message: string;
}

export interface EmailgisticsHelperStatus {
  status: "completed" | "failed";
  user_mailbox: string;
  shared_mailbox: string;
  resolved_user_display_name: string;
  resolved_user_principal_name: string;
  resolved_shared_display_name: string;
  resolved_shared_principal_name: string;
  addin_group_name: string;
  note: string;
  error: string;
  steps: EmailgisticsHelperStep[];
}

export interface DeactivateUserToolRequest {
  entra_user_id?: string;
  ad_sam?: string;
  display_name?: string;
}

export interface DeactivateUserToolStepResult {
  ok: boolean;
  message: string;
}

export interface DeactivateUserToolResult {
  display_name: string;
  entra: DeactivateUserToolStepResult | null;
  ad: DeactivateUserToolStepResult | null;
}

export interface OneDriveCopyJobStatus {
  job_id: string;
  site_scope: string;
  status: "queued" | "running" | "completed" | "failed";
  phase: "queued" | "resolving_drives" | "enumerating" | "creating_folders" | "dispatching_copy" | "completed" | "failed";
  requested_by_email: string;
  requested_by_name: string;
  source_upn: string;
  destination_upn: string;
  destination_folder: string;
  test_mode: boolean;
  test_file_limit: number;
  exclude_system_folders: boolean;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress_current: number;
  progress_total: number;
  progress_message: string;
  total_folders_found: number;
  total_files_found: number;
  folders_created: number;
  files_dispatched: number;
  files_failed: number;
  error: string | null;
  events: OneDriveCopyJobEvent[];
}

export interface AzureDirectoryExtra {
  user_type: string;
  department: string;
  job_title: string;
  office_location: string;
  company_name: string;
  city: string;
  country: string;
  mobile_phone: string;
  business_phones: string;
  created_datetime: string;
  on_prem_sync: string;
  on_prem_domain: string;
  on_prem_netbios: string;
  on_prem_sam_account_name: string;
  on_prem_distinguished_name: string;
  last_password_change: string;
  proxy_addresses: string;
  is_licensed: string;
  license_count: string;
  sku_part_numbers: string;
  last_interactive_utc: string;
  last_interactive_local: string;
  last_noninteractive_utc: string;
  last_noninteractive_local: string;
  last_successful_utc: string;
  last_successful_local: string;
  employee_type: string;
  account_class: string;
  priority_band: string;
  priority_score: string;
  priority_reason: string;
  missing_profile_fields: string;
  mailbox_type_hint: string;
  [key: string]: string;
}

export interface AzureDirectoryObject {
  id: string;
  display_name: string;
  object_type: "user" | "group" | "enterprise_app" | "app_registration" | "directory_role";
  principal_name: string;
  mail: string;
  app_id: string;
  enabled: boolean | null;
  extra: AzureDirectoryExtra;
}

export interface AzureQuickJumpResult {
  id: string;
  kind:
    | "page"
    | "vm"
    | "desktop"
    | "resource"
    | "user"
    | "group"
    | "enterprise_app"
    | "app_registration"
    | "directory_role";
  label: string;
  subtitle: string;
  route: string;
}

export interface AzureQuickJumpResponse {
  results: AzureQuickJumpResult[];
}

export type UserAdminActionType =
  | "disable_sign_in"
  | "enable_sign_in"
  | "reset_password"
  | "revoke_sessions"
  | "reset_mfa"
  | "unblock_sign_in"
  | "update_usage_location"
  | "update_profile"
  | "set_manager"
  | "add_group_membership"
  | "remove_group_membership"
  | "assign_license"
  | "remove_license"
  | "add_directory_role"
  | "remove_directory_role"
  | "mailbox_add_alias"
  | "mailbox_remove_alias"
  | "mailbox_set_forwarding"
  | "mailbox_clear_forwarding"
  | "mailbox_convert_type"
  | "mailbox_set_delegates"
  | "device_sync"
  | "device_retire"
  | "device_wipe"
  | "device_remote_lock"
  | "device_reassign_primary_user"
  | "exit_group_cleanup"
  | "exit_on_prem_deprovision"
  | "exit_remove_all_licenses"
  | "exit_manual_task_complete";

export interface UserAdminReference {
  id: string;
  display_name: string;
  principal_name: string;
  mail: string;
}

export interface UserAdminCapabilities {
  can_manage_users: boolean;
  enabled_providers: {
    entra: boolean;
    mailbox: boolean;
    device_management: boolean;
  };
  supported_actions: UserAdminActionType[];
  license_catalog: Array<{
    sku_id: string;
    sku_part_number: string;
    display_name: string;
  }>;
  group_catalog: UserAdminReference[];
  role_catalog: UserAdminReference[];
  conditional_access_exception_groups: UserAdminReference[];
}

export interface UserAdminUserDetail {
  id: string;
  display_name: string;
  principal_name: string;
  mail: string;
  enabled: boolean | null;
  user_type: string;
  department: string;
  job_title: string;
  office_location: string;
  company_name: string;
  city: string;
  country: string;
  mobile_phone: string;
  business_phones: string[];
  created_datetime: string;
  last_password_change: string;
  on_prem_sync: boolean;
  on_prem_domain: string;
  on_prem_netbios: string;
  on_prem_sam_account_name: string;
  on_prem_distinguished_name: string;
  usage_location: string;
  employee_id: string;
  employee_type: string;
  preferred_language: string;
  proxy_addresses: string[];
  is_licensed: boolean;
  license_count: number;
  sku_part_numbers: string[];
  last_interactive_utc: string;
  last_interactive_local: string;
  last_noninteractive_utc: string;
  last_noninteractive_local: string;
  last_successful_utc: string;
  last_successful_local: string;
  manager: UserAdminReference | null;
  source_directory: string;
}

export interface UserAdminGroupMembership {
  id: string;
  display_name: string;
  mail: string;
  security_enabled: boolean;
  group_types: string[];
  object_type: string;
}

export interface UserAdminLicense {
  sku_id: string;
  sku_part_number: string;
  display_name: string;
  state: string;
  disabled_plans: string[];
  assigned_by_group: boolean;
}

export interface UserAdminRole {
  id: string;
  display_name: string;
  description: string;
  assignment_type: string;
}

export interface UserAdminMailbox {
  primary_address: string;
  aliases: string[];
  forwarding_enabled: boolean;
  forwarding_address: string;
  mailbox_type: string;
  delegate_delivery_mode: string;
  delegates: UserAdminReference[];
  automatic_replies_status: string;
  provider_enabled: boolean;
  management_supported: boolean;
  note: string;
}

export interface UserAdminDevice {
  id: string;
  device_name: string;
  operating_system: string;
  operating_system_version: string;
  compliance_state: string;
  management_state: string;
  owner_type: string;
  enrollment_type: string;
  last_sync_date_time: string;
  azure_ad_device_id: string;
  primary_users: UserAdminReference[];
}

export interface UserAdminAuditEntry {
  audit_id: string;
  job_id: string;
  actor_email: string;
  actor_name: string;
  target_user_id: string;
  target_display_name: string;
  provider: "entra" | "mailbox" | "device_management" | "windows_agent" | "workflow";
  action_type: UserAdminActionType;
  params_summary: Record<string, unknown>;
  before_summary: Record<string, unknown>;
  after_summary: Record<string, unknown>;
  status: string;
  error: string;
  created_at: string;
}

export interface UserAdminJobRequest {
  action_type: UserAdminActionType;
  target_user_ids: string[];
  params: Record<string, unknown>;
}

export interface UserAdminJobStatus {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  action_type: UserAdminActionType;
  provider: "entra" | "mailbox" | "device_management" | "windows_agent" | "workflow";
  target_user_ids: string[];
  requested_by_email: string;
  requested_by_name: string;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress_current: number;
  progress_total: number;
  progress_message: string;
  success_count: number;
  failure_count: number;
  results_ready: boolean;
  error: string;
  one_time_results_available: boolean;
}

export interface UserAdminJobResult {
  target_user_id: string;
  target_display_name: string;
  provider: "entra" | "mailbox" | "device_management" | "windows_agent" | "workflow";
  success: boolean;
  summary: string;
  error: string;
  before_summary: Record<string, unknown>;
  after_summary: Record<string, unknown>;
  one_time_secret: string | null;
}

export interface AzureCostPoint {
  date: string;
  cost: number;
  actual_cost?: number;
  amortized_cost?: number;
  currency: string;
  source?: "exports" | "cache";
}

export type UserDirectoryReportFilter = "" | "disabled_licensed" | "active_no_success_30d";

export interface UserDirectoryExportParams {
  search?: string;
  status?: "all" | "enabled" | "disabled";
  type?: "all" | "member" | "guest";
  license?: "all" | "licensed";
  activity?: "all" | "no_success_30d";
  sync?: "all" | "on_prem_synced";
  directory?: string;
  report_filter?: UserDirectoryReportFilter;
  scope?: "filtered" | "all";
}

export type UserExitWorkflowStatus = "queued" | "running" | "awaiting_manual" | "completed" | "failed";
export type UserExitStepStatus = "queued" | "running" | "completed" | "failed" | "skipped";
export type UserExitStepProvider = "entra" | "windows_agent" | "workflow";

export interface UserExitWorkflowSummary {
  workflow_id: string;
  user_id: string;
  user_display_name: string;
  user_principal_name: string;
  status: UserExitWorkflowStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  profile_key: string;
  on_prem_required: boolean;
  requires_on_prem_username_override: boolean;
  error: string;
}

export interface UserExitPreflightStep {
  step_key: string;
  label: string;
  provider: UserExitStepProvider;
  will_run: boolean;
  reason: string;
}

export interface UserExitManualTask {
  task_id: string;
  label: string;
  status: "pending" | "completed";
  notes: string;
  completed_at: string | null;
  completed_by_email: string;
  completed_by_name: string;
}

export interface UserExitPreflight {
  user_id: string;
  user_display_name: string;
  user_principal_name: string;
  profile_key: string;
  profile_label: string;
  scope_summary: string;
  on_prem_required: boolean;
  requires_on_prem_username_override: boolean;
  on_prem_sam_account_name: string;
  on_prem_distinguished_name: string;
  mailbox_expected: boolean;
  direct_license_count: number;
  direct_licenses: UserAdminLicense[];
  managed_devices: UserAdminDevice[];
  manual_tasks: UserExitManualTask[];
  steps: UserExitPreflightStep[];
  warnings: string[];
  active_workflow: UserExitWorkflowSummary | null;
}

export interface UserExitWorkflowStep {
  step_id: string;
  step_key: string;
  label: string;
  provider: UserExitStepProvider;
  status: UserExitStepStatus;
  order_index: number;
  profile_key: string;
  summary: string;
  error: string;
  before_summary: Record<string, unknown>;
  after_summary: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  retry_count: number;
}

export interface UserExitWorkflow {
  workflow_id: string;
  user_id: string;
  user_display_name: string;
  user_principal_name: string;
  requested_by_email: string;
  requested_by_name: string;
  status: UserExitWorkflowStatus;
  profile_key: string;
  on_prem_required: boolean;
  requires_on_prem_username_override: boolean;
  on_prem_sam_account_name: string;
  on_prem_distinguished_name: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string;
  steps: UserExitWorkflowStep[];
  manual_tasks: UserExitManualTask[];
}

// ── Azure Alert types ─────────────────────────────────────────────────────────

export interface AzureAlertRule {
  id: string;
  name: string;
  domain: "cost" | "vms" | "identity" | "resources";
  trigger_type: string;
  trigger_config: Record<string, unknown>;
  frequency: "immediate" | "hourly" | "daily" | "weekly";
  schedule_time: string;
  schedule_days: string;
  recipients: string;
  teams_webhook_url: string;
  custom_subject: string;
  custom_message: string;
  enabled: boolean;
  last_run: string | null;
  last_sent: string | null;
  created_at: string;
  updated_at: string;
}

export interface AzureAlertRuleCreate {
  name: string;
  domain: AzureAlertRule["domain"];
  trigger_type: string;
  trigger_config: Record<string, unknown>;
  frequency: AzureAlertRule["frequency"];
  schedule_time: string;
  schedule_days: string;
  recipients: string;
  teams_webhook_url: string;
  custom_subject: string;
  custom_message: string;
}

export interface AzureAlertTestResponse {
  match_count: number;
  sample_items: Record<string, unknown>[];
}

export interface AzureAlertHistoryItem {
  id: string;
  rule_id: string;
  rule_name: string;
  trigger_type: string;
  sent_at: string;
  recipients: string;
  match_count: number;
  match_summary: Record<string, unknown>;
  status: "sent" | "partial" | "failed" | "dry_run";
  error: string | null;
}

export interface AzureChatParseResponse {
  parsed: boolean;
  rule: AzureAlertRuleCreate | null;
  summary: string;
  error: string;
}

export type AzureAlertTriggerSchema = Record<string, Record<string, Record<string, unknown>>>;

export interface AzureCostBreakdownItem {
  label: string;
  amount: number;
  actual_cost?: number;
  amortized_cost?: number;
  currency: string;
  share: number;
  source?: "exports" | "cache";
}

export interface AzureAdvisorRecommendation {
  id: string;
  category: string;
  impact: string;
  recommendation_type: string;
  title: string;
  description: string;
  subscription_id: string;
  subscription_name: string;
  resource_id: string;
  annual_savings: number;
  monthly_savings: number;
  currency: string;
}

export interface AzureSavingsEvidenceRow {
  label: string;
  value: string;
}

export interface AzureSavingsAggregateRow {
  label: string;
  count: number;
  estimated_monthly_savings: number;
}

export interface AzureSavingsOpportunity {
  id: string;
  category: "compute" | "storage" | "network" | "commitment" | "other";
  opportunity_type: string;
  source: "heuristic" | "advisor";
  title: string;
  summary: string;
  subscription_id: string;
  subscription_name: string;
  resource_group: string;
  location: string;
  resource_id: string;
  resource_name: string;
  resource_type: string;
  current_monthly_cost: number | null;
  estimated_monthly_savings: number | null;
  currency: string;
  quantified: boolean;
  estimate_basis: string;
  effort: "low" | "medium" | "high";
  risk: "low" | "medium" | "high";
  confidence: "low" | "medium" | "high";
  recommended_steps: string[];
  evidence: AzureSavingsEvidenceRow[];
  portal_url: string;
  follow_up_route: string;
  lifecycle_status?: "open" | "dismissed" | "accepted";
  action_state?: string;
  dismissed_reason?: string;
}

export interface AzureRecommendationActionEvent {
  event_id: string;
  recommendation_id: string;
  action_type: string;
  action_status: string;
  actor_type: string;
  actor_id: string;
  note: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface AzureRecommendationActionField {
  key: string;
  label: string;
  description: string;
  required: boolean;
}

export interface AzureRecommendationActionOption {
  key: string;
  label: string;
  description: string;
  default_dry_run: boolean;
  allow_apply: boolean;
  repeatable: boolean;
}

export interface AzureRecommendationActionContractItem {
  action_type: "create_ticket" | "send_alert" | "export" | "run_safe_script";
  label: string;
  description: string;
  category: "jira" | "teams" | "export" | "script";
  status: "available" | "pending" | "completed" | "blocked" | "future";
  can_execute: boolean;
  requires_admin: boolean;
  repeatable: boolean;
  pending_action_state: string;
  completed_action_state: string;
  current_action_state: string;
  blocked_reason: string;
  note_placeholder: string;
  metadata_fields: AzureRecommendationActionField[];
  options: AzureRecommendationActionOption[];
  latest_event: Record<string, unknown>;
}

export interface AzureRecommendationActionContract {
  recommendation_id: string;
  lifecycle_status: string;
  current_action_state: string;
  generated_at: string;
  actions: AzureRecommendationActionContractItem[];
}

export interface AzureRecommendationCreateTicketResponse {
  recommendation: AzureRecommendation;
  ticket_key: string;
  ticket_url: string;
  jira_issue_id: string;
  project_key: string;
  issue_type: string;
  summary: string;
}

export interface AzureRecommendationSendAlertResponse {
  recommendation: AzureRecommendation;
  alert_status: string;
  delivery_channel: string;
  sent_at: string;
}

export interface AzureRecommendationRunSafeScriptResponse {
  recommendation: AzureRecommendation;
  hook_key: string;
  hook_label: string;
  action_status: string;
  dry_run: boolean;
  started_at: string;
  completed_at: string;
  duration_ms: number;
  exit_code: number | null;
  output_excerpt: string;
}

export type AzureRecommendation = AzureSavingsOpportunity;

export interface AzureSavingsSummary {
  currency: string;
  total_opportunities: number;
  quantified_opportunities: number;
  quantified_monthly_savings: number;
  quick_win_count: number;
  quick_win_monthly_savings: number;
  unquantified_opportunity_count: number;
  by_category: AzureSavingsAggregateRow[];
  by_opportunity_type: AzureSavingsAggregateRow[];
  by_effort: AzureCountByLabel[];
  by_risk: AzureCountByLabel[];
  by_confidence: AzureCountByLabel[];
  top_subscriptions: AzureSavingsAggregateRow[];
  top_resource_groups: AzureSavingsAggregateRow[];
  source?: string;
  source_label?: string;
  source_description?: string;
  last_refreshed_at?: string | null;
  cost_context?: AzureCostContext;
}

export interface AzureComputeOptimizationSummary {
  total_vms: number;
  running_vms: number;
  idle_vms: number;
  total_running_cost: number | null;
  total_advisor_savings: number;
  ri_gap_count: number;
}

export interface AzureComputeOptimizationResponse {
  summary: AzureComputeOptimizationSummary;
  idle_vms: AzureVirtualMachineRow[];
  top_cost_vms: AzureVirtualMachineRow[];
  ri_coverage_gaps: AzureVirtualMachineSizeCoverageRow[];
  advisor_recommendations: AzureAdvisorRecommendation[];
  cost_available: boolean;
  reservation_data_available: boolean;
  cost_context?: AzureCostContext;
}

export interface AzureStorageAccount {
  id: string;
  name: string;
  kind: string;
  sku_name: string;
  access_tier: string;
  location: string;
  subscription_id: string;
  subscription_name: string;
  resource_group: string;
  state: string;
  created_time: string;
  tags: Record<string, string>;
  cost: number | null;
  currency: string;
}

export interface AzureManagedDisk {
  id: string;
  name: string;
  sku_name: string;
  disk_size_gb: number | null;
  disk_state: string;
  source_resource_id: string;
  disk_iops: number | null;
  location: string;
  subscription_id: string;
  subscription_name: string;
  resource_group: string;
  state: string;
  created_time: string;
  managed_by: string;
  tags: Record<string, string>;
  cost: number | null;
  currency: string;
}

export interface AzureStorageSummary {
  storage_accounts: AzureStorageAccount[];
  managed_disks: AzureManagedDisk[];
  snapshots: AzureManagedDisk[];
  summary: {
    total_storage_accounts: number;
    total_managed_disks: number;
    total_snapshots: number;
    unattached_disks: number;
    total_storage_cost: number | null;
    total_disk_gb: number;
    total_snapshot_gb: number;
    total_provisioned_gb: number;
    avg_cost_per_gb: number | null;
  };
  disk_by_sku: Record<string, number>;
  disk_by_state: Record<string, number>;
  accounts_by_kind: Record<string, number>;
  accounts_by_tier: Record<string, number>;
  storage_services_cost: Array<{ label: string; amount: number; currency: string }>;
  cost_available: boolean;
  cost_basis: string | null;
  cost_context?: AzureCostContext;
}

export interface AzureCitation {
  source_type: string;
  label: string;
  detail: string;
}

export interface AzureCostChatResponse {
  answer: string;
  model_used: string;
  generated_at: string;
  citations: AzureCitation[];
}

export type SecurityCopilotLane =
  | "identity_compromise"
  | "mailbox_abuse"
  | "app_or_service_principal"
  | "azure_alert_or_resource"
  | "dlp_finding"
  | "unknown";

export interface SecurityCopilotChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface SecurityCopilotIncident {
  lane: SecurityCopilotLane;
  summary: string;
  timeframe: string;
  affected_users: string[];
  affected_mailboxes: string[];
  affected_apps: string[];
  affected_resources: string[];
  alert_names: string[];
  observed_artifacts: string[];
  identity_query: string;
  identity_candidates: SecurityCopilotIdentityCandidate[];
  confidence: number;
  missing_fields: string[];
}

export interface SecurityCopilotIdentityCandidate {
  id: string;
  display_name: string;
  principal_name: string;
  mail: string;
  match_reason: string;
}

export interface SecurityCopilotFollowUpQuestion {
  key: string;
  label: string;
  prompt: string;
  placeholder: string;
  required: boolean;
  input_type: "text" | "textarea" | "email" | "list";
  choices: string[];
}

export interface SecurityCopilotPlannedSource {
  key: string;
  label: string;
  status: "planned" | "running" | "completed" | "skipped" | "error";
  query_summary: string;
  reason: string;
}

export interface SecurityCopilotSourceResult {
  key: string;
  label: string;
  status: "completed" | "running" | "skipped" | "error";
  query_summary: string;
  item_count: number;
  highlights: string[];
  preview: Record<string, unknown>[];
  citations: AzureCitation[];
  reason: string;
}

export interface SecurityCopilotJobRef {
  job_type: "delegate_mailbox_scan";
  label: string;
  job_id: string;
  status: string;
  phase: string;
  target: string;
  summary: string;
  started_automatically: boolean;
}

export interface SecurityCopilotAnswer {
  summary: string;
  findings: string[];
  next_steps: string[];
  warnings: string[];
}

export interface SecurityAccessReviewMetric {
  key: string;
  label: string;
  value: number;
  detail: string;
  tone: "slate" | "sky" | "emerald" | "amber" | "rose" | "violet";
}

export interface SecurityAccessReviewPrincipal {
  principal_id: string;
  principal_type: string;
  object_type: string;
  display_name: string;
  principal_name: string;
  enabled: boolean | null;
  user_type: string;
  last_successful_utc: string;
  role_names: string[];
  assignment_count: number;
  scope_count: number;
  highest_privilege: "critical" | "elevated" | "limited";
  flags: string[];
  subscriptions: string[];
}

export interface SecurityAccessReviewAssignment {
  assignment_id: string;
  principal_id: string;
  principal_type: string;
  object_type: string;
  display_name: string;
  principal_name: string;
  role_definition_id: string;
  role_name: string;
  privilege_level: "critical" | "elevated" | "limited";
  scope: string;
  subscription_id: string;
  subscription_name: string;
  enabled: boolean | null;
  user_type: string;
  last_successful_utc: string;
  flags: string[];
}

export interface SecurityAccessReviewBreakGlassCandidate {
  user_id: string;
  display_name: string;
  principal_name: string;
  enabled: boolean | null;
  last_successful_utc: string;
  matched_terms: string[];
  privileged_assignment_count: number;
  has_privileged_access: boolean;
  flags: string[];
}

export interface SecurityAccessReviewResponse {
  generated_at: string;
  inventory_last_refresh: string;
  directory_last_refresh: string;
  metrics: SecurityAccessReviewMetric[];
  flagged_principals: SecurityAccessReviewPrincipal[];
  assignments: SecurityAccessReviewAssignment[];
  break_glass_candidates: SecurityAccessReviewBreakGlassCandidate[];
  warnings: string[];
  scope_notes: string[];
}

export interface SecurityAppHygieneMetric {
  key: string;
  label: string;
  value: number;
  detail: string;
  tone: "slate" | "sky" | "emerald" | "amber" | "rose" | "violet";
}

export interface SecurityAppHygieneApp {
  application_id: string;
  app_id: string;
  display_name: string;
  sign_in_audience: string;
  created_datetime: string;
  publisher_domain: string;
  verified_publisher_name: string;
  owner_count: number;
  owners: string[];
  owner_lookup_error: string;
  credential_count: number;
  password_credential_count: number;
  key_credential_count: number;
  next_credential_expiry: string;
  expired_credential_count: number;
  expiring_30d_count: number;
  expiring_90d_count: number;
  status: "critical" | "warning" | "healthy" | "info";
  flags: string[];
}

export interface SecurityAppHygieneCredential {
  application_id: string;
  app_id: string;
  application_display_name: string;
  credential_type: "secret" | "certificate";
  display_name: string;
  key_id: string;
  start_date_time: string;
  end_date_time: string;
  days_until_expiry: number | null;
  status: "expired" | "expiring" | "active" | "unknown";
  owner_count: number;
  owners: string[];
  flags: string[];
}

export interface SecurityAppHygieneResponse {
  generated_at: string;
  directory_last_refresh: string;
  metrics: SecurityAppHygieneMetric[];
  flagged_apps: SecurityAppHygieneApp[];
  credentials: SecurityAppHygieneCredential[];
  warnings: string[];
  scope_notes: string[];
}

export interface SecurityBreakGlassValidationAccount {
  user_id: string;
  display_name: string;
  principal_name: string;
  enabled: boolean | null;
  user_type: string;
  account_class: string;
  matched_terms: string[];
  has_privileged_access: boolean;
  privileged_assignment_count: number;
  last_successful_utc: string;
  days_since_last_successful: number | null;
  last_password_change: string;
  days_since_password_change: number | null;
  is_licensed: boolean | null;
  license_count: number;
  on_prem_sync: boolean;
  mfa_enrolled: boolean | null;
  mfa_methods: string[];
  status: "critical" | "warning" | "healthy";
  flags: string[];
}

export interface SecurityBreakGlassValidationResponse {
  generated_at: string;
  inventory_last_refresh: string;
  directory_last_refresh: string;
  metrics: SecurityAccessReviewMetric[];
  accounts: SecurityBreakGlassValidationAccount[];
  warnings: string[];
  scope_notes: string[];
}

export interface SecurityDirectoryRoleReviewRole {
  role_id: string;
  display_name: string;
  description: string;
  privilege_level: "critical" | "elevated" | "limited";
  member_count: number;
  flagged_member_count: number;
  flags: string[];
}

export interface SecurityDirectoryRoleReviewMembership {
  role_id: string;
  role_name: string;
  role_description: string;
  privilege_level: "critical" | "elevated" | "limited";
  principal_id: string;
  principal_type: string;
  object_type: string;
  display_name: string;
  principal_name: string;
  enabled: boolean | null;
  user_type: string;
  last_successful_utc: string;
  assignment_type: string;
  status: "critical" | "warning" | "healthy";
  flags: string[];
}

export interface SecurityDirectoryRoleReviewResponse {
  generated_at: string;
  directory_last_refresh: string;
  access_available: boolean;
  access_message: string;
  metrics: SecurityAccessReviewMetric[];
  roles: SecurityDirectoryRoleReviewRole[];
  memberships: SecurityDirectoryRoleReviewMembership[];
  warnings: string[];
  scope_notes: string[];
}

export interface SecurityConditionalAccessPolicy {
  policy_id: string;
  display_name: string;
  state: string;
  created_date_time: string;
  modified_date_time: string;
  user_scope_summary: string;
  application_scope_summary: string;
  grant_controls: string[];
  session_controls: string[];
  impact_level: "critical" | "warning" | "healthy" | "info";
  risk_tags: string[];
}

export interface SecurityConditionalAccessChange {
  event_id: string;
  activity_date_time: string;
  activity_display_name: string;
  result: string;
  initiated_by_display_name: string;
  initiated_by_principal_name: string;
  initiated_by_type: "user" | "app" | "unknown";
  target_policy_id: string;
  target_policy_name: string;
  impact_level: "critical" | "warning" | "healthy" | "info";
  change_summary: string;
  modified_properties: string[];
  flags: string[];
}

export interface SecurityConditionalAccessTrackerResponse {
  generated_at: string;
  conditional_access_last_refresh: string;
  access_available: boolean;
  access_message: string;
  metrics: SecurityAccessReviewMetric[];
  policies: SecurityConditionalAccessPolicy[];
  changes: SecurityConditionalAccessChange[];
  warnings: string[];
  scope_notes: string[];
}

export interface SecurityWorkspaceLaneSummary {
  lane_key: string;
  status: "critical" | "warning" | "healthy" | "info" | "unavailable";
  attention_score: number;
  attention_count: number;
  attention_label: string;
  secondary_label: string;
  refresh_at: string;
  access_available: boolean;
  access_message: string;
  warning_count: number;
  summary_mode: "count" | "availability" | "manual";
}

export interface SecurityWorkspaceSummaryResponse {
  generated_at: string;
  workspace_last_refresh: string;
  lanes: SecurityWorkspaceLaneSummary[];
}

export type SecurityFindingExceptionScope = "directory_user";
export type SecurityFindingExceptionFindingKey =
  | "all-findings"
  | "priority-user"
  | "stale-signin"
  | "disabled-licensed"
  | "guest-user"
  | "on-prem-synced"
  | "shared-service";
export type SecurityFindingExceptionStatus = "active" | "restored";

export interface SecurityFindingException {
  exception_id: string;
  scope: SecurityFindingExceptionScope;
  finding_key: SecurityFindingExceptionFindingKey;
  finding_label: string;
  entity_id: string;
  entity_label: string;
  entity_subtitle: string;
  reason: string;
  status: SecurityFindingExceptionStatus;
  created_at: string;
  updated_at: string;
  created_by_email: string;
  created_by_name: string;
  updated_by_email: string;
  updated_by_name: string;
}

export interface SecurityFindingExceptionCreateRequest {
  scope: SecurityFindingExceptionScope;
  finding_key: SecurityFindingExceptionFindingKey;
  finding_label?: string;
  entity_id: string;
  entity_label?: string;
  entity_subtitle?: string;
  reason: string;
}

export type SecurityDeviceActionType =
  | "device_sync"
  | "device_remote_lock"
  | "device_retire"
  | "device_wipe"
  | "device_reassign_primary_user";

export interface SecurityDeviceComplianceDevice {
  id: string;
  device_name: string;
  operating_system: string;
  operating_system_version: string;
  compliance_state: string;
  management_state: string;
  owner_type: string;
  enrollment_type: string;
  last_sync_date_time: string;
  last_sync_age_days: number | null;
  azure_ad_device_id: string;
  primary_users: UserAdminReference[];
  risk_level: "critical" | "high" | "medium" | "low";
  finding_tags: string[];
  recommended_actions: string[];
  recommended_fix_action: SecurityDeviceActionType | null;
  recommended_fix_label: string;
  recommended_fix_reason: string;
  recommended_fix_requires_user_picker: boolean;
  action_ready: boolean;
  supported_actions: SecurityDeviceActionType[];
  action_blockers: string[];
}

export interface SecurityDeviceComplianceResponse {
  generated_at: string;
  device_last_refresh: string;
  access_available: boolean;
  access_message: string;
  metrics: SecurityAccessReviewMetric[];
  devices: SecurityDeviceComplianceDevice[];
  warnings: string[];
  scope_notes: string[];
}

export interface SecurityDeviceActionRequest {
  action_type: SecurityDeviceActionType;
  device_ids: string[];
  reason?: string;
  confirm_device_count?: number;
  confirm_device_names?: string[];
  params?: Record<string, unknown>;
}

export interface SecurityDeviceActionJob {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  action_type: SecurityDeviceActionType;
  device_ids: string[];
  device_names: string[];
  requested_by_email: string;
  requested_by_name: string;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress_current: number;
  progress_total: number;
  progress_message: string;
  success_count: number;
  failure_count: number;
  results_ready: boolean;
  reason: string;
  error: string;
}

export interface SecurityDeviceActionJobResult {
  device_id: string;
  device_name: string;
  azure_ad_device_id: string;
  success: boolean;
  summary: string;
  error: string;
  before_summary: Record<string, unknown>;
  after_summary: Record<string, unknown>;
}

export interface SecurityDeviceFixPlanRequest {
  device_ids: string[];
}

export interface SecurityDeviceFixPlanDevice {
  device_id: string;
  device_name: string;
  risk_level: "critical" | "high" | "medium" | "low";
  finding_tags: string[];
  action_type: SecurityDeviceActionType | null;
  action_label: string;
  action_reason: string;
  requires_primary_user: boolean;
  primary_users: UserAdminReference[];
  skip_reason: string;
}

export interface SecurityDeviceFixPlanGroup {
  action_type: SecurityDeviceActionType;
  action_label: string;
  device_count: number;
  device_ids: string[];
  device_names: string[];
  requires_confirmation: boolean;
}

export interface SecurityDeviceFixPlanResponse {
  generated_at: string;
  device_ids: string[];
  items: SecurityDeviceFixPlanDevice[];
  groups: SecurityDeviceFixPlanGroup[];
  devices_requiring_primary_user: SecurityDeviceFixPlanDevice[];
  skipped_devices: SecurityDeviceFixPlanDevice[];
  destructive_device_count: number;
  destructive_device_names: string[];
  requires_destructive_confirmation: boolean;
  warnings: string[];
}

export interface SecurityDeviceFixPlanExecuteRequest {
  device_ids: string[];
  reason?: string;
  assignment_map?: Record<string, string>;
  confirm_device_count?: number;
  confirm_device_names?: string[];
}

export interface SecurityDeviceActionBatchJob {
  child_job_id: string;
  action_type: SecurityDeviceActionType;
  action_label: string;
  device_ids: string[];
  device_names: string[];
  status: "queued" | "running" | "completed" | "failed";
  progress_current: number;
  progress_total: number;
  success_count: number;
  failure_count: number;
  results_ready: boolean;
}

export interface SecurityDeviceActionBatchStatus {
  batch_id: string;
  status: "queued" | "running" | "completed" | "failed";
  requested_by_email: string;
  requested_by_name: string;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress_current: number;
  progress_total: number;
  progress_message: string;
  success_count: number;
  failure_count: number;
  results_ready: boolean;
  item_count: number;
  destructive_device_count: number;
  destructive_device_names: string[];
  child_jobs: SecurityDeviceActionBatchJob[];
  error: string;
}

export interface SecurityDeviceActionBatchResult {
  device_id: string;
  device_name: string;
  action_type: SecurityDeviceActionType;
  action_label: string;
  child_job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  success: boolean | null;
  summary: string;
  error: string;
  assignment_user_id: string;
  assignment_user_display_name: string;
}

export interface SecurityCopilotChatRequest {
  message: string;
  history?: SecurityCopilotChatMessage[];
  incident?: SecurityCopilotIncident;
  jobs?: SecurityCopilotJobRef[];
  model?: string;
}

export interface SecurityCopilotChatResponse {
  phase: "needs_input" | "running_jobs" | "complete";
  assistant_message: string;
  incident: SecurityCopilotIncident;
  follow_up_questions: SecurityCopilotFollowUpQuestion[];
  planned_sources: SecurityCopilotPlannedSource[];
  source_results: SecurityCopilotSourceResult[];
  jobs: SecurityCopilotJobRef[];
  answer: SecurityCopilotAnswer;
  citations: AzureCitation[];
  model_used: string;
  generated_at: string;
}

export interface AzureAICostSummary {
  lookback_days: number;
  usage_record_count: number;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_tokens: number;
  estimated_cost: number;
  currency: string;
  top_model: string;
  top_feature: string;
  window_start: string;
  window_end: string;
}

export interface AzureAICostTrendPoint {
  date: string;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_tokens: number;
  estimated_cost: number;
  currency: string;
}

export interface AzureAICostBreakdownItem {
  label: string;
  request_count: number;
  estimated_tokens: number;
  estimated_cost: number;
  currency: string;
  share: number;
}

export type AzureAllocationDimension = "team" | "application" | "product";
export type AzureAllocationRuleType = "tag" | "regex" | "percentage" | "shared";
export type AzureAllocationBucketType = "direct" | "shared" | "fallback";

export interface AzureAllocationDimensionPolicy {
  dimension: AzureAllocationDimension;
  label: string;
  fallback_bucket: string;
  shared_bucket: string;
  description: string;
}

export interface AzureAllocationPolicy {
  version: number;
  target_dimensions: AzureAllocationDimensionPolicy[];
  shared_cost_posture: {
    mode: string;
    description: string;
  };
  supported_rule_types: AzureAllocationRuleType[];
  supported_match_fields: string[];
}

export interface AzureAllocationRule {
  rule_id: string;
  rule_version: number;
  name: string;
  description: string;
  rule_type: AzureAllocationRuleType;
  target_dimension: AzureAllocationDimension;
  priority: number;
  enabled: boolean;
  condition: Record<string, unknown>;
  allocation: Record<string, unknown>;
  created_by: string;
  created_at: string;
  superseded_at: string;
}

export interface AzureAllocationRunDimensionSummary {
  target_dimension: AzureAllocationDimension;
  source_record_count: number;
  source_actual_cost: number;
  source_amortized_cost: number;
  source_usage_quantity: number;
  direct_allocated_actual_cost: number;
  direct_allocated_amortized_cost: number;
  direct_allocated_usage_quantity: number;
  residual_actual_cost: number;
  residual_amortized_cost: number;
  residual_usage_quantity: number;
  total_allocated_actual_cost: number;
  total_allocated_amortized_cost: number;
  total_allocated_usage_quantity: number;
  coverage_pct: number;
  created_at: string;
}

export interface AzureAllocationRunRuleVersion {
  rule_id: string;
  rule_version: number;
  target_dimension: AzureAllocationDimension;
  rule_type: AzureAllocationRuleType;
  priority: number;
  snapshot: AzureAllocationRule;
}

export interface AzureAllocationRun {
  run_id: string;
  run_label: string;
  trigger_type: string;
  triggered_by: string;
  note: string;
  status: string;
  target_dimensions: AzureAllocationDimension[];
  policy_version: number;
  source_record_count: number;
  created_at: string;
  completed_at: string;
  dimensions: AzureAllocationRunDimensionSummary[];
  rule_versions?: AzureAllocationRunRuleVersion[];
}

export interface AzureAllocationStatus {
  available: boolean;
  policy: AzureAllocationPolicy;
  rule_version_count: number;
  active_rule_count: number;
  inactive_rule_count: number;
  run_count: number;
  last_run_at: string;
  latest_run: AzureAllocationRun | null;
}

export interface AzureAllocationResult {
  allocation_value: string;
  bucket_type: AzureAllocationBucketType;
  allocation_method: string;
  source_record_count: number;
  allocated_actual_cost: number;
  allocated_amortized_cost: number;
  allocated_usage_quantity: number;
}

export interface AzureAllocationRunRequest {
  target_dimensions?: AzureAllocationDimension[];
  run_label?: string;
  note?: string;
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
  libra_support?: LibraSupportFilterMode;
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
  libra_support?: LibraSupportFilterMode;
}

export interface SLAMetricsQueryParams extends MetricsQueryParams {
  search?: string;
}

export interface TriageLogQueryParams {
  search?: string;
}

export interface TechnicianScoreQueryParams {
  search?: string;
  key?: string;
}

export interface AzureResourceQueryParams {
  search?: string;
  subscription_id?: string;
  resource_group?: string;
  resource_type?: string;
  location?: string;
  state?: string;
  tag_key?: string;
  tag_value?: string;
}

export interface AzureVirtualMachineQueryParams {
  search?: string;
  subscription_id?: string;
  resource_group?: string;
  location?: string;
  state?: string;
  size?: string;
}

export interface AzureVirtualDesktopRemovalQueryParams {
  search?: string;
  removal_only?: boolean;
  under_utilized_only?: boolean;
  over_utilized_only?: boolean;
}

export interface AzureSavingsQueryParams {
  search?: string;
  category?: string;
  opportunity_type?: string;
  subscription_id?: string;
  resource_group?: string;
  effort?: string;
  risk?: string;
  confidence?: string;
  quantified_only?: boolean;
}

export interface AzureStorageQueryParams {
  account_search?: string;
  disk_search?: string;
  snapshot_search?: string;
  disk_unattached_only?: boolean;
}

export interface AzureComputeOptimizationQueryParams {
  idle_vm_search?: string;
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
    } catch (err) {
      if (!(err instanceof Error && err.message === "Not authenticated")) {
        logClientError("Auth bootstrap failed", err, { url: "/api/auth/me" });
      }
      return null;
    }
  },

  getAtlassianConnectUrl(returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`): string {
    return `/api/auth/atlassian/connect?return_to=${encodeURIComponent(returnTo)}`;
  },

  getAtlassianStatus(): Promise<JiraAuthStatus> {
    return fetchJSON<JiraAuthStatus>("/api/auth/atlassian/status");
  },

  disconnectAtlassian(): Promise<{ disconnected: boolean }> {
    return postJSON<{ disconnected: boolean }>("/api/auth/atlassian/disconnect", {});
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
  getFilterOptions(): Promise<TicketFilterOptions> {
    return fetchJSON<TicketFilterOptions>("/api/filter-options");
  },

  /** Fetch a single ticket by its Jira key with full detail payload. */
  getTicket(key: string): Promise<TicketDetail> {
    return fetchJSON<TicketDetail>(`/api/tickets/${encodeURIComponent(key)}`);
  },

  /** Fetch the editable Jira component names for a single ticket. */
  getTicketComponents(key: string): Promise<string[]> {
    return fetchJSON<string[]>(`/api/tickets/${encodeURIComponent(key)}/components`);
  },

  /** Refresh the currently displayed ticket rows from live Jira data. */
  refreshVisibleTickets(keys: string[]): Promise<VisibleTicketRefreshResponse> {
    return postJSON<VisibleTicketRefreshResponse>("/api/tickets/refresh-visible", { keys });
  },

  /** Update a ticket reporter from the OCC creator line in the saved description. */
  syncTicketReporter(key: string): Promise<SyncTicketReporterResponse> {
    return postJSON<SyncTicketReporterResponse>(`/api/tickets/${encodeURIComponent(key)}/sync-reporter`, {});
  },

  /** Reconcile a ticket requestor against the Office 365 mirror and Jira customers. */
  syncTicketRequestor(key: string): Promise<SyncTicketReporterResponse> {
    return postJSON<SyncTicketReporterResponse>(`/api/tickets/${encodeURIComponent(key)}/sync-requestor`, {});
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

  /** Fetch computed SLA metrics with optional date range and search filters. */
  getSLAMetrics(params: SLAMetricsQueryParams = {}): Promise<SLAMetricsResponse> {
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

  /** Fetch all active Jira users assignable to the project. */
  getUsers(): Promise<Assignee[]> {
    return fetchJSON<Assignee[]>("/api/users");
  },

  /** Search Jira users by name or email for reporter changes. */
  searchUsers(query: string): Promise<Assignee[]> {
    return fetchJSON<Assignee[]>(`/api/users/search${buildQuery({ q: query })}`);
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

  createTicket(payload: TicketCreatePayload): Promise<TicketCreateResponse> {
    return postJSON<TicketCreateResponse>("/api/tickets", payload);
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

  fetchAttachmentPreviewBlob(url: string): Promise<Blob> {
    return fetchBlob(url);
  },

  fetchAttachmentPreviewText(url: string): Promise<string> {
    return fetchText(url);
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
  async exportReport(config: ReportConfig, templateId?: string | null): Promise<void> {
    await downloadPost(`/api/report/export${buildQuery({ template_id: templateId || undefined })}`, config, "OIT_Report_Windows.xlsx");
  },

  async exportMasterReportWorkbook(): Promise<void> {
    await downloadGet("/api/report/templates/master.xlsx", "OIT_Master_Report.xlsx", {
      timeoutMs: 120_000,
      timeoutMessage:
        "Master workbook export timed out after 120 seconds. The backend may be restarting or the export may have stalled. Please try again.",
    });
  },

  listReportTemplates(): Promise<ReportTemplate[]> {
    return fetchJSON<ReportTemplate[]>("/api/report/templates");
  },

  listReportTemplateInsights(): Promise<ReportTemplateInsight[]> {
    return fetchJSON<ReportTemplateInsight[]>("/api/report/templates/insights");
  },

  listReportAISummaries(): Promise<ReportAISummary[]> {
    return fetchJSON<ReportAISummary[]>("/api/report/templates/ai-summaries");
  },

  generateReportAISummaries(): Promise<ReportAISummaryBatchStartResponse> {
    return postJSON<ReportAISummaryBatchStartResponse>("/api/report/templates/ai-summaries/generate", {});
  },

  getReportAISummaryBatch(batchId: string): Promise<ReportAISummaryBatchStatus> {
    return fetchJSON<ReportAISummaryBatchStatus>(`/api/report/templates/ai-summaries/batches/${encodeURIComponent(batchId)}`);
  },

  createReportTemplate(body: ReportTemplateSaveRequest): Promise<ReportTemplate> {
    return postJSON<ReportTemplate>("/api/report/templates", body);
  },

  updateReportTemplate(templateId: string, body: ReportTemplateSaveRequest): Promise<ReportTemplate> {
    return putJSON<ReportTemplate>(`/api/report/templates/${encodeURIComponent(templateId)}`, body);
  },

  async deleteReportTemplate(templateId: string): Promise<void> {
    await deleteJSON(`/api/report/templates/${encodeURIComponent(templateId)}`);
  },

  updateReportTemplateExportSelection(templateId: string, includeInMasterExport: boolean): Promise<ReportTemplate> {
    return postJSON<ReportTemplate>(
      `/api/report/templates/${encodeURIComponent(templateId)}/export-selection`,
      { include_in_master_export: includeInMasterExport },
    );
  },

  previewOasisDevWorkloadReport(
    request: OasisDevWorkloadReportRequest,
  ): Promise<OasisDevWorkloadReportResponse> {
    return postJSON<OasisDevWorkloadReportResponse>("/api/report/oasisdev-workload", request);
  },

  async exportOasisDevWorkloadReport(request: OasisDevWorkloadReportRequest): Promise<void> {
    await downloadPost(
      "/api/report/oasisdev-workload/export",
      request,
      "OasisDev_Workload_Report.xlsx",
    );
  },

  /** Fetch current cache status. */
  getCacheStatus(): Promise<CacheStatus> {
    return fetchJSON<CacheStatus>("/api/cache/status");
  },

  /** Fetch Azure portal cache status. */
  getAzureStatus(): Promise<AzureStatus> {
    return fetchJSON<AzureStatus>("/api/azure/status");
  },

  /** Trigger an admin-only Azure cache refresh. */
  refreshAzure(): Promise<AzureStatus> {
    return postJSON<AzureStatus>("/api/azure/refresh", {});
  },

  /** Fetch Azure overview metrics. */
  getAzureOverview(): Promise<AzureOverviewResponse> {
    return fetchJSON<AzureOverviewResponse>("/api/azure/overview");
  },

  getAzureFinopsValidation(): Promise<AzureFinopsValidationReport> {
    return fetchJSON<AzureFinopsValidationReport>("/api/azure/finops/validation");
  },

  getAzureSubscriptions(): Promise<AzureSubscription[]> {
    return fetchJSON<AzureSubscription[]>("/api/azure/subscriptions");
  },

  getAzureManagementGroups(): Promise<AzureManagementGroup[]> {
    return fetchJSON<AzureManagementGroup[]>("/api/azure/management-groups");
  },

  getAzureRoleAssignments(search = "", subscriptionId = ""): Promise<AzureRoleAssignment[]> {
    return fetchJSON<AzureRoleAssignment[]>(
      `/api/azure/role-assignments${buildQuery({ search, subscription_id: subscriptionId })}`,
    );
  },

  getAzureResources(params: AzureResourceQueryParams = {}): Promise<AzureResourceListResponse> {
    return fetchJSON<AzureResourceListResponse>(`/api/azure/resources${buildQuery(params)}`);
  },

  getAzureVMs(params: AzureVirtualMachineQueryParams = {}): Promise<AzureVirtualMachineListResponse> {
    return fetchJSON<AzureVirtualMachineListResponse>(`/api/azure/vms${buildQuery(params)}`);
  },

  getAzureQuickJump(search: string): Promise<AzureQuickJumpResponse> {
    return fetchJSON<AzureQuickJumpResponse>(`/api/azure/search${buildQuery({ search })}`);
  },

  getAzureVirtualDesktopRemovalCandidates(
    params: AzureVirtualDesktopRemovalQueryParams = {},
  ): Promise<AzureVirtualDesktopRemovalResponse> {
    return fetchJSON<AzureVirtualDesktopRemovalResponse>(
      `/api/azure/virtual-desktops/removal-candidates${buildQuery(params)}`,
    );
  },

  getAzureVirtualDesktopDetail(resource_id: string): Promise<AzureVirtualDesktopDetailResponse> {
    return fetchJSON<AzureVirtualDesktopDetailResponse>(
      `/api/azure/virtual-desktops/detail${buildQuery({ resource_id })}`,
    );
  },

  getAzureVMDetail(resource_id: string): Promise<AzureVirtualMachineDetailResponse> {
    return fetchJSON<AzureVirtualMachineDetailResponse>(`/api/azure/vms/detail${buildQuery({ resource_id })}`);
  },

  createAzureVMCostExportJob(
    body: AzureVirtualMachineCostExportJobRequest,
  ): Promise<AzureVirtualMachineCostExportJobStatus> {
    return postJSON<AzureVirtualMachineCostExportJobStatus>("/api/azure/vms/cost-export-jobs", body);
  },

  getAzureVMCostExportJob(job_id: string): Promise<AzureVirtualMachineCostExportJobStatus> {
    return fetchJSON<AzureVirtualMachineCostExportJobStatus>(`/api/azure/vms/cost-export-jobs/${encodeURIComponent(job_id)}`);
  },

  downloadAzureVMCostExportJob(job_id: string): string {
    return `/api/azure/vms/cost-export-jobs/${encodeURIComponent(job_id)}/download`;
  },

  exportAzureVMCoverageCsv(): string {
    return "/api/azure/vms/coverage/export.csv";
  },

  exportAzureVMCoverageExcel(): string {
    return "/api/azure/vms/coverage/export.xlsx";
  },

  exportAzureVMExcessCsv(): string {
    return "/api/azure/vms/excess/export.csv";
  },

  exportAzureVMExcessExcel(): string {
    return "/api/azure/vms/excess/export.xlsx";
  },

  getAzureUsers(search = ""): Promise<AzureDirectoryObject[]> {
    return fetchJSON<AzureDirectoryObject[]>(`/api/azure/directory/users${buildQuery({ search })}`);
  },

  searchOneDriveCopyUsers(search = "", limit = 20): Promise<OneDriveCopyUserOption[]> {
    return fetchJSON<OneDriveCopyUserOption[]>(
      `/api/tools/onedrive-copy/users${buildQuery({ search, limit })}`,
    );
  },

  createOneDriveCopyJob(body: OneDriveCopyJobRequest): Promise<OneDriveCopyJobStatus> {
    return postJSON<OneDriveCopyJobStatus>("/api/tools/onedrive-copy/jobs", body);
  },

  listOneDriveCopyJobs(limit = 100): Promise<OneDriveCopyJobStatus[]> {
    return fetchJSON<OneDriveCopyJobStatus[]>(`/api/tools/onedrive-copy/jobs${buildQuery({ limit })}`);
  },

  clearFinishedOneDriveCopyJobs(): Promise<{ deleted_count: number }> {
    return postJSON<{ deleted_count: number }>("/api/tools/onedrive-copy/jobs/clear-finished", {});
  },

  getOneDriveCopyJob(job_id: string): Promise<OneDriveCopyJobStatus> {
    return fetchJSON<OneDriveCopyJobStatus>(`/api/tools/onedrive-copy/jobs/${encodeURIComponent(job_id)}`);
  },

  listLoginAudit(limit = 100): Promise<AppLoginAuditEvent[]> {
    return fetchJSON<AppLoginAuditEvent[]>(`/api/tools/onedrive-copy/login-audit${buildQuery({ limit })}`);
  },

  listMailboxRules(mailbox: string): Promise<MailboxRulesStatus> {
    return fetchJSON<MailboxRulesStatus>(`/api/tools/mailbox-rules${buildQuery({ mailbox })}`);
  },

  getAutoReply(mailbox: string): Promise<AutoReplyStatus> {
    return fetchJSON<AutoReplyStatus>(`/api/tools/auto-reply${buildQuery({ mailbox })}`);
  },

  setAutoReply(body: SetAutoReplyRequest): Promise<AutoReplyStatus> {
    return putJSON<AutoReplyStatus>("/api/tools/auto-reply", body);
  },

  // Defender autonomous agent
  getDefenderAgentConfig(): Promise<DefenderAgentConfig> {
    return fetchJSON<DefenderAgentConfig>("/api/azure/security/defender-agent/config");
  },
  updateDefenderAgentConfig(body: Partial<DefenderAgentConfig>): Promise<DefenderAgentConfig> {
    return putJSON<DefenderAgentConfig>("/api/azure/security/defender-agent/config", body);
  },
  listDefenderAgentRuns(limit = 20): Promise<DefenderAgentRun[]> {
    return fetchJSON<DefenderAgentRun[]>(`/api/azure/security/defender-agent/runs?limit=${limit}`);
  },
  listDefenderAgentDecisions(params?: { limit?: number; offset?: number }): Promise<DefenderAgentDecisionsResponse> {
    return fetchJSON<DefenderAgentDecisionsResponse>(
      `/api/azure/security/defender-agent/decisions${buildQuery({ limit: params?.limit ?? 100, offset: params?.offset ?? 0 })}`
    );
  },
  getDefenderAgentDecision(decisionId: string): Promise<DefenderAgentDecision> {
    return fetchJSON<DefenderAgentDecision>(`/api/azure/security/defender-agent/decisions/${decisionId}`);
  },
  getDefenderAgentSummary(): Promise<DefenderAgentSummary> {
    return fetchJSON<DefenderAgentSummary>("/api/azure/security/defender-agent/summary");
  },
  cancelDefenderAgentDecision(decisionId: string): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(`/api/azure/security/defender-agent/decisions/${decisionId}/cancel`, {});
  },
  approveDefenderAgentDecision(decisionId: string): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(`/api/azure/security/defender-agent/decisions/${decisionId}/approve`, {});
  },
  resolveDefenderAgentDecision(decisionId: string): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(`/api/azure/security/defender-agent/decisions/${decisionId}/resolve`, {});
  },
  unisolateDefenderAgentDecision(decisionId: string): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(`/api/azure/security/defender-agent/decisions/${decisionId}/unisolate`, {});
  },
  unrestrictDefenderAgentDecision(decisionId: string): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(`/api/azure/security/defender-agent/decisions/${decisionId}/unrestrict`, {});
  },
  forceInvestigateDecision(decisionId: string): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(`/api/azure/security/defender-agent/decisions/${decisionId}/force-investigate`, {});
  },
  executeDecisionNow(decisionId: string): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(`/api/azure/security/defender-agent/decisions/${decisionId}/execute-now`, {});
  },
  enableSignInDecision(decisionId: string): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(`/api/azure/security/defender-agent/decisions/${decisionId}/enable-sign-in`, {});
  },
  setDefenderAgentDisposition(
    decisionId: string,
    disposition: "true_positive" | "false_positive" | "inconclusive",
    note = ""
  ): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(
      `/api/azure/security/defender-agent/decisions/${decisionId}/disposition`,
      { disposition, note }
    );
  },
  getDefenderAgentDispositionStats(): Promise<DefenderAgentDispositionStats> {
    return fetchJSON<DefenderAgentDispositionStats>("/api/azure/security/defender-agent/disposition-stats");
  },
  getEntityTimeline(entityId: string, limit = 100): Promise<DefenderAgentEntityTimeline> {
    return fetchJSON<DefenderAgentEntityTimeline>(
      `/api/azure/security/defender-agent/entities/${encodeURIComponent(entityId)}/timeline?limit=${limit}`
    );
  },
  getDefenderAgentMetrics(days = 30): Promise<DefenderAgentMetrics> {
    return fetchJSON<DefenderAgentMetrics>(`/api/azure/security/defender-agent/metrics?days=${days}`);
  },
  addDecisionNote(decisionId: string, text: string): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(
      `/api/azure/security/defender-agent/decisions/${decisionId}/notes`,
      { text }
    );
  },
  generateDefenderNarrative(decisionId: string): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(
      `/api/azure/security/defender-agent/decisions/${decisionId}/narrative`,
      {}
    );
  },
  getSecurityRuntimeConfig(): Promise<Record<string, string>> {
    return fetchJSON<Record<string, string>>("/api/azure/security/runtime-config");
  },
  setSecurityRuntimeConfig(config: Record<string, string>): Promise<Record<string, string>> {
    return fetch("/api/azure/security/runtime-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }).then(async res => {
      if (res.status === 401) { window.location.href = "/api/auth/login"; throw new Error("Not authenticated"); }
      if (!res.ok) throw new Error(await res.text());
      return res.json() as Promise<Record<string, string>>;
    });
  },
  getLaneSummaries(): Promise<SecurityLaneAISummary[]> {
    return fetchJSON<SecurityLaneAISummary[]>("/api/azure/security/lane-summaries");
  },
  regenerateLaneSummary(laneKey: string): Promise<{ status: string; lane_key: string }> {
    return postJSON(`/api/azure/security/lane-summaries/${laneKey}/regenerate`, {});
  },
  listWatchlist(includeInactive = false): Promise<{ entries: DefenderAgentWatchlistEntry[]; total: number }> {
    return fetchJSON(`/api/azure/security/defender-agent/watchlist?include_inactive=${includeInactive}`);
  },
  addWatchlistEntry(entry: { entity_type: string; entity_id: string; entity_name?: string; reason?: string; boost_tier?: boolean }): Promise<DefenderAgentWatchlistEntry> {
    return postJSON("/api/azure/security/defender-agent/watchlist", entry);
  },
  removeWatchlistEntry(entryId: string): Promise<void> {
    return fetch(`/api/azure/security/defender-agent/watchlist/${encodeURIComponent(entryId)}`, { method: "DELETE" }).then(async res => {
      if (res.status === 401) { window.location.href = "/api/auth/login"; throw new Error("Not authenticated"); }
      if (!res.ok) { const t = await res.text(); throw new Error(t || `HTTP ${res.status}`); }
    });
  },
  listDefenderIndicators(): Promise<{ indicators: DefenderIndicator[]; total: number }> {
    return fetchJSON<{ indicators: DefenderIndicator[]; total: number }>(
      "/api/azure/security/defender-agent/indicators"
    );
  },
  deleteDefenderIndicator(indicatorId: string): Promise<{ deleted: boolean; indicator_id: string }> {
    const url = `/api/azure/security/defender-agent/indicators/${encodeURIComponent(indicatorId)}`;
    return fetch(url, { method: "DELETE" }).then(async res => {
      if (res.status === 401) { window.location.href = "/api/auth/login"; throw new Error("Not authenticated"); }
      if (!res.ok) throw new Error(`DELETE ${url} failed: ${res.status}`);
      return res.json() as Promise<{ deleted: boolean; indicator_id: string }>;
    });
  },
  listDefenderAgentSuppressions(): Promise<DefenderAgentSuppressionsResponse> {
    return fetchJSON<DefenderAgentSuppressionsResponse>("/api/azure/security/defender-agent/suppressions");
  },
  createDefenderAgentSuppression(body: {
    suppression_type: DefenderSuppressionType;
    value: string;
    reason?: string;
    expires_at?: string | null;
  }): Promise<DefenderAgentSuppression> {
    return postJSON<DefenderAgentSuppression>("/api/azure/security/defender-agent/suppressions", body);
  },
  deleteDefenderAgentSuppression(suppressionId: string): Promise<DefenderAgentSuppression> {
    const url = `/api/azure/security/defender-agent/suppressions/${encodeURIComponent(suppressionId)}`;
    return fetch(url, { method: "DELETE" }).then(async res => {
      if (res.status === 401) { window.location.href = "/api/auth/login"; throw new Error("Not authenticated"); }
      if (!res.ok) throw new Error(`DELETE ${url} failed: ${res.status}`);
      return res.json() as Promise<DefenderAgentSuppression>;
    });
  },
  runDefenderAgentNow(): Promise<{ run_id: string; started: boolean }> {
    return postJSON<{ run_id: string; started: boolean }>("/api/azure/security/defender-agent/run-now", {});
  },
  listDefenderAgentBuiltinRules(): Promise<DefenderAgentBuiltinRule[]> {
    return fetchJSON<DefenderAgentBuiltinRule[]>("/api/azure/security/defender-agent/rules");
  },
  updateDefenderAgentRule(ruleId: string, body: { disabled: boolean; confidence_score?: number | null }): Promise<DefenderAgentBuiltinRule> {
    return putJSON<DefenderAgentBuiltinRule>(`/api/azure/security/defender-agent/rules/${encodeURIComponent(ruleId)}`, body);
  },
  listDefenderAgentCustomRules(enabledOnly = false): Promise<DefenderAgentCustomRule[]> {
    return fetchJSON<DefenderAgentCustomRule[]>(`/api/azure/security/defender-agent/custom-rules?enabled_only=${enabledOnly}`);
  },
  createDefenderAgentCustomRule(body: Omit<DefenderAgentCustomRule, "id" | "enabled" | "created_by" | "created_at" | "playbook_name">): Promise<DefenderAgentCustomRule> {
    return postJSON<DefenderAgentCustomRule>("/api/azure/security/defender-agent/custom-rules", body);
  },
  listDefenderAgentPlaybooks(): Promise<DefenderAgentPlaybook[]> {
    return fetchJSON<DefenderAgentPlaybook[]>("/api/azure/security/defender-agent/playbooks");
  },
  createDefenderAgentPlaybook(body: { name: string; description: string; actions: string[] }): Promise<DefenderAgentPlaybook> {
    return postJSON<DefenderAgentPlaybook>("/api/azure/security/defender-agent/playbooks", body);
  },
  updateDefenderAgentPlaybook(playbookId: string, body: { name?: string; description?: string; actions?: string[]; enabled?: boolean }): Promise<DefenderAgentPlaybook> {
    return putJSON<DefenderAgentPlaybook>(`/api/azure/security/defender-agent/playbooks/${encodeURIComponent(playbookId)}`, body);
  },
  deleteDefenderAgentPlaybook(playbookId: string): Promise<{ deleted: boolean; id: string }> {
    const url = `/api/azure/security/defender-agent/playbooks/${encodeURIComponent(playbookId)}`;
    return fetch(url, { method: "DELETE" }).then(async res => {
      if (res.status === 401) { window.location.href = "/api/auth/login"; throw new Error("Not authenticated"); }
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error((e as { detail?: string }).detail || `DELETE ${url} failed: ${res.status}`); }
      return res.json() as Promise<{ deleted: boolean; id: string }>;
    });
  },
  listPlaybookRules(playbookId: string): Promise<DefenderAgentCustomRule[]> {
    return fetchJSON<DefenderAgentCustomRule[]>(`/api/azure/security/defender-agent/playbooks/${encodeURIComponent(playbookId)}/rules`);
  },
  deleteDefenderAgentCustomRule(ruleId: string): Promise<{ deleted: boolean; id: string }> {
    const url = `/api/azure/security/defender-agent/custom-rules/${encodeURIComponent(ruleId)}`;
    return fetch(url, { method: "DELETE" }).then(async res => {
      if (res.status === 401) { window.location.href = "/api/auth/login"; throw new Error("Not authenticated"); }
      if (!res.ok) throw new Error(`DELETE ${url} failed: ${res.status}`);
      return res.json() as Promise<{ deleted: boolean; id: string }>;
    });
  },
  toggleDefenderAgentCustomRule(ruleId: string, enabled: boolean): Promise<DefenderAgentCustomRule> {
    return putJSON<DefenderAgentCustomRule>(`/api/azure/security/defender-agent/custom-rules/${encodeURIComponent(ruleId)}/toggle?enabled=${enabled}`, {});
  },
  updateDefenderAgentCustomRule(ruleId: string, body: Partial<Omit<DefenderAgentCustomRule, "id" | "enabled" | "created_by" | "created_at" | "playbook_name">>): Promise<DefenderAgentCustomRule> {
    return putJSON<DefenderAgentCustomRule>(`/api/azure/security/defender-agent/custom-rules/${encodeURIComponent(ruleId)}`, body);
  },
  listDefenderAgentKnownTags(): Promise<{ tags: string[] }> {
    return fetchJSON<{ tags: string[] }>("/api/azure/security/defender-agent/tags");
  },
  addDecisionTag(decisionId: string, tag: string): Promise<DefenderAgentDecision> {
    return postJSON<DefenderAgentDecision>(`/api/azure/security/defender-agent/decisions/${encodeURIComponent(decisionId)}/tags/${encodeURIComponent(tag)}`, {});
  },
  removeDecisionTag(decisionId: string, tag: string): Promise<DefenderAgentDecision> {
    const url = `/api/azure/security/defender-agent/decisions/${encodeURIComponent(decisionId)}/tags/${encodeURIComponent(tag)}`;
    return fetch(url, { method: "DELETE" }).then(async res => {
      if (res.status === 401) { window.location.href = "/api/auth/login"; throw new Error("Not authenticated"); }
      if (!res.ok) throw new Error(`DELETE ${url} failed: ${res.status}`);
      return res.json() as Promise<DefenderAgentDecision>;
    });
  },
  exportDefenderAgentDecisions(days = 30): string {
    return `/api/azure/security/defender-agent/decisions/export?days=${days}`;
  },

  listMailboxDelegates(mailbox: string): Promise<MailboxDelegatesStatus> {
    return fetchJSON<MailboxDelegatesStatus>(`/api/tools/mailbox-delegates${buildQuery({ mailbox })}`);
  },

  listDelegateMailboxes(user: string): Promise<DelegateMailboxesStatus> {
    return fetchJSON<DelegateMailboxesStatus>(`/api/tools/delegate-mailboxes${buildQuery({ user })}`);
  },

  createDelegateMailboxJob(body: DelegateMailboxJobRequest): Promise<DelegateMailboxJobStatus> {
    return postJSON<DelegateMailboxJobStatus>("/api/tools/delegate-mailboxes/jobs", body);
  },

  listDelegateMailboxJobs(limit = 20): Promise<DelegateMailboxJobStatus[]> {
    return fetchJSON<DelegateMailboxJobStatus[]>(`/api/tools/delegate-mailboxes/jobs${buildQuery({ limit })}`);
  },

  clearFinishedDelegateMailboxJobs(): Promise<{ deleted_count: number }> {
    return postJSON<{ deleted_count: number }>("/api/tools/delegate-mailboxes/jobs/clear-finished", {});
  },

  runEmailgisticsHelper(body: EmailgisticsHelperRequest): Promise<EmailgisticsHelperStatus> {
    return postJSON<EmailgisticsHelperStatus>("/api/tools/emailgistics-helper", body);
  },

  deactivateUser(body: DeactivateUserToolRequest): Promise<DeactivateUserToolResult> {
    return postJSON<DeactivateUserToolResult>("/api/tools/deactivate-user", body);
  },

  getDelegateMailboxJob(job_id: string): Promise<DelegateMailboxJobStatus> {
    return fetchJSON<DelegateMailboxJobStatus>(`/api/tools/delegate-mailboxes/jobs/${encodeURIComponent(job_id)}`);
  },

  cancelDelegateMailboxJob(job_id: string): Promise<{ cancelled: boolean; message?: string }> {
    return postJSON<{ cancelled: boolean; message?: string }>(
      `/api/tools/delegate-mailboxes/jobs/${encodeURIComponent(job_id)}/cancel`,
      {},
    );
  },

  getAzureGroups(search = ""): Promise<AzureDirectoryObject[]> {
    return fetchJSON<AzureDirectoryObject[]>(`/api/azure/directory/groups${buildQuery({ search })}`);
  },

  getAzureEnterpriseApps(search = ""): Promise<AzureDirectoryObject[]> {
    return fetchJSON<AzureDirectoryObject[]>(`/api/azure/directory/enterprise-apps${buildQuery({ search })}`);
  },

  getAzureAppRegistrations(search = ""): Promise<AzureDirectoryObject[]> {
    return fetchJSON<AzureDirectoryObject[]>(`/api/azure/directory/app-registrations${buildQuery({ search })}`);
  },

  getAzureDirectoryRoles(search = ""): Promise<AzureDirectoryObject[]> {
    return fetchJSON<AzureDirectoryObject[]>(`/api/azure/directory/roles${buildQuery({ search })}`);
  },

  getUserAdminCapabilities(): Promise<UserAdminCapabilities> {
    return fetchJSON<UserAdminCapabilities>("/api/user-admin/capabilities");
  },

  getUserAdminUserDetail(userId: string): Promise<UserAdminUserDetail> {
    return fetchJSON<UserAdminUserDetail>(`/api/user-admin/users/${encodeURIComponent(userId)}/detail`);
  },

  getUserAdminUserGroups(userId: string): Promise<UserAdminGroupMembership[]> {
    return fetchJSON<UserAdminGroupMembership[]>(`/api/user-admin/users/${encodeURIComponent(userId)}/groups`);
  },

  getUserAdminUserLicenses(userId: string): Promise<UserAdminLicense[]> {
    return fetchJSON<UserAdminLicense[]>(`/api/user-admin/users/${encodeURIComponent(userId)}/licenses`);
  },

  getUserAdminUserRoles(userId: string): Promise<UserAdminRole[]> {
    return fetchJSON<UserAdminRole[]>(`/api/user-admin/users/${encodeURIComponent(userId)}/roles`);
  },

  getUserAdminUserMailbox(userId: string): Promise<UserAdminMailbox> {
    return fetchJSON<UserAdminMailbox>(`/api/user-admin/users/${encodeURIComponent(userId)}/mailbox`);
  },

  getUserAdminUserDevices(userId: string): Promise<UserAdminDevice[]> {
    return fetchJSON<UserAdminDevice[]>(`/api/user-admin/users/${encodeURIComponent(userId)}/devices`);
  },

  getUserAdminUserActivity(userId: string, limit = 50): Promise<UserAdminAuditEntry[]> {
    return fetchJSON<UserAdminAuditEntry[]>(
      `/api/user-admin/users/${encodeURIComponent(userId)}/activity${buildQuery({ limit })}`,
    );
  },

  createUserAdminJob(body: UserAdminJobRequest): Promise<UserAdminJobStatus> {
    return postJSON<UserAdminJobStatus>("/api/user-admin/jobs", body);
  },

  getUserAdminJob(jobId: string): Promise<UserAdminJobStatus> {
    return fetchJSON<UserAdminJobStatus>(`/api/user-admin/jobs/${encodeURIComponent(jobId)}`);
  },

  getUserAdminJobResults(jobId: string): Promise<UserAdminJobResult[]> {
    return fetchJSON<UserAdminJobResult[]>(`/api/user-admin/jobs/${encodeURIComponent(jobId)}/results`);
  },

  getUserAdminAudit(limit = 100): Promise<UserAdminAuditEntry[]> {
    return fetchJSON<UserAdminAuditEntry[]>(`/api/user-admin/audit${buildQuery({ limit })}`);
  },

  exportUserAdminUsersCsv(params: UserDirectoryExportParams = {}): string {
    return `/api/user-admin/users/export.csv${buildQuery(params)}`;
  },

  exportUserAdminUsersExcel(params: UserDirectoryExportParams = {}): string {
    return `/api/user-admin/users/export.xlsx${buildQuery(params)}`;
  },

  getUserExitPreflight(userId: string): Promise<UserExitPreflight> {
    return fetchJSON<UserExitPreflight>(`/api/user-exit/users/${encodeURIComponent(userId)}/preflight`);
  },

  createUserExitWorkflow(body: {
    user_id: string;
    typed_upn_confirmation: string;
    on_prem_sam_account_name_override?: string;
  }): Promise<UserExitWorkflow> {
    return postJSON<UserExitWorkflow>("/api/user-exit/workflows", body);
  },

  getUserExitWorkflow(workflowId: string): Promise<UserExitWorkflow> {
    return fetchJSON<UserExitWorkflow>(`/api/user-exit/workflows/${encodeURIComponent(workflowId)}`);
  },

  retryUserExitWorkflowStep(workflowId: string, stepId: string): Promise<UserExitWorkflow> {
    return postJSON<UserExitWorkflow>(`/api/user-exit/workflows/${encodeURIComponent(workflowId)}/retry-step`, {
      step_id: stepId,
    });
  },

  completeUserExitManualTask(workflowId: string, taskId: string, notes = ""): Promise<UserExitWorkflow> {
    return postJSON<UserExitWorkflow>(
      `/api/user-exit/workflows/${encodeURIComponent(workflowId)}/manual-tasks/${encodeURIComponent(taskId)}/complete`,
      { notes },
    );
  },

  getAzureCostSummary(): Promise<AzureCostSummary> {
    return fetchJSON<AzureCostSummary>("/api/azure/cost/summary");
  },

  getAzureCostTrend(): Promise<AzureCostPoint[]> {
    return fetchJSON<AzureCostPoint[]>("/api/azure/cost/trend");
  },

  getAzureCostBreakdown(groupBy: "service" | "subscription" | "resource_group" = "service"): Promise<AzureCostBreakdownItem[]> {
    return fetchJSON<AzureCostBreakdownItem[]>(`/api/azure/cost/breakdown${buildQuery({ group_by: groupBy })}`);
  },

  getAzureAllocationPolicy(): Promise<AzureAllocationPolicy> {
    return fetchJSON<AzureAllocationPolicy>("/api/azure/allocations/policy");
  },

  getAzureAllocationStatus(): Promise<AzureAllocationStatus> {
    return fetchJSON<AzureAllocationStatus>("/api/azure/allocations/status");
  },

  getAzureAllocationRules(params: { include_inactive?: boolean; include_all_versions?: boolean } = {}): Promise<AzureAllocationRule[]> {
    return fetchJSON<AzureAllocationRule[]>(`/api/azure/allocations/rules${buildQuery(params)}`);
  },

  getAzureAllocationRuns(limit = 20): Promise<AzureAllocationRun[]> {
    return fetchJSON<AzureAllocationRun[]>(`/api/azure/allocations/runs${buildQuery({ limit })}`);
  },

  getAzureAllocationRun(runId: string): Promise<AzureAllocationRun> {
    return fetchJSON<AzureAllocationRun>(`/api/azure/allocations/runs/${encodeURIComponent(runId)}`);
  },

  runAzureAllocation(body: AzureAllocationRunRequest): Promise<AzureAllocationRun> {
    return postJSON<AzureAllocationRun>("/api/azure/allocations/runs", body);
  },

  getAzureAllocationResults(
    runId: string,
    dimension: AzureAllocationDimension,
    bucketType = "",
  ): Promise<AzureAllocationResult[]> {
    return fetchJSON<AzureAllocationResult[]>(
      `/api/azure/allocations/runs/${encodeURIComponent(runId)}/results${buildQuery({ dimension, bucket_type: bucketType })}`,
    );
  },

  getAzureAllocationResiduals(runId: string, dimension: AzureAllocationDimension): Promise<AzureAllocationResult[]> {
    return fetchJSON<AzureAllocationResult[]>(
      `/api/azure/allocations/runs/${encodeURIComponent(runId)}/residuals${buildQuery({ dimension })}`,
    );
  },

  getAzureAdvisor(): Promise<AzureAdvisorRecommendation[]> {
    return fetchJSON<AzureAdvisorRecommendation[]>("/api/azure/advisor");
  },

  getAzureSavingsSummary(): Promise<AzureSavingsSummary> {
    return fetchJSON<AzureSavingsSummary>("/api/azure/savings/summary");
  },

  getAzureSavingsOpportunities(params: AzureSavingsQueryParams = {}): Promise<AzureSavingsOpportunity[]> {
    return fetchJSON<AzureSavingsOpportunity[]>(`/api/azure/savings/opportunities${buildQuery(params)}`);
  },

  exportAzureSavingsCsv(params: AzureSavingsQueryParams = {}): string {
    return `/api/azure/savings/export.csv${buildQuery(params)}`;
  },

  exportAzureSavingsExcel(params: AzureSavingsQueryParams = {}): string {
    return `/api/azure/savings/export.xlsx${buildQuery(params)}`;
  },

  getAzureRecommendationsSummary(): Promise<AzureSavingsSummary> {
    return fetchJSON<AzureSavingsSummary>("/api/azure/recommendations/summary");
  },

  getAzureRecommendations(params: AzureSavingsQueryParams = {}): Promise<AzureRecommendation[]> {
    return fetchJSON<AzureRecommendation[]>(`/api/azure/recommendations${buildQuery(params)}`);
  },

  getAzureRecommendation(recommendationId: string): Promise<AzureRecommendation> {
    return fetchJSON<AzureRecommendation>(`/api/azure/recommendations/${encodeURIComponent(recommendationId)}`);
  },

  getAzureRecommendationActionContract(recommendationId: string): Promise<AzureRecommendationActionContract> {
    return fetchJSON<AzureRecommendationActionContract>(
      `/api/azure/recommendations/${encodeURIComponent(recommendationId)}/actions`,
    );
  },

  getAzureRecommendationHistory(recommendationId: string): Promise<AzureRecommendationActionEvent[]> {
    return fetchJSON<AzureRecommendationActionEvent[]>(
      `/api/azure/recommendations/${encodeURIComponent(recommendationId)}/history`,
    );
  },

  dismissAzureRecommendation(recommendationId: string, reason = ""): Promise<AzureRecommendation> {
    return postJSON<AzureRecommendation>(`/api/azure/recommendations/${encodeURIComponent(recommendationId)}/dismiss`, { reason });
  },

  reopenAzureRecommendation(recommendationId: string, note = ""): Promise<AzureRecommendation> {
    return postJSON<AzureRecommendation>(`/api/azure/recommendations/${encodeURIComponent(recommendationId)}/reopen`, { note });
  },

  updateAzureRecommendationActionState(
    recommendationId: string,
    body: { action_state: string; action_type?: string; note?: string; metadata?: Record<string, unknown> },
  ): Promise<AzureRecommendation> {
    return postJSON<AzureRecommendation>(
      `/api/azure/recommendations/${encodeURIComponent(recommendationId)}/action-state`,
      body,
    );
  },

  createAzureRecommendationTicket(
    recommendationId: string,
    body: { project_key?: string; issue_type?: string; summary?: string; note?: string },
  ): Promise<AzureRecommendationCreateTicketResponse> {
    return postJSON<AzureRecommendationCreateTicketResponse>(
      `/api/azure/recommendations/${encodeURIComponent(recommendationId)}/actions/create-ticket`,
      body,
    );
  },

  sendAzureRecommendationAlert(
    recommendationId: string,
    body: { channel?: string; teams_webhook_url?: string; note?: string },
  ): Promise<AzureRecommendationSendAlertResponse> {
    return postJSON<AzureRecommendationSendAlertResponse>(
      `/api/azure/recommendations/${encodeURIComponent(recommendationId)}/actions/send-alert`,
      body,
    );
  },

  runAzureRecommendationSafeScript(
    recommendationId: string,
    body: { hook_key?: string; dry_run?: boolean; note?: string },
  ): Promise<AzureRecommendationRunSafeScriptResponse> {
    return postJSON<AzureRecommendationRunSafeScriptResponse>(
      `/api/azure/recommendations/${encodeURIComponent(recommendationId)}/actions/run-safe-script`,
      body,
    );
  },

  exportAzureRecommendationsCsv(params: AzureSavingsQueryParams = {}): string {
    return `/api/azure/recommendations/export.csv${buildQuery(params)}`;
  },

  exportAzureRecommendationsExcel(params: AzureSavingsQueryParams = {}): string {
    return `/api/azure/recommendations/export.xlsx${buildQuery(params)}`;
  },

  getAzureStorage(params: AzureStorageQueryParams = {}): Promise<AzureStorageSummary> {
    return fetchJSON<AzureStorageSummary>(`/api/azure/storage${buildQuery(params)}`);
  },

  getAzureComputeOptimization(params: AzureComputeOptimizationQueryParams = {}): Promise<AzureComputeOptimizationResponse> {
    return fetchJSON<AzureComputeOptimizationResponse>(`/api/azure/compute/optimization${buildQuery(params)}`);
  },

  getAzureAIModels(): Promise<AIModel[]> {
    return fetchJSON<AIModel[]>("/api/azure/ai/models");
  },

  getAzureSecurityCopilotModels(): Promise<AIModel[]> {
    return fetchJSON<AIModel[]>("/api/azure/security/copilot/models");
  },

  getAzureAICostSummary(lookbackDays?: number): Promise<AzureAICostSummary> {
    return fetchJSON<AzureAICostSummary>(`/api/azure/ai-costs/summary${buildQuery({ lookback_days: lookbackDays })}`);
  },

  getAzureAICostTrend(lookbackDays?: number): Promise<AzureAICostTrendPoint[]> {
    return fetchJSON<AzureAICostTrendPoint[]>(`/api/azure/ai-costs/trend${buildQuery({ lookback_days: lookbackDays })}`);
  },

  getAzureAICostBreakdown(groupBy: "model" | "provider" | "feature" | "app" | "team" | "actor", lookbackDays?: number): Promise<AzureAICostBreakdownItem[]> {
    return fetchJSON<AzureAICostBreakdownItem[]>(`/api/azure/ai-costs/breakdown${buildQuery({ group_by: groupBy, lookback_days: lookbackDays })}`);
  },

  askAzureCostCopilot(question: string, model?: string): Promise<AzureCostChatResponse> {
    return postJSON<AzureCostChatResponse>("/api/azure/ai/cost-chat", { question, model });
  },

  getAzureSecurityAccessReview(): Promise<SecurityAccessReviewResponse> {
    return fetchJSON<SecurityAccessReviewResponse>("/api/azure/security/access-review");
  },

  getAzureSecurityWorkspaceSummary(): Promise<SecurityWorkspaceSummaryResponse> {
    return fetchJSON<SecurityWorkspaceSummaryResponse>("/api/azure/security/workspace-summary");
  },

  getAzureSecurityFindingExceptions(
    scope: SecurityFindingExceptionScope = "directory_user",
    activeOnly = true,
  ): Promise<SecurityFindingException[]> {
    return fetchJSON<SecurityFindingException[]>(
      `/api/azure/security/finding-exceptions${buildQuery({ scope, active_only: activeOnly })}`,
    );
  },

  createAzureSecurityFindingException(
    body: SecurityFindingExceptionCreateRequest,
  ): Promise<SecurityFindingException> {
    return postJSON<SecurityFindingException>("/api/azure/security/finding-exceptions", body);
  },

  restoreAzureSecurityFindingException(exceptionId: string): Promise<SecurityFindingException> {
    return postJSON<SecurityFindingException>(
      `/api/azure/security/finding-exceptions/${encodeURIComponent(exceptionId)}/restore`,
      {},
    );
  },

  getAzureSecurityBreakGlassValidation(): Promise<SecurityBreakGlassValidationResponse> {
    return fetchJSON<SecurityBreakGlassValidationResponse>("/api/azure/security/break-glass-validation");
  },

  getAzureSecurityConditionalAccessTracker(): Promise<SecurityConditionalAccessTrackerResponse> {
    return fetchJSON<SecurityConditionalAccessTrackerResponse>("/api/azure/security/conditional-access-tracker");
  },

  getAzureSecurityDirectoryRoleReview(): Promise<SecurityDirectoryRoleReviewResponse> {
    return fetchJSON<SecurityDirectoryRoleReviewResponse>("/api/azure/security/directory-role-review");
  },

  getAzureSecurityDeviceCompliance(): Promise<SecurityDeviceComplianceResponse> {
    return fetchJSON<SecurityDeviceComplianceResponse>("/api/azure/security/device-compliance");
  },

  createAzureSecurityDeviceAction(body: SecurityDeviceActionRequest): Promise<SecurityDeviceActionJob> {
    return postJSON<SecurityDeviceActionJob>("/api/azure/security/device-compliance/actions", body);
  },

  previewAzureSecurityDeviceFixPlan(body: SecurityDeviceFixPlanRequest): Promise<SecurityDeviceFixPlanResponse> {
    return postJSON<SecurityDeviceFixPlanResponse>("/api/azure/security/device-compliance/fix-plan", body);
  },

  executeAzureSecurityDeviceFixPlan(body: SecurityDeviceFixPlanExecuteRequest): Promise<SecurityDeviceActionBatchStatus> {
    return postJSON<SecurityDeviceActionBatchStatus>("/api/azure/security/device-compliance/fix-plan/execute", body);
  },

  getAzureSecurityDeviceActionJob(jobId: string): Promise<SecurityDeviceActionJob> {
    return fetchJSON<SecurityDeviceActionJob>(`/api/azure/security/device-compliance/jobs/${encodeURIComponent(jobId)}`);
  },

  getAzureSecurityDeviceActionJobResults(jobId: string): Promise<SecurityDeviceActionJobResult[]> {
    return fetchJSON<SecurityDeviceActionJobResult[]>(
      `/api/azure/security/device-compliance/jobs/${encodeURIComponent(jobId)}/results`,
    );
  },

  getAzureSecurityDeviceActionBatch(batchId: string): Promise<SecurityDeviceActionBatchStatus> {
    return fetchJSON<SecurityDeviceActionBatchStatus>(
      `/api/azure/security/device-compliance/job-batches/${encodeURIComponent(batchId)}`,
    );
  },

  getAzureSecurityDeviceActionBatchResults(batchId: string): Promise<SecurityDeviceActionBatchResult[]> {
    return fetchJSON<SecurityDeviceActionBatchResult[]>(
      `/api/azure/security/device-compliance/job-batches/${encodeURIComponent(batchId)}/results`,
    );
  },

  getAzureSecurityAppHygiene(): Promise<SecurityAppHygieneResponse> {
    return fetchJSON<SecurityAppHygieneResponse>("/api/azure/security/app-hygiene");
  },

  chatAzureSecurityCopilot(body: SecurityCopilotChatRequest): Promise<SecurityCopilotChatResponse> {
    return postJSON<SecurityCopilotChatResponse>("/api/azure/security/copilot/chat", body);
  },

  // -------------------------------------------------------------------------
  // Azure Alerts
  // -------------------------------------------------------------------------

  getAzureAlertRules(): Promise<AzureAlertRule[]> {
    return fetchJSON<AzureAlertRule[]>("/api/azure/alerts/rules");
  },

  createAzureAlertRule(body: AzureAlertRuleCreate): Promise<AzureAlertRule> {
    return postJSON<AzureAlertRule>("/api/azure/alerts/rules", body);
  },

  updateAzureAlertRule(id: string, body: AzureAlertRuleCreate): Promise<AzureAlertRule> {
    return putJSON<AzureAlertRule>(`/api/azure/alerts/rules/${encodeURIComponent(id)}`, body);
  },

  deleteAzureAlertRule(id: string): Promise<void> {
    return deleteJSON(`/api/azure/alerts/rules/${encodeURIComponent(id)}`);
  },

  toggleAzureAlertRule(id: string): Promise<AzureAlertRule> {
    return postJSON<AzureAlertRule>(`/api/azure/alerts/rules/${encodeURIComponent(id)}/toggle`, {});
  },

  testAzureAlertRule(id: string): Promise<AzureAlertTestResponse> {
    return postJSON<AzureAlertTestResponse>(`/api/azure/alerts/rules/${encodeURIComponent(id)}/test`, {});
  },

  getAzureAlertHistory(params?: { limit?: number; rule_id?: string }): Promise<AzureAlertHistoryItem[]> {
    return fetchJSON<AzureAlertHistoryItem[]>(`/api/azure/alerts/history${buildQuery(params ?? {})}`);
  },

  getAzureAlertTriggerTypes(): Promise<AzureAlertTriggerSchema> {
    return fetchJSON<AzureAlertTriggerSchema>("/api/azure/alerts/trigger-types");
  },

  chatParseAzureAlert(message: string): Promise<AzureChatParseResponse> {
    return postJSON<AzureChatParseResponse>("/api/azure/alerts/chat-parse", { message });
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
  getTriageLog(params: TriageLogQueryParams = {}): Promise<TriageLogEntry[]> {
    return fetchJSON<TriageLogEntry[]>(`/api/triage/log${buildQuery(params)}`);
  },

  /** Fetch technician QA scores for closed tickets. */
  getTechnicianScores(params: TechnicianScoreQueryParams = {}): Promise<TechnicianScoreEntry[]> {
    return fetchJSON<TechnicianScoreEntry[]>(`/api/triage/technician-scores${buildQuery(params)}`);
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
  getTriageRunStatus(): Promise<TriageRunStatus> {
    return fetchJSON<TriageRunStatus>("/api/triage/run-status");
  },

  /** Get live queue snapshot for every Ollama request coordinator. */
  getOllamaQueueStatus(): Promise<OllamaLaneSnapshot[]> {
    return fetchJSON<OllamaLaneSnapshot[]>("/api/triage/ollama-queue");
  },

  /** Get progress of the current closed-ticket scoring run. */
  getTechnicianScoreRunStatus(): Promise<{
    running: boolean;
    processed: number;
    total: number;
    current_key: string | null;
    remaining_count?: number;
    processed_count?: number;
    priority_blocked?: boolean;
    priority_message?: string;
    priority_reason?: string;
    priority_pending_count?: number;
    priority_running?: boolean;
    priority_current_key?: string | null;
  }> {
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

  // ---------------------------------------------------------------------------
  // Active Directory
  // ---------------------------------------------------------------------------

  getADStatus(): Promise<ADStatus> {
    return fetchJSON<ADStatus>("/api/ad/status");
  },

  searchAD(q: string): Promise<ADSearchResult[]> {
    return fetchJSON<ADSearchResult[]>(`/api/ad/search?q=${encodeURIComponent(q)}`);
  },

  listADUsers(params?: { q?: string; ou?: string; page?: number; limit?: number }): Promise<ADUserPage> {
    const p = new URLSearchParams();
    if (params?.q) p.set("q", params.q);
    if (params?.ou) p.set("ou", params.ou);
    if (params?.page) p.set("page", String(params.page));
    if (params?.limit) p.set("limit", String(params.limit));
    const qs = p.toString();
    return fetchJSON<ADUserPage>(`/api/ad/users${qs ? `?${qs}` : ""}`);
  },

  getADUser(sam: string): Promise<ADUser> {
    return fetchJSON<ADUser>(`/api/ad/users/${encodeURIComponent(sam)}`);
  },

  createADUser(body: CreateADUserRequest): Promise<ADUser> {
    return postJSON<ADUser>("/api/ad/users", body);
  },

  updateADUser(sam: string, attributes: Record<string, string>): Promise<ADUser> {
    return postJSON<ADUser>(`/api/ad/users/${encodeURIComponent(sam)}/update`, { attributes });
  },

  enableADUser(sam: string): Promise<ADUser> {
    return postJSON<ADUser>(`/api/ad/users/${encodeURIComponent(sam)}/enable`, {});
  },

  disableADUser(sam: string): Promise<ADUser> {
    return postJSON<ADUser>(`/api/ad/users/${encodeURIComponent(sam)}/disable`, {});
  },

  unlockADUser(sam: string): Promise<ADUser> {
    return postJSON<ADUser>(`/api/ad/users/${encodeURIComponent(sam)}/unlock`, {});
  },

  resetADPassword(sam: string, new_password: string, must_change: boolean): Promise<{ ok: boolean }> {
    return postJSON<{ ok: boolean }>(`/api/ad/users/${encodeURIComponent(sam)}/reset-password`, {
      new_password,
      must_change,
    });
  },

  moveADUser(sam: string, new_ou_dn: string): Promise<ADUser> {
    return postJSON<ADUser>(`/api/ad/users/${encodeURIComponent(sam)}/move`, { new_ou_dn });
  },

  deleteADUser(sam: string): Promise<{ deleted: boolean; dn: string }> {
    return deleteJSON(`/api/ad/users/${encodeURIComponent(sam)}`).then(() => ({ deleted: true, dn: "" }));
  },

  listADGroups(params?: { q?: string; page?: number; limit?: number }): Promise<ADGroupPage> {
    const p = new URLSearchParams();
    if (params?.q) p.set("q", params.q);
    if (params?.page) p.set("page", String(params.page));
    if (params?.limit) p.set("limit", String(params.limit));
    const qs = p.toString();
    return fetchJSON<ADGroupPage>(`/api/ad/groups${qs ? `?${qs}` : ""}`);
  },

  getADGroup(sam: string): Promise<ADGroup> {
    return fetchJSON<ADGroup>(`/api/ad/groups/${encodeURIComponent(sam)}`);
  },

  createADGroup(body: CreateADGroupRequest): Promise<ADGroup> {
    return postJSON<ADGroup>("/api/ad/groups", body);
  },

  deleteADGroup(sam: string): Promise<{ deleted: boolean }> {
    return deleteJSON(`/api/ad/groups/${encodeURIComponent(sam)}`).then(() => ({ deleted: true }));
  },

  addADGroupMember(groupSam: string, member_dn: string): Promise<ADGroup> {
    return postJSON<ADGroup>(`/api/ad/groups/${encodeURIComponent(groupSam)}/members`, { member_dn });
  },

  removeADGroupMember(groupSam: string, member_dn: string): Promise<ADGroup> {
    const p = new URLSearchParams({ member_dn });
    return deleteJSON(`/api/ad/groups/${encodeURIComponent(groupSam)}/members?${p.toString()}`).then(
      () => api.getADGroup(groupSam),
    );
  },

  listADComputers(params?: { q?: string; page?: number; limit?: number }): Promise<ADComputerPage> {
    const p = new URLSearchParams();
    if (params?.q) p.set("q", params.q);
    if (params?.page) p.set("page", String(params.page));
    if (params?.limit) p.set("limit", String(params.limit));
    const qs = p.toString();
    return fetchJSON<ADComputerPage>(`/api/ad/computers${qs ? `?${qs}` : ""}`);
  },

  getADComputer(cn: string): Promise<ADComputer> {
    return fetchJSON<ADComputer>(`/api/ad/computers/${encodeURIComponent(cn)}`);
  },

  listADOUs(base_dn?: string): Promise<ADOU[]> {
    const p = base_dn ? `?base_dn=${encodeURIComponent(base_dn)}` : "";
    return fetchJSON<ADOU[]>(`/api/ad/ous${p}`);
  },

  createADOU(name: string, parent_dn: string, description?: string): Promise<ADOU> {
    return postJSON<ADOU>("/api/ad/ous", { name, parent_dn, description: description ?? "" });
  },

  deleteADOU(dn: string): Promise<{ deleted: boolean }> {
    return deleteJSON(`/api/ad/ous?dn=${encodeURIComponent(dn)}`).then(() => ({ deleted: true }));
  },

  // Deactivation scheduling
  createDeactivationJob(req: CreateDeactivationJobRequest): Promise<DeactivationJob> {
    return postJSON<DeactivationJob>("/api/deactivation-schedule", req);
  },

  listDeactivationJobsForTicket(ticketKey: string): Promise<DeactivationJob[]> {
    return fetchJSON<DeactivationJob[]>(`/api/deactivation-schedule/${encodeURIComponent(ticketKey)}`);
  },

  async cancelDeactivationJob(jobId: string): Promise<DeactivationJob> {
    const res = await fetch(`/api/deactivation-schedule/${encodeURIComponent(jobId)}`, { method: "DELETE" });
    if (res.status === 401) { window.location.href = "/api/auth/login"; throw new Error("Not authenticated"); }
    if (!res.ok) throw new Error(await res.text());
    return res.json() as Promise<DeactivationJob>;
  },

  listAllDeactivationJobs(limit = 100): Promise<DeactivationJob[]> {
    return fetchJSON<DeactivationJob[]>(`/api/deactivation-schedule?limit=${limit}`);
  },
};

export default api;

// ---------------------------------------------------------------------------
// Active Directory types
// ---------------------------------------------------------------------------

export interface ADStatus {
  configured: boolean;
  connected: boolean;
  server: string;
  base_dn: string;
  ssl?: boolean;
  port?: number;
  error?: string;
}

export interface ADUserFlags {
  enabled: boolean;
  locked: boolean;
  password_never_expires: boolean;
  password_not_required: boolean;
}

export interface ADUser {
  dn: string;
  sam_account_name: string;
  upn: string;
  display_name: string;
  given_name: string;
  surname: string;
  email: string;
  phone: string;
  mobile: string;
  department: string;
  title: string;
  manager_dn: string;
  description: string;
  street: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  company: string;
  employee_id: string;
  user_account_control: number;
  flags: ADUserFlags;
  last_logon: string | null;
  pwd_last_set: string | null;
  account_expires: string | null;
  lockout_time: string | null;
  bad_pwd_count: number;
  when_created: string | null;
  when_changed: string | null;
  member_of: string[];
}

export interface ADUserPage {
  total: number;
  page: number;
  limit: number;
  items: ADUser[];
}

export interface CreateADUserRequest {
  sam: string;
  upn: string;
  display_name: string;
  given_name: string;
  surname: string;
  ou_dn: string;
  password?: string;
  email?: string;
  title?: string;
  department?: string;
  description?: string;
}

export interface ADGroup {
  dn: string;
  sam_account_name: string;
  cn: string;
  description: string;
  email: string;
  group_type_raw: number;
  group_type_label: string;
  member_of: string[];
  members?: string[];
  when_created: string | null;
  when_changed: string | null;
}

export interface ADGroupPage {
  total: number;
  page: number;
  limit: number;
  items: ADGroup[];
}

export interface CreateADGroupRequest {
  name: string;
  sam: string;
  ou_dn: string;
  group_type?: number;
  description?: string;
  email?: string;
}

export interface ADComputer {
  dn: string;
  cn: string;
  dns_hostname: string;
  os: string;
  os_version: string;
  description: string;
  managed_by: string;
  enabled: boolean;
  last_logon: string | null;
  when_created: string | null;
}

export interface ADComputerPage {
  total: number;
  page: number;
  limit: number;
  items: ADComputer[];
}

export interface ADOU {
  dn: string;
  ou: string;
  description: string;
  when_created: string | null;
}

export interface ADSearchResult {
  kind: "user" | "group" | "computer" | "ou";
  label: string;
  sam: string;
  dn: string;
  email: string;
}

// ---------------------------------------------------------------------------
// Deactivation scheduling types
// ---------------------------------------------------------------------------

export interface DeactivationJob {
  job_id: string;
  ticket_key: string;
  display_name: string;
  entra_user_id: string;
  ad_sam: string;
  run_at: string;
  timezone_label: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  result: {
    entra?: string;
    ad?: string;
  };
  created_at: string;
  created_by: string;
}

export interface CreateDeactivationJobRequest {
  ticket_key: string;
  display_name: string;
  entra_user_id: string;
  ad_sam?: string;
  run_at: string;
  timezone_label: string;
}

export interface SecurityLaneAISummary {
  lane_key: string;
  narrative: string;
  teaser: string;
  bullets: string[];
  bullets_json: string;
  generated_at: string;
  model_used: string;
}

