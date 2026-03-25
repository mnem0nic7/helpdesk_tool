"""Tests for Microsoft Entra ID authentication flow."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make backend importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set required env vars before importing auth modules
os.environ.setdefault("ENTRA_TENANT_ID", "test-tenant-id")
os.environ.setdefault("ENTRA_CLIENT_ID", "test-client-id")
os.environ.setdefault("ENTRA_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ALLOWED_USERS", "")


# ---------------------------------------------------------------------------
# Session store tests
# ---------------------------------------------------------------------------

class TestSessionStore:
    """Tests for in-memory session management."""

    def test_create_session_returns_token(self):
        from auth import create_session
        sid = create_session("alice@example.com", "Alice")
        assert isinstance(sid, str)
        assert len(sid) >= 32

    def test_get_session_returns_user_data(self):
        from auth import create_session, get_session
        sid = create_session("bob@example.com", "Bob Builder")
        session = get_session(sid)
        assert session is not None
        assert session["email"] == "bob@example.com"
        assert session["name"] == "Bob Builder"

    def test_get_session_returns_none_for_unknown(self):
        from auth import get_session
        assert get_session("nonexistent-token") is None

    def test_delete_session_invalidates(self):
        from auth import create_session, get_session, delete_session
        sid = create_session("charlie@example.com", "Charlie")
        delete_session(sid)
        assert get_session(sid) is None

    def test_expired_session_returns_none(self):
        from auth import create_session, get_session, _DB_PATH
        from datetime import datetime, timezone, timedelta
        import sqlite3
        sid = create_session("expired@example.com", "Expired User")
        expired_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute("UPDATE sessions SET expires_at = ? WHERE sid = ?", (expired_at, sid))
            conn.commit()
        assert get_session(sid) is None


# ---------------------------------------------------------------------------
# Allowed users whitelist tests
# ---------------------------------------------------------------------------

class TestAllowedUsers:

    def test_empty_whitelist_allows_all(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_USERS", "")
        # Re-import to pick up env change
        import auth
        monkeypatch.setattr(auth, "ALLOWED_USERS", "")
        assert auth.is_allowed_user("anyone@example.com") is True

    def test_whitelist_allows_listed_user(self, monkeypatch):
        import auth
        monkeypatch.setattr(auth, "ALLOWED_USERS", "alice@example.com,bob@example.com")
        assert auth.is_allowed_user("alice@example.com") is True
        assert auth.is_allowed_user("bob@example.com") is True

    def test_whitelist_blocks_unlisted_user(self, monkeypatch):
        import auth
        monkeypatch.setattr(auth, "ALLOWED_USERS", "alice@example.com")
        assert auth.is_allowed_user("hacker@evil.com") is False

    def test_whitelist_is_case_insensitive(self, monkeypatch):
        import auth
        monkeypatch.setattr(auth, "ALLOWED_USERS", "Alice@Example.COM")
        assert auth.is_allowed_user("alice@example.com") is True


# ---------------------------------------------------------------------------
# Auth middleware tests
# ---------------------------------------------------------------------------

class TestAuthMiddleware:
    """Tests for the authentication middleware protecting /api/* routes."""

    @pytest.fixture()
    def auth_client(self, monkeypatch):
        """TestClient with auth middleware active but cache mocked."""
        import issue_cache
        import routes_metrics
        import routes_tickets
        import routes_chart
        import routes_export
        import routes_cache
        import routes_azure
        import routes_user_admin
        import azure_cache as azure_cache_module
        import user_admin_jobs as user_admin_jobs_module
        import user_admin_providers as user_admin_providers_module

        mock_cache = MagicMock()
        mock_cache.get_filtered_issues.return_value = []
        mock_cache.get_all_issues.return_value = []
        mock_cache.initialized = True
        mock_cache.refreshing = False
        mock_cache.last_refresh = None
        mock_cache.status.return_value = {
            "initialized": True, "refreshing": False,
            "issue_count": 0, "filtered_count": 0, "last_refresh": None,
        }

        for mod in [issue_cache, routes_metrics, routes_tickets, routes_chart, routes_export, routes_cache]:
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
        mock_azure_cache.list_resources.return_value = {
            "resources": [],
            "matched_count": 0,
            "total_count": 0,
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
            "usage_location": "",
            "employee_id": "",
            "employee_type": "",
            "preferred_language": "",
            "proxy_addresses": [],
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
        from starlette.testclient import TestClient
        return TestClient(main.app)

    def test_health_is_public(self, auth_client):
        resp = auth_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["site_scope"] == "primary"

    def test_health_uses_oasisdev_host_scope(self, auth_client):
        resp = auth_client.get("/api/health", headers={"host": "oasisdev.movedocs.com"})
        assert resp.status_code == 200
        assert resp.json()["site_scope"] == "oasisdev"

    def test_health_uses_azure_host_scope(self, auth_client):
        resp = auth_client.get("/api/health", headers={"host": "azure.movedocs.com"})
        assert resp.status_code == 200
        assert resp.json()["site_scope"] == "azure"

    def test_health_uses_forwarded_host_scope(self, auth_client):
        resp = auth_client.get(
            "/api/health",
            headers={
                "host": "dashboard.internal",
                "x-forwarded-host": "oasisdev.movedocs.com",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["site_scope"] == "oasisdev"

    def test_auth_login_is_not_blocked_by_middleware(self, auth_client):
        resp = auth_client.get("/api/auth/login", follow_redirects=False)
        # Login endpoint is public (not blocked by auth middleware).
        # May fail with 500 if OIDC discovery can't reach test tenant — that's OK,
        # the important thing is it's NOT a 401.
        assert resp.status_code != 401

    def test_auth_me_returns_401_without_session(self, auth_client):
        resp = auth_client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_readiness_is_public_and_reports_ready(self, auth_client):
        import main

        main.cache.status.return_value = {
            "initialized": True,
            "refreshing": False,
            "issue_count": 0,
            "filtered_count": 0,
            "last_refresh": "2026-03-23T17:00:00+00:00",
        }
        main.azure_cache.status.return_value = {
            "configured": False,
            "initialized": False,
            "refreshing": False,
            "last_refresh": None,
            "datasets": [],
        }
        main.app.state.kb_seed_status = {
            "ready": True,
            "message": "Knowledge base seed check complete",
            "imported_count": 0,
            "error": None,
        }

        resp = auth_client.get("/api/health/ready")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["status"] == "ready"
        assert payload["site_scope"] == "primary"
        assert payload["components"]["issue_cache"]["ready"] is True
        assert payload["components"]["issue_cache"]["last_refresh"] == "2026-03-23T17:00:00+00:00"
        assert payload["components"]["azure_cache"]["ready"] is False
        assert payload["components"]["knowledge_base"]["ready"] is True

    def test_readiness_returns_503_while_issue_cache_warming(self, auth_client):
        import main

        main.cache.status.return_value = {
            "initialized": False,
            "refreshing": True,
            "issue_count": 0,
            "filtered_count": 0,
            "last_refresh": None,
        }
        main.azure_cache.status.return_value = {
            "configured": True,
            "initialized": True,
            "refreshing": False,
            "last_refresh": "2026-03-23T16:00:00+00:00",
            "datasets": [],
        }
        main.app.state.kb_seed_status = {
            "ready": False,
            "message": "Knowledge base seed import running in the background",
            "imported_count": 0,
            "error": None,
        }

        resp = auth_client.get("/api/health/ready", headers={"host": "azure.movedocs.com"})

        assert resp.status_code == 503
        payload = resp.json()
        assert payload["status"] == "warming"
        assert payload["site_scope"] == "azure"
        assert payload["components"]["issue_cache"]["ready"] is False
        assert payload["components"]["issue_cache"]["message"] == "Issue cache is warming"
        assert payload["components"]["azure_cache"]["ready"] is True
        assert payload["components"]["knowledge_base"]["ready"] is False

    def test_protected_route_returns_401_without_session(self, auth_client):
        resp = auth_client.get("/api/metrics")
        assert resp.status_code == 401

    def test_protected_route_works_with_valid_session(self, auth_client):
        from auth import create_session
        sid = create_session("test@example.com", "Test User")
        auth_client.cookies.set("session_id", sid)
        resp = auth_client.get("/api/metrics")
        assert resp.status_code == 200

    def test_auth_me_returns_user_with_valid_session(self, auth_client):
        from auth import create_session
        sid = create_session("test@example.com", "Test User")
        auth_client.cookies.set("session_id", sid)
        resp = auth_client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "test@example.com"
        assert data["name"] == "Test User"
        assert data["is_admin"] is True
        assert data["can_manage_users"] is True
        assert data["jira_auth"]["connected"] is False
        assert data["jira_auth"]["mode"] == "fallback_it_app"

    def test_logout_clears_session(self, auth_client):
        from auth import create_session, get_session
        sid = create_session("test@example.com", "Test User")
        auth_client.cookies.set("session_id", sid)
        resp = auth_client.post("/api/auth/logout")
        assert resp.status_code == 200
        # Session should be deleted
        assert get_session(sid) is None

    def test_user_exit_agent_endpoint_uses_shared_secret_without_session(self, auth_client, monkeypatch):
        import routes_user_exit

        mock_workflows = MagicMock()
        mock_workflows.claim_agent_step.return_value = None
        monkeypatch.setattr(routes_user_exit, "USER_EXIT_AGENT_SHARED_SECRET", "secret-123")
        monkeypatch.setattr(routes_user_exit, "user_exit_workflows", mock_workflows)

        resp = auth_client.post(
            "/api/user-exit/agent/steps/claim",
            headers={"host": "it-app.movedocs.com", "x-user-exit-agent-secret": "secret-123"},
            json={"agent_id": "agent-1", "profile_keys": ["oasis"]},
        )

        assert resp.status_code == 200
