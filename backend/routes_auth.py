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
from config import ATLASSIAN_ALLOWED_SITE_URL, ENTRA_TENANT_ID
from site_context import get_request_origin

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
    redirect_uri = str(request.url_for(route_name))
    if request.headers.get("x-forwarded-proto") == "https":
        redirect_uri = redirect_uri.replace("http://", "https://")
    return redirect_uri


@router.get("/login")
async def login(request: Request):
    """Redirect the user to Microsoft Entra ID login."""
    entra = oauth.create_client("entra")
    if not entra:
        raise HTTPException(status_code=500, detail="Entra ID not configured")
    # Build callback URL from the request
    redirect_uri = _oauth_redirect_uri(request, "auth_callback")
    try:
        return await entra.authorize_redirect(request, redirect_uri)
    except Exception as exc:
        logger.exception("Failed to initiate OAuth login")
        raise HTTPException(status_code=500, detail="OAuth login failed. Please try again.") from exc


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    """Handle the OAuth2 callback from Entra ID."""
    entra = oauth.create_client("entra")
    if not entra:
        raise HTTPException(status_code=500, detail="Entra ID not configured")

    token = await entra.authorize_access_token(request)
    id_token = token.get("userinfo") or {}

    email = (
        id_token.get("email")
        or id_token.get("preferred_username")
        or ""
    )
    name = id_token.get("name", email)

    if not email:
        logger.warning("OAuth callback: no email in ID token")
        raise HTTPException(status_code=400, detail="No email returned from Entra ID")

    if not is_allowed_user(email):
        logger.warning("OAuth callback: user %s not in whitelist", email)
        raise HTTPException(status_code=403, detail="Access denied — your account is not authorized")

    sid = create_session(email, name)
    response = RedirectResponse(url="/")
    response.set_cookie(
        key=_COOKIE_NAME,
        value=sid,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    logger.info("User %s logged in", email)
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
    if not atlassian_oauth_configured():
        raise HTTPException(status_code=500, detail="Atlassian OAuth is not configured")
    atlassian = oauth.create_client("atlassian")
    if not atlassian:
        raise HTTPException(status_code=500, detail="Atlassian OAuth is not configured")
    request.session["atlassian_oauth_email"] = str(session.get("email") or "")
    request.session["atlassian_oauth_return_to"] = _safe_return_to(return_to)
    redirect_uri = _oauth_redirect_uri(request, "atlassian_callback")
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


@router.get("/atlassian/callback", name="atlassian_callback")
async def atlassian_callback(
    request: Request,
    _session: dict[str, Any] = Depends(require_authenticated_user),
):
    """Handle the OAuth2 callback from Atlassian."""
    if not atlassian_oauth_configured():
        raise HTTPException(status_code=500, detail="Atlassian OAuth is not configured")
    atlassian = oauth.create_client("atlassian")
    if not atlassian:
        raise HTTPException(status_code=500, detail="Atlassian OAuth is not configured")

    email = str(request.session.pop("atlassian_oauth_email", "") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="MoveDocs session expired before Atlassian connection completed")
    return_to = _safe_return_to(request.session.pop("atlassian_oauth_return_to", "/"))

    token = await atlassian.authorize_access_token(request)
    access_token = str(token.get("access_token") or "").strip()
    refresh_token = str(token.get("refresh_token") or "").strip()
    expires_in = int(token.get("expires_in") or 3600)
    if not access_token or not refresh_token:
        raise HTTPException(status_code=400, detail="Atlassian OAuth response was missing required tokens")

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
    myself_resp = requests.get(
        f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=(10, 30),
    )
    if not myself_resp.ok:
        raise HTTPException(status_code=502, detail="Unable to resolve Atlassian account identity")
    myself = myself_resp.json()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(expires_in - 60, 60))
    save_atlassian_connection(
        email=email,
        atlassian_account_id=str(myself.get("accountId") or ""),
        atlassian_account_name=str(myself.get("displayName") or myself.get("emailAddress") or email),
        cloud_id=cloud_id,
        site_url=site_url,
        scope=" ".join(sorted(set(resource.get("scopes") or []))),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )
    logger.info("User %s connected Atlassian account for %s", email, site_url)
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
    """Log out — clear local session, return Entra logout URL."""
    sid = request.cookies.get(_COOKIE_NAME)
    if sid:
        delete_session(sid)
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
