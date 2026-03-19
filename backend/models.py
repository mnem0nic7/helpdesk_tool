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
    created: str
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
    # SLA resolution
    sla_resolution_status: str = ""
    sla_resolution_breach_time: str = ""
    sla_resolution_remaining_millis: Optional[int] = None
    # Additional fields
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    work_category: str = ""
    organizations: list[str] = Field(default_factory=list)
    attachment_count: int = 0


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
