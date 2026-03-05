"""Auth routes — Entra ID OAuth2 login, callback, user info, logout."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from auth import oauth, create_session, get_session, delete_session, is_allowed_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

_COOKIE_NAME = "session_id"
_COOKIE_MAX_AGE = 8 * 60 * 60  # 8 hours


@router.get("/login")
async def login(request: Request):
    """Redirect the user to Microsoft Entra ID login."""
    entra = oauth.create_client("entra")
    if not entra:
        raise HTTPException(status_code=500, detail="Entra ID not configured")
    # Build callback URL from the request
    redirect_uri = str(request.url_for("auth_callback"))
    # Fix scheme if behind reverse proxy
    if request.headers.get("x-forwarded-proto") == "https":
        redirect_uri = redirect_uri.replace("http://", "https://")
    try:
        return await entra.authorize_redirect(request, redirect_uri)
    except Exception as exc:
        logger.exception("Failed to initiate OAuth login")
        raise HTTPException(status_code=500, detail=f"OAuth login failed: {exc}") from exc


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
    return {"email": session["email"], "name": session["name"]}


@router.post("/logout")
async def logout(request: Request):
    """Log out — clear session and cookie."""
    sid = request.cookies.get(_COOKIE_NAME)
    if sid:
        delete_session(sid)
    response = JSONResponse(content={"logged_out": True})
    response.delete_cookie(key=_COOKIE_NAME, path="/", secure=True, samesite="lax")
    return response
