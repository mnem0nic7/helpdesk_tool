"""Pydantic data models for the OIT Helpdesk Dashboard API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Metric response models
# ---------------------------------------------------------------------------


class HeadlineMetrics(BaseModel):
    """Top-level KPI snapshot returned by /api/metrics/headline."""

    total_tickets: int
    open_backlog: int
    resolved: int
    resolution_rate: float
    median_ttr_hours: Optional[float] = None
    p90_ttr_hours: Optional[float] = None
    p95_ttr_hours: Optional[float] = None
    stale_count: int
    excluded_count: int


class MonthlyVolume(BaseModel):
    """Created / resolved counts for a single calendar month."""

    month: str
    created: int
    resolved: int
    net_flow: int


class AgeBucket(BaseModel):
    """One bucket of the open-backlog aging distribution."""

    bucket: str
    count: int
    percent: float


class TTRBucket(BaseModel):
    """One bucket of the time-to-resolve distribution."""

    bucket: str
    count: int
    percent: float
    cumulative_percent: float


class AssigneeStats(BaseModel):
    """Per-assignee workload and performance summary."""

    name: str
    resolved: int
    open: int
    median_ttr: Optional[float] = None
    p90_ttr: Optional[float] = None
    stale: int


class PriorityCount(BaseModel):
    """Ticket counts by priority level."""

    priority: str
    total: int
    open: int


class SLATimerSummary(BaseModel):
    """Summary statistics for one JSM SLA timer."""

    timer_name: str
    total: int
    met: int
    breached: int
    running: int
    paused: int
    met_rate: float
    breach_rate: float


class TicketRow(BaseModel):
    """Flat representation of a single Jira issue for the tickets table."""

    key: str
    summary: str
    issue_type: str
    status: str
    status_category: str
    priority: str
    resolution: str
    assignee: str
    assignee_account_id: str
    reporter: str
    reporter_account_id: str = ""
    occ_ticket_id: str = ""
    created: str
    first_contact_date: str = ""
    updated: str
    resolved: str
    request_type: str
    request_type_id: str = ""
    calendar_ttr_hours: Optional[float] = None
    age_days: Optional[float] = None
    days_since_update: Optional[float] = None
    excluded: bool
    # SLA first response
    sla_first_response_status: str = ""
    sla_first_response_breach_time: str = ""
    sla_first_response_remaining_millis: Optional[int] = None
    sla_first_response_elapsed_millis: Optional[int] = None
    sla_first_response_goal_millis: Optional[int] = None
    # SLA resolution
    sla_resolution_status: str = ""
    sla_resolution_breach_time: str = ""
    sla_resolution_remaining_millis: Optional[int] = None
    sla_resolution_elapsed_millis: Optional[int] = None
    sla_resolution_goal_millis: Optional[int] = None
    # Response/follow-up compliance proxy
    response_followup_status: str = ""
    first_response_2h_status: str = ""
    daily_followup_status: str = ""
    last_support_touch_date: str = ""
    support_touch_count: int = 0
    followup_authoritative: bool = False
    first_response_authoritative: bool = False
    # Additional fields
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    work_category: str = ""
    organizations: list[str] = Field(default_factory=list)
    attachment_count: int = 0


class JiraAuthStatus(BaseModel):
    """Current Jira write identity linkage for the signed-in MoveDocs user."""

    connected: bool = False
    mode: str = "fallback_it_app"
    site_url: str = ""
    account_name: str = ""
    configured: bool = False


# ---------------------------------------------------------------------------
# Bulk action request models
# ---------------------------------------------------------------------------


class ReportFilters(BaseModel):
    """Filter criteria for the report builder — mirrors ticket query params."""

    status: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    issue_type: Optional[str] = None
    label: Optional[str] = None
    libra_support: Optional[Literal["all", "libra_support", "non_libra_support"]] = None
    search: Optional[str] = None
    open_only: bool = False
    stale_only: bool = False
    created_after: Optional[str] = None
    created_before: Optional[str] = None


class ReportConfig(BaseModel):
    """Full report builder configuration sent by the frontend."""

    filters: ReportFilters = Field(default_factory=ReportFilters)
    columns: list[str] = Field(default_factory=list)
    sort_field: str = "created"
    sort_dir: str = "desc"  # "asc" or "desc"
    group_by: Optional[str] = None
    include_excluded: bool = False
    window_mode: Literal["7d", "30d", "custom"] = "30d"


class ReportTemplateBase(BaseModel):
    """Shared report template payload fields."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=1000)
    include_in_master_export: bool = True
    config: ReportConfig = Field(default_factory=ReportConfig)


class ReportTemplateCreateRequest(ReportTemplateBase):
    """Create a new saved report template."""


class ReportTemplateUpdateRequest(ReportTemplateBase):
    """Replace an existing saved report template."""


class ReportTemplate(BaseModel):
    """Saved report template returned to the frontend."""

    id: str
    site_scope: str
    name: str
    description: str = ""
    category: str = ""
    notes: str = ""
    readiness: str = "custom"
    is_seed: bool = False
    include_in_master_export: bool = True
    created_at: str
    updated_at: str
    created_by_email: str = ""
    created_by_name: str = ""
    updated_by_email: str = ""
    updated_by_name: str = ""
    config: ReportConfig


class ReportTemplateInsightPoint(BaseModel):
    """Single daily point for a saved report template insight sparkline."""

    date: str
    count: int


class ReportTemplateInsight(BaseModel):
    """Operational summary for a saved report template."""

    template_id: str
    template_name: str
    window_mode: Literal["7d", "30d", "custom"] = "30d"
    window_label: str
    window_field: str
    window_field_label: str
    window_start: str
    window_end: str
    count_in_window: int
    p95_daily_count: float
    trend: list[ReportTemplateInsightPoint] = Field(default_factory=list)


class ReportAISummary(BaseModel):
    """Current AI-generated narrative for a saved report template."""

    template_id: str
    template_name: str
    site_scope: str
    source: Literal["manual", "nightly"] = "manual"
    status: str = "ready"
    summary: str = ""
    bullets: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    model_used: str = ""
    generated_at: Optional[str] = None
    template_version: str = ""
    data_version: str = ""
    error: str = ""


class ReportAISummaryBatchStartResponse(BaseModel):
    """Response returned when a manual AI summary batch is queued."""

    batch_id: str
    site_scope: str
    status: str = "queued"
    item_count: int = 0
    requested_at: str


class ReportAISummaryBatchItem(BaseModel):
    """Per-template progress entry for a report AI summary batch."""

    template_id: str
    template_name: str
    status: str = "queued"
    source: Literal["manual", "nightly"] = "manual"
    summary: str = ""
    bullets: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    model_used: str = ""
    generated_at: Optional[str] = None
    error: str = ""


class ReportAISummaryBatchStatus(BaseModel):
    """Manual AI summary batch status payload."""

    batch_id: str
    site_scope: str
    status: str = "queued"
    item_count: int = 0
    requested_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    items: list[ReportAISummaryBatchItem] = Field(default_factory=list)


class ReportTemplateExportSelectionRequest(BaseModel):
    """Update whether a template is included in the master workbook export."""

    include_in_master_export: bool = True


class OasisDevWorkloadReportRequest(BaseModel):
    """Request body for the OasisDev workload summary report."""

    assignee: Optional[str] = None
    report_start: Optional[str] = None
    report_end: Optional[str] = None
    last_report_date: Optional[str] = None


class ChartDataRequest(BaseModel):
    """Request body for the grouped chart data endpoint."""

    filters: ReportFilters = Field(default_factory=ReportFilters)
    group_by: str
    metric: str = "count"  # count|open|resolved|avg_ttr|median_ttr|avg_age
    include_excluded: bool = False


class ChartTimeseriesRequest(BaseModel):
    """Request body for the time series chart data endpoint."""

    filters: ReportFilters = Field(default_factory=ReportFilters)
    bucket: str = "week"  # week|month
    include_excluded: bool = False


class BulkActionRequest(BaseModel):
    """Base model for bulk operations on a set of issue keys."""

    keys: list[str]


class BulkStatusRequest(BulkActionRequest):
    """Transition a batch of issues to a new status."""

    transition_id: str


class BulkAssignRequest(BulkActionRequest):
    """Reassign a batch of issues to a single account."""

    account_id: str


class BulkPriorityRequest(BulkActionRequest):
    """Change the priority of a batch of issues."""

    priority: str


class BulkCommentRequest(BulkActionRequest):
    """Add the same comment to a batch of issues."""

    comment: str


class TicketCreateRequest(BaseModel):
    """Create a new Jira service request ticket."""

    summary: str = ""
    description: str = ""
    priority: str = ""
    request_type_id: str = ""


