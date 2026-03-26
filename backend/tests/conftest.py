"""Shared fixtures for backend tests."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Make backend importable without installing
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set DATA_DIR to a temp directory BEFORE any backend import touches it
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="altlassian_test_"))
# Set dummy Jira config so config.py doesn't fail
os.environ.setdefault("JIRA_EMAIL", "test@example.com")
os.environ.setdefault("JIRA_API_TOKEN", "test-token")
os.environ.setdefault("JIRA_BASE_URL", "https://example.atlassian.net")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")
os.environ.setdefault("TOOLS_ALLOWED_IDENTIFIERS", "test,gallison,wberry")

# Frozen time constant (also used in test_metrics.py)
FROZEN_NOW = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Sample Jira-shaped issue dicts
# ---------------------------------------------------------------------------

def _make_issue(
    key: str,
    summary: str,
    status_name: str,
    status_category: str,
    priority: str,
    assignee: str | None,
    created: str,
    updated: str,
    resolution_date: str | None = None,
    labels: list[str] | None = None,
    sla_first_resp: dict | None = None,
    sla_resolution: dict | None = None,
) -> dict[str, Any]:
    """Build a minimal Jira issue dict with realistic field structure."""
    assignee_obj = (
        {"displayName": assignee, "accountId": f"acc-{assignee.lower().replace(' ', '-')}"}
        if assignee
        else None
    )
    resolution_obj = {"name": "Done"} if resolution_date else None
    status_cat_obj = {"name": status_category}

    fields: dict[str, Any] = {
        "summary": summary,
        "status": {"name": status_name, "statusCategory": status_cat_obj},
        "priority": {"name": priority},
        "assignee": assignee_obj,
        "reporter": {"displayName": "Reporter One"},
        "issuetype": {"name": "[System] Service request"},
        "resolution": resolution_obj,
        "created": created,
        "updated": updated,
        "resolutiondate": resolution_date,
        "labels": labels or [],
        "customfield_10010": None,
        "customfield_11266": sla_first_resp,
        "customfield_11264": sla_resolution,
        "customfield_11267": None,
        "customfield_11268": None,
    }
    return {"key": key, "fields": fields}


@pytest.fixture()
def sample_issues() -> list[dict[str, Any]]:
    """Six issues covering major categories for testing."""
    return [
        # 0: Open / Active — recently updated (not stale)
        _make_issue(
            key="OIT-100",
            summary="Active open ticket",
            status_name="In Progress",
            status_category="In Progress",
            priority="High",
            assignee="Alice Admin",
            created="2026-02-01T10:00:00+00:00",
            updated="2026-03-03T10:00:00+00:00",
            sla_first_resp={"completedCycles": [{"breached": False}]},
            sla_resolution={"ongoingCycle": {"breached": False, "paused": False}},
        ),
        # 1: Open / Stale — updated > 7 days ago
        _make_issue(
            key="OIT-200",
            summary="Stale open ticket",
            status_name="Open",
            status_category="To Do",
            priority="Medium",
            assignee="Bob Builder",
            created="2026-01-10T08:00:00+00:00",
            updated="2026-02-15T08:00:00+00:00",
            sla_first_resp={"ongoingCycle": {"breached": True, "paused": False}},
        ),
        # 2: Resolved / High priority — 72h TTR
        _make_issue(
            key="OIT-300",
            summary="Resolved high priority",
            status_name="Resolved",
            status_category="Done",
            priority="High",
            assignee="Alice Admin",
            created="2026-02-20T12:00:00+00:00",
            updated="2026-02-23T12:00:00+00:00",
            resolution_date="2026-02-23T12:00:00+00:00",
            sla_first_resp={"completedCycles": [{"breached": False}]},
            sla_resolution={"completedCycles": [{"breached": False}]},
        ),
        # 3: Closed / Low priority — 240h TTR
        _make_issue(
            key="OIT-400",
            summary="Closed low priority",
            status_name="Closed",
            status_category="Done",
            priority="Low",
            assignee=None,
            created="2026-01-20T09:00:00+00:00",
            updated="2026-01-30T09:00:00+00:00",
            resolution_date="2026-01-30T09:00:00+00:00",
        ),
        # 4: Excluded by label
        _make_issue(
            key="OIT-500",
            summary="Normal ticket with dev label",
            status_name="Open",
            status_category="To Do",
            priority="Medium",
            assignee="Charlie Chief",
            created="2026-02-10T10:00:00+00:00",
            updated="2026-03-01T10:00:00+00:00",
            labels=["oasisdev"],
        ),
        # 5: Excluded by summary
        _make_issue(
            key="OIT-600",
            summary="oasisdev test ticket",
            status_name="Open",
            status_category="To Do",
            priority="Low",
            assignee="Charlie Chief",
            created="2026-02-12T10:00:00+00:00",
            updated="2026-03-01T10:00:00+00:00",
        ),
    ]


@pytest.fixture()
def filtered_issues(sample_issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First 4 issues (non-excluded) — matches what IssueCache.get_filtered_issues returns."""
    return sample_issues[:4]


