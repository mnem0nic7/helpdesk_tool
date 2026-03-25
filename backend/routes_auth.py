"""Auth routes — Entra ID OAuth2 login, callback, user info, logout."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import requests

from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import JSONResponse, RedirectResponse

from auth import (
    atlassian_oauth_configured,
    oauth,
    create_session,
    get_session,
    delete_session,
    delete_atlassian_connection,
    get_atlassian_connection_status,
    is_allowed_user,
    require_authenticated_user,
    save_atlassian_connection,
    session_to_public_user,
)
from config import (
    ATLASSIAN_ACCESS_GROUPS,
    ATLASSIAN_ADMIN_GROUPS,
    ATLASSIAN_ALLOWED_SITE_URL,
    ENTRA_TENANT_ID,
    get_auth_provider_for_scope,
)
from jira_client import JiraClient
from site_context import get_request_origin, get_site_scope_from_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

_COOKIE_NAME = "session_id"
_COOKIE_MAX_AGE = 8 * 60 * 60  # 8 hours


def _safe_return_to(value: str | None) -> str:
    path = str(value or "/").strip() or "/"
    if not path.startswith("/") or path.startswith("//"):
        return "/"
    return path


def _oauth_redirect_uri(request: Request, route_name: str) -> str:
    callback_path = str(request.app.url_path_for(route_name))
    host = (request.headers.get("host") or request.url.netloc or "").strip().lower()
    if host.endswith(".movedocs.com"):
        return f"https://{host}{callback_path}"
    origin = get_request_origin(request).rstrip("/")
    if request.headers.get("x-forwarded-proto") == "https":
        origin = origin.replace("http://", "https://", 1)
    return f"{origin}{callback_path}"


def _request_auth_provider(request: Request) -> str:
    return get_auth_provider_for_scope(get_site_scope_from_request(request))


def _set_session_cookie(response: RedirectResponse, sid: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=sid,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


async def _authorize_atlassian(request: Request, route_name: str):
    if not atlassian_oauth_configured():
        raise HTTPException(status_code=500, detail="Atlassian OAuth is not configured")
    atlassian = oauth.create_client("atlassian")
    if not atlassian:
        raise HTTPException(status_code=500, detail="Atlassian OAuth is not configured")
    redirect_uri = _oauth_redirect_uri(request, route_name)
    try:
        return await atlassian.authorize_redirect(
            request,
            redirect_uri,
            audience="api.atlassian.com",
            prompt="consent",
        )
    except Exception as exc:
        logger.exception("Failed to initiate Atlassian OAuth login")
        raise HTTPException(status_code=500, detail="Atlassian OAuth login failed. Please try again.") from exc


def _resolve_allowed_atlassian_resource(access_token: str) -> tuple[str, str, str]:
    resources_resp = requests.get(
        "https://api.atlassian.com/oauth/token/accessible-resources",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=(10, 30),
    )
    if not resources_resp.ok:
        raise HTTPException(status_code=502, detail="Unable to resolve Atlassian site access")
    resources = resources_resp.json()
    allowed_site = ATLASSIAN_ALLOWED_SITE_URL.rstrip("/").lower()
    resource = next(
        (
            item
            for item in resources
            if str(item.get("url") or "").rstrip("/").lower() == allowed_site
        ),
        None,
    )
    if resource is None:
        raise HTTPException(status_code=403, detail="Your Atlassian account does not have access to the configured Jira site")
    cloud_id = str(resource.get("id") or "").strip()
    site_url = str(resource.get("url") or "").strip()
    scopes = " ".join(sorted(set(resource.get("scopes") or [])))
    return cloud_id, site_url, scopes


def _resolve_atlassian_identity(access_token: str, cloud_id: str) -> dict[str, str]:
    identity_payload: dict[str, Any] = {}
    identity_resp = requests.get(
        "https://api.atlassian.com/me",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=(10, 30),
    )
    if identity_resp.ok:
        identity_payload = identity_resp.json()

    myself_resp = requests.get(
        f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=(10, 30),
    )
    if not myself_resp.ok:
        raise HTTPException(status_code=502, detail="Unable to resolve Atlassian account identity")
    myself = myself_resp.json()

    account_id = (
        str(identity_payload.get("account_id") or "").strip()
        or str(identity_payload.get("accountId") or "").strip()
        or str(myself.get("accountId") or "").strip()
    )
    if not account_id:
        raise HTTPException(status_code=502, detail="Unable to resolve Atlassian account identity")

    email = (
        str(identity_payload.get("email") or "").strip()
        or str(identity_payload.get("emailAddress") or "").strip()
        or str(myself.get("emailAddress") or "").strip()
    )
    if not email:
        logger.warning("Atlassian identity missing email for account %s; falling back to synthetic local address", account_id)
        email = f"{account_id}@atlassian.local"

    name = (
        str(identity_payload.get("name") or "").strip()
        or str(identity_payload.get("nickname") or "").strip()
        or str(myself.get("displayName") or "").strip()
        or email
    )
    return {
        "account_id": account_id,
        "email": email.lower(),
        "name": name,
    }


def _resolve_atlassian_group_access(account_id: str) -> dict[str, Any]:
    groups_to_check: list[str] = []
    for group_name in [*ATLASSIAN_ACCESS_GROUPS, *ATLASSIAN_ADMIN_GROUPS]:
        if group_name not in groups_to_check:
            groups_to_check.append(group_name)

    matched_access: list[str] = []
    matched_admin: list[str] = []
    client = JiraClient()
    for group_name in groups_to_check:
        try:
            members = client.get_group_members(group_name)
        except Exception as exc:
            logger.exception("Failed to resolve Jira group %s during Atlassian login", group_name)
            raise HTTPException(status_code=502, detail="Unable to verify Jira group access") from exc
        if any(str(member.get("accountId") or "").strip() == account_id for member in members):
            if group_name in ATLASSIAN_ACCESS_GROUPS:
                matched_access.append(group_name)
            if group_name in ATLASSIAN_ADMIN_GROUPS:
                matched_admin.append(group_name)
    return {
        "allowed": bool(matched_access or matched_admin),
        "is_admin": bool(matched_admin),
        "access_groups": matched_access,
        "admin_groups": matched_admin,
    }


async def _complete_atlassian_oauth(request: Request) -> dict[str, Any]:
    if not atlassian_oauth_configured():
        raise HTTPException(status_code=500, detail="Atlassian OAuth is not configured")
    atlassian = oauth.create_client("atlassian")
    if not atlassian:
        raise HTTPException(status_code=500, detail="Atlassian OAuth is not configured")

    token = await atlassian.authorize_access_token(request)
    access_token = str(token.get("access_token") or "").strip()
    refresh_token = str(token.get("refresh_token") or "").strip()
    expires_in = int(token.get("expires_in") or 3600)
    if not access_token or not refresh_token:
        raise HTTPException(status_code=400, detail="Atlassian OAuth response was missing required tokens")

    cloud_id, site_url, scope = _resolve_allowed_atlassian_resource(access_token)
    identity = _resolve_atlassian_identity(access_token, cloud_id)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(expires_in - 60, 60))
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "cloud_id": cloud_id,
        "site_url": site_url,
        "scope": scope,
        **identity,
    }


async def _complete_entra_login(request: Request) -> RedirectResponse:
    """Handle the OAuth2 callback from Entra ID."""
    entra = oauth.create_client("entra")
    if not entra:
        raise HTTPException(status_code=500, detail="Entra ID not configured")

    token = await entra.authorize_access_token(request)
    id_token = token.get("userinfo") or {}

    email = id_token.get("email") or id_token.get("preferred_username") or ""
    name = id_token.get("name", email)

    if not email:
        logger.warning("OAuth callback: no email in ID token")
        raise HTTPException(status_code=400, detail="No email returned from Entra ID")

    if not is_allowed_user(email):
        logger.warning("OAuth callback: user %s not in whitelist", email)
        raise HTTPException(status_code=403, detail="Access denied — your account is not authorized")

    sid = create_session(email, name, auth_provider="entra", site_scope=get_site_scope_from_request(request))
    response = RedirectResponse(url="/")
    _set_session_cookie(response, sid)
    logger.info("User %s logged in", email)
    return response


@router.get("/login")
async def login(request: Request):
    """Redirect the user to the configured host-specific primary login provider."""
    if _request_auth_provider(request) == "atlassian":
        return await _authorize_atlassian(request, "auth_callback")

    entra = oauth.create_client("entra")
    if not entra:
        raise HTTPException(status_code=500, detail="Entra ID not configured")
    redirect_uri = _oauth_redirect_uri(request, "auth_callback")
    try:
        return await entra.authorize_redirect(request, redirect_uri)
    except Exception as exc:
        logger.exception("Failed to initiate OAuth login")
        raise HTTPException(status_code=500, detail="OAuth login failed. Please try again.") from exc


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    """Handle the host-specific primary OAuth callback."""
    if _request_auth_provider(request) != "atlassian":
        return await _complete_entra_login(request)

    resolved = await _complete_atlassian_oauth(request)
    access = _resolve_atlassian_group_access(str(resolved.get("account_id") or ""))
    if not access["allowed"]:
        logger.warning("Atlassian login denied for %s; no configured access groups matched", resolved["email"])
        raise HTTPException(status_code=403, detail="Access denied — your Jira account is not authorized for this app")

    save_atlassian_connection(
        email=resolved["email"],
        atlassian_account_id=resolved["account_id"],
        atlassian_account_name=resolved["name"],
        cloud_id=resolved["cloud_id"],
        site_url=resolved["site_url"],
        scope=resolved["scope"],
        access_token=resolved["access_token"],
        refresh_token=resolved["refresh_token"],
        expires_at=resolved["expires_at"],
    )
    sid = create_session(
        resolved["email"],
        resolved["name"],
        auth_provider="atlassian",
        is_admin=bool(access["is_admin"]),
        can_manage_users=bool(access["is_admin"]),
        site_scope=get_site_scope_from_request(request),
    )
    response = RedirectResponse(url="/")
    _set_session_cookie(response, sid)
    logger.info("User %s logged in via Atlassian for %s", resolved["email"], resolved["site_url"])
    return response


@router.get("/me")
async def me(request: Request):
    """Return the currently logged-in user's info."""
    sid = request.cookies.get(_COOKIE_NAME)
    if not sid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = get_session(sid)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")
    return session_to_public_user(session)


