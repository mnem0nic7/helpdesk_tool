# Teams Message Retention (retention.movedocs.com) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new host, `retention.movedocs.com`, where allowlisted operators browse Microsoft Teams/channels and configure a per-channel rolling message-retention window, enforced by an hourly leader-only job that deletes aged channel messages, replies, and SharePoint attachments through a delegated (not app-only) Microsoft Graph connection signed in as a dedicated service account.

**Architecture:** New `retention` site scope alongside the existing `primary`/`oasisdev`/`azure`/`security`/`hrapp` scopes (`backend/site_context.py`). A one-time delegated OAuth connection (`backend/retention_graph_connection.py`) persists an encrypted refresh token for the service account, mirroring the existing Atlassian 3LO pattern in `backend/auth.py`. A policy store (`backend/retention_policy_store.py`) tracks per-channel policies through a `pending_preview` → `active` state machine plus durable run/deletion audit tables. A thin Graph client (`backend/retention_graph_client.py`) wraps the delegated HTTP calls. An hourly leader-only job (`backend/retention_cleanup_job.py`) orchestrates enforcement, exposing a `compute_preview()` method the API also uses for the dry-run step. Two new frontend pages talk to a new `/api/retention/*` route set.

**Tech Stack:** FastAPI + `authlib` OAuth (existing `oauth` client registry in `auth.py`), SQLite/Postgres dual-write via `postgres_utils`/`sqlite_utils` (existing pattern), `requests` for raw Graph HTTP calls (no MSAL, matching the rest of the repo), React 19 + React Query 5 on the frontend.

**Spec:** `docs/superpowers/specs/2026-09-10-teams-retention-design.md` — read it in full before starting; this plan implements it task-by-task and does not restate every rationale from it.

## Global Constraints

- Graph's channel-message delete has no application-permission path — every Graph call in this feature (list, delete) must use the delegated service-account token from `retention_graph_connection`, never a client-credentials app-only token.
- `retention_days` is always 1–365 inclusive; reject anything outside that range with a 400.
- A policy never deletes anything until it has gone through `pending_preview` → operator preview → `POST .../confirm` → `active`. Creating or editing `retention_days` always lands a policy in `pending_preview`.
- `RETENTION_ALLOWED_USERS` empty means **deny all** (fail closed) — this is the opposite default of the existing `ALLOWED_USERS` var, because this host can trigger tenant-wide message deletion.
- Every table uses `SMALLINT` for booleans (none needed here — all state is string enums) and `CREATE TABLE IF NOT EXISTS` / idempotent DDL, per repo convention.
- New Postgres migrations must be numbered following the existing sequence (current highest is `0030_askhr_bot_customer_accounts.sql`, so this plan uses `0031` and `0032`).

---

## Task 1: Backend site scope and config plumbing

**Files:**
- Modify: `backend/config.py` (near line 140, after `HRAPP_AUTH_PROVIDER`; near line 183, after `ALLOWED_USERS`; near line 192, after `ATLASSIAN_TOKEN_ENCRYPTION_KEY`; and `get_auth_provider_for_scope` at line 234)
- Modify: `backend/site_context.py`
- Test: `backend/tests/test_site_context.py`

**Interfaces:**
- Produces: `config.RETENTION_APP_HOST: str`, `config.RETENTION_AUTH_PROVIDER: str`, `config.RETENTION_ALLOWED_USERS: str`, `config.RETENTION_GRAPH_CLIENT_ID/CLIENT_SECRET/TENANT_ID: str`, `config.RETENTION_TOKEN_ENCRYPTION_KEY: str`, `site_context.SiteScope` including `"retention"`, `site_context.get_site_scope_for_host()` mapping `RETENTION_APP_HOST` to `"retention"`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_site_context.py — add these cases (existing file already tests other scopes)
def test_retention_host_maps_to_retention_scope():
    from site_context import get_site_scope_for_host
    from config import RETENTION_APP_HOST
    assert get_site_scope_for_host(RETENTION_APP_HOST) == "retention"


def test_retention_scope_excluded_from_scoped_issues():
    from site_context import issue_matches_scope
    issue = {"key": "OIT-1", "fields": {"project": {"key": "OIT"}}}
    assert issue_matches_scope(issue, "retention") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_site_context.py -k retention -v`
Expected: FAIL — `get_site_scope_for_host` returns `"primary"` for the retention host (no branch yet), and `issue_matches_scope` raises `KeyError` or returns `True` since `"retention"` isn't yet in the exclusion tuple.

- [ ] **Step 3: Implement the config additions**

In `backend/config.py`, after line 140 (`HRAPP_AUTH_PROVIDER: str = _env_auth_provider("HRAPP_AUTH_PROVIDER", "entra")`):

```python
RETENTION_APP_HOST: str = os.getenv("RETENTION_APP_HOST", "retention.movedocs.com")
RETENTION_AUTH_PROVIDER: str = _env_auth_provider("RETENTION_AUTH_PROVIDER", "entra")
```

After line 183 (`ALLOWED_USERS: str = os.getenv("ALLOWED_USERS", "")`):

```python
RETENTION_ALLOWED_USERS: str = os.getenv("RETENTION_ALLOWED_USERS", "")  # comma-separated emails; empty = deny all (fail closed — this host can delete tenant Teams data)
```

After line 192 (`ATLASSIAN_TOKEN_ENCRYPTION_KEY: str = os.getenv("ATLASSIAN_TOKEN_ENCRYPTION_KEY", "").strip()`):

```python
# Delegated Microsoft Graph OAuth for the Teams-retention service account
# (deleting channel messages has no supported application-permission path).
RETENTION_GRAPH_CLIENT_ID: str = os.getenv("RETENTION_GRAPH_CLIENT_ID", "").strip()
RETENTION_GRAPH_CLIENT_SECRET: str = os.getenv("RETENTION_GRAPH_CLIENT_SECRET", "").strip()
RETENTION_GRAPH_TENANT_ID: str = os.getenv("RETENTION_GRAPH_TENANT_ID", "").strip()
RETENTION_TOKEN_ENCRYPTION_KEY: str = os.getenv("RETENTION_TOKEN_ENCRYPTION_KEY", "").strip()
```

Update `get_auth_provider_for_scope` (around line 234):

```python
def get_auth_provider_for_scope(scope: str) -> AuthProvider:
    if scope == "azure":
        return AZURE_AUTH_PROVIDER  # type: ignore[return-value]
    if scope == "security":
        return SECURITY_AUTH_PROVIDER  # type: ignore[return-value]
    if scope == "hrapp":
        return HRAPP_AUTH_PROVIDER  # type: ignore[return-value]
    if scope == "retention":
        return RETENTION_AUTH_PROVIDER  # type: ignore[return-value]
    if scope == "oasisdev":
        return OASISDEV_AUTH_PROVIDER  # type: ignore[return-value]
    return PRIMARY_AUTH_PROVIDER  # type: ignore[return-value]
```

- [ ] **Step 4: Implement the site_context.py additions**

In `backend/site_context.py`, update the import line:

```python
from config import (
    AZURE_APP_HOST,
    HRAPP_APP_HOST,
    OASISDEV_APP_HOST,
    PRIMARY_APP_HOST,
    RETENTION_APP_HOST,
    SECURITY_APP_HOST,
)
```

Update the `SiteScope` literal:

```python
SiteScope = Literal["primary", "oasisdev", "azure", "security", "hrapp", "retention"]
```

Add to `_SITE_PROFILES` (after the `"hrapp"` entry):

```python
    "retention": {
        "scope": "retention",
        "host": RETENTION_APP_HOST,
        "app_name": "Teams Retention",
        "dashboard_name": "Teams Retention",
        "alert_prefix": "Retention",
        "report_prefix": "Retention",
    },
```

Add a branch to `get_site_scope_for_host` (after the `HRAPP_APP_HOST` check):

```python
    if normalized == normalize_host(RETENTION_APP_HOST):
        return "retention"
```

Update the no-Jira-issues group in both `issue_matches_scope` and `get_scoped_issues`:

```python
    if scope in ("azure", "security", "hrapp", "retention"):
        return False  # (issue_matches_scope)
```

```python
    if scope in ("azure", "security", "hrapp", "retention"):
        return []  # (get_scoped_issues)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_site_context.py -k retention -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/config.py backend/site_context.py backend/tests/test_site_context.py
git commit -m "feat(retention): add retention site scope and config"
```

---

## Task 2: Retention allowlist auth dependency

**Files:**
- Modify: `backend/auth.py` (near `is_allowed_user`/`require_admin`, around line 580 and 623)
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Consumes: `config.RETENTION_ALLOWED_USERS` (Task 1).
- Produces: `auth.is_retention_allowed_user(email: str) -> bool`, `auth.require_retention_access(request: Request) -> dict[str, Any]` (FastAPI dependency, 401 if unauthenticated, 403 if not allowlisted).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_auth.py — add these cases
def test_is_retention_allowed_user_denies_all_when_unset(monkeypatch):
    import auth
    import config
    monkeypatch.setattr(config, "RETENTION_ALLOWED_USERS", "")
    monkeypatch.setattr(auth, "RETENTION_ALLOWED_USERS", "")
    assert auth.is_retention_allowed_user("anyone@example.com") is False


def test_is_retention_allowed_user_allows_listed_email(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "RETENTION_ALLOWED_USERS", "ops@example.com, Other@Example.com")
    assert auth.is_retention_allowed_user("ops@example.com") is True
    assert auth.is_retention_allowed_user("other@example.com") is True
    assert auth.is_retention_allowed_user("nope@example.com") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_auth.py -k retention_allowed -v`
Expected: FAIL with `AttributeError: module 'auth' has no attribute 'is_retention_allowed_user'`

- [ ] **Step 3: Implement**

In `backend/auth.py`, add `RETENTION_ALLOWED_USERS` to the existing `from config import (...)` block, then add near `is_allowed_user` (after line 585):

```python
def is_retention_allowed_user(email: str) -> bool:
    """Check RETENTION_ALLOWED_USERS. Empty = deny all (fail closed) — unlike
    is_allowed_user, this host can trigger tenant-wide Teams message deletion."""
    allowed = {e.strip().lower() for e in RETENTION_ALLOWED_USERS.split(",") if e.strip()}
    if not allowed:
        return False
    return email.lower() in allowed
```

Add near `require_admin` (after line 632):

```python
def require_retention_access(request: Request) -> dict[str, Any]:
    """FastAPI dependency: require an authenticated session allowlisted for retention.movedocs.com."""
    from fastapi import HTTPException as _HTTPException

    sid = request.cookies.get("session_id", "")
    session = get_session(sid) if sid else None
    if not session:
        raise _HTTPException(status_code=401, detail="Not authenticated")
    if not is_retention_allowed_user(str(session.get("email") or "")):
        raise _HTTPException(status_code=403, detail="Retention access required")
    return session
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_auth.py -k retention_allowed -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/auth.py backend/tests/test_auth.py
git commit -m "feat(retention): add retention allowlist auth dependency"
```

---

## Task 3: Delegated Graph service-account connection store

**Files:**
- Create: `backend/storage_migrations/0031_retention_graph_connection.sql`
- Create: `backend/retention_graph_connection.py`
- Test: `backend/tests/test_retention_graph_connection.py`

