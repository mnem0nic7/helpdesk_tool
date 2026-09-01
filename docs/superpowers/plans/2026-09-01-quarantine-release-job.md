# Quarantine Auto-Release Job Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an admin-only Tools-page feature that checks Exchange Online quarantine hourly for messages from a configurable list of trusted sender domains (default `complexlegal.com`) and releases them to all recipients, with an on/off toggle and durable run/release history.

**Architecture:** A leader-only background service (`backend/quarantine_release_job.py`), modeled directly on the existing `backend/password_expiry_notifier.py` pattern, polls every 5 minutes and executes the real check once per UTC clock hour. It reuses the existing `ExchangeOnlinePowerShellClient` singleton (already used by the offboarding tool) for two new PowerShell-backed operations. Settings and history live in three new SQLite/Postgres tables. Four admin-only REST routes expose status/history/settings. A new Tools-page card renders the toggle and history tables.

**Tech Stack:** Python/FastAPI backend, Exchange Online PowerShell via `pwsh` subprocess, SQLite (dev) / Postgres (prod) via the existing `postgres_utils`/`sqlite_utils` abstraction, React 19 + React Query 5 frontend.

**Spec:** `docs/superpowers/specs/2026-09-01-quarantine-release-job-design.md`

## Global Constraints

- No test-mode/dry-run concept — `enabled=false` means the job does nothing and writes no run row (not "logs only").
- Release action is always `-ReleaseToAll` (all original recipients), and always releases regardless of quarantine category (including phishing/malware) — this is an intentional, already-approved risk acceptance for the configured trusted domains.
- All 4 API routes are admin-only (`require_admin`), including the GET routes — this feature has no "read-only for everyone" tier, unlike the password-expiry notifier.
- `allowed_domains` is admin-editable at runtime via `PATCH /settings`, not hardcoded — `QUARANTINE_RELEASE_DEFAULT_DOMAINS` only seeds the settings row the first time it's created.
- Every new table needs a matching `backend/storage_migrations/NNNN_*.sql` file in the same commit (next number is `0027`) — `CREATE TABLE IF NOT EXISTS` / idempotent, per repo convention.
- Feature is primary-site-scope-only, admin-only on the frontend (matches the AD employee-number import tool's gating).

---

### Task 1: Config, migration, and job settings core

**Files:**
- Modify: `backend/config.py` — add `QUARANTINE_RELEASE_DEFAULT_DOMAINS` after line 417 (end of the password-expiry config block).
- Create: `backend/storage_migrations/0027_quarantine_release.sql`
- Create: `backend/quarantine_release_job.py`
- Test: `backend/tests/test_quarantine_release_job.py`

**Interfaces:**
- Produces: `QuarantineReleaseJob` class with `__init__(self, db_path: str | None = None)`, `_conn()`, `_sqlite_conn()`, `_placeholder()`, `_parse_domains(text: str) -> list[str]` (module-level pure function), `_get_settings(self) -> dict[str, Any]` returning `{"enabled": bool, "allowed_domains": list[str]}`, `_already_ran_this_hour(self, run_hour: str, conn) -> bool`. Module-level singleton `quarantine_release_job = QuarantineReleaseJob()`.

- [ ] **Step 1: Add the config constant**

In `backend/config.py`, immediately after line 417 (`PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE: int = ...`):

```python

# Quarantine auto-release job
QUARANTINE_RELEASE_DEFAULT_DOMAINS: str = os.getenv("QUARANTINE_RELEASE_DEFAULT_DOMAINS", "complexlegal.com").strip()
```

- [ ] **Step 2: Write the migration file**

Create `backend/storage_migrations/0027_quarantine_release.sql`:

```sql
CREATE TABLE IF NOT EXISTS quarantine_release_settings (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    enabled         SMALLINT NOT NULL DEFAULT 0,
    allowed_domains TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL DEFAULT '',
    updated_by      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS quarantine_release_runs (
    run_hour        TEXT PRIMARY KEY,
    ran_at          TEXT NOT NULL,
    domains_checked TEXT NOT NULL,
    checked_count   INTEGER NOT NULL DEFAULT 0,
    released_count  INTEGER NOT NULL DEFAULT 0,
    failed_count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quarantine_releases (
    id                TEXT PRIMARY KEY,
    run_hour          TEXT NOT NULL,
    message_identity  TEXT NOT NULL,
    sender_address    TEXT NOT NULL,
    recipient_address TEXT NOT NULL,
    subject           TEXT NOT NULL DEFAULT '',
    received_at       TEXT NOT NULL DEFAULT '',
    quarantine_reason TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL,
    error             TEXT,
    released_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qr_run_hour
    ON quarantine_releases (run_hour);
```

- [ ] **Step 3: Write the failing tests for settings bootstrap and hour-gating**

Create `backend/tests/test_quarantine_release_job.py`:

```python
"""Tests for the quarantine auto-release job core: settings and hour-gating."""
from __future__ import annotations

import tempfile


def _fresh_job():
    from quarantine_release_job import QuarantineReleaseJob
    tmp = tempfile.mktemp(suffix=".db")
    return QuarantineReleaseJob(db_path=tmp)


def test_parse_domains_splits_and_normalizes():
    from quarantine_release_job import _parse_domains

    assert _parse_domains("complexlegal.com, Example.com ,,") == ["complexlegal.com", "example.com"]
    assert _parse_domains("") == []
    assert _parse_domains(None) == []


def test_get_settings_bootstraps_default_row_when_missing(monkeypatch):
    import config
    monkeypatch.setattr(config, "QUARANTINE_RELEASE_DEFAULT_DOMAINS", "complexlegal.com")
    import quarantine_release_job as qrj_module
    monkeypatch.setattr(qrj_module, "QUARANTINE_RELEASE_DEFAULT_DOMAINS", "complexlegal.com")

    job = _fresh_job()
    settings = job._get_settings()

    assert settings == {"enabled": False, "allowed_domains": ["complexlegal.com"]}

    # Second call reads the now-persisted row rather than re-bootstrapping.
    settings_again = job._get_settings()
    assert settings_again == {"enabled": False, "allowed_domains": ["complexlegal.com"]}


def test_get_settings_reads_persisted_enabled_and_domains():
    job = _fresh_job()
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO quarantine_release_settings (id, enabled, allowed_domains, updated_at, updated_by) "
            "VALUES (1, 1, 'complexlegal.com,partner.org', '2026-09-01T00:00:00+00:00', 'admin@example.com')"
        )

    settings = job._get_settings()

    assert settings == {"enabled": True, "allowed_domains": ["complexlegal.com", "partner.org"]}


def test_already_ran_this_hour_true_after_run_row_inserted():
    job = _fresh_job()
    run_hour = "2026-09-01T14:00:00Z"
    with job._sqlite_conn() as conn:
        assert job._already_ran_this_hour(run_hour, conn) is False
        conn.execute(
            "INSERT INTO quarantine_release_runs (run_hour, ran_at, domains_checked, checked_count, released_count, failed_count) "
            "VALUES (?, ?, ?, 0, 0, 0)",
            (run_hour, "2026-09-01T14:01:00+00:00", "complexlegal.com"),
        )
    with job._sqlite_conn() as conn:
        assert job._already_ran_this_hour(run_hour, conn) is True
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_quarantine_release_job.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarantine_release_job'`

- [ ] **Step 5: Implement the job module core**

Create `backend/quarantine_release_job.py`:

```python
"""Hourly Exchange Online quarantine auto-release job for trusted domains.

Runs as a leader-only background service. No test-mode/dry-run concept:
enabled=false means the job does nothing and writes no run row.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR, QUARANTINE_RELEASE_DEFAULT_DOMAINS
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(DATA_DIR, "quarantine_release.db")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_domains(text: str | None) -> list[str]:
    if not text:
        return []
    domains: list[str] = []
    for part in str(text).split(","):
        domain = part.strip().lower()
        if domain and domain not in domains:
            domains.append(domain)
    return domains


class QuarantineReleaseJob:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._bg_task = None
        self._init_db()

    # ------------------------------------------------------------------
    # Schema
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
                CREATE TABLE IF NOT EXISTS quarantine_release_settings (
                    id              INTEGER PRIMARY KEY DEFAULT 1,
                    enabled         SMALLINT NOT NULL DEFAULT 0,
                    allowed_domains TEXT NOT NULL DEFAULT '',
                    updated_at      TEXT NOT NULL DEFAULT '',
                    updated_by      TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quarantine_release_runs (
                    run_hour        TEXT PRIMARY KEY,
                    ran_at          TEXT NOT NULL,
                    domains_checked TEXT NOT NULL,
                    checked_count   INTEGER NOT NULL DEFAULT 0,
                    released_count  INTEGER NOT NULL DEFAULT 0,
                    failed_count    INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quarantine_releases (
                    id                TEXT PRIMARY KEY,
                    run_hour          TEXT NOT NULL,
                    message_identity  TEXT NOT NULL,
                    sender_address    TEXT NOT NULL,
                    recipient_address TEXT NOT NULL,
                    subject           TEXT NOT NULL DEFAULT '',
                    received_at       TEXT NOT NULL DEFAULT '',
                    quarantine_reason TEXT NOT NULL DEFAULT '',
                    status            TEXT NOT NULL,
                    error             TEXT,
                    released_at       TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_qr_run_hour
                    ON quarantine_releases (run_hour)
            """)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _get_settings(self) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT enabled, allowed_domains FROM quarantine_release_settings WHERE id = 1"
            ).fetchone()
            if row is None:
                ph = self._placeholder()
                conn.execute(
                    f"INSERT INTO quarantine_release_settings "
                    f"(id, enabled, allowed_domains, updated_at, updated_by) "
                    f"VALUES (1, 0, {ph}, {ph}, {ph})",
                    (QUARANTINE_RELEASE_DEFAULT_DOMAINS, _utcnow().isoformat(), "system"),
                )
                return {"enabled": False, "allowed_domains": _parse_domains(QUARANTINE_RELEASE_DEFAULT_DOMAINS)}
        return {"enabled": bool(row["enabled"]), "allowed_domains": _parse_domains(row["allowed_domains"])}

    # ------------------------------------------------------------------
    # Run gating
    # ------------------------------------------------------------------

    def _already_ran_this_hour(self, run_hour: str, conn: sqlite3.Connection) -> bool:
        ph = self._placeholder()
        row = conn.execute(
            f"SELECT 1 FROM quarantine_release_runs WHERE run_hour = {ph}",
            (run_hour,),
        ).fetchone()
        return row is not None


quarantine_release_job = QuarantineReleaseJob()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_quarantine_release_job.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add backend/config.py backend/storage_migrations/0027_quarantine_release.sql backend/quarantine_release_job.py backend/tests/test_quarantine_release_job.py
git commit -m "feat: add quarantine release job settings and schema"
```

---

### Task 2: Exchange Online client — list and release quarantine messages

**Files:**
- Modify: `backend/exchange_online_client.py`
- Modify: `backend/tests/test_exchange_online_client.py`

**Interfaces:**
- Consumes: `ExchangeOnlinePowerShellClient._run_script` (existing).
- Produces: `ExchangeOnlinePowerShellClient.list_quarantine_messages(self, domains: list[str]) -> list[dict[str, Any]]` — each dict has keys `identity, sender_address, recipient_address, subject, received_at, quarantine_reason`. `ExchangeOnlinePowerShellClient.release_quarantine_message(self, identity: str) -> dict[str, Any]` — returns `{"identity": str, "released": bool}`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_exchange_online_client.py` (before `test_sanitize_powershell_error_text_removes_ansi_sequences`):

```python
def test_run_script_command_name_allow_list_includes_quarantine_cmdlets(monkeypatch):
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

    assert "'Get-QuarantineMessage'" in captured["script"]
    assert "'Release-QuarantineMessage'" in captured["script"]


def test_list_quarantine_messages_builds_one_call_per_domain(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        captured["script_body"] = script_body
        captured["extra_env"] = extra_env or {}
        return {
            "messages": [
                {
                    "identity": "msg-1",
                    "sender_address": "billing@complexlegal.com",
                    "recipient_address": "ap@example.com",
                    "subject": "Invoice",
                    "received_at": "2026-09-01T14:05:00Z",
                    "quarantine_reason": "Spam",
                }
            ]
        }

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    result = client.list_quarantine_messages(["complexlegal.com", "partner.org"])

    assert result == [
        {
            "identity": "msg-1",
            "sender_address": "billing@complexlegal.com",
            "recipient_address": "ap@example.com",
            "subject": "Invoice",
            "received_at": "2026-09-01T14:05:00Z",
            "quarantine_reason": "Spam",
        }
    ]
    assert captured["extra_env"] == {"QR_DOMAINS": "complexlegal.com,partner.org"}
    assert "Get-QuarantineMessage" in captured["script_body"]
    assert "$env:QR_DOMAINS" in captured["script_body"]


def test_list_quarantine_messages_returns_empty_list_for_no_domains():
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())

    assert client.list_quarantine_messages([]) == []


def test_list_quarantine_messages_coerces_single_dict_payload_to_list(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        return {"messages": {"identity": "msg-1", "sender_address": "a@complexlegal.com",
                              "recipient_address": "b@example.com", "subject": "", "received_at": "", "quarantine_reason": "Spam"}}

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    result = client.list_quarantine_messages(["complexlegal.com"])

    assert len(result) == 1
    assert result[0]["identity"] == "msg-1"


def test_release_quarantine_message_uses_release_to_all(monkeypatch):
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())
    captured: dict[str, object] = {}

    def fake_run_script(script_body, *, extra_env=None, timeout_seconds=None, cancel_requested=None):
        captured["script_body"] = script_body
        captured["extra_env"] = extra_env or {}
        return {"identity": "msg-1", "released": True}

    monkeypatch.setattr(client, "_run_script", fake_run_script)

    result = client.release_quarantine_message("msg-1")

    assert result == {"identity": "msg-1", "released": True}
    assert captured["extra_env"] == {"QR_IDENTITY": "msg-1"}
    assert "Release-QuarantineMessage -Identity $identity -ReleaseToAll -Confirm:$false" in captured["script_body"]


def test_release_quarantine_message_requires_identity():
    client = ExchangeOnlinePowerShellClient(azure_client=StubAzureClient())

    try:
        client.release_quarantine_message("")
        assert False, "expected ExchangeOnlinePowerShellError"
    except ExchangeOnlinePowerShellError:
        pass


```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_exchange_online_client.py -v`
Expected: FAIL — `AttributeError: 'ExchangeOnlinePowerShellClient' object has no attribute 'list_quarantine_messages'` (and related failures for the allow-list test, since the cmdlets aren't in it yet).

- [ ] **Step 3: Add the cmdlets to the Connect-ExchangeOnline allow-list**

In `backend/exchange_online_client.py`, in `_run_script`, extend the existing `-CommandName` list (already containing `'Set-Mailbox'`, `'Remove-DistributionGroupMember'`, etc. from the offboarding-tool fix):

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
    'Disconnect-ExchangeOnline'
  ) | Out-Null
```

- [ ] **Step 4: Implement `list_quarantine_messages` and `release_quarantine_message`**

Add to `ExchangeOnlinePowerShellClient` in `backend/exchange_online_client.py` (after `remove_distribution_group_member`):

```python
    def list_quarantine_messages(self, domains: list[str]) -> list[dict[str, Any]]:
        """List currently quarantined messages whose sender domain is in `domains`."""
        clean_domains = [str(d or "").strip() for d in domains if str(d or "").strip()]
        if not clean_domains:
            return []
        script = """
$domains = $env:QR_DOMAINS -split ','
$allMessages = @()
foreach ($domain in $domains) {
  $domain = $domain.Trim()
  if (-not $domain) { continue }
  $page = 1
  while ($true) {
    $batch = @(Get-QuarantineMessage -SenderAddress "*@$domain" -PageSize 100 -Page $page)
    if ($batch.Count -eq 0) { break }
    $allMessages += $batch
    if ($batch.Count -lt 100) { break }
    $page++
  }
}
[pscustomobject]@{
  messages = @(
    foreach ($m in $allMessages) {
      [pscustomobject]@{
        identity = $m.Identity.ToString()
        sender_address = $m.SenderAddress
        recipient_address = ($m.RecipientAddress -join ';')
        subject = $m.Subject
        received_at = $m.ReceivedTime.ToString("o")
        quarantine_reason = $m.Type.ToString()
      }
    }
  )
} | ConvertTo-Json -Depth 6 -Compress
"""
        payload = self._run_script(script.strip(), extra_env={"QR_DOMAINS": ",".join(clean_domains)})
        messages = payload.get("messages") if isinstance(payload, dict) else []
        if isinstance(messages, dict):
            messages = [messages]
        return messages if isinstance(messages, list) else []

    def release_quarantine_message(self, identity: str) -> dict[str, Any]:
        """Release a quarantined message to all of its original recipients."""
        message_identity = str(identity or "").strip()
        if not message_identity:
            raise ExchangeOnlinePowerShellError("identity is required")
        script = """
$identity = $env:QR_IDENTITY
Release-QuarantineMessage -Identity $identity -ReleaseToAll -Confirm:$false
@{
  identity = $identity
  released = $true
} | ConvertTo-Json -Compress
"""
        payload = self._run_script(script.strip(), extra_env={"QR_IDENTITY": message_identity})
        return {
            "identity": message_identity,
            "released": bool(payload.get("released", True)),
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_exchange_online_client.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add backend/exchange_online_client.py backend/tests/test_exchange_online_client.py
git commit -m "feat: add quarantine list/release to Exchange Online client"
```

---

### Task 3: Job orchestration — `run_hourly_job()`

**Files:**
- Modify: `backend/quarantine_release_job.py`
- Modify: `backend/tests/test_quarantine_release_job.py`

**Interfaces:**
- Consumes: `_get_settings()`, `_already_ran_this_hour()` (Task 1); `ExchangeOnlinePowerShellClient.list_quarantine_messages()` / `.release_quarantine_message()` (Task 2), reached via `user_admin_providers.user_admin_providers.mailbox.exchange_powershell`.
- Produces: `async def run_hourly_job(self) -> None` — the entry point Task 4's background loop calls every poll cycle.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_quarantine_release_job.py`:

```python
from unittest.mock import MagicMock, patch


def _seed_settings(job, *, enabled: bool, domains: str = "complexlegal.com"):
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO quarantine_release_settings (id, enabled, allowed_domains, updated_at, updated_by) "
            "VALUES (1, ?, ?, '2026-09-01T00:00:00+00:00', 'admin@example.com')",
            (1 if enabled else 0, domains),
        )


async def test_run_hourly_job_skips_when_disabled_and_writes_no_run_row():
    job = _fresh_job()
    _seed_settings(job, enabled=False)

    mock_uap_module = MagicMock()
    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        await job.run_hourly_job()

    mock_uap_module.user_admin_providers.mailbox.exchange_powershell.list_quarantine_messages.assert_not_called()
    with job._sqlite_conn() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM quarantine_release_runs").fetchone()["c"]
    assert count == 0


async def test_run_hourly_job_releases_matching_messages_and_records_run():
    job = _fresh_job()
    _seed_settings(job, enabled=True, domains="complexlegal.com")

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.list_quarantine_messages.return_value = [
        {
            "identity": "msg-1",
            "sender_address": "billing@complexlegal.com",
            "recipient_address": "ap@example.com",
            "subject": "Invoice",
            "received_at": "2026-09-01T14:05:00Z",
            "quarantine_reason": "Spam",
        }
    ]
    exchange.release_quarantine_message.return_value = {"identity": "msg-1", "released": True}

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        await job.run_hourly_job()

    exchange.list_quarantine_messages.assert_called_once_with(["complexlegal.com"])
    exchange.release_quarantine_message.assert_called_once_with("msg-1")

    with job._sqlite_conn() as conn:
        run = conn.execute("SELECT * FROM quarantine_release_runs").fetchone()
        release = conn.execute("SELECT * FROM quarantine_releases").fetchone()
    assert run["checked_count"] == 1
    assert run["released_count"] == 1
    assert run["failed_count"] == 0
    assert release["status"] == "released"
    assert release["sender_address"] == "billing@complexlegal.com"


async def test_run_hourly_job_records_failure_without_aborting_other_messages():
    job = _fresh_job()
    _seed_settings(job, enabled=True, domains="complexlegal.com")

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.list_quarantine_messages.return_value = [
        {"identity": "msg-1", "sender_address": "a@complexlegal.com", "recipient_address": "x@example.com",
         "subject": "", "received_at": "", "quarantine_reason": "Spam"},
        {"identity": "msg-2", "sender_address": "b@complexlegal.com", "recipient_address": "y@example.com",
         "subject": "", "received_at": "", "quarantine_reason": "Phish"},
    ]
    exchange.release_quarantine_message.side_effect = [RuntimeError("boom"), {"identity": "msg-2", "released": True}]

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        await job.run_hourly_job()

    assert exchange.release_quarantine_message.call_count == 2
    with job._sqlite_conn() as conn:
        run = conn.execute("SELECT * FROM quarantine_release_runs").fetchone()
        statuses = {r["message_identity"]: r["status"] for r in conn.execute("SELECT * FROM quarantine_releases")}
    assert run["released_count"] == 1
    assert run["failed_count"] == 1
    assert statuses == {"msg-1": "failed", "msg-2": "released"}


async def test_run_hourly_job_skips_if_already_ran_this_hour():
    job = _fresh_job()
    _seed_settings(job, enabled=True, domains="complexlegal.com")

    mock_uap_module = MagicMock()
    exchange = mock_uap_module.user_admin_providers.mailbox.exchange_powershell
    exchange.list_quarantine_messages.return_value = []

    with patch.dict("sys.modules", {"user_admin_providers": mock_uap_module}):
        await job.run_hourly_job()
        await job.run_hourly_job()

    assert exchange.list_quarantine_messages.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_quarantine_release_job.py -v`
Expected: FAIL — `AttributeError: 'QuarantineReleaseJob' object has no attribute 'run_hourly_job'`

- [ ] **Step 3: Implement `run_hourly_job` and its recording helpers**

Add to `backend/quarantine_release_job.py`. First add `import asyncio` and `import uuid` to the top-level imports (alongside the existing `logging`, `os`, `sqlite3` imports). Then add these methods to `QuarantineReleaseJob`, after `_already_ran_this_hour`:

```python
    def _record_release(
        self,
        *,
        run_hour: str,
        message: dict[str, Any],
        status: str,
        error: str | None,
        conn: sqlite3.Connection,
    ) -> None:
        ph = self._placeholder()
        conn.execute(
            f"""INSERT INTO quarantine_releases
                (id, run_hour, message_identity, sender_address, recipient_address,
                 subject, received_at, quarantine_reason, status, error, released_at)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
            (
                uuid.uuid4().hex,
                run_hour,
                str(message.get("identity") or ""),
                str(message.get("sender_address") or ""),
                str(message.get("recipient_address") or ""),
                str(message.get("subject") or ""),
                str(message.get("received_at") or ""),
                str(message.get("quarantine_reason") or ""),
                status,
                error,
                _utcnow().isoformat(),
            ),
        )

    def _record_run(
        self,
        *,
        run_hour: str,
        domains: list[str],
        checked_count: int,
        released_count: int,
        failed_count: int,
        conn: sqlite3.Connection,
    ) -> None:
        ph = self._placeholder()
        conn.execute(
            f"""INSERT INTO quarantine_release_runs
                (run_hour, ran_at, domains_checked, checked_count, released_count, failed_count)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph})""",
            (run_hour, _utcnow().isoformat(), ",".join(domains), checked_count, released_count, failed_count),
        )

    async def run_hourly_job(self) -> None:
        import user_admin_providers as _uap_module

        current_hour = _utcnow().replace(minute=0, second=0, microsecond=0)
        run_hour = current_hour.strftime("%Y-%m-%dT%H:00:00Z")

        with self._conn() as conn:
            if self._already_ran_this_hour(run_hour, conn):
                return

        settings = self._get_settings()
        if not settings["enabled"]:
            return
        domains = settings["allowed_domains"]
        if not domains:
            return

        exchange = _uap_module.user_admin_providers.mailbox.exchange_powershell
        loop = asyncio.get_event_loop()

        try:
            messages = await loop.run_in_executor(None, lambda: exchange.list_quarantine_messages(domains))
        except Exception:
            logger.exception("Quarantine release job: failed to list quarantine messages")
            return

        released = 0
        failed = 0
        for message in messages:
            identity = str(message.get("identity") or "").strip()
            if not identity:
                continue
            try:
                await loop.run_in_executor(None, lambda i=identity: exchange.release_quarantine_message(i))
                status, error = "released", None
                released += 1
            except Exception as exc:
                status, error = "failed", str(exc)
                failed += 1
            with self._conn() as conn:
                self._record_release(run_hour=run_hour, message=message, status=status, error=error, conn=conn)

        with self._conn() as conn:
            self._record_run(
                run_hour=run_hour,
                domains=domains,
                checked_count=len(messages),
                released_count=released,
                failed_count=failed,
                conn=conn,
            )

        logger.info(
            "Quarantine release job: run %s complete — %d checked, %d released, %d failed",
            run_hour, len(messages), released, failed,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_quarantine_release_job.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add backend/quarantine_release_job.py backend/tests/test_quarantine_release_job.py
git commit -m "feat: implement quarantine release job hourly run logic"
```

---

### Task 4: Background runner and leader-service wiring

**Files:**
- Modify: `backend/quarantine_release_job.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/test_quarantine_release_job.py`

**Interfaces:**
- Produces: `QuarantineReleaseJob.start_background_runner(self) -> None`, `.stop_background_runner(self) -> None`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_quarantine_release_job.py`:

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

Run: `cd backend && python3 -m pytest tests/test_quarantine_release_job.py::test_start_and_stop_background_runner_does_not_raise -v`
Expected: FAIL — `AttributeError: 'QuarantineReleaseJob' object has no attribute 'start_background_runner'`

- [ ] **Step 3: Implement the background loop**

Add `import asyncio` is already present from Task 3. Add these methods to `QuarantineReleaseJob` in `backend/quarantine_release_job.py`, at the end of the class:

```python
    # ------------------------------------------------------------------
    # Background runner
    # ------------------------------------------------------------------

    def start_background_runner(self) -> None:
        loop = asyncio.get_event_loop()
        self._bg_task = loop.create_task(self._run_loop())

    def stop_background_runner(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_hourly_job()
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Quarantine release job loop error")
                await asyncio.sleep(300)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_quarantine_release_job.py -v`
Expected: all passed

- [ ] **Step 5: Wire into `main.py` leader services**

In `backend/main.py`, add the import after line 53 (`from password_expiry_notifier import password_expiry_notifier as _password_expiry_notifier`):

```python
from quarantine_release_job import quarantine_release_job as _quarantine_release_job
```

In `_start_leader_services`, immediately after the existing `_password_expiry_notifier.start_background_runner()` try/except block (around line 147):

```python

    try:
        _quarantine_release_job.start_background_runner()
    except Exception:
        logger.exception("Failed to start quarantine release job")
```

In `_stop_leader_services`, immediately after `_password_expiry_notifier.stop_background_runner()`:

```python
    _quarantine_release_job.stop_background_runner()
```

- [ ] **Step 6: Verify the backend still imports cleanly**

Run: `cd backend && python3 -c "import main"`
Expected: no exceptions raised (this catches import-order/typo mistakes in the wiring).

- [ ] **Step 7: Commit**

```bash
git add backend/quarantine_release_job.py backend/main.py backend/tests/test_quarantine_release_job.py
git commit -m "feat: wire quarantine release job into leader-only background services"
```

---

### Task 5: Backend API routes

**Files:**
- Create: `backend/routes_quarantine_release.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_routes_quarantine_release.py`

**Interfaces:**
- Consumes: `quarantine_release_job` singleton (`_get_settings`, `_conn`, `_sqlite_conn`, `_placeholder`), `auth.require_admin`.
- Produces: `router` (FastAPI `APIRouter`, prefix `/api/quarantine-release`) with `GET /status`, `GET /runs`, `GET /releases`, `PATCH /settings`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_routes_quarantine_release.py`:

```python
"""Tests for quarantine release job API routes."""
from __future__ import annotations

import uuid


def test_get_status_no_settings_row_bootstraps_disabled(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    resp = test_client.get("/api/quarantine-release/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["allowed_domains"] == ["complexlegal.com"]
    assert data["last_run"] is None


def test_get_status_reflects_last_run(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO quarantine_release_runs (run_hour, ran_at, domains_checked, checked_count, released_count, failed_count) "
            "VALUES ('2026-09-01T14:00:00Z', '2026-09-01T14:02:00+00:00', 'complexlegal.com', 3, 3, 0)"
        )
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    resp = test_client.get("/api/quarantine-release/status")
    assert resp.status_code == 200
    last_run = resp.json()["last_run"]
    assert last_run["run_hour"] == "2026-09-01T14:00:00Z"
    assert last_run["released_count"] == 3


def test_get_status_forbidden_for_non_admin(test_client, monkeypatch, tmp_path):
    import auth
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: email != "non-admin@example.com")
    non_admin_sid = auth.create_session("non-admin@example.com", "Non Admin")
    test_client.cookies.set("session_id", non_admin_sid)
    try:
        resp = test_client.get("/api/quarantine-release/status")
        assert resp.status_code == 403
    finally:
        test_client.cookies.set("session_id", auth.create_session("test@example.com", "Test User"))


def test_get_runs_pagination(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    with job._sqlite_conn() as conn:
        for hour in ["2026-09-01T12:00:00Z", "2026-09-01T13:00:00Z", "2026-09-01T14:00:00Z"]:
            conn.execute(
                "INSERT INTO quarantine_release_runs (run_hour, ran_at, domains_checked, checked_count, released_count, failed_count) "
                "VALUES (?, ?, 'complexlegal.com', 1, 1, 0)",
                (hour, f"{hour[:-1]}+00:00"),
            )
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    resp = test_client.get("/api/quarantine-release/runs?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["items"][0]["run_hour"] == "2026-09-01T14:00:00Z"


def test_get_releases_pagination_and_run_hour_filter(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    with job._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO quarantine_releases "
            "(id, run_hour, message_identity, sender_address, recipient_address, subject, received_at, quarantine_reason, status, error, released_at) "
            "VALUES (?, '2026-09-01T14:00:00Z', 'msg-1', 'a@complexlegal.com', 'b@example.com', 'Invoice', '', 'Spam', 'released', NULL, '2026-09-01T14:02:00+00:00')",
            (uuid.uuid4().hex,),
        )
        conn.execute(
            "INSERT INTO quarantine_releases "
            "(id, run_hour, message_identity, sender_address, recipient_address, subject, received_at, quarantine_reason, status, error, released_at) "
            "VALUES (?, '2026-09-01T13:00:00Z', 'msg-2', 'c@complexlegal.com', 'd@example.com', 'Statement', '', 'Bulk', 'released', NULL, '2026-09-01T13:02:00+00:00')",
            (uuid.uuid4().hex,),
        )
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    resp_all = test_client.get("/api/quarantine-release/releases")
    assert resp_all.json()["total"] == 2

    resp_filtered = test_client.get("/api/quarantine-release/releases?run_hour=2026-09-01T14:00:00Z")
    data = resp_filtered.json()
    assert data["total"] == 1
    assert data["items"][0]["message_identity"] == "msg-1"


def test_patch_settings_admin_updates_enabled_and_domains(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    resp = test_client.patch(
        "/api/quarantine-release/settings",
        json={"enabled": True, "allowed_domains": ["complexlegal.com", "partner.org"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["allowed_domains"] == ["complexlegal.com", "partner.org"]


def test_patch_settings_partial_update_preserves_other_field(test_client, monkeypatch, tmp_path):
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)

    test_client.patch(
        "/api/quarantine-release/settings",
        json={"enabled": True, "allowed_domains": ["complexlegal.com"]},
    )
    resp = test_client.patch("/api/quarantine-release/settings", json={"enabled": False})
    data = resp.json()
    assert data["enabled"] is False
    assert data["allowed_domains"] == ["complexlegal.com"]


def test_patch_settings_forbidden_for_non_admin(test_client, monkeypatch, tmp_path):
    import auth
    import quarantine_release_job as qrj_module

    job = qrj_module.QuarantineReleaseJob(db_path=str(tmp_path / "qr.db"))
    import routes_quarantine_release
    monkeypatch.setattr(routes_quarantine_release, "quarantine_release_job", job)
    monkeypatch.setattr(auth, "is_admin_user", lambda email: email != "non-admin@example.com")
    non_admin_sid = auth.create_session("non-admin@example.com", "Non Admin")
    test_client.cookies.set("session_id", non_admin_sid)
    try:
        resp = test_client.patch("/api/quarantine-release/settings", json={"enabled": True})
        assert resp.status_code == 403
    finally:
        test_client.cookies.set("session_id", auth.create_session("test@example.com", "Test User"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_routes_quarantine_release.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'routes_quarantine_release'`

- [ ] **Step 3: Implement the routes**

Create `backend/routes_quarantine_release.py`:

```python
"""FastAPI routes for the quarantine auto-release job."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_admin
from quarantine_release_job import quarantine_release_job

router = APIRouter(prefix="/api/quarantine-release", tags=["quarantine-release"])


class PatchSettingsRequest(BaseModel):
    enabled: bool | None = None
    allowed_domains: list[str] | None = None


def _last_run(job) -> dict[str, Any] | None:
    with job._conn() as conn:
        row = conn.execute(
            "SELECT run_hour, ran_at, domains_checked, checked_count, released_count, failed_count "
            "FROM quarantine_release_runs ORDER BY run_hour DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row is not None else None


def _status_payload(job) -> dict[str, Any]:
    settings = job._get_settings()
    return {
        "enabled": settings["enabled"],
        "allowed_domains": settings["allowed_domains"],
        "last_run": _last_run(job),
    }


@router.get("/status", dependencies=[Depends(require_admin)])
async def get_status() -> dict[str, Any]:
    return _status_payload(quarantine_release_job)


@router.get("/runs", dependencies=[Depends(require_admin)])
async def get_runs(limit: int = 30, offset: int = 0) -> dict[str, Any]:
    limit = min(limit, 100)
    ph = quarantine_release_job._placeholder()
    with quarantine_release_job._conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS cnt FROM quarantine_release_runs").fetchone()["cnt"]
        rows = conn.execute(
            "SELECT run_hour, ran_at, domains_checked, checked_count, released_count, failed_count "
            f"FROM quarantine_release_runs ORDER BY run_hour DESC LIMIT {ph} OFFSET {ph}",
            (limit, offset),
        ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.get("/releases", dependencies=[Depends(require_admin)])
async def get_releases(limit: int = 50, offset: int = 0, run_hour: str | None = None) -> dict[str, Any]:
    limit = min(limit, 100)
    ph = quarantine_release_job._placeholder()
    columns = (
        "id, run_hour, message_identity, sender_address, recipient_address, "
        "subject, received_at, quarantine_reason, status, error, released_at"
    )
    with quarantine_release_job._conn() as conn:
        if run_hour:
            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM quarantine_releases WHERE run_hour = {ph}",
                (run_hour,),
            ).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT {columns} FROM quarantine_releases WHERE run_hour = {ph} "
                f"ORDER BY released_at DESC LIMIT {ph} OFFSET {ph}",
                (run_hour, limit, offset),
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) AS cnt FROM quarantine_releases").fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT {columns} FROM quarantine_releases ORDER BY released_at DESC LIMIT {ph} OFFSET {ph}",
                (limit, offset),
            ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.patch("/settings")
async def patch_settings(
    body: PatchSettingsRequest,
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    current = quarantine_release_job._get_settings()
    enabled = current["enabled"] if body.enabled is None else body.enabled
    domains = current["allowed_domains"] if body.allowed_domains is None else body.allowed_domains
    updated_at = datetime.now(timezone.utc).isoformat()
    updated_by = user.get("email") or user.get("name") or "unknown"
    ph = quarantine_release_job._placeholder()
    with quarantine_release_job._conn() as conn:
        conn.execute(
            f"INSERT INTO quarantine_release_settings (id, enabled, allowed_domains, updated_at, updated_by) "
            f"VALUES (1, {ph}, {ph}, {ph}, {ph}) "
            f"ON CONFLICT (id) DO UPDATE SET "
            f"enabled = excluded.enabled, allowed_domains = excluded.allowed_domains, "
            f"updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (1 if enabled else 0, ",".join(domains), updated_at, updated_by),
        )
    return _status_payload(quarantine_release_job)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_routes_quarantine_release.py -v`
Expected: all passed

- [ ] **Step 5: Register the router in `main.py`**

In `backend/main.py`, add the import after line 51 (`from routes_password_expiry_notifier import router as password_expiry_notifier_router`):

```python
from routes_quarantine_release import router as quarantine_release_router
```

After `app.include_router(password_expiry_notifier_router)` (around line 463):

```python
app.include_router(quarantine_release_router)
```

- [ ] **Step 6: Verify the backend still imports cleanly and run the full backend suite**

Run: `cd backend && python3 -c "import main" && python3 -m pytest tests/ -q`
Expected: no import errors; only the pre-existing unrelated failures (confirmed earlier via `git stash` to exist on `main` independent of this feature) — no new failures.

- [ ] **Step 7: Commit**

```bash
git add backend/routes_quarantine_release.py backend/main.py backend/tests/test_routes_quarantine_release.py
git commit -m "feat: add quarantine release job API routes"
```

---

### Task 6: Frontend API client

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Produces: types `QuarantineReleaseRun`, `QuarantineReleaseMessage`, `QuarantineReleaseStatus`; functions `getQuarantineReleaseStatus()`, `getQuarantineReleaseRuns(limit?, offset?)`, `getQuarantineReleaseReleases(limit?, offset?, runHour?)`, `patchQuarantineReleaseSettings(body)`.

- [ ] **Step 1: Add the types**

Append to the end of `frontend/src/lib/api.ts` (after the existing `PasswordExpiryNotification` interface):

```typescript

export interface QuarantineReleaseRun {
  run_hour: string;
  ran_at: string;
  domains_checked: string;
  checked_count: number;
  released_count: number;
  failed_count: number;
}

export interface QuarantineReleaseMessage {
  id: string;
  run_hour: string;
  message_identity: string;
  sender_address: string;
  recipient_address: string;
  subject: string;
  received_at: string;
  quarantine_reason: string;
  status: "released" | "failed";
  error: string | null;
  released_at: string;
}

export interface QuarantineReleaseStatus {
  enabled: boolean;
  allowed_domains: string[];
  last_run: QuarantineReleaseRun | null;
}
```

- [ ] **Step 2: Add the API functions**

In `frontend/src/lib/api.ts`, insert immediately after the `patchPasswordExpirySettings` method and before the closing `};` of the `api` object:

```typescript

  getQuarantineReleaseStatus(): Promise<QuarantineReleaseStatus> {
    return fetchJSON<QuarantineReleaseStatus>("/api/quarantine-release/status");
  },

  getQuarantineReleaseRuns(
    limit = 30,
    offset = 0,
  ): Promise<{ items: QuarantineReleaseRun[]; total: number }> {
    return fetchJSON(`/api/quarantine-release/runs?limit=${limit}&offset=${offset}`);
  },

  getQuarantineReleaseReleases(
    limit = 50,
    offset = 0,
    runHour?: string,
  ): Promise<{ items: QuarantineReleaseMessage[]; total: number }> {
    const runHourParam = runHour ? `&run_hour=${encodeURIComponent(runHour)}` : "";
    return fetchJSON(`/api/quarantine-release/releases?limit=${limit}&offset=${offset}${runHourParam}`);
  },

  async patchQuarantineReleaseSettings(
    body: { enabled?: boolean; allowed_domains?: string[] },
  ): Promise<QuarantineReleaseStatus> {
    const res = await fetch("/api/quarantine-release/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.status === 401) {
      window.location.href = "/api/auth/login";
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      throw new Error(await buildErrorMessage("PATCH", "/api/quarantine-release/settings", res));
    }
    return res.json() as Promise<QuarantineReleaseStatus>;
  },
```

- [ ] **Step 3: Verify the frontend still type-checks**

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add quarantine release API client"
```

---

### Task 7: Frontend Tools-page component

**Files:**
- Create: `frontend/src/components/QuarantineReleaseTool.tsx`
- Modify: `frontend/src/pages/ToolsPage.tsx`
- Test: `frontend/src/__tests__/QuarantineReleaseTool.test.tsx`

**Interfaces:**
- Consumes: `api.getQuarantineReleaseStatus`, `api.getQuarantineReleaseRuns`, `api.getQuarantineReleaseReleases`, `api.patchQuarantineReleaseSettings` (Task 6).
- Produces: default-exported `QuarantineReleaseTool` component, rendered from `ToolsPage.tsx` for admins on the primary scope.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/QuarantineReleaseTool.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { render } from "../test-utils.tsx";
import QuarantineReleaseTool from "../components/QuarantineReleaseTool.tsx";

const mockApi = vi.hoisted(() => ({
  getQuarantineReleaseStatus: vi.fn(),
  getQuarantineReleaseRuns: vi.fn(),
  getQuarantineReleaseReleases: vi.fn(),
  patchQuarantineReleaseSettings: vi.fn(),
}));

vi.mock("../lib/api.ts", () => ({
  api: mockApi,
  default: mockApi,
}));

describe("QuarantineReleaseTool", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getQuarantineReleaseStatus.mockResolvedValue({
      enabled: false,
      allowed_domains: ["complexlegal.com"],
      last_run: {
        run_hour: "2026-09-01T14:00:00Z",
        ran_at: "2026-09-01T14:02:00+00:00",
        domains_checked: "complexlegal.com",
        checked_count: 3,
        released_count: 3,
        failed_count: 0,
      },
    });
    mockApi.getQuarantineReleaseRuns.mockResolvedValue({
      items: [
        {
          run_hour: "2026-09-01T14:00:00Z",
          ran_at: "2026-09-01T14:02:00+00:00",
          domains_checked: "complexlegal.com",
          checked_count: 3,
          released_count: 3,
          failed_count: 0,
        },
      ],
      total: 1,
    });
    mockApi.getQuarantineReleaseReleases.mockResolvedValue({
      items: [
        {
          id: "r1",
          run_hour: "2026-09-01T14:00:00Z",
          message_identity: "msg-1",
          sender_address: "billing@complexlegal.com",
          recipient_address: "ap@example.com",
          subject: "Invoice",
          received_at: "2026-09-01T14:00:00Z",
          quarantine_reason: "Spam",
          status: "released",
          error: null,
          released_at: "2026-09-01T14:02:00Z",
        },
      ],
      total: 1,
    });
    mockApi.patchQuarantineReleaseSettings.mockResolvedValue({
      enabled: true,
      allowed_domains: ["complexlegal.com"],
      last_run: null,
    });
  });

  it("renders the toggle, last-run summary, and releases table", async () => {
    render(<QuarantineReleaseTool />);

    await waitFor(() => expect(screen.getByRole("switch")).toBeInTheDocument());
    expect(screen.getByText(/3 released/i)).toBeInTheDocument();
    expect(await screen.findByText("billing@complexlegal.com")).toBeInTheDocument();
  });

  it("toggles the job on and calls the settings patch", async () => {
    render(<QuarantineReleaseTool />);

    const toggle = await screen.findByRole("switch");
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(mockApi.patchQuarantineReleaseSettings).toHaveBeenCalledWith({ enabled: true }),
    );
  });

  it("saves an edited domain list", async () => {
    render(<QuarantineReleaseTool />);

    const input = await screen.findByLabelText(/trusted domains/i);
    fireEvent.change(input, { target: { value: "complexlegal.com, partner.org" } });
    fireEvent.click(screen.getByRole("button", { name: /save domains/i }));

    await waitFor(() =>
      expect(mockApi.patchQuarantineReleaseSettings).toHaveBeenCalledWith({
        allowed_domains: ["complexlegal.com", "partner.org"],
      }),
    );
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm run test:run -- QuarantineReleaseTool`
Expected: FAIL — cannot find module `../components/QuarantineReleaseTool.tsx`

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/QuarantineReleaseTool.tsx`:

```tsx
/**
 * Tools-page card: admin toggle for the hourly Exchange Online quarantine
 * auto-release job, plus run history and per-message release detail.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type QuarantineReleaseRun } from "../lib/api.ts";

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export default function QuarantineReleaseTool() {
  const queryClient = useQueryClient();
  const [domainsInput, setDomainsInput] = useState("");
  const [selectedRunHour, setSelectedRunHour] = useState<string | null>(null);

  const statusQuery = useQuery({
    queryKey: ["quarantine-release", "status"],
    queryFn: () => api.getQuarantineReleaseStatus(),
  });

  const runsQuery = useQuery({
    queryKey: ["quarantine-release", "runs"],
    queryFn: () => api.getQuarantineReleaseRuns(30, 0),
  });

  const releasesQuery = useQuery({
    queryKey: ["quarantine-release", "releases", selectedRunHour],
    queryFn: () => api.getQuarantineReleaseReleases(50, 0, selectedRunHour ?? undefined),
  });

  const settingsMutation = useMutation({
    mutationFn: (body: { enabled?: boolean; allowed_domains?: string[] }) =>
      api.patchQuarantineReleaseSettings(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quarantine-release", "status"] });
    },
  });

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ["quarantine-release"] });
  }

  function handleSaveDomains() {
    const domains = domainsInput
      .split(",")
      .map((d) => d.trim())
      .filter((d) => d.length > 0);
    settingsMutation.mutate({ allowed_domains: domains });
  }

  const status = statusQuery.data;
  const enabled = status?.enabled ?? false;

  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Exchange Online</div>
          <h2 className="mt-1 text-2xl font-semibold text-slate-900">Quarantine auto-release</h2>
          <p className="mt-1 text-sm text-slate-500">
            Hourly job that releases quarantined mail from trusted sender domains to all original recipients.
          </p>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          className="rounded border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
        >
          Refresh
        </button>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-600">Job enabled</span>
          <button
            role="switch"
            aria-checked={enabled}
            aria-label="Enable quarantine auto-release job"
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
          {status?.last_run ? (
            <>
              Last run <strong>{formatDateTime(status.last_run.ran_at)}</strong> —{" "}
              <strong>{status.last_run.checked_count}</strong> checked,{" "}
              <strong>{status.last_run.released_count} released</strong>,{" "}
              <strong>{status.last_run.failed_count}</strong> failed
            </>
          ) : (
            "No runs yet"
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div className="flex-1">
          <label htmlFor="quarantine-release-domains" className="text-sm font-medium text-slate-700">
            Trusted domains (comma-separated)
          </label>
          <input
            id="quarantine-release-domains"
            aria-label="Trusted domains"
            type="text"
            defaultValue={status?.allowed_domains.join(", ") ?? ""}
            onChange={(event) => setDomainsInput(event.target.value)}
            className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <button
          type="button"
          onClick={handleSaveDomains}
          disabled={settingsMutation.isPending}
          className="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          Save domains
        </button>
      </div>

      <div className="mt-6">
        <h3 className="text-sm font-semibold text-slate-700">Run history</h3>
        <div className="mt-2 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left">Hour</th>
                <th className="px-3 py-2 text-left">Checked</th>
                <th className="px-3 py-2 text-left">Released</th>
                <th className="px-3 py-2 text-left">Failed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(runsQuery.data?.items ?? []).map((run: QuarantineReleaseRun) => (
                <tr
                  key={run.run_hour}
                  onClick={() => setSelectedRunHour(run.run_hour)}
                  className={`cursor-pointer hover:bg-slate-50 ${selectedRunHour === run.run_hour ? "bg-sky-50" : ""}`}
                >
                  <td className="px-3 py-2">{formatDateTime(run.ran_at)}</td>
                  <td className="px-3 py-2">{run.checked_count}</td>
                  <td className="px-3 py-2">{run.released_count}</td>
                  <td className="px-3 py-2">{run.failed_count}</td>
                </tr>
              ))}
              {(runsQuery.data?.items ?? []).length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-center text-slate-500" colSpan={4}>
                    No runs yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-6">
        <h3 className="text-sm font-semibold text-slate-700">
          Released messages{selectedRunHour ? ` — ${formatDateTime(selectedRunHour)}` : ""}
        </h3>
        <div className="mt-2 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left">Sender</th>
                <th className="px-3 py-2 text-left">Recipient</th>
                <th className="px-3 py-2 text-left">Subject</th>
                <th className="px-3 py-2 text-left">Reason</th>
                <th className="px-3 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(releasesQuery.data?.items ?? []).map((release) => (
                <tr key={release.id} title={release.error ?? undefined}>
                  <td className="px-3 py-2">{release.sender_address}</td>
                  <td className="px-3 py-2">{release.recipient_address}</td>
                  <td className="px-3 py-2">{release.subject}</td>
                  <td className="px-3 py-2">{release.quarantine_reason}</td>
                  <td className={`px-3 py-2 ${release.status === "failed" ? "text-red-600" : "text-emerald-600"}`}>
                    {release.status}
                  </td>
                </tr>
              ))}
              {(releasesQuery.data?.items ?? []).length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-center text-slate-500" colSpan={5}>
                    No released messages yet.
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

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm run test:run -- QuarantineReleaseTool`
Expected: 3 passed

- [ ] **Step 5: Render the component from the Tools page**

In `frontend/src/pages/ToolsPage.tsx`:

Add the import near the existing `AdEmployeeNumberImportTool` import:
```typescript
import QuarantineReleaseTool from "../components/QuarantineReleaseTool.tsx";
```

Add the admin flag near `canUseAdEmployeeNumberImport` (around line 1853):
```typescript
  const canUseQuarantineRelease = !!meQuery.data?.is_admin;
```

Render it immediately after the existing `{isPrimaryScope && canUseAdEmployeeNumberImport ? <AdEmployeeNumberImportTool /> : null}` line:
```tsx
          {isPrimaryScope && canUseQuarantineRelease ? <QuarantineReleaseTool /> : null}
```

- [ ] **Step 6: Run the full frontend test suite and type-check**

Run: `cd frontend && npm run test:run && npx tsc --noEmit -p .`
Expected: all tests pass, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/QuarantineReleaseTool.tsx frontend/src/pages/ToolsPage.tsx frontend/src/__tests__/QuarantineReleaseTool.test.tsx
git commit -m "feat: add quarantine auto-release card to Tools page"
```

---

## Post-implementation notes for the operator (not a task — informational)

- The job is admin-only end to end (routes and UI). It starts disabled — an admin must flip the toggle on the Tools page after deploy.
- `Get-QuarantineMessage`/`Release-QuarantineMessage` require the same Exchange Online app-permission scope already granted for the existing mailbox-delegate and offboarding-tool PowerShell operations; no new Azure AD app permission should be needed, but confirm in the first live run since quarantine management permissions (`Quarantine.ReadWrite.*` in newer Exchange RBAC) can be scoped separately from mailbox permissions in some tenants.
- Because the job always uses `-ReleaseToAll` and never filters by quarantine category, verify the `allowed_domains` list is accurate before enabling — anything landing in quarantine from those domains, including phishing/malware, will be delivered.
