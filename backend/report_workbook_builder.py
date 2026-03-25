"""XlsxWriter-based workbook generation for executive OIT report exports."""

from __future__ import annotations

import logging
import os
import re
import statistics
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell

from jira_client import JiraClient
from metrics import extract_sla_info, issue_to_row, parse_dt, percentile
from models import ReportConfig, ReportTemplate
from routes_tickets import _match
from site_context import issue_matches_scope

logger = logging.getLogger(__name__)

_REPORT_WINDOW_LABELS: dict[str, str] = {
    "created": "Created",
    "updated": "Updated",
    "resolved": "Resolved",
}

_WINDOW_EXPORT_SPECS: list[tuple[str, int]] = [
    ("7 Day", 7),
    ("30 Day", 30),
]

_MASTER_CHANGELOG_PREFETCH_LIMIT = 250
_MASTER_CHANGELOG_SKIP_PREFIX = "Skipped Jira changelog fetch for large master export"

_DETAIL_WIDTH_DEFAULTS: dict[str, int] = {
    "key": 12,
    "summary": 50,
    "description": 60,
    "issue_type": 18,
    "status": 22,
    "status_category": 18,
    "priority": 12,
    "resolution": 18,
    "assignee": 25,
    "assignee_account_id": 20,
    "reporter": 25,
    "created": 22,
    "updated": 22,
    "resolved": 22,
    "request_type": 25,
    "work_category": 20,
    "calendar_ttr_hours": 12,
    "age_days": 10,
    "days_since_update": 14,
    "comment_count": 10,
    "last_comment_date": 22,
    "last_comment_author": 25,
    "excluded": 10,
    "sla_first_response_status": 18,
    "sla_resolution_status": 18,
    "response_followup_status": 22,
    "first_response_2h_status": 16,
    "daily_followup_status": 18,
    "last_support_touch_date": 22,
    "support_touch_count": 12,
    "labels": 30,
    "components": 25,
    "organizations": 30,
    "attachment_count": 12,
    "comments_text": 60,
}

_FIELD_LABELS: dict[str, str] = {
    "key": "Key",
    "summary": "Summary",
    "description": "Description",
    "issue_type": "Type",
    "status": "Status",
    "status_category": "Status Category",
    "priority": "Priority",
    "resolution": "Resolution",
    "assignee": "Assignee",
    "assignee_account_id": "Assignee ID",
    "reporter": "Reporter",
    "created": "Created",
    "updated": "Updated",
    "resolved": "Resolved",
    "request_type": "Request Type",
    "work_category": "Work Category",
    "calendar_ttr_hours": "TTR (h)",
    "age_days": "Age (d)",
    "days_since_update": "Days Since Update",
    "comment_count": "Comments",
    "last_comment_date": "Last Comment",
    "last_comment_author": "Last Commenter",
    "excluded": "Excluded",
    "sla_first_response_status": "SLA Response",
    "sla_resolution_status": "SLA Resolution",
    "response_followup_status": "Response + Follow-Up",
    "first_response_2h_status": "Response <=2h",
    "daily_followup_status": "Daily Follow-Up",
    "last_support_touch_date": "Last Public Agent Touch",
    "support_touch_count": "Public Agent Touch Count",
    "labels": "Labels",
    "components": "Components",
    "organizations": "Organizations",
    "attachment_count": "Attachments",
    "comments_text": "All Comments",
}

_DEFAULT_COLUMNS: list[str] = [
    "key",
    "summary",
    "issue_type",
    "status",
    "priority",
    "assignee",
    "created",
    "resolved",
    "calendar_ttr_hours",
]

_TERMINAL_STATUSES = {
    "resolved",
    "closed",
    "done",
    "cancelled",
    "declined",
    "canceled",
}
_PRIORITY_RANK = {"lowest": 0, "low": 1, "medium": 2, "high": 3, "highest": 4}
_ESCALATION_MARKERS = ("tier2", "tier3", "escalation", "escalated")
_AGING_BUCKETS: list[tuple[int | None, str]] = [
    (3, "0-3 days"),
    (7, "4-7 days"),
    (14, "8-14 days"),
    (30, "15-30 days"),
    (60, "31-60 days"),
    (None, "60+ days"),
]


@dataclass
class ReportIssueFact:
    """Ticket-level facts reused across every sheet in one workbook build."""

    key: str
    issue: dict[str, Any]
    row: dict[str, Any]
    created_dt: datetime | None
    updated_dt: datetime | None
    resolved_dt: datetime | None
    ttr_hours: float | None
    open_age_hours: float | None
    first_response_hours: float | None
    resolution_sla_elapsed_hours: float | None
    sla_response_status: str
    sla_resolution_status: str
    comment_count: int
    followup_authoritative: bool = False
    first_response_authoritative: bool = False
    labels_lower: list[str] = field(default_factory=list)
    components_lower: list[str] = field(default_factory=list)
    first_resolved_dt: datetime | None = None
    reopen_count: int = 0
    assignee_change_count: int = 0
    priority_increase_count: int = 0
    is_escalated: bool = False
    escalation_reasons: list[str] = field(default_factory=list)
    escalation_event_dates: set[date] = field(default_factory=set)
    changelog_loaded: bool = False
    changelog_error: str = ""

    @property
    def is_open(self) -> bool:
        return str(self.row.get("status_category") or "") != "Done"


@dataclass
class TemplateGap:
    """Human-readable data-quality or readiness note."""

    template_name: str
    window_label: str
    readiness: str
    limitation: str
    recommendation: str


@dataclass
class ChartTableInfo:
    """Coordinates for a written table that charts can reference."""

    header_row: int
    first_data_row: int
    last_data_row: int
    column_map: dict[str, int]


@dataclass
class MasterSheetSummary:
    """Metadata for one master-workbook detail sheet."""

    report_name: str
    sheet_name: str
    window_label: str
    window_field_label: str
    window_start: date
    window_end: date
    category: str
    readiness: str
    view_type: str
    row_count: int
    description: str
    notes: str
    report_kind: str
    table_info: ChartTableInfo
    total_row: int | None = None
    metric_row: int | None = None


@dataclass
class TrendAnomaly:
    """A suspicious daily escalation spike detected during build."""

    row_idx: int
    excel_row: int
    day: str
    count: int
    baseline_peak: int


def _sanitize_for_excel(value: str) -> str:
    if value and value[0] in ("=", "+", "-", "@"):
        return "\t" + value
    return value


def _cell_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return _sanitize_for_excel(", ".join(str(part) for part in value))
    if value is None:
        return ""
    if isinstance(value, str):
        return _sanitize_for_excel(value)
    return value


def _cell_ref(row_idx: int, col_idx: int, *, absolute: bool = False) -> str:
    return xl_rowcol_to_cell(row_idx, col_idx, row_abs=absolute, col_abs=absolute)


def _range_ref(
    first_row: int,
    first_col: int,
    last_row: int,
    last_col: int,
    *,
    absolute: bool = False,
) -> str:
    start = _cell_ref(first_row, first_col, absolute=absolute)
    end = _cell_ref(last_row, last_col, absolute=absolute)
    return f"{start}:{end}"


def _safe_sum_formula(range_ref: str) -> str:
    return f"SUM({range_ref})"


def _safe_max_formula(range_ref: str) -> str:
    return f'IF(COUNTA({range_ref})=0,0,MAX({range_ref}))'


def _weighted_average_formula(weight_range: str, value_range: str) -> str:
    total = _safe_sum_formula(weight_range)
    return f"IF({total}=0,0,SUMPRODUCT({weight_range},{value_range})/{total})"


def _status_match_formula(label_range: str, target: str, value_range: str, denominator_formula: str) -> str:
    return (
        f'IF(({denominator_formula})=0,0,IFERROR('
        f'INDEX({value_range},MATCH("{target}",{label_range},0))/({denominator_formula}),0))'
    )


def _sanitize_sheet_name(name: str) -> str:
    cleaned = re.sub(r"[\[\]\*:/\\?]", " ", str(name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:31] or "Report"


def _unique_sheet_name(name: str, used_names: set[str]) -> str:
    base = _sanitize_sheet_name(name)
    candidate = base
    suffix = 2
    while candidate in used_names:
        suffix_text = f" ({suffix})"
        candidate = f"{base[: max(1, 31 - len(suffix_text))]}{suffix_text}"
        suffix += 1
    used_names.add(candidate)
    return candidate


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _date_field_for_report_window_config(config: ReportConfig, *, report_name: str = "") -> str:
    sort_field = str(config.sort_field or "").strip().lower()
    if sort_field in _REPORT_WINDOW_LABELS:
        return sort_field

    name = str(report_name or "").strip().lower()
    if any(token in name for token in ("resolution", "mttr", "reopen", "csat")):
        return "resolved"
    if any(token in name for token in ("escalation", "utilization")):
        return "updated"
    return "created"


def _window_bounds(window_days: int, *, today: date) -> tuple[date, date]:
    return today - timedelta(days=max(window_days - 1, 0)), today


def _prior_window_bounds(window_days: int, *, today: date) -> tuple[date, date]:
    current_start, _ = _window_bounds(window_days, today=today)
    prior_end = current_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=max(window_days - 1, 0))
    return prior_start, prior_end


def _date_for_window(fact: ReportIssueFact, window_field: str) -> date | None:
    if window_field == "updated" and fact.updated_dt:
        return fact.updated_dt.date()
    if window_field == "resolved" and fact.resolved_dt:
        return fact.resolved_dt.date()
    if fact.created_dt:
        return fact.created_dt.date()
    return None


def _percentile_hours(values: list[float], p: float) -> float | None:
    result = percentile(values, p)
    return round(float(result), 1) if result is not None else None


def _mean_hours(values: list[float]) -> float | None:
    return round(float(statistics.mean(values)), 1) if values else None


def _group_key(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(part) for part in value) if value else "(none)"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value or "").strip()
    return text or "(none)"


def _report_view_type(config: ReportConfig) -> str:
    return "Grouped" if config.group_by else "Detail"


def _is_terminal_status_name(value: str | None) -> bool:
    return (value or "").strip().lower() in _TERMINAL_STATUSES


def _priority_increase(from_value: str | None, to_value: str | None) -> bool:
    from_rank = _PRIORITY_RANK.get((from_value or "").strip().lower())
    to_rank = _PRIORITY_RANK.get((to_value or "").strip().lower())
    if from_rank is None or to_rank is None:
        return False
    return to_rank > from_rank


def _matches_escalation_markers(fact: ReportIssueFact) -> bool:
    tokens = fact.labels_lower + fact.components_lower
    return any(marker in token for token in tokens for marker in _ESCALATION_MARKERS)


def _aging_bucket_label(age_days: float | None) -> str:
    if age_days is None:
        return "Unknown"
    for upper, label in _AGING_BUCKETS:
        if upper is None or age_days <= upper:
            return label
    return "Unknown"


def _report_kind(report_name: str, config: ReportConfig) -> str:
    name = report_name.strip().lower()
    if "backlog" in name:
        return "backlog"
    if "daily follow-up" in name or "daily follow up" in name or "response & daily follow-up" in name:
        return "follow_up"
    if "first response" in name:
        return "first_response"
    if "first contact" in name:
        return "fcr"
    if "sla compliance" in name:
        return "sla"
    if "escalation" in name:
        return "escalation"
    if "reopen" in name:
        return "reopen"
    if "csat" in name:
        return "csat"
    if "ticket volume" in name:
        return "ticket_volume"
    if "utilization" in name:
        return "utilization"
    if "mttr" in name or "resolution" in name:
        return "mttr"
    if config.group_by == "sla_first_response_status":
        return "first_response"
    if config.group_by == "sla_resolution_status":
        return "sla"
    if config.group_by == "response_followup_status":
        return "follow_up"
    if config.group_by == "assignee":
        return "utilization"
    return "generic"


def _metric_values_for_kind(report_kind: str, facts: Sequence[ReportIssueFact]) -> list[float]:
    if report_kind == "first_response":
        return [fact.first_response_hours for fact in facts if fact.first_response_hours is not None]
    if report_kind == "backlog":
        return [fact.open_age_hours for fact in facts if fact.open_age_hours is not None]
    return [fact.ttr_hours for fact in facts if fact.ttr_hours is not None]


def _report_kind_requires_changelog(report_kind: str) -> bool:
    return report_kind in {"escalation", "reopen"}


def _is_master_changelog_skip_error(message: str) -> bool:
    return str(message or "").startswith(_MASTER_CHANGELOG_SKIP_PREFIX)


def _template_readiness(template: ReportTemplate, *, facts: Sequence[ReportIssueFact]) -> str:
    name = template.name.strip().lower()
    report_kind = _report_kind(template.name, template.config)
    changelog_available = any(fact.changelog_loaded and not fact.changelog_error for fact in facts)
    changelog_skipped = any(_is_master_changelog_skip_error(fact.changelog_error) for fact in facts)
    if report_kind == "csat" or "csat" in name:
        return "gap"
    if report_kind == "fcr":
        return "proxy"
    if report_kind == "follow_up":
        missing_followup = any(not fact.followup_authoritative for fact in facts)
        missing_first_response = any(not fact.first_response_authoritative for fact in facts)
        return "proxy" if missing_followup or missing_first_response else "ready"
    if report_kind == "first_response":
        missing_first_response = any(fact.first_response_hours is None for fact in facts)
        return "proxy" if missing_first_response else (template.readiness or "custom")
    if report_kind == "escalation":
        return "proxy" if changelog_available or changelog_skipped else "gap"
    if report_kind == "reopen":
        return "proxy" if changelog_available or changelog_skipped else "gap"
    return template.readiness or "custom"