@router.get("/atlassian/connect")
async def atlassian_connect(
    request: Request,
    session: dict[str, Any] = Depends(require_authenticated_user),
    return_to: str = Query("/", alias="return_to"),
):
    """Redirect the current MoveDocs user through Atlassian OAuth 3LO."""
    request.session["atlassian_oauth_email"] = str(session.get("email") or "")
    request.session["atlassian_oauth_return_to"] = _safe_return_to(return_to)
    return await _authorize_atlassian(request, "atlassian_callback")


@router.get("/atlassian/callback", name="atlassian_callback")
async def atlassian_callback(
    request: Request,
    _session: dict[str, Any] = Depends(require_authenticated_user),
):
    """Handle the OAuth2 callback from Atlassian."""
    email = str(request.session.pop("atlassian_oauth_email", "") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="MoveDocs session expired before Atlassian connection completed")
    return_to = _safe_return_to(request.session.pop("atlassian_oauth_return_to", "/"))
    resolved = await _complete_atlassian_oauth(request)
    save_atlassian_connection(
        email=email,
        atlassian_account_id=resolved["account_id"],
        atlassian_account_name=resolved["name"],
        cloud_id=resolved["cloud_id"],
        site_url=resolved["site_url"],
        scope=resolved["scope"],
        access_token=resolved["access_token"],
        refresh_token=resolved["refresh_token"],
        expires_at=resolved["expires_at"],
    )
    logger.info("User %s connected Atlassian account for %s", email, resolved["site_url"])
    return RedirectResponse(url=return_to)


