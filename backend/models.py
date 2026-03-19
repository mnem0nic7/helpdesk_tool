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
