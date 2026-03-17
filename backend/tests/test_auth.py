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
        from auth import create_session, get_session, _sessions
        from datetime import datetime, timezone, timedelta
        sid = create_session("expired@example.com", "Expired User")
        # Manually set expiry to the past
        _sessions[sid]["expires_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
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
        import azure_cache as azure_cache_module

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

        from main import app
        from starlette.testclient import TestClient
        return TestClient(app)

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

    def test_logout_clears_session(self, auth_client):
        from auth import create_session, get_session
        sid = create_session("test@example.com", "Test User")
        auth_client.cookies.set("session_id", sid)
        resp = auth_client.post("/api/auth/logout")
        assert resp.status_code == 200
        # Session should be deleted
        assert get_session(sid) is None