**Interfaces:**
- Consumes: `config.RETENTION_GRAPH_CLIENT_ID/CLIENT_SECRET/TENANT_ID`, `config.RETENTION_TOKEN_ENCRYPTION_KEY` (Task 1), `auth.oauth` (existing `OAuth()` registry), `auth.APP_SECRET_KEY`.
- Produces: `RetentionGraphConnectionError` (exception), `RetentionGraphConnectionStore` class with `get_connection()`, `save_connection(...)`, `mark_disconnected(error)`, `get_status()`, `get_valid_token() -> str`; module singleton `retention_graph_connection`; `retention_graph_oauth_configured() -> bool`; `RETENTION_GRAPH_SCOPES: str`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_retention_graph_connection.py
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _fresh_store():
    from retention_graph_connection import RetentionGraphConnectionStore
    return RetentionGraphConnectionStore(db_path=tempfile.mktemp(suffix=".db"))


def test_get_connection_returns_none_when_unset():
    store = _fresh_store()
    assert store.get_connection() is None
    assert store.get_status() == {
        "status": "disconnected", "service_account_upn": "", "last_refreshed_at": None, "last_error": None,
    }


def test_save_and_get_connection_round_trips_and_encrypts_refresh_token():
    store = _fresh_store()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="raw-refresh-token",
        access_token="raw-access-token",
        access_token_expires_at=expires_at,
        connected_by="ops@example.com",
    )
    with store._sqlite_conn() as conn:
        row = conn.execute("SELECT encrypted_refresh_token FROM retention_graph_connection WHERE id = 1").fetchone()
    assert "raw-refresh-token" not in row["encrypted_refresh_token"]

    connection = store.get_connection()
    assert connection["service_account_upn"] == "retention-bot@movedocs.com"
    assert connection["refresh_token"] == "raw-refresh-token"
    assert connection["status"] == "connected"


def test_get_valid_token_returns_cached_token_when_not_near_expiry():
    store = _fresh_store()
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="rt",
        access_token="cached-access-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        connected_by="ops@example.com",
    )
    with patch("retention_graph_connection.requests") as mock_requests:
        token = store.get_valid_token()
    assert token == "cached-access-token"
    mock_requests.post.assert_not_called()


def test_get_valid_token_refreshes_when_near_expiry():
    store = _fresh_store()
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="old-refresh",
        access_token="stale-access-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        connected_by="ops@example.com",
    )
    mock_response = MagicMock(ok=True)
    mock_response.json.return_value = {"access_token": "new-access-token", "refresh_token": "new-refresh", "expires_in": 3600}
    with patch("retention_graph_connection.requests.post", return_value=mock_response):
        token = store.get_valid_token()
    assert token == "new-access-token"
    assert store.get_connection()["refresh_token"] == "new-refresh"


def test_get_valid_token_marks_disconnected_on_refresh_failure():
    from retention_graph_connection import RetentionGraphConnectionError
    store = _fresh_store()
    store.save_connection(
        service_account_upn="retention-bot@movedocs.com",
        refresh_token="old-refresh",
        access_token="stale-access-token",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        connected_by="ops@example.com",
    )
    mock_response = MagicMock(ok=False, status_code=400, text="invalid_grant")
    with patch("retention_graph_connection.requests.post", return_value=mock_response):
        try:
            store.get_valid_token()
            assert False, "expected RetentionGraphConnectionError"
        except RetentionGraphConnectionError:
            pass
    assert store.get_status()["status"] == "disconnected"


def test_get_valid_token_raises_when_never_connected():
    from retention_graph_connection import RetentionGraphConnectionError
    store = _fresh_store()
    try:
        store.get_valid_token()
        assert False, "expected RetentionGraphConnectionError"
    except RetentionGraphConnectionError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_retention_graph_connection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'retention_graph_connection'`

- [ ] **Step 3: Create the migration**

`backend/storage_migrations/0031_retention_graph_connection.sql`:

```sql
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
);
```

- [ ] **Step 4: Implement `backend/retention_graph_connection.py`**

```python
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
    "ChannelMessage.ReadWrite Files.ReadWrite.All "
    "Team.ReadBasic.All Channel.ReadBasic.All offline_access"
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
            self.mark_disconnected(error)
            raise RetentionGraphConnectionError(error)
        payload = resp.json()
        access_token = str(payload.get("access_token") or "").strip()
        new_refresh_token = str(payload.get("refresh_token") or connection["refresh_token"]).strip()
        expires_in = int(payload.get("expires_in") or 3600)
        if not access_token:
            error = "Token refresh response missing access_token"
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
        connection = self.get_connection()
        if not connection:
            raise RetentionGraphConnectionError("Retention Graph connection is not set up")
        if connection["status"] != "connected":
            raise RetentionGraphConnectionError(connection["last_error"] or "Retention Graph connection is disconnected")
        expires_at = connection["access_token_expires_at"]
        if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=2) and connection["access_token"]:
            return connection["access_token"]
        refreshed = self._refresh_access_token(connection)
        return refreshed["access_token"]


retention_graph_connection = RetentionGraphConnectionStore()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_retention_graph_connection.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/storage_migrations/0031_retention_graph_connection.sql backend/retention_graph_connection.py backend/tests/test_retention_graph_connection.py
git commit -m "feat(retention): add delegated Graph service-account connection store"
```

---

## Task 4: Retention policy store (policies, runs, deletions)

**Files:**
- Create: `backend/storage_migrations/0032_retention_policies.sql`
- Create: `backend/retention_policy_store.py`
- Test: `backend/tests/test_retention_policy_store.py`

**Interfaces:**
- Produces: `RetentionPolicyStore` class with `create_policy(...)`, `get_policy(policy_id)`, `get_policy_for_channel(team_id, channel_id)`, `list_policies(limit, offset)`, `list_active_policies()`, `confirm_policy(policy_id)`, `update_policy(policy_id, retention_days=None, status=None)`, `start_run(policy_id) -> str`, `finish_run(run_id, outcome, messages_deleted, attachments_deleted, error=None)`, `record_deletion(...)`, `list_runs(policy_id=None, limit, offset)`, `list_deletions(run_id=None, limit, offset)`; module singleton `retention_policy_store`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_retention_policy_store.py
from __future__ import annotations

import tempfile


def _fresh_store():
    from retention_policy_store import RetentionPolicyStore
    return RetentionPolicyStore(db_path=tempfile.mktemp(suffix=".db"))


def test_create_policy_starts_pending_preview():
    store = _fresh_store()
    policy = store.create_policy(
        team_id="team-1", team_name="Engineering", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    assert policy["status"] == "pending_preview"
    assert policy["retention_days"] == 30
    assert store.get_policy_for_channel("team-1", "chan-1")["id"] == policy["id"]


def test_confirm_policy_sets_active():
    store = _fresh_store()
    policy = store.create_policy(
        team_id="team-1", team_name="Engineering", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    confirmed = store.confirm_policy(policy["id"])
    assert confirmed["status"] == "active"
    assert [p["id"] for p in store.list_active_policies()] == [policy["id"]]


def test_update_policy_retention_days_resets_to_pending_preview():
    store = _fresh_store()
    policy = store.create_policy(
        team_id="team-1", team_name="Engineering", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    store.confirm_policy(policy["id"])
    updated = store.update_policy(policy["id"], retention_days=60)
    assert updated["status"] == "pending_preview"
    assert updated["retention_days"] == 60
    assert store.list_active_policies() == []


def test_update_policy_status_disable_does_not_reset_days():
    store = _fresh_store()
    policy = store.create_policy(
        team_id="team-1", team_name="Engineering", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    store.confirm_policy(policy["id"])
    updated = store.update_policy(policy["id"], status="disabled")
    assert updated["status"] == "disabled"
    assert updated["retention_days"] == 30


def test_run_and_deletion_lifecycle():
    store = _fresh_store()
    policy = store.create_policy(
        team_id="team-1", team_name="Engineering", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    run_id = store.start_run(policy["id"])
    store.record_deletion(
        run_id=run_id, item_type="message", item_id="msg-1", sender_or_author="Alice",
        original_created_at="2026-01-01T00:00:00Z", status="deleted",
    )
    store.record_deletion(
        run_id=run_id, item_type="attachment", item_id="att-1", sender_or_author="Alice",
        original_created_at="2026-01-01T00:00:00Z", status="failed", error="not found",
    )
    store.finish_run(run_id, outcome="partial", messages_deleted=1, attachments_deleted=0, error=None)

    runs, total_runs = store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert total_runs == 1
    assert runs[0]["outcome"] == "partial"
    assert runs[0]["messages_deleted"] == 1

    deletions, total_deletions = store.list_deletions(run_id=run_id, limit=10, offset=0)
    assert total_deletions == 2
    statuses = {d["item_id"]: d["status"] for d in deletions}
    assert statuses == {"msg-1": "deleted", "att-1": "failed"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_retention_policy_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'retention_policy_store'`

- [ ] **Step 3: Create the migration**

`backend/storage_migrations/0032_retention_policies.sql`:

```sql
CREATE TABLE IF NOT EXISTS retention_policies (
    id             TEXT PRIMARY KEY,
    team_id        TEXT NOT NULL,
    team_name      TEXT NOT NULL DEFAULT '',
    channel_id     TEXT NOT NULL,
    channel_name   TEXT NOT NULL DEFAULT '',
    retention_days INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending_preview',
    created_by     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_retention_policies_channel
    ON retention_policies (team_id, channel_id);

CREATE TABLE IF NOT EXISTS retention_runs (
    id                  TEXT PRIMARY KEY,
    policy_id           TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    outcome             TEXT NOT NULL DEFAULT 'running',
    messages_deleted    INTEGER NOT NULL DEFAULT 0,
    attachments_deleted INTEGER NOT NULL DEFAULT 0,
    error               TEXT
);

CREATE INDEX IF NOT EXISTS idx_retention_runs_policy
    ON retention_runs (policy_id);

CREATE TABLE IF NOT EXISTS retention_deletions (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    item_type           TEXT NOT NULL,
    item_id             TEXT NOT NULL,
    sender_or_author    TEXT NOT NULL DEFAULT '',
    original_created_at TEXT NOT NULL DEFAULT '',
    deleted_at          TEXT NOT NULL,
    status              TEXT NOT NULL,
    error               TEXT
);

CREATE INDEX IF NOT EXISTS idx_retention_deletions_run
    ON retention_deletions (run_id);
```

- [ ] **Step 4: Implement `backend/retention_policy_store.py`**

