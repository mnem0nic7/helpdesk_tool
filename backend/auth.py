"""Microsoft Entra ID (Azure AD) authentication — session store and OAuth client."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any

from starlette.requests import Request

from authlib.integrations.starlette_client import OAuth

from config import (
    ENTRA_TENANT_ID,
    ENTRA_CLIENT_ID,
    ENTRA_CLIENT_SECRET,
    ALLOWED_USERS,
    ADMIN_USERS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}
_SESSION_TTL = timedelta(hours=8)
_last_cleanup: datetime = datetime.now(timezone.utc)
_CLEANUP_INTERVAL = timedelta(minutes=30)


def create_session(email: str, name: str) -> str:
    """Create a new session and return the session ID."""
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = {
        "email": email,
        "name": name,
        "expires_at": datetime.now(timezone.utc) + _SESSION_TTL,
    }
    logger.info("Session created for %s", email)
    return sid


def _cleanup_expired() -> None:
    """Remove all expired sessions periodically to prevent memory leaks."""
    global _last_cleanup
    now = datetime.now(timezone.utc)
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    expired = [sid for sid, s in _sessions.items() if now > s["expires_at"]]
    for sid in expired:
        del _sessions[sid]
    if expired:
        logger.info("Cleaned up %d expired sessions", len(expired))


def get_session(session_id: str) -> dict[str, Any] | None:
    """Return session data if valid and not expired, else None."""
    _cleanup_expired()
    session = _sessions.get(session_id)
    if not session:
        return None
    if datetime.now(timezone.utc) > session["expires_at"]:
        del _sessions[session_id]
        return None
    return session


def delete_session(session_id: str) -> None:
    """Remove a session."""
    _sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# User whitelist
# ---------------------------------------------------------------------------


def is_allowed_user(email: str) -> bool:
    """Check if email is in the ALLOWED_USERS whitelist. Empty = allow all."""
    if not ALLOWED_USERS:
        return True
    allowed = {e.strip().lower() for e in ALLOWED_USERS.split(",") if e.strip()}
    return email.lower() in allowed


def is_admin_user(email: str) -> bool:
    """Check if email is in the ADMIN_USERS list. Empty = all authenticated users are admin."""
    if not ADMIN_USERS:
        return True
    admins = {e.strip().lower() for e in ADMIN_USERS.split(",") if e.strip()}
    return email.lower() in admins


def require_admin(request: Request) -> dict[str, Any]:
    """FastAPI dependency: require admin role. Raises 403 if not admin."""
    from fastapi import HTTPException as _HTTPException
    sid = request.cookies.get("session_id", "")
    session = get_session(sid) if sid else None
    if not session:
        raise _HTTPException(status_code=401, detail="Not authenticated")
    if not is_admin_user(session["email"]):
        raise _HTTPException(status_code=403, detail="Admin access required")
    return session


def session_to_public_user(session: dict[str, Any]) -> dict[str, Any]:
    """Return the frontend-safe user payload for the current session."""
    return {
        "email": session["email"],
        "name": session["name"],
        "is_admin": is_admin_user(session["email"]),
    }


# ---------------------------------------------------------------------------
# OAuth client (Entra ID / Azure AD via OIDC)
# ---------------------------------------------------------------------------

oauth = OAuth()

if ENTRA_TENANT_ID and ENTRA_CLIENT_ID:
    oauth.register(
        name="entra",
        client_id=ENTRA_CLIENT_ID,
        client_secret=ENTRA_CLIENT_SECRET,
        server_metadata_url=(
            f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0/"
            ".well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid email profile"},
    )