@router.get("/atlassian/status")
async def atlassian_status(session: dict[str, Any] = Depends(require_authenticated_user)):
    """Return Atlassian Jira-write connection status for the current user."""
    return get_atlassian_connection_status(str(session.get("email") or ""))


@router.post("/atlassian/disconnect")
async def atlassian_disconnect(session: dict[str, Any] = Depends(require_authenticated_user)):
    """Disconnect the current user's Atlassian account."""
    delete_atlassian_connection(str(session.get("email") or ""))
    return {"disconnected": True}


@router.post("/logout")
async def logout(request: Request):
    """Log out — clear local session and return provider-specific logout guidance."""
    sid = request.cookies.get(_COOKIE_NAME)
    if sid:
        delete_session(sid)
    if _request_auth_provider(request) == "atlassian":
        response = JSONResponse(content={"logged_out": True})
        response.delete_cookie(key=_COOKIE_NAME, path="/", secure=True, samesite="lax")
        return response
    # Build the post-logout redirect back to the current dashboard host.
    app_origin = get_request_origin(request).rstrip("/")
    post_logout_uri = f"{app_origin}/"
    entra_logout = (
        f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={quote(post_logout_uri, safe='')}"
    )
    response = JSONResponse(content={"logged_out": True, "redirect": entra_logout})
    response.delete_cookie(key=_COOKIE_NAME, path="/", secure=True, samesite="lax")
    return response