```python
"""Persistence for Teams retention policies, worker runs, and the per-item
deletion audit trail. Pure storage — no Graph calls live here."""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

_DB_PATH = os.path.join(DATA_DIR, "retention_policies.db")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class RetentionPolicyStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
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
                CREATE TABLE IF NOT EXISTS retention_policies (
                    id             TEXT PRIMARY KEY,
                    team_id        TEXT NOT NULL,
                    team_name      TEXT NOT NULL DEFAULT '',
                    channel_id     TEXT NOT NULL,
                    channel_name   TEXT NOT NULL DEFAULT '',
                    retention_days INTEGER NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'pending_preview',
                    created_by     TEXT NOT NULL DEFAULT '',
                    created_at     TEXT NOT NULL DEFAULT '',
                    updated_at     TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_retention_policies_channel
                    ON retention_policies (team_id, channel_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retention_runs (
                    id                  TEXT PRIMARY KEY,
                    policy_id           TEXT NOT NULL,
                    started_at          TEXT NOT NULL,
                    finished_at         TEXT,
                    outcome             TEXT NOT NULL DEFAULT 'running',
                    messages_deleted    INTEGER NOT NULL DEFAULT 0,
                    attachments_deleted INTEGER NOT NULL DEFAULT 0,
                    error               TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_retention_runs_policy
                    ON retention_runs (policy_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retention_deletions (
                    id                  TEXT PRIMARY KEY,
                    run_id              TEXT NOT NULL,
                    item_type           TEXT NOT NULL,
                    item_id             TEXT NOT NULL,
                    sender_or_author    TEXT NOT NULL DEFAULT '',
                    original_created_at TEXT NOT NULL DEFAULT '',
                    deleted_at          TEXT NOT NULL,
                    status              TEXT NOT NULL,
                    error               TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_retention_deletions_run
                    ON retention_deletions (run_id)
            """)

    # -- policies --

    def create_policy(
        self, *, team_id: str, team_name: str, channel_id: str, channel_name: str,
        retention_days: int, created_by: str,
    ) -> dict[str, Any]:
        ph = self._placeholder()
        policy_id = uuid.uuid4().hex
        now = _utcnow()
        with self._conn() as conn:
            conn.execute(
                f"""INSERT INTO retention_policies
                    (id, team_id, team_name, channel_id, channel_name, retention_days, status, created_by, created_at, updated_at)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},'pending_preview',{ph},{ph},{ph})""",
                (policy_id, team_id, team_name, channel_id, channel_name, retention_days, created_by, now, now),
            )
        policy = self.get_policy(policy_id)
        assert policy is not None
        return policy

    def get_policy(self, policy_id: str) -> dict[str, Any] | None:
        ph = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT id, team_id, team_name, channel_id, channel_name, retention_days, status, "
                f"created_by, created_at, updated_at FROM retention_policies WHERE id = {ph}",
                (policy_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_policy_for_channel(self, team_id: str, channel_id: str) -> dict[str, Any] | None:
        ph = self._placeholder()
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT id, team_id, team_name, channel_id, channel_name, retention_days, status, "
                f"created_by, created_at, updated_at FROM retention_policies "
                f"WHERE team_id = {ph} AND channel_id = {ph}",
                (team_id, channel_id),
            ).fetchone()
        return dict(row) if row else None

    def list_policies(self, *, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        ph = self._placeholder()
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) AS cnt FROM retention_policies").fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT id, team_id, team_name, channel_id, channel_name, retention_days, status, "
                f"created_by, created_at, updated_at FROM retention_policies "
                f"ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows], total

    def list_active_policies(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, team_id, team_name, channel_id, channel_name, retention_days, status, "
                "created_by, created_at, updated_at FROM retention_policies WHERE status = 'active'"
            ).fetchall()
        return [dict(r) for r in rows]

    def confirm_policy(self, policy_id: str) -> dict[str, Any] | None:
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE retention_policies SET status = 'active', updated_at = {ph} WHERE id = {ph}",
                (_utcnow(), policy_id),
            )
        return self.get_policy(policy_id)

    def update_policy(
        self, policy_id: str, *, retention_days: int | None = None, status: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_policy(policy_id)
        if not current:
            return None
        new_days = current["retention_days"] if retention_days is None else retention_days
        if retention_days is not None:
            new_status = "pending_preview"
        elif status is not None:
            new_status = status
        else:
            new_status = current["status"]
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE retention_policies SET retention_days = {ph}, status = {ph}, updated_at = {ph} WHERE id = {ph}",
                (new_days, new_status, _utcnow(), policy_id),
            )
        return self.get_policy(policy_id)

    # -- runs / deletions --

    def start_run(self, policy_id: str) -> str:
        ph = self._placeholder()
        run_id = uuid.uuid4().hex
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO retention_runs (id, policy_id, started_at, outcome) VALUES ({ph},{ph},{ph},'running')",
                (run_id, policy_id, _utcnow()),
            )
        return run_id

    def finish_run(
        self, run_id: str, *, outcome: str, messages_deleted: int, attachments_deleted: int, error: str | None = None,
    ) -> None:
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"UPDATE retention_runs SET finished_at = {ph}, outcome = {ph}, messages_deleted = {ph}, "
                f"attachments_deleted = {ph}, error = {ph} WHERE id = {ph}",
                (_utcnow(), outcome, messages_deleted, attachments_deleted, error, run_id),
            )

    def record_deletion(
        self, *, run_id: str, item_type: str, item_id: str, sender_or_author: str,
        original_created_at: str, status: str, error: str | None = None,
    ) -> None:
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"""INSERT INTO retention_deletions
                    (id, run_id, item_type, item_id, sender_or_author, original_created_at, deleted_at, status, error)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
                (uuid.uuid4().hex, run_id, item_type, item_id, sender_or_author, original_created_at, _utcnow(), status, error),
            )

    def list_runs(
        self, *, policy_id: str | None = None, limit: int = 30, offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        ph = self._placeholder()
        columns = "id, policy_id, started_at, finished_at, outcome, messages_deleted, attachments_deleted, error"
        with self._conn() as conn:
            if policy_id:
                total = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM retention_runs WHERE policy_id = {ph}", (policy_id,)
                ).fetchone()["cnt"]
                rows = conn.execute(
                    f"SELECT {columns} FROM retention_runs WHERE policy_id = {ph} "
                    f"ORDER BY started_at DESC LIMIT {ph} OFFSET {ph}",
                    (policy_id, limit, offset),
                ).fetchall()
            else:
                total = conn.execute("SELECT COUNT(*) AS cnt FROM retention_runs").fetchone()["cnt"]
                rows = conn.execute(
                    f"SELECT {columns} FROM retention_runs ORDER BY started_at DESC LIMIT {ph} OFFSET {ph}",
                    (limit, offset),
                ).fetchall()
        return [dict(r) for r in rows], total

    def list_deletions(
        self, *, run_id: str | None = None, limit: int = 50, offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        ph = self._placeholder()
        columns = "id, run_id, item_type, item_id, sender_or_author, original_created_at, deleted_at, status, error"
        with self._conn() as conn:
            if run_id:
                total = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM retention_deletions WHERE run_id = {ph}", (run_id,)
                ).fetchone()["cnt"]
                rows = conn.execute(
                    f"SELECT {columns} FROM retention_deletions WHERE run_id = {ph} "
                    f"ORDER BY deleted_at DESC LIMIT {ph} OFFSET {ph}",
                    (run_id, limit, offset),
                ).fetchall()
            else:
                total = conn.execute("SELECT COUNT(*) AS cnt FROM retention_deletions").fetchone()["cnt"]
                rows = conn.execute(
                    f"SELECT {columns} FROM retention_deletions ORDER BY deleted_at DESC LIMIT {ph} OFFSET {ph}",
                    (limit, offset),
                ).fetchall()
        return [dict(r) for r in rows], total


retention_policy_store = RetentionPolicyStore()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_retention_policy_store.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/storage_migrations/0032_retention_policies.sql backend/retention_policy_store.py backend/tests/test_retention_policy_store.py
git commit -m "feat(retention): add retention policy/run/deletion store"
```

---

## Task 5: Delegated Graph client for Teams content

**Files:**
- Create: `backend/retention_graph_client.py`
- Test: `backend/tests/test_retention_graph_client.py`

**Interfaces:**
- Produces: `RetentionGraphError` (exception with `.status_code`), `list_teams(access_token)`, `list_channels(access_token, team_id)`, `list_messages_older_than(access_token, team_id, channel_id, cutoff)`, `list_replies_older_than(access_token, team_id, channel_id, message_id, cutoff)` (each reply dict includes `parent_id`), `delete_message(access_token, team_id, channel_id, message_id)`, `delete_reply(access_token, team_id, channel_id, message_id, reply_id)`, `resolve_team_site_id(access_token, team_id)`, `delete_drive_item(access_token, site_id, drive_item_id)`.
- Each message/reply summary dict shape: `{"id": str, "created_at": str, "sender_or_author": str, "attachments": [{"id": str, "content_url": str}]}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_retention_graph_client.py
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _ok_response(payload):
    resp = MagicMock(ok=True, status_code=200)
    resp.json.return_value = payload
    resp.headers = {}
    return resp


def test_list_teams_follows_next_link():
    page1 = _ok_response({"value": [{"id": "t1", "displayName": "Eng"}], "@odata.nextLink": "https://graph/next"})
    page2 = _ok_response({"value": [{"id": "t2", "displayName": "Ops"}]})
    with patch("retention_graph_client.requests.request", side_effect=[page1, page2]):
        import retention_graph_client as g
        teams = g.list_teams("token")
    assert teams == [{"id": "t1", "name": "Eng"}, {"id": "t2", "name": "Ops"}]


def test_list_messages_older_than_filters_by_cutoff_and_extracts_attachments():
    import retention_graph_client as g
    old_msg = {
        "id": "m1", "createdDateTime": "2025-01-01T00:00:00Z",
        "from": {"user": {"displayName": "Alice"}},
        "attachments": [{"id": "a1", "contentType": "reference", "contentUrl": "https://sp/file1"}],
    }
    new_msg = {"id": "m2", "createdDateTime": "2026-09-01T00:00:00Z", "from": {"user": {"displayName": "Bob"}}, "attachments": []}
    resp = _ok_response({"value": [old_msg, new_msg]})
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with patch("retention_graph_client.requests.request", return_value=resp):
        messages = g.list_messages_older_than("token", "team-1", "chan-1", cutoff)
    assert len(messages) == 1
    assert messages[0]["id"] == "m1"
    assert messages[0]["sender_or_author"] == "Alice"
    assert messages[0]["attachments"] == [{"id": "a1", "content_url": "https://sp/file1"}]


def test_list_replies_older_than_tags_parent_id():
    import retention_graph_client as g
    reply = {"id": "r1", "createdDateTime": "2025-01-01T00:00:00Z", "from": {"user": {"displayName": "Alice"}}, "attachments": []}
    resp = _ok_response({"value": [reply]})
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with patch("retention_graph_client.requests.request", return_value=resp):
        replies = g.list_replies_older_than("token", "team-1", "chan-1", "m1", cutoff)
    assert replies[0]["parent_id"] == "m1"


def test_delete_message_raises_retention_graph_error_on_failure():
    import retention_graph_client as g
    resp = MagicMock(ok=False, status_code=403, text="Forbidden")
    resp.headers = {}
    with patch("retention_graph_client.requests.request", return_value=resp):
        try:
            g.delete_message("token", "team-1", "chan-1", "m1")
            assert False, "expected RetentionGraphError"
        except g.RetentionGraphError as exc:
            assert exc.status_code == 403


def test_request_retries_on_429_then_succeeds(monkeypatch):
    import retention_graph_client as g
    monkeypatch.setattr(g.time, "sleep", lambda _seconds: None)
    throttled = MagicMock(ok=False, status_code=429)
    throttled.headers = {"Retry-After": "1"}
    success = MagicMock(ok=True, status_code=200)
    success.headers = {}
    with patch("retention_graph_client.requests.request", side_effect=[throttled, success]):
        resp = g._request("POST", "https://graph/x", "token")
    assert resp.ok is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_retention_graph_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'retention_graph_client'`

