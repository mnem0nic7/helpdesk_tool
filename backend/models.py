"""Pydantic data models for the OIT Helpdesk Dashboard API."""

from __future__ import annotations

from typing import Optional

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
    created: str
    updated: str
    resolved: str
    request_type: str
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
    request_type_id: Optional[str] = None


class TicketTransitionRequest(BaseModel):
    """Transition a single issue to another workflow state."""

    transition_id: str


class TicketCommentRequest(BaseModel):
    """Add a comment to a single issue."""

    comment: str
    public: bool = False


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
