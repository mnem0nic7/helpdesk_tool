"""Host-aware site scope helpers for the primary and OasisDev dashboard hosts."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Literal

from fastapi import Request

from config import OASISDEV_APP_HOST, PRIMARY_APP_HOST
from jira_client import JiraClient

SiteScope = Literal["primary", "oasisdev"]

_site_scope_var: ContextVar[SiteScope] = ContextVar("site_scope", default="primary")

_SITE_PROFILES: dict[SiteScope, dict[str, str]] = {
    "primary": {
        "scope": "primary",
        "host": PRIMARY_APP_HOST,
        "app_name": "OIT Helpdesk",
        "dashboard_name": "OIT Dashboard",
        "alert_prefix": "OIT",
        "report_prefix": "OIT",
    },
    "oasisdev": {
        "scope": "oasisdev",
        "host": OASISDEV_APP_HOST,
        "app_name": "OasisDev Helpdesk",
        "dashboard_name": "OasisDev Dashboard",
        "alert_prefix": "OasisDev",
        "report_prefix": "OasisDev",
    },
}


def normalize_host(host: str | None) -> str:
    """Return a lowercase hostname without any port suffix."""
    raw = (host or "").strip().lower()
    if not raw:
        return ""
    return raw.split(":", 1)[0]


def get_site_scope_for_host(host: str | None) -> SiteScope:
    """Map a request host to the configured dashboard site scope."""
    if normalize_host(host) == normalize_host(OASISDEV_APP_HOST):
        return "oasisdev"
    return "primary"


def get_site_scope_from_request(request: Request) -> SiteScope:
    """Determine the current site scope from the incoming request host."""
    return get_site_scope_for_host(request.headers.get("host") or request.url.netloc)


def set_current_site_scope(scope: SiteScope) -> Token[SiteScope]:
    """Store the current site scope in a request-local context variable."""
    return _site_scope_var.set(scope)


def reset_current_site_scope(token: Token[SiteScope]) -> None:
    """Restore the previous site scope after a request completes."""
    _site_scope_var.reset(token)


def get_current_site_scope() -> SiteScope:
    """Return the request-local site scope, defaulting to the primary host."""
    return _site_scope_var.get()


def get_site_profile(scope: SiteScope | None = None) -> dict[str, str]:
    """Return branding and host metadata for the requested site scope."""
    active_scope = scope or get_current_site_scope()
    return dict(_SITE_PROFILES[active_scope])


def issue_matches_scope(issue: dict[str, Any], scope: SiteScope) -> bool:
    """Return True when an issue belongs on the given site."""
    is_oasisdev_issue = JiraClient.is_excluded(issue)
    if scope == "oasisdev":
        return is_oasisdev_issue
    return not is_oasisdev_issue


def filter_issues_for_scope(
    issues: list[dict[str, Any]],
    scope: SiteScope | None = None,
) -> list[dict[str, Any]]:
    """Restrict a Jira issue list to the current host-visible site scope."""
    active_scope = scope or get_current_site_scope()
    return [issue for issue in issues if issue_matches_scope(issue, active_scope)]


def get_scoped_issues(*, include_excluded_on_primary: bool = False) -> list[dict[str, Any]]:
    """Return cached issues visible to the current site scope.

    The primary site can optionally request the full cache, preserving the
    existing report/chart behavior where "include excluded" widens the dataset.
    The OasisDev site always stays constrained to OasisDev tickets.
    """
    from issue_cache import cache

    all_issues = cache.get_all_issues()
    scope = get_current_site_scope()
    if scope == "primary" and include_excluded_on_primary:
        return all_issues
    return filter_issues_for_scope(all_issues, scope)


def key_is_visible_in_scope(key: str, scope: SiteScope | None = None) -> bool:
    """Return True when a cached ticket key belongs to the active site scope."""
    from issue_cache import cache

    active_scope = scope or get_current_site_scope()
    for issue in cache.get_all_issues():
        if issue.get("key") == key:
            return issue_matches_scope(issue, active_scope)
    return False


def get_request_origin(request: Request) -> str:
    """Build a same-host absolute origin for redirects and email links."""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    host = (request.headers.get("host") or request.url.netloc or "").strip()
    if not host:
        host = get_site_profile()["host"]
    return f"{proto}://{host}"


def get_site_origin(scope: SiteScope | None = None) -> str:
    """Return the canonical HTTPS origin for a site scope."""
    profile = get_site_profile(scope)
    return f"https://{profile['host']}"