class TicketUpdateRequest(BaseModel):
    """Update editable ticket fields on a single issue."""

    summary: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    assignee_account_id: Optional[str] = None
    reporter_account_id: Optional[str] = None
    reporter_display_name: Optional[str] = None
    request_type_id: Optional[str] = None
    components: Optional[list[str]] = None
    work_category: Optional[str] = None


class TicketTransitionRequest(BaseModel):
    """Transition a single issue to another workflow state."""

    transition_id: str


class TicketCommentRequest(BaseModel):
    """Add a comment to a single issue."""

    comment: str
    public: bool = False


class TicketRefreshRequest(BaseModel):
    """Refresh a specific set of displayed tickets from Jira."""

    keys: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# AI Triage models
# ---------------------------------------------------------------------------


class TriageSuggestion(BaseModel):
    """AI-generated suggestion for a single field."""

    field: str
    current_value: str
    suggested_value: str
    reasoning: str
    confidence: float


class TriageResult(BaseModel):
    """Full AI triage result for one ticket."""

    key: str
    suggestions: list[TriageSuggestion]
    model_used: str
    created_at: str


class TriageApplyRequest(BaseModel):
    """Apply accepted suggestions to a ticket."""

    key: str
    accepted_fields: list[str]


class TriageFieldAction(BaseModel):
    """Apply a single field suggestion to a ticket."""

    key: str
    field: str


class TriageDismissRequest(BaseModel):
    """Dismiss (delete) all suggestions for a ticket."""

    key: str


class TriageAnalyzeRequest(BaseModel):
    """Request to analyze one or more tickets."""

    keys: list[str]
    model: str
    force: bool = False


class AIModel(BaseModel):
    """Available AI model for triage."""

    id: str
    name: str
    provider: str


class TechnicianScore(BaseModel):
    """AI-evaluated quality score for a closed technician-handled ticket."""

    key: str
    communication_score: int = Field(ge=1, le=5)
    communication_notes: str
    documentation_score: int = Field(ge=1, le=5)
    documentation_notes: str
    score_summary: str
    model_used: str
    created_at: str


# ---------------------------------------------------------------------------
# Knowledge base models
# ---------------------------------------------------------------------------


class KnowledgeBaseArticle(BaseModel):
    """One searchable/editable internal knowledge base article."""

    id: int | None = None
    slug: str
    code: str = ""
    title: str
    request_type: str = ""
    summary: str = ""
    content: str
    source_filename: str = ""
    source_ticket_key: str = ""
    imported_from_seed: bool = False
    ai_generated: bool = False
    created_at: str
    updated_at: str


class KnowledgeBaseArticleUpsertRequest(BaseModel):
    """Create or update a knowledge base article."""

    title: str
    request_type: str = ""
    summary: str = ""
    content: str
    source_ticket_key: str = ""


class KnowledgeBaseDraftRequest(BaseModel):
    """Generate an AI-authored KB draft from a closed ticket."""

    key: str
    model: Optional[str] = None
    article_id: Optional[int] = None


class KnowledgeBaseDraft(BaseModel):
    """AI-generated draft to create or update a KB article."""

    title: str
    request_type: str = ""
    summary: str = ""
    content: str
    model_used: str
    source_ticket_key: str
    suggested_article_id: Optional[int] = None
    suggested_article_title: str = ""
    recommended_action: str = "create_new"
    change_summary: str = ""


# ---------------------------------------------------------------------------
# Azure portal models
# ---------------------------------------------------------------------------


class AzureDatasetStatus(BaseModel):
    """Refresh status metadata for one cached Azure dataset group."""

    key: str
    label: str
    configured: bool
    refreshing: bool
    interval_minutes: int
    item_count: int
    last_refresh: Optional[str] = None
    error: Optional[str] = None


class AzureStatus(BaseModel):
    """Overall Azure cache state for the site banner."""

    configured: bool
    initialized: bool
    refreshing: bool
    last_refresh: Optional[str] = None
    datasets: list[AzureDatasetStatus] = Field(default_factory=list)


class AzureSubscription(BaseModel):
    """Azure subscription metadata returned by the inventory APIs."""

    subscription_id: str
    display_name: str
    state: str = ""
    tenant_id: str = ""
    authorization_source: str = ""


class AzureManagementGroup(BaseModel):
    """Azure management group entry."""

    id: str
    name: str
    display_name: str
    parent_id: str = ""
    parent_display_name: str = ""
    group_type: str = ""


class AzureResourceRow(BaseModel):
    """Flat Azure resource row for the resource explorer."""

    id: str
    name: str
    resource_type: str
    subscription_id: str
    subscription_name: str = ""
    resource_group: str = ""
    location: str = ""
    kind: str = ""
    sku_name: str = ""
    vm_size: str = ""
    state: str = ""
    created_time: str = ""
    tags: dict[str, str] = Field(default_factory=dict)


class AzureResourceListResponse(BaseModel):
    """Filtered resource explorer response."""

    resources: list[AzureResourceRow] = Field(default_factory=list)
    matched_count: int = 0
    total_count: int = 0


class AzureVirtualMachineRow(AzureResourceRow):
    """Azure virtual machine row for the dedicated VM explorer."""

    size: str = ""
    power_state: str = ""


class AzureCountByLabel(BaseModel):
    """Simple label/count breakdown row."""

    label: str
    count: int


class AzureVirtualMachineSummary(BaseModel):
    """Headline VM inventory summary."""

    total_vms: int = 0
    running_vms: int = 0
    deallocated_vms: int = 0
    distinct_sizes: int = 0


class AzureVirtualMachineSizeCoverageRow(BaseModel):
    """Tenant-wide VM vs reserved-instance coverage for one exact SKU and region."""

    label: str
    region: str = ""
    vm_count: int = 0
    reserved_instance_count: Optional[int] = None
    delta: Optional[int] = None
    coverage_status: str = "unavailable"


class AzureVirtualMachineListResponse(BaseModel):
    """Filtered virtual machine explorer response."""

    vms: list[AzureVirtualMachineRow] = Field(default_factory=list)
    matched_count: int = 0
    total_count: int = 0
    summary: AzureVirtualMachineSummary = Field(default_factory=AzureVirtualMachineSummary)
    by_size: list[AzureVirtualMachineSizeCoverageRow] = Field(default_factory=list)
    by_state: list[AzureCountByLabel] = Field(default_factory=list)
    reservation_data_available: bool = False
    reservation_error: Optional[str] = None


class AzureVirtualMachineAssociatedResource(BaseModel):
    """One resource associated with a virtual machine detail view."""

    id: str
    name: str
    resource_type: str
    relationship: str
    subscription_id: str = ""
    subscription_name: str = ""
    resource_group: str = ""
    location: str = ""
    state: str = ""
    cost: Optional[float] = None
    currency: str = "USD"


class AzureVirtualMachineCostDetails(BaseModel):
    """Cost rollup for a VM and its directly associated resources."""

    lookback_days: int
    currency: str = "USD"
    cost_data_available: bool = False
    cost_error: Optional[str] = None
    total_cost: Optional[float] = None
    vm_cost: Optional[float] = None
    related_resource_cost: Optional[float] = None
    priced_resource_count: int = 0


class AzureVirtualMachineDetailResponse(BaseModel):
    """Detailed VM drill-down with related resources and cost."""

    vm: AzureVirtualMachineRow
    associated_resources: list[AzureVirtualMachineAssociatedResource] = Field(default_factory=list)
    cost: AzureVirtualMachineCostDetails


class AzureVirtualMachineExportFilters(BaseModel):
    """Saved VM filter set for export jobs."""

    search: str = ""
    subscription_id: str = ""
    resource_group: str = ""
    location: str = ""
    state: str = ""
    size: str = ""


class AzureVirtualMachineCostExportJobCreateRequest(BaseModel):
    """Request body for starting a background VM cost export."""

    scope: Literal["all", "filtered"] = "all"
    lookback_days: Literal[7, 30, 90] = 30
    filters: AzureVirtualMachineExportFilters = Field(default_factory=AzureVirtualMachineExportFilters)


class AzureVirtualMachineCostExportJobResponse(BaseModel):
    """Status payload for one VM cost export background job."""

    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    recipient_email: str
    scope: Literal["all", "filtered"]
    lookback_days: Literal[7, 30, 90]
    filters: AzureVirtualMachineExportFilters = Field(default_factory=AzureVirtualMachineExportFilters)
    requested_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress_current: int = 0
    progress_total: int = 0
    progress_message: str = ""
    file_name: Optional[str] = None
    file_ready: bool = False
    error: Optional[str] = None


class OneDriveCopyUserOptionResponse(BaseModel):
    """Directory-backed user lookup row for the OneDrive copy tool."""

    id: str
    display_name: str
    principal_name: str = ""
    mail: str = ""
    enabled: Optional[bool] = None
    source: Literal["entra", "saved"] = "entra"
    on_prem_sam: str = ""


