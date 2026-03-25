"""Microsoft Entra ID (Azure AD) authentication — session store and OAuth client."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
from starlette.requests import Request

from authlib.integrations.starlette_client import OAuth
from cryptography.fernet import Fernet

from config import (
    APP_SECRET_KEY,
    ATLASSIAN_ALLOWED_SITE_URL,
    ATLASSIAN_CLIENT_ID,
    ATLASSIAN_CLIENT_SECRET,
    ATLASSIAN_TOKEN_ENCRYPTION_KEY,
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
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        for name, ddl in (
            ("auth_provider", "ALTER TABLE sessions ADD COLUMN auth_provider TEXT"),
            ("is_admin", "ALTER TABLE sessions ADD COLUMN is_admin INTEGER"),
            ("can_manage_users", "ALTER TABLE sessions ADD COLUMN can_manage_users INTEGER"),
            ("site_scope", "ALTER TABLE sessions ADD COLUMN site_scope TEXT"),
        ):
            if name not in columns:
                conn.execute(ddl)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS atlassian_connections (
                email                    TEXT PRIMARY KEY,
                atlassian_account_id     TEXT NOT NULL,
                atlassian_account_name   TEXT NOT NULL,
                cloud_id                 TEXT NOT NULL,
                site_url                 TEXT NOT NULL,
                scope                    TEXT NOT NULL,
                access_token_encrypted   TEXT NOT NULL,
                refresh_token_encrypted  TEXT NOT NULL,
                expires_at               TEXT NOT NULL,
                updated_at               TEXT NOT NULL
            )
        """)


_init_session_db()


def create_session(
    email: str,
    name: str,
    *,
    auth_provider: str = "entra",
    is_admin: bool | None = None,
    can_manage_users: bool | None = None,
    site_scope: str = "primary",
) -> str:
    """Create a new session, persist it, and return the session ID."""
    sid = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + _SESSION_TTL).isoformat()
    resolved_is_admin = is_admin_user(email) if is_admin is None else bool(is_admin)
    resolved_can_manage_users = resolved_is_admin if can_manage_users is None else bool(can_manage_users)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                sid, email, name, expires_at, auth_provider, is_admin, can_manage_users, site_scope
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid,
                email,
                name,
                expires_at,
                str(auth_provider or "entra"),
                int(resolved_is_admin),
                int(resolved_can_manage_users),
                str(site_scope or "primary"),
            ),
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
            """
            SELECT email, name, expires_at, auth_provider, is_admin, can_manage_users, site_scope
            FROM sessions
            WHERE sid = ?
            """,
            (session_id,),
        ).fetchone()
    if not row:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        delete_session(session_id)
        return None
    stored_is_admin = row["is_admin"]
    stored_can_manage_users = row["can_manage_users"]
    return {
        "email": row["email"],
        "name": row["name"],
        "expires_at": expires_at,
        "auth_provider": str(row["auth_provider"] or "entra"),
        "is_admin": bool(stored_is_admin) if stored_is_admin is not None else is_admin_user(str(row["email"] or "")),
        "can_manage_users": (
            bool(stored_can_manage_users)
            if stored_can_manage_users is not None
            else True
        ),
        "site_scope": str(row["site_scope"] or "primary"),
    }


def delete_session(session_id: str) -> None:
    """Remove a session."""
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("DELETE FROM sessions WHERE sid = ?", (session_id,))


def _token_cipher() -> Fernet:
    raw_key = ATLASSIAN_TOKEN_ENCRYPTION_KEY.strip()
    if raw_key:
        key_bytes = raw_key.encode("utf-8")
    else:
        digest = hashlib.sha256(APP_SECRET_KEY.encode("utf-8")).digest()
        key_bytes = base64.urlsafe_b64encode(digest)
    return Fernet(key_bytes)


def _encrypt_token(value: str) -> str:
    return _token_cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_token(value: str) -> str:
    return _token_cipher().decrypt(value.encode("utf-8")).decode("utf-8")


def _normalize_site_url(url: str) -> str:
    return str(url or "").strip().rstrip("/").lower()


def get_atlassian_connection(email: str) -> dict[str, Any] | None:
    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT email, atlassian_account_id, atlassian_account_name, cloud_id, site_url,
                   scope, access_token_encrypted, refresh_token_encrypted, expires_at, updated_at
            FROM atlassian_connections
            WHERE email = ?
            """,
            (email.lower(),),
        ).fetchone()
    if not row:
        return None
    return {
        "email": row["email"],
        "atlassian_account_id": row["atlassian_account_id"],
        "atlassian_account_name": row["atlassian_account_name"],
        "cloud_id": row["cloud_id"],
        "site_url": row["site_url"],
        "scope": row["scope"],
        "access_token": _decrypt_token(row["access_token_encrypted"]),
        "refresh_token": _decrypt_token(row["refresh_token_encrypted"]),
        "expires_at": datetime.fromisoformat(row["expires_at"]),
        "updated_at": datetime.fromisoformat(row["updated_at"]),
    }


def save_atlassian_connection(
    *,
    email: str,
    atlassian_account_id: str,
    atlassian_account_name: str,
    cloud_id: str,
    site_url: str,
    scope: str,
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO atlassian_connections (
                email, atlassian_account_id, atlassian_account_name, cloud_id, site_url,
                scope, access_token_encrypted, refresh_token_encrypted, expires_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                atlassian_account_id=excluded.atlassian_account_id,
                atlassian_account_name=excluded.atlassian_account_name,
                cloud_id=excluded.cloud_id,
                site_url=excluded.site_url,
                scope=excluded.scope,
                access_token_encrypted=excluded.access_token_encrypted,
                refresh_token_encrypted=excluded.refresh_token_encrypted,
                expires_at=excluded.expires_at,
                updated_at=excluded.updated_at
            """,
            (
                email.lower(),
                atlassian_account_id,
                atlassian_account_name,
                cloud_id,
                site_url.rstrip("/"),
                scope,
                _encrypt_token(access_token),
                _encrypt_token(refresh_token),
                expires_at.isoformat(),
                now,
            ),
        )


