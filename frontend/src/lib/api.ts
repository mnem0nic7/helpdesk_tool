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

async function deleteJSON(url: string): Promise<void> {
  const res = await fetch(url, {
    method: "DELETE",
  });
  if (res.status === 401) {
    window.location.href = "/api/auth/login";
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`DELETE ${url} failed (${res.status}): ${text}`);
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
    const text = await res.text();
    throw new Error(`Export failed (${res.status}): ${text}`);
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
  reporter_account_id?: string | null;
  reporter_display_name?: string;
  request_type_id?: string;
  components?: string[];
  work_category?: string;
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
  is_admin: boolean;
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

export interface AzureStatus {
  configured: boolean;
  initialized: boolean;
  refreshing: boolean;
  last_refresh: string | null;
  datasets: AzureDatasetStatus[];
}

export interface AzureCostSummary {
  lookback_days: number;
  total_cost: number;
  currency: string;
  top_service: string;
  top_subscription: string;
  top_resource_group: string;
  recommendation_count: number;
  potential_monthly_savings: number;
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

export interface AzureDirectoryObject {
  id: string;
  display_name: string;
  object_type: "user" | "group" | "enterprise_app" | "app_registration" | "directory_role";
  principal_name: string;
  mail: string;
  app_id: string;
  enabled: boolean | null;
  extra: Record<string, string>;
}

export interface AzureCostPoint {
  date: string;
  cost: number;
  currency: string;
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
  currency: string;
  share: number;
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
  getFilterOptions(): Promise<TicketFilterOptions> {
    return fetchJSON<TicketFilterOptions>("/api/filter-options");
  },

  /** Fetch a single ticket by its Jira key with full detail payload. */
  getTicket(key: string): Promise<TicketDetail> {
    return fetchJSON<TicketDetail>(`/api/tickets/${encodeURIComponent(key)}`);
  },

  /** Refresh the currently displayed ticket rows from live Jira data. */
  refreshVisibleTickets(keys: string[]): Promise<VisibleTicketRefreshResponse> {
    return postJSON<VisibleTicketRefreshResponse>("/api/tickets/refresh-visible", { keys });
  },

  /** Update a ticket reporter from the OCC creator line in the saved description. */
  syncTicketReporter(key: string): Promise<SyncTicketReporterResponse> {
    return postJSON<SyncTicketReporterResponse>(`/api/tickets/${encodeURIComponent(key)}/sync-reporter`, {});
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
    await downloadPost("/api/report/export", config, "OIT_Report.xlsx");
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

  getAzureCostSummary(): Promise<AzureCostSummary> {
    return fetchJSON<AzureCostSummary>("/api/azure/cost/summary");
  },

  getAzureCostTrend(): Promise<AzureCostPoint[]> {
    return fetchJSON<AzureCostPoint[]>("/api/azure/cost/trend");
  },

  getAzureCostBreakdown(groupBy: "service" | "subscription" | "resource_group" = "service"): Promise<AzureCostBreakdownItem[]> {
    return fetchJSON<AzureCostBreakdownItem[]>(`/api/azure/cost/breakdown${buildQuery({ group_by: groupBy })}`);
  },

  getAzureAdvisor(): Promise<AzureAdvisorRecommendation[]> {
    return fetchJSON<AzureAdvisorRecommendation[]>("/api/azure/advisor");
  },

  getAzureStorage(): Promise<AzureStorageSummary> {
    return fetchJSON<AzureStorageSummary>("/api/azure/storage");
  },

  getAzureComputeOptimization(): Promise<AzureComputeOptimizationResponse> {
    return fetchJSON<AzureComputeOptimizationResponse>("/api/azure/compute/optimization");
  },

  getAzureAIModels(): Promise<AIModel[]> {
    return fetchJSON<AIModel[]>("/api/azure/ai/models");
  },

  askAzureCostCopilot(question: string, model?: string): Promise<AzureCostChatResponse> {
    return postJSON<AzureCostChatResponse>("/api/azure/ai/cost-chat", { question, model });
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