class OneDriveCopyJobCreateRequest(BaseModel):
    """Request body for starting a OneDrive copy job."""

    source_upn: str = Field(min_length=3, max_length=320)
    destination_upn: str = Field(min_length=3, max_length=320)
    destination_folder: str = Field(min_length=1, max_length=255)
    test_mode: bool = False
    test_file_limit: int = Field(default=25, ge=1, le=500)
    exclude_system_folders: bool = True


class OneDriveCopyJobEventResponse(BaseModel):
    """One persisted job event or failure row."""

    event_id: int
    level: Literal["info", "warning", "error"]
    message: str
    created_at: str


class AppLoginAuditEventResponse(BaseModel):
    """One recorded MoveDocs login event."""

    event_id: int
    email: str
    name: str
    auth_provider: str
    site_scope: str
    source_ip: str = ""
    user_agent: str = ""
    created_at: str


class MailboxRuleResponse(BaseModel):
    """One normalized inbox rule returned by the shared Tools surface."""

    id: str
    display_name: str = ""
    sequence: Optional[int] = None
    is_enabled: bool = False
    has_error: bool = False
    stop_processing_rules: bool = False
    conditions_summary: list[str] = Field(default_factory=list)
    exceptions_summary: list[str] = Field(default_factory=list)
    actions_summary: list[str] = Field(default_factory=list)


class MailboxRulesResponse(BaseModel):
    """Inbox rule listing payload for a provided mailbox identifier."""

    mailbox: str
    display_name: str = ""
    principal_name: str = ""
    primary_address: str = ""
    provider_enabled: bool = False
    note: str = ""
    rule_count: int = 0
    rules: list[MailboxRuleResponse] = Field(default_factory=list)


class MailboxDelegateEntryResponse(BaseModel):
    """One mailbox delegate entry for a mailbox."""

    identity: str = ""
    display_name: str = ""
    principal_name: str = ""
    mail: str = ""
    permission_types: list[str] = Field(default_factory=list)


class MailboxDelegatesResponse(BaseModel):
    """Mailbox delegate listing payload for a provided mailbox identifier."""

    mailbox: str
    display_name: str = ""
    principal_name: str = ""
    primary_address: str = ""
    provider_enabled: bool = False
    supported_permission_types: list[str] = Field(default_factory=list)
    permission_counts: dict[str, int] = Field(default_factory=dict)
    note: str = ""
    delegate_count: int = 0
    delegates: list[MailboxDelegateEntryResponse] = Field(default_factory=list)


class DelegateMailboxResponse(BaseModel):
    """One mailbox where the provided user has delegate access."""

    identity: str = ""
    display_name: str = ""
    principal_name: str = ""
    primary_address: str = ""
    permission_types: list[str] = Field(default_factory=list)


class DelegateMailboxesResponse(BaseModel):
    """Org-wide mailbox delegate matches for a provided user identifier."""

    user: str
    display_name: str = ""
    principal_name: str = ""
    primary_address: str = ""
    provider_enabled: bool = False
    supported_permission_types: list[str] = Field(default_factory=list)
    permission_counts: dict[str, int] = Field(default_factory=dict)
    note: str = ""
    mailbox_count: int = 0
    scanned_mailbox_count: int = 0
    mailboxes: list[DelegateMailboxResponse] = Field(default_factory=list)


class DelegateMailboxJobCreateRequest(BaseModel):
    """Request body for starting a delegate mailbox background scan."""

    user: str = Field(min_length=3, max_length=320)


class DelegateMailboxJobResponse(BaseModel):
    """Status payload for one delegate mailbox background scan job."""

    job_id: str
    site_scope: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    phase: Literal[
        "queued",
        "resolving_user",
        "scanning_send_on_behalf",
        "scanning_exchange_permissions",
        "merging_results",
        "completed",
        "failed",
        "cancelled",
    ]
    requested_by_email: str
    requested_by_name: str
    user: str
    display_name: str = ""
    principal_name: str = ""
    primary_address: str = ""
    provider_enabled: bool = False
    supported_permission_types: list[str] = Field(default_factory=list)
    permission_counts: dict[str, int] = Field(default_factory=dict)
    note: str = ""
    mailbox_count: int = 0
    scanned_mailbox_count: int = 0
    mailboxes: list[DelegateMailboxResponse] = Field(default_factory=list)
    requested_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress_current: int = 0
    progress_total: int = 0
    progress_message: str = ""
    error: Optional[str] = None
    events: list[OneDriveCopyJobEventResponse] = Field(default_factory=list)


class EmailgisticsHelperRequest(BaseModel):
    """Request body for the Emailgistics Helper tool."""

    user_mailbox: str = Field(min_length=3, max_length=320)
    shared_mailbox: str = Field(min_length=3, max_length=320)


class EmailgisticsHelperStepResponse(BaseModel):
    """One step result returned by Emailgistics Helper."""

    key: Literal["full_access", "send_as", "addin_group"]
    label: str
    status: Literal["pending", "completed", "already_present", "failed"]
    message: str = ""


class EmailgisticsHelperResponse(BaseModel):
    """Result payload for one Emailgistics Helper execution."""

    status: Literal["completed", "failed"]
    user_mailbox: str
    shared_mailbox: str
    resolved_user_display_name: str = ""
    resolved_user_principal_name: str = ""
    resolved_shared_display_name: str = ""
    resolved_shared_principal_name: str = ""
    addin_group_name: str = ""
    note: str = ""
    error: str = ""
    steps: list[EmailgisticsHelperStepResponse] = Field(default_factory=list)


class OneDriveCopyJobResponse(BaseModel):
    """Status payload for one OneDrive copy background job."""

    job_id: str
    site_scope: str
    status: Literal["queued", "running", "completed", "failed"]
    phase: Literal["queued", "resolving_drives", "enumerating", "creating_folders", "dispatching_copy", "completed", "failed"]
    requested_by_email: str
    requested_by_name: str
    source_upn: str
    destination_upn: str
    destination_folder: str
    test_mode: bool = False
    test_file_limit: int = 25
    exclude_system_folders: bool = True
    requested_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress_current: int = 0
    progress_total: int = 0
    progress_message: str = ""
    total_folders_found: int = 0
    total_files_found: int = 0
    folders_created: int = 0
    files_dispatched: int = 0
    files_failed: int = 0
    error: Optional[str] = None
    events: list[OneDriveCopyJobEventResponse] = Field(default_factory=list)


class AzureDirectoryObject(BaseModel):
    """Normalized Entra directory object row."""

    id: str
    display_name: str
    object_type: Literal[
        "user",
        "group",
        "enterprise_app",
        "app_registration",
        "directory_role",
    ]
    principal_name: str = ""
    mail: str = ""
    app_id: str = ""
    enabled: Optional[bool] = None
    extra: dict[str, str] = Field(default_factory=dict)


class AzureCostPoint(BaseModel):
    """Daily cost trend point."""

    date: str
    cost: float
    currency: str = "USD"


class AzureCostBreakdownItem(BaseModel):
    """Cost grouped by a chosen Azure dimension."""

    label: str
    amount: float
    currency: str = "USD"
    share: float = 0.0


class AzureAdvisorRecommendation(BaseModel):
    """Normalized Azure Advisor recommendation."""

    id: str
    category: str
    impact: str
    recommendation_type: str = ""
    title: str
    description: str
    subscription_id: str = ""
    subscription_name: str = ""
    resource_id: str = ""
    annual_savings: float = 0.0
    monthly_savings: float = 0.0
    currency: str = "USD"


class AzureCostSummary(BaseModel):
    """Top-line Azure spend summary for the current lookback window."""

    lookback_days: int
    total_cost: float
    currency: str = "USD"
    top_service: str = ""
    top_subscription: str = ""
    top_resource_group: str = ""
    recommendation_count: int = 0
    potential_monthly_savings: float = 0.0


class AzureSavingsEvidenceRow(BaseModel):
    """One evidence row explaining why an Azure savings opportunity was flagged."""

    label: str
    value: str


class AzureSavingsAggregateRow(BaseModel):
    """Count and value rollup for a savings dimension."""

    label: str
    count: int = 0
    estimated_monthly_savings: float = 0.0


class AzureSavingsOpportunity(BaseModel):
    """Normalized Azure savings opportunity from heuristics or Advisor."""

    id: str
    category: Literal["compute", "storage", "network", "commitment", "other"]
    opportunity_type: str
    source: Literal["heuristic", "advisor"]
    title: str
    summary: str
    subscription_id: str = ""
    subscription_name: str = ""
    resource_group: str = ""
    location: str = ""
    resource_id: str = ""
    resource_name: str = ""
    resource_type: str = ""
    current_monthly_cost: Optional[float] = None
    estimated_monthly_savings: Optional[float] = None
    currency: str = "USD"
    quantified: bool = False
    estimate_basis: str = ""
    effort: Literal["low", "medium", "high"] = "medium"
    risk: Literal["low", "medium", "high"] = "medium"
    confidence: Literal["low", "medium", "high"] = "medium"
    recommended_steps: list[str] = Field(default_factory=list)
    evidence: list[AzureSavingsEvidenceRow] = Field(default_factory=list)
    portal_url: str = ""
    follow_up_route: str = ""