def delete_atlassian_connection(email: str) -> None:
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("DELETE FROM atlassian_connections WHERE email = ?", (email.lower(),))


def atlassian_oauth_configured() -> bool:
    return bool(ATLASSIAN_CLIENT_ID and ATLASSIAN_CLIENT_SECRET)


def get_atlassian_connection_status(email: str) -> dict[str, Any]:
    connection = get_atlassian_connection(email)
    connected = connection is not None
    return {
        "connected": connected,
        "mode": "jira_user" if connected else "fallback_it_app",
        "site_url": (connection or {}).get("site_url", ""),
        "account_name": (connection or {}).get("atlassian_account_name", ""),
        "configured": atlassian_oauth_configured(),
    }


def _refresh_atlassian_access_token(connection: dict[str, Any]) -> dict[str, Any] | None:
    if not atlassian_oauth_configured():
        return None
    refresh_token = str(connection.get("refresh_token") or "").strip()
    if not refresh_token:
        return None
    resp = requests.post(
        "https://auth.atlassian.com/oauth/token",
        json={
            "grant_type": "refresh_token",
            "client_id": ATLASSIAN_CLIENT_ID,
            "client_secret": ATLASSIAN_CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
        timeout=(10, 30),
    )
    if not resp.ok:
        logger.warning("Failed to refresh Atlassian token for %s: %s", connection.get("email"), resp.text[:500])
        delete_atlassian_connection(str(connection.get("email") or ""))
        return None
    payload = resp.json()
    access_token = str(payload.get("access_token") or "").strip()
    new_refresh_token = str(payload.get("refresh_token") or refresh_token).strip()
    expires_in = int(payload.get("expires_in") or 3600)
    if not access_token:
        delete_atlassian_connection(str(connection.get("email") or ""))
        return None
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(expires_in - 60, 60))
    save_atlassian_connection(
        email=str(connection.get("email") or ""),
        atlassian_account_id=str(connection.get("atlassian_account_id") or ""),
        atlassian_account_name=str(connection.get("atlassian_account_name") or ""),
        cloud_id=str(connection.get("cloud_id") or ""),
        site_url=str(connection.get("site_url") or ""),
        scope=str(payload.get("scope") or connection.get("scope") or ""),
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_at=expires_at,
    )
    refreshed = get_atlassian_connection(str(connection.get("email") or ""))
    return refreshed


def get_valid_atlassian_connection(email: str) -> dict[str, Any] | None:
    connection = get_atlassian_connection(email)
    if not connection:
        return None
    expires_at = connection.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at > datetime.now(timezone.utc) + timedelta(minutes=2):
        return connection
    return _refresh_atlassian_access_token(connection)


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


def session_is_admin(session: dict[str, Any] | None) -> bool:
    if not session:
        return False
    if str(session.get("auth_provider") or "entra").strip().lower() != "atlassian":
        return is_admin_user(str(session.get("email") or ""))
    stored = session.get("is_admin")
    if stored is not None:
        return bool(stored)
    return is_admin_user(str(session.get("email") or ""))


def session_can_manage_users(session: dict[str, Any] | None) -> bool:
    if not session:
        return False
    if str(session.get("auth_provider") or "entra").strip().lower() != "atlassian":
        return True
    stored = session.get("can_manage_users")
    if stored is not None:
        return bool(stored)
    return True


def require_admin(request: Request) -> dict[str, Any]:
    """FastAPI dependency: require admin role. Raises 403 if not admin."""
    from fastapi import HTTPException as _HTTPException
    sid = request.cookies.get("session_id", "")
    session = get_session(sid) if sid else None
    if not session:
        raise _HTTPException(status_code=401, detail="Not authenticated")
    if not session_is_admin(session):
        raise _HTTPException(status_code=403, detail="Admin access required")
    return session


def require_can_manage_users(request: Request) -> dict[str, Any]:
    """FastAPI dependency: require user-management capability."""
    from fastapi import HTTPException as _HTTPException

    sid = request.cookies.get("session_id", "")
    session = get_session(sid) if sid else None
    if not session:
        raise _HTTPException(status_code=401, detail="Not authenticated")
    if not session_can_manage_users(session):
        raise _HTTPException(status_code=403, detail="User administration access required")
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
        "is_admin": session_is_admin(session),
        "can_manage_users": session_can_manage_users(session),
        "jira_auth": get_atlassian_connection_status(session["email"]),
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

if ATLASSIAN_CLIENT_ID and ATLASSIAN_CLIENT_SECRET:
    oauth.register(
        name="atlassian",
        client_id=ATLASSIAN_CLIENT_ID,
        client_secret=ATLASSIAN_CLIENT_SECRET,
        authorize_url="https://auth.atlassian.com/authorize",
        access_token_url="https://auth.atlassian.com/oauth/token",
        client_kwargs={
            "scope": (
                "openid profile email offline_access read:jira-user read:jira-work write:jira-work "
                "read:servicedesk-request write:servicedesk-request"
            ),
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