class ReportWorkbookBuilder:
    """Build rich report workbooks for a fixed site and issue set."""

    def __init__(
        self,
        *,
        all_issues: list[dict[str, Any]],
        site_scope: str,
        today: date | None = None,
        jira_client: JiraClient | None = None,
        enable_changelog_fetch: bool | None = None,
    ) -> None:
        self.site_scope = site_scope
        self.today = today or _now_utc().date()
        self.now = _now_utc()
        self._all_issues = list(all_issues)
        self._jira_client = jira_client or JiraClient()
        self._enable_changelog_fetch = (
            enable_changelog_fetch if enable_changelog_fetch is not None else not bool(os.getenv("PYTEST_CURRENT_TEST"))
        )
        self._facts_by_key: dict[str, ReportIssueFact] = {}
        self._build_basic_facts()

    def _build_basic_facts(self) -> None:
        now = self.now
        for issue in self._all_issues:
            row = issue_to_row(issue, include_comment_meta=True, include_description=True)
            fields = issue.get("fields") or {}
            created_dt = parse_dt(fields.get("created"))
            updated_dt = parse_dt(fields.get("updated"))
            resolved_dt = parse_dt(fields.get("resolutiondate"))
            fr_info = extract_sla_info(fields.get("customfield_11266"))
            res_info = extract_sla_info(fields.get("customfield_11264"))
            open_age_hours = None
            if created_dt and str(row.get("status_category") or "") != "Done":
                open_age_hours = max((now - created_dt).total_seconds() / 3600.0, 0.0)
            first_response_hours = (
                round(float(fr_info["elapsed_millis"]) / 3_600_000.0, 2)
                if fr_info.get("elapsed_millis") is not None
                else None
            )
            resolution_sla_elapsed_hours = (
                round(float(res_info["elapsed_millis"]) / 3_600_000.0, 2)
                if res_info.get("elapsed_millis") is not None
                else None
            )
            labels_lower = [str(label).strip().lower() for label in (row.get("labels") or [])]
            components_lower = [str(component).strip().lower() for component in (row.get("components") or [])]
            marker_escalated = _matches_escalation_markers(
                ReportIssueFact(
                    key=str(issue.get("key") or ""),
                    issue=issue,
                    row=row,
                    created_dt=created_dt,
                    updated_dt=updated_dt,
                    resolved_dt=resolved_dt,
                    ttr_hours=row.get("calendar_ttr_hours"),
                    open_age_hours=None,
                    first_response_hours=first_response_hours,
                    resolution_sla_elapsed_hours=resolution_sla_elapsed_hours,
                    sla_response_status=str(row.get("sla_first_response_status") or ""),
                    sla_resolution_status=str(row.get("sla_resolution_status") or ""),
                    comment_count=int(row.get("comment_count") or 0),
                    followup_authoritative=bool(row.get("followup_authoritative")),
                    first_response_authoritative=bool(row.get("first_response_authoritative")),
                    labels_lower=labels_lower,
                    components_lower=components_lower,
                )
            )
            marker_event_dates: set[date] = set()
            marker_anchor = created_dt or updated_dt or resolved_dt
            if marker_escalated and marker_anchor:
                marker_event_dates.add(marker_anchor.date())
            fact = ReportIssueFact(
                key=str(issue.get("key") or ""),
                issue=issue,
                row=row,
                created_dt=created_dt,
                updated_dt=updated_dt,
                resolved_dt=resolved_dt,
                ttr_hours=row.get("calendar_ttr_hours"),
                open_age_hours=round(open_age_hours, 1) if open_age_hours is not None else None,
                first_response_hours=first_response_hours,
                resolution_sla_elapsed_hours=resolution_sla_elapsed_hours,
                sla_response_status=str(row.get("sla_first_response_status") or ""),
                sla_resolution_status=str(row.get("sla_resolution_status") or ""),
                comment_count=int(row.get("comment_count") or 0),
                followup_authoritative=bool(row.get("followup_authoritative")),
                first_response_authoritative=bool(row.get("first_response_authoritative")),
                labels_lower=labels_lower,
                components_lower=components_lower,
                is_escalated=marker_escalated,
                escalation_reasons=["Escalation marker"] if marker_escalated else [],
                escalation_event_dates=marker_event_dates,
            )
            self._facts_by_key[fact.key] = fact

    def _issues_for_config(self, config: ReportConfig) -> list[dict[str, Any]]:
        if self.site_scope == "primary" and not config.include_excluded:
            candidates = [issue for issue in self._all_issues if issue_matches_scope(issue, "primary")]
        else:
            candidates = list(self._all_issues)
        filters = config.filters.model_dump(exclude_none=True)
        for key in ("open_only", "stale_only"):
            if not filters.get(key):
                filters.pop(key, None)
        return [issue for issue in candidates if _match(issue, **filters)]

    def _facts_for_config(self, config: ReportConfig) -> list[ReportIssueFact]:
        return [
            self._facts_by_key[key]
            for key in (str(issue.get("key") or "") for issue in self._issues_for_config(config))
            if key in self._facts_by_key
        ]

    def runtime_template_readiness(self, template: ReportTemplate) -> str:
        """Return the best current readiness for a saved template."""
        report_kind = _report_kind(template.name, template.config)
        if report_kind not in {"follow_up", "first_response"}:
            return template.readiness or "custom"
        return _template_readiness(template, facts=self._facts_for_config(template.config))

    def _facts_for_window(
        self,
        facts: Sequence[ReportIssueFact],
        *,
        window_field: str,
        window_start: date,
        window_end: date,
    ) -> list[ReportIssueFact]:
        selected: list[ReportIssueFact] = []
        for fact in facts:
            issue_day = _date_for_window(fact, window_field)
            if not issue_day or issue_day < window_start or issue_day > window_end:
                continue
            selected.append(fact)
        return selected

    def _changelog_target_keys_for_single(self, config: ReportConfig, *, report_name: str) -> set[str]:
        facts = self._facts_for_config(config)
        window_field = _date_field_for_report_window_config(config, report_name=report_name)
        target: set[str] = set()
        for _, days in _WINDOW_EXPORT_SPECS:
            current_start, current_end = _window_bounds(days, today=self.today)
            prior_start, prior_end = _prior_window_bounds(days, today=self.today)
            for fact in facts:
                issue_day = _date_for_window(fact, window_field)
                if not issue_day:
                    continue
                if current_start <= issue_day <= current_end or prior_start <= issue_day <= prior_end:
                    target.add(fact.key)
        for fact in facts:
            if any(
                dt and dt.date() >= self.today - timedelta(days=29)
                for dt in (fact.created_dt, fact.updated_dt, fact.resolved_dt)
            ):
                target.add(fact.key)
        return target

    def _changelog_target_keys_for_master(self, templates: Sequence[ReportTemplate]) -> set[str]:
        target: set[str] = set()
        for template in templates:
            config = template.config if isinstance(template.config, ReportConfig) else ReportConfig()
            report_kind = _report_kind(template.name, config)
            if not _report_kind_requires_changelog(report_kind):
                continue
            facts = self._facts_for_config(config)
            window_field = _date_field_for_report_window_config(config, report_name=template.name)
            for _, days in _WINDOW_EXPORT_SPECS:
                current_start, current_end = _window_bounds(days, today=self.today)
                prior_start, prior_end = _prior_window_bounds(days, today=self.today)
                for fact in facts:
                    issue_day = _date_for_window(fact, window_field)
                    if not issue_day:
                        continue
                    if current_start <= issue_day <= current_end or prior_start <= issue_day <= prior_end:
                        target.add(fact.key)
        return target

    def _apply_changelog(self, fact: ReportIssueFact, histories: Sequence[dict[str, Any]]) -> None:
        first_resolved: datetime | None = fact.resolved_dt
        reopen_count = 0
        assignee_changes = 0
        priority_increase_count = 0
        escalation_event_dates = set(fact.escalation_event_dates)
        for history in sorted(histories, key=lambda item: parse_dt(item.get("created")) or datetime.min.replace(tzinfo=timezone.utc)):
            history_created = parse_dt(history.get("created"))
            for change in history.get("items") or []:
                field_name = str(change.get("field") or change.get("fieldId") or "").strip().lower()
                from_string = str(change.get("fromString") or "")
                to_string = str(change.get("toString") or "")
                if field_name == "assignee" and from_string != to_string:
                    assignee_changes += 1
                    if assignee_changes > 1 and history_created:
                        escalation_event_dates.add(history_created.date())
                if field_name == "priority" and _priority_increase(from_string, to_string):
                    priority_increase_count += 1
                    if history_created:
                        escalation_event_dates.add(history_created.date())
                if field_name == "status":
                    if _is_terminal_status_name(to_string) and history_created and first_resolved is None:
                        first_resolved = history_created
                    if _is_terminal_status_name(from_string) and not _is_terminal_status_name(to_string):
                        reopen_count += 1
                if field_name == "resolution" and history_created and not first_resolved and to_string.strip():
                    first_resolved = history_created

        fact.first_resolved_dt = first_resolved or fact.resolved_dt
        fact.reopen_count = reopen_count
        fact.assignee_change_count = assignee_changes
        fact.priority_increase_count = priority_increase_count
        fact.escalation_event_dates = escalation_event_dates
        if assignee_changes > 1 and "Reassigned more than once" not in fact.escalation_reasons:
            fact.escalation_reasons.append("Reassigned more than once")
        if priority_increase_count > 0 and "Priority increased" not in fact.escalation_reasons:
            fact.escalation_reasons.append("Priority increased")
        fact.is_escalated = bool(fact.escalation_reasons)

    def ensure_changelogs(self, keys: Iterable[str]) -> None:
        keys_to_fetch = [
            key
            for key in {str(key or "").strip() for key in keys}
            if key and key in self._facts_by_key and not self._facts_by_key[key].changelog_loaded
        ]
        if not keys_to_fetch:
            return
        if not self._enable_changelog_fetch or not str(getattr(self._jira_client, "base_url", "") or "").strip():
            for key in keys_to_fetch:
                fact = self._facts_by_key[key]
                fact.changelog_loaded = True
                fact.changelog_error = "Changelog fetch disabled"
            return

        workers = min(4, len(keys_to_fetch))
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            future_map = {
                executor.submit(self._jira_client.get_issue_changelog_all, key): key
                for key in keys_to_fetch
            }
            for future in as_completed(future_map):
                key = future_map[future]
                fact = self._facts_by_key[key]
                try:
                    histories = future.result() or []
                    self._apply_changelog(fact, histories)
                    fact.changelog_loaded = True
                except Exception as exc:  # pragma: no cover - defensive network fallback
                    fact.changelog_loaded = True
                    fact.changelog_error = str(exc)

    def _prepare_master_changelogs(self, templates: Sequence[ReportTemplate]) -> None:
        keys = self._changelog_target_keys_for_master(templates)
        if len(keys) > _MASTER_CHANGELOG_PREFETCH_LIMIT:
            message = (
                f"{_MASTER_CHANGELOG_SKIP_PREFIX} "
                f"({len(keys)} issues exceeds {_MASTER_CHANGELOG_PREFETCH_LIMIT} issue limit)"
            )
            logger.warning(message)
            for key in keys:
                fact = self._facts_by_key.get(key)
                if not fact:
                    continue
                fact.changelog_loaded = True
                fact.changelog_error = message
            return
        self.ensure_changelogs(keys)

    def build_single_report(
        self,
        *,
        path: str,
        config: ReportConfig,
        report_name: str,
        report_description: str,
        template: ReportTemplate | None = None,
    ) -> None:
        self.ensure_changelogs(self._changelog_target_keys_for_single(config, report_name=report_name))
        workbook = xlsxwriter.Workbook(
            path,
            {
                "in_memory": False,
                "strings_to_numbers": False,
                "strings_to_formulas": False,
            },
        )
        try:
            formats = self._build_formats(workbook)
            current_facts = self._facts_for_config(config)
            summary_context = self._build_dashboard_context(
                report_name=report_name,
                report_description=report_description,
                facts=current_facts,
                template=template,
            )
            self._write_single_summary_sheet(workbook, formats, summary_context)
            self._write_trends_sheet(workbook, formats, summary_context["trend_rows"], title="Trends")
            if summary_context["gaps"]:
                self._write_data_gaps_sheet(workbook, formats, summary_context["gaps"], title="Data Gaps")
            for window_label, window_days in _WINDOW_EXPORT_SPECS:
                self._write_template_window_sheet(
                    workbook,
                    formats,
                    template=template,
                    config=config,
                    report_name=report_name,
                    report_description=report_description,
                    window_label=window_label,
                    window_days=window_days,
                )
        finally:
            workbook.close()

    def _detect_escalation_anomaly(self, trend_rows: Sequence[dict[str, Any]]) -> TrendAnomaly | None:
        ranked = sorted(
            (
                {
                    "idx": idx,
                    "count": int(row.get("escalation_count") or 0),
                    "date": str(row.get("date") or ""),
                }
                for idx, row in enumerate(trend_rows)
            ),
            key=lambda item: item["count"],
            reverse=True,
        )
        if not ranked or ranked[0]["count"] < 100:
            return None
        baseline = ranked[1]["count"] if len(ranked) > 1 else 0
        if ranked[0]["count"] < max(1, baseline) * 10:
            return None
        row_idx = 4 + ranked[0]["idx"]
        return TrendAnomaly(
            row_idx=row_idx,
            excel_row=row_idx + 1,
            day=ranked[0]["date"],
            count=ranked[0]["count"],
            baseline_peak=baseline,
        )

    def _write_master_index_sheet(self, worksheet, formats: dict[str, Any], rows: Sequence[dict[str, Any]]) -> None:
        headers = [
            "Status",
            "Report",
            "Sheet",
            "Window",
            "Window Field",
            "Window Start",
            "Window End",
            "Category",
            "Readiness",
            "View",
            "Rows",
            "Description",
            "Notes",
        ]
        worksheet.write_row(0, 0, headers, formats["header"])
        if not rows:
            worksheet.write(1, 1, "No report templates are currently included in the master export.", formats["text"])
            worksheet.set_column(0, 0, 12)
            worksheet.freeze_panes(1, 0)
            return
        for row_idx, row in enumerate(rows, start=1):
            readiness = str(row["readiness"] or "").strip().lower()
            status_value = "✅"
            status_format = formats["status_ready"]
            if readiness in {"proxy", "gap"}:
                status_value = "⚠️"
                status_format = formats["status_proxy"]
            if readiness == "anomaly":
                status_value = "🔴"
                status_format = formats["status_issue"]
            worksheet.write(row_idx, 0, status_value, status_format)
            worksheet.write(row_idx, 1, row["report"], formats["text"])
            worksheet.write_url(row_idx, 2, f"internal:'{row['sheet']}'!A1", string=row["sheet"], cell_format=formats["link"])
            worksheet.write(row_idx, 3, row["window"], formats["text"])
            worksheet.write(row_idx, 4, row["window_field"], formats["text"])
            worksheet.write(row_idx, 5, row["window_start"], formats["date_text"])
            worksheet.write(row_idx, 6, row["window_end"], formats["date_text"])
            worksheet.write(row_idx, 7, row["category"], formats["text"])
            worksheet.write(row_idx, 8, row["readiness"], formats["text"])
            worksheet.write(row_idx, 9, row["view"], formats["text"])
            worksheet.write_number(row_idx, 10, int(row["rows"]), formats["integer"])
            worksheet.write(row_idx, 11, row["description"], formats["wrap"])
            worksheet.write(row_idx, 12, row["notes"], formats["wrap"])
        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, max(1, len(rows)), len(headers) - 1)
        worksheet.set_column(0, 0, 10)
        worksheet.set_column(1, 1, 30)
        worksheet.set_column(2, 2, 28)
        worksheet.set_column(3, 6, 14)
        worksheet.set_column(7, 9, 16)
        worksheet.set_column(10, 10, 10)
        worksheet.set_column(11, 11, 48)
        worksheet.set_column(12, 12, 60)

    def _write_master_trends_sheet(
        self,
        workbook,
        formats: dict[str, Any],
        trend_rows: Sequence[dict[str, Any]],
        used_names: set[str],
        *,
        anomaly: TrendAnomaly | None,
    ):
        title = _unique_sheet_name("Trends", used_names)
        worksheet = workbook.add_worksheet(title)
        worksheet.write(0, 0, title, formats["title"])
        worksheet.write(1, 0, "Daily operational trend data for the last 30 days.", formats["text"])
        headers = [
            "Date",
            "Tickets Created",
            "Tickets Resolved",
            "MTTR Avg (h)",
            "MTTR P95 (h)",
            "SLA Compliance %",
            "Backlog Count",
            "Escalation Count",
            "Created (7d MA)",
            "SLA Compliance (7d MA)",
            "MTTR P95 (7d MA)",
            "Day",
        ]
        header_row = 3
        worksheet.write_row(header_row, 0, headers, formats["header"])
        for offset, row in enumerate(trend_rows):
            idx = header_row + 1 + offset
            worksheet.write(idx, 0, row["date"], formats["date_text"])
            worksheet.write_number(idx, 1, row["tickets_created"], formats["integer"])
            worksheet.write_number(idx, 2, row["tickets_resolved"], formats["integer"])
            worksheet.write_number(idx, 3, row["mttr_avg_hours"], formats["hours"])
            worksheet.write_number(idx, 4, row["mttr_p95_hours"], formats["hours"])
            worksheet.write_number(idx, 5, row["sla_compliance_rate"], formats["percent"])
            worksheet.write_number(idx, 6, row["backlog_count"], formats["integer"])
            worksheet.write_number(idx, 7, row["escalation_count"], formats["integer"])
            if offset >= 6:
                created_range = _range_ref(idx - 6, 1, idx, 1)
                sla_range = _range_ref(idx - 6, 5, idx, 5)
                mttr_range = _range_ref(idx - 6, 4, idx, 4)
                source_rows = trend_rows[offset - 6: offset + 1]
                worksheet.write_formula(
                    idx,
                    8,
                    f"=AVERAGE({created_range})",
                    formats["integer"],
                    round(sum(point["tickets_created"] for point in source_rows) / 7.0, 1),
                )
                worksheet.write_formula(
                    idx,
                    9,
                    f"=AVERAGE({sla_range})",
                    formats["percent"],
                    round(sum(point["sla_compliance_rate"] for point in source_rows) / 7.0, 4),
                )
                worksheet.write_formula(
                    idx,
                    10,
                    f"=AVERAGE({mttr_range})",
                    formats["hours"],
                    round(sum(point["mttr_p95_hours"] for point in source_rows) / 7.0, 1),
                )
            else:
                worksheet.write_blank(idx, 8, None, formats["text"])
                worksheet.write_blank(idx, 9, None, formats["text"])
                worksheet.write_blank(idx, 10, None, formats["text"])
            day_label = datetime.fromisoformat(f"{row['date']}T00:00:00+00:00").strftime("%a")
            worksheet.write_formula(
                idx,
                11,
                f'=TEXT(A{idx + 1},"ddd")',
                formats["text"],
                day_label,
            )
        if anomaly:
            worksheet.write_comment(
                anomaly.row_idx,
                7,
                (
                    f"⚠️ DATA ANOMALY: {anomaly.count:,} escalations on {anomaly.day} "
                    f"is ~{max(1, round(anomaly.count / max(anomaly.baseline_peak, 1))):,}x the typical daily count "
                    f"(0-{anomaly.baseline_peak}). May be bulk system action or extraction artifact. Verify with source system."
                ),
            )
        worksheet.freeze_panes(header_row + 1, 0)
        worksheet.autofilter(header_row, 0, header_row + len(trend_rows), len(headers) - 1)
        worksheet.set_column(0, 0, 14)
        worksheet.set_column(1, 2, 16)
        worksheet.set_column(3, 4, 14)
        worksheet.set_column(5, 5, 16)
        worksheet.set_column(6, 7, 16)
        worksheet.set_column(8, 10, 18)
        worksheet.set_column(11, 11, 10)
        first_data_row = header_row + 1
        last_data_row = header_row + len(trend_rows)
        worksheet.conditional_format(
            first_data_row,
            0,
            last_data_row,
            11,
            {
                "type": "formula",
                "criteria": '=OR($L5="Sat",$L5="Sun")',
                "format": formats["weekend"],
            },
        )

        chart = workbook.add_chart({"type": "line"})
        chart.add_series({
            "name": "Tickets Created",
            "categories": [worksheet.name, first_data_row, 0, last_data_row, 0],
            "values": [worksheet.name, first_data_row, 1, last_data_row, 1],
            "line": {"color": "#2563EB", "width": 2.0},
            "marker": {"type": "circle", "size": 4, "border": {"color": "#2563EB"}, "fill": {"color": "#2563EB"}},
        })
        chart.add_series({
            "name": "Tickets Resolved",
            "categories": [worksheet.name, first_data_row, 0, last_data_row, 0],
            "values": [worksheet.name, first_data_row, 2, last_data_row, 2],
            "line": {"color": "#10B981", "width": 2.0},
            "marker": {"type": "diamond", "size": 4, "border": {"color": "#10B981"}, "fill": {"color": "#10B981"}},
        })
        line = workbook.add_chart({"type": "line"})
        line.add_series({
            "name": "MTTR P95",
            "categories": [worksheet.name, first_data_row, 0, last_data_row, 0],
            "values": [worksheet.name, first_data_row, 4, last_data_row, 4],
            "y2_axis": True,
            "line": {"color": "#DC2626", "width": 2.25, "dash_type": "dash"},
            "marker": {"type": "square", "size": 4, "border": {"color": "#DC2626"}, "fill": {"color": "#DC2626"}},
        })
        line.set_y2_axis({"name": "MTTR P95 (hours)"})
        chart.combine(line)
        chart.set_y_axis({"name": "Ticket Count"})
        chart.set_x_axis({"name": "Date", "label_position": "low"})
        chart.set_legend({"position": "bottom"})
        chart.set_title({"name": "30-Day Trends"})
        worksheet.insert_chart("N4", chart, {"x_scale": 1.3, "y_scale": 1.1})
        return worksheet

    def _write_master_template_window_sheet(
        self,
        workbook,
        formats: dict[str, Any],
        *,
        template: ReportTemplate,
        config: ReportConfig,
        report_name: str,
        report_description: str,
        window_label: str,
        window_days: int,
        sheet_name: str,
    ) -> MasterSheetSummary:
        view_type = _report_view_type(config)
        report_kind = _report_kind(report_name, config)
        window_field = _date_field_for_report_window_config(config, report_name=report_name)
        window_field_label = _REPORT_WINDOW_LABELS.get(window_field, "Created")
        current_start, current_end = _window_bounds(window_days, today=self.today)
        prior_start, prior_end = _prior_window_bounds(window_days, today=self.today)
        facts = self._facts_for_config(config)
        current_facts = self._facts_for_window(facts, window_field=window_field, window_start=current_start, window_end=current_end)
        prior_facts = self._facts_for_window(facts, window_field=window_field, window_start=prior_start, window_end=prior_end)
        readiness = _template_readiness(template, facts=current_facts)
        metadata = self._template_window_metadata(
            report_name=report_name,
            report_description=report_description,
            category=(template.category or ""),
            readiness=readiness,
            view_type=view_type,
            notes=(template.notes or ""),
            window_label=window_label,
            window_field_label=window_field_label,
            window_start=current_start,
            window_end=current_end,
        )
        worksheet = workbook.add_worksheet(sheet_name)
        self._write_metadata_block(worksheet, formats, metadata)
        self._apply_master_readiness_annotation(worksheet, formats, readiness)

        if report_kind == "backlog":
            backlog_rows, backlog_statuses = self._backlog_rows(
                [fact for fact in current_facts if fact.is_open],
                [fact for fact in prior_facts if fact.is_open],
            )
            table_info, total_row = self._write_master_backlog_table(
                worksheet,
                formats,
                backlog_rows,
                backlog_statuses,
                window_days=window_days,
            )
            self._insert_backlog_chart(worksheet, table_info, workbook)
            row_count = len(backlog_rows)
            metric_row = None
        elif config.group_by:
            grouped_rows = self._group_summary_rows(
                facts=current_facts,
                prior_facts=prior_facts,
                group_by=config.group_by,
                report_kind=report_kind,
            )
            table_info, total_row, metric_row = self._write_master_grouped_table(
                worksheet,
                formats,
                grouped_rows,
                group_by=config.group_by,
                report_kind=report_kind,
            )
            self._insert_group_chart(worksheet, table_info, workbook, report_name=report_name, report_kind=report_kind)
            row_count = len(grouped_rows)
        else:
            columns = config.columns or _DEFAULT_COLUMNS
            self._write_detail_table(worksheet, formats, columns, current_facts)
            row_count = len(current_facts)
            table_info = ChartTableInfo(header_row=12, first_data_row=13, last_data_row=12 + row_count, column_map={})
            total_row = None
            metric_row = None
        return MasterSheetSummary(
            report_name=report_name,
            sheet_name=sheet_name,
            window_label=window_label,
            window_field_label=window_field_label,
            window_start=current_start,
            window_end=current_end,
            category=template.category or "",
            readiness=readiness,
            view_type=view_type,
            row_count=row_count,
            description=report_description,
            notes=template.notes or "",
            report_kind=report_kind,
            table_info=table_info,
            total_row=total_row,
            metric_row=metric_row,
        )

    def _apply_master_readiness_annotation(self, worksheet, formats: dict[str, Any], readiness: str) -> None:
        readiness_text = str(readiness or "").strip().lower()
        cell_format = formats["readiness_ready"]
        comment = None
        if readiness_text in {"proxy", "gap", "anomaly"}:
            cell_format = formats["readiness_proxy"] if readiness_text == "proxy" else formats["readiness_issue"]
        if readiness_text == "proxy":
            comment = "⚠️ PROXY METRIC: Uses heuristic approximations. See Data Gaps sheet."
        worksheet.write(6, 1, readiness, cell_format)
        if comment:
            worksheet.write_comment(6, 1, comment)

    def _write_master_grouped_table(
        self,
        worksheet,
        formats: dict[str, Any],
        rows: Sequence[dict[str, Any]],
        *,
        group_by: str,
        report_kind: str,
    ) -> tuple[ChartTableInfo, int | None, int | None]:
        header_row = 12
        headers = [
            _FIELD_LABELS.get(group_by, group_by),
            "Count",
            "Open",
            "Avg TTR (h)",
            "Median TTR (h)",
            "P95 TTR (h)",
            "P99 TTR (h)",
            "Δ Count vs Prior",
        ]
        column_map = {
            "group": 0,
            "count": 1,
            "open": 2,
            "avg_ttr_hours": 3,
            "median_ttr_hours": 4,
            "p95_ttr_hours": 5,
            "p99_ttr_hours": 6,
            "delta_vs_prior_period": 7,
        }
        if report_kind == "ticket_volume":
            headers.append("% of Total")
            column_map["percent_of_total"] = len(headers) - 1
        if report_kind == "fcr":
            headers.append("FCR %")
            column_map["fcr_rate"] = len(headers) - 1
        if report_kind == "escalation":
            headers.append("Escalation Rate %")
            column_map["escalation_rate"] = len(headers) - 1
        worksheet.write_row(header_row, 0, headers, formats["header"])

        data_first_row = header_row + 1
        row_count = len(rows)
        data_last_row = header_row + row_count
        count_range_abs = _range_ref(data_first_row, 1, data_last_row, 1, absolute=True) if row_count else ""

        for row_offset, row in enumerate(rows, start=1):
            row_idx = header_row + row_offset
            worksheet.write(row_idx, 0, row["group"], formats["text"])
            worksheet.write_number(row_idx, 1, row["count"], formats["integer"])
            worksheet.write_number(row_idx, 2, row["open"], formats["integer"])
            worksheet.write_number(row_idx, 3, row["avg_ttr_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, 4, row["median_ttr_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, 5, row["p95_ttr_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, 6, row["p99_ttr_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, 7, row["delta_vs_prior_period"], formats["integer"])
            if "percent_of_total" in column_map:
                formula = f"=IF(SUM({count_range_abs})=0,0,B{row_idx + 1}/SUM({count_range_abs}))" if row_count else "=0"
                cached = (row["count"] / max(sum(item["count"] for item in rows), 1)) if rows else 0.0
                worksheet.write_formula(row_idx, column_map["percent_of_total"], formula, formats["percent"], cached)
            if "fcr_rate" in row:
                worksheet.write_number(row_idx, column_map["fcr_rate"], row["fcr_rate"], formats["percent"])
            if "escalation_rate" in row:
                worksheet.write_number(row_idx, column_map["escalation_rate"], row["escalation_rate"], formats["percent"])

        total_row = data_last_row + 1 if row_count else header_row + 1
        if row_count:
            count_range = _range_ref(data_first_row, 1, data_last_row, 1)
            open_range = _range_ref(data_first_row, 2, data_last_row, 2)
            avg_range = _range_ref(data_first_row, 3, data_last_row, 3)
            p95_range = _range_ref(data_first_row, 5, data_last_row, 5)
            p99_range = _range_ref(data_first_row, 6, data_last_row, 6)
            delta_range = _range_ref(data_first_row, 7, data_last_row, 7)
        else:
            count_range = open_range = avg_range = p95_range = p99_range = delta_range = ""

        total_count = sum(row["count"] for row in rows)
        total_open = sum(row["open"] for row in rows)
        weighted_avg = (
            sum((row["count"] or 0) * float(row["avg_ttr_hours"] or 0.0) for row in rows) / total_count
            if total_count else 0.0
        )
        max_p95 = max((row["p95_ttr_hours"] or 0.0) for row in rows) if rows else 0.0
        max_p99 = max((row["p99_ttr_hours"] or 0.0) for row in rows) if rows else 0.0
        delta_total = sum(row["delta_vs_prior_period"] for row in rows)
        worksheet.write(total_row, 0, "Total", formats["total_text"])
        worksheet.write_formula(total_row, 1, f"={_safe_sum_formula(count_range)}" if row_count else "=0", formats["total_integer"], total_count)
        worksheet.write_formula(total_row, 2, f"={_safe_sum_formula(open_range)}" if row_count else "=0", formats["total_integer"], total_open)
        worksheet.write_formula(
            total_row,
            3,
            f"={_weighted_average_formula(count_range, avg_range)}" if row_count else "=0",
            formats["total_hours"],
            round(weighted_avg, 1),
        )
        worksheet.write_blank(total_row, 4, None, formats["total_blank"])
        worksheet.write_formula(total_row, 5, f"={_safe_max_formula(p95_range)}" if row_count else "=0", formats["total_hours"], max_p95)
        worksheet.write_formula(total_row, 6, f"={_safe_max_formula(p99_range)}" if row_count else "=0", formats["total_hours"], max_p99)
        worksheet.write_formula(total_row, 7, f"={_safe_sum_formula(delta_range)}" if row_count else "=0", formats["total_integer"], delta_total)
        if "percent_of_total" in column_map:
            percent_range = _range_ref(data_first_row, column_map["percent_of_total"], data_last_row, column_map["percent_of_total"])
            worksheet.write_formula(
                total_row,
                column_map["percent_of_total"],
                f"={_safe_sum_formula(percent_range)}" if row_count else "=0",
                formats["total_percent"],
                1.0 if total_count else 0.0,
            )
        if "fcr_rate" in column_map:
            fcr_total = (
                sum((row["count"] or 0) * float(row.get("fcr_rate") or 0.0) for row in rows) / total_count
                if total_count else 0.0
            )
            rate_range = _range_ref(data_first_row, column_map["fcr_rate"], data_last_row, column_map["fcr_rate"])
            worksheet.write_formula(
                total_row,
                column_map["fcr_rate"],
                f"={_weighted_average_formula(count_range, rate_range)}" if row_count else "=0",
                formats["total_percent"],
                fcr_total,
            )
        if "escalation_rate" in column_map:
            escalation_total = (
                sum((row["count"] or 0) * float(row.get("escalation_rate") or 0.0) for row in rows) / total_count
                if total_count else 0.0
            )
            rate_range = _range_ref(data_first_row, column_map["escalation_rate"], data_last_row, column_map["escalation_rate"])
            worksheet.write_formula(
                total_row,
                column_map["escalation_rate"],
                f"={_weighted_average_formula(count_range, rate_range)}" if row_count else "=0",
                formats["total_percent"],
                escalation_total,
            )

        metric_row = None
        if report_kind in {"sla", "first_response", "follow_up"}:
            metric_row = total_row + 1
            label_range = _range_ref(data_first_row, 0, data_last_row, 0, absolute=True) if row_count else ""
            count_values = _range_ref(data_first_row, 1, data_last_row, 1, absolute=True) if row_count else ""
            if report_kind == "sla":
                metric_label = "SLA Compliance %"
            elif report_kind == "first_response":
                metric_label = "First Response SLA Met %"
            else:
                metric_label = "Response + Follow-Up Compliance %"
            cached_metric = 0.0
            met_row = next((row for row in rows if str(row["group"]).strip().lower() == "met"), None)
            if met_row and total_count:
                cached_metric = float(met_row["count"]) / total_count
            worksheet.write(metric_row, 0, metric_label, formats["metric_label"])
            worksheet.write_formula(
                metric_row,
                1,
                f"={_status_match_formula(label_range, 'Met', count_values, _safe_sum_formula(count_range_abs))}" if row_count else "=0",
                formats["metric_percent"],
                cached_metric,
            )

        worksheet.freeze_panes(header_row + 1, 0)
        worksheet.autofilter(header_row, 0, header_row + max(1, row_count), len(headers) - 1)
        worksheet.set_column(0, 0, 30 if report_kind in {"ticket_volume", "escalation", "fcr"} else 24)
        worksheet.set_column(1, 2, 12)
        worksheet.set_column(3, 6, 16)
        worksheet.set_column(7, len(headers) - 1, 18)
        self._apply_master_group_conditional_formatting(
            worksheet,
            formats,
            report_kind=report_kind,
            first_row=data_first_row,
            last_row=data_last_row,
            last_col=len(headers) - 1,
            column_map=column_map,
        )
        return (
            ChartTableInfo(
                header_row=header_row,
                first_data_row=data_first_row,
                last_data_row=data_last_row if row_count else header_row,
                column_map=column_map,
            ),
            total_row,
            metric_row,
        )

    def _write_master_backlog_table(
        self,
        worksheet,
        formats: dict[str, Any],
        rows: Sequence[dict[str, Any]],
        statuses: Sequence[str],
        *,
        window_days: int,
    ) -> tuple[ChartTableInfo, int]:
        header_row = 12
        fixed_statuses = (
            ["In Progress", "Pending", "Waiting for customer", "Waiting for support"]
            if window_days == 7
            else ["Acknowledged", "In Progress", "Pending", "Waiting for customer", "Waiting for support"]
        )
        headers = [
            "Aging Bucket",
            "% of Backlog",
            *fixed_statuses,
            "Total",
            "Avg Age (h)",
            "Median Age (h)",
            "P95 Age (h)",
            "P99 Age (h)",
            "Δ Count vs Prior",
        ]
        worksheet.write_row(header_row, 0, headers, formats["header"])
        data_first_row = header_row + 1
        data_last_row = header_row + len(rows)
        for row_offset, row in enumerate(rows, start=1):
            row_idx = header_row + row_offset
            worksheet.write(row_idx, 0, row["bucket"], formats["text"])
            worksheet.write_number(row_idx, 1, row["percent_of_backlog"], formats["percent"])
            for status_idx, status in enumerate(fixed_statuses, start=2):
                worksheet.write_number(row_idx, status_idx, row["status_counts"].get(status, 0), formats["integer"])
            start_stats_col = 2 + len(fixed_statuses)
            worksheet.write_number(row_idx, start_stats_col, row["total"], formats["integer"])
            worksheet.write_number(row_idx, start_stats_col + 1, row["avg_age_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, start_stats_col + 2, row["median_age_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, start_stats_col + 3, row["p95_age_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, start_stats_col + 4, row["p99_age_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, start_stats_col + 5, row["delta_vs_prior_period"], formats["integer"])
        total_row = data_last_row + 1
        total_col = 2 + len(fixed_statuses)
        total_total = sum(row["total"] for row in rows)
        total_avg = (
            sum((row["total"] or 0) * float(row["avg_age_hours"] or 0.0) for row in rows) / total_total
            if total_total else 0.0
        )
        worksheet.write(total_row, 0, "Total", formats["total_text"])
        percent_range = _range_ref(data_first_row, 1, data_last_row, 1) if rows else ""
        worksheet.write_formula(total_row, 1, f"={_safe_sum_formula(percent_range)}" if rows else "=0", formats["total_percent"], 1.0 if total_total else 0.0)
        for status_idx, _status in enumerate(fixed_statuses, start=2):
            status_range = _range_ref(data_first_row, status_idx, data_last_row, status_idx) if rows else ""
            status_total = sum(row["status_counts"].get(fixed_statuses[status_idx - 2], 0) for row in rows)
            worksheet.write_formula(total_row, status_idx, f"={_safe_sum_formula(status_range)}" if rows else "=0", formats["total_integer"], status_total)
        total_range = _range_ref(data_first_row, total_col, data_last_row, total_col) if rows else ""
        avg_range = _range_ref(data_first_row, total_col + 1, data_last_row, total_col + 1) if rows else ""
        p95_range = _range_ref(data_first_row, total_col + 3, data_last_row, total_col + 3) if rows else ""
        p99_range = _range_ref(data_first_row, total_col + 4, data_last_row, total_col + 4) if rows else ""
        delta_range = _range_ref(data_first_row, total_col + 5, data_last_row, total_col + 5) if rows else ""
        worksheet.write_formula(total_row, total_col, f"={_safe_sum_formula(total_range)}" if rows else "=0", formats["total_integer"], total_total)
        worksheet.write_formula(
            total_row,
            total_col + 1,
            f"={_weighted_average_formula(total_range, avg_range)}" if rows else "=0",
            formats["total_hours"],
            round(total_avg, 1),
        )
        worksheet.write_blank(total_row, total_col + 2, None, formats["total_blank"])
        worksheet.write_formula(
            total_row,
            total_col + 3,
            f"={_safe_max_formula(p95_range)}" if rows else "=0",
            formats["total_hours"],
            max((row["p95_age_hours"] or 0.0) for row in rows) if rows else 0.0,
        )
        worksheet.write_formula(
            total_row,
            total_col + 4,
            f"={_safe_max_formula(p99_range)}" if rows else "=0",
            formats["total_hours"],
            max((row["p99_age_hours"] or 0.0) for row in rows) if rows else 0.0,
        )
        worksheet.write_formula(
            total_row,
            total_col + 5,
            f"={_safe_sum_formula(delta_range)}" if rows else "=0",
            formats["total_integer"],
            sum(row["delta_vs_prior_period"] for row in rows),
        )
        worksheet.freeze_panes(header_row + 1, 0)
        worksheet.autofilter(header_row, 0, header_row + max(1, len(rows)), len(headers) - 1)
        worksheet.set_column(0, 0, 28)
        worksheet.set_column(1, 1, 14)
        worksheet.set_column(2, 1 + len(fixed_statuses), 18)
        worksheet.set_column(2 + len(fixed_statuses), len(headers) - 1, 16)
        self._apply_master_backlog_conditional_formatting(
            worksheet,
            formats,
            first_row=data_first_row,
            last_row=data_last_row,
            last_col=len(headers) - 1,
        )
        return (
            ChartTableInfo(
                header_row=header_row,
                first_data_row=data_first_row,
                last_data_row=data_last_row if rows else header_row,
                column_map={status: 2 + idx for idx, status in enumerate(fixed_statuses)},
            ),
            total_row,
        )

    def _apply_master_group_conditional_formatting(
        self,
        worksheet,
        formats: dict[str, Any],
        *,
        report_kind: str,
        first_row: int,
        last_row: int,
        last_col: int,
        column_map: dict[str, int],
    ) -> None:
        if last_row < first_row:
            return
        if report_kind in {"sla", "follow_up"}:
            worksheet.conditional_format(first_row, 0, last_row, last_col, {
                "type": "formula",
                "criteria": f'=$A{first_row + 1}="BREACHED"',
                "format": formats["row_red"],
            })
            worksheet.conditional_format(first_row, 0, last_row, last_col, {
                "type": "formula",
                "criteria": f'=$A{first_row + 1}="Running"',
                "format": formats["row_yellow"],
            })
        if report_kind == "mttr":
            for col_idx in (5, 6):
                worksheet.conditional_format(first_row, col_idx, last_row, col_idx, {
                    "type": "cell",
                    "criteria": ">",
                    "value": 1000,
                    "format": formats["kpi_bad"],
                })
                worksheet.conditional_format(first_row, col_idx, last_row, col_idx, {
                    "type": "cell",
                    "criteria": "between",
                    "minimum": 200,
                    "maximum": 1000,
                    "format": formats["kpi_warn"],
                })
                worksheet.conditional_format(first_row, col_idx, last_row, col_idx, {
                    "type": "cell",
                    "criteria": "<=",
                    "value": 200,
                    "format": formats["kpi_good"],
                })
        if report_kind == "escalation" and "escalation_rate" in column_map:
            col_idx = column_map["escalation_rate"]
            worksheet.conditional_format(first_row, col_idx, last_row, col_idx, {
                "type": "cell",
                "criteria": ">",
                "value": 0.4,
                "format": formats["kpi_bad"],
            })
            worksheet.conditional_format(first_row, col_idx, last_row, col_idx, {
                "type": "cell",
                "criteria": "between",
                "minimum": 0.2,
                "maximum": 0.4,
                "format": formats["kpi_warn"],
            })
            worksheet.conditional_format(first_row, col_idx, last_row, col_idx, {
                "type": "cell",
                "criteria": "<",
                "value": 0.2,
                "format": formats["kpi_good"],
            })
        if report_kind == "fcr" and "fcr_rate" in column_map:
            col_idx = column_map["fcr_rate"]
            worksheet.conditional_format(first_row, col_idx, last_row, col_idx, {
                "type": "cell",
                "criteria": ">",
                "value": 0.3,
                "format": formats["kpi_good"],
            })
            worksheet.conditional_format(first_row, col_idx, last_row, col_idx, {
                "type": "cell",
                "criteria": "between",
                "minimum": 0.15,
                "maximum": 0.3,
                "format": formats["kpi_warn"],
            })
            worksheet.conditional_format(first_row, col_idx, last_row, col_idx, {
                "type": "cell",
                "criteria": "<",
                "value": 0.15,
                "format": formats["kpi_bad"],
            })

    def _apply_master_backlog_conditional_formatting(
        self,
        worksheet,
        formats: dict[str, Any],
        *,
        first_row: int,
        last_row: int,
        last_col: int,
    ) -> None:
        if last_row < first_row:
            return
        bucket_formats = {
            "0-3 days": formats["row_green"],
            "4-7 days": formats["row_pale_yellow"],
            "8-14 days": formats["row_orange"],
            "15-30 days": formats["row_light_red"],
            "31-60 days": formats["row_red"],
            "60+ days": formats["row_dark_red"],
        }
        for bucket, fmt in bucket_formats.items():
            worksheet.conditional_format(first_row, 0, last_row, last_col, {
                "type": "formula",
                "criteria": f'=$A{first_row + 1}="{bucket}"',
                "format": fmt,
            })

    def build_master_report(self, *, path: str, templates: Sequence[ReportTemplate]) -> None:
        if self.site_scope != "primary":
            self._build_master_report_legacy(path=path, templates=templates)
            return
        self._build_master_report_primary(path=path, templates=templates)

    def _build_master_report_legacy(self, *, path: str, templates: Sequence[ReportTemplate]) -> None:
        included_templates = [template for template in templates if template.include_in_master_export]
        self._prepare_master_changelogs(included_templates)
        workbook = xlsxwriter.Workbook(
            path,
            {
                "in_memory": False,
                "strings_to_numbers": False,
                "strings_to_formulas": False,
            },
        )
        try:
            formats = self._build_formats(workbook)
            used_names: set[str] = set()
            index_sheet_name = _unique_sheet_name("Report Index", used_names)
            index_sheet = workbook.add_worksheet(index_sheet_name)
            index_rows: list[dict[str, Any]] = []

            dashboard_context = self._build_dashboard_context(
                report_name="Executive Dashboard",
                report_description="Cross-template operational summary for the current site scope.",
                facts=list(self._facts_by_key.values()),
                template=None,
            )
            aggregated_gaps: list[TemplateGap] = list(dashboard_context["gaps"])
            for template in included_templates:
                config = template.config if isinstance(template.config, ReportConfig) else ReportConfig()
                gap_window_field = _date_field_for_report_window_config(config, report_name=template.name)
                gap_window_start, gap_window_end = _window_bounds(30, today=self.today)
                gap_facts = self._facts_for_window(
                    self._facts_for_config(config),
                    window_field=gap_window_field,
                    window_start=gap_window_start,
                    window_end=gap_window_end,
                )
                aggregated_gaps.extend(
                    self._build_data_gaps(
                        template=template,
                        report_name=template.name,
                        facts=gap_facts,
                    )
                )
            self._write_master_dashboard_sheet(workbook, formats, dashboard_context, used_names)
            self._write_trends_sheet(workbook, formats, dashboard_context["trend_rows"], title=_unique_sheet_name("Trends", used_names))
            self._write_data_gaps_sheet(workbook, formats, aggregated_gaps, title=_unique_sheet_name("Data Gaps", used_names))

            if not included_templates:
                self._write_index_sheet(index_sheet, formats, [])
                return

            for template in included_templates:
                config = template.config if isinstance(template.config, ReportConfig) else ReportConfig()
                for window_label, window_days in _WINDOW_EXPORT_SPECS:
                    sheet_name = _unique_sheet_name(f"{template.name} {window_days}d", used_names)
                    window_summary = self._write_template_window_sheet(
                        workbook,
                        formats,
                        template=template,
                        config=config,
                        report_name=template.name,
                        report_description=template.description or "",
                        window_label=window_label,
                        window_days=window_days,
                        sheet_name=sheet_name,
                    )
                    index_rows.append(
                        {
                            "report": template.name,
                            "sheet": sheet_name,
                            "window": window_label,
                            "window_field": window_summary["window_field_label"],
                            "window_start": window_summary["window_start"].isoformat(),
                            "window_end": window_summary["window_end"].isoformat(),
                            "category": template.category or "",
                            "readiness": window_summary["readiness"],
                            "view": window_summary["view_type"],
                            "rows": window_summary["row_count"],
                            "description": template.description or "",
                            "notes": template.notes or "",
                        }
                    )
            self._write_index_sheet(index_sheet, formats, index_rows)
        finally:
            workbook.close()

    def _build_master_report_primary(self, *, path: str, templates: Sequence[ReportTemplate]) -> None:
        included_templates = [template for template in templates if template.include_in_master_export]
        self._prepare_master_changelogs(included_templates)
        workbook = xlsxwriter.Workbook(
            path,
            {
                "in_memory": False,
                "strings_to_numbers": False,
                "strings_to_formulas": False,
            },
        )
        try:
            formats = self._build_formats(workbook)
            used_names: set[str] = set()
            index_sheet_name = _unique_sheet_name("Report Index", used_names)
            index_sheet = workbook.add_worksheet(index_sheet_name)
            index_rows: list[dict[str, Any]] = []

            dashboard_context = self._build_dashboard_context(
                report_name="Executive Dashboard",
                report_description="Cross-template operational summary for the current site scope.",
                facts=list(self._facts_by_key.values()),
                template=None,
            )
            anomaly = self._detect_escalation_anomaly(dashboard_context["trend_rows"])
            dashboard_info = self._write_master_dashboard_sheet(workbook, formats, dashboard_context, used_names)
            self._write_master_trends_sheet(
                workbook,
                formats,
                dashboard_context["trend_rows"],
                used_names,
                anomaly=anomaly,
            )

            aggregated_gaps: list[TemplateGap] = []
            detail_summaries: list[MasterSheetSummary] = []

            for template in included_templates:
                config = template.config if isinstance(template.config, ReportConfig) else ReportConfig()
                gap_window_field = _date_field_for_report_window_config(config, report_name=template.name)
                gap_window_start, gap_window_end = _window_bounds(30, today=self.today)
                gap_facts = self._facts_for_window(
                    self._facts_for_config(config),
                    window_field=gap_window_field,
                    window_start=gap_window_start,
                    window_end=gap_window_end,
                )
                aggregated_gaps.extend(
                    self._build_data_gaps(
                        template=template,
                        report_name=template.name,
                        facts=gap_facts,
                    )
                )
                for window_label, window_days in _WINDOW_EXPORT_SPECS:
                    sheet_name = _unique_sheet_name(f"{template.name} {window_days}d", used_names)
                    summary = self._write_master_template_window_sheet(
                        workbook,
                        formats,
                        template=template,
                        config=config,
                        report_name=template.name,
                        report_description=template.description or "",
                        window_label=window_label,
                        window_days=window_days,
                        sheet_name=sheet_name,
                    )
                    detail_summaries.append(summary)
                    index_rows.append(
                        {
                            "report": summary.report_name,
                            "sheet": summary.sheet_name,
                            "window": summary.window_label,
                            "window_field": summary.window_field_label,
                            "window_start": summary.window_start.isoformat(),
                            "window_end": summary.window_end.isoformat(),
                            "category": summary.category,
                            "readiness": summary.readiness,
                            "view": summary.view_type,
                            "rows": summary.row_count,
                            "description": summary.description,
                            "notes": summary.notes,
                        }
                    )

            if anomaly:
                aggregated_gaps.append(
                    TemplateGap(
                        "Escalation Rate",
                        "30 Day",
                        "anomaly",
                        (
                            f"{anomaly.count:,} escalations on {anomaly.day} is "
                            f"~{max(1, round(anomaly.count / max(anomaly.baseline_peak, 1))):,}x typical daily volume"
                        ),
                        "Verify with Jira audit log. If artifact, exclude and re-run.",
                    )
                )

            self._write_data_gaps_sheet(
                workbook,
                formats,
                aggregated_gaps,
                title=_unique_sheet_name("Data Gaps", used_names),
            )
            self._write_master_index_sheet(index_sheet, formats, index_rows)
            self._populate_master_dashboard_sheet(
                dashboard_info["worksheet"],
                formats,
                dashboard_context,
                helper_sheet_name=dashboard_info["helper_sheet_name"],
                detail_summaries=detail_summaries,
                anomaly=anomaly,
            )
        finally:
            workbook.close()

    def _write_index_sheet(self, worksheet, formats: dict[str, Any], rows: Sequence[dict[str, Any]]) -> None:
        headers = [
            "Report",
            "Sheet",
            "Window",
            "Window Field",
            "Window Start",
            "Window End",
            "Category",
            "Readiness",
            "View",
            "Rows",
            "Description",
            "Notes",
        ]
        worksheet.write_row(0, 0, headers, formats["header"])
        if not rows:
            worksheet.write(1, 0, "No report templates are currently included in the master export.", formats["text"])
            worksheet.set_column(0, 0, 48)
            worksheet.freeze_panes(1, 0)
            return
        for row_idx, row in enumerate(rows, start=1):
            worksheet.write(row_idx, 0, row["report"], formats["text"])
            worksheet.write_url(row_idx, 1, f"internal:'{row['sheet']}'!A1", string=row["sheet"], cell_format=formats["link"])
            worksheet.write(row_idx, 2, row["window"], formats["text"])
            worksheet.write(row_idx, 3, row["window_field"], formats["text"])
            worksheet.write(row_idx, 4, row["window_start"], formats["date_text"])
            worksheet.write(row_idx, 5, row["window_end"], formats["date_text"])
            worksheet.write(row_idx, 6, row["category"], formats["text"])
            worksheet.write(row_idx, 7, row["readiness"], formats["text"])
            worksheet.write(row_idx, 8, row["view"], formats["text"])
            worksheet.write_number(row_idx, 9, int(row["rows"]), formats["integer"])
            worksheet.write(row_idx, 10, row["description"], formats["wrap"])
            worksheet.write(row_idx, 11, row["notes"], formats["wrap"])
        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, max(1, len(rows)), len(headers) - 1)
        worksheet.set_column(0, 0, 30)
        worksheet.set_column(1, 1, 28)
        worksheet.set_column(2, 5, 14)
        worksheet.set_column(6, 8, 16)
        worksheet.set_column(9, 9, 10)
        worksheet.set_column(10, 10, 48)
        worksheet.set_column(11, 11, 60)

    def _write_single_summary_sheet(self, workbook, formats: dict[str, Any], context: dict[str, Any]) -> None:
        worksheet = workbook.add_worksheet("Summary")
        self._write_dashboard_core(worksheet, workbook, formats, context, dashboard_title="Summary")

    def _write_master_dashboard_sheet(
        self,
        workbook,
        formats: dict[str, Any],
        context: dict[str, Any],
        used_names: set[str],
    ) -> dict[str, Any]:
        worksheet = workbook.add_worksheet(_unique_sheet_name("Executive Dashboard", used_names))
        helper_sheet_name = self._write_dashboard_core(
            worksheet,
            workbook,
            formats,
            context,
            dashboard_title="Executive Dashboard",
        )
        return {"worksheet": worksheet, "helper_sheet_name": helper_sheet_name}

    def _write_dashboard_core(self, worksheet, workbook, formats: dict[str, Any], context: dict[str, Any], *, dashboard_title: str) -> str:
        helper_sheet_name = self._write_dashboard_helper_sheet(workbook, formats, context, dashboard_title=dashboard_title)
        worksheet.write(0, 0, dashboard_title, formats["title"])
        worksheet.write(1, 0, context["report_name"], formats["subtitle"])
        worksheet.write(2, 0, context["report_description"], formats["text"])
        worksheet.write(3, 0, f"Generated: {self.now.isoformat()}", formats["muted"])

        kpi_headers = [
            "Metric",
            "7d",
            "30d",
            "Δ vs Prior",
            "Sparkline",
        ]
        start_row = 5
        worksheet.write_row(start_row, 0, kpi_headers, formats["header"])
        for offset, metric_row in enumerate(context["kpis"], start=1):
            row_idx = start_row + offset
            worksheet.write(row_idx, 0, metric_row["label"], formats["text"])
            if metric_row["type"] == "percent":
                worksheet.write_number(row_idx, 1, metric_row["value_7d"], formats["percent"])
                worksheet.write_number(row_idx, 2, metric_row["value_30d"], formats["percent"])
                worksheet.write_number(row_idx, 3, metric_row["delta"], formats["delta_percent"])
            elif metric_row["type"] == "integer":
                worksheet.write_number(row_idx, 1, metric_row["value_7d"], formats["integer"])
                worksheet.write_number(row_idx, 2, metric_row["value_30d"], formats["integer"])
                worksheet.write_number(row_idx, 3, metric_row["delta"], formats["integer"])
            else:
                worksheet.write_number(row_idx, 1, metric_row["value_7d"], formats["hours"])
                worksheet.write_number(row_idx, 2, metric_row["value_30d"], formats["hours"])
                worksheet.write_number(row_idx, 3, metric_row["delta"], formats["hours"])

        sparkline_map = {
            "Ticket Volume": f"'{helper_sheet_name}'!B2:{xl_col_to_name(len(context['trend_rows']))}2",
            "Backlog Count": f"'{helper_sheet_name}'!B3:{xl_col_to_name(len(context['trend_rows']))}3",
            "MTTR P95 (h)": f"'{helper_sheet_name}'!B4:{xl_col_to_name(len(context['trend_rows']))}4",
            "First Response SLA Met %": f"'{helper_sheet_name}'!B5:{xl_col_to_name(len(context['trend_rows']))}5",
            "SLA Compliance Rate %": f"'{helper_sheet_name}'!B6:{xl_col_to_name(len(context['trend_rows']))}6",
        }
        for offset, metric_row in enumerate(context["kpis"], start=1):
            row_idx = start_row + offset
            source = sparkline_map.get(metric_row["label"])
            if source:
                worksheet.add_sparkline(row_idx, 4, {"range": source, "series_color": "#1F4E79"})

        worksheet.write(start_row, 6, "Top 3 Problem Areas", formats["header"])
        for idx, problem in enumerate(context["problem_areas"], start=1):
            worksheet.write(start_row + idx, 6, problem, formats["wrap"])

        self._insert_dashboard_charts(worksheet, workbook, context, helper_sheet_name=helper_sheet_name)

        for offset, metric_row in enumerate(context["kpis"], start=1):
            if metric_row["type"] != "percent":
                continue
            row_idx = start_row + offset
            worksheet.conditional_format(row_idx, 1, row_idx, 2, {
                "type": "cell",
                "criteria": ">=",
                "value": 0.95,
                "format": formats["kpi_good"],
            })
            worksheet.conditional_format(row_idx, 1, row_idx, 2, {
                "type": "cell",
                "criteria": "between",
                "minimum": 0.85,
                "maximum": 0.9499,
                "format": formats["kpi_warn"],
            })
            worksheet.conditional_format(row_idx, 1, row_idx, 2, {
                "type": "cell",
                "criteria": "<",
                "value": 0.85,
                "format": formats["kpi_bad"],
            })
        worksheet.set_column(0, 0, 28)
        worksheet.set_column(1, 3, 14)
        worksheet.set_column(4, 4, 18)
        worksheet.set_column(6, 6, 42)
        return helper_sheet_name

    def _write_dashboard_helper_sheet(self, workbook, formats: dict[str, Any], context: dict[str, Any], *, dashboard_title: str) -> str:
        worksheet = workbook.add_worksheet(_sanitize_sheet_name(f"{dashboard_title} Data"))
        worksheet.hide()
        base_col = 0
        worksheet.write_row(0, base_col, [point["date"] for point in context["trend_rows"]], formats["hidden"])
        ticket_volume_values = [point["tickets_created"] for point in context["trend_rows"]]
        backlog_values = [point["backlog_count"] for point in context["trend_rows"]]
        mttr_p95_values = [point["mttr_p95_hours"] or 0.0 for point in context["trend_rows"]]
        first_response_values = [point["first_response_met_rate"] for point in context["trend_rows"]]
        sla_values = [point["sla_compliance_rate"] for point in context["trend_rows"]]
        helper_rows = [
            ticket_volume_values,
            backlog_values,
            mttr_p95_values,
            first_response_values,
            sla_values,
        ]
        for idx, values in enumerate(helper_rows, start=1):
            worksheet.write_row(idx, base_col + 1, values, formats["hidden"])

        base_col = 12
        worksheet.write_row(0, base_col, ["Date", "Created", "Resolved", "MTTR P95", "SLA Compliance %"], formats["hidden"])
        for idx, point in enumerate(context["trend_rows"], start=1):
            worksheet.write(idx, base_col, point["date"], formats["hidden"])
            worksheet.write_number(idx, base_col + 1, point["tickets_created"], formats["hidden"])
            worksheet.write_number(idx, base_col + 2, point["tickets_resolved"], formats["hidden"])
            worksheet.write_number(idx, base_col + 3, point["mttr_p95_hours"] or 0.0, formats["hidden"])
            worksheet.write_number(idx, base_col + 4, point["sla_compliance_rate"], formats["hidden"])

        section_row = 40
        worksheet.write_row(section_row, base_col, ["Status", "Count"], formats["hidden"])
        for offset, (label, count) in enumerate(context["sla_status_counts"].items(), start=1):
            worksheet.write(section_row + offset, base_col, label, formats["hidden"])
            worksheet.write_number(section_row + offset, base_col + 1, count, formats["hidden"])

        mttr_row = 48
        worksheet.write_row(mttr_row, base_col, ["Priority", "Avg", "P95"], formats["hidden"])
        for offset, row in enumerate(context["mttr_priority_rows"], start=1):
            worksheet.write(mttr_row + offset, base_col, row["group"], formats["hidden"])
            worksheet.write_number(mttr_row + offset, base_col + 1, row["avg_ttr_hours"] or 0.0, formats["hidden"])
            worksheet.write_number(mttr_row + offset, base_col + 2, row["p95_ttr_hours"] or 0.0, formats["hidden"])

        volume_row = 56
        worksheet.write_row(volume_row, base_col, ["Category", "Count"], formats["hidden"])
        for offset, row in enumerate(context["top_category_rows"], start=1):
            worksheet.write(volume_row + offset, base_col, row["group"], formats["hidden"])
            worksheet.write_number(volume_row + offset, base_col + 1, row["count"], formats["hidden"])

        backlog_row = 68
        backlog_statuses = list(context["backlog_statuses"])
        worksheet.write_row(backlog_row, base_col, ["Bucket", *backlog_statuses, "Total"], formats["hidden"])
        for offset, row in enumerate(context["backlog_rows"], start=1):
            worksheet.write(backlog_row + offset, base_col, row["bucket"], formats["hidden"])
            for status_idx, status in enumerate(backlog_statuses, start=1):
                worksheet.write_number(backlog_row + offset, base_col + status_idx, row["status_counts"].get(status, 0), formats["hidden"])
            worksheet.write_number(backlog_row + offset, base_col + len(backlog_statuses) + 1, row["total"], formats["hidden"])

        escalation_row = 82
        worksheet.write_row(escalation_row, base_col, ["Assignee", "Escalated"], formats["hidden"])
        for offset, row in enumerate(context["escalation_rows"], start=1):
            worksheet.write(escalation_row + offset, base_col, row["group"], formats["hidden"])
            worksheet.write_number(escalation_row + offset, base_col + 1, row["escalated_count"], formats["hidden"])

        fr_row = 94
        worksheet.write_row(fr_row, base_col, ["First Response Status", "Count"], formats["hidden"])
        for offset, (label, count) in enumerate(context["first_response_status_counts"].items(), start=1):
            worksheet.write(fr_row + offset, base_col, label, formats["hidden"])
            worksheet.write_number(fr_row + offset, base_col + 1, count, formats["hidden"])
        worksheet.write_comment(
            0,
            0,
            "Section: Transposed daily data. Row 2=Created, Row 3=Backlog, Row 4=MTTR P95, Row 5=First Response SLA Met %, Row 6=SLA Compliance %.",
        )
        worksheet.write_comment(
            0,
            12,
            "Section: Daily Time Series for trend charts and sparklines",
        )
        section_labels = {
            40: "--- SLA Compliance (Doughnut Source) ---",
            48: "--- MTTR by Priority (Bar Source) ---",
            56: "--- Ticket Volume by Category (Bar Source) ---",
            68: "--- Backlog Aging (Stacked Source) ---",
            82: "--- Escalation by Assignee (Column Source) ---",
            94: "--- First Response SLA (Doughnut Source) ---",
        }
        for row_idx, label in section_labels.items():
            worksheet.write(row_idx, 10, label, formats["hidden_note"])
        return worksheet.name

    def _insert_dashboard_charts(self, worksheet, workbook, context: dict[str, Any], *, helper_sheet_name: str) -> None:
        base_col = 12
        chart_trends = workbook.add_chart({"type": "line"})
        chart_trends.add_series({
            "name": "Tickets Created",
            "categories": [helper_sheet_name, 1, base_col, len(context["trend_rows"]), base_col],
            "values": [helper_sheet_name, 1, base_col + 1, len(context["trend_rows"]), base_col + 1],
            "line": {"color": "#2563EB", "width": 2.0},
            "marker": {"type": "circle", "size": 4, "border": {"color": "#2563EB"}, "fill": {"color": "#2563EB"}},
        })
        chart_trends.add_series({
            "name": "Tickets Resolved",
            "categories": [helper_sheet_name, 1, base_col, len(context["trend_rows"]), base_col],
            "values": [helper_sheet_name, 1, base_col + 2, len(context["trend_rows"]), base_col + 2],
            "line": {"color": "#10B981", "width": 2.0},
            "marker": {"type": "diamond", "size": 4, "border": {"color": "#10B981"}, "fill": {"color": "#10B981"}},
        })
        chart_trends.set_y_axis({"name": "Ticket Count"})
        chart_trends.set_x_axis({"name": "Date", "label_position": "low"})
        chart_trends.set_legend({"position": "bottom"})
        chart_trends.set_title({"name": "30-Day Trend"})
        chart_trends.set_plotarea({"border": {"none": True}})
        line_chart = workbook.add_chart({"type": "line"})
        line_chart.add_series({
            "name": "MTTR P95",
            "categories": [helper_sheet_name, 1, base_col, len(context["trend_rows"]), base_col],
            "values": [helper_sheet_name, 1, base_col + 3, len(context["trend_rows"]), base_col + 3],
            "y2_axis": True,
            "line": {"color": "#DC2626", "width": 2.25, "dash_type": "dash"},
            "marker": {"type": "square", "size": 4, "border": {"color": "#DC2626"}, "fill": {"color": "#DC2626"}},
        })
        line_chart.set_y2_axis({"name": "MTTR P95 (hours)"})
        chart_trends.combine(line_chart)
        worksheet.insert_chart("A14", chart_trends, {"x_scale": 1.35, "y_scale": 1.1})

        chart_sla = workbook.add_chart({"type": "doughnut"})
        status_count = len(context["sla_status_counts"])
        if status_count > 0:
            chart_sla.add_series({
                "name": "SLA Compliance",
                "categories": [helper_sheet_name, 41, base_col, 40 + status_count, base_col],
                "values": [helper_sheet_name, 41, base_col + 1, 40 + status_count, base_col + 1],
            })
            chart_sla.set_title({"name": "SLA Compliance"})
            worksheet.insert_chart("J14", chart_sla, {"x_scale": 1.0, "y_scale": 1.0})

        mttr_count = len(context["mttr_priority_rows"])
        if mttr_count > 0:
            chart_mttr = workbook.add_chart({"type": "bar"})
            chart_mttr.add_series({
                "name": "Avg TTR",
                "categories": [helper_sheet_name, 49, base_col, 48 + mttr_count, base_col],
                "values": [helper_sheet_name, 49, base_col + 1, 48 + mttr_count, base_col + 1],
            })
            chart_mttr.add_series({
                "name": "P95 TTR",
                "categories": [helper_sheet_name, 49, base_col, 48 + mttr_count, base_col],
                "values": [helper_sheet_name, 49, base_col + 2, 48 + mttr_count, base_col + 2],
            })
            chart_mttr.set_title({"name": "MTTR by Priority"})
            worksheet.insert_chart("A33", chart_mttr, {"x_scale": 1.2, "y_scale": 1.1})

        volume_count = len(context["top_category_rows"])
        if volume_count > 0:
            chart_volume = workbook.add_chart({"type": "bar"})
            chart_volume.add_series({
                "name": "Tickets",
                "categories": [helper_sheet_name, 57, base_col, 56 + volume_count, base_col],
                "values": [helper_sheet_name, 57, base_col + 1, 56 + volume_count, base_col + 1],
            })
            chart_volume.set_title({"name": "Ticket Volume by Category"})
            worksheet.insert_chart("J33", chart_volume, {"x_scale": 1.0, "y_scale": 1.0})

        backlog_row_count = len(context["backlog_rows"])
        if backlog_row_count > 0 and context["backlog_statuses"]:
            chart_backlog = workbook.add_chart({"type": "column", "subtype": "stacked"})
            for offset, status in enumerate(context["backlog_statuses"], start=1):
                chart_backlog.add_series({
                    "name": status,
                    "categories": [helper_sheet_name, 69, base_col, 68 + backlog_row_count, base_col],
                    "values": [helper_sheet_name, 69, base_col + offset, 68 + backlog_row_count, base_col + offset],
                })
            chart_backlog.set_title({"name": "Backlog Aging"})
            worksheet.insert_chart("A52", chart_backlog, {"x_scale": 1.2, "y_scale": 1.0})

        escalation_count = len(context["escalation_rows"])
        if escalation_count > 0:
            chart_escalation = workbook.add_chart({"type": "column"})
            chart_escalation.add_series({
                "name": "Escalated Tickets",
                "categories": [helper_sheet_name, 83, base_col, 82 + escalation_count, base_col],
                "values": [helper_sheet_name, 83, base_col + 1, 82 + escalation_count, base_col + 1],
            })
            chart_escalation.set_title({"name": "Escalation by Assignee"})
            worksheet.insert_chart("J52", chart_escalation, {"x_scale": 1.0, "y_scale": 1.0})

        fr_count = len(context["first_response_status_counts"])
        if fr_count > 0:
            chart_fr = workbook.add_chart({"type": "doughnut"})
            chart_fr.add_series({
                "name": "First Response SLA",
                "categories": [helper_sheet_name, 95, base_col, 94 + fr_count, base_col],
                "values": [helper_sheet_name, 95, base_col + 1, 94 + fr_count, base_col + 1],
            })
            chart_fr.set_title({"name": "First Response SLA"})
            worksheet.insert_chart("J69", chart_fr, {"x_scale": 1.0, "y_scale": 1.0})

    def _populate_master_dashboard_sheet(
        self,
        worksheet,
        formats: dict[str, Any],
        context: dict[str, Any],
        *,
        helper_sheet_name: str,
        detail_summaries: Sequence[MasterSheetSummary],
        anomaly: TrendAnomaly | None,
    ) -> None:
        summary_lookup = {(summary.report_name, summary.window_label): summary for summary in detail_summaries}
        sla_7 = summary_lookup.get(("SLA Compliance Rate", "7 Day"))
        sla_30 = summary_lookup.get(("SLA Compliance Rate", "30 Day"))
        mttr_7 = summary_lookup.get(("Mean Time to Resolution", "7 Day"))
        mttr_30 = summary_lookup.get(("Mean Time to Resolution", "30 Day"))
        fr_7 = summary_lookup.get(("First Response Time", "7 Day"))
        fr_30 = summary_lookup.get(("First Response Time", "30 Day"))
        volume_7 = summary_lookup.get(("Ticket Volume by Category", "7 Day"))
        volume_30 = summary_lookup.get(("Ticket Volume by Category", "30 Day"))
        start_row = 5
        worksheet.write(start_row, 5, "Trend", formats["header"])
        worksheet.write(start_row, 6, "Key Findings & Actions", formats["header"])

        if sla_7 and sla_30 and sla_7.metric_row is not None and sla_30.metric_row is not None:
            worksheet.write_formula(
                start_row + 1,
                1,
                f"='{sla_7.sheet_name}'!B{sla_7.metric_row + 1}",
                formats["percent"],
                context["kpis"][0]["value_7d"],
            )
            worksheet.write_formula(
                start_row + 1,
                2,
                f"='{sla_30.sheet_name}'!B{sla_30.metric_row + 1}",
                formats["percent"],
                context["kpis"][0]["value_30d"],
            )
            worksheet.write_formula(
                start_row + 1,
                3,
                f"=B{start_row + 2}-C{start_row + 2}",
                formats["delta_percent"],
                context["kpis"][0]["value_7d"] - context["kpis"][0]["value_30d"],
            )
        if mttr_7 and mttr_30 and mttr_7.total_row is not None and mttr_30.total_row is not None:
            worksheet.write_formula(
                start_row + 2,
                1,
                f"='{mttr_7.sheet_name}'!F{mttr_7.total_row + 1}",
                formats["hours"],
                context["kpis"][1]["value_7d"],
            )
            worksheet.write_formula(
                start_row + 2,
                2,
                f"='{mttr_30.sheet_name}'!F{mttr_30.total_row + 1}",
                formats["hours"],
                context["kpis"][1]["value_30d"],
            )
            worksheet.write_formula(
                start_row + 2,
                3,
                f"=B{start_row + 3}-C{start_row + 3}",
                formats["hours"],
                context["kpis"][1]["value_7d"] - context["kpis"][1]["value_30d"],
            )
        if fr_7 and fr_30 and fr_7.metric_row is not None and fr_30.metric_row is not None:
            worksheet.write_formula(
                start_row + 3,
                1,
                f"='{fr_7.sheet_name}'!B{fr_7.metric_row + 1}",
                formats["percent"],
                context["kpis"][2]["value_7d"],
            )
            worksheet.write_formula(
                start_row + 3,
                2,
                f"='{fr_30.sheet_name}'!B{fr_30.metric_row + 1}",
                formats["percent"],
                context["kpis"][2]["value_30d"],
            )
            worksheet.write_formula(
                start_row + 3,
                3,
                f"=B{start_row + 4}-C{start_row + 4}",
                formats["delta_percent"],
                context["kpis"][2]["value_7d"] - context["kpis"][2]["value_30d"],
            )
        worksheet.write_formula(
            start_row + 4,
            1,
            "=INDEX(Trends!G5:G34,COUNTA(Trends!G5:G34))",
            formats["integer"],
            context["kpis"][3]["value_7d"],
        )
        worksheet.write_formula(
            start_row + 4,
            2,
            f"=B{start_row + 5}",
            formats["integer"],
            context["kpis"][3]["value_30d"],
        )
        worksheet.write_formula(
            start_row + 4,
            3,
            "=INDEX(Trends!G5:G34,COUNTA(Trends!G5:G34))-INDEX(Trends!G5:G34,1)",
            formats["integer"],
            (
                (context["trend_rows"][-1]["backlog_count"] - context["trend_rows"][0]["backlog_count"])
                if context["trend_rows"]
                else 0
            ),
        )
        if volume_7 and volume_30 and volume_7.total_row is not None and volume_30.total_row is not None:
            worksheet.write_formula(
                start_row + 5,
                1,
                f"='{volume_7.sheet_name}'!B{volume_7.total_row + 1}",
                formats["integer"],
                context["kpis"][4]["value_7d"],
            )
            worksheet.write_formula(
                start_row + 5,
                2,
                f"='{volume_30.sheet_name}'!B{volume_30.total_row + 1}",
                formats["integer"],
                context["kpis"][4]["value_30d"],
            )
            worksheet.write_formula(
                start_row + 5,
                3,
                f"=B{start_row + 6}-C{start_row + 6}",
                formats["integer"],
                context["kpis"][4]["value_7d"] - context["kpis"][4]["value_30d"],
            )

        trend_rows = {
            6: ("=IF(D7>0,\"▲\",IF(D7<0,\"▼\",\"—\"))", "good_up"),
            7: ("=IF(D8<0,\"▲\",IF(D8>0,\"▼\",\"—\"))", "good_down"),
            8: ("=IF(D9>0,\"▲\",IF(D9<0,\"▼\",\"—\"))", "good_up"),
            9: ("=IF(D10<0,\"▲\",IF(D10>0,\"▼\",\"—\"))", "good_down"),
            10: ("=IF(D11<0,\"▲\",IF(D11>0,\"▼\",\"—\"))", "good_down"),
        }
        for row_idx, (formula, direction) in trend_rows.items():
            cached = "—"
            delta = context["kpis"][row_idx - 6]["delta"]
            if direction == "good_up":
                cached = "▲" if delta > 0 else ("▼" if delta < 0 else "—")
            else:
                cached = "▲" if delta < 0 else ("▼" if delta > 0 else "—")
            worksheet.write_formula(row_idx, 5, formula, formats["trend_arrow"], cached)

        worksheet.conditional_format(6, 5, 10, 5, {
            "type": "text",
            "criteria": "containing",
            "value": "▲",
            "format": formats["arrow_good"],
        })
        worksheet.conditional_format(6, 5, 10, 5, {
            "type": "text",
            "criteria": "containing",
            "value": "▼",
            "format": formats["arrow_bad"],
        })
        worksheet.conditional_format(6, 1, 6, 2, {
            "type": "cell",
            "criteria": ">=",
            "value": 0.9,
            "format": formats["kpi_good"],
        })
        worksheet.conditional_format(6, 1, 6, 2, {
            "type": "cell",
            "criteria": "between",
            "minimum": 0.75,
            "maximum": 0.9,
            "format": formats["kpi_warn"],
        })
        worksheet.conditional_format(6, 1, 6, 2, {
            "type": "cell",
            "criteria": "<",
            "value": 0.75,
            "format": formats["kpi_bad"],
        })
        worksheet.conditional_format(8, 1, 8, 2, {
            "type": "cell",
            "criteria": ">=",
            "value": 0.9,
            "format": formats["kpi_good"],
        })
        worksheet.conditional_format(8, 1, 8, 2, {
            "type": "cell",
            "criteria": "between",
            "minimum": 0.75,
            "maximum": 0.9,
            "format": formats["kpi_warn"],
        })
        worksheet.conditional_format(8, 1, 8, 2, {
            "type": "cell",
            "criteria": "<",
            "value": 0.75,
            "format": formats["kpi_bad"],
        })
        worksheet.conditional_format(7, 1, 7, 2, {
            "type": "cell",
            "criteria": "<=",
            "value": 200,
            "format": formats["kpi_good"],
        })
        worksheet.conditional_format(7, 1, 7, 2, {
            "type": "cell",
            "criteria": "between",
            "minimum": 200,
            "maximum": 1000,
            "format": formats["kpi_warn"],
        })
        worksheet.conditional_format(7, 1, 7, 2, {
            "type": "cell",
            "criteria": ">",
            "value": 1000,
            "format": formats["kpi_bad"],
        })

        findings = self._build_key_findings(context, anomaly=anomaly)
        for offset, finding in enumerate(findings, start=1):
            row_idx = start_row + offset
            worksheet.write(row_idx, 6, finding, formats["finding_text"])
            worksheet.set_row(row_idx, 42)

        worksheet.set_column(5, 5, 12)
        worksheet.set_column(6, 6, 58)

    def _build_key_findings(self, context: dict[str, Any], *, anomaly: TrendAnomaly | None) -> list[str]:
        def _group_row(rows: Sequence[dict[str, Any]], label: str) -> dict[str, Any] | None:
            return next((row for row in rows if str(row.get("group") or "").strip().lower() == label.lower()), None)

        sla_rate = context["kpis"][0]["value_30d"]
        sla_rows_30 = context.get("sla_rows_30") or []
        breached_sla = _group_row(sla_rows_30, "BREACHED") or {}
        met_sla = _group_row(sla_rows_30, "Met") or {}
        sla_icon = "🔴" if sla_rate < 0.9 else "🟢"

        mttr_rows = context.get("mttr_priority_rows") or []
        worst_mttr = max(mttr_rows, key=lambda row: row.get("p95_ttr_hours") or 0.0) if mttr_rows else {"group": "(none)", "p95_ttr_hours": 0.0}

        fr_rate = context["kpis"][2]["value_30d"]
        fr_rows_30 = context.get("first_response_rows_30") or []
        breached_fr = _group_row(fr_rows_30, "BREACHED") or {}
        fr_icon = "🟢" if fr_rate >= 0.9 else ("🟡" if fr_rate >= 0.75 else "🔴")

        backlog_rows = context.get("backlog_rows") or []
        fresh_backlog = _group_row(backlog_rows, "0-3 days") or {}
        oldest_backlog = _group_row(backlog_rows, "60+ days") or {}
        trend_rows = context.get("trend_rows") or []
        backlog_current = trend_rows[-1]["backlog_count"] if trend_rows else 0
        backlog_start = trend_rows[0]["backlog_count"] if trend_rows else 0
        backlog_icon = "🟢" if not (oldest_backlog.get("total") or 0) else "🟡"
        old_tickets_text = (
            "No tickets >60 days."
            if not (oldest_backlog.get("total") or 0)
            else f"{int(oldest_backlog.get('total') or 0):,} tickets are >60 days old."
        )

        findings = [
            (
                f"{sla_icon} SLA Compliance: {sla_rate:.1%} (30d) — below 90% target. "
                f"BREACHED tickets avg {(breached_sla.get('avg_ttr_hours') or 0.0):.1f}h TTR vs "
                f"{(met_sla.get('avg_ttr_hours') or 0.0):.1f}h for Met. "
                f"Focus: reduce breach count from {int(breached_sla.get('count') or 0):,}."
            ),
            (
                f"🔴 MTTR Tail Risk: {worst_mttr.get('group') or '(none)'} P95 = "
                f"{(worst_mttr.get('p95_ttr_hours') or 0.0):,.1f}h. "
                "Worst tail in the portfolio. Action: review that queue for stale tickets."
            ),
            (
                f"{fr_icon} First Response: {fr_rate:.1%} Met (30d). "
                f"{int(breached_fr.get('count') or 0):,} BREACHED avg {(breached_fr.get('avg_ttr_hours') or 0.0):.1f}h. "
                "Action: triage BREACHED first-response tickets."
            ),
            (
                f"{backlog_icon} Backlog: {backlog_current:,} open tickets, "
                f"{(fresh_backlog.get('percent_of_backlog') or 0.0):.0%} in 0-3d bucket. "
                f"{'Down' if backlog_current <= backlog_start else 'Up'} from {backlog_start:,}. "
                f"{old_tickets_text}"
            ),
        ]
        if anomaly:
            findings.append(
                f"⚠️ Data Quality: Escalation Rate & FCR are proxy metrics. {anomaly.count:,} escalation spike on {anomaly.day} is a suspected outlier and needs verification."
            )
        else:
            findings.append("⚠️ Data Quality: Escalation Rate and FCR are proxy metrics. See Data Gaps for current limitations.")
        return findings

    def _build_dashboard_context(
        self,
        *,
        report_name: str,
        report_description: str,
        facts: Sequence[ReportIssueFact],
        template: ReportTemplate | None,
    ) -> dict[str, Any]:
        trend_rows = self._build_trend_rows(facts)
        current_7_start, current_7_end = _window_bounds(7, today=self.today)
        current_30_start, current_30_end = _window_bounds(30, today=self.today)
        prior_7_start, prior_7_end = _prior_window_bounds(7, today=self.today)
        prior_30_start, prior_30_end = _prior_window_bounds(30, today=self.today)

        volume_7 = self._facts_for_window(facts, window_field="created", window_start=current_7_start, window_end=current_7_end)
        volume_30 = self._facts_for_window(facts, window_field="created", window_start=current_30_start, window_end=current_30_end)
        volume_prior_30 = self._facts_for_window(facts, window_field="created", window_start=prior_30_start, window_end=prior_30_end)

        mttr_7 = self._facts_for_window(facts, window_field="resolved", window_start=current_7_start, window_end=current_7_end)
        mttr_30 = self._facts_for_window(facts, window_field="resolved", window_start=current_30_start, window_end=current_30_end)
        mttr_prior_30 = self._facts_for_window(facts, window_field="resolved", window_start=prior_30_start, window_end=prior_30_end)

        fr_7 = self._facts_for_window(facts, window_field="created", window_start=current_7_start, window_end=current_7_end)
        fr_30 = self._facts_for_window(facts, window_field="created", window_start=current_30_start, window_end=current_30_end)
        fr_prior_30 = self._facts_for_window(facts, window_field="created", window_start=prior_30_start, window_end=prior_30_end)

        backlog_open = [fact for fact in facts if fact.is_open]
        backlog_prior = [fact for fact in facts if fact.created_dt and fact.created_dt.date() <= prior_30_end and (not fact.resolved_dt or fact.resolved_dt.date() > prior_30_end)]

        sla_7 = self._sla_status_counts(mttr_7)
        sla_30 = self._sla_status_counts(mttr_30)
        fr_status_7 = self._first_response_status_counts(fr_7)
        fr_status_30 = self._first_response_status_counts(fr_30)

        kpis = [
            {
                "label": "SLA Compliance Rate %",
                "type": "percent",
                "value_7d": self._sla_rate(sla_7),
                "value_30d": self._sla_rate(sla_30),
                "delta": self._sla_rate(sla_30) - self._sla_rate(self._sla_status_counts(self._facts_for_window(facts, window_field='resolved', window_start=prior_30_start, window_end=prior_30_end))),
            },
            {
                "label": "MTTR P95 (h)",
                "type": "hours",
                "value_7d": _percentile_hours(_metric_values_for_kind("mttr", mttr_7), 95) or 0.0,
                "value_30d": _percentile_hours(_metric_values_for_kind("mttr", mttr_30), 95) or 0.0,
                "delta": (_percentile_hours(_metric_values_for_kind("mttr", mttr_30), 95) or 0.0) - (_percentile_hours(_metric_values_for_kind("mttr", mttr_prior_30), 95) or 0.0),
            },
            {
                "label": "First Response SLA Met %",
                "type": "percent",
                "value_7d": self._met_rate(fr_status_7),
                "value_30d": self._met_rate(fr_status_30),
                "delta": self._met_rate(fr_status_30) - self._met_rate(self._first_response_status_counts(fr_prior_30)),
            },
            {
                "label": "Backlog Count",
                "type": "integer",
                "value_7d": len(backlog_open),
                "value_30d": len(backlog_open),
                "delta": len(backlog_open) - len(backlog_prior),
            },
            {
                "label": "Ticket Volume",
                "type": "integer",
                "value_7d": len(volume_7),
                "value_30d": len(volume_30),
                "delta": len(volume_30) - len(volume_prior_30),
            },
        ]

        top_category_rows = self._group_summary_rows(
            facts=volume_30,
            prior_facts=volume_prior_30,
            group_by="request_type",
            report_kind="ticket_volume",
        )
        if len(top_category_rows) > 10:
            other_count = sum(row["count"] for row in top_category_rows[10:])
            top_category_rows = top_category_rows[:10] + [{"group": "Other", "count": other_count, "avg_ttr_hours": 0.0, "p95_ttr_hours": 0.0}]

        mttr_priority_rows = self._group_summary_rows(
            facts=mttr_30,
            prior_facts=mttr_prior_30,
            group_by="priority",
            report_kind="mttr",
        )
        sla_rows_30 = self._group_summary_rows(
            facts=mttr_30,
            prior_facts=mttr_prior_30,
            group_by="sla_resolution_status",
            report_kind="sla",
        )
        first_response_rows_30 = self._group_summary_rows(
            facts=fr_30,
            prior_facts=fr_prior_30,
            group_by="sla_first_response_status",
            report_kind="first_response",
        )
        backlog_rows, backlog_statuses = self._backlog_rows(backlog_open, backlog_prior)
        escalation_rows = [
            row
            for row in self._group_summary_rows(
                facts=fr_30,
                prior_facts=fr_prior_30,
                group_by="assignee",
                report_kind="escalation",
            )
            if row.get("escalated_count")
        ][:10]

        gap_facts = facts
        if template is not None:
            gap_window_field = _date_field_for_report_window_config(template.config, report_name=report_name)
            gap_facts = self._facts_for_window(
                facts,
                window_field=gap_window_field,
                window_start=current_30_start,
                window_end=current_30_end,
            )
        gaps = self._build_data_gaps(template=template, report_name=report_name, facts=gap_facts)
        problem_areas = self._problem_areas(mttr_priority_rows, top_category_rows, backlog_rows)
        return {
            "report_name": report_name,
            "report_description": report_description,
            "trend_rows": trend_rows,
            "kpis": kpis,
            "sla_status_counts": sla_30,
            "first_response_status_counts": fr_status_30,
            "mttr_priority_rows": mttr_priority_rows,
            "sla_rows_30": sla_rows_30,
            "first_response_rows_30": first_response_rows_30,
            "top_category_rows": top_category_rows,
            "backlog_rows": backlog_rows,
            "backlog_statuses": backlog_statuses,
            "escalation_rows": escalation_rows,
            "problem_areas": problem_areas,
            "gaps": gaps,
        }

    def _build_trend_rows(self, facts: Sequence[ReportIssueFact]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for offset in range(29, -1, -1):
            day = self.today - timedelta(days=offset)
            created = [fact for fact in facts if fact.created_dt and fact.created_dt.date() == day]
            resolved = [fact for fact in facts if fact.resolved_dt and fact.resolved_dt.date() == day]
            backlog = [
                fact
                for fact in facts
                if fact.created_dt and fact.created_dt.date() <= day and (not fact.resolved_dt or fact.resolved_dt.date() > day)
            ]
            escalated = [fact for fact in facts if day in fact.escalation_event_dates]
            sla_counts = self._sla_status_counts(resolved)
            fr_counts = self._first_response_status_counts(created)
            rows.append(
                {
                    "date": day.isoformat(),
                    "tickets_created": len(created),
                    "tickets_resolved": len(resolved),
                    "mttr_avg_hours": _mean_hours(_metric_values_for_kind("mttr", resolved)) or 0.0,
                    "mttr_p95_hours": _percentile_hours(_metric_values_for_kind("mttr", resolved), 95) or 0.0,
                    "sla_compliance_rate": self._sla_rate(sla_counts),
                    "backlog_count": len(backlog),
                    "escalation_count": len(escalated),
                    "first_response_met_rate": self._met_rate(fr_counts),
                }
            )
        return rows

    def _build_data_gaps(
        self,
        *,
        template: ReportTemplate | None,
        report_name: str,
        facts: Sequence[ReportIssueFact],
    ) -> list[TemplateGap]:
        name = report_name.strip().lower()
        report_kind = _report_kind(
            template.name if template is not None else report_name,
            template.config if template is not None else ReportConfig(),
        )
        gaps: list[TemplateGap] = []
        template_readiness = "proxy"
        if template is not None:
            template_readiness = _template_readiness(template, facts=facts)
            if template_readiness in {"gap", "proxy"}:
                limitation = template.notes or "This report relies on partial source data."
                recommendation = "Review the configured Jira fields or workflow history to improve readiness."
                gaps.append(TemplateGap(template.name, "All", template_readiness, limitation, recommendation))
        if report_kind == "first_response" or "first response" in name:
            missing = sum(1 for fact in facts if fact.first_response_hours is None)
            if missing:
                gaps.append(
                    TemplateGap(
                        report_name,
                        "All",
                        template_readiness,
                        f"{missing} tickets are missing Jira first-response elapsed time, so percentile reporting is partial.",
                        "Ensure the Jira first-response SLA timer is populated for all relevant requests.",
                    )
                )
        if report_kind == "follow_up" or "daily follow-up" in name or "daily follow up" in name:
            missing_followup = sum(1 for fact in facts if not fact.followup_authoritative)
            missing_first_response = sum(1 for fact in facts if not fact.first_response_authoritative)
            if missing_followup or missing_first_response:
                limitation_parts: list[str] = []
                if missing_followup:
                    limitation_parts.append(
                        f"{missing_followup} tickets are missing authoritative Daily Public Follow-Up fields"
                    )
                if missing_first_response:
                    limitation_parts.append(
                        f"{missing_first_response} tickets are missing Jira first-response SLA status"
                    )
                gaps.append(
                    TemplateGap(
                        report_name,
                        "All",
                        "proxy",
                        "; ".join(limitation_parts) + ". Proxy fallback is being used for those tickets.",
                        "Populate Jira public-agent touch fields via Automation and confirm the first-response SLA timer is available for all relevant requests.",
                    )
                )
        if report_kind == "escalation" or "escalation" in name:
            gaps.append(
                TemplateGap(
                    report_name,
                    "All",
                    "proxy",
                    "Escalation rate currently uses assignee-change, priority-increase, and marker heuristics.",
                    "Add explicit Jira escalation markers or workflow transitions to move this metric from proxy to ready.",
                )
            )
        if report_kind == "fcr" or "first contact" in name:
            gaps.append(
                TemplateGap(
                    report_name,
                    "All",
                    "proxy",
                    "First Contact Resolution still uses a one-touch proxy based on first resolution timing and comment volume.",
                    "Add contact-cycle data or explicit one-touch markers to make FCR authoritative.",
                )
            )
        if report_kind == "csat" or "csat" in name:
            gaps.append(
                TemplateGap(
                    report_name,
                    "All",
                    "gap",
                    "No survey source is currently connected for CSAT.",
                    "Connect CSAT survey data to Jira or a linked satisfaction feed.",
                )
            )
        if any(_is_master_changelog_skip_error(fact.changelog_error) for fact in facts):
            gaps.append(
                TemplateGap(
                    report_name,
                    "All",
                    "proxy",
                    "Jira changelog prefetch was skipped for this large master export, so escalation and reopen heuristics may be incomplete.",
                    "Reduce master export scope or move changelog enrichment to an asynchronous export pipeline.",
                )
            )
        non_skip_changelog_errors = [
            fact.changelog_error
            for fact in facts
            if fact.changelog_error and not _is_master_changelog_skip_error(fact.changelog_error)
        ]
        if non_skip_changelog_errors:
            gaps.append(
                TemplateGap(
                    report_name,
                    "All",
                    "proxy",
                    "Some Jira changelog fetches failed, so reopen and escalation heuristics may be incomplete.",
                    "Check Jira API connectivity and changelog permissions for the report service account.",
                )
            )
        return gaps

    def _problem_areas(
        self,
        mttr_rows: Sequence[dict[str, Any]],
        category_rows: Sequence[dict[str, Any]],
        backlog_rows: Sequence[dict[str, Any]],
    ) -> list[str]:
        problems: list[str] = []
        if mttr_rows:
            worst_p95 = max(mttr_rows, key=lambda row: row.get("p95_ttr_hours") or 0.0)
            problems.append(
                f"Worst MTTR tail: {worst_p95['group']} has P95 {worst_p95.get('p95_ttr_hours') or 0.0:.1f}h."
            )
        if category_rows:
            busiest = max(category_rows, key=lambda row: row.get("count") or 0)
            problems.append(f"Highest demand: {busiest['group']} drove {busiest.get('count') or 0:,} tickets in the last 30 days.")
        if backlog_rows:
            oldest = max(backlog_rows, key=lambda row: row.get("total") or 0)
            problems.append(f"Backlog pressure: {oldest['bucket']} holds {oldest.get('total') or 0:,} open tickets.")
        return problems[:3]

    def _write_trends_sheet(self, workbook, formats: dict[str, Any], trend_rows: Sequence[dict[str, Any]], *, title: str) -> None:
        worksheet = workbook.add_worksheet(title)
        worksheet.write(0, 0, title, formats["title"])
        worksheet.write(1, 0, "Daily operational trend data for the last 30 days.", formats["text"])
        headers = [
            "Date",
            "Tickets Created",
            "Tickets Resolved",
            "MTTR Avg (h)",
            "MTTR P95 (h)",
            "SLA Compliance %",
            "Backlog Count",
            "Escalation Count",
        ]
        header_row = 3
        worksheet.write_row(header_row, 0, headers, formats["header"])
        for idx, row in enumerate(trend_rows, start=header_row + 1):
            worksheet.write(idx, 0, row["date"], formats["date_text"])
            worksheet.write_number(idx, 1, row["tickets_created"], formats["integer"])
            worksheet.write_number(idx, 2, row["tickets_resolved"], formats["integer"])
            worksheet.write_number(idx, 3, row["mttr_avg_hours"], formats["hours"])
            worksheet.write_number(idx, 4, row["mttr_p95_hours"], formats["hours"])
            worksheet.write_number(idx, 5, row["sla_compliance_rate"], formats["percent"])
            worksheet.write_number(idx, 6, row["backlog_count"], formats["integer"])
            worksheet.write_number(idx, 7, row["escalation_count"], formats["integer"])
        worksheet.freeze_panes(header_row + 1, 0)
        worksheet.autofilter(header_row, 0, header_row + len(trend_rows), len(headers) - 1)
        worksheet.set_column(0, 0, 14)
        worksheet.set_column(1, 2, 16)
        worksheet.set_column(3, 4, 14)
        worksheet.set_column(5, 5, 16)
        worksheet.set_column(6, 7, 16)

        chart = workbook.add_chart({"type": "column"})
        chart = workbook.add_chart({"type": "line"})
        chart.add_series({
            "name": "Tickets Created",
            "categories": [worksheet.name, header_row + 1, 0, header_row + len(trend_rows), 0],
            "values": [worksheet.name, header_row + 1, 1, header_row + len(trend_rows), 1],
            "line": {"color": "#2563EB", "width": 2.0},
            "marker": {"type": "circle", "size": 4, "border": {"color": "#2563EB"}, "fill": {"color": "#2563EB"}},
        })
        chart.add_series({
            "name": "Tickets Resolved",
            "categories": [worksheet.name, header_row + 1, 0, header_row + len(trend_rows), 0],
            "values": [worksheet.name, header_row + 1, 2, header_row + len(trend_rows), 2],
            "line": {"color": "#10B981", "width": 2.0},
            "marker": {"type": "diamond", "size": 4, "border": {"color": "#10B981"}, "fill": {"color": "#10B981"}},
        })
        line = workbook.add_chart({"type": "line"})
        line.add_series({
            "name": "MTTR P95",
            "categories": [worksheet.name, header_row + 1, 0, header_row + len(trend_rows), 0],
            "values": [worksheet.name, header_row + 1, 4, header_row + len(trend_rows), 4],
            "y2_axis": True,
            "line": {"color": "#DC2626", "width": 2.25},
            "marker": {"type": "square", "size": 4, "border": {"color": "#DC2626"}, "fill": {"color": "#DC2626"}},
        })
        line.set_y2_axis({"name": "MTTR P95 (h)"})
        chart.combine(line)
        chart.set_y_axis({"name": "Tickets"})
        chart.set_x_axis({"name": "Date", "label_position": "low"})
        chart.set_legend({"position": "bottom"})
        chart.set_title({"name": "30-Day Trends"})
        worksheet.insert_chart("J4", chart, {"x_scale": 1.3, "y_scale": 1.1})

    def _write_data_gaps_sheet(self, workbook, formats: dict[str, Any], gaps: Sequence[TemplateGap], *, title: str) -> None:
        worksheet = workbook.add_worksheet(title)
        worksheet.write(0, 0, "Data Gaps", formats["title"])
        headers = ["Report", "Window", "Readiness", "Limitation", "Recommendation"]
        worksheet.write_row(2, 0, headers, formats["header"])
        if not gaps:
            worksheet.write(3, 0, "No known data gaps.", formats["text"])
            worksheet.set_column(0, 0, 24)
            return
        for idx, gap in enumerate(gaps, start=3):
            worksheet.write(idx, 0, gap.template_name, formats["text"])
            worksheet.write(idx, 1, gap.window_label, formats["text"])
            worksheet.write(idx, 2, gap.readiness, formats["text"])
            worksheet.write(idx, 3, gap.limitation, formats["wrap"])
            worksheet.write(idx, 4, gap.recommendation, formats["wrap"])
        worksheet.freeze_panes(3, 0)
        worksheet.autofilter(2, 0, 2 + len(gaps), len(headers) - 1)
        worksheet.set_column(0, 0, 28)
        worksheet.set_column(1, 2, 14)
        worksheet.set_column(3, 4, 60)

    def _template_window_metadata(
        self,
        *,
        report_name: str,
        report_description: str,
        category: str,
        readiness: str,
        view_type: str,
        notes: str,
        window_label: str,
        window_field_label: str,
        window_start: date,
        window_end: date,
    ) -> list[tuple[str, Any]]:
        return [
            ("Report", report_name),
            ("Window", window_label),
            ("Window Field", window_field_label),
            ("Window Start", window_start.isoformat()),
            ("Window End", window_end.isoformat()),
            ("Category", category or "Uncategorized"),
            ("Readiness", readiness),
            ("View", view_type),
            ("Description", report_description),
            ("Notes", notes),
            ("Generated", self.now.isoformat()),
        ]

    def _write_template_window_sheet(
        self,
        workbook,
        formats: dict[str, Any],
        *,
        template: ReportTemplate | None,
        config: ReportConfig,
        report_name: str,
        report_description: str,
        window_label: str,
        window_days: int,
        sheet_name: str | None = None,
    ) -> dict[str, Any]:
        view_type = _report_view_type(config)
        report_kind = _report_kind(report_name, config)
        window_field = _date_field_for_report_window_config(config, report_name=report_name)
        window_field_label = _REPORT_WINDOW_LABELS.get(window_field, "Created")
        current_start, current_end = _window_bounds(window_days, today=self.today)
        prior_start, prior_end = _prior_window_bounds(window_days, today=self.today)
        facts = self._facts_for_config(config)
        current_facts = self._facts_for_window(facts, window_field=window_field, window_start=current_start, window_end=current_end)
        prior_facts = self._facts_for_window(facts, window_field=window_field, window_start=prior_start, window_end=prior_end)
        readiness = _template_readiness(template, facts=current_facts) if template else "custom"
        metadata = self._template_window_metadata(
            report_name=report_name,
            report_description=report_description,
            category=(template.category if template else ""),
            readiness=readiness,
            view_type=view_type,
            notes=(template.notes if template else ""),
            window_label=window_label,
            window_field_label=window_field_label,
            window_start=current_start,
            window_end=current_end,
        )
        worksheet = workbook.add_worksheet(sheet_name or window_label)
        self._write_metadata_block(worksheet, formats, metadata)
        if report_kind == "backlog":
            backlog_rows, backlog_statuses = self._backlog_rows([fact for fact in current_facts if fact.is_open], [fact for fact in prior_facts if fact.is_open])
            table_info = self._write_backlog_table(worksheet, formats, backlog_rows, backlog_statuses)
            self._insert_backlog_chart(worksheet, table_info, workbook)
            row_count = len(backlog_rows)
        elif config.group_by:
            grouped_rows = self._group_summary_rows(
                facts=current_facts,
                prior_facts=prior_facts,
                group_by=config.group_by,
                report_kind=report_kind,
            )
            table_info = self._write_grouped_table(
                worksheet,
                formats,
                grouped_rows,
                group_by=config.group_by,
                report_kind=report_kind,
            )
            self._insert_group_chart(worksheet, table_info, workbook, report_name=report_name, report_kind=report_kind)
            row_count = len(grouped_rows)
        else:
            columns = config.columns or _DEFAULT_COLUMNS
            self._write_detail_table(worksheet, formats, columns, current_facts)
            row_count = len(current_facts)
        return {
            "window_field_label": window_field_label,
            "window_start": current_start,
            "window_end": current_end,
            "readiness": readiness,
            "view_type": view_type,
            "row_count": row_count,
        }

    def _write_metadata_block(self, worksheet, formats: dict[str, Any], metadata: Sequence[tuple[str, Any]]) -> None:
        for row_idx, (label, value) in enumerate(metadata):
            worksheet.write(row_idx, 0, label, formats["meta_label"])
            worksheet.write(row_idx, 1, _cell_value(value), formats["meta_value"])
            worksheet.set_row(row_idx, None, None, {"level": 1, "hidden": True})
        worksheet.set_row(10, None, None, {"level": 1, "hidden": True, "collapsed": True})
        worksheet.set_column(0, 0, 18)
        worksheet.set_column(1, 1, 56)
        worksheet.outline_settings(True, False, True, False)

    def _write_detail_table(
        self,
        worksheet,
        formats: dict[str, Any],
        columns: Sequence[str],
        facts: Sequence[ReportIssueFact],
    ) -> None:
        header_row = 12
        worksheet.write_row(header_row, 0, [_FIELD_LABELS.get(column, column) for column in columns], formats["header"])
        for row_offset, fact in enumerate(facts, start=1):
            row_idx = header_row + row_offset
            for col_idx, column in enumerate(columns):
                value = _cell_value(fact.row.get(column))
                cell_format = formats["text"]
                if column in {"calendar_ttr_hours", "age_days", "days_since_update"} and value not in ("", None):
                    cell_format = formats["hours"]
                worksheet.write(row_idx, col_idx, value, cell_format)
        worksheet.freeze_panes(header_row + 1, 0)
        worksheet.autofilter(header_row, 0, header_row + max(1, len(facts)), max(0, len(columns) - 1))
        for idx, column in enumerate(columns):
            worksheet.set_column(idx, idx, _DETAIL_WIDTH_DEFAULTS.get(column, 15))
            if column in {"sla_first_response_status", "sla_resolution_status"}:
                worksheet.conditional_format(header_row + 1, idx, header_row + max(1, len(facts)), idx, {
                    "type": "text",
                    "criteria": "containing",
                    "value": "BREACHED",
                    "format": formats["breached_text"],
                })

    def _group_summary_rows(
        self,
        *,
        facts: Sequence[ReportIssueFact],
        prior_facts: Sequence[ReportIssueFact],
        group_by: str,
        report_kind: str,
    ) -> list[dict[str, Any]]:
        current_groups: dict[str, list[ReportIssueFact]] = defaultdict(list)
        prior_groups: dict[str, list[ReportIssueFact]] = defaultdict(list)
        for fact in facts:
            current_groups[_group_key(fact.row.get(group_by))].append(fact)
        for fact in prior_facts:
            prior_groups[_group_key(fact.row.get(group_by))].append(fact)

        all_groups = sorted(set(current_groups) | set(prior_groups))
        rows: list[dict[str, Any]] = []
        for group in all_groups:
            current = current_groups.get(group, [])
            previous = prior_groups.get(group, [])
            metrics = _metric_values_for_kind(report_kind, current)
            open_count = sum(1 for fact in current if fact.is_open)
            row = {
                "group": group,
                "count": len(current),
                "open": open_count,
                "avg_ttr_hours": _mean_hours(metrics),
                "median_ttr_hours": _percentile_hours(metrics, 50),
                "p95_ttr_hours": _percentile_hours(metrics, 95),
                "p99_ttr_hours": _percentile_hours(metrics, 99),
                "delta_vs_prior_period": len(current) - len(previous),
                "escalated_count": sum(1 for fact in current if fact.is_escalated),
            }
            if report_kind == "fcr":
                resolved = [fact for fact in current if fact.resolved_dt]
                fcr_hits = [
                    fact for fact in resolved
                    if (fact.first_resolved_dt and fact.created_dt and (fact.first_resolved_dt - fact.created_dt).total_seconds() <= 1800)
                    or fact.comment_count <= 1
                ]
                row["fcr_rate"] = (len(fcr_hits) / len(resolved)) if resolved else 0.0
            if report_kind == "escalation":
                row["escalation_rate"] = (row["escalated_count"] / row["count"]) if row["count"] else 0.0
            if report_kind == "reopen":
                reopen_hits = [fact for fact in current if fact.reopen_count > 0]
                row["reopen_rate"] = (len(reopen_hits) / row["count"]) if row["count"] else 0.0
            rows.append(row)
        rows.sort(key=lambda item: ((item.get("count") or 0) * -1, str(item.get("group") or "").lower()))
        return rows

    def _backlog_rows(
        self,
        current_facts: Sequence[ReportIssueFact],
        prior_facts: Sequence[ReportIssueFact],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        statuses = sorted({str(fact.row.get("status") or "Unknown") for fact in current_facts} | {str(fact.row.get("status") or "Unknown") for fact in prior_facts})
        current_by_bucket: dict[str, list[ReportIssueFact]] = defaultdict(list)
        prior_by_bucket: dict[str, list[ReportIssueFact]] = defaultdict(list)
        for fact in current_facts:
            current_by_bucket[_aging_bucket_label((fact.open_age_hours or 0.0) / 24.0 if fact.open_age_hours is not None else None)].append(fact)
        for fact in prior_facts:
            prior_by_bucket[_aging_bucket_label((fact.open_age_hours or 0.0) / 24.0 if fact.open_age_hours is not None else None)].append(fact)
        total_backlog = len(current_facts)
        rows: list[dict[str, Any]] = []
        for _, label in _AGING_BUCKETS:
            current = current_by_bucket.get(label, [])
            previous = prior_by_bucket.get(label, [])
            age_values = [fact.open_age_hours for fact in current if fact.open_age_hours is not None]
            rows.append(
                {
                    "bucket": label,
                    "percent_of_backlog": (len(current) / total_backlog) if total_backlog else 0.0,
                    "status_counts": {status: sum(1 for fact in current if str(fact.row.get("status") or "Unknown") == status) for status in statuses},
                    "total": len(current),
                    "avg_age_hours": _mean_hours(age_values),
                    "median_age_hours": _percentile_hours(age_values, 50),
                    "p95_age_hours": _percentile_hours(age_values, 95),
                    "p99_age_hours": _percentile_hours(age_values, 99),
                    "delta_vs_prior_period": len(current) - len(previous),
                }
            )
        return rows, statuses

    def _write_grouped_table(
        self,
        worksheet,
        formats: dict[str, Any],
        rows: Sequence[dict[str, Any]],
        *,
        group_by: str,
        report_kind: str,
    ) -> ChartTableInfo:
        header_row = 12
        headers = [
            _FIELD_LABELS.get(group_by, group_by),
            "Count",
            "Open",
            "Avg TTR (h)",
            "Median TTR (h)",
            "P95 TTR (h)",
            "P99 TTR (h)",
            "Δ Count vs Prior",
        ]
        column_map = {
            "group": 0,
            "count": 1,
            "open": 2,
            "avg_ttr_hours": 3,
            "median_ttr_hours": 4,
            "p95_ttr_hours": 5,
            "p99_ttr_hours": 6,
            "delta_vs_prior_period": 7,
        }
        if report_kind == "fcr":
            headers.append("FCR %")
            column_map["fcr_rate"] = len(headers) - 1
        if report_kind == "escalation":
            headers.append("Escalation Rate %")
            column_map["escalation_rate"] = len(headers) - 1
        if report_kind == "reopen":
            headers.append("Reopen Rate %")
            column_map["reopen_rate"] = len(headers) - 1
        worksheet.write_row(header_row, 0, headers, formats["header"])
        for row_offset, row in enumerate(rows, start=1):
            row_idx = header_row + row_offset
            worksheet.write(row_idx, 0, row["group"], formats["text"])
            worksheet.write_number(row_idx, 1, row["count"], formats["integer"])
            worksheet.write_number(row_idx, 2, row["open"], formats["integer"])
            worksheet.write_number(row_idx, 3, row["avg_ttr_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, 4, row["median_ttr_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, 5, row["p95_ttr_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, 6, row["p99_ttr_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, 7, row["delta_vs_prior_period"], formats["integer"])
            if "fcr_rate" in row:
                worksheet.write_number(row_idx, column_map["fcr_rate"], row["fcr_rate"], formats["percent"])
            if "escalation_rate" in row:
                worksheet.write_number(row_idx, column_map["escalation_rate"], row["escalation_rate"], formats["percent"])
            if "reopen_rate" in row:
                worksheet.write_number(row_idx, column_map["reopen_rate"], row["reopen_rate"], formats["percent"])
        worksheet.freeze_panes(header_row + 1, 0)
        worksheet.autofilter(header_row, 0, header_row + max(1, len(rows)), len(headers) - 1)
        worksheet.set_column(0, 0, 28)
        worksheet.set_column(1, 2, 12)
        worksheet.set_column(3, 6, 16)
        worksheet.set_column(7, len(headers) - 1, 16)
        worksheet.conditional_format(header_row + 1, 3, header_row + max(1, len(rows)), 3, {
            "type": "cell",
            "criteria": ">",
            "value": 200,
            "format": formats["high_avg"],
        })
        worksheet.conditional_format(header_row + 1, 5, header_row + max(1, len(rows)), 5, {
            "type": "formula",
            "criteria": f"=${xl_col_to_name(5)}{header_row + 2}>(${xl_col_to_name(3)}{header_row + 2}*3)",
            "format": formats["high_variance"],
        })
        if report_kind in {"sla", "follow_up"}:
            worksheet.conditional_format(header_row + 1, 0, header_row + max(1, len(rows)), len(headers) - 1, {
                "type": "formula",
                "criteria": f'=$A{header_row + 2}="BREACHED"',
                "format": formats["row_red"],
            })
            worksheet.conditional_format(header_row + 1, 0, header_row + max(1, len(rows)), len(headers) - 1, {
                "type": "formula",
                "criteria": f'=$A{header_row + 2}="Running"',
                "format": formats["row_yellow"],
            })
        else:
            worksheet.conditional_format(header_row + 1, 0, header_row + max(1, len(rows)), 0, {
                "type": "text",
                "criteria": "containing",
                "value": "BREACHED",
                "format": formats["breached_text"],
            })
        return ChartTableInfo(
            header_row=header_row,
            first_data_row=header_row + 1,
            last_data_row=header_row + max(1, len(rows)),
            column_map=column_map,
        )

    def _write_backlog_table(
        self,
        worksheet,
        formats: dict[str, Any],
        rows: Sequence[dict[str, Any]],
        statuses: Sequence[str],
    ) -> ChartTableInfo:
        header_row = 12
        headers = [
            "Aging Bucket",
            "% of Backlog",
            *statuses,
            "Total",
            "Avg Age (h)",
            "Median Age (h)",
            "P95 Age (h)",
            "P99 Age (h)",
            "Δ vs Prior Period",
        ]
        worksheet.write_row(header_row, 0, headers, formats["header"])
        for row_offset, row in enumerate(rows, start=1):
            row_idx = header_row + row_offset
            worksheet.write(row_idx, 0, row["bucket"], formats["text"])
            worksheet.write_number(row_idx, 1, row["percent_of_backlog"], formats["percent"])
            for status_idx, status in enumerate(statuses, start=2):
                worksheet.write_number(row_idx, status_idx, row["status_counts"].get(status, 0), formats["integer"])
            start_stats_col = 2 + len(statuses)
            worksheet.write_number(row_idx, start_stats_col, row["total"], formats["integer"])
            worksheet.write_number(row_idx, start_stats_col + 1, row["avg_age_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, start_stats_col + 2, row["median_age_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, start_stats_col + 3, row["p95_age_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, start_stats_col + 4, row["p99_age_hours"] or 0.0, formats["hours"])
            worksheet.write_number(row_idx, start_stats_col + 5, row["delta_vs_prior_period"], formats["integer"])
        worksheet.freeze_panes(header_row + 1, 0)
        worksheet.autofilter(header_row, 0, header_row + max(1, len(rows)), len(headers) - 1)
        worksheet.set_column(0, 0, 18)
        worksheet.set_column(1, 1, 14)
        worksheet.set_column(2, 1 + len(statuses), 12)
        worksheet.set_column(2 + len(statuses), len(headers) - 1, 16)
        return ChartTableInfo(
            header_row=header_row,
            first_data_row=header_row + 1,
            last_data_row=header_row + max(1, len(rows)),
            column_map={status: 2 + idx for idx, status in enumerate(statuses)},
        )

    def _insert_group_chart(self, worksheet, table_info: ChartTableInfo, workbook, *, report_name: str, report_kind: str) -> None:
        if table_info.last_data_row <= table_info.first_data_row:
            return
        lower_name = report_name.strip().lower()
        if report_kind == "sla" or "sla compliance" in lower_name:
            chart = workbook.add_chart({"type": "doughnut"})
            chart.add_series({
                "name": report_name,
                "categories": [worksheet.name, table_info.first_data_row, 0, table_info.last_data_row, 0],
                "values": [worksheet.name, table_info.first_data_row, table_info.column_map["count"], table_info.last_data_row, table_info.column_map["count"]],
            })
            chart.set_title({"name": "SLA Compliance"})
        elif report_kind == "first_response" or "first response" in lower_name:
            chart = workbook.add_chart({"type": "doughnut"})
            chart.add_series({
                "name": report_name,
                "categories": [worksheet.name, table_info.first_data_row, 0, table_info.last_data_row, 0],
                "values": [worksheet.name, table_info.first_data_row, table_info.column_map["count"], table_info.last_data_row, table_info.column_map["count"]],
            })
            chart.set_title({"name": "First Response SLA"})
        elif report_kind == "follow_up" or "daily follow-up" in lower_name or "daily follow up" in lower_name:
            chart = workbook.add_chart({"type": "doughnut"})
            chart.add_series({
                "name": report_name,
                "categories": [worksheet.name, table_info.first_data_row, 0, table_info.last_data_row, 0],
                "values": [worksheet.name, table_info.first_data_row, table_info.column_map["count"], table_info.last_data_row, table_info.column_map["count"]],
            })
            chart.set_title({"name": "2-Hour Response + Daily Follow-Up"})
        elif report_kind == "ticket_volume" or "ticket volume" in lower_name:
            chart = workbook.add_chart({"type": "bar"})
            chart.add_series({
                "name": "Count",
                "categories": [worksheet.name, table_info.first_data_row, 0, table_info.last_data_row, 0],
                "values": [worksheet.name, table_info.first_data_row, table_info.column_map["count"], table_info.last_data_row, table_info.column_map["count"]],
            })
            chart.set_title({"name": "Ticket Volume by Category"})
        elif report_kind == "escalation" or "escalation" in lower_name:
            chart = workbook.add_chart({"type": "column"})
            values_col = table_info.column_map.get("escalation_rate", table_info.column_map["count"])
            chart.add_series({
                "name": "Escalation",
                "categories": [worksheet.name, table_info.first_data_row, 0, table_info.last_data_row, 0],
                "values": [worksheet.name, table_info.first_data_row, values_col, table_info.last_data_row, values_col],
            })
            chart.set_title({"name": "Escalation by Assignee"})
        else:
            chart = workbook.add_chart({"type": "bar"})
            chart.add_series({
                "name": "Avg TTR",
                "categories": [worksheet.name, table_info.first_data_row, 0, table_info.last_data_row, 0],
                "values": [worksheet.name, table_info.first_data_row, table_info.column_map["avg_ttr_hours"], table_info.last_data_row, table_info.column_map["avg_ttr_hours"]],
            })
            chart.add_series({
                "name": "P95 TTR",
                "categories": [worksheet.name, table_info.first_data_row, 0, table_info.last_data_row, 0],
                "values": [worksheet.name, table_info.first_data_row, table_info.column_map["p95_ttr_hours"], table_info.last_data_row, table_info.column_map["p95_ttr_hours"]],
            })
            chart.set_title({"name": "Avg vs P95"})
        worksheet.insert_chart("J14", chart, {"x_scale": 1.1, "y_scale": 1.0})

    def _insert_backlog_chart(self, worksheet, table_info: ChartTableInfo, workbook) -> None:
        if table_info.last_data_row <= table_info.first_data_row or not table_info.column_map:
            return
        chart = workbook.add_chart({"type": "column", "subtype": "stacked"})
        for status, col_idx in table_info.column_map.items():
            chart.add_series({
                "name": status,
                "categories": [worksheet.name, table_info.first_data_row, 0, table_info.last_data_row, 0],
                "values": [worksheet.name, table_info.first_data_row, col_idx, table_info.last_data_row, col_idx],
            })
        chart.set_title({"name": "Backlog Aging"})
        worksheet.insert_chart("J14", chart, {"x_scale": 1.2, "y_scale": 1.0})

    def _sla_status_counts(self, facts: Sequence[ReportIssueFact]) -> Counter[str]:
        counts: Counter[str] = Counter()
        for fact in facts:
            counts[(fact.sla_resolution_status or "(none)").strip() or "(none)"] += 1
        if not counts:
            counts["(none)"] = 0
        return counts

    def _first_response_status_counts(self, facts: Sequence[ReportIssueFact]) -> Counter[str]:
        counts: Counter[str] = Counter()
        for fact in facts:
            counts[(fact.sla_response_status or "(none)").strip() or "(none)"] += 1
        if not counts:
            counts["(none)"] = 0
        return counts

    def _sla_rate(self, counts: Counter[str]) -> float:
        total = sum(counts.values())
        if not total:
            return 0.0
        return (counts.get("Met", 0) / total)

    def _met_rate(self, counts: Counter[str]) -> float:
        total = sum(counts.values())
        if not total:
            return 0.0
        return (counts.get("Met", 0) / total)

    def _build_formats(self, workbook) -> dict[str, Any]:
        return {
            "title": workbook.add_format({"bold": True, "font_size": 18, "font_color": "#0F172A"}),
            "subtitle": workbook.add_format({"bold": True, "font_size": 11, "font_color": "#334155"}),
            "text": workbook.add_format({"font_size": 10, "valign": "top"}),
            "wrap": workbook.add_format({"font_size": 10, "valign": "top", "text_wrap": True}),
            "muted": workbook.add_format({"font_size": 9, "font_color": "#64748B"}),
            "meta_label": workbook.add_format({"bold": True, "font_color": "#0F172A"}),
            "meta_value": workbook.add_format({"font_color": "#334155"}),
            "header": workbook.add_format(
                {
                    "bold": True,
                    "font_color": "#FFFFFF",
                    "bg_color": "#1F4E79",
                    "align": "center",
                    "valign": "vcenter",
                    "border": 1,
                }
            ),
            "hours": workbook.add_format({"num_format": "0.0", "valign": "top"}),
            "percent": workbook.add_format({"num_format": "0.0%", "valign": "top"}),
            "integer": workbook.add_format({"num_format": "#,##0", "valign": "top"}),
            "delta_percent": workbook.add_format({"num_format": "0.0%;-0.0%", "valign": "top"}),
            "date_text": workbook.add_format({"num_format": "@", "valign": "top"}),
            "breached_text": workbook.add_format({"font_color": "#B91C1C"}),
            "high_avg": workbook.add_format({"bg_color": "#FECACA"}),
            "high_variance": workbook.add_format({"bg_color": "#FEF08A"}),
            "link": workbook.add_format({"font_color": "#2563EB", "underline": 1}),
            "kpi_good": workbook.add_format({"bg_color": "#DCFCE7"}),
            "kpi_warn": workbook.add_format({"bg_color": "#FEF3C7"}),
            "kpi_bad": workbook.add_format({"bg_color": "#FEE2E2"}),
            "hidden": workbook.add_format({"font_color": "#FFFFFF"}),
            "hidden_note": workbook.add_format({"font_color": "#FFFFFF", "italic": True}),
            "total_text": workbook.add_format({"bold": True, "top": 1, "valign": "top"}),
            "total_integer": workbook.add_format({"bold": True, "top": 1, "valign": "top", "num_format": "#,##0"}),
            "total_hours": workbook.add_format({"bold": True, "top": 1, "valign": "top", "num_format": "0.0"}),
            "total_percent": workbook.add_format({"bold": True, "top": 1, "valign": "top", "num_format": "0.0%"}),
            "total_blank": workbook.add_format({"bold": True, "top": 1, "valign": "top"}),
            "metric_label": workbook.add_format({"bold": True, "valign": "top"}),
            "metric_percent": workbook.add_format({"bold": True, "valign": "top", "num_format": "0.0%", "bg_color": "#FEF08A"}),
            "readiness_ready": workbook.add_format({"bold": True, "bg_color": "#DCFCE7", "font_color": "#0F172A"}),
            "readiness_proxy": workbook.add_format({"bold": True, "bg_color": "#FEF3C7", "font_color": "#0F172A"}),
            "readiness_issue": workbook.add_format({"bold": True, "bg_color": "#FEE2E2", "font_color": "#7F1D1D"}),
            "status_ready": workbook.add_format({"bold": True, "align": "center", "bg_color": "#DCFCE7"}),
            "status_proxy": workbook.add_format({"bold": True, "align": "center", "bg_color": "#FEF3C7"}),
            "status_issue": workbook.add_format({"bold": True, "align": "center", "bg_color": "#FEE2E2"}),
            "trend_arrow": workbook.add_format({"bold": True, "font_size": 14, "align": "center", "valign": "vcenter"}),
            "arrow_good": workbook.add_format({"bold": True, "font_size": 14, "font_color": "#16A34A", "align": "center"}),
            "arrow_bad": workbook.add_format({"bold": True, "font_size": 14, "font_color": "#DC2626", "align": "center"}),
            "finding_text": workbook.add_format({"font_size": 10, "valign": "top", "text_wrap": True}),
            "weekend": workbook.add_format({"bg_color": "#F1F5F9"}),
            "row_green": workbook.add_format({"bg_color": "#DCFCE7"}),
            "row_pale_yellow": workbook.add_format({"bg_color": "#FEF9C3"}),
            "row_orange": workbook.add_format({"bg_color": "#FED7AA"}),
            "row_light_red": workbook.add_format({"bg_color": "#FECACA"}),
            "row_red": workbook.add_format({"bg_color": "#FCA5A5"}),
            "row_dark_red": workbook.add_format({"bg_color": "#F87171", "font_color": "#FFFFFF"}),
            "row_yellow": workbook.add_format({"bg_color": "#FEF3C7"}),
        }