class AzureSavingsSummary(BaseModel):
    """Headline rollup for the Azure savings workspace."""

    currency: str = "USD"
    total_opportunities: int = 0
    quantified_opportunities: int = 0
    quantified_monthly_savings: float = 0.0
    quick_win_count: int = 0
    quick_win_monthly_savings: float = 0.0
    unquantified_opportunity_count: int = 0
    by_category: list[AzureSavingsAggregateRow] = Field(default_factory=list)
    by_opportunity_type: list[AzureSavingsAggregateRow] = Field(default_factory=list)
    by_effort: list[AzureCountByLabel] = Field(default_factory=list)
    by_risk: list[AzureCountByLabel] = Field(default_factory=list)
    by_confidence: list[AzureCountByLabel] = Field(default_factory=list)
    top_subscriptions: list[AzureSavingsAggregateRow] = Field(default_factory=list)
    top_resource_groups: list[AzureSavingsAggregateRow] = Field(default_factory=list)
    source: str = "cache"
    source_label: str = "Cached heuristic workspace"
    source_description: str = ""
    last_refreshed_at: Optional[str] = None
    cost_context: dict[str, Any] = Field(default_factory=dict)


class AzureOverviewResponse(BaseModel):
    """Azure portal overview payload."""

    subscriptions: int
    management_groups: int
    resources: int
    role_assignments: int
    users: int
    groups: int
    enterprise_apps: int
    app_registrations: int
    directory_roles: int
    cost: AzureCostSummary
    datasets: list[AzureDatasetStatus] = Field(default_factory=list)
    last_refresh: Optional[str] = None


class AzureCostChatRequest(BaseModel):
    """User question for the Azure cost copilot."""

    question: str
    model: Optional[str] = None


class SecurityCopilotChatMessage(BaseModel):
    """One browser-kept transcript turn sent to the security copilot."""

    role: Literal["user", "assistant"]
    content: str


class SecurityCopilotIdentityCandidate(BaseModel):
    """One Azure user candidate resolved from a display-name style lookup."""

    id: str = ""
    display_name: str = ""
    principal_name: str = ""
    mail: str = ""
    match_reason: str = ""


class SecurityCopilotIncident(BaseModel):
    """Normalized incident profile built from the chat intake."""

    lane: Literal[
        "identity_compromise",
        "mailbox_abuse",
        "app_or_service_principal",
        "azure_alert_or_resource",
        "dlp_finding",
        "unknown",
    ] = "unknown"
    summary: str = ""
    timeframe: str = ""
    affected_users: list[str] = Field(default_factory=list)
    affected_mailboxes: list[str] = Field(default_factory=list)
    affected_apps: list[str] = Field(default_factory=list)
    affected_resources: list[str] = Field(default_factory=list)
    alert_names: list[str] = Field(default_factory=list)
    observed_artifacts: list[str] = Field(default_factory=list)
    identity_query: str = ""
    identity_candidates: list[SecurityCopilotIdentityCandidate] = Field(default_factory=list)
    confidence: float = 0.0
    missing_fields: list[str] = Field(default_factory=list)


class SecurityCopilotFollowUpQuestion(BaseModel):
    """One intake question the frontend should surface next."""

    key: str
    label: str
    prompt: str
    placeholder: str = ""
    required: bool = True
    input_type: Literal["text", "textarea", "email", "list"] = "text"
    choices: list[str] = Field(default_factory=list)


class SecurityCopilotPlannedSource(BaseModel):
    """One source the incident copilot plans to query."""

    key: str
    label: str
    status: Literal["planned", "running", "completed", "skipped", "error"] = "planned"
    query_summary: str = ""
    reason: str = ""


class SecurityCopilotSourceResult(BaseModel):
    """One executed or skipped source query result."""

    key: str
    label: str
    status: Literal["completed", "running", "skipped", "error"]
    query_summary: str = ""
    item_count: int = 0
    highlights: list[str] = Field(default_factory=list)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    citations: list["AzureCitation"] = Field(default_factory=list)
    reason: str = ""


class SecurityCopilotJobRef(BaseModel):
    """Tracked safe background job started or observed by the security copilot."""

    job_type: Literal["delegate_mailbox_scan"]
    label: str
    job_id: str
    status: str
    phase: str = ""
    target: str = ""
    summary: str = ""
    started_automatically: bool = True


class SecurityCopilotAnswer(BaseModel):
    """Structured final answer returned by the security copilot."""

    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SecurityCopilotChatRequest(BaseModel):
    """Main request body for the Azure security incident copilot."""

    message: str = ""
    history: list[SecurityCopilotChatMessage] = Field(default_factory=list)
    incident: SecurityCopilotIncident = Field(default_factory=SecurityCopilotIncident)
    jobs: list[SecurityCopilotJobRef] = Field(default_factory=list)
    model: Optional[str] = None


class SecurityAccessReviewMetric(BaseModel):
    """Headline metric shown on the Azure privileged access review page."""

    key: str
    label: str
    value: int = 0
    detail: str = ""
    tone: Literal["slate", "sky", "emerald", "amber", "rose", "violet"] = "slate"


class SecurityAccessReviewPrincipal(BaseModel):
    """One principal with privileged Azure RBAC access in review scope."""

    principal_id: str
    principal_type: str
    object_type: str = ""
    display_name: str = ""
    principal_name: str = ""
    enabled: Optional[bool] = None
    user_type: str = ""
    last_successful_utc: str = ""
    role_names: list[str] = Field(default_factory=list)
    assignment_count: int = 0
    scope_count: int = 0
    highest_privilege: Literal["critical", "elevated", "limited"] = "limited"
    flags: list[str] = Field(default_factory=list)
    subscriptions: list[str] = Field(default_factory=list)


class SecurityAccessReviewAssignment(BaseModel):
    """One privileged Azure RBAC assignment surfaced in the review."""

    assignment_id: str
    principal_id: str
    principal_type: str
    object_type: str = ""
    display_name: str = ""
    principal_name: str = ""
    role_definition_id: str = ""
    role_name: str = ""
    privilege_level: Literal["critical", "elevated", "limited"] = "limited"
    scope: str = ""
    subscription_id: str = ""
    subscription_name: str = ""
    enabled: Optional[bool] = None
    user_type: str = ""
    last_successful_utc: str = ""
    flags: list[str] = Field(default_factory=list)


class SecurityAccessReviewBreakGlassCandidate(BaseModel):
    """One account that looks like an emergency or break-glass identity."""

    user_id: str
    display_name: str = ""
    principal_name: str = ""
    enabled: Optional[bool] = None
    last_successful_utc: str = ""
    matched_terms: list[str] = Field(default_factory=list)
    privileged_assignment_count: int = 0
    has_privileged_access: bool = False
    flags: list[str] = Field(default_factory=list)


