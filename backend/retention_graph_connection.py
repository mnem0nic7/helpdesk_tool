"""Delegated Microsoft Graph OAuth connection for the Teams-retention service
account. Mirrors the Atlassian 3LO refresh-token-persistence pattern in
auth.py, but as its own connection: Graph's channel-message delete has no
application-permission path, so this feature needs its own dedicated
service-account identity, distinct from any operator's Entra session."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from cryptography.fernet import Fernet

from auth import APP_SECRET_KEY, oauth
from config import (
    DATA_DIR,
    RETENTION_GRAPH_CLIENT_ID,
    RETENTION_GRAPH_CLIENT_SECRET,
    RETENTION_GRAPH_TENANT_ID,
    RETENTION_TOKEN_ENCRYPTION_KEY,
)
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(DATA_DIR, "retention_graph_connection.db")

RETENTION_GRAPH_SCOPES = (
    "ChannelMessage.ReadWrite ChannelMessage.Read.All TeamMember.ReadWrite.All "
    "Files.ReadWrite.All Team.ReadBasic.All Channel.ReadBasic.All offline_access"
)

if RETENTION_GRAPH_CLIENT_ID and RETENTION_GRAPH_CLIENT_SECRET and RETENTION_GRAPH_TENANT_ID:
    oauth.register(
        name="retention_graph",
        client_id=RETENTION_GRAPH_CLIENT_ID,
        client_secret=RETENTION_GRAPH_CLIENT_SECRET,
        server_metadata_url=(
            f"https://login.microsoftonline.com/{RETENTION_GRAPH_TENANT_ID}/v2.0/"
            ".well-known/openid-configuration"
        ),
        client_kwargs={"scope": RETENTION_GRAPH_SCOPES},
    )


def retention_graph_oauth_configured() -> bool:
    return bool(RETENTION_GRAPH_CLIENT_ID and RETENTION_GRAPH_CLIENT_SECRET and RETENTION_GRAPH_TENANT_ID)


class RetentionGraphConnectionError(Exception):
    """Raised when a valid delegated Graph token cannot be obtained."""


def _token_cipher() -> Fernet:
    raw_key = RETENTION_TOKEN_ENCRYPTION_KEY.strip()
    if raw_key:
        key_bytes = raw_key.encode("utf-8")
    else:
        digest = hashlib.sha256(APP_SECRET_KEY.encode("utf-8")).digest()
        key_bytes = base64.urlsafe_b64encode(digest)
    return Fernet(key_bytes)


def _encrypt(value: str) -> str:
    return _token_cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt(value: str) -> str:
    return _token_cipher().decrypt(value.encode("utf-8")).decode("utf-8")


class RetentionGraphConnectionStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        # Serializes get_valid_token() within this process. Entra rotates refresh
        # tokens, so two callers (background job, /teams, /teams/{id}/channels,
        # compute_preview) both deciding a refresh is due near the 2-minute buffer
        # would redeem the same refresh token concurrently; the loser gets
        # invalid_grant and calls mark_disconnected(), which has no compare-and-set
        # and would clobber the winner's freshly saved 'connected' row.
        # NOTE: this is process-local only — it does not protect against two backend
        # processes (blue/green) refreshing at the same moment.
        self._refresh_lock = threading.Lock()
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _sqlite_conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _conn(self):
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return self._sqlite_conn()

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            return
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retention_graph_connection (
                    id                      INTEGER PRIMARY KEY DEFAULT 1,
                    service_account_upn     TEXT NOT NULL DEFAULT '',
                    encrypted_refresh_token TEXT NOT NULL DEFAULT '',
                    access_token_cache      TEXT NOT NULL DEFAULT '',
                    access_token_expires_at TEXT NOT NULL DEFAULT '',
                    status                  TEXT NOT NULL DEFAULT 'disconnected',
                    last_refreshed_at       TEXT,
                    last_error              TEXT,
                    connected_by            TEXT NOT NULL DEFAULT '',
                    connected_at            TEXT NOT NULL DEFAULT ''
                )
            """)

    def get_connection(self) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT service_account_upn, encrypted_refresh_token, access_token_cache, "
                "access_token_expires_at, status, last_refreshed_at, last_error, connected_by, connected_at "
                "FROM retention_graph_connection WHERE id = 1"
            ).fetchone()
        if not row or not row["encrypted_refresh_token"]:
            return None
        return {
            "service_account_upn": row["service_account_upn"],
            "refresh_token": _decrypt(row["encrypted_refresh_token"]),
            "access_token": _decrypt(row["access_token_cache"]) if row["access_token_cache"] else "",
            "access_token_expires_at": (
                datetime.fromisoformat(row["access_token_expires_at"]) if row["access_token_expires_at"] else None
            ),
            "status": row["status"],
            "last_refreshed_at": row["last_refreshed_at"],
            "last_error": row["last_error"],
            "connected_by": row["connected_by"],
            "connected_at": row["connected_at"],
        }

    def save_connection(
        self,
        *,
        service_account_upn: str,
        refresh_token: str,
        access_token: str,
        access_token_expires_at: datetime,
        connected_by: str,
        status: str = "connected",
        last_error: str | None = None,
    ) -> None:
        ph = self._placeholder()
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                f"""INSERT INTO retention_graph_connection (
                    id, service_account_upn, encrypted_refresh_token, access_token_cache,
                    access_token_expires_at, status, last_refreshed_at, last_error, connected_by, connected_at
                ) VALUES (1, {ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
                ON CONFLICT (id) DO UPDATE SET
                    service_account_upn=excluded.service_account_upn,
                    encrypted_refresh_token=excluded.encrypted_refresh_token,
                    access_token_cache=excluded.access_token_cache,
                    access_token_expires_at=excluded.access_token_expires_at,
                    status=excluded.status,
                    last_refreshed_at=excluded.last_refreshed_at,
                    last_error=excluded.last_error,
                    connected_by=excluded.connected_by,
                    connected_at=excluded.connected_at
                """,
                (
                    service_account_upn,
                    _encrypt(refresh_token),
                    _encrypt(access_token) if access_token else "",
                    access_token_expires_at.isoformat(),
                    status,
                    now,
                    last_error,
                    connected_by,
                    now if status == "connected" else "",
                ),
            )

    def mark_disconnected(self, error: str) -> None:
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE retention_graph_connection SET status = {ph}, last_error = {ph} WHERE id = 1",
                ("disconnected", error),
            )

    def get_status(self) -> dict[str, Any]:
        connection = self.get_connection()
        if not connection:
            return {"status": "disconnected", "service_account_upn": "", "last_refreshed_at": None, "last_error": None}
        return {
            "status": connection["status"],
            "service_account_upn": connection["service_account_upn"],
            "last_refreshed_at": connection["last_refreshed_at"],
            "last_error": connection["last_error"],
        }

    def _refresh_access_token(self, connection: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(
            f"https://login.microsoftonline.com/{RETENTION_GRAPH_TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type": "refresh_token",
                "client_id": RETENTION_GRAPH_CLIENT_ID,
                "client_secret": RETENTION_GRAPH_CLIENT_SECRET,
                "refresh_token": connection["refresh_token"],
                "scope": RETENTION_GRAPH_SCOPES,
            },
            timeout=(10, 30),
        )
        if not resp.ok:
            error = f"Token refresh failed: {resp.status_code} {resp.text[:300]}"
            logger.warning("Retention Graph connection: %s", error)
            self.mark_disconnected(error)
            raise RetentionGraphConnectionError(error)
        payload = resp.json()
        access_token = str(payload.get("access_token") or "").strip()
        new_refresh_token = str(payload.get("refresh_token") or connection["refresh_token"]).strip()
        expires_in = int(payload.get("expires_in") or 3600)
        if not access_token:
            error = "Token refresh response missing access_token"
            logger.warning("Retention Graph connection: %s", error)
            self.mark_disconnected(error)
            raise RetentionGraphConnectionError(error)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(expires_in - 60, 60))
        self.save_connection(
            service_account_upn=connection["service_account_upn"],
            refresh_token=new_refresh_token,
            access_token=access_token,
            access_token_expires_at=expires_at,
            connected_by=connection["connected_by"],
        )
        return {"access_token": access_token, "expires_at": expires_at}

    def get_valid_token(self) -> str:
        # The whole body runs under _refresh_lock so the "is a refresh needed?"
        # check and the refresh itself are one atomic step. Contention is rare
        # (a refresh is only due near token expiry, roughly hourly), and the
        # second caller re-reads the row and sees the first caller's fresh token.
        with self._refresh_lock:
            connection = self.get_connection()
            if not connection:
                raise RetentionGraphConnectionError("Retention Graph connection is not set up")
            if connection["status"] != "connected":
                raise RetentionGraphConnectionError(
                    connection["last_error"] or "Retention Graph connection is disconnected"
                )
            expires_at = connection["access_token_expires_at"]
            if (
                expires_at
                and expires_at > datetime.now(timezone.utc) + timedelta(minutes=2)
                and connection["access_token"]
            ):
                return connection["access_token"]
            logger.info(
                "Retention Graph connection: refreshing access token for %s",
                connection["service_account_upn"],
            )
            refreshed = self._refresh_access_token(connection)
            logger.info("Retention Graph connection: access token refreshed successfully")
            return refreshed["access_token"]


retention_graph_connection = RetentionGraphConnectionStore()
