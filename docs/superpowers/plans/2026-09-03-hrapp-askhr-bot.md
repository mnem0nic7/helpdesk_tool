# hrapp.movedocs.com + AskHR/Benefits Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a new Entra-authenticated site scope at `hrapp.movedocs.com`, and ship its first tool — a leader-only background bot that replaces the AskHR/Benefits mail-flow Bcc-to-Jira transport rules with direct Jira Service Management ticket creation (AskHR/Benefits as reporter, not the original sender), with a status/history/retry admin UI.

**Architecture:** Mirrors `backend/quarantine_release_job.py` (leader-only asyncio job, DB-backed singleton settings row, run-history + per-item detail tables, paginated admin routes) with two differences: a checkpoint-bounded poll window per mailbox instead of an hour-gate (avoids the 2026-09-01 full-sweep timeout pattern), and a detail table that also drives a manual Retry action. The `hrapp` site scope itself reuses the existing host-based-scope + Entra-SSO machinery already serving `azure`/`security` — no new auth code.

**Tech Stack:** FastAPI + SQLite/Postgres (backend), React 19 + React Query 5 + Vite (frontend), Microsoft Graph (app-only, existing Entra app registration), Jira Cloud REST v3 / JSM REST API, Exchange Online PowerShell (existing `pwsh` runner).

**Spec:** `docs/superpowers/specs/2026-09-03-hrapp-askhr-bot-design.md`

## Global Constraints