# ---------------------------------------------------------------------------
# Mock cache
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_cache(sample_issues, filtered_issues):
    """A mock object that satisfies the IssueCache interface used by routes."""
    m = MagicMock()
    m.get_filtered_issues.return_value = filtered_issues
    m.get_all_issues.return_value = sample_issues
    m.issue_count = len(sample_issues)
    m.filtered_count = len(filtered_issues)
    m.initialized = True
    m.refreshing = False
    m.last_refresh = "2026-03-04T08:00:00+00:00"
    m.status.return_value = {
        "initialized": True,
        "refreshing": False,
        "issue_count": len(sample_issues),
        "filtered_count": len(filtered_issues),
        "last_refresh": "2026-03-04T08:00:00+00:00",
    }
    return m


# ---------------------------------------------------------------------------
# Time freeze
# ---------------------------------------------------------------------------

@pytest.fixture()
def freeze_time(monkeypatch):
    """Freeze metrics._now() to 2026-03-04T12:00:00Z for deterministic tests."""
    import metrics
    monkeypatch.setattr(metrics, "_now", lambda: FROZEN_NOW)
    return FROZEN_NOW


# ---------------------------------------------------------------------------
# FastAPI test client with cache patched
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_client(mock_cache, freeze_time, monkeypatch):
    """FastAPI TestClient with the cache singleton replaced in every route module."""
    import issue_cache
    import routes_metrics
    import routes_tickets
    import routes_chart
    import routes_export
    import routes_cache
    import routes_triage
    import routes_azure
    import routes_tools
    import routes_user_admin
    import routes_user_exit
    import azure_cache as azure_cache_module
    import onedrive_copy_jobs as onedrive_copy_jobs_module
    import user_admin_jobs as user_admin_jobs_module
    import user_admin_providers as user_admin_providers_module
    import user_exit_workflows as user_exit_workflows_module
    import report_ai_summary_service as report_ai_summary_service_module

    for mod in [issue_cache, routes_metrics, routes_tickets, routes_chart, routes_export, routes_cache, routes_triage]:
        monkeypatch.setattr(mod, "cache", mock_cache)

    mock_azure_cache = MagicMock()
    mock_azure_cache.start_background_refresh = AsyncMock()
    mock_azure_cache.stop_background_refresh = AsyncMock()
    mock_azure_cache.status.return_value = {
        "configured": False,
        "initialized": True,
        "refreshing": False,
        "last_refresh": None,
        "datasets": [],
    }
    mock_azure_cache.get_overview.return_value = {
        "subscriptions": 0,
        "management_groups": 0,
        "resources": 0,
        "role_assignments": 0,
        "users": 0,
        "groups": 0,
        "enterprise_apps": 0,
        "app_registrations": 0,
        "directory_roles": 0,
        "cost": {
            "lookback_days": 30,
            "total_cost": 0.0,
            "currency": "USD",
            "top_service": "",
            "top_subscription": "",
            "top_resource_group": "",
            "recommendation_count": 0,
            "potential_monthly_savings": 0.0,
        },
        "datasets": [],
        "last_refresh": None,
    }
    mock_azure_cache.get_cost_summary.return_value = mock_azure_cache.get_overview.return_value["cost"]
    mock_azure_cache.get_cost_trend.return_value = []
    mock_azure_cache.get_cost_breakdown.return_value = []
    mock_azure_cache.get_advisor.return_value = []
    mock_azure_cache.get_savings_summary.return_value = {
        "currency": "USD",
        "total_opportunities": 0,
        "quantified_opportunities": 0,
        "quantified_monthly_savings": 0.0,
        "quick_win_count": 0,
        "quick_win_monthly_savings": 0.0,
        "unquantified_opportunity_count": 0,
        "by_category": [],
        "by_opportunity_type": [],
        "by_effort": [],
        "by_risk": [],
        "by_confidence": [],
        "top_subscriptions": [],
        "top_resource_groups": [],
    }
    mock_azure_cache.list_savings_opportunities.return_value = []
    mock_azure_cache.list_resources.return_value = {
        "resources": [],
        "matched_count": 0,
        "total_count": 0,
    }
    mock_azure_cache.list_virtual_machines.return_value = {
        "vms": [],
        "matched_count": 0,
        "total_count": 0,
        "summary": {
            "total_vms": 0,
            "running_vms": 0,
            "deallocated_vms": 0,
            "distinct_sizes": 0,
        },
        "by_size": [],
        "by_state": [],
        "reservation_data_available": False,
        "reservation_error": None,
    }
    mock_azure_cache.list_directory_objects.return_value = []
    mock_azure_cache.get_grounding_context.return_value = {}

    monkeypatch.setattr(azure_cache_module, "azure_cache", mock_azure_cache)
    monkeypatch.setattr(routes_azure, "azure_cache", mock_azure_cache)

    mock_user_admin_jobs = MagicMock()
    mock_user_admin_jobs.start_worker = AsyncMock()
    mock_user_admin_jobs.stop_worker = AsyncMock()
    mock_user_admin_jobs.list_audit.return_value = []
    mock_user_admin_jobs.get_job.return_value = None
    mock_user_admin_jobs.get_job_results.return_value = []
    mock_user_admin_jobs.job_belongs_to.return_value = True
    monkeypatch.setattr(user_admin_jobs_module, "user_admin_jobs", mock_user_admin_jobs)
    monkeypatch.setattr(routes_user_admin, "user_admin_jobs", mock_user_admin_jobs)

    mock_onedrive_copy_jobs = MagicMock()
    mock_onedrive_copy_jobs.start_worker = AsyncMock()
    mock_onedrive_copy_jobs.stop_worker = AsyncMock()
    mock_onedrive_copy_jobs.list_jobs.return_value = []
    mock_onedrive_copy_jobs.get_job.return_value = None
    monkeypatch.setattr(onedrive_copy_jobs_module, "onedrive_copy_jobs", mock_onedrive_copy_jobs)
    monkeypatch.setattr(routes_tools, "onedrive_copy_jobs", mock_onedrive_copy_jobs)

    mock_report_ai_summary_service = MagicMock()
    mock_report_ai_summary_service.start_worker = AsyncMock()
    mock_report_ai_summary_service.stop_worker = AsyncMock()
    mock_report_ai_summary_service.list_current_summaries.return_value = []
    mock_report_ai_summary_service.get_current_master_summaries.return_value = {}
    mock_report_ai_summary_service.start_manual_batch = AsyncMock(
        return_value={
            "batch_id": "batch-1",
            "site_scope": "primary",
            "status": "queued",
            "item_count": 0,
            "requested_at": "2026-03-26T00:00:00+00:00",
        }
    )
    mock_report_ai_summary_service.get_batch_status.return_value = {
        "batch_id": "batch-1",
        "site_scope": "primary",
        "status": "completed",
        "item_count": 0,
        "requested_at": "2026-03-26T00:00:00+00:00",
        "started_at": "2026-03-26T00:00:00+00:00",
        "completed_at": "2026-03-26T00:00:00+00:00",
        "items": [],
    }
    monkeypatch.setattr(report_ai_summary_service_module, "report_ai_summary_service", mock_report_ai_summary_service)
    monkeypatch.setattr(routes_export, "report_ai_summary_service", mock_report_ai_summary_service)

    mock_user_admin_providers = MagicMock()
    mock_user_admin_providers.get_capabilities.return_value = {
        "can_manage_users": True,
        "enabled_providers": {"entra": True, "mailbox": False, "device_management": True},
        "supported_actions": [],
        "license_catalog": [],
        "group_catalog": [],
        "role_catalog": [],
        "conditional_access_exception_groups": [],
    }
    mock_user_admin_providers.get_user_detail.return_value = {
        "id": "user-1",
        "display_name": "Test User",
        "principal_name": "test@example.com",
        "mail": "test@example.com",
        "enabled": True,
        "user_type": "Member",
        "department": "",
        "job_title": "",
        "office_location": "",
        "company_name": "",
        "city": "",
        "country": "",
        "mobile_phone": "",
        "business_phones": [],
        "created_datetime": "",
        "last_password_change": "",
        "on_prem_sync": False,
        "on_prem_domain": "",
        "on_prem_netbios": "",
        "on_prem_sam_account_name": "",
        "on_prem_distinguished_name": "",
        "usage_location": "",
        "employee_id": "",
        "employee_type": "",
        "preferred_language": "",
        "proxy_addresses": [],
        "is_licensed": False,
        "license_count": 0,
        "sku_part_numbers": [],
        "last_interactive_utc": "",
        "last_interactive_local": "",
        "last_noninteractive_utc": "",
        "last_noninteractive_local": "",
        "last_successful_utc": "",
        "last_successful_local": "",
        "manager": None,
        "source_directory": "Cloud",
    }
    mock_user_admin_providers.list_groups.return_value = []
    mock_user_admin_providers.list_licenses.return_value = []
    mock_user_admin_providers.list_roles.return_value = []
    mock_user_admin_providers.get_mailbox.return_value = {
        "primary_address": "test@example.com",
        "aliases": [],
        "forwarding_enabled": False,
        "forwarding_address": "",
        "mailbox_type": "",
        "delegate_delivery_mode": "",
        "delegates": [],
        "automatic_replies_status": "",
        "provider_enabled": True,
        "management_supported": False,
        "note": "",
    }
    mock_user_admin_providers.list_devices.return_value = []
    monkeypatch.setattr(user_admin_providers_module, "user_admin_providers", mock_user_admin_providers)
    monkeypatch.setattr(routes_user_admin, "user_admin_providers", mock_user_admin_providers)

    mock_user_exit_workflows = MagicMock()
    mock_user_exit_workflows.start_worker = AsyncMock()
    mock_user_exit_workflows.stop_worker = AsyncMock()
    mock_user_exit_workflows.build_preflight.return_value = {
        "user_id": "user-1",
        "user_display_name": "Test User",
        "user_principal_name": "test@example.com",
        "profile_key": "",
        "profile_label": "",
        "scope_summary": "Cloud-only exit workflow",
        "on_prem_required": False,
        "requires_on_prem_username_override": False,
        "on_prem_sam_account_name": "",
        "on_prem_distinguished_name": "",
        "mailbox_expected": True,
        "direct_license_count": 0,
        "direct_licenses": [],
        "managed_devices": [],
        "manual_tasks": [{"task_id": "", "label": "RingCentral", "status": "pending", "notes": "", "completed_at": None, "completed_by_email": "", "completed_by_name": ""}],
        "steps": [{"step_key": "disable_sign_in", "label": "Disable Entra Sign-In", "provider": "entra", "will_run": True, "reason": ""}],
        "warnings": [],
        "active_workflow": None,
    }
    mock_user_exit_workflows.create_workflow.return_value = {
        "workflow_id": "workflow-1",
        "user_id": "user-1",
        "user_display_name": "Test User",
        "user_principal_name": "test@example.com",
        "requested_by_email": "test@example.com",
        "requested_by_name": "Test User",
        "status": "running",
        "profile_key": "",
        "on_prem_required": False,
        "requires_on_prem_username_override": False,
        "on_prem_sam_account_name": "",
        "on_prem_distinguished_name": "",
        "created_at": "2026-03-19T00:00:00Z",
        "started_at": None,
        "completed_at": None,
        "error": "",
        "steps": [],
        "manual_tasks": [],
    }
    mock_user_exit_workflows.get_workflow.return_value = mock_user_exit_workflows.create_workflow.return_value
    mock_user_exit_workflows.retry_step.return_value = mock_user_exit_workflows.create_workflow.return_value
    mock_user_exit_workflows.complete_manual_task.return_value = mock_user_exit_workflows.create_workflow.return_value
    mock_user_exit_workflows.claim_agent_step.return_value = None
    mock_user_exit_workflows.heartbeat_agent_step.return_value = None
    mock_user_exit_workflows.complete_agent_step.return_value = mock_user_exit_workflows.create_workflow.return_value
    monkeypatch.setattr(user_exit_workflows_module, "user_exit_workflows", mock_user_exit_workflows)
    monkeypatch.setattr(routes_user_exit, "user_exit_workflows", mock_user_exit_workflows)

    # Import app *after* patching
    import main
    mock_ai_work_scheduler = MagicMock()
    mock_ai_work_scheduler.start_worker = AsyncMock()
    mock_ai_work_scheduler.stop_worker = AsyncMock()
    monkeypatch.setattr(main, "ai_work_scheduler", mock_ai_work_scheduler)
    mock_technician_scoring_manager = MagicMock()
    mock_technician_scoring_manager.start_worker = AsyncMock()
    mock_technician_scoring_manager.stop_worker = AsyncMock()
    monkeypatch.setattr(main, "technician_scoring_manager", mock_technician_scoring_manager)
    mock_kb_store = MagicMock()
    mock_kb_store.ensure_seed_articles.return_value = 0
    monkeypatch.setattr(main, "kb_store", mock_kb_store)
    monkeypatch.setattr(main, "onedrive_copy_jobs", mock_onedrive_copy_jobs)
    monkeypatch.setattr(main, "report_ai_summary_service", mock_report_ai_summary_service)
    app = main.app
    from starlette.testclient import TestClient
    from auth import create_session

    client = TestClient(app)
    # Create a session so tests pass through the auth middleware
    sid = create_session("test@example.com", "Test User")
    client.cookies.set("session_id", sid)
    return client