class SecurityAccessReviewResponse(BaseModel):
    """Computed Azure privileged access review payload."""

    generated_at: str
    inventory_last_refresh: str = ""
    directory_last_refresh: str = ""
    metrics: list[SecurityAccessReviewMetric] = Field(default_factory=list)
    flagged_principals: list[SecurityAccessReviewPrincipal] = Field(default_factory=list)
    assignments: list[SecurityAccessReviewAssignment] = Field(default_factory=list)
    break_glass_candidates: list[SecurityAccessReviewBreakGlassCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scope_notes: list[str] = Field(default_factory=list)


class SecurityAppHygieneMetric(BaseModel):
    """Headline metric shown on the Azure application hygiene page."""

    key: str
    label: str
    value: int = 0
    detail: str = ""
    tone: Literal["slate", "sky", "emerald", "amber", "rose", "violet"] = "slate"


class SecurityAppHygieneApp(BaseModel):
    """One application registration summarized for hygiene review."""

    application_id: str
    app_id: str = ""
    display_name: str = ""
    sign_in_audience: str = ""
    created_datetime: str = ""
    publisher_domain: str = ""
    verified_publisher_name: str = ""
    owner_count: int = 0
    owners: list[str] = Field(default_factory=list)
    owner_lookup_error: str = ""
    credential_count: int = 0
    password_credential_count: int = 0
    key_credential_count: int = 0
    next_credential_expiry: str = ""
    expired_credential_count: int = 0
    expiring_30d_count: int = 0
    expiring_90d_count: int = 0
    status: Literal["critical", "warning", "healthy", "info"] = "info"
    flags: list[str] = Field(default_factory=list)


class SecurityAppHygieneCredential(BaseModel):
    """One app credential row shown in the hygiene detail table."""

    application_id: str
    app_id: str = ""
    application_display_name: str = ""
    credential_type: Literal["secret", "certificate"] = "secret"
    display_name: str = ""
    key_id: str = ""
    start_date_time: str = ""
    end_date_time: str = ""
    days_until_expiry: int | None = None
    status: Literal["expired", "expiring", "active", "unknown"] = "unknown"
    owner_count: int = 0
    owners: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class SecurityAppHygieneResponse(BaseModel):
    """Computed Azure app registration hygiene payload."""

    generated_at: str
    directory_last_refresh: str = ""
    metrics: list[SecurityAppHygieneMetric] = Field(default_factory=list)
    flagged_apps: list[SecurityAppHygieneApp] = Field(default_factory=list)
    credentials: list[SecurityAppHygieneCredential] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scope_notes: list[str] = Field(default_factory=list)


class SecurityBreakGlassValidationAccount(BaseModel):
    """One account reviewed in the break-glass validation lane."""

    user_id: str
    display_name: str = ""
    principal_name: str = ""
    enabled: Optional[bool] = None
    user_type: str = ""
    account_class: str = ""
    matched_terms: list[str] = Field(default_factory=list)
    has_privileged_access: bool = False
    privileged_assignment_count: int = 0
    last_successful_utc: str = ""
    days_since_last_successful: Optional[int] = None
    last_password_change: str = ""
    days_since_password_change: Optional[int] = None
    is_licensed: Optional[bool] = None
    license_count: int = 0
    on_prem_sync: bool = False
    status: Literal["critical", "warning", "healthy"] = "healthy"
    flags: list[str] = Field(default_factory=list)


class SecurityBreakGlassValidationResponse(BaseModel):
    """Computed Azure break-glass validation payload."""

    generated_at: str
    inventory_last_refresh: str = ""
    directory_last_refresh: str = ""
    metrics: list[SecurityAccessReviewMetric] = Field(default_factory=list)
    accounts: list[SecurityBreakGlassValidationAccount] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scope_notes: list[str] = Field(default_factory=list)


class SecurityDirectoryRoleReviewRole(BaseModel):
    """One Entra directory role summarized for the security review lane."""

    role_id: str
    display_name: str = ""
    description: str = ""
    privilege_level: Literal["critical", "elevated", "limited"] = "limited"
    member_count: int = 0
    flagged_member_count: int = 0
    flags: list[str] = Field(default_factory=list)


class SecurityDirectoryRoleReviewMembership(BaseModel):
    """One direct directory-role membership surfaced in the review."""

    role_id: str
    role_name: str = ""
    role_description: str = ""
    privilege_level: Literal["critical", "elevated", "limited"] = "limited"
    principal_id: str
    principal_type: str = ""
    object_type: str = ""
    display_name: str = ""
    principal_name: str = ""
    enabled: Optional[bool] = None
    user_type: str = ""
    last_successful_utc: str = ""
    assignment_type: str = "direct"
    status: Literal["critical", "warning", "healthy"] = "healthy"
    flags: list[str] = Field(default_factory=list)


class SecurityDirectoryRoleReviewResponse(BaseModel):
    """Computed Azure direct directory-role review payload."""

    generated_at: str
    directory_last_refresh: str = ""
    access_available: bool = False
    access_message: str = ""
    metrics: list[SecurityAccessReviewMetric] = Field(default_factory=list)
    roles: list[SecurityDirectoryRoleReviewRole] = Field(default_factory=list)
    memberships: list[SecurityDirectoryRoleReviewMembership] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scope_notes: list[str] = Field(default_factory=list)


class SecurityConditionalAccessPolicy(BaseModel):
    """One conditional access policy summarized for change tracking."""

    policy_id: str
    display_name: str = ""
    state: str = ""
    created_date_time: str = ""
    modified_date_time: str = ""
    user_scope_summary: str = ""
    application_scope_summary: str = ""
    grant_controls: list[str] = Field(default_factory=list)
    session_controls: list[str] = Field(default_factory=list)
    impact_level: Literal["critical", "warning", "healthy", "info"] = "info"
    risk_tags: list[str] = Field(default_factory=list)


class SecurityConditionalAccessChange(BaseModel):
    """One recent conditional access change event."""

    event_id: str
    activity_date_time: str = ""
    activity_display_name: str = ""
    result: str = ""
    initiated_by_display_name: str = ""
    initiated_by_principal_name: str = ""
    initiated_by_type: Literal["user", "app", "unknown"] = "unknown"
    target_policy_id: str = ""
    target_policy_name: str = ""
    impact_level: Literal["critical", "warning", "healthy", "info"] = "info"
    change_summary: str = ""
    modified_properties: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class SecurityConditionalAccessTrackerResponse(BaseModel):
    """Computed Azure conditional access change-tracker payload."""

    generated_at: str
    conditional_access_last_refresh: str = ""
    access_available: bool = False
    access_message: str = ""
    metrics: list[SecurityAccessReviewMetric] = Field(default_factory=list)
    policies: list[SecurityConditionalAccessPolicy] = Field(default_factory=list)
    changes: list[SecurityConditionalAccessChange] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scope_notes: list[str] = Field(default_factory=list)


class SecurityWorkspaceLaneSummary(BaseModel):
    """One lightweight lane summary for the Azure security workspace hub."""

    lane_key: str
    status: Literal["critical", "warning", "healthy", "info", "unavailable"] = "info"
    attention_score: int = 0
    attention_count: int = 0
    attention_label: str = ""
    secondary_label: str = ""
    refresh_at: str = ""
    access_available: bool = True
    access_message: str = ""
    warning_count: int = 0
    summary_mode: Literal["count", "availability", "manual"] = "count"


class SecurityWorkspaceSummaryResponse(BaseModel):
    """Top-level Azure security workspace summary payload."""

    generated_at: str
    workspace_last_refresh: str = ""
    lanes: list[SecurityWorkspaceLaneSummary] = Field(default_factory=list)


SecurityFindingExceptionScope = Literal["directory_user"]
SecurityFindingExceptionFindingKey = Literal[
    "all-findings",
    "priority-user",
    "stale-signin",
    "disabled-licensed",
    "guest-user",
    "on-prem-synced",
    "shared-service",
]
SecurityFindingExceptionStatus = Literal["active", "restored"]


class SecurityFindingException(BaseModel):
    """One durable exception that suppresses a security finding from review queues."""

    exception_id: str
    scope: SecurityFindingExceptionScope = "directory_user"
    finding_key: SecurityFindingExceptionFindingKey = "all-findings"
    finding_label: str = "All user-security findings"
    entity_id: str
    entity_label: str = ""
    entity_subtitle: str = ""
    reason: str = ""
    status: SecurityFindingExceptionStatus = "active"
    created_at: str
    updated_at: str
    created_by_email: str = ""
    created_by_name: str = ""
    updated_by_email: str = ""
    updated_by_name: str = ""


class SecurityFindingExceptionCreateRequest(BaseModel):
    """Request body for marking a security finding as an approved exception."""

    scope: SecurityFindingExceptionScope = "directory_user"
    finding_key: SecurityFindingExceptionFindingKey = "all-findings"
    finding_label: str = Field(default="All user-security findings", max_length=120)
    entity_id: str = Field(min_length=1, max_length=200)
    entity_label: str = Field(default="", max_length=300)
    entity_subtitle: str = Field(default="", max_length=300)
    reason: str = Field(min_length=1, max_length=2000)


SecurityDeviceActionType = Literal[
    "device_sync",
    "device_remote_lock",
    "device_retire",
    "device_wipe",
    "device_reassign_primary_user",
    # MDE (Microsoft Defender for Endpoint) actions — use mdeDeviceId, not Intune deviceId
    "isolate_device",
    "unisolate_device",
    "run_av_scan",
    "collect_investigation_package",
    "restrict_app_execution",
    # Red Canary parity — MDE advanced response
    "stop_and_quarantine_file",
    "start_investigation",
    "create_block_indicator",
    "unrestrict_app_execution",
]

SecurityDeviceActionJobStatus = Literal["queued", "running", "completed", "failed"]


class SecurityDeviceComplianceDevice(BaseModel):
    """One Intune-managed device row surfaced in the security lane."""

    id: str
    device_name: str
    operating_system: str = ""
    operating_system_version: str = ""
    compliance_state: str = ""
    management_state: str = ""
    owner_type: str = ""
    enrollment_type: str = ""
    last_sync_date_time: str = ""
    last_sync_age_days: int | None = None
    azure_ad_device_id: str = ""
    primary_users: list[UserAdminReference] = Field(default_factory=list)
    risk_level: Literal["critical", "high", "medium", "low"] = "low"
    finding_tags: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    recommended_fix_action: SecurityDeviceActionType | None = None
    recommended_fix_label: str = ""
    recommended_fix_reason: str = ""
    recommended_fix_requires_user_picker: bool = False
    action_ready: bool = False
    supported_actions: list[SecurityDeviceActionType] = Field(default_factory=list)
    action_blockers: list[str] = Field(default_factory=list)


class SecurityDeviceComplianceResponse(BaseModel):
    """Computed Azure device-compliance review payload."""

    generated_at: str
    device_last_refresh: str = ""
    access_available: bool = False
    access_message: str = ""
    metrics: list[SecurityAccessReviewMetric] = Field(default_factory=list)
    devices: list[SecurityDeviceComplianceDevice] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scope_notes: list[str] = Field(default_factory=list)


class SecurityDeviceActionRequest(BaseModel):
    """Queue one Azure security device action job."""

    action_type: SecurityDeviceActionType
    device_ids: list[str] = Field(default_factory=list, min_length=1)
    reason: str = ""
    confirm_device_count: int | None = None
    confirm_device_names: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class SecurityDeviceActionJob(BaseModel):
    """Queued Azure security device action job."""

    job_id: str
    status: SecurityDeviceActionJobStatus
    action_type: SecurityDeviceActionType
    device_ids: list[str] = Field(default_factory=list)
    device_names: list[str] = Field(default_factory=list)
    requested_by_email: str
    requested_by_name: str = ""
    requested_at: str
    started_at: str | None = None
    completed_at: str | None = None
    progress_current: int = 0
    progress_total: int = 0
    progress_message: str = ""
    success_count: int = 0
    failure_count: int = 0
    results_ready: bool = False
    reason: str = ""
    error: str = ""


class SecurityDeviceActionJobResult(BaseModel):
    """One per-device execution result from an Azure security device action job."""

    device_id: str
    device_name: str = ""
    azure_ad_device_id: str = ""
    success: bool
    summary: str = ""
    error: str = ""
    before_summary: dict[str, Any] = Field(default_factory=dict)
    after_summary: dict[str, Any] = Field(default_factory=dict)


class SecurityDeviceFixPlanRequest(BaseModel):
    """Request a deterministic remediation preview for selected devices."""

    device_ids: list[str] = Field(default_factory=list, min_length=1)


class SecurityDeviceFixPlanDevice(BaseModel):
    """One device inside a smart remediation preview."""

    device_id: str
    device_name: str = ""
    risk_level: Literal["critical", "high", "medium", "low"] = "low"
    finding_tags: list[str] = Field(default_factory=list)
    action_type: SecurityDeviceActionType | None = None
    action_label: str = ""
    action_reason: str = ""
    requires_primary_user: bool = False
    primary_users: list[UserAdminReference] = Field(default_factory=list)
    skip_reason: str = ""


class SecurityDeviceFixPlanGroup(BaseModel):
    """Grouped action summary for a smart remediation preview."""

    action_type: SecurityDeviceActionType
    action_label: str
    device_count: int = 0
    device_ids: list[str] = Field(default_factory=list)
    device_names: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False


class SecurityDeviceFixPlanResponse(BaseModel):
    """Deterministic smart-remediation preview for selected devices."""

    generated_at: str
    device_ids: list[str] = Field(default_factory=list)
    items: list[SecurityDeviceFixPlanDevice] = Field(default_factory=list)
    groups: list[SecurityDeviceFixPlanGroup] = Field(default_factory=list)
    devices_requiring_primary_user: list[SecurityDeviceFixPlanDevice] = Field(default_factory=list)
    skipped_devices: list[SecurityDeviceFixPlanDevice] = Field(default_factory=list)
    destructive_device_count: int = 0
    destructive_device_names: list[str] = Field(default_factory=list)
    requires_destructive_confirmation: bool = False
    warnings: list[str] = Field(default_factory=list)


class SecurityDeviceFixPlanExecuteRequest(BaseModel):
    """Execute an approved smart-remediation preview."""

    device_ids: list[str] = Field(default_factory=list, min_length=1)
    reason: str = ""
    assignment_map: dict[str, str] = Field(default_factory=dict)
    confirm_device_count: int | None = None
    confirm_device_names: list[str] = Field(default_factory=list)


class SecurityDeviceActionBatchJob(BaseModel):
    """One child action job inside a smart-remediation batch."""

    child_job_id: str
    action_type: SecurityDeviceActionType
    action_label: str = ""
    device_ids: list[str] = Field(default_factory=list)
    device_names: list[str] = Field(default_factory=list)
    status: SecurityDeviceActionJobStatus = "queued"
    progress_current: int = 0
    progress_total: int = 0
    success_count: int = 0
    failure_count: int = 0
    results_ready: bool = False


class SecurityDeviceActionBatchStatus(BaseModel):
    """Status payload for a smart-remediation device batch."""

    batch_id: str
    status: SecurityDeviceActionJobStatus = "queued"
    requested_by_email: str
    requested_by_name: str = ""
    requested_at: str
    started_at: str | None = None
    completed_at: str | None = None
    progress_current: int = 0
    progress_total: int = 0
    progress_message: str = ""
    success_count: int = 0
    failure_count: int = 0
    results_ready: bool = False
    item_count: int = 0
    destructive_device_count: int = 0
    destructive_device_names: list[str] = Field(default_factory=list)
    child_jobs: list[SecurityDeviceActionBatchJob] = Field(default_factory=list)
    error: str = ""


class SecurityDeviceActionBatchResult(BaseModel):
    """Per-device result row for a smart-remediation batch."""

    device_id: str
    device_name: str = ""
    action_type: SecurityDeviceActionType
    action_label: str = ""
    child_job_id: str = ""
    status: SecurityDeviceActionJobStatus = "queued"
    success: bool | None = None
    summary: str = ""
    error: str = ""
    assignment_user_id: str = ""
    assignment_user_display_name: str = ""


class AzureRecommendationDismissRequest(BaseModel):
    """Dismiss a persisted recommendation with an optional operator note."""

    reason: str = ""


class AzureRecommendationReopenRequest(BaseModel):
    """Reopen a previously dismissed recommendation."""

    note: str = ""


class AzureRecommendationActionStateRequest(BaseModel):
    """Update the operator workflow state for a persisted recommendation."""

    action_state: str
    action_type: str = ""
    note: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AzureRecommendationActionField(BaseModel):
    """One metadata field supported by a recommendation action type."""

    key: str
    label: str
    description: str = ""
    required: bool = False


class AzureRecommendationActionOption(BaseModel):
    """One allowlisted option exposed by an action contract item."""

    key: str
    label: str
    description: str = ""
    default_dry_run: bool = True
    allow_apply: bool = False
    repeatable: bool = True


class AzureRecommendationActionContractItem(BaseModel):
    """Normalized action contract for one recommendation action."""

    action_type: Literal["create_ticket", "send_alert", "export", "run_safe_script"]
    label: str
    description: str
    category: Literal["jira", "teams", "export", "script"]
    status: Literal["available", "pending", "completed", "blocked", "future"]
    can_execute: bool
    requires_admin: bool = True
    repeatable: bool = False
    pending_action_state: str = ""
    completed_action_state: str = ""
    current_action_state: str = ""
    blocked_reason: str = ""
    note_placeholder: str = ""
    metadata_fields: list[AzureRecommendationActionField] = Field(default_factory=list)
    options: list[AzureRecommendationActionOption] = Field(default_factory=list)
    latest_event: dict[str, Any] = Field(default_factory=dict)


class AzureRecommendationActionContractResponse(BaseModel):
    """Action contract payload for one persisted recommendation."""

    recommendation_id: str
    lifecycle_status: str
    current_action_state: str
    generated_at: str
    actions: list[AzureRecommendationActionContractItem] = Field(default_factory=list)


class AzureRecommendationCreateTicketRequest(BaseModel):
    """Create a Jira follow-up for a persisted recommendation."""

    project_key: str = ""
    issue_type: str = ""
    summary: str = ""
    note: str = ""


class AzureRecommendationCreateTicketResponse(BaseModel):
    """Stored Jira linkage for a recommendation follow-up ticket."""

    recommendation: dict[str, Any] = Field(default_factory=dict)
    ticket_key: str = ""
    ticket_url: str = ""
    jira_issue_id: str = ""
    project_key: str = ""
    issue_type: str = ""
    summary: str = ""


class AzureRecommendationSendAlertRequest(BaseModel):
    """Send a Teams alert for a persisted recommendation."""

    channel: str = ""
    teams_webhook_url: str = ""
    note: str = ""


class AzureRecommendationSendAlertResponse(BaseModel):
    """Stored Teams delivery outcome for a recommendation alert."""

    recommendation: dict[str, Any] = Field(default_factory=dict)
    alert_status: str = ""
    delivery_channel: str = ""
    sent_at: str = ""


class AzureRecommendationRunSafeScriptRequest(BaseModel):
    """Execute an allowlisted safe remediation hook for a recommendation."""

    hook_key: str = ""
    dry_run: bool = True
    note: str = ""


class AzureRecommendationRunSafeScriptResponse(BaseModel):
    """Stored outcome for a safe remediation hook execution."""

    recommendation: dict[str, Any] = Field(default_factory=dict)
    hook_key: str = ""
    hook_label: str = ""
    action_status: str = ""
    dry_run: bool = True
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0
    exit_code: int | None = None
    output_excerpt: str = ""


class AzureAllocationRuleRequest(BaseModel):
    """Create or version an allocation rule in the local FinOps store."""

    rule_id: str = ""
    name: str
    description: str = ""
    rule_type: Literal["tag", "regex", "percentage", "shared"]
    target_dimension: Literal["team", "application", "product"]
    priority: int = 100
    enabled: bool = True
    condition: dict[str, Any] = Field(default_factory=dict)
    allocation: dict[str, Any] = Field(default_factory=dict)


class AzureAllocationRunRequest(BaseModel):
    """Trigger a non-destructive allocation run for one or more dimensions."""

    target_dimensions: list[Literal["team", "application", "product"]] = Field(default_factory=list)
    run_label: str = ""
    note: str = ""


class AzureCitation(BaseModel):
    """Grounding citation attached to an Azure AI response."""

    source_type: str
    label: str
    detail: str = ""


class AzureCostChatResponse(BaseModel):
    """Grounded Azure cost copilot answer."""

    answer: str
    model_used: str
    generated_at: str
    citations: list[AzureCitation] = Field(default_factory=list)


class SecurityCopilotChatResponse(BaseModel):
    """End-to-end response for the Azure security incident copilot."""

    phase: Literal["needs_input", "running_jobs", "complete"]
    assistant_message: str
    incident: SecurityCopilotIncident = Field(default_factory=SecurityCopilotIncident)
    follow_up_questions: list[SecurityCopilotFollowUpQuestion] = Field(default_factory=list)
    planned_sources: list[SecurityCopilotPlannedSource] = Field(default_factory=list)
    source_results: list[SecurityCopilotSourceResult] = Field(default_factory=list)
    jobs: list[SecurityCopilotJobRef] = Field(default_factory=list)
    answer: SecurityCopilotAnswer = Field(default_factory=SecurityCopilotAnswer)
    citations: list[AzureCitation] = Field(default_factory=list)
    model_used: str
    generated_at: str


# ── Azure Alerts ──────────────────────────────────────────────────────────────


class AzureAlertRuleCreate(BaseModel):
    name: str
    domain: Literal["cost", "vms", "identity", "resources"]
    trigger_type: str
    trigger_config: dict[str, Any] = {}
    frequency: Literal["immediate", "hourly", "daily", "weekly"]
    schedule_time: str = "09:00"        # HH:MM, always UTC
    schedule_days: str = "0,1,2,3,4"   # comma-separated 0=Mon..6=Sun
    recipients: str = ""                # comma-separated emails
    teams_webhook_url: str = ""
    custom_subject: str = ""
    custom_message: str = ""


class AzureAlertRuleUpdate(AzureAlertRuleCreate):
    pass


class AzureAlertRuleResponse(AzureAlertRuleCreate):
    id: str
    enabled: bool
    last_run: str | None = None
    last_sent: str | None = None
    created_at: str
    updated_at: str


class AzureAlertTestResponse(BaseModel):
    match_count: int
    sample_items: list[dict[str, Any]]


class AzureAlertHistoryItem(BaseModel):
    id: str
    rule_id: str
    rule_name: str
    trigger_type: str
    sent_at: str
    recipients: str
    match_count: int
    match_summary: dict[str, Any]
    status: str
    error: str | None = None


class AzureChatParseRequest(BaseModel):
    message: str


class AzureChatParseResponse(BaseModel):
    parsed: bool
    rule: AzureAlertRuleCreate | None = None
    summary: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# User administration models
# ---------------------------------------------------------------------------


UserAdminActionType = Literal[
    "disable_sign_in",
    "enable_sign_in",
    "reset_password",
    "revoke_sessions",
    "reset_mfa",
    "unblock_sign_in",
    "update_usage_location",
    "update_profile",
    "set_manager",
    "add_group_membership",
    "remove_group_membership",
    "assign_license",
    "remove_license",
    "add_directory_role",
    "remove_directory_role",
    "mailbox_add_alias",
    "mailbox_remove_alias",
    "mailbox_set_forwarding",
    "mailbox_clear_forwarding",
    "mailbox_convert_type",
    "mailbox_set_delegates",
    "device_sync",
    "device_retire",
    "device_wipe",
    "device_remote_lock",
    "device_reassign_primary_user",
    "exit_group_cleanup",
    "exit_on_prem_deprovision",
    "exit_remove_all_licenses",
    "exit_manual_task_complete",
]

UserAdminJobStatus = Literal["queued", "running", "completed", "failed"]
UserAdminProviderKey = Literal["entra", "mailbox", "device_management", "windows_agent", "workflow"]


class UserAdminReference(BaseModel):
    id: str
    display_name: str
    principal_name: str = ""
    mail: str = ""


class UserAdminCapabilitiesResponse(BaseModel):
    can_manage_users: bool = True
    enabled_providers: dict[UserAdminProviderKey, bool] = Field(default_factory=dict)
    supported_actions: list[UserAdminActionType] = Field(default_factory=list)
    license_catalog: list[dict[str, str]] = Field(default_factory=list)
    group_catalog: list[UserAdminReference] = Field(default_factory=list)
    role_catalog: list[UserAdminReference] = Field(default_factory=list)
    conditional_access_exception_groups: list[UserAdminReference] = Field(default_factory=list)


class UserAdminUserDetailResponse(BaseModel):
    id: str
    display_name: str
    principal_name: str = ""
    mail: str = ""
    enabled: Optional[bool] = None
    user_type: str = "Member"
    department: str = ""
    job_title: str = ""
    office_location: str = ""
    company_name: str = ""
    city: str = ""
    country: str = ""
    mobile_phone: str = ""
    business_phones: list[str] = Field(default_factory=list)
    created_datetime: str = ""
    last_password_change: str = ""
    on_prem_sync: bool = False
    on_prem_domain: str = ""
    on_prem_netbios: str = ""
    on_prem_sam_account_name: str = ""
    on_prem_distinguished_name: str = ""
    usage_location: str = ""
    employee_id: str = ""
    employee_type: str = ""
    preferred_language: str = ""
    proxy_addresses: list[str] = Field(default_factory=list)
    is_licensed: bool = False
    license_count: int = 0
    sku_part_numbers: list[str] = Field(default_factory=list)
    last_interactive_utc: str = ""
    last_interactive_local: str = ""
    last_noninteractive_utc: str = ""
    last_noninteractive_local: str = ""
    last_successful_utc: str = ""
    last_successful_local: str = ""
    manager: UserAdminReference | None = None
    source_directory: str = ""


class UserAdminGroupMembershipResponse(BaseModel):
    id: str
    display_name: str
    mail: str = ""
    security_enabled: bool = False
    group_types: list[str] = Field(default_factory=list)
    object_type: str = "group"


class UserAdminLicenseResponse(BaseModel):
    sku_id: str
    sku_part_number: str = ""
    display_name: str = ""
    state: str = ""
    disabled_plans: list[str] = Field(default_factory=list)
    assigned_by_group: bool = False


class UserAdminRoleResponse(BaseModel):
    id: str
    display_name: str
    description: str = ""
    assignment_type: str = "direct"


class UserAdminMailboxResponse(BaseModel):
    primary_address: str = ""
    aliases: list[str] = Field(default_factory=list)
    forwarding_enabled: bool = False
    forwarding_address: str = ""
    mailbox_type: str = ""
    delegate_delivery_mode: str = ""
    delegates: list[UserAdminReference] = Field(default_factory=list)
    automatic_replies_status: str = ""
    provider_enabled: bool = False
    management_supported: bool = False
    note: str = ""


class UserAdminDeviceResponse(BaseModel):
    id: str
    device_name: str
    operating_system: str = ""
    operating_system_version: str = ""
    compliance_state: str = ""
    management_state: str = ""
    owner_type: str = ""
    enrollment_type: str = ""
    last_sync_date_time: str = ""
    azure_ad_device_id: str = ""
    primary_users: list[UserAdminReference] = Field(default_factory=list)


class UserAdminAuditEntryResponse(BaseModel):
    audit_id: str
    job_id: str = ""
    actor_email: str
    actor_name: str = ""
    target_user_id: str
    target_display_name: str = ""
    provider: UserAdminProviderKey
    action_type: UserAdminActionType
    params_summary: dict[str, Any] = Field(default_factory=dict)
    before_summary: dict[str, Any] = Field(default_factory=dict)
    after_summary: dict[str, Any] = Field(default_factory=dict)
    status: str
    error: str = ""
    created_at: str


class UserAdminJobCreateRequest(BaseModel):
    action_type: UserAdminActionType
    target_user_ids: list[str] = Field(default_factory=list, min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class UserAdminJobResultResponse(BaseModel):
    target_user_id: str
    target_display_name: str = ""
    provider: UserAdminProviderKey
    success: bool
    summary: str = ""
    error: str = ""
    before_summary: dict[str, Any] = Field(default_factory=dict)
    after_summary: dict[str, Any] = Field(default_factory=dict)
    one_time_secret: str | None = None


class UserAdminJobResponse(BaseModel):
    job_id: str
    status: UserAdminJobStatus
    action_type: UserAdminActionType
    provider: UserAdminProviderKey
    target_user_ids: list[str] = Field(default_factory=list)
    requested_by_email: str
    requested_by_name: str = ""
    requested_at: str
    started_at: str | None = None
    completed_at: str | None = None
    progress_current: int = 0
    progress_total: int = 0
    progress_message: str = ""
    success_count: int = 0
    failure_count: int = 0
    results_ready: bool = False
    error: str = ""
    one_time_results_available: bool = False


UserExitWorkflowStatus = Literal["queued", "running", "awaiting_manual", "completed", "failed"]
UserExitStepStatus = Literal["queued", "running", "completed", "failed", "skipped"]
UserExitStepProvider = Literal["entra", "windows_agent", "workflow"]
UserExitReportFilter = Literal["", "disabled_licensed", "active_no_success_30d"]


class UserExitWorkflowSummary(BaseModel):
    workflow_id: str
    user_id: str
    user_display_name: str = ""
    user_principal_name: str = ""
    status: UserExitWorkflowStatus
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    profile_key: str = ""
    on_prem_required: bool = False
    requires_on_prem_username_override: bool = False
    error: str = ""


class UserExitPreflightStepResponse(BaseModel):
    step_key: str
    label: str
    provider: UserExitStepProvider
    will_run: bool = True
    reason: str = ""


class UserExitManualTaskResponse(BaseModel):
    task_id: str = ""
    label: str
    status: Literal["pending", "completed"] = "pending"
    notes: str = ""
    completed_at: str | None = None
    completed_by_email: str = ""
    completed_by_name: str = ""


class UserExitPreflightResponse(BaseModel):
    user_id: str
    user_display_name: str = ""
    user_principal_name: str = ""
    profile_key: str = ""
    profile_label: str = ""
    scope_summary: str = ""
    on_prem_required: bool = False
    requires_on_prem_username_override: bool = False
    on_prem_sam_account_name: str = ""
    on_prem_distinguished_name: str = ""
    mailbox_expected: bool = False
    direct_license_count: int = 0
    direct_licenses: list[UserAdminLicenseResponse] = Field(default_factory=list)
    managed_devices: list[UserAdminDeviceResponse] = Field(default_factory=list)
    manual_tasks: list[UserExitManualTaskResponse] = Field(default_factory=list)
    steps: list[UserExitPreflightStepResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    active_workflow: UserExitWorkflowSummary | None = None


class UserExitWorkflowCreateRequest(BaseModel):
    user_id: str
    typed_upn_confirmation: str
    on_prem_sam_account_name_override: str = ""


class UserExitRetryStepRequest(BaseModel):
    step_id: str


class UserExitWorkflowStepResponse(BaseModel):
    step_id: str
    step_key: str
    label: str
    provider: UserExitStepProvider
    status: UserExitStepStatus
    order_index: int
    profile_key: str = ""
    summary: str = ""
    error: str = ""
    before_summary: dict[str, Any] = Field(default_factory=dict)
    after_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    retry_count: int = 0


class UserExitWorkflowResponse(BaseModel):
    workflow_id: str
    user_id: str
    user_display_name: str = ""
    user_principal_name: str = ""
    requested_by_email: str
    requested_by_name: str = ""
    status: UserExitWorkflowStatus
    profile_key: str = ""
    on_prem_required: bool = False
    requires_on_prem_username_override: bool = False
    on_prem_sam_account_name: str = ""
    on_prem_distinguished_name: str = ""
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str = ""
    steps: list[UserExitWorkflowStepResponse] = Field(default_factory=list)
    manual_tasks: list[UserExitManualTaskResponse] = Field(default_factory=list)


class UserExitManualTaskCompleteRequest(BaseModel):
    notes: str = ""


class UserExitAgentClaimRequest(BaseModel):
    agent_id: str
    profile_keys: list[str] = Field(default_factory=list)


class UserExitAgentClaimResponse(BaseModel):
    step_id: str
    workflow_id: str
    step_key: str
    label: str
    profile_key: str = ""
    user_id: str
    user_display_name: str = ""
    user_principal_name: str = ""
    on_prem_sam_account_name: str = ""
    on_prem_distinguished_name: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    lease_expires_at: str


class UserExitAgentHeartbeatRequest(BaseModel):
    agent_id: str


class UserExitAgentCompleteRequest(BaseModel):
    agent_id: str
    status: Literal["completed", "failed", "skipped"]
    summary: str = ""
    error: str = ""
    before_summary: dict[str, Any] = Field(default_factory=dict)
    after_summary: dict[str, Any] = Field(default_factory=dict)


class AutoReplyStatus(BaseModel):
    """Current automatic-reply / out-of-office state for a mailbox."""

    mailbox: str
    display_name: str = ""
    principal_name: str = ""
    status: str = ""  # "disabled" | "alwaysEnabled" | "scheduled"
    internal_message: str = ""
    external_message: str = ""
    scheduled_start: str = ""  # ISO-8601 or ""
    scheduled_end: str = ""    # ISO-8601 or ""
    external_audience: str = ""  # "none" | "known" | "all"
    provider_enabled: bool = False
    note: str = ""


class SetAutoReplyRequest(BaseModel):
    """Request body for setting a mailbox automatic reply."""

    mailbox: str = Field(min_length=3, max_length=320)
    status: Literal["disabled", "alwaysEnabled", "scheduled"] = "alwaysEnabled"
    internal_message: str = Field(default="", max_length=10000)
    external_message: str = Field(default="", max_length=10000)
    scheduled_start: str = ""   # ISO-8601 datetime or "" (required when status=scheduled)
    scheduled_end: str = ""     # ISO-8601 datetime or "" (required when status=scheduled)
    external_audience: Literal["none", "known", "all"] = "known"


# ---------------------------------------------------------------------------
# Defender autonomous agent
# ---------------------------------------------------------------------------

class DefenderAgentConfigResponse(BaseModel):
    enabled: bool = False
    min_severity: Literal["informational", "low", "medium", "high", "critical"] = "high"
    tier2_delay_minutes: int = 15
    dry_run: bool = False
    updated_at: Optional[str] = None
    updated_by: str = ""


class DefenderAgentConfigUpdate(BaseModel):
    enabled: bool
    min_severity: Literal["informational", "low", "medium", "high", "critical"] = "high"
    tier2_delay_minutes: int = Field(default=15, ge=0, le=1440)
    dry_run: bool = False


class DefenderAgentRunResponse(BaseModel):
    run_id: str
    started_at: str
    completed_at: Optional[str] = None
    alerts_fetched: int = 0
    alerts_new: int = 0
    decisions_made: int = 0
    actions_queued: int = 0
    error: str = ""


class DefenderAgentDecisionItem(BaseModel):
    decision_id: str
    run_id: str
    alert_id: str
    alert_title: str = ""
    alert_severity: str = ""
    alert_category: str = ""
    alert_created_at: str = ""
    service_source: str = ""
    entities: list[dict[str, Any]] = Field(default_factory=list)
    tier: Optional[int] = None
    decision: str = "skip"
    action_type: str = ""
    job_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    executed_at: str = ""
    not_before_at: Optional[str] = None
    cancelled: bool = False
    cancelled_at: Optional[str] = None
    cancelled_by: str = ""
    human_approved: bool = False
    approved_at: Optional[str] = None
    approved_by: str = ""
    alert_raw: dict[str, Any] = Field(default_factory=dict)
    alert_written_back: bool = False


class DefenderAgentDecisionsResponse(BaseModel):
    decisions: list[DefenderAgentDecisionItem]
    total: int


class DefenderAgentSummaryResponse(BaseModel):
    enabled: bool = False
    last_run_at: Optional[str] = None
    last_run_error: str = ""
    total_alerts_today: int = 0
    total_actions_today: int = 0
    pending_approvals: int = 0
    pending_tier2: int = 0
    recent_decisions: list[DefenderAgentDecisionItem] = Field(default_factory=list)
