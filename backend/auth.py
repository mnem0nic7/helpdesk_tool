"""Microsoft Entra ID (Azure AD) authentication — session store and OAuth client."""

from __future__ import annotations

import logging
import secrets
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from starlette.requests import Request

from authlib.integrations.starlette_client import OAuth

from config import (
    DATA_DIR,
    ENTRA_TENANT_ID,
    ENTRA_CLIENT_ID,
    ENTRA_CLIENT_SECRET,
    ALLOWED_USERS,
    ADMIN_USERS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLite-backed session store
# ---------------------------------------------------------------------------

_DB_PATH = Path(DATA_DIR) / "sessions.db"
_SESSION_TTL = timedelta(hours=8)
_last_cleanup: datetime = datetime.now(timezone.utc)
_CLEANUP_INTERVAL = timedelta(minutes=30)


def _init_session_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                sid        TEXT PRIMARY KEY,
                email      TEXT NOT NULL,
                name       TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)


_init_session_db()


def create_session(email: str, name: str) -> str:
    """Create a new session, persist it, and return the session ID."""
    sid = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + _SESSION_TTL).isoformat()
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO sessions (sid, email, name, expires_at) VALUES (?, ?, ?, ?)",
            (sid, email, name, expires_at),
        )
    logger.info("Session created for %s", email)
    return sid


def _cleanup_expired() -> None:
    """Remove expired sessions periodically."""
    global _last_cleanup
    now = datetime.now(timezone.utc)
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    with sqlite3.connect(_DB_PATH) as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE expires_at < ?",
            (now.isoformat(),),
        )
    if cur.rowcount:
        logger.info("Cleaned up %d expired sessions", cur.rowcount)


def get_session(session_id: str) -> dict[str, Any] | None:
    """Return session data if valid and not expired, else None."""
    _cleanup_expired()
    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT email, name, expires_at FROM sessions WHERE sid = ?",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        delete_session(session_id)
        return None
    return {"email": row["email"], "name": row["name"], "expires_at": expires_at}


def delete_session(session_id: str) -> None:
    """Remove a session."""
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("DELETE FROM sessions WHERE sid = ?", (session_id,))


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


def require_authenticated_user(request: Request) -> dict[str, Any]:
    """FastAPI dependency: require a valid session and return it."""
    from fastapi import HTTPException as _HTTPException

    sid = request.cookies.get("session_id", "")
    session = get_session(sid) if sid else None
    if not session:
        raise _HTTPException(status_code=401, detail="Not authenticated")
    return session


def session_to_public_user(session: dict[str, Any]) -> dict[str, Any]:
    """Return the frontend-safe user payload for the current session."""
    return {
        "email": session["email"],
        "name": session["name"],
        "is_admin": is_admin_user(session["email"]),
        "can_manage_users": True,
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