- [ ] **Step 3: Implement `backend/retention_graph_client.py`**

```python
"""Delegated Microsoft Graph calls for Teams retention: read channel content
and delete aged messages/replies/attachments. Every call here uses a
delegated access token — Graph has no supported application-permission path
for deleting channel messages."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import requests

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_MAX_RETRIES = 3


class RetentionGraphError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _request(method: str, url: str, access_token: str, **kwargs: Any) -> requests.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = None
    for attempt in range(_MAX_RETRIES):
        resp = requests.request(method, url, headers=headers, timeout=(10, 30), **kwargs)
        if resp.status_code != 429:
            return resp
        if attempt == _MAX_RETRIES - 1:
            return resp
        retry_after = int(resp.headers.get("Retry-After") or (2 ** attempt))
        time.sleep(retry_after)
    return resp  # type: ignore[return-value]


def _get_all_pages(url: str, access_token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    next_url: str | None = url
    while next_url:
        resp = _request("GET", next_url, access_token)
        if not resp.ok:
            raise RetentionGraphError(
                f"Graph GET {next_url} failed: {resp.status_code} {resp.text[:300]}", status_code=resp.status_code,
            )
        payload = resp.json()
        items.extend(payload.get("value") or [])
        next_url = payload.get("@odata.nextLink")
    return items


def list_teams(access_token: str) -> list[dict[str, Any]]:
    raw = _get_all_pages(f"{_GRAPH_BASE}/teams", access_token)
    return [{"id": t["id"], "name": t.get("displayName", "")} for t in raw]


def list_channels(access_token: str, team_id: str) -> list[dict[str, Any]]:
    raw = _get_all_pages(f"{_GRAPH_BASE}/teams/{team_id}/channels", access_token)
    return [{"id": c["id"], "name": c.get("displayName", "")} for c in raw]


def _message_summary(raw: dict[str, Any]) -> dict[str, Any]:
    attachments = [
        {"id": a.get("id", ""), "content_url": a.get("contentUrl", "")}
        for a in (raw.get("attachments") or [])
        if a.get("contentType") == "reference" and a.get("contentUrl")
    ]
    from_user = (raw.get("from") or {}).get("user") or {}
    return {
        "id": raw["id"],
        "created_at": raw.get("createdDateTime", ""),
        "sender_or_author": from_user.get("displayName", ""),
        "attachments": attachments,
    }


def _is_older_than(raw: dict[str, Any], cutoff: datetime) -> bool:
    created = raw.get("createdDateTime")
    if not created:
        return False
    return datetime.fromisoformat(created.replace("Z", "+00:00")) < cutoff


def list_messages_older_than(
    access_token: str, team_id: str, channel_id: str, cutoff: datetime,
) -> list[dict[str, Any]]:
    raw = _get_all_pages(f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages", access_token)
    return [_message_summary(m) for m in raw if _is_older_than(m, cutoff)]


def list_replies_older_than(
    access_token: str, team_id: str, channel_id: str, message_id: str, cutoff: datetime,
) -> list[dict[str, Any]]:
    raw = _get_all_pages(
        f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies", access_token,
    )
    replies = [_message_summary(r) for r in raw if _is_older_than(r, cutoff)]
    for reply in replies:
        reply["parent_id"] = message_id
    return replies


def delete_message(access_token: str, team_id: str, channel_id: str, message_id: str) -> None:
    url = f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages/{message_id}/softDelete"
    resp = _request("POST", url, access_token)
    if not resp.ok:
        raise RetentionGraphError(
            f"Delete message {message_id} failed: {resp.status_code} {resp.text[:300]}", status_code=resp.status_code,
        )


def delete_reply(access_token: str, team_id: str, channel_id: str, message_id: str, reply_id: str) -> None:
    url = f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies/{reply_id}/softDelete"
    resp = _request("POST", url, access_token)
    if not resp.ok:
        raise RetentionGraphError(
            f"Delete reply {reply_id} failed: {resp.status_code} {resp.text[:300]}", status_code=resp.status_code,
        )


def resolve_team_site_id(access_token: str, team_id: str) -> str:
    resp = _request("GET", f"{_GRAPH_BASE}/groups/{team_id}/sites/root?$select=id", access_token)
    if not resp.ok:
        raise RetentionGraphError(
            f"Resolve site for team {team_id} failed: {resp.status_code} {resp.text[:300]}", status_code=resp.status_code,
        )
    return resp.json()["id"]


def delete_drive_item(access_token: str, site_id: str, drive_item_id: str) -> None:
    url = f"{_GRAPH_BASE}/sites/{site_id}/drive/items/{drive_item_id}"
    resp = _request("DELETE", url, access_token)
    if not resp.ok and resp.status_code != 404:
        raise RetentionGraphError(
            f"Delete drive item {drive_item_id} failed: {resp.status_code} {resp.text[:300]}", status_code=resp.status_code,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_retention_graph_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/retention_graph_client.py backend/tests/test_retention_graph_client.py
git commit -m "feat(retention): add delegated Graph client for Teams content"
```

---

## Task 6: Retention cleanup job (preview + hourly enforcement)

**Files:**
- Create: `backend/retention_cleanup_job.py`
- Test: `backend/tests/test_retention_cleanup_job.py`

**Interfaces:**
- Consumes: `retention_graph_connection.RetentionGraphConnectionError`, `retention_graph_connection.retention_graph_connection` (Task 3); `retention_policy_store.retention_policy_store` (Task 4); `retention_graph_client` module functions (Task 5).
- Produces: `RetentionCleanupJob` class with constructor `__init__(self, *, connection_store=None, policy_store=None, graph_module=None)` (dependency injection for tests), `async def compute_preview(self, policy_id) -> dict`, `async def run_cycle(self) -> None`, `start_background_runner()`, `stop_background_runner()`; module singleton `retention_cleanup_job`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_retention_cleanup_job.py
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _job_with_stores():
    from retention_cleanup_job import RetentionCleanupJob
    from retention_policy_store import RetentionPolicyStore
    policy_store = RetentionPolicyStore(db_path=tempfile.mktemp(suffix=".db"))
    connection_store = MagicMock()
    connection_store.get_valid_token.return_value = "token"
    graph_module = MagicMock()
    job = RetentionCleanupJob(connection_store=connection_store, policy_store=policy_store, graph_module=graph_module)
    return job, policy_store, connection_store, graph_module


async def test_compute_preview_counts_messages_and_replies():
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    graph_module.list_messages_older_than.return_value = [
        {"id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice", "attachments": [{"id": "a1", "content_url": "u"}]},
    ]
    graph_module.list_replies_older_than.return_value = []

    preview = await job.compute_preview(policy["id"])

    assert preview["messages_count"] == 1
    assert preview["attachments_count"] == 1
    assert preview["oldest_message_at"] == "2025-01-01T00:00:00Z"


async def test_run_cycle_skips_when_no_active_policies():
    job, _policy_store, connection_store, graph_module = _job_with_stores()
    await job.run_cycle()
    connection_store.get_valid_token.assert_not_called()
    graph_module.list_messages_older_than.assert_not_called()


async def test_run_cycle_deletes_messages_and_records_run():
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = [
        {"id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice", "attachments": []},
    ]
    graph_module.list_replies_older_than.return_value = []

    await job.run_cycle()

    runs, total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert total == 1
    assert runs[0]["outcome"] == "ok"
    assert runs[0]["messages_deleted"] == 1
    graph_module.delete_message.assert_called_once_with("token", "team-1", "chan-1", "m1")


