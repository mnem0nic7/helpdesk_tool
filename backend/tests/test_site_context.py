"""Tests for host-aware site scope resolution, including the hrapp scope."""
from __future__ import annotations


def test_get_site_scope_for_host_resolves_hrapp(monkeypatch):
    import config
    monkeypatch.setattr(config, "HRAPP_APP_HOST", "hrapp.movedocs.com")
    import site_context
    monkeypatch.setattr(site_context, "HRAPP_APP_HOST", "hrapp.movedocs.com")

    assert site_context.get_site_scope_for_host("hrapp.movedocs.com") == "hrapp"
    assert site_context.get_site_scope_for_host("hrapp.movedocs.com:443") == "hrapp"


def test_get_site_scope_for_host_still_resolves_azure_and_primary():
    import site_context

    assert site_context.get_site_scope_for_host("azure.movedocs.com") == "azure"
    assert site_context.get_site_scope_for_host("unknown.example.com") == "primary"


def test_issue_matches_scope_returns_false_for_hrapp():
    import site_context

    issue = {"key": "OIT-1", "fields": {"project": {"key": "OIT"}}}
    assert site_context.issue_matches_scope(issue, "hrapp") is False


def test_get_site_profile_returns_hrapp_branding():
    import site_context

    profile = site_context.get_site_profile("hrapp")
    assert profile["scope"] == "hrapp"
    assert profile["app_name"] == "AskHR Portal"


def test_get_auth_provider_for_scope_hrapp_defaults_to_entra():
    import config

    assert config.get_auth_provider_for_scope("hrapp") == "entra"