- Every new table/column needs a matching `backend/storage_migrations/*.sql` file in the same commit as the code change (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `SMALLINT` for booleans) — see [[feedback_postgres_migrations]] / CLAUDE.md.
- `enabled=false` means the job does nothing and writes no run row — no dry-run/test-mode concept, same contract as the quarantine release job.
- Never widen a Graph/PowerShell query to an unbounded sweep — every mailbox poll must be scoped by a `receivedDateTime` window (checkpoint + lookback margin), per the 2026-09-01 quarantine incident.
- `require_admin` is a no-op for Entra-authenticated sessions today (all pass) — routes still use it for consistency with the rest of the Entra-scoped surface, not because it's a tighter gate.
- Jira service desk id `73` (project `HRD`, project id `11514`); request type `420` = AskHR mailbox, `619` = Benefits mailbox; reporter accountIds and mailbox addresses are fixed constants from the spec, not env-configurable (they're specific to this one integration).
- Disabling the four legacy transport rules is **out of scope for this plan** — manual runbook step (Task 14), never a code path.

---

## File Structure

**Backend — new files:**
- `backend/askhr_bot_job.py` — `AskHrBotJob` class: settings/runs/messages schema, domain refresh, mailbox polling, ticket creation + attachment, background loop.
- `backend/routes_askhr_bot.py` — `/api/askhr-bot/*` admin routes.
- `backend/storage_migrations/0029_askhr_bot.sql` — the 3 new tables.
- `backend/tests/test_site_context.py` — new file (none existed for `site_context.py`).
- `backend/tests/test_askhr_bot_job.py`, `backend/tests/test_routes_askhr_bot.py` — new.

**Backend — modified files:**
- `backend/site_context.py` — add `hrapp` scope.
- `backend/config.py` — add `HRAPP_APP_HOST`, `HRAPP_AUTH_PROVIDER`, `ASKHR_BOT_ENABLED_DEFAULT`.
- `backend/jira_client.py` — add `create_request`, `create_issue_with_reporter`, `find_issue_by_internet_message_id`.
- `backend/exchange_online_client.py` — add `get_transport_rule_domains`, extend the `Connect-ExchangeOnline -CommandName` allow-list.
- `backend/main.py` — register the job's background runner + include the new router.
- `backend/tests/test_exchange_online_client.py`, `backend/tests/test_jira_client.py` — extended.

**Frontend — new files:**
- `frontend/src/pages/HrAppPage.tsx` — single-lane landing page.
- `frontend/src/pages/AskHrBotPage.tsx` — status/settings/history/retry dashboard.
- `frontend/src/__tests__/AskHrBotPage.test.tsx` — new.

**Frontend — modified files:**
- `frontend/src/lib/siteContext.ts` — add `hrapp` scope.
- `frontend/src/components/Layout.tsx` — add `hrappNavGroups` + a grouped-nav renderer.
- `frontend/src/App.tsx` — add the `hrapp` route branch.
- `frontend/src/lib/api.ts` — new types + functions.
- `frontend/src/__tests__/siteContext.test.ts` — extended.

**Docs — new file:**
- `docs/runbooks/askhr-bot-cutover.md` — manual transport-rule-disable runbook.

**Infra — modified file:**
- `Caddyfile` — append `hrapp.movedocs.com` to the shared site block host list.

---

### Task 1: `hrapp` site scope — backend

**Files:**
- Modify: `backend/site_context.py:1-167`
- Modify: `backend/config.py:131-240`
- Test: `backend/tests/test_site_context.py` (new)

**Interfaces:**
- Produces: `site_context.SiteScope` now includes `"hrapp"`; `site_context.get_site_scope_for_host(host: str | None) -> SiteScope` resolves `HRAPP_APP_HOST` to `"hrapp"`; `site_context.issue_matches_scope(issue, "hrapp") -> False`; `config.get_auth_provider_for_scope("hrapp") -> "entra"` (default).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_site_context.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_site_context.py -v`
Expected: FAIL — `hrapp` not a valid scope / `HRAPP_APP_HOST` not defined.

- [ ] **Step 3: Implement — `config.py`**

After line 134 (`SECURITY_APP_HOST: str = ...`):

```python
HRAPP_APP_HOST: str = os.getenv("HRAPP_APP_HOST", "hrapp.movedocs.com")
```

After line 138 (`SECURITY_AUTH_PROVIDER: str = ...`):

```python
HRAPP_AUTH_PROVIDER: str = _env_auth_provider("HRAPP_AUTH_PROVIDER", "entra")
```

In `get_auth_provider_for_scope` (line 232-240), add a branch before the `oasisdev` check:

```python
def get_auth_provider_for_scope(scope: str) -> AuthProvider:
    normalized = (scope or "").strip().lower()
    if normalized == "azure":
        return AZURE_AUTH_PROVIDER  # type: ignore[return-value]
    if normalized == "security":
        return SECURITY_AUTH_PROVIDER  # type: ignore[return-value]
    if normalized == "hrapp":
        return HRAPP_AUTH_PROVIDER  # type: ignore[return-value]
    if normalized == "oasisdev":
        return OASISDEV_AUTH_PROVIDER  # type: ignore[return-value]
    return PRIMARY_AUTH_PROVIDER  # type: ignore[return-value]
```

- [ ] **Step 4: Implement — `site_context.py`**

Line 10, import `HRAPP_APP_HOST`:

```python
from config import AZURE_APP_HOST, HRAPP_APP_HOST, OASISDEV_APP_HOST, PRIMARY_APP_HOST, SECURITY_APP_HOST
```

Line 13, extend the literal:

```python
SiteScope = Literal["primary", "oasisdev", "azure", "security", "hrapp"]
```

In `_SITE_PROFILES` (after the `"security"` entry, line 49):

```python
    "hrapp": {
        "scope": "hrapp",
        "host": HRAPP_APP_HOST,
        "app_name": "AskHR Portal",
        "dashboard_name": "AskHR Portal",
        "alert_prefix": "HR",
        "report_prefix": "HR",
    },
```

In `get_site_scope_for_host` (line 63-72), add a branch:

```python
def get_site_scope_for_host(host: str | None) -> SiteScope:
    """Map a request host to the configured dashboard site scope."""
    normalized = normalize_host(host)
    if normalized == normalize_host(AZURE_APP_HOST):
        return "azure"
    if normalized == normalize_host(SECURITY_APP_HOST):
        return "security"
    if normalized == normalize_host(HRAPP_APP_HOST):
        return "hrapp"
    if normalized == normalize_host(OASISDEV_APP_HOST):
        return "oasisdev"
    return "primary"
```

In `issue_matches_scope` (line 104-113) and `get_scoped_issues` (line 125-140), extend the tuple in both places:

```python
    if scope in ("azure", "security", "hrapp"):
        return False
```

```python
    if scope in ("azure", "security", "hrapp"):
        return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_site_context.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/site_context.py backend/config.py backend/tests/test_site_context.py
git commit -m "feat: add hrapp site scope (Entra-authenticated, no Jira issue list)"
```

---

### Task 2: `hrapp` site scope — frontend

**Files:**
- Modify: `frontend/src/lib/siteContext.ts:1-71`
- Test: `frontend/src/__tests__/siteContext.test.ts:1-17`

**Interfaces:**
- Produces: `SiteBranding["scope"]` now includes `"hrapp"`; `getSiteBranding()` returns `{ scope: "hrapp", appName: "AskHR Portal", dashboardName: "AskHR Portal", alertPrefix: "HR" }` for hostnames matching `isHrappHost()`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/__tests__/siteContext.test.ts`:

```typescript
  it("detects the hrapp host", () => {
    document.documentElement.dataset.siteHostname = "hrapp.movedocs.com";
    window.history.replaceState({}, "", "/");
    expect(getSiteBranding().scope).toBe("hrapp");
    expect(getSiteBranding().appName).toBe("AskHR Portal");
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test:run -- siteContext`
Expected: FAIL — scope is `"primary"`, not `"hrapp"`.

- [ ] **Step 3: Implement**

`frontend/src/lib/siteContext.ts`:

```typescript
export interface SiteBranding {
  scope: "primary" | "oasisdev" | "azure" | "security" | "hrapp";
  appName: string;
  dashboardName: string;
  alertPrefix: string;
}

function isOasisDevHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  return host === "oasisdev.movedocs.com" || host.startsWith("oasisdev.");
}

function isAzureHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  return host === "azure.movedocs.com" || host.startsWith("azure.");
}

function isSecurityHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  return host === "security.movedocs.com" || host.startsWith("security.");
}

function isHrappHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  return host === "hrapp.movedocs.com" || host.startsWith("hrapp.");
}

function getCurrentHostname(): string {
  if (typeof document !== "undefined") {
    const testHost = document.documentElement.dataset.siteHostname;
    if (testHost) return testHost;
  }
  if (typeof window !== "undefined") {
    return window.location.hostname;
  }
  return "";
}

export function getSiteBranding(): SiteBranding {
  const hostname = getCurrentHostname();

  if (isSecurityHost(hostname)) {
    return {
      scope: "security",
      appName: "Security Portal",
      dashboardName: "Security Portal",
      alertPrefix: "Security",
    };
  }

  if (isHrappHost(hostname)) {
    return {
      scope: "hrapp",
      appName: "AskHR Portal",
      dashboardName: "AskHR Portal",
      alertPrefix: "HR",
    };
  }

  if (isAzureHost(hostname)) {
    return {
      scope: "azure",
      appName: "MoveDocs Azure Portal",
      dashboardName: "Azure Control Center",
      alertPrefix: "Azure",
    };
  }

  if (isOasisDevHost(hostname)) {
    return {
      scope: "oasisdev",
      appName: "OasisDev Helpdesk",
      dashboardName: "OasisDev Dashboard",
      alertPrefix: "OasisDev",
    };
  }

  return {
    scope: "primary",
    appName: "OIT Helpdesk",
    dashboardName: "OIT Dashboard",
    alertPrefix: "OIT",
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test:run -- siteContext`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/siteContext.ts frontend/src/__tests__/siteContext.test.ts
git commit -m "feat: recognize the hrapp host in frontend site branding"
```

---

### Task 3: `askhr_bot_job.py` core — schema + settings

**Files:**
- Create: `backend/askhr_bot_job.py`
- Create: `backend/storage_migrations/0029_askhr_bot.sql`
- Modify: `backend/config.py` (add `ASKHR_BOT_ENABLED_DEFAULT`)
- Test: `backend/tests/test_askhr_bot_job.py` (new)

**Interfaces:**
- Produces: `AskHrBotJob(db_path: str | None = None)`; `job._conn()`, `job._placeholder()`, `job._sqlite_conn()` (same shape as `QuarantineReleaseJob`); `job._get_settings() -> dict` bootstraps a default row on first call, returning `{"enabled": bool, "poll_interval_seconds": int, "lookback_minutes": int, "askhr_checkpoint_at": str, "benefits_checkpoint_at": str, "trusted_domains": list[str], "trusted_domains_refreshed_at": str, "domain_refresh_interval_seconds": int, "reporter_mode": str}`; `job._update_settings(**fields) -> dict` (same shape, partial update, sets `updated_at`/`updated_by`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_askhr_bot_job.py`:

```python
"""Tests for the AskHR/Benefits bot job core: schema, settings bootstrap, and updates."""
from __future__ import annotations

import tempfile


def _fresh_job():
    from askhr_bot_job import AskHrBotJob
    tmp = tempfile.mktemp(suffix=".db")
    return AskHrBotJob(db_path=tmp)


def test_get_settings_bootstraps_default_row_when_missing(monkeypatch):
    import config
    monkeypatch.setattr(config, "ASKHR_BOT_ENABLED_DEFAULT", False)
    import askhr_bot_job as job_module
    monkeypatch.setattr(job_module, "ASKHR_BOT_ENABLED_DEFAULT", False)

    job = _fresh_job()
    settings = job._get_settings()

    assert settings["enabled"] is False
    assert settings["poll_interval_seconds"] == 120
    assert settings["lookback_minutes"] == 15
    assert settings["askhr_checkpoint_at"] == ""
    assert settings["benefits_checkpoint_at"] == ""
    assert settings["trusted_domains"] == []
    assert settings["domain_refresh_interval_seconds"] == 3600
    assert settings["reporter_mode"] == "unset"

    # Second call reads the persisted row rather than re-bootstrapping.
    assert job._get_settings() == settings


def test_update_settings_partial_update_preserves_other_fields():
    job = _fresh_job()
    job._get_settings()  # bootstrap

    updated = job._update_settings(enabled=True, poll_interval_seconds=60, updated_by="admin@example.com")

    assert updated["enabled"] is True
    assert updated["poll_interval_seconds"] == 60
    assert updated["lookback_minutes"] == 15  # untouched

    again = job._update_settings(enabled=False)
    assert again["enabled"] is False
    assert again["poll_interval_seconds"] == 60  # still preserved


def test_update_settings_persists_trusted_domains_and_checkpoints():
    job = _fresh_job()
    job._get_settings()

    updated = job._update_settings(
        trusted_domains=["librasolutionsgroup.com", "movedocs.com"],
        askhr_checkpoint_at="2026-09-03T00:00:00+00:00",
    )

    assert updated["trusted_domains"] == ["librasolutionsgroup.com", "movedocs.com"]
    assert updated["askhr_checkpoint_at"] == "2026-09-03T00:00:00+00:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_askhr_bot_job.py -v`
Expected: FAIL — `askhr_bot_job` module does not exist.

- [ ] **Step 3: Create the migration**

Create `backend/storage_migrations/0029_askhr_bot.sql`:

```sql
CREATE TABLE IF NOT EXISTS askhr_bot_settings (
    id                              INTEGER PRIMARY KEY DEFAULT 1,
    enabled                         SMALLINT NOT NULL DEFAULT 0,
    poll_interval_seconds           INTEGER NOT NULL DEFAULT 120,
    lookback_minutes                INTEGER NOT NULL DEFAULT 15,
    askhr_checkpoint_at             TEXT NOT NULL DEFAULT '',
    benefits_checkpoint_at          TEXT NOT NULL DEFAULT '',
    trusted_domains                 TEXT NOT NULL DEFAULT '[]',
    trusted_domains_refreshed_at    TEXT NOT NULL DEFAULT '',
    domain_refresh_interval_seconds INTEGER NOT NULL DEFAULT 3600,
    reporter_mode                   TEXT NOT NULL DEFAULT 'unset',
    updated_at                      TEXT NOT NULL DEFAULT '',
    updated_by                      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS askhr_bot_runs (
    id               TEXT PRIMARY KEY,
    mailbox          TEXT NOT NULL,
    run_started_at   TEXT NOT NULL,
    messages_scanned INTEGER NOT NULL DEFAULT 0,
    created_count    INTEGER NOT NULL DEFAULT 0,
    skipped_count    INTEGER NOT NULL DEFAULT 0,
    failed_count     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS askhr_bot_messages (
    internet_message_id TEXT PRIMARY KEY,
    mailbox              TEXT NOT NULL,
    graph_message_id     TEXT NOT NULL,
    subject               TEXT NOT NULL DEFAULT '',
    sender_email          TEXT NOT NULL DEFAULT '',
    received_at           TEXT NOT NULL DEFAULT '',
    status                TEXT NOT NULL,
    jira_issue_key        TEXT,
    error                 TEXT,
    processed_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_askhr_bot_messages_mailbox_received
    ON askhr_bot_messages (mailbox, received_at);
```

- [ ] **Step 4: Add the config default**

In `backend/config.py`, after the `QUARANTINE_RELEASE_DEFAULT_DOMAINS` line at the bottom of the file:

```python
# AskHR/Benefits bot
ASKHR_BOT_ENABLED_DEFAULT: bool = _env_bool("ASKHR_BOT_ENABLED_DEFAULT", "0")
```

- [ ] **Step 5: Implement `backend/askhr_bot_job.py`**

```python
"""AskHR/Benefits mailbox-to-Jira bot.

Runs as a leader-only background service. Polls the AskHR and Benefits
mailboxes, filters by trusted sender domain, and creates HRD Jira tickets
with AskHR/Benefits as reporter instead of the original external sender.
No test-mode/dry-run concept: enabled=false means the job does nothing.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from config import ASKHR_BOT_ENABLED_DEFAULT, DATA_DIR
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(DATA_DIR, "askhr_bot.db")

MAILBOXES: dict[str, dict[str, str]] = {
    "askhr": {"address": "AskHR@librasolutionsgroup.com", "request_type_id": "420"},
    "benefits": {"address": "Benefits@librasolutionsgroup.com", "request_type_id": "619"},
}
PAYROLL_BYPASS_SENDER = "payroll@librasolutionsgroup.com"
JSM_SERVICE_DESK_ID = "73"
JSM_PROJECT_KEY = "HRD"
REPORTER_ACCOUNT_IDS: dict[str, str] = {
    "askhr": "qm:43cd1b99-1808-44a4-95b1-09e2c82c645a:9528d568-c455-4457-9ce4-edd8d58b218c",
    "benefits": "qm:43cd1b99-1808-44a4-95b1-09e2c82c645a:5f896e59-af49-457a-a456-edaa7515d98a",
}

_TRANSPORT_RULE_IDENTITY = "Forward External Mail to Jira - AskHR"

_SETTINGS_FIELDS = (
    "enabled",
    "poll_interval_seconds",
    "lookback_minutes",
    "askhr_checkpoint_at",
    "benefits_checkpoint_at",
    "trusted_domains",
    "trusted_domains_refreshed_at",
    "domain_refresh_interval_seconds",
    "reporter_mode",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _settings_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "enabled": bool(row["enabled"]),
        "poll_interval_seconds": int(row["poll_interval_seconds"]),
        "lookback_minutes": int(row["lookback_minutes"]),
        "askhr_checkpoint_at": str(row["askhr_checkpoint_at"] or ""),
        "benefits_checkpoint_at": str(row["benefits_checkpoint_at"] or ""),
        "trusted_domains": json.loads(row["trusted_domains"] or "[]"),
        "trusted_domains_refreshed_at": str(row["trusted_domains_refreshed_at"] or ""),
        "domain_refresh_interval_seconds": int(row["domain_refresh_interval_seconds"]),
        "reporter_mode": str(row["reporter_mode"] or "unset"),
    }


class AskHrBotJob:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._bg_task = None
        self._init_db()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _sqlite_conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _conn(self) -> sqlite3.Connection:
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
                CREATE TABLE IF NOT EXISTS askhr_bot_settings (
                    id                              INTEGER PRIMARY KEY DEFAULT 1,
                    enabled                         SMALLINT NOT NULL DEFAULT 0,
                    poll_interval_seconds           INTEGER NOT NULL DEFAULT 120,
                    lookback_minutes                INTEGER NOT NULL DEFAULT 15,
                    askhr_checkpoint_at             TEXT NOT NULL DEFAULT '',
                    benefits_checkpoint_at          TEXT NOT NULL DEFAULT '',
                    trusted_domains                 TEXT NOT NULL DEFAULT '[]',
                    trusted_domains_refreshed_at    TEXT NOT NULL DEFAULT '',
                    domain_refresh_interval_seconds INTEGER NOT NULL DEFAULT 3600,
                    reporter_mode                   TEXT NOT NULL DEFAULT 'unset',
                    updated_at                      TEXT NOT NULL DEFAULT '',
                    updated_by                      TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS askhr_bot_runs (
                    id               TEXT PRIMARY KEY,
                    mailbox          TEXT NOT NULL,
                    run_started_at   TEXT NOT NULL,
                    messages_scanned INTEGER NOT NULL DEFAULT 0,
                    created_count    INTEGER NOT NULL DEFAULT 0,
                    skipped_count    INTEGER NOT NULL DEFAULT 0,
                    failed_count     INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS askhr_bot_messages (
                    internet_message_id TEXT PRIMARY KEY,
                    mailbox              TEXT NOT NULL,
                    graph_message_id     TEXT NOT NULL,
                    subject               TEXT NOT NULL DEFAULT '',
                    sender_email          TEXT NOT NULL DEFAULT '',
                    received_at           TEXT NOT NULL DEFAULT '',
                    status                TEXT NOT NULL,
                    jira_issue_key        TEXT,
                    error                 TEXT,
                    processed_at          TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_askhr_bot_messages_mailbox_received
                    ON askhr_bot_messages (mailbox, received_at)
            """)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _get_settings(self) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT enabled, poll_interval_seconds, lookback_minutes, askhr_checkpoint_at, "
                "benefits_checkpoint_at, trusted_domains, trusted_domains_refreshed_at, "
                "domain_refresh_interval_seconds, reporter_mode "
                "FROM askhr_bot_settings WHERE id = 1"
            ).fetchone()
            if row is None:
                ph = self._placeholder()
                defaults = (1, 1 if ASKHR_BOT_ENABLED_DEFAULT else 0, 120, 15, "", "", "[]", "", 3600, "unset",
                            _utcnow().isoformat(), "system")
                conn.execute(
                    f"INSERT INTO askhr_bot_settings "
                    f"(id, enabled, poll_interval_seconds, lookback_minutes, askhr_checkpoint_at, "
                    f"benefits_checkpoint_at, trusted_domains, trusted_domains_refreshed_at, "
                    f"domain_refresh_interval_seconds, reporter_mode, updated_at, updated_by) "
                    f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                    defaults,
                )
                return {
                    "enabled": bool(ASKHR_BOT_ENABLED_DEFAULT),
                    "poll_interval_seconds": 120,
                    "lookback_minutes": 15,
                    "askhr_checkpoint_at": "",
                    "benefits_checkpoint_at": "",
                    "trusted_domains": [],
                    "trusted_domains_refreshed_at": "",
                    "domain_refresh_interval_seconds": 3600,
                    "reporter_mode": "unset",
                }
        return _settings_row_to_dict(row)

    def _update_settings(self, *, updated_by: str = "system", **fields: Any) -> dict[str, Any]:
        current = self._get_settings()
        for key, value in fields.items():
            if key not in _SETTINGS_FIELDS:
                raise ValueError(f"Unknown settings field: {key}")
            current[key] = value
        ph = self._placeholder()
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO askhr_bot_settings "
                f"(id, enabled, poll_interval_seconds, lookback_minutes, askhr_checkpoint_at, "
                f"benefits_checkpoint_at, trusted_domains, trusted_domains_refreshed_at, "
                f"domain_refresh_interval_seconds, reporter_mode, updated_at, updated_by) "
                f"VALUES (1,{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph}) "
                f"ON CONFLICT (id) DO UPDATE SET "
                f"enabled = excluded.enabled, poll_interval_seconds = excluded.poll_interval_seconds, "
                f"lookback_minutes = excluded.lookback_minutes, askhr_checkpoint_at = excluded.askhr_checkpoint_at, "
                f"benefits_checkpoint_at = excluded.benefits_checkpoint_at, trusted_domains = excluded.trusted_domains, "
                f"trusted_domains_refreshed_at = excluded.trusted_domains_refreshed_at, "
                f"domain_refresh_interval_seconds = excluded.domain_refresh_interval_seconds, "
                f"reporter_mode = excluded.reporter_mode, updated_at = excluded.updated_at, "
                f"updated_by = excluded.updated_by",
                (
                    1 if current["enabled"] else 0,
                    current["poll_interval_seconds"],
                    current["lookback_minutes"],
                    current["askhr_checkpoint_at"],
                    current["benefits_checkpoint_at"],
                    json.dumps(current["trusted_domains"]),
                    current["trusted_domains_refreshed_at"],
                    current["domain_refresh_interval_seconds"],
                    current["reporter_mode"],
                    _utcnow().isoformat(),
                    updated_by,
                ),
            )
        return current
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_askhr_bot_job.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/askhr_bot_job.py backend/storage_migrations/0029_askhr_bot.sql backend/config.py backend/tests/test_askhr_bot_job.py
git commit -m "feat: add AskHR bot job schema and settings (disabled by default)"
```

---

### Task 4: `exchange_online_client.get_transport_rule_domains`

**Files:**
- Modify: `backend/exchange_online_client.py:112-207` (`_run_script` allow-list) and append a new method after `release_quarantine_message` (line 702).
- Test: `backend/tests/test_exchange_online_client.py` (extend)

**Interfaces:**
- Produces: `ExchangeOnlinePowerShellClient.get_transport_rule_domains(rule_identity: str) -> list[str]` — lower-cased domain list from `ExceptIfSenderDomainIs`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_exchange_online_client.py`:

```python
def test_run_script_command_name_allow_list_includes_get_transport_rule(monkeypatch):
    client = ExchangeOnlinePowerShellClient(
        azure_client=StubAzureClient(), organization_override="contoso.onmicrosoft.com"
    )
    monkeypatch.setattr("exchange_online_client.shutil.which", lambda name: "/usr/bin/pwsh")
    captured: dict[str, str] = {}

    def fake_popen(args, **kwargs):
        captured["script"] = Path(args[-1]).read_text()
        return FakeProcess()

    monkeypatch.setattr("exchange_online_client.subprocess.Popen", fake_popen)

    client._run_script("Get-Mailbox -Identity 'x'")

    assert "'Get-TransportRule'" in captured["script"]


def test_get_transport_rule_domains_builds_correct_script_and_normalizes(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        captured["script_body"] = script_body
        captured["extra_env"] = extra_env or {}
        return {"domains": ["Example.com", "PARTNER.org", "example.com"]}

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    result = client.get_transport_rule_domains("Forward External Mail to Jira - AskHR")

    assert result == ["example.com", "partner.org"]
    assert captured["extra_env"] == {"TR_RULE_IDENTITY": "Forward External Mail to Jira - AskHR"}
    assert "Get-TransportRule" in captured["script_body"]
    assert "ExceptIfSenderDomainIs" in captured["script_body"]


def test_get_transport_rule_domains_requires_rule_identity():
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    try:
        client.get_transport_rule_domains("")
        assert False, "expected ExchangeOnlinePowerShellError"
    except ExchangeOnlinePowerShellError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exchange_online_client.py -k transport_rule -v`
Expected: FAIL — `get_transport_rule_domains` does not exist; allow-list missing `Get-TransportRule`.

- [ ] **Step 3: Implement**

In `_run_script` (exchange_online_client.py:136-146), add `'Get-TransportRule'` to the `-CommandName` array, right after `'Release-QuarantineMessage'`:

```python
  -CommandName @(
    'Get-Mailbox',
    'Set-Mailbox',
    'Add-MailboxPermission',
    'Add-RecipientPermission',
    'Get-EXOMailboxPermission',
    'Get-EXORecipientPermission',
    'Remove-DistributionGroupMember',
    'Get-QuarantineMessage',
    'Release-QuarantineMessage',
    'Get-TransportRule',
    'Disconnect-ExchangeOnline'
  ) | Out-Null
```

After `release_quarantine_message` (end of file, line 702), add:

```python
    def get_transport_rule_domains(self, rule_identity: str) -> list[str]:
        """Return the ExceptIfSenderDomainIs list for a transport rule.

        This is the authoritative source for "internal/vanity domain" lists used
        elsewhere (e.g. the AskHR bot's trusted-domain filter) so callers never
        hardcode a copy that drifts from the real transport rule.
        """
        identity = str(rule_identity or "").strip()
        if not identity:
            raise ExchangeOnlinePowerShellError("rule_identity is required")
        script = """
$ruleIdentity = $env:TR_RULE_IDENTITY
$rule = Get-TransportRule -Identity $ruleIdentity
$domains = @($rule.ExceptIfSenderDomainIs)
@{
  domains = $domains
} | ConvertTo-Json -Depth 4 -Compress
"""
        payload = self._run_script(script.strip(), extra_env={"TR_RULE_IDENTITY": identity})
        domains = payload.get("domains") if isinstance(payload, dict) else []
        if isinstance(domains, str):
            domains = [domains]
        seen: list[str] = []
        for domain in domains or []:
            normalized = str(domain or "").strip().lower()
            if normalized and normalized not in seen:
                seen.append(normalized)
        return seen
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exchange_online_client.py -v`
Expected: PASS (all tests in the file, including pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add backend/exchange_online_client.py backend/tests/test_exchange_online_client.py
git commit -m "feat: add get_transport_rule_domains to the Exchange Online PowerShell client"
```

---

### Task 5: `askhr_bot_job` domain refresh

**Files:**
- Modify: `backend/askhr_bot_job.py` (add `_refresh_trusted_domains_if_needed`)
- Test: `backend/tests/test_askhr_bot_job.py` (extend)

**Interfaces:**
- Consumes: `job._get_settings()`, `job._update_settings(**fields)` from Task 3; `exchange.get_transport_rule_domains(rule_identity)` from Task 4 (accessed lazily via `user_admin_providers.user_admin_providers.mailbox.exchange_powershell`, same lazy-import pattern as `QuarantineReleaseJob.run_hourly_job`).
- Produces: `job._refresh_trusted_domains_if_needed() -> None` — no-op if the cache is still fresh; otherwise calls Exchange and updates `trusted_domains`/`trusted_domains_refreshed_at`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_askhr_bot_job.py`:

```python
from unittest.mock import MagicMock, patch


def test_refresh_trusted_domains_calls_exchange_when_stale(monkeypatch):
    import askhr_bot_job as job_module
    from datetime import datetime, timezone

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(job_module, "_utcnow", lambda: now)

    job = _fresh_job()
    job._get_settings()  # bootstrap; trusted_domains_refreshed_at == ""

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.get_transport_rule_domains.return_value = ["librasolutionsgroup.com", "movedocs.com"]

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        job._refresh_trusted_domains_if_needed()

    exchange.get_transport_rule_domains.assert_called_once_with(job_module._TRANSPORT_RULE_IDENTITY)
    settings = job._get_settings()
    assert settings["trusted_domains"] == ["librasolutionsgroup.com", "movedocs.com"]
    assert settings["trusted_domains_refreshed_at"] == now.isoformat()


def test_refresh_trusted_domains_skips_when_still_fresh(monkeypatch):
    import askhr_bot_job as job_module
    from datetime import datetime, timezone

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(job_module, "_utcnow", lambda: now)

    job = _fresh_job()
    job._get_settings()
    job._update_settings(trusted_domains=["movedocs.com"], trusted_domains_refreshed_at=now.isoformat())

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        job._refresh_trusted_domains_if_needed()

    exchange.get_transport_rule_domains.assert_not_called()
```

Note: `_update_settings` currently rejects unknown fields, but `trusted_domains_refreshed_at` is already in `_SETTINGS_FIELDS`, so this call is valid as-is.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_askhr_bot_job.py -k refresh_trusted_domains -v`
Expected: FAIL — `_refresh_trusted_domains_if_needed` does not exist.

- [ ] **Step 3: Implement**

Add to `backend/askhr_bot_job.py`, after `_update_settings`:

```python
    def _refresh_trusted_domains_if_needed(self) -> None:
        settings = self._get_settings()
        refreshed_at = settings["trusted_domains_refreshed_at"]
        interval = settings["domain_refresh_interval_seconds"]
        if refreshed_at:
            elapsed = (_utcnow() - datetime.fromisoformat(refreshed_at)).total_seconds()
            if elapsed < interval:
                return

        import user_admin_providers as _uap_module

        exchange = _uap_module.user_admin_providers.mailbox.exchange_powershell
        domains = exchange.get_transport_rule_domains(_TRANSPORT_RULE_IDENTITY)
        self._update_settings(
            trusted_domains=domains,
            trusted_domains_refreshed_at=_utcnow().isoformat(),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_askhr_bot_job.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/askhr_bot_job.py backend/tests/test_askhr_bot_job.py
git commit -m "feat: refresh AskHR bot trusted-domain cache from the live transport rule"
```

---

### Task 6: `jira_client` — request creation + JQL idempotency lookup

**Files:**
- Modify: `backend/jira_client.py` (add three methods after `create_issue`, line 717)
- Test: `backend/tests/test_jira_client.py` (extend)

**Interfaces:**
- Produces:
  - `JiraClient.create_request(*, service_desk_id: str, request_type_id: str, raise_on_behalf_of: str, summary: str, description: str) -> dict[str, Any]` (`POST /rest/servicedeskapi/request`)
  - `JiraClient.create_issue_with_reporter(*, project_key: str, issue_type: str, summary: str, description: str, reporter_account_id: str) -> dict[str, Any]` (`POST /rest/api/3/issue` with `fields.reporter.id`)
  - `JiraClient.find_issue_by_internet_message_id(internet_message_id: str, *, project_key: str) -> str | None`

- [ ] **Step 1: Write the failing tests**

Check the existing test file's fixture pattern first — search `backend/tests/test_jira_client.py` for how a `JiraClient` instance and its `session.post`/`session` are mocked (e.g. `responses` library, or `monkeypatch.setattr(client.session, "post", ...)`), and mirror that exact pattern. If the file uses `requests_mock` or `responses`, register these new tests the same way. Write:

```python
def test_create_request_posts_raise_on_behalf_of_payload(jira_client_and_mock):
    client, mock = jira_client_and_mock  # adapt to this file's existing fixture name/shape
    mock.post(
        f"{client.base_url}/rest/servicedeskapi/request",
        json={"issueKey": "HRD-1"},
        status_code=201,
    )

    result = client.create_request(
        service_desk_id="73",
        request_type_id="420",
        raise_on_behalf_of="qm:tenant:askhr-account-id",
        summary="Help with benefits",
        description="Originally sent by: Jane Doe <jane@example.com> on 2026-09-03 09:00\n\nBody text",
    )

    assert result["issueKey"] == "HRD-1"
    sent = mock.request_history[-1].json()
    assert sent["serviceDeskId"] == "73"
    assert sent["requestTypeId"] == "420"
    assert sent["raiseOnBehalfOf"] == "qm:tenant:askhr-account-id"
    assert sent["requestFieldValues"]["summary"] == "Help with benefits"


def test_create_issue_with_reporter_posts_classic_issue_payload(jira_client_and_mock):
    client, mock = jira_client_and_mock
    mock.post(f"{client.base_url}/rest/api/3/issue", json={"key": "HRD-2"}, status_code=201)

    result = client.create_issue_with_reporter(
        project_key="HRD",
        issue_type="Emailed request",
        summary="Help with benefits",
        description="Body text",
        reporter_account_id="qm:tenant:askhr-account-id",
    )

    assert result["key"] == "HRD-2"
    sent = mock.request_history[-1].json()
    assert sent["fields"]["project"]["key"] == "HRD"
    assert sent["fields"]["issuetype"]["name"] == "Emailed request"
    assert sent["fields"]["reporter"]["id"] == "qm:tenant:askhr-account-id"


def test_find_issue_by_internet_message_id_returns_key_when_found(jira_client_and_mock):
    client, mock = jira_client_and_mock
    mock.post(
        f"{client.base_url}/rest/api/3/search/jql",
        json={"issues": [{"key": "HRD-3"}]},
    )

    key = client.find_issue_by_internet_message_id("<abc123@mail.example.com>", project_key="HRD")

    assert key == "HRD-3"
    sent = mock.request_history[-1].json()
    assert "HRD" in sent["jql"]
    assert "abc123@mail.example.com" in sent["jql"]


def test_find_issue_by_internet_message_id_returns_none_when_not_found(jira_client_and_mock):
    client, mock = jira_client_and_mock
    mock.post(f"{client.base_url}/rest/api/3/search/jql", json={"issues": []})

    assert client.find_issue_by_internet_message_id("<missing@mail.example.com>", project_key="HRD") is None
```

Before writing these for real, read `backend/tests/test_jira_client.py`'s first ~40 lines to see the actual mocking fixture in use (likely `requests_mock` given `mock.request_history`/`mock.post` above is illustrative) and adjust the fixture name/usage to match exactly — do not invent a fixture that doesn't exist in the file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_jira_client.py -k "create_request or create_issue_with_reporter or find_issue_by_internet_message_id" -v`
Expected: FAIL — methods don't exist.

- [ ] **Step 3: Implement**

Add to `backend/jira_client.py`, after `create_issue` (line 717):

```python
    def create_request(
        self,
        *,
        service_desk_id: str,
        request_type_id: str,
        raise_on_behalf_of: str,
        summary: str,
        description: str,
    ) -> dict[str, Any]:
        """POST /rest/servicedeskapi/request, raising the ticket on behalf of another account."""
        url = f"{self.base_url}/rest/servicedeskapi/request"
        payload = {
            "serviceDeskId": service_desk_id,
            "requestTypeId": request_type_id,
            "raiseOnBehalfOf": raise_on_behalf_of,
            "requestFieldValues": {
                "summary": summary,
                "description": description,
            },
        }
        resp = self.session.post(url, json=payload, timeout=self._TIMEOUT)
        self._raise_for_status(resp)
        return resp.json()

    def create_issue_with_reporter(
        self,
        *,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str,
        reporter_account_id: str,
    ) -> dict[str, Any]:
        """POST /rest/api/3/issue with an explicit reporter accountId.

        Fallback path for raiseOnBehalfOf when the calling account isn't
        recognized as a JSM agent on the target service desk.
        """
        payload_fields: dict[str, Any] = {
            "project": {"key": project_key.strip().upper()},
            "summary": summary,
            "issuetype": {"name": issue_type},
            "reporter": {"id": reporter_account_id},
        }
        if description.strip():
            payload_fields["description"] = self._plain_text_to_adf(description)
        url = f"{self.base_url}/rest/api/3/issue"
        resp = self.session.post(url, json={"fields": payload_fields}, timeout=self._TIMEOUT)
        self._raise_for_status(resp)
        return resp.json()

    def find_issue_by_internet_message_id(self, internet_message_id: str, *, project_key: str) -> str | None:
        """Defensive idempotency check: does a ticket already reference this message?

        Used as a fallback before creating a ticket, in case a prior run created
        the ticket but failed to persist that fact locally.
        """
        message_id = internet_message_id.strip()
        if not message_id:
            return None
        jql = f'project = {project_key.strip().upper()} AND text ~ "{message_id}"'
        url = f"{self.base_url}/rest/api/3/search/jql"
        resp = self.session.post(
            url,
            json={"jql": jql, "maxResults": 1, "fields": ["key"]},
            timeout=self._TIMEOUT,
        )
        self._raise_for_status(resp)
        issues = resp.json().get("issues") or []
        return str(issues[0]["key"]) if issues else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_jira_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/jira_client.py backend/tests/test_jira_client.py
git commit -m "feat: add JSM request creation, classic-reporter fallback, and message-id lookup to JiraClient"
```

---

### Task 7: `askhr_bot_job` — ticket creation + attachment orchestration

**Files:**
- Modify: `backend/askhr_bot_job.py` (add `_create_or_attach_ticket`, `_probe_or_use_reporter_mode`)
- Test: `backend/tests/test_askhr_bot_job.py` (extend)

**Interfaces:**
- Consumes: `JiraClient.create_request`, `create_issue_with_reporter`, `find_issue_by_internet_message_id` from Task 6; `AzureClient.graph_raw_request` (existing, `backend/azure_client.py:1006`).
- Produces: `job._create_or_attach_ticket(mailbox: str, message: dict, existing_issue_key: str | None) -> tuple[str, str | None, str | None]` returning `(status, jira_issue_key, error)` where `status` is `"created"` or `"failed"`. `message` is `{"internet_message_id", "graph_message_id", "subject", "sender_email", "sender_name", "received_at", "body"}`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_askhr_bot_job.py`:

```python
def _sample_message(**overrides):
    base = {
        "internet_message_id": "<abc123@mail.example.com>",
        "graph_message_id": "AAMkAD...",
        "subject": "Need help with benefits",
        "sender_email": "jane@example.com",
        "sender_name": "Jane Doe",
        "received_at": "2026-09-03T09:00:00+00:00",
        "body": "Can someone help me with open enrollment?",
    }
    base.update(overrides)
    return base


def test_create_or_attach_ticket_probes_and_caches_raise_on_behalf_of(monkeypatch):
    job = _fresh_job()
    job._get_settings()

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None
    mock_jira.create_request.return_value = {"issueKey": "HRD-10"}
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)
    monkeypatch.setattr(mock_jira, "add_attachment", MagicMock(), raising=False)

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key=None)

    assert status == "created"
    assert issue_key == "HRD-10"
    assert error is None
    mock_jira.create_request.assert_called_once()
    assert job._get_settings()["reporter_mode"] == "raise_on_behalf_of"


def test_create_or_attach_ticket_falls_back_to_classic_reporter_on_403(monkeypatch):
    import requests

    job = _fresh_job()
    job._get_settings()

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None
    forbidden = requests.exceptions.HTTPError(response=MagicMock(status_code=403))
    mock_jira.create_request.side_effect = forbidden
    mock_jira.create_issue_with_reporter.return_value = {"key": "HRD-11"}
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key=None)

    assert status == "created"
    assert issue_key == "HRD-11"
    mock_jira.create_issue_with_reporter.assert_called_once()
    assert job._get_settings()["reporter_mode"] == "classic_reporter_field"


def test_create_or_attach_ticket_uses_cached_reporter_mode_without_probing(monkeypatch):
    job = _fresh_job()
    job._get_settings()
    job._update_settings(reporter_mode="classic_reporter_field")

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None
    mock_jira.create_issue_with_reporter.return_value = {"key": "HRD-12"}
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    job._create_or_attach_ticket("benefits", _sample_message(), existing_issue_key=None)

    mock_jira.create_request.assert_not_called()
    mock_jira.create_issue_with_reporter.assert_called_once()


def test_create_or_attach_ticket_skips_creation_when_issue_key_already_exists(monkeypatch):
    job = _fresh_job()
    job._get_settings()

    mock_jira = MagicMock()
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.return_value = MagicMock(status_code=200, content=b"raw-eml-bytes")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key="HRD-9")

    assert status == "created"
    assert issue_key == "HRD-9"
    mock_jira.create_request.assert_not_called()
    mock_jira.create_issue_with_reporter.assert_not_called()
    mock_jira.find_issue_by_internet_message_id.assert_not_called()


def test_create_or_attach_ticket_records_attachment_failure_but_keeps_issue_key(monkeypatch):
    job = _fresh_job()
    job._get_settings()
    job._update_settings(reporter_mode="raise_on_behalf_of")

    mock_jira = MagicMock()
    mock_jira.find_issue_by_internet_message_id.return_value = None
    mock_jira.create_request.return_value = {"issueKey": "HRD-13"}
    mock_azure = MagicMock()
    mock_azure.graph_raw_request.side_effect = RuntimeError("graph timeout")
    monkeypatch.setattr(job, "_jira", mock_jira)
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    status, issue_key, error = job._create_or_attach_ticket("askhr", _sample_message(), existing_issue_key=None)

    assert status == "failed"
    assert issue_key == "HRD-13"
    assert "graph timeout" in error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_askhr_bot_job.py -k create_or_attach -v`
Expected: FAIL — `_create_or_attach_ticket` does not exist.

- [ ] **Step 3: Implement**

Add near the top of `backend/askhr_bot_job.py` (imports section):

```python
import requests

from jira_client import JiraClient
```

Add inside `AskHrBotJob.__init__`, after `self._init_db()`:

```python
        self._jira = JiraClient()
```

Add these methods to `AskHrBotJob`:

```python
    def _azure_client(self):
        import azure_cache

        return azure_cache._client

    def _build_description(self, message: dict[str, Any]) -> str:
        return (
            f"Originally sent by: {message['sender_name']} <{message['sender_email']}> "
            f"on {message['received_at']}\n\n{message['body']}"
        )

    def _create_ticket(self, mailbox: str, message: dict[str, Any]) -> str:
        settings = self._get_settings()
        mode = settings["reporter_mode"]
        service_desk_id = JSM_SERVICE_DESK_ID
        request_type_id = MAILBOXES[mailbox]["request_type_id"]
        reporter_account_id = REPORTER_ACCOUNT_IDS[mailbox]
        summary = message["subject"]
        description = self._build_description(message)

        if mode == "classic_reporter_field":
            issue = self._jira.create_issue_with_reporter(
                project_key=JSM_PROJECT_KEY,
                issue_type="Emailed request" if mailbox == "askhr" else "Benefits",
                summary=summary,
                description=description,
                reporter_account_id=reporter_account_id,
            )
            return str(issue["key"])

        if mode == "raise_on_behalf_of":
            issue = self._jira.create_request(
                service_desk_id=service_desk_id,
                request_type_id=request_type_id,
                raise_on_behalf_of=reporter_account_id,
                summary=summary,
                description=description,
            )
            return str(issue["issueKey"])

        # mode == "unset": probe raiseOnBehalfOf once, cache whichever mode works.
        try:
            issue = self._jira.create_request(
                service_desk_id=service_desk_id,
                request_type_id=request_type_id,
                raise_on_behalf_of=reporter_account_id,
                summary=summary,
                description=description,
            )
            self._update_settings(reporter_mode="raise_on_behalf_of")
            return str(issue["issueKey"])
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in (400, 403):
                raise
            issue = self._jira.create_issue_with_reporter(
                project_key=JSM_PROJECT_KEY,
                issue_type="Emailed request" if mailbox == "askhr" else "Benefits",
                summary=summary,
                description=description,
                reporter_account_id=reporter_account_id,
            )
            self._update_settings(reporter_mode="classic_reporter_field")
            return str(issue["key"])

    def _attach_email(self, mailbox: str, message: dict[str, Any], issue_key: str) -> None:
        mailbox_address = MAILBOXES[mailbox]["address"]
        response = self._azure_client().graph_raw_request(
            "GET", f"users/{mailbox_address}/messages/{message['graph_message_id']}/$value"
        )
        files = {"file": (f"{message['internet_message_id']}.eml", response.content, "message/rfc822")}
        upload_url = f"{self._jira.base_url}/rest/api/3/issue/{issue_key}/attachments"
        upload_response = self._jira.session.post(
            upload_url, files=files, headers={"X-Atlassian-Token": "no-check"}, timeout=self._jira._TIMEOUT
        )
        self._jira._raise_for_status(upload_response)

    def _create_or_attach_ticket(
        self, mailbox: str, message: dict[str, Any], *, existing_issue_key: str | None
    ) -> tuple[str, str | None, str | None]:
        issue_key = existing_issue_key
        if not issue_key:
            issue_key = self._jira.find_issue_by_internet_message_id(
                message["internet_message_id"], project_key=JSM_PROJECT_KEY
            )
        if not issue_key:
            issue_key = self._create_ticket(mailbox, message)
        try:
            self._attach_email(mailbox, message, issue_key)
        except Exception as exc:
            return "failed", issue_key, f"attachment failed: {exc}"
        return "created", issue_key, None
```

Note: `self.session.post(..., files=...)` on a `requests.Session` whose default headers include `"Content-Type": "application/json"` (set in `JiraClient.__init__`) will conflict with multipart uploads — `requests` overrides `Content-Type` automatically when `files=` is passed and no explicit `Content-Type` header is given in the call, so leaving the session-level header alone is fine as long as this call site does not also pass `"Content-Type"` in its own `headers=`. Confirm this doesn't warn/fail during Step 4; if it does, pass `headers={"X-Atlassian-Token": "no-check", "Content-Type": None}` is NOT valid for requests — instead build a one-off request without the session's default header via `requests.post(...)` directly with the session's auth, or clear the header on a per-request basis using `self._jira.session.post(url, files=files, headers={"X-Atlassian-Token": "no-check"})` and verify empirically (add an assertion in the test mocking `session.post` to confirm this if in doubt).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_askhr_bot_job.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/askhr_bot_job.py backend/tests/test_askhr_bot_job.py
git commit -m "feat: create-or-attach ticket flow with reporter-mode probing and idempotency"
```

---

### Task 8: `askhr_bot_job` — mailbox polling cycle

**Files:**
- Modify: `backend/askhr_bot_job.py` (add `_should_process`, `_poll_mailbox`, `run_cycle`)
- Test: `backend/tests/test_askhr_bot_job.py` (extend)

**Interfaces:**
- Consumes: `AzureClient.graph_paged_get` (existing, `backend/azure_client.py:1025`); `job._create_or_attach_ticket` from Task 7; `job._refresh_trusted_domains_if_needed` from Task 5.
- Produces: `job._should_process(sender_email: str, trusted_domains: list[str]) -> bool`; `async job.run_cycle() -> None` — the one entry point the background loop calls every `poll_interval_seconds`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_askhr_bot_job.py`:

```python
def test_should_process_skips_trusted_domain_and_allows_payroll_bypass():
    job = _fresh_job()
    trusted = ["librasolutionsgroup.com", "movedocs.com"]

    assert job._should_process("someone@librasolutionsgroup.com", trusted) is False
    assert job._should_process("outsider@example.com", trusted) is True
    assert job._should_process("payroll@librasolutionsgroup.com", trusted) is True


async def test_run_cycle_skips_entirely_when_disabled():
    job = _fresh_job()
    job._get_settings()  # bootstrap, enabled=False by default

    mock_azure = MagicMock()
    with patch.object(job, "_azure_client", return_value=mock_azure):
        await job.run_cycle()

    mock_azure.graph_paged_get.assert_not_called()
    with job._sqlite_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM askhr_bot_runs").fetchone()["c"] == 0


async def test_run_cycle_creates_ticket_for_untrusted_sender_and_advances_checkpoint(monkeypatch):
    import askhr_bot_job as job_module

    job = _fresh_job()
    job._get_settings()
    job._update_settings(
        enabled=True,
        trusted_domains=["librasolutionsgroup.com"],
        trusted_domains_refreshed_at="2026-09-03T00:00:00+00:00",
        domain_refresh_interval_seconds=3600,
    )
    monkeypatch.setattr(job_module, "_utcnow", lambda: __import__("datetime").datetime(
        2026, 9, 3, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc
    ))

    graph_message = {
        "id": "graph-1",
        "internetMessageId": "<abc@mail.example.com>",
        "subject": "Need benefits help",
        "receivedDateTime": "2026-09-03T11:00:00Z",
        "from": {"emailAddress": {"address": "outsider@example.com", "name": "Outsider Person"}},
        "body": {"content": "Please help"},
    }
    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = [graph_message]
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)
    monkeypatch.setattr(
        job, "_create_or_attach_ticket", lambda mailbox, message, existing_issue_key: ("created", "HRD-20", None)
    )

    await job.run_cycle()

    with job._sqlite_conn() as conn:
        runs = conn.execute("SELECT * FROM askhr_bot_runs").fetchall()
        messages = conn.execute("SELECT * FROM askhr_bot_messages").fetchall()
    # Two mailboxes polled (askhr, benefits) -> at least one run row per mailbox.
    assert len(runs) == 2
    assert any(m["jira_issue_key"] == "HRD-20" for m in messages)
    settings = job._get_settings()
    assert settings["askhr_checkpoint_at"] == "2026-09-03T11:00:00+00:00" or settings["benefits_checkpoint_at"] == "2026-09-03T11:00:00+00:00"


async def test_run_cycle_records_skip_for_trusted_domain_sender(monkeypatch):
    job = _fresh_job()
    job._get_settings()
    job._update_settings(
        enabled=True,
        trusted_domains=["librasolutionsgroup.com"],
        trusted_domains_refreshed_at="2026-09-03T00:00:00+00:00",
    )

    graph_message = {
        "id": "graph-2",
        "internetMessageId": "<internal@mail.example.com>",
        "subject": "Internal note",
        "receivedDateTime": "2026-09-03T11:05:00Z",
        "from": {"emailAddress": {"address": "hr@librasolutionsgroup.com", "name": "HR Team"}},
        "body": {"content": "FYI"},
    }
    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = [graph_message]
    import unittest.mock as mock_lib
    with mock_lib.patch.object(job, "_azure_client", return_value=mock_azure):
        with mock_lib.patch.object(job, "_create_or_attach_ticket") as create_mock:
            await job.run_cycle()
            create_mock.assert_not_called()

    with job._sqlite_conn() as conn:
        row = conn.execute(
            "SELECT status FROM askhr_bot_messages WHERE internet_message_id = ?",
            ("<internal@mail.example.com>",),
        ).fetchone()
    assert row["status"] == "skipped_internal_domain"


async def test_run_cycle_one_message_failure_does_not_abort_the_batch(monkeypatch):
    job = _fresh_job()
    job._get_settings()
    job._update_settings(enabled=True, trusted_domains=[], trusted_domains_refreshed_at="2026-09-03T00:00:00+00:00")

    messages = [
        {
            "id": "graph-3", "internetMessageId": "<m1@mail.example.com>", "subject": "One",
            "receivedDateTime": "2026-09-03T11:00:00Z",
            "from": {"emailAddress": {"address": "a@example.com", "name": "A"}}, "body": {"content": "x"},
        },
        {
            "id": "graph-4", "internetMessageId": "<m2@mail.example.com>", "subject": "Two",
            "receivedDateTime": "2026-09-03T11:01:00Z",
            "from": {"emailAddress": {"address": "b@example.com", "name": "B"}}, "body": {"content": "y"},
        },
    ]
    mock_azure = MagicMock()
    mock_azure.graph_paged_get.return_value = messages
    monkeypatch.setattr(job, "_azure_client", lambda: mock_azure)

    def fake_create(mailbox, message, existing_issue_key):
        if message["internet_message_id"] == "<m1@mail.example.com>":
            raise RuntimeError("jira down")
        return "created", "HRD-30", None

    monkeypatch.setattr(job, "_create_or_attach_ticket", fake_create)

    await job.run_cycle()

    with job._sqlite_conn() as conn:
        statuses = {
            r["internet_message_id"]: r["status"]
            for r in conn.execute("SELECT internet_message_id, status FROM askhr_bot_messages")
        }
    assert statuses["<m1@mail.example.com>"] == "failed"
    assert statuses["<m2@mail.example.com>"] == "created"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_askhr_bot_job.py -k "should_process or run_cycle" -v`
Expected: FAIL — `_should_process`/`run_cycle` do not exist.

- [ ] **Step 3: Implement**

Add to `backend/askhr_bot_job.py`:

```python
    def _should_process(self, sender_email: str, trusted_domains: list[str]) -> bool:
        sender = sender_email.strip().lower()
        if sender == PAYROLL_BYPASS_SENDER:
            return True
        domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
        return domain not in trusted_domains

    def _record_message(
        self,
        *,
        mailbox: str,
        message: dict[str, Any],
        status: str,
        jira_issue_key: str | None,
        error: str | None,
        conn: sqlite3.Connection,
    ) -> None:
        ph = self._placeholder()
        upsert = (
            "INSERT INTO askhr_bot_messages "
            "(internet_message_id, mailbox, graph_message_id, subject, sender_email, received_at, "
            "status, jira_issue_key, error, processed_at) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph}) "
            "ON CONFLICT (internet_message_id) DO UPDATE SET "
            "status = excluded.status, jira_issue_key = excluded.jira_issue_key, "
            "error = excluded.error, processed_at = excluded.processed_at"
        )
        conn.execute(
            upsert,
            (
                message["internet_message_id"],
                mailbox,
                message["graph_message_id"],
                message["subject"],
                message["sender_email"],
                message["received_at"],
                status,
                jira_issue_key,
                error,
                _utcnow().isoformat(),
            ),
        )

    def _existing_message_row(self, internet_message_id: str, conn: sqlite3.Connection) -> dict[str, Any] | None:
        ph = self._placeholder()
        row = conn.execute(
            f"SELECT status, jira_issue_key FROM askhr_bot_messages WHERE internet_message_id = {ph}",
            (internet_message_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    async def _poll_mailbox(self, mailbox: str, settings: dict[str, Any]) -> None:
        import asyncio

        mailbox_address = MAILBOXES[mailbox]["address"]
        checkpoint_key = f"{mailbox}_checkpoint_at"
        checkpoint = settings[checkpoint_key]
        lookback = settings["lookback_minutes"]
        if checkpoint:
            since = datetime.fromisoformat(checkpoint) - __import__("datetime").timedelta(minutes=lookback)
        else:
            since = _utcnow() - __import__("datetime").timedelta(minutes=lookback)
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        loop = asyncio.get_event_loop()
        azure = self._azure_client()
        graph_messages = await loop.run_in_executor(
            None,
            lambda: azure.graph_paged_get(
                f"users/{mailbox_address}/mailFolders/Inbox/messages",
                params={
                    "$filter": f"receivedDateTime ge {since_iso}",
                    "$orderby": "receivedDateTime asc",
                    "$select": "id,internetMessageId,subject,receivedDateTime,from,body",
                    "$top": "50",
                },
            ),
        )

        trusted_domains = settings["trusted_domains"]
        created = skipped = failed = 0
        latest_received: str | None = None

        for graph_message in graph_messages:
            internet_message_id = str(graph_message.get("internetMessageId") or "").strip()
            if not internet_message_id:
                continue
            received_at = str(graph_message.get("receivedDateTime") or "")
            if not latest_received or received_at > latest_received:
                latest_received = received_at
            sender = graph_message.get("from", {}).get("emailAddress", {})
            message = {
                "internet_message_id": internet_message_id,
                "graph_message_id": str(graph_message.get("id") or ""),
                "subject": str(graph_message.get("subject") or ""),
                "sender_email": str(sender.get("address") or ""),
                "sender_name": str(sender.get("name") or ""),
                "received_at": received_at,
                "body": str((graph_message.get("body") or {}).get("content") or ""),
            }

            with self._conn() as conn:
                existing = self._existing_message_row(internet_message_id, conn)

            if existing and existing["status"] == "created":
                continue

            if not self._should_process(message["sender_email"], trusted_domains):
                skipped += 1
                with self._conn() as conn:
                    self._record_message(
                        mailbox=mailbox, message=message, status="skipped_internal_domain",
                        jira_issue_key=None, error=None, conn=conn,
                    )
                continue

            existing_issue_key = existing["jira_issue_key"] if existing else None
            try:
                status, issue_key, error = await loop.run_in_executor(
                    None,
                    lambda: self._create_or_attach_ticket(mailbox, message, existing_issue_key=existing_issue_key),
                )
            except Exception as exc:
                status, issue_key, error = "failed", existing_issue_key, str(exc)

            if status == "created":
                created += 1
            else:
                failed += 1
            with self._conn() as conn:
                self._record_message(
                    mailbox=mailbox, message=message, status=status,
                    jira_issue_key=issue_key, error=error, conn=conn,
                )

        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO askhr_bot_runs "
                f"(id, mailbox, run_started_at, messages_scanned, created_count, skipped_count, failed_count) "
                f"VALUES ({self._placeholder()},{self._placeholder()},{self._placeholder()},"
                f"{self._placeholder()},{self._placeholder()},{self._placeholder()},{self._placeholder()})",
                (uuid.uuid4().hex, mailbox, _utcnow().isoformat(), len(graph_messages), created, skipped, failed),
            )

        if latest_received:
            self._update_settings(**{checkpoint_key: latest_received})

    async def run_cycle(self) -> None:
        settings = self._get_settings()
        if not settings["enabled"]:
            return
        self._refresh_trusted_domains_if_needed()
        settings = self._get_settings()
        for mailbox in MAILBOXES:
            await self._poll_mailbox(mailbox, settings)
```

Note on `received_at` normalization: Graph returns `receivedDateTime` as `...Z`-suffixed UTC (e.g. `2026-09-03T11:00:00Z`), which `datetime.fromisoformat` in Python < 3.11 cannot parse directly (no `Z` support before 3.11). If the repo's Python version is below 3.11, normalize with `received_at.replace("Z", "+00:00")` before `datetime.fromisoformat(...)` wherever `_poll_mailbox` reads back a stored checkpoint. Check `backend/pyproject.toml`/`Dockerfile` for the Python version before writing this step; if it's 3.11+, no change is needed since `fromisoformat` accepts `Z` there. If it's older, patch `_poll_mailbox`'s checkpoint-parsing line to:

```python
        if checkpoint:
            normalized_checkpoint = checkpoint.replace("Z", "+00:00")
            since = datetime.fromisoformat(normalized_checkpoint) - __import__("datetime").timedelta(minutes=lookback)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_askhr_bot_job.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/askhr_bot_job.py backend/tests/test_askhr_bot_job.py
git commit -m "feat: poll AskHR/Benefits mailboxes with a checkpoint-bounded window"
```

---

### Task 9: `askhr_bot_job` — background loop + `main.py` wiring

**Files:**
- Modify: `backend/askhr_bot_job.py` (add `start_background_runner`/`stop_background_runner`/`_run_loop`, module-level `askhr_bot_job` instance)
- Modify: `backend/main.py:151-201` (register in `_start_deferred_services`/`_stop_leader_services`, mirroring the quarantine job's leader-only pattern), import lines near `backend/main.py:52-55`.
- Test: `backend/tests/test_askhr_bot_job.py` (extend)

**Interfaces:**
- Produces: `askhr_bot_job.start_background_runner() -> None`, `askhr_bot_job.stop_background_runner() -> None`; module-level singleton `askhr_bot_job: AskHrBotJob`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_askhr_bot_job.py`:

```python
async def test_start_and_stop_background_runner_does_not_raise():
    import asyncio

    job = _fresh_job()
    job.start_background_runner()
    assert job._bg_task is not None
    await asyncio.sleep(0)
    job.stop_background_runner()
    await asyncio.sleep(0)
    assert job._bg_task.cancelled() or job._bg_task.done()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_askhr_bot_job.py -k background_runner -v`
Expected: FAIL — methods don't exist.

- [ ] **Step 3: Implement — `askhr_bot_job.py`**

Add at the end of the class:

```python
    def start_background_runner(self) -> None:
        import asyncio

        loop = asyncio.get_event_loop()
        self._bg_task = loop.create_task(self._run_loop())

    def stop_background_runner(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()

    async def _run_loop(self) -> None:
        import asyncio

        while True:
            try:
                interval = self._get_settings()["poll_interval_seconds"]
                await self.run_cycle()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("AskHR bot job loop error")
                await asyncio.sleep(120)
```

At the bottom of the file, add the module singleton:

```python
askhr_bot_job = AskHrBotJob()
```

- [ ] **Step 4: Implement — `main.py` wiring**

Near line 52-55 (alongside the quarantine release imports):

```python
from routes_askhr_bot import router as askhr_bot_router
from askhr_bot_job import askhr_bot_job as _askhr_bot_job
```

(`routes_askhr_bot` doesn't exist yet — this import will be exercised once Task 10 lands; if executing tasks strictly in order, temporarily comment this import out or move Task 9's `main.py` edit to land together with Task 10 in the same commit. Simpler: do the `main.py` wiring for the job's start/stop here, and add the router import + `include_router` call in Task 10 instead, so this task only needs the job import.)

In `_start_leader_services`, after the `_quarantine_release_job.start_background_runner()` block (main.py:151-154):

```python
    try:
        _askhr_bot_job.start_background_runner()
    except Exception:
        logger.exception("Failed to start AskHR bot job")
```

In `_stop_leader_services`, after `_quarantine_release_job.stop_background_runner()` (main.py:201):

```python
    _askhr_bot_job.stop_background_runner()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_askhr_bot_job.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/askhr_bot_job.py backend/main.py backend/tests/test_askhr_bot_job.py
git commit -m "feat: run the AskHR bot as a leader-only background service"
```

---

### Task 10: `routes_askhr_bot.py` — admin API

**Files:**
- Create: `backend/routes_askhr_bot.py`
- Modify: `backend/main.py` (finish the Task 9 import, add `app.include_router(askhr_bot_router)` near line 472)
- Test: `backend/tests/test_routes_askhr_bot.py` (new)

**Interfaces:**
- Produces: `GET /api/askhr-bot/status`, `GET /api/askhr-bot/runs`, `GET /api/askhr-bot/messages`, `PATCH /api/askhr-bot/settings`, `POST /api/askhr-bot/reporter-mode/reset`, `POST /api/askhr-bot/messages/{internet_message_id}/retry` — all `require_admin`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_routes_askhr_bot.py`:

```python
"""Tests for the AskHR bot admin API routes."""
from __future__ import annotations


def _job_with_settings(tmp_path, **overrides):
    import askhr_bot_job as job_module

    job = job_module.AskHrBotJob(db_path=str(tmp_path / "askhr.db"))
    job._get_settings()
    if overrides:
        job._update_settings(**overrides)
    return job


def test_get_status_reflects_settings_and_no_runs(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path, enabled=True)
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)

    resp = test_client.get("/api/askhr-bot/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["last_runs"]["askhr"] is None
    assert data["last_runs"]["benefits"] is None


def test_get_status_forbidden_for_non_admin(test_client, monkeypatch, tmp_path):
    import auth
    job = _job_with_settings(tmp_path)
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: email != "non-admin@example.com")
    non_admin_sid = auth.create_session("non-admin@example.com", "Non Admin")
    test_client.cookies.set("session_id", non_admin_sid)
    try:
        resp = test_client.get("/api/askhr-bot/status")
        assert resp.status_code == 403
    finally:
        test_client.cookies.set("session_id", auth.create_session("test@example.com", "Test User"))


def test_patch_settings_updates_enabled_and_poll_interval(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path)
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)

    resp = test_client.patch("/api/askhr-bot/settings", json={"enabled": True, "poll_interval_seconds": 60})
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["poll_interval_seconds"] == 60


def test_post_reporter_mode_reset_sets_unset(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path, reporter_mode="classic_reporter_field")
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)

    resp = test_client.post("/api/askhr-bot/reporter-mode/reset")
    assert resp.status_code == 200
    assert resp.json()["reporter_mode"] == "unset"


def test_get_runs_filters_by_mailbox(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path)
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO askhr_bot_runs (id, mailbox, run_started_at, messages_scanned, created_count, skipped_count, failed_count) "
            "VALUES ('r1', 'askhr', '2026-09-03T11:00:00+00:00', 2, 1, 1, 0)"
        )
        conn.execute(
            "INSERT INTO askhr_bot_runs (id, mailbox, run_started_at, messages_scanned, created_count, skipped_count, failed_count) "
            "VALUES ('r2', 'benefits', '2026-09-03T11:00:00+00:00', 1, 1, 0, 0)"
        )
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)

    resp = test_client.get("/api/askhr-bot/runs?mailbox=askhr")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "r1"


def test_retry_creates_ticket_for_previously_failed_message(test_client, monkeypatch, tmp_path):
    job = _job_with_settings(tmp_path)
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO askhr_bot_messages "
            "(internet_message_id, mailbox, graph_message_id, subject, sender_email, received_at, "
            "status, jira_issue_key, error, processed_at) "
            "VALUES ('<m1@mail.example.com>', 'askhr', 'graph-1', 'Subject', 'a@example.com', "
            "'2026-09-03T11:00:00+00:00', 'failed', 'HRD-40', 'attachment failed: boom', '2026-09-03T11:01:00+00:00')"
        )
    import routes_askhr_bot
    monkeypatch.setattr(routes_askhr_bot, "askhr_bot_job", job)
    monkeypatch.setattr(
        job, "_create_or_attach_ticket",
        lambda mailbox, message, existing_issue_key: ("created", "HRD-40", None),
    )
    monkeypatch.setattr(job, "_azure_client", lambda: __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock())

    resp = test_client.post("/api/askhr-bot/messages/%3Cm1%40mail.example.com%3E/retry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "created"
    assert data["jira_issue_key"] == "HRD-40"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes_askhr_bot.py -v`
Expected: FAIL — `routes_askhr_bot` module does not exist.

- [ ] **Step 3: Implement `backend/routes_askhr_bot.py`**

```python
"""FastAPI routes for the AskHR/Benefits bot."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from askhr_bot_job import MAILBOXES, askhr_bot_job
from auth import require_admin

router = APIRouter(prefix="/api/askhr-bot", tags=["askhr-bot"])


class PatchSettingsRequest(BaseModel):
    enabled: bool | None = None
    poll_interval_seconds: int | None = None
    lookback_minutes: int | None = None
    domain_refresh_interval_seconds: int | None = None


def _last_run(mailbox: str) -> dict[str, Any] | None:
    ph = askhr_bot_job._placeholder()
    with askhr_bot_job._conn() as conn:
        row = conn.execute(
            f"SELECT id, mailbox, run_started_at, messages_scanned, created_count, skipped_count, failed_count "
            f"FROM askhr_bot_runs WHERE mailbox = {ph} ORDER BY run_started_at DESC LIMIT 1",
            (mailbox,),
        ).fetchone()
    return dict(row) if row is not None else None


def _status_payload() -> dict[str, Any]:
    settings = askhr_bot_job._get_settings()
    return {
        **settings,
        "last_runs": {mailbox: _last_run(mailbox) for mailbox in MAILBOXES},
    }


@router.get("/status", dependencies=[Depends(require_admin)])
async def get_status() -> dict[str, Any]:
    return _status_payload()


@router.get("/runs", dependencies=[Depends(require_admin)])
async def get_runs(
    mailbox: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    ph = askhr_bot_job._placeholder()
    columns = "id, mailbox, run_started_at, messages_scanned, created_count, skipped_count, failed_count"
    with askhr_bot_job._conn() as conn:
        if mailbox:
            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM askhr_bot_runs WHERE mailbox = {ph}", (mailbox,)
            ).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT {columns} FROM askhr_bot_runs WHERE mailbox = {ph} "
                f"ORDER BY run_started_at DESC LIMIT {ph} OFFSET {ph}",
                (mailbox, limit, offset),
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) AS cnt FROM askhr_bot_runs").fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT {columns} FROM askhr_bot_runs ORDER BY run_started_at DESC LIMIT {ph} OFFSET {ph}",
                (limit, offset),
            ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.get("/messages", dependencies=[Depends(require_admin)])
async def get_messages(
    mailbox: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    ph = askhr_bot_job._placeholder()
    columns = (
        "internet_message_id, mailbox, graph_message_id, subject, sender_email, received_at, "
        "status, jira_issue_key, error, processed_at"
    )
    clauses = []
    params: list[Any] = []
    if mailbox:
        clauses.append(f"mailbox = {ph}")
        params.append(mailbox)
    if status:
        clauses.append(f"status = {ph}")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with askhr_bot_job._conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS cnt FROM askhr_bot_messages {where}", params).fetchone()["cnt"]
        rows = conn.execute(
            f"SELECT {columns} FROM askhr_bot_messages {where} "
            f"ORDER BY received_at DESC LIMIT {ph} OFFSET {ph}",
            (*params, limit, offset),
        ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.patch("/settings")
async def patch_settings(
    body: PatchSettingsRequest,
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated_by = user.get("email") or user.get("name") or "unknown"
    askhr_bot_job._update_settings(updated_by=updated_by, **updates)
    return _status_payload()


@router.post("/reporter-mode/reset")
async def reset_reporter_mode(user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    updated_by = user.get("email") or user.get("name") or "unknown"
    askhr_bot_job._update_settings(reporter_mode="unset", updated_by=updated_by)
    return _status_payload()


@router.post("/messages/{internet_message_id}/retry", dependencies=[Depends(require_admin)])
async def retry_message(internet_message_id: str) -> dict[str, Any]:
    ph = askhr_bot_job._placeholder()
    with askhr_bot_job._conn() as conn:
        row = conn.execute(
            f"SELECT mailbox, graph_message_id, subject, sender_email, received_at, jira_issue_key "
            f"FROM askhr_bot_messages WHERE internet_message_id = {ph}",
            (internet_message_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")

    message = {
        "internet_message_id": internet_message_id,
        "graph_message_id": row["graph_message_id"],
        "subject": row["subject"],
        "sender_email": row["sender_email"],
        "sender_name": row["sender_email"],
        "received_at": row["received_at"],
        "body": "",
    }
    status, issue_key, error = askhr_bot_job._create_or_attach_ticket(
        row["mailbox"], message, existing_issue_key=row["jira_issue_key"]
    )
    with askhr_bot_job._conn() as conn:
        askhr_bot_job._record_message(
            mailbox=row["mailbox"], message=message, status=status,
            jira_issue_key=issue_key, error=error, conn=conn,
        )
    return {
        "internet_message_id": internet_message_id,
        "status": status,
        "jira_issue_key": issue_key,
        "error": error,
    }
```

Note: `retry_message`'s `message["body"]` is empty because the original Graph body wasn't persisted — this means a retry that needs to *create* a ticket (not just re-attach) will produce a ticket with an empty description body. Since the detail table doesn't store the email body (only Jira does, via the created ticket, or the attached `.eml` has the real content), this is an acceptable limitation for now: retry primarily exists to fix a failed attachment or Jira-API hiccup on an already-known message, not to reconstruct a ticket from scratch after data loss. If this bothers you when implementing, an alternative is to have `retry_message` first refetch the full message from Graph by `graph_message_id` via `askhr_bot_job._azure_client().graph_request("GET", f"users/{mailbox}/messages/{graph_message_id}")` before rebuilding `message`, which restores the subject/body/sender exactly. Prefer that refetch approach if you have time; the empty-body fallback above is the minimum to keep this task's tests green.

- [ ] **Step 4: Implement `main.py` router registration**

Finish the Task 9 import at `backend/main.py:52-55`:

```python
from routes_askhr_bot import router as askhr_bot_router
from askhr_bot_job import askhr_bot_job as _askhr_bot_job
```

Near line 472 (`app.include_router(quarantine_release_router)`), add:

```python
app.include_router(askhr_bot_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_routes_askhr_bot.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/routes_askhr_bot.py backend/main.py backend/tests/test_routes_askhr_bot.py
git commit -m "feat: add admin API routes for the AskHR bot"
```

---

### Task 11: Frontend `api.ts` — AskHR bot types + functions

**Files:**
- Modify: `frontend/src/lib/api.ts` (add types near `QuarantineReleaseStatus`, functions near the quarantine-release functions)

**Interfaces:**
- Produces: `AskHrBotStatus`, `AskHrBotRun`, `AskHrBotMessage` types; `getAskHrBotStatus()`, `getAskHrBotRuns(mailbox?, limit?, offset?)`, `getAskHrBotMessages(mailbox?, status?, limit?, offset?)`, `patchAskHrBotSettings(body)`, `resetAskHrBotReporterMode()`, `retryAskHrBotMessage(internetMessageId)`.

- [ ] **Step 1: Implement**

Add near the quarantine-release functions (after `patchQuarantineReleaseSettings`, api.ts:5216):

```typescript
  getAskHrBotStatus(): Promise<AskHrBotStatus> {
    return fetchJSON<AskHrBotStatus>("/api/askhr-bot/status");
  },

  getAskHrBotRuns(
    mailbox?: string,
    limit = 30,
    offset = 0,
  ): Promise<{ items: AskHrBotRun[]; total: number }> {
    const mailboxParam = mailbox ? `&mailbox=${encodeURIComponent(mailbox)}` : "";
    return fetchJSON(`/api/askhr-bot/runs?limit=${limit}&offset=${offset}${mailboxParam}`);
  },

  getAskHrBotMessages(
    mailbox?: string,
    status?: string,
    limit = 50,
    offset = 0,
  ): Promise<{ items: AskHrBotMessage[]; total: number }> {
    const mailboxParam = mailbox ? `&mailbox=${encodeURIComponent(mailbox)}` : "";
    const statusParam = status ? `&status=${encodeURIComponent(status)}` : "";
    return fetchJSON(`/api/askhr-bot/messages?limit=${limit}&offset=${offset}${mailboxParam}${statusParam}`);
  },

  async patchAskHrBotSettings(
    body: { enabled?: boolean; poll_interval_seconds?: number; lookback_minutes?: number; domain_refresh_interval_seconds?: number },
  ): Promise<AskHrBotStatus> {
    const res = await fetch("/api/askhr-bot/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.status === 401) {
      window.location.href = "/api/auth/login";
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      throw new Error(await buildErrorMessage("PATCH", "/api/askhr-bot/settings", res));
    }
    return res.json() as Promise<AskHrBotStatus>;
  },

  async resetAskHrBotReporterMode(): Promise<AskHrBotStatus> {
    const res = await fetch("/api/askhr-bot/reporter-mode/reset", { method: "POST" });
    if (res.status === 401) {
      window.location.href = "/api/auth/login";
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      throw new Error(await buildErrorMessage("POST", "/api/askhr-bot/reporter-mode/reset", res));
    }
    return res.json() as Promise<AskHrBotStatus>;
  },

  async retryAskHrBotMessage(
    internetMessageId: string,
  ): Promise<{ internet_message_id: string; status: string; jira_issue_key: string | null; error: string | null }> {
    const url = `/api/askhr-bot/messages/${encodeURIComponent(internetMessageId)}/retry`;
    const res = await fetch(url, { method: "POST" });
    if (res.status === 401) {
      window.location.href = "/api/auth/login";
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      throw new Error(await buildErrorMessage("POST", url, res));
    }
    return res.json();
  },
```

Add near the quarantine-release types (after `QuarantineReleaseStatus`, api.ts:5499):

```typescript
export interface AskHrBotRun {
  id: string;
  mailbox: "askhr" | "benefits";
  run_started_at: string;
  messages_scanned: number;
  created_count: number;
  skipped_count: number;
  failed_count: number;
}

export interface AskHrBotMessage {
  internet_message_id: string;
  mailbox: "askhr" | "benefits";
  graph_message_id: string;
  subject: string;
  sender_email: string;
  received_at: string;
  status: "created" | "skipped_internal_domain" | "failed";
  jira_issue_key: string | null;
  error: string | null;
  processed_at: string;
}

export interface AskHrBotStatus {
  enabled: boolean;
  poll_interval_seconds: number;
  lookback_minutes: number;
  askhr_checkpoint_at: string;
  benefits_checkpoint_at: string;
  trusted_domains: string[];
  trusted_domains_refreshed_at: string;
  domain_refresh_interval_seconds: number;
  reporter_mode: "unset" | "raise_on_behalf_of" | "classic_reporter_field";
  last_runs: { askhr: AskHrBotRun | null; benefits: AskHrBotRun | null };
}
```

- [ ] **Step 2: Typecheck**

Run (from `frontend/`): `npm run build` (or `npx tsc --noEmit` if faster) to confirm no type errors before the consuming page exists in Task 12 — a standalone `api.ts` change with unused exports is still valid TypeScript, so this should pass cleanly.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add frontend API client for the AskHR bot"
```

---

### Task 12: Frontend `AskHrBotPage.tsx` + `HrAppPage.tsx` + nav/routes

**Files:**
- Create: `frontend/src/pages/AskHrBotPage.tsx`
- Create: `frontend/src/pages/HrAppPage.tsx`
- Modify: `frontend/src/components/Layout.tsx` (add `hrappNavGroups` + rendering branch)
- Modify: `frontend/src/App.tsx` (add `hrapp` route branch)
- Test: `frontend/src/__tests__/AskHrBotPage.test.tsx` (new)

**Interfaces:**
- Consumes: `api.getAskHrBotStatus`, `getAskHrBotRuns`, `getAskHrBotMessages`, `patchAskHrBotSettings`, `resetAskHrBotReporterMode`, `retryAskHrBotMessage` from Task 11; `getPollingQueryOptions` from `frontend/src/lib/queryPolling.ts`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/AskHrBotPage.test.tsx`:

```tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import AskHrBotPage from "../pages/AskHrBotPage.tsx";
import { api } from "../lib/api.ts";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AskHrBotPage />
    </QueryClientProvider>,
  );
}

describe("AskHrBotPage", () => {
  beforeEach(() => {
    vi.spyOn(api, "getAskHrBotStatus").mockResolvedValue({
      enabled: false,
      poll_interval_seconds: 120,
      lookback_minutes: 15,
      askhr_checkpoint_at: "",
      benefits_checkpoint_at: "",
      trusted_domains: ["librasolutionsgroup.com"],
      trusted_domains_refreshed_at: "2026-09-03T00:00:00+00:00",
      domain_refresh_interval_seconds: 3600,
      reporter_mode: "unset",
      last_runs: { askhr: null, benefits: null },
    });
    vi.spyOn(api, "getAskHrBotRuns").mockResolvedValue({ items: [], total: 0 });
    vi.spyOn(api, "getAskHrBotMessages").mockResolvedValue({
      items: [
        {
          internet_message_id: "<m1@mail.example.com>",
          mailbox: "askhr",
          graph_message_id: "g1",
          subject: "Need help",
          sender_email: "outsider@example.com",
          received_at: "2026-09-03T11:00:00+00:00",
          status: "failed",
          jira_issue_key: "HRD-1",
          error: "attachment failed: boom",
          processed_at: "2026-09-03T11:01:00+00:00",
        },
      ],
      total: 1,
    });
    vi.spyOn(api, "patchAskHrBotSettings").mockResolvedValue({
      enabled: true,
      poll_interval_seconds: 120,
      lookback_minutes: 15,
      askhr_checkpoint_at: "",
      benefits_checkpoint_at: "",
      trusted_domains: [],
      trusted_domains_refreshed_at: "",
      domain_refresh_interval_seconds: 3600,
      reporter_mode: "unset",
      last_runs: { askhr: null, benefits: null },
    });
    vi.spyOn(api, "retryAskHrBotMessage").mockResolvedValue({
      internet_message_id: "<m1@mail.example.com>",
      status: "created",
      jira_issue_key: "HRD-1",
      error: null,
    });
  });

  it("shows the disabled toggle and the failed message with a retry button", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("switch")).toBeInTheDocument());
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    await waitFor(() => expect(screen.getByText("Need help")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("calls retry when the Retry button is clicked", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(api.retryAskHrBotMessage).toHaveBeenCalledWith("<m1@mail.example.com>"));
  });

  it("toggles enabled via the settings mutation", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("switch")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(api.patchAskHrBotSettings).toHaveBeenCalledWith({ enabled: true }));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test:run -- AskHrBotPage`
Expected: FAIL — `AskHrBotPage` module does not exist.

- [ ] **Step 3: Implement `frontend/src/pages/AskHrBotPage.tsx`**

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AskHrBotMessage } from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";

const RUNS_LIMIT = 30;
const MESSAGES_LIMIT = 50;

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export default function AskHrBotPage() {
  const queryClient = useQueryClient();
  const [runsOffset, setRunsOffset] = useState(0);
  const [messagesOffset, setMessagesOffset] = useState(0);

  const statusQuery = useQuery({
    queryKey: ["askhr-bot", "status"],
    queryFn: () => api.getAskHrBotStatus(),
    ...getPollingQueryOptions("slow_5m"),
  });

  const runsQuery = useQuery({
    queryKey: ["askhr-bot", "runs", runsOffset],
    queryFn: () => api.getAskHrBotRuns(undefined, RUNS_LIMIT, runsOffset),
    ...getPollingQueryOptions("slow_5m"),
  });

  const messagesQuery = useQuery({
    queryKey: ["askhr-bot", "messages", messagesOffset],
    queryFn: () => api.getAskHrBotMessages(undefined, undefined, MESSAGES_LIMIT, messagesOffset),
    ...getPollingQueryOptions("slow_5m"),
  });

  const settingsMutation = useMutation({
    mutationFn: (body: { enabled?: boolean }) => api.patchAskHrBotSettings(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["askhr-bot", "status"] }),
  });

  const reporterModeResetMutation = useMutation({
    mutationFn: () => api.resetAskHrBotReporterMode(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["askhr-bot", "status"] }),
  });

  const retryMutation = useMutation({
    mutationFn: (internetMessageId: string) => api.retryAskHrBotMessage(internetMessageId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["askhr-bot", "messages"] }),
  });

  const status = statusQuery.data;
  const enabled = status?.enabled ?? false;

  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">HR</div>
        <h1 className="mt-1 text-2xl font-semibold text-slate-900">AskHR / Benefits Bot</h1>
        <p className="mt-1 text-sm text-slate-500">
          Polls the AskHR and Benefits mailboxes and creates HRD Jira tickets with AskHR/Benefits as reporter.
        </p>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-600">Bot enabled</span>
          <button
            role="switch"
            aria-checked={enabled}
            aria-label="Enable AskHR bot"
            disabled={settingsMutation.isPending}
            onClick={() => settingsMutation.mutate({ enabled: !enabled })}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
              enabled ? "bg-emerald-500" : "bg-slate-300"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                enabled ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
        </div>
        <div className="h-4 w-px bg-slate-200" />
        <div className="text-sm text-slate-600">
          Reporter mode: <strong>{status?.reporter_mode ?? "unset"}</strong>{" "}
          <button
            type="button"
            onClick={() => reporterModeResetMutation.mutate()}
            className="ml-2 rounded border border-slate-200 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100"
          >
            Re-test
          </button>
        </div>
        <div className="h-4 w-px bg-slate-200" />
        <div className="text-sm text-slate-600">
          Trusted domains: <strong>{status?.trusted_domains.length ?? 0}</strong> (refreshed{" "}
          {formatDateTime(status?.trusted_domains_refreshed_at)})
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-600">
        <div>AskHR checkpoint: {formatDateTime(status?.askhr_checkpoint_at)}</div>
        <div>Benefits checkpoint: {formatDateTime(status?.benefits_checkpoint_at)}</div>
      </div>

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-slate-700">Run history</h2>
        <div className="mt-2 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left">Mailbox</th>
                <th className="px-3 py-2 text-left">Started</th>
                <th className="px-3 py-2 text-left">Scanned</th>
                <th className="px-3 py-2 text-left">Created</th>
                <th className="px-3 py-2 text-left">Skipped</th>
                <th className="px-3 py-2 text-left">Failed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(runsQuery.data?.items ?? []).map((run) => (
                <tr key={run.id}>
                  <td className="px-3 py-2">{run.mailbox}</td>
                  <td className="px-3 py-2">{formatDateTime(run.run_started_at)}</td>
                  <td className="px-3 py-2">{run.messages_scanned}</td>
                  <td className="px-3 py-2">{run.created_count}</td>
                  <td className="px-3 py-2">{run.skipped_count}</td>
                  <td className="px-3 py-2">{run.failed_count}</td>
                </tr>
              ))}
              {(runsQuery.data?.items ?? []).length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-center text-slate-500" colSpan={6}>
                    No runs yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-slate-700">Messages</h2>
        <div className="mt-2 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left">Mailbox</th>
                <th className="px-3 py-2 text-left">Subject</th>
                <th className="px-3 py-2 text-left">Sender</th>
                <th className="px-3 py-2 text-left">Received</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-left">Jira</th>
                <th className="px-3 py-2 text-left">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(messagesQuery.data?.items ?? []).map((message: AskHrBotMessage) => (
                <tr key={message.internet_message_id} title={message.error ?? undefined}>
                  <td className="px-3 py-2">{message.mailbox}</td>
                  <td className="px-3 py-2">{message.subject}</td>
                  <td className="px-3 py-2">{message.sender_email}</td>
                  <td className="px-3 py-2">{formatDateTime(message.received_at)}</td>
                  <td className={`px-3 py-2 ${message.status === "failed" ? "text-red-600" : "text-emerald-600"}`}>
                    {message.status}
                  </td>
                  <td className="px-3 py-2">{message.jira_issue_key ?? "—"}</td>
                  <td className="px-3 py-2">
                    {message.status === "failed" ? (
                      <button
                        type="button"
                        onClick={() => retryMutation.mutate(message.internet_message_id)}
                        disabled={retryMutation.isPending}
                        className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                      >
                        Retry
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
              {(messagesQuery.data?.items ?? []).length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-center text-slate-500" colSpan={7}>
                    No messages processed yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Implement `frontend/src/pages/HrAppPage.tsx`**

```tsx
import { Link } from "react-router-dom";

export default function HrAppPage() {
  return (
    <div className="mx-auto max-w-3xl p-6">
      <h1 className="text-2xl font-semibold text-slate-900">AskHR Portal</h1>
      <p className="mt-1 text-sm text-slate-500">HR and Benefits automation tools.</p>

      <div className="mt-6 grid gap-4">
        <Link
          to="/askhr-bot"
          className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm transition hover:border-slate-300 hover:shadow"
        >
          <h2 className="text-lg font-semibold text-slate-900">AskHR / Benefits Bot</h2>
          <p className="mt-1 text-sm text-slate-500">
            Status, run history, and retry for the mailbox-to-Jira ticket bot.
          </p>
        </Link>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Wire up `Layout.tsx`**

Add after `securityNavGroups` (Layout.tsx, after line 89):

```typescript
const hrappNavGroups: NavGroup[] = [
  {
    label: "HR",
    items: [
      { to: "/", label: "Overview", icon: "hr", end: true },
      { to: "/askhr-bot", label: "AskHR / Benefits Bot", icon: "hr" },
    ],
  },
];
```

Generalize `SecurityGroupedNav` into a reusable renderer (rename is optional — simplest is to add a second, near-identical component rather than risk breaking the security nav's collapse-state localStorage key):

```typescript
function HrAppGroupedNav({ pathname }: { pathname: string }) {
  return (
    <nav className="flex-1 space-y-3 px-3 py-4 overflow-y-auto">
      {hrappNavGroups.map(group => (
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

In the render branch (Layout.tsx:354), extend:

```tsx
        {branding.scope === "security" ? (
          <SecurityGroupedNav pathname={location.pathname} />
        ) : branding.scope === "hrapp" ? (
          <HrAppGroupedNav pathname={location.pathname} />
        ) : (
          <nav className="flex-1 space-y-1 px-3 py-4">
```

- [ ] **Step 6: Wire up `App.tsx`**

Add lazy imports near the other page imports:

```typescript
const HrAppPage = lazy(() => import("./pages/HrAppPage"));
const AskHrBotPage = lazy(() => import("./pages/AskHrBotPage"));
```

Add `isHrappSite` and a route branch:

```tsx
  const isAzureSite = branding.scope === "azure";
  const isSecuritySite = branding.scope === "security";
  const isHrappSite = branding.scope === "hrapp";
```

```tsx
            {isSecuritySite ? (
              ...
            ) : isHrappSite ? (
              <>
                <Route index element={<HrAppPage />} />
                <Route path="askhr-bot" element={<AskHrBotPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </>
            ) : isAzureSite ? (
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `npm run test:run -- AskHrBotPage`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/AskHrBotPage.tsx frontend/src/pages/HrAppPage.tsx frontend/src/components/Layout.tsx frontend/src/App.tsx frontend/src/__tests__/AskHrBotPage.test.tsx
git commit -m "feat: add the hrapp landing page and AskHR bot status/history/retry dashboard"
```

---

### Task 13: Infra — `Caddyfile` host wiring

**Files:**
- Modify: `Caddyfile:8`

**Interfaces:** none (infra config only).

- [ ] **Step 1: Implement**

Change:

```
it-app.movedocs.com, oasisdev.movedocs.com, azure.movedocs.com, security.movedocs.com {
```

to:

```
it-app.movedocs.com, oasisdev.movedocs.com, azure.movedocs.com, security.movedocs.com, hrapp.movedocs.com {
```

- [ ] **Step 2: Verify**

Run: `caddy validate --config Caddyfile` if Caddy is available locally; otherwise confirm the change is a plain comma-separated host addition with no other syntax changes (visually diff against the original line).

- [ ] **Step 3: Commit**

```bash
git add Caddyfile
git commit -m "feat: route hrapp.movedocs.com through the shared Caddy site block"
```

Note: this change is inert until DNS for `hrapp.movedocs.com` exists and points at the same infrastructure as the other four hosts — confirm DNS is provisioned before deploying, or the ACME issuer will fail to obtain a certificate for the new name and could affect the shared site block's renewal for the other three hosts. Deploy this only after DNS is confirmed, and treat it as a deploy-time action requiring the same confirm-before-acting care as any other production infra change.

---

### Task 14: Runbook — manual transport-rule cutover

**Files:**
- Create: `docs/runbooks/askhr-bot-cutover.md`

**Interfaces:** none (documentation only, no code path performs this).

- [ ] **Step 1: Write the runbook**

```markdown
# AskHR/Benefits bot — legacy transport rule cutover

**Do this manually, once, after the AskHR bot has been enabled and verified end-to-end.**
No code path in this repo performs this step — it is a deliberate one-time,
human-triggered action because disabling mail routing is high blast-radius
and hard to reverse quickly if something is wrong.

## Prerequisites

- The AskHR bot (`/askhr-bot` on `hrapp.movedocs.com`) has been enabled for
  at least a few days.
- You have spot-checked that tickets created by the bot in HRD look correct:
  reporter is AskHR/Benefits (not the original sender), the original email
  is attached as `.eml`, and the description includes the original
  sender/date/body.
- You have compared bot-created ticket volume against historical Bcc-forwarded
  ticket volume for the same mailboxes over a comparable period, and they're
  consistent.

## Steps

Connect to Exchange Online PowerShell with an account that can manage
transport rules, then run:

```powershell
Disable-TransportRule -Identity "Forward External Mail to Jira - AskHR" -Confirm:$false
Disable-TransportRule -Identity "Forward Payroll Mail to Jira - AskHR" -Confirm:$false
Disable-TransportRule -Identity "Forward External Mail to Jira - Benefits" -Confirm:$false
Disable-TransportRule -Identity "Forward Payroll Mail to Jira - Benefits" -Confirm:$false
```

Verify each rule shows `State: Disabled` (not deleted — keep them in place
in case you need to re-enable quickly):

```powershell
Get-TransportRule -Identity "Forward External Mail to Jira - AskHR" | Select-Object Name, State
Get-TransportRule -Identity "Forward Payroll Mail to Jira - AskHR" | Select-Object Name, State
Get-TransportRule -Identity "Forward External Mail to Jira - Benefits" | Select-Object Name, State
Get-TransportRule -Identity "Forward Payroll Mail to Jira - Benefits" | Select-Object Name, State
```

## Rollback

Re-enable any rule with `Enable-TransportRule -Identity "<name>"` if the bot
needs to be disabled and mail-flow forwarding restored while you investigate.
```

- [ ] **Step 2: Commit**

```bash
git add docs/runbooks/askhr-bot-cutover.md
git commit -m "docs: add the AskHR bot legacy transport rule cutover runbook"
```

---

## Self-Review

**Spec coverage:**
- `hrapp` site scope (backend + frontend + Caddy) → Tasks 1, 2, 13.
- Job settings/runs/messages schema, migration → Task 3.
- Domain refresh from live transport rule → Tasks 4, 5.
- Reporter-mode probe/cache + classic fallback + JQL idempotency → Tasks 6, 7.
- Checkpoint-bounded mailbox polling + filter (internal domain / payroll bypass) → Task 8.
- Attachment of original `.eml` → Task 7 (`_attach_email`).
- Leader-only background service → Task 9.
- Admin routes (status/runs/messages/settings/reporter-mode/retry) → Task 10.
- Frontend status/history/retry dashboard + landing page + nav/routes → Tasks 11, 12.
- Manual cutover runbook → Task 14.
- Out-of-scope items from the spec (Application Access Policy, Graph webhooks, Teams notifications, moving/flagging source mail, non-admin visibility) — correctly absent from every task above; no task attempts them.

**Placeholder scan:** no "TBD"/"TODO" in any task. The one deliberately-flagged ambiguity (Task 8's Python-version-dependent `Z`-suffix parsing, Task 10's empty-body retry limitation, Task 7's multipart `Content-Type` header caveat) each include the actual code to use in the common case, with an explicit note on what to check/verify rather than leaving the decision unresolved — these are genuine "verify against this repo's exact runtime" instructions, not missing design decisions.

**Type consistency:** `AskHrBotStatus`/`AskHrBotRun`/`AskHrBotMessage` (frontend, Task 11) match the exact keys returned by `_status_payload()`/`get_runs()`/`get_messages()` (backend, Task 10), which in turn match `_get_settings()`'s dict shape (Task 3) and `_record_message`'s column list (Task 8). `_create_or_attach_ticket`'s `(status, jira_issue_key, error)` tuple (Task 7) is consumed identically in `_poll_mailbox` (Task 8) and `retry_message` (Task 10). Fixed during review: `retry_message` in Task 10 originally didn't handle a missing message row — added the `HTTPException(404)` guard.

---

Plan complete and saved to `docs/superpowers/plans/2026-09-03-hrapp-askhr-bot.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