async def test_run_cycle_records_partial_when_one_message_delete_fails():
    job, policy_store, _connection_store, graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    graph_module.list_messages_older_than.return_value = [
        {"id": "m1", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Alice", "attachments": []},
        {"id": "m2", "created_at": "2025-01-01T00:00:00Z", "sender_or_author": "Bob", "attachments": []},
    ]
    graph_module.list_replies_older_than.return_value = []
    graph_module.delete_message.side_effect = [None, RuntimeError("boom")]

    await job.run_cycle()

    runs, _total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert runs[0]["outcome"] == "partial"
    assert runs[0]["messages_deleted"] == 1
    deletions, _total = policy_store.list_deletions(run_id=runs[0]["id"], limit=10, offset=0)
    statuses = {d["item_id"]: d["status"] for d in deletions}
    assert statuses == {"m1": "deleted", "m2": "failed"}


async def test_run_cycle_marks_all_active_policies_failed_when_token_invalid():
    from retention_graph_connection import RetentionGraphConnectionError
    job, policy_store, connection_store, _graph_module = _job_with_stores()
    policy = policy_store.create_policy(
        team_id="team-1", team_name="Eng", channel_id="chan-1", channel_name="General",
        retention_days=30, created_by="ops@example.com",
    )
    policy_store.confirm_policy(policy["id"])
    connection_store.get_valid_token.side_effect = RetentionGraphConnectionError("disconnected")

    await job.run_cycle()

    runs, total = policy_store.list_runs(policy_id=policy["id"], limit=10, offset=0)
    assert total == 1
    assert runs[0]["outcome"] == "failed"
    assert runs[0]["error"] == "token_invalid"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_retention_cleanup_job.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'retention_cleanup_job'`

- [ ] **Step 3: Implement `backend/retention_cleanup_job.py`**

```python
"""Hourly leader-only background job enforcing per-channel Teams message
retention: deletes aged messages/replies (delegated Graph call) and their
attachments (SharePoint driveItem) for every 'active' policy. Also exposes
compute_preview(), reused synchronously by the API's dry-run step so preview
and enforcement can never drift on selection logic."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import retention_graph_client as _graph_module
from retention_graph_connection import RetentionGraphConnectionError, retention_graph_connection
from retention_policy_store import retention_policy_store

logger = logging.getLogger(__name__)


class RetentionCleanupJob:
    def __init__(self, *, connection_store: Any = None, policy_store: Any = None, graph_module: Any = None) -> None:
        self._connection_store = connection_store or retention_graph_connection
        self._policy_store = policy_store or retention_policy_store
        self._graph = graph_module or _graph_module
        self._bg_task: asyncio.Task | None = None

    async def _collect_items(self, policy: dict, token: str, cutoff: datetime) -> list[tuple[dict, bool]]:
        loop = asyncio.get_event_loop()
        messages = await loop.run_in_executor(
            None, lambda: self._graph.list_messages_older_than(token, policy["team_id"], policy["channel_id"], cutoff),
        )
        items: list[tuple[dict, bool]] = [(m, False) for m in messages]
        for message in messages:
            replies = await loop.run_in_executor(
                None,
                lambda m=message: self._graph.list_replies_older_than(
                    token, policy["team_id"], policy["channel_id"], m["id"], cutoff,
                ),
            )
            items.extend((r, True) for r in replies)
        return items

    async def compute_preview(self, policy_id: str) -> dict[str, Any]:
        policy = self._policy_store.get_policy(policy_id)
        if not policy:
            raise ValueError(f"Unknown policy {policy_id}")
        token = self._connection_store.get_valid_token()
        cutoff = datetime.now(timezone.utc) - timedelta(days=policy["retention_days"])
        items = await self._collect_items(policy, token, cutoff)
        all_items = [item for item, _is_reply in items]
        attachments_count = sum(len(item["attachments"]) for item in all_items)
        oldest = min((item["created_at"] for item in all_items), default=None)
        return {
            "messages_count": len(all_items),
            "attachments_count": attachments_count,
            "oldest_message_at": oldest,
        }

    async def _delete_item(self, item: dict, is_reply: bool, policy: dict, token: str) -> None:
        loop = asyncio.get_event_loop()
        if is_reply:
            await loop.run_in_executor(
                None,
                lambda: self._graph.delete_reply(
                    token, policy["team_id"], policy["channel_id"], item["parent_id"], item["id"],
                ),
            )
        else:
            await loop.run_in_executor(
                None, lambda: self._graph.delete_message(token, policy["team_id"], policy["channel_id"], item["id"]),
            )

    async def _delete_attachments(self, item: dict, policy: dict, token: str, run_id: str) -> tuple[int, bool]:
        loop = asyncio.get_event_loop()
        deleted = 0
        had_failure = False
        for attachment in item["attachments"]:
            try:
                site_id = await loop.run_in_executor(
                    None, lambda: self._graph.resolve_team_site_id(token, policy["team_id"]),
                )
                await loop.run_in_executor(
                    None, lambda: self._graph.delete_drive_item(token, site_id, attachment["id"]),
                )
                self._policy_store.record_deletion(
                    run_id=run_id, item_type="attachment", item_id=attachment["id"],
                    sender_or_author=item["sender_or_author"], original_created_at=item["created_at"], status="deleted",
                )
                deleted += 1
            except Exception as exc:
                had_failure = True
                self._policy_store.record_deletion(
                    run_id=run_id, item_type="attachment", item_id=attachment["id"],
                    sender_or_author=item["sender_or_author"], original_created_at=item["created_at"],
                    status="failed", error=str(exc),
                )
        return deleted, had_failure

    async def _run_policy(self, policy: dict, token: str) -> None:
        run_id = self._policy_store.start_run(policy["id"])
        cutoff = datetime.now(timezone.utc) - timedelta(days=policy["retention_days"])
        messages_deleted = 0
        attachments_deleted = 0
        had_failure = False

        try:
            items = await self._collect_items(policy, token, cutoff)
        except Exception as exc:
            logger.exception("Retention job: failed to list content for policy %s", policy["id"])
            self._policy_store.finish_run(run_id, outcome="failed", messages_deleted=0, attachments_deleted=0, error=str(exc))
            return

        for item, is_reply in items:
            try:
                await self._delete_item(item, is_reply, policy, token)
            except Exception as exc:
                had_failure = True
                self._policy_store.record_deletion(
                    run_id=run_id, item_type="message", item_id=item["id"],
                    sender_or_author=item["sender_or_author"], original_created_at=item["created_at"],
                    status="failed", error=str(exc),
                )
                continue
            self._policy_store.record_deletion(
                run_id=run_id, item_type="message", item_id=item["id"],
                sender_or_author=item["sender_or_author"], original_created_at=item["created_at"], status="deleted",
            )
            messages_deleted += 1
            deleted, attachment_failure = await self._delete_attachments(item, policy, token, run_id)
            attachments_deleted += deleted
            had_failure = had_failure or attachment_failure

        outcome = "partial" if had_failure else "ok"
        self._policy_store.finish_run(
            run_id, outcome=outcome, messages_deleted=messages_deleted, attachments_deleted=attachments_deleted,
        )

    async def run_cycle(self) -> None:
        policies = self._policy_store.list_active_policies()
        if not policies:
            return
        try:
            token = self._connection_store.get_valid_token()
        except RetentionGraphConnectionError as exc:
            logger.warning("Retention job: no valid Graph token, skipping cycle: %s", exc)
            for policy in policies:
                run_id = self._policy_store.start_run(policy["id"])
                self._policy_store.finish_run(
                    run_id, outcome="failed", messages_deleted=0, attachments_deleted=0, error="token_invalid",
                )
            return
        for policy in policies:
            await self._run_policy(policy, token)

    def start_background_runner(self) -> None:
        loop = asyncio.get_event_loop()
        self._bg_task = loop.create_task(self._run_loop())

    def stop_background_runner(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_cycle()
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Retention cleanup job loop error")
                await asyncio.sleep(3600)


retention_cleanup_job = RetentionCleanupJob()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_retention_cleanup_job.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/retention_cleanup_job.py backend/tests/test_retention_cleanup_job.py
git commit -m "feat(retention): add hourly retention cleanup job with preview support"
```

---

## Task 7: Retention API routes

**Files:**
- Create: `backend/routes_retention.py`
- Test: `backend/tests/test_routes_retention.py`

**Interfaces:**
- Consumes: `auth.oauth`, `auth.require_retention_access` (Task 2); `retention_graph_connection.retention_graph_connection`, `.RetentionGraphConnectionError`, `.retention_graph_oauth_configured` (Task 3); `retention_policy_store.retention_policy_store` (Task 4); `retention_graph_client.list_teams`/`list_channels` (Task 5); `retention_cleanup_job.retention_cleanup_job` (Task 6); `routes_auth._oauth_redirect_uri` (existing helper, reused rather than duplicated).
- Produces: `router` (FastAPI `APIRouter`, prefix `/api/retention`) with routes: `GET /connection/status`, `GET /connection/connect`, `GET /connection/callback` (name=`retention_graph_callback`), `GET /teams`, `GET /teams/{team_id}/channels`, `POST /policies`, `GET /policies`, `GET /policies/{policy_id}/preview`, `POST /policies/{policy_id}/confirm`, `PATCH /policies/{policy_id}`, `GET /runs`, `GET /deletions`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_routes_retention.py
from __future__ import annotations


def _allow_retention(monkeypatch, email="test@example.com"):
    import auth
    monkeypatch.setattr(auth, "RETENTION_ALLOWED_USERS", email)


def test_connection_status_forbidden_when_not_allowlisted(test_client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "RETENTION_ALLOWED_USERS", "someone-else@example.com")
    resp = test_client.get("/api/retention/connection/status")
    assert resp.status_code == 403


def test_connection_status_disconnected_by_default(test_client, monkeypatch):
    _allow_retention(monkeypatch)
    resp = test_client.get("/api/retention/connection/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "disconnected"


def test_create_policy_rejects_out_of_range_days(test_client, monkeypatch):
    _allow_retention(monkeypatch)
    resp = test_client.post(
        "/api/retention/policies",
        json={"team_id": "t1", "team_name": "Eng", "channel_id": "c1", "channel_name": "General", "retention_days": 400},
    )
    assert resp.status_code == 400


def test_create_then_confirm_policy(test_client, monkeypatch):
    _allow_retention(monkeypatch)
    create_resp = test_client.post(
        "/api/retention/policies",
        json={"team_id": "t1", "team_name": "Eng", "channel_id": "c1", "channel_name": "General", "retention_days": 30},
    )
    assert create_resp.status_code == 200
    policy = create_resp.json()
    assert policy["status"] == "pending_preview"

    confirm_resp = test_client.post(f"/api/retention/policies/{policy['id']}/confirm")
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "active"


def test_create_policy_conflicts_when_channel_already_has_one(test_client, monkeypatch):
    _allow_retention(monkeypatch)
    body = {"team_id": "t1", "team_name": "Eng", "channel_id": "c1", "channel_name": "General", "retention_days": 30}
    first = test_client.post("/api/retention/policies", json=body)
    assert first.status_code == 200
    second = test_client.post("/api/retention/policies", json=body)
    assert second.status_code == 409


def test_patch_policy_retention_days_resets_status(test_client, monkeypatch):
    _allow_retention(monkeypatch)
    create_resp = test_client.post(
        "/api/retention/policies",
        json={"team_id": "t1", "team_name": "Eng", "channel_id": "c1", "channel_name": "General", "retention_days": 30},
    )
    policy_id = create_resp.json()["id"]
    test_client.post(f"/api/retention/policies/{policy_id}/confirm")

    patch_resp = test_client.patch(f"/api/retention/policies/{policy_id}", json={"retention_days": 60})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "pending_preview"
    assert patch_resp.json()["retention_days"] == 60


def test_list_runs_and_deletions_pagination(test_client, monkeypatch):
    import retention_policy_store as rps_module
    _allow_retention(monkeypatch)
    store = rps_module.retention_policy_store
    policy = store.create_policy(
        team_id="t1", team_name="Eng", channel_id="c1", channel_name="General", retention_days=30, created_by="x",
    )
    run_id = store.start_run(policy["id"])
    store.record_deletion(
        run_id=run_id, item_type="message", item_id="m1", sender_or_author="Alice",
        original_created_at="2026-01-01T00:00:00Z", status="deleted",
    )
    store.finish_run(run_id, outcome="ok", messages_deleted=1, attachments_deleted=0)

    runs_resp = test_client.get(f"/api/retention/runs?policy_id={policy['id']}")
    assert runs_resp.status_code == 200
    assert runs_resp.json()["total"] == 1

    deletions_resp = test_client.get(f"/api/retention/deletions?run_id={run_id}")
    assert deletions_resp.status_code == 200
    assert deletions_resp.json()["total"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_routes_retention.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routes_retention'` (and the app doesn't yet expose `/api/retention/*`)

- [ ] **Step 3: Implement `backend/routes_retention.py`**

```python
"""FastAPI routes for the Teams retention workspace (retention.movedocs.com)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from auth import oauth, require_retention_access
from retention_cleanup_job import retention_cleanup_job
from retention_graph_client import list_channels as _list_channels, list_teams as _list_teams
from retention_graph_connection import (
    RetentionGraphConnectionError,
    retention_graph_connection,
    retention_graph_oauth_configured,
)
from retention_policy_store import retention_policy_store
from routes_auth import _oauth_redirect_uri

router = APIRouter(prefix="/api/retention", tags=["retention"])

_VALID_STATUSES = {"active", "disabled", "pending_preview"}


class CreatePolicyRequest(BaseModel):
    team_id: str
    team_name: str
    channel_id: str
    channel_name: str
    retention_days: int


class UpdatePolicyRequest(BaseModel):
    retention_days: int | None = None
    status: str | None = None


@router.get("/connection/status", dependencies=[Depends(require_retention_access)])
async def connection_status() -> dict[str, Any]:
    return retention_graph_connection.get_status()


@router.get("/connection/connect", dependencies=[Depends(require_retention_access)])
async def connection_connect(request: Request):
    if not retention_graph_oauth_configured():
        raise HTTPException(status_code=500, detail="Retention Graph OAuth is not configured")
    client = oauth.create_client("retention_graph")
    if not client:
        raise HTTPException(status_code=500, detail="Retention Graph OAuth is not configured")
    redirect_uri = _oauth_redirect_uri(request, "retention_graph_callback")
    return await client.authorize_redirect(request, redirect_uri, prompt="select_account")


@router.get("/connection/callback", name="retention_graph_callback")
async def connection_callback(request: Request, session: dict[str, Any] = Depends(require_retention_access)):
    client = oauth.create_client("retention_graph")
    if not client:
        raise HTTPException(status_code=500, detail="Retention Graph OAuth is not configured")
    token = await client.authorize_access_token(request)
    access_token = str(token.get("access_token") or "").strip()
    refresh_token = str(token.get("refresh_token") or "").strip()
    expires_in = int(token.get("expires_in") or 3600)
    if not access_token or not refresh_token:
        raise HTTPException(status_code=400, detail="Retention Graph OAuth response was missing required tokens")
    userinfo = token.get("userinfo") or {}
    service_account_upn = str(userinfo.get("preferred_username") or userinfo.get("email") or "")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(expires_in - 60, 60))
    retention_graph_connection.save_connection(
        service_account_upn=service_account_upn,
        refresh_token=refresh_token,
        access_token=access_token,
        access_token_expires_at=expires_at,
        connected_by=str(session.get("email") or ""),
    )
    return RedirectResponse(url="/")


@router.get("/teams", dependencies=[Depends(require_retention_access)])
async def get_teams(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    token = retention_graph_connection.get_valid_token()
    teams = _list_teams(token)
    active_by_team: dict[str, int] = {}
    for policy in retention_policy_store.list_active_policies():
        active_by_team[policy["team_id"]] = active_by_team.get(policy["team_id"], 0) + 1
    for team in teams:
        team["policy_count"] = active_by_team.get(team["id"], 0)
    return {"items": teams[offset : offset + limit], "total": len(teams)}


@router.get("/teams/{team_id}/channels", dependencies=[Depends(require_retention_access)])
async def get_channels(
    team_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    token = retention_graph_connection.get_valid_token()
    channels = _list_channels(token, team_id)
    for channel in channels:
        channel["policy"] = retention_policy_store.get_policy_for_channel(team_id, channel["id"])
    return {"items": channels[offset : offset + limit], "total": len(channels)}


@router.post("/policies", dependencies=[Depends(require_retention_access)])
async def create_policy(
    body: CreatePolicyRequest, session: dict[str, Any] = Depends(require_retention_access),
) -> dict[str, Any]:
    if not 1 <= body.retention_days <= 365:
        raise HTTPException(status_code=400, detail="retention_days must be between 1 and 365")
    if retention_policy_store.get_policy_for_channel(body.team_id, body.channel_id):
        raise HTTPException(status_code=409, detail="A policy already exists for this channel")
    return retention_policy_store.create_policy(
        team_id=body.team_id, team_name=body.team_name, channel_id=body.channel_id,
        channel_name=body.channel_name, retention_days=body.retention_days,
        created_by=str(session.get("email") or ""),
    )


@router.get("/policies", dependencies=[Depends(require_retention_access)])
async def list_policies(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    items, total = retention_policy_store.list_policies(limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/policies/{policy_id}/preview", dependencies=[Depends(require_retention_access)])
async def preview_policy(policy_id: str) -> dict[str, Any]:
    try:
        return await retention_cleanup_job.compute_preview(policy_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RetentionGraphConnectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/policies/{policy_id}/confirm", dependencies=[Depends(require_retention_access)])
async def confirm_policy(policy_id: str) -> dict[str, Any]:
    policy = retention_policy_store.confirm_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


@router.patch("/policies/{policy_id}", dependencies=[Depends(require_retention_access)])
async def update_policy(policy_id: str, body: UpdatePolicyRequest) -> dict[str, Any]:
    if body.retention_days is not None and not 1 <= body.retention_days <= 365:
        raise HTTPException(status_code=400, detail="retention_days must be between 1 and 365")
    if body.status is not None and body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    policy = retention_policy_store.update_policy(policy_id, retention_days=body.retention_days, status=body.status)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


@router.get("/runs", dependencies=[Depends(require_retention_access)])
async def list_runs(
    policy_id: str | None = None, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items, total = retention_policy_store.list_runs(policy_id=policy_id, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/deletions", dependencies=[Depends(require_retention_access)])
async def list_deletions(
    run_id: str | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items, total = retention_policy_store.list_deletions(run_id=run_id, limit=limit, offset=offset)
    return {"items": items, "total": total}
```

- [ ] **Step 4: Register the router so `test_client` can reach it**

The `test_client` fixture builds the app from `main.py`, so `/api/retention/*` won't resolve until the router is included. Add this now (the rest of Task 8's `main.py` wiring — background job start/stop — can follow in the next task, but the router include must land here for these tests to pass):

In `backend/main.py`, add the import near the other route imports:

```python
from routes_retention import router as retention_router
```

Add near the other `app.include_router(...)` calls (after `app.include_router(tools_router)`):

```python
app.include_router(retention_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_routes_retention.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/routes_retention.py backend/tests/test_routes_retention.py backend/main.py
git commit -m "feat(retention): add retention API routes"
```

---

## Task 8: Wire the cleanup job into leader-only startup/shutdown

**Files:**
- Modify: `backend/main.py` (import block near line 56; `_start_deferred_services` near line 153; `_stop_leader_services` near line 208)

**Interfaces:**
- Consumes: `retention_cleanup_job.retention_cleanup_job` (Task 6).

- [ ] **Step 1: Implement**

Add the import near the other job singleton imports (alongside the existing `from quarantine_release_job import quarantine_release_job as _quarantine_release_job`):

```python
from retention_cleanup_job import retention_cleanup_job as _retention_cleanup_job
```

In `_start_deferred_services`, add alongside the other `try/except` starters (after the `_quarantine_release_job.start_background_runner()` block):

```python
    try:
        _retention_cleanup_job.start_background_runner()
    except Exception:
        logger.exception("Failed to start retention cleanup job")
```

In `_stop_leader_services`, add alongside the other stop calls (after `_quarantine_release_job.stop_background_runner()`):

```python
    _retention_cleanup_job.stop_background_runner()
```

- [ ] **Step 2: Verify the app still starts cleanly**

Run: `cd backend && python -c "import main"`
Expected: No exceptions — the module imports and registers the app without starting the event loop.

- [ ] **Step 3: Run the full backend retention test suite to confirm no regressions**

Run: `cd backend && pytest tests/test_site_context.py tests/test_auth.py tests/test_retention_graph_connection.py tests/test_retention_policy_store.py tests/test_retention_graph_client.py tests/test_retention_cleanup_job.py tests/test_routes_retention.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(retention): start/stop the retention cleanup job as a leader-only service"
```

---

## Task 9: Frontend API client (types + functions)

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Produces types: `RetentionConnectionStatus`, `RetentionTeam`, `RetentionPolicySummary`, `RetentionChannel`, `RetentionPreview`, `RetentionRun`, `RetentionDeletion`.
- Produces `api.*` functions: `getRetentionConnectionStatus`, `getRetentionTeams`, `getRetentionChannels`, `createRetentionPolicy`, `getRetentionPolicyPreview`, `confirmRetentionPolicy`, `patchRetentionPolicy`, `getRetentionPolicies`, `getRetentionRuns`, `getRetentionDeletions`.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/__tests__/api.retention.test.ts
import { describe, expect, it, vi, beforeEach } from "vitest";
import { api } from "../lib/api.ts";

describe("retention API client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("getRetentionConnectionStatus fetches the status endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: null, last_error: null }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.getRetentionConnectionStatus();

    expect(fetchMock).toHaveBeenCalledWith("/api/retention/connection/status", expect.anything());
    expect(result.status).toBe("connected");
  });

  it("createRetentionPolicy posts the body and returns the created policy", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: "p1", team_id: "t1", team_name: "Eng", channel_id: "c1", channel_name: "General",
        retention_days: 30, status: "pending_preview", created_by: "x", created_at: "now", updated_at: "now",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.createRetentionPolicy({
      team_id: "t1", team_name: "Eng", channel_id: "c1", channel_name: "General", retention_days: 30,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/retention/policies",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.status).toBe("pending_preview");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:run -- api.retention`
Expected: FAIL — `api.getRetentionConnectionStatus is not a function`

- [ ] **Step 3: Implement**

Find the `QuarantineRelease*` interfaces near the end of `frontend/src/lib/api.ts` (around line 5549) and add these new interfaces after them:

```typescript
export interface RetentionConnectionStatus {
  status: "connected" | "disconnected";
  service_account_upn: string;
  last_refreshed_at: string | null;
  last_error: string | null;
}

export interface RetentionTeam {
  id: string;
  name: string;
  policy_count: number;
}

export interface RetentionPolicySummary {
  id: string;
  team_id: string;
  team_name: string;
  channel_id: string;
  channel_name: string;
  retention_days: number;
  status: "pending_preview" | "active" | "disabled";
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface RetentionChannel {
  id: string;
  name: string;
  policy: RetentionPolicySummary | null;
}

export interface RetentionPreview {
  messages_count: number;
  attachments_count: number;
  oldest_message_at: string | null;
}

export interface RetentionRun {
  id: string;
  policy_id: string;
  started_at: string;
  finished_at: string | null;
  outcome: "running" | "ok" | "partial" | "failed";
  messages_deleted: number;
  attachments_deleted: number;
  error: string | null;
}

export interface RetentionDeletion {
  id: string;
  run_id: string;
  item_type: "message" | "attachment";
  item_id: string;
  sender_or_author: string;
  original_created_at: string;
  deleted_at: string;
  status: "deleted" | "failed";
  error: string | null;
}
```

Find the `patchQuarantineReleaseSettings` method inside the `api` object (around line 5200-5216) and add these methods immediately after it:

```typescript
  getRetentionConnectionStatus(): Promise<RetentionConnectionStatus> {
    return fetchJSON<RetentionConnectionStatus>("/api/retention/connection/status");
  },

  getRetentionTeams(limit = 50, offset = 0): Promise<{ items: RetentionTeam[]; total: number }> {
    return fetchJSON(`/api/retention/teams?limit=${limit}&offset=${offset}`);
  },

  getRetentionChannels(
    teamId: string, limit = 50, offset = 0,
  ): Promise<{ items: RetentionChannel[]; total: number }> {
    return fetchJSON(`/api/retention/teams/${encodeURIComponent(teamId)}/channels?limit=${limit}&offset=${offset}`);
  },

  async createRetentionPolicy(body: {
    team_id: string; team_name: string; channel_id: string; channel_name: string; retention_days: number;
  }): Promise<RetentionPolicySummary> {
    const res = await fetch("/api/retention/policies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.status === 401) {
      window.location.href = "/api/auth/login";
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      throw new Error(await buildErrorMessage("POST", "/api/retention/policies", res));
    }
    return res.json() as Promise<RetentionPolicySummary>;
  },

  getRetentionPolicyPreview(policyId: string): Promise<RetentionPreview> {
    return fetchJSON(`/api/retention/policies/${encodeURIComponent(policyId)}/preview`);
  },

  async confirmRetentionPolicy(policyId: string): Promise<RetentionPolicySummary> {
    const res = await fetch(`/api/retention/policies/${encodeURIComponent(policyId)}/confirm`, { method: "POST" });
    if (res.status === 401) {
      window.location.href = "/api/auth/login";
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      throw new Error(await buildErrorMessage("POST", "/api/retention/policies/confirm", res));
    }
    return res.json() as Promise<RetentionPolicySummary>;
  },

  async patchRetentionPolicy(
    policyId: string, body: { retention_days?: number; status?: string },
  ): Promise<RetentionPolicySummary> {
    const res = await fetch(`/api/retention/policies/${encodeURIComponent(policyId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.status === 401) {
      window.location.href = "/api/auth/login";
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      throw new Error(await buildErrorMessage("PATCH", `/api/retention/policies/${policyId}`, res));
    }
    return res.json() as Promise<RetentionPolicySummary>;
  },

  getRetentionPolicies(limit = 50, offset = 0): Promise<{ items: RetentionPolicySummary[]; total: number }> {
    return fetchJSON(`/api/retention/policies?limit=${limit}&offset=${offset}`);
  },

  getRetentionRuns(
    policyId?: string, limit = 30, offset = 0,
  ): Promise<{ items: RetentionRun[]; total: number }> {
    const policyParam = policyId ? `&policy_id=${encodeURIComponent(policyId)}` : "";
    return fetchJSON(`/api/retention/runs?limit=${limit}&offset=${offset}${policyParam}`);
  },

  getRetentionDeletions(
    runId?: string, limit = 50, offset = 0,
  ): Promise<{ items: RetentionDeletion[]; total: number }> {
    const runParam = runId ? `&run_id=${encodeURIComponent(runId)}` : "";
    return fetchJSON(`/api/retention/deletions?limit=${limit}&offset=${offset}${runParam}`);
  },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test:run -- api.retention`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/__tests__/api.retention.test.ts
git commit -m "feat(retention): add retention API client types and functions"
```

---

## Task 10: RetentionTeamsPage (browse + configure + preview/confirm)

**Files:**
- Create: `frontend/src/pages/RetentionTeamsPage.tsx`
- Test: `frontend/src/__tests__/RetentionTeamsPage.test.tsx`

**Interfaces:**
- Consumes: `api.getRetentionConnectionStatus`, `api.getRetentionTeams`, `api.getRetentionChannels`, `api.createRetentionPolicy`, `api.getRetentionPolicyPreview`, `api.confirmRetentionPolicy` (Task 9).
- Produces: default-exported React component `RetentionTeamsPage`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/RetentionTeamsPage.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import RetentionTeamsPage from "../pages/RetentionTeamsPage.tsx";
import { api } from "../lib/api.ts";

vi.mock("../lib/api.ts", () => ({
  api: {
    getRetentionConnectionStatus: vi.fn(),
    getRetentionTeams: vi.fn(),
    getRetentionChannels: vi.fn(),
    createRetentionPolicy: vi.fn(),
    getRetentionPolicyPreview: vi.fn(),
    confirmRetentionPolicy: vi.fn(),
  },
}));

function renderWithClient() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <RetentionTeamsPage />
    </QueryClientProvider>,
  );
}

describe("RetentionTeamsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a connect banner when the service account is disconnected", async () => {
    (api.getRetentionConnectionStatus as any).mockResolvedValue({
      status: "disconnected", service_account_upn: "", last_refreshed_at: null, last_error: "not set up",
    });

    renderWithClient();

    await waitFor(() => expect(screen.getByText(/Service account not connected/i)).toBeInTheDocument());
  });

  it("lists teams and channels, then previews and confirms a new policy", async () => {
    (api.getRetentionConnectionStatus as any).mockResolvedValue({
      status: "connected", service_account_upn: "bot@x.com", last_refreshed_at: "now", last_error: null,
    });
    (api.getRetentionTeams as any).mockResolvedValue({ items: [{ id: "t1", name: "Engineering", policy_count: 0 }], total: 1 });
    (api.getRetentionChannels as any).mockResolvedValue({
      items: [{ id: "c1", name: "General", policy: null }], total: 1,
    });
    (api.createRetentionPolicy as any).mockResolvedValue({
      id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
      retention_days: 30, status: "pending_preview", created_by: "x", created_at: "now", updated_at: "now",
    });
    (api.getRetentionPolicyPreview as any).mockResolvedValue({ messages_count: 5, attachments_count: 1, oldest_message_at: "2026-01-01" });
    (api.confirmRetentionPolicy as any).mockResolvedValue({
      id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
      retention_days: 30, status: "active", created_by: "x", created_at: "now", updated_at: "now",
    });

    renderWithClient();

    fireEvent.click(await screen.findByText("Engineering"));
    fireEvent.click(await screen.findByText("Configure retention"));
    fireEvent.click(screen.getByText("Preview"));

    await waitFor(() => expect(screen.getByText(/approximately/i)).toBeInTheDocument());
    expect(screen.getByText(/5/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Confirm & Enable"));

    await waitFor(() => expect(api.confirmRetentionPolicy).toHaveBeenCalledWith("p1"));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:run -- RetentionTeamsPage`
Expected: FAIL — `Failed to resolve import "../pages/RetentionTeamsPage.tsx"`

- [ ] **Step 3: Implement `frontend/src/pages/RetentionTeamsPage.tsx`**

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type RetentionChannel, type RetentionTeam } from "../lib/api.ts";

export default function RetentionTeamsPage() {
  const queryClient = useQueryClient();
  const [expandedTeamId, setExpandedTeamId] = useState<string | null>(null);
  const [configuringChannel, setConfiguringChannel] = useState<{ team: RetentionTeam; channel: RetentionChannel } | null>(null);
  const [days, setDays] = useState(30);
  const [previewPolicyId, setPreviewPolicyId] = useState<string | null>(null);

  const statusQuery = useQuery({
    queryKey: ["retention", "connection-status"],
    queryFn: () => api.getRetentionConnectionStatus(),
  });

  const teamsQuery = useQuery({
    queryKey: ["retention", "teams"],
    queryFn: () => api.getRetentionTeams(100, 0),
    enabled: statusQuery.data?.status === "connected",
  });

  const channelsQuery = useQuery({
    queryKey: ["retention", "channels", expandedTeamId],
    queryFn: () => api.getRetentionChannels(expandedTeamId as string, 100, 0),
    enabled: !!expandedTeamId,
  });

  const createMutation = useMutation({
    mutationFn: (input: { team: RetentionTeam; channel: RetentionChannel; retentionDays: number }) =>
      api.createRetentionPolicy({
        team_id: input.team.id,
        team_name: input.team.name,
        channel_id: input.channel.id,
        channel_name: input.channel.name,
        retention_days: input.retentionDays,
      }),
    onSuccess: (policy) => {
      setPreviewPolicyId(policy.id);
      queryClient.invalidateQueries({ queryKey: ["retention", "channels", expandedTeamId] });
    },
  });

  const previewQuery = useQuery({
    queryKey: ["retention", "preview", previewPolicyId],
    queryFn: () => api.getRetentionPolicyPreview(previewPolicyId as string),
    enabled: !!previewPolicyId,
  });

  const confirmMutation = useMutation({
    mutationFn: (policyId: string) => api.confirmRetentionPolicy(policyId),
    onSuccess: () => {
      setConfiguringChannel(null);
      setPreviewPolicyId(null);
      queryClient.invalidateQueries({ queryKey: ["retention", "channels", expandedTeamId] });
    },
  });

  if (statusQuery.data && statusQuery.data.status !== "connected") {
    return (
      <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-800">
        <p className="font-medium">Service account not connected</p>
        <p className="mt-1">
          {statusQuery.data.last_error || "Connect the retention service account to browse Teams and channels."}
        </p>
        <a href="/api/retention/connection/connect" className="mt-2 inline-block rounded bg-amber-600 px-3 py-1.5 text-white">
          Connect service account
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Teams &amp; Channels</h1>
      <div className="divide-y divide-slate-200 rounded-md border border-slate-200">
        {(teamsQuery.data?.items ?? []).map((team) => (
          <div key={team.id}>
            <button
              onClick={() => setExpandedTeamId(expandedTeamId === team.id ? null : team.id)}
              className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium hover:bg-slate-50"
            >
              <span>{team.name}</span>
              <span className="text-xs text-slate-500">
                {team.policy_count} active polic{team.policy_count === 1 ? "y" : "ies"}
              </span>
            </button>
            {expandedTeamId === team.id && (
              <div className="divide-y divide-slate-100 bg-slate-50 px-4">
                {(channelsQuery.data?.items ?? []).map((channel) => (
                  <div key={channel.id} className="flex items-center justify-between py-2 text-sm">
                    <span>{channel.name}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-500">
                        {channel.policy ? `${channel.policy.status}, ${channel.policy.retention_days}d` : "No policy"}
                      </span>
                      {!channel.policy && (
                        <button
                          onClick={() => setConfiguringChannel({ team, channel })}
                          className="rounded bg-blue-600 px-2 py-1 text-xs text-white"
                        >
                          Configure retention
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {configuringChannel && (
        <div className="rounded-md border border-slate-300 bg-white p-4 shadow-sm">
          <h2 className="text-sm font-semibold">
            Configure retention for {configuringChannel.channel.name} ({configuringChannel.team.name})
          </h2>
          {!previewPolicyId ? (
            <div className="mt-3 flex items-center gap-2">
              <label className="text-sm">Retain messages for</label>
              <input
                type="number"
                min={1}
                max={365}
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                className="w-20 rounded border border-slate-300 px-2 py-1 text-sm"
              />
              <span className="text-sm">days</span>
              <button
                onClick={() =>
                  createMutation.mutate({ team: configuringChannel.team, channel: configuringChannel.channel, retentionDays: days })
                }
                disabled={createMutation.isPending}
                className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white"
              >
                Preview
              </button>
            </div>
          ) : (
            <div className="mt-3 space-y-2 text-sm">
              {previewQuery.isLoading ? (
                <p>Computing preview...</p>
              ) : (
                <>
                  <p>
                    This will delete approximately <strong>{previewQuery.data?.messages_count ?? 0}</strong> message(s) and{" "}
                    <strong>{previewQuery.data?.attachments_count ?? 0}</strong> attachment(s) older than {days} days
                    {previewQuery.data?.oldest_message_at ? `, oldest dated ${previewQuery.data.oldest_message_at}` : ""}.
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => confirmMutation.mutate(previewPolicyId)}
                      disabled={confirmMutation.isPending}
                      className="rounded bg-red-600 px-3 py-1.5 text-white"
                    >
                      Confirm &amp; Enable
                    </button>
                    <button
                      onClick={() => {
                        setConfiguringChannel(null);
                        setPreviewPolicyId(null);
                      }}
                      className="rounded border border-slate-300 px-3 py-1.5"
                    >
                      Cancel
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test:run -- RetentionTeamsPage`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/RetentionTeamsPage.tsx frontend/src/__tests__/RetentionTeamsPage.test.tsx
git commit -m "feat(retention): add Teams & Channels retention configuration page"
```

---

## Task 11: RetentionHistoryPage (runs + deletions audit)

**Files:**
- Create: `frontend/src/pages/RetentionHistoryPage.tsx`
- Test: `frontend/src/__tests__/RetentionHistoryPage.test.tsx`

**Interfaces:**
- Consumes: `api.getRetentionPolicies`, `api.getRetentionRuns`, `api.getRetentionDeletions` (Task 9).
- Produces: default-exported React component `RetentionHistoryPage`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/RetentionHistoryPage.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import RetentionHistoryPage from "../pages/RetentionHistoryPage.tsx";
import { api } from "../lib/api.ts";

vi.mock("../lib/api.ts", () => ({
  api: {
    getRetentionPolicies: vi.fn(),
    getRetentionRuns: vi.fn(),
    getRetentionDeletions: vi.fn(),
  },
}));

function renderWithClient() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <RetentionHistoryPage />
    </QueryClientProvider>,
  );
}

describe("RetentionHistoryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getRetentionPolicies as any).mockResolvedValue({
      items: [{
        id: "p1", team_id: "t1", team_name: "Engineering", channel_id: "c1", channel_name: "General",
        retention_days: 30, status: "active", created_by: "x", created_at: "now", updated_at: "now",
      }],
      total: 1,
    });
    (api.getRetentionRuns as any).mockResolvedValue({
      items: [{
        id: "r1", policy_id: "p1", started_at: "2026-09-10T00:00:00Z", finished_at: "2026-09-10T00:01:00Z",
        outcome: "ok", messages_deleted: 3, attachments_deleted: 1, error: null,
      }],
      total: 1,
    });
    (api.getRetentionDeletions as any).mockResolvedValue({
      items: [{
        id: "d1", run_id: "r1", item_type: "message", item_id: "m1", sender_or_author: "Alice",
        original_created_at: "2026-08-01T00:00:00Z", deleted_at: "2026-09-10T00:00:30Z", status: "deleted", error: null,
      }],
      total: 1,
    });
  });

  it("shows run history and drills into deletions for a selected run", async () => {
    renderWithClient();

    await waitFor(() => expect(screen.getByText("2026-09-10T00:00:00Z")).toBeInTheDocument());

    fireEvent.click(screen.getByText("2026-09-10T00:00:00Z"));

    await waitFor(() => expect(api.getRetentionDeletions).toHaveBeenCalledWith("r1", 100, 0));
    expect(await screen.findByText("Alice")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:run -- RetentionHistoryPage`
Expected: FAIL — `Failed to resolve import "../pages/RetentionHistoryPage.tsx"`

- [ ] **Step 3: Implement `frontend/src/pages/RetentionHistoryPage.tsx`**

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";

export default function RetentionHistoryPage() {
  const [selectedPolicyId, setSelectedPolicyId] = useState<string | undefined>(undefined);
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>(undefined);

  const policiesQuery = useQuery({
    queryKey: ["retention", "policies"],
    queryFn: () => api.getRetentionPolicies(100, 0),
  });

  const runsQuery = useQuery({
    queryKey: ["retention", "runs", selectedPolicyId],
    queryFn: () => api.getRetentionRuns(selectedPolicyId, 50, 0),
  });

  const deletionsQuery = useQuery({
    queryKey: ["retention", "deletions", selectedRunId],
    queryFn: () => api.getRetentionDeletions(selectedRunId, 100, 0),
    enabled: !!selectedRunId,
  });

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Policy History</h1>

      <div>
        <label className="text-sm font-medium">Filter by policy</label>
        <select
          value={selectedPolicyId ?? ""}
          onChange={(e) => setSelectedPolicyId(e.target.value || undefined)}
          className="mt-1 block rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">All policies</option>
          {(policiesQuery.data?.items ?? []).map((policy) => (
            <option key={policy.id} value={policy.id}>
              {policy.team_name} / {policy.channel_name} ({policy.retention_days}d)
            </option>
          ))}
        </select>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-slate-500">
            <th className="py-1">Started</th>
            <th>Outcome</th>
            <th>Messages</th>
            <th>Attachments</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {(runsQuery.data?.items ?? []).map((run) => (
            <tr
              key={run.id}
              onClick={() => setSelectedRunId(run.id)}
              className={`cursor-pointer border-t border-slate-100 ${selectedRunId === run.id ? "bg-blue-50" : ""}`}
            >
              <td className="py-1">{run.started_at}</td>
              <td>{run.outcome}</td>
              <td>{run.messages_deleted}</td>
              <td>{run.attachments_deleted}</td>
              <td className="text-red-600">{run.error ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {selectedRunId && (
        <div>
          <h2 className="text-sm font-semibold">Deletions for run {selectedRunId}</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th className="py-1">Type</th>
                <th>Sender/Author</th>
                <th>Original Date</th>
                <th>Deleted At</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(deletionsQuery.data?.items ?? []).map((deletion) => (
                <tr key={deletion.id} className="border-t border-slate-100">
                  <td className="py-1">{deletion.item_type}</td>
                  <td>{deletion.sender_or_author}</td>
                  <td>{deletion.original_created_at}</td>
                  <td>{deletion.deleted_at}</td>
                  <td>{deletion.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test:run -- RetentionHistoryPage`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/RetentionHistoryPage.tsx frontend/src/__tests__/RetentionHistoryPage.test.tsx
git commit -m "feat(retention): add policy history/audit page"
```

---

## Task 12: Wire the retention site scope into siteContext, Layout, and App routing

**Files:**
- Modify: `frontend/src/lib/siteContext.ts`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/__tests__/siteContext.test.ts` (extend existing file if present, otherwise create)

**Interfaces:**
- Consumes: `RetentionTeamsPage`, `RetentionHistoryPage` (Tasks 10-11).
- Produces: `SiteBranding.scope` including `"retention"`, `isRetentionHost(hostname)`, retention branch in `getSiteBranding()`, `retentionNavGroups`, `RetentionGroupedNav`, retention route branch in `App.tsx`.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/__tests__/siteContext.test.ts — add this case (existing file already tests other hosts)
import { describe, expect, it, afterEach } from "vitest";
import { getSiteBranding } from "../lib/siteContext.ts";

describe("retention host branding", () => {
  afterEach(() => {
    delete document.documentElement.dataset.siteHostname;
  });

  it("returns the retention scope for retention.movedocs.com", () => {
    document.documentElement.dataset.siteHostname = "retention.movedocs.com";
    const branding = getSiteBranding();
    expect(branding.scope).toBe("retention");
    expect(branding.appName).toBe("Teams Retention");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:run -- siteContext`
Expected: FAIL — `getSiteBranding()` returns `scope: "primary"` for the retention hostname

- [ ] **Step 3: Implement `frontend/src/lib/siteContext.ts` changes**

Update the `SiteBranding` interface:

```typescript
export interface SiteBranding {
  scope: "primary" | "oasisdev" | "azure" | "security" | "hrapp" | "retention";
  appName: string;
  dashboardName: string;
  alertPrefix: string;
}
```

Add a helper function (after `isHrappHost`):

```typescript
function isRetentionHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  return host === "retention.movedocs.com" || host.startsWith("retention.");
}
```

Add a branch inside `getSiteBranding()` (after the `isHrappHost` branch):

```typescript
  if (isRetentionHost(hostname)) {
    return {
      scope: "retention",
      appName: "Teams Retention",
      dashboardName: "Teams Retention",
      alertPrefix: "Retention",
    };
  }
```

- [ ] **Step 4: Implement `frontend/src/components/Layout.tsx` changes**

Add a nav group definition (after `hrappNavGroups`):

```typescript
const retentionNavGroups: NavGroup[] = [
  {
    label: "Retention",
    items: [
      { to: "/", label: "Teams & Channels", icon: "⏳", end: true },
      { to: "/history", label: "Policy History", icon: "▤" },
    ],
  },
];
```

Add a nav component (after `HrAppGroupedNav`'s closing brace):

```tsx
function RetentionGroupedNav({ pathname }: { pathname: string }) {
  return (
    <nav className="flex-1 space-y-3 px-3 py-4 overflow-y-auto">
      {retentionNavGroups.map(group => (
        <div key={group.label}>
          <div className="px-2 py-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
            {group.label}
          </div>
          <div className="mt-1 space-y-1">
            {group.items.map(({ to, label, icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end ?? (pathname === to)}
                className={({ isActive }) =>
                  [
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive ? "bg-slate-700 text-white" : "text-slate-300 hover:bg-slate-800 hover:text-white",
                  ].join(" ")
                }
              >
                <span className="text-base leading-none">{icon}</span>
                <span>{label}</span>
              </NavLink>
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
}
```

Update the nav-rendering branch (around line 396-399) to add a retention case:

```tsx
        {branding.scope === "security" ? (
          <SecurityGroupedNav pathname={location.pathname} />
        ) : branding.scope === "hrapp" ? (
          <HrAppGroupedNav pathname={location.pathname} />
        ) : branding.scope === "retention" ? (
          <RetentionGroupedNav pathname={location.pathname} />
        ) : (
```

Update the "no Jira widget" branch (around line 471) to include retention, since it's not a helpdesk queue either:

```tsx
        ) : branding.scope === "hrapp" || branding.scope === "retention" ? (
          // Neither hrapp nor retention is a helpdesk queue (site_context.issue_matches_scope()
          // returns False for both), so neither must render the Jira issue-cache widget.
          null
        ) : (
```

- [ ] **Step 5: Implement `frontend/src/App.tsx` changes**

Add lazy imports (after `const AskHrBotPage = lazy(...)`):

```typescript
const RetentionTeamsPage = lazy(() => import("./pages/RetentionTeamsPage"));
const RetentionHistoryPage = lazy(() => import("./pages/RetentionHistoryPage"));
```

Add a scope flag (after `const isHrappSite = branding.scope === "hrapp";`):

```typescript
  const isRetentionSite = branding.scope === "retention";
```

Add a route branch (after the `isHrappSite` branch, before `isAzureSite`):

```tsx
            ) : isRetentionSite ? (
              <>
                <Route index element={<RetentionTeamsPage />} />
                <Route path="history" element={<RetentionHistoryPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </>
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npm run test:run -- siteContext`
Expected: PASS

- [ ] **Step 7: Run the full frontend retention test suite to confirm no regressions**

Run: `cd frontend && npm run test:run -- Retention siteContext api.retention`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/siteContext.ts frontend/src/components/Layout.tsx frontend/src/App.tsx frontend/src/__tests__/siteContext.test.ts
git commit -m "feat(retention): wire retention site scope into nav and routing"
```

---

## Post-implementation notes (not code tasks)

- **Env vars to document/set for real deployment** (not covered by this plan's code, since they're deployment config, not code): `RETENTION_APP_HOST`, `RETENTION_ALLOWED_USERS`, `RETENTION_GRAPH_CLIENT_ID`, `RETENTION_GRAPH_CLIENT_SECRET`, `RETENTION_GRAPH_TENANT_ID`, `RETENTION_TOKEN_ENCRYPTION_KEY`. An Entra app registration must exist with delegated `ChannelMessage.ReadWrite`, `Files.ReadWrite.All`, `Team.ReadBasic.All`, `Channel.ReadBasic.All` permissions granted and admin-consented, and the dedicated service account must be added as an owner on every Team it needs to manage.
- **DNS/reverse proxy**: `retention.movedocs.com` needs to be added to Caddy routing alongside the existing `it-app`/`azure`/`security`/`hrapp` hosts — that's infrastructure config outside this repo's application code and isn't part of this plan.
- After Task 8, run the full backend suite (`pytest tests/`) and full frontend suite (`npm run test:run`) once to confirm nothing outside the retention feature regressed.
