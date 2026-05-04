# Password Expiry Email Notifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send a daily HTML email to every enabled AD user whose password expires within 14 days, until they reset it, with tracking in the database and a test-mode toggle.

**Architecture:** A leader-only background service (`password_expiry_notifier.py`) mirrors the `deactivation_schedule.py` pattern — a class with an asyncio poll loop that fires once per calendar day. It fetches all AD users, filters by expiry window, sends email via the existing `email_service.send_email`, and records every notification and daily run to SQLite/Postgres. Starts in test mode (logs only) until `PASSWORD_EXPIRY_NOTIFY_ENABLED=true`.

**Tech Stack:** Python 3.11+, ldap3 (via existing `ad_client`), httpx (via existing `email_service`), asyncio, SQLite/Postgres (dual-write pattern from `deactivation_schedule.py`)

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `backend/storage_migrations/0024_password_expiry_notifications.sql` | Schema for notifications + daily runs tables |
| Modify | `backend/config.py` | Three new env vars |
| Create | `backend/password_expiry_notifier.py` | Notifier class + background runner |
| Create | `backend/tests/test_password_expiry_notifier.py` | Unit + integration tests |
| Modify | `backend/main.py` | Wire up as leader-only service |

---

## Task 1: SQL Migration

**Files:**
- Create: `backend/storage_migrations/0024_password_expiry_notifications.sql`

- [ ] **Step 1: Create the migration file**

```sql
CREATE TABLE IF NOT EXISTS password_expiry_notifications (
    id                  TEXT PRIMARY KEY,
    sam_account_name    TEXT NOT NULL,
    email               TEXT NOT NULL,
    expiry_date         TEXT NOT NULL,
    days_until_expiry   INTEGER NOT NULL,
    notified_at         TEXT NOT NULL,
    test_mode           SMALLINT NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_pen_sam_date
    ON password_expiry_notifications (sam_account_name, notified_at);

CREATE TABLE IF NOT EXISTS password_expiry_notify_runs (
    run_date        TEXT PRIMARY KEY,
    ran_at          TEXT NOT NULL,
    users_notified  INTEGER NOT NULL DEFAULT 0,
    test_mode       SMALLINT NOT NULL DEFAULT 1
);
```

- [ ] **Step 2: Verify migration file is in the right place**

```bash
ls backend/storage_migrations/0024_password_expiry_notifications.sql
```

Expected: file exists with no error.

- [ ] **Step 3: Commit**

```bash
git add backend/storage_migrations/0024_password_expiry_notifications.sql
git commit -m "feat: add password expiry notification tables (migration 0024)"
```

---

## Task 2: Config Vars

**Files:**
- Modify: `backend/config.py` (append after the `AD_BIND_PASSWORD` block at line ~408)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_password_expiry_notifier.py` with:

```python
"""Tests for password expiry notifier."""
import importlib
import os
import sys


def test_config_defaults(monkeypatch):
    """Config vars have correct defaults."""
    monkeypatch.delenv("PASSWORD_EXPIRY_NOTIFY_ENABLED", raising=False)
    monkeypatch.delenv("AD_MAX_PWD_AGE_DAYS", raising=False)
    monkeypatch.delenv("PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE", raising=False)

    # Re-import config with cleared env
    if "config" in sys.modules:
        del sys.modules["config"]
    import config as cfg

    assert cfg.PASSWORD_EXPIRY_NOTIFY_ENABLED is False
    assert cfg.AD_MAX_PWD_AGE_DAYS == 90
    assert cfg.PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE == 14
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_password_expiry_notifier.py::test_config_defaults -v
```

Expected: `FAILED` — `AttributeError: module 'config' has no attribute 'PASSWORD_EXPIRY_NOTIFY_ENABLED'`

- [ ] **Step 3: Add the config vars**

Open `backend/config.py`. After the line `AD_BIND_PASSWORD: str = os.getenv("AD_BIND_PASSWORD", "").strip()` add:

```python

# Password expiry email notifications
PASSWORD_EXPIRY_NOTIFY_ENABLED: bool = os.getenv("PASSWORD_EXPIRY_NOTIFY_ENABLED", "").strip().lower() in {"1", "true", "yes"}
AD_MAX_PWD_AGE_DAYS: int = int(os.getenv("AD_MAX_PWD_AGE_DAYS", "90"))
PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE: int = int(os.getenv("PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE", "14"))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_password_expiry_notifier.py::test_config_defaults -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/config.py backend/tests/test_password_expiry_notifier.py
git commit -m "feat: add password expiry notifier config vars"
```

---

## Task 3: Core Notifier Module

**Files:**
- Create: `backend/password_expiry_notifier.py`
- Modify: `backend/tests/test_password_expiry_notifier.py`

### 3a: Expiry calculation helper

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_password_expiry_notifier.py`:

```python
from datetime import date, datetime, timezone, timedelta


def _make_user(pwd_last_set_days_ago: int | None, enabled: bool = True, email: str = "user@example.com") -> dict:
    if pwd_last_set_days_ago is None:
        pwd_last_set = None
    else:
        dt = datetime.now(timezone.utc) - timedelta(days=pwd_last_set_days_ago)
        pwd_last_set = dt.isoformat()
    return {
        "sam_account_name": "jdoe",
        "display_name": "Jane Doe",
        "email": email,
        "pwd_last_set": pwd_last_set,
        "flags": {"enabled": enabled},
    }


def test_days_until_expiry_normal():
    from password_expiry_notifier import _days_until_expiry
    # Password set 80 days ago with 90-day max age → 10 days left
    result = _days_until_expiry(_make_user(80), max_age_days=90)
    assert result == 10


def test_days_until_expiry_no_pwd_last_set():
    from password_expiry_notifier import _days_until_expiry
    result = _days_until_expiry(_make_user(None), max_age_days=90)
    assert result is None


def test_days_until_expiry_already_expired():
    from password_expiry_notifier import _days_until_expiry
    # Password set 95 days ago → already expired
    result = _days_until_expiry(_make_user(95), max_age_days=90)
    assert result is not None and result <= 0


def test_should_notify_true():
    from password_expiry_notifier import _should_notify
    # 10 days left, window is 14 → should notify
    user = _make_user(80)
    days = _should_notify(user, max_age_days=90, days_before=14)
    assert days == 10


def test_should_notify_false_outside_window():
    from password_expiry_notifier import _should_notify
    # 30 days left → outside 14-day window
    user = _make_user(60)
    assert _should_notify(user, max_age_days=90, days_before=14) is None


def test_should_notify_false_disabled():
    from password_expiry_notifier import _should_notify
    user = _make_user(80, enabled=False)
    assert _should_notify(user, max_age_days=90, days_before=14) is None


def test_should_notify_false_no_email():
    from password_expiry_notifier import _should_notify
    user = _make_user(80, email="")
    assert _should_notify(user, max_age_days=90, days_before=14) is None


def test_should_notify_false_no_pwd_last_set():
    from password_expiry_notifier import _should_notify
    user = _make_user(None)
    assert _should_notify(user, max_age_days=90, days_before=14) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_password_expiry_notifier.py -k "expiry or should_notify" -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'password_expiry_notifier'`

- [ ] **Step 3: Write the minimal implementation**

Create `backend/password_expiry_notifier.py`:

```python
"""Daily password-expiry email notifier.

Runs once per calendar day as a leader-only background service.
Notifies enabled AD users whose passwords expire within the configured
window. Starts in test mode (logs only) until PASSWORD_EXPIRY_NOTIFY_ENABLED=true.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from config import (
    AD_MAX_PWD_AGE_DAYS,
    DATA_DIR,
    PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE,
    PASSWORD_EXPIRY_NOTIFY_ENABLED,
)
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 60  # seconds
_DB_PATH = os.path.join(DATA_DIR, "password_expiry_notifier.db")

_RESET_URL = "https://myaccount.microsoft.com/?ref=MeControl"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _today_str() -> str:
    return _utcnow().date().isoformat()


# ---------------------------------------------------------------------------
# Pure helpers — no I/O, easy to unit-test
# ---------------------------------------------------------------------------


def _days_until_expiry(user: dict[str, Any], *, max_age_days: int) -> int | None:
    """Return days until the user's password expires, or None if unknown."""
    pwd_last_set = user.get("pwd_last_set")
    if not pwd_last_set:
        return None
    try:
        last_set = datetime.fromisoformat(pwd_last_set).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    expiry = last_set + timedelta(days=max_age_days)
    return (expiry.date() - _utcnow().date()).days


def _should_notify(
    user: dict[str, Any],
    *,
    max_age_days: int,
    days_before: int,
) -> int | None:
    """Return days_until_expiry if the user should be notified, else None."""
    if not user.get("flags", {}).get("enabled"):
        return None
    if not user.get("email"):
        return None
    days = _days_until_expiry(user, max_age_days=max_age_days)
    if days is None:
        return None
    if days <= 0 or days > days_before:
        return None
    return days


def _build_email_body(display_name: str, days: int, expiry_date: str) -> str:
    name = display_name or "there"
    return f"""<p>Hi {name},</p>
<p>Your network password will expire in <strong>{days} day(s)</strong> (on {expiry_date}).</p>
<p>Please reset it before it expires to avoid losing access:</p>
<p><a href="{_RESET_URL}">Reset your password</a></p>
<p>If you need help, contact the IT Help Desk.</p>
<p>— IT Team</p>"""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_password_expiry_notifier.py -k "expiry or should_notify" -v
```

Expected: all 7 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/password_expiry_notifier.py backend/tests/test_password_expiry_notifier.py
git commit -m "feat: add password expiry calculation helpers with tests"
```

---

### 3b: Database and PasswordExpiryNotifier class

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_password_expiry_notifier.py`:

```python
import sqlite3
import tempfile
import os


def _make_notifier(tmp_path: str, enabled: bool = False):
    from password_expiry_notifier import PasswordExpiryNotifier
    db = os.path.join(tmp_path, "test_pen.db")
    notifier = PasswordExpiryNotifier(db_path=db)
    notifier._notify_enabled = enabled
    return notifier


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def test_already_ran_today_false(tmp_path):
    n = _make_notifier(str(tmp_path))
    with n._sqlite_conn() as conn:
        assert n._already_ran_today(conn) is False


def test_already_ran_today_true(tmp_path):
    n = _make_notifier(str(tmp_path))
    today = _today()
    with n._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO password_expiry_notify_runs (run_date, ran_at, users_notified, test_mode) VALUES (?,?,?,?)",
            (today, datetime.now(timezone.utc).isoformat(), 0, 1),
        )
        assert n._already_ran_today(conn) is True


def test_already_notified_today_false(tmp_path):
    n = _make_notifier(str(tmp_path))
    with n._sqlite_conn() as conn:
        assert n._already_notified_today("jdoe", conn) is False


def test_already_notified_today_true(tmp_path):
    n = _make_notifier(str(tmp_path))
    today = _today()
    with n._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO password_expiry_notifications (id, sam_account_name, email, expiry_date, days_until_expiry, notified_at, test_mode) VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, "jdoe", "jdoe@x.com", "2026-06-01", 5, f"{today}T00:00:00+00:00", 1),
        )
        assert n._already_notified_today("jdoe", conn) is True


def test_already_notified_today_different_day(tmp_path):
    n = _make_notifier(str(tmp_path))
    with n._sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO password_expiry_notifications (id, sam_account_name, email, expiry_date, days_until_expiry, notified_at, test_mode) VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, "jdoe", "jdoe@x.com", "2026-06-01", 5, "2020-01-01T00:00:00+00:00", 1),
        )
        assert n._already_notified_today("jdoe", conn) is False


def test_record_notification_writes_row(tmp_path):
    n = _make_notifier(str(tmp_path))
    with n._sqlite_conn() as conn:
        n._record_notification(
            sam="jdoe",
            email="jdoe@x.com",
            expiry_date="2026-06-01",
            days=10,
            test_mode=True,
            conn=conn,
        )
        row = conn.execute(
            "SELECT * FROM password_expiry_notifications WHERE sam_account_name='jdoe'"
        ).fetchone()
    assert row is not None
    assert row["days_until_expiry"] == 10
    assert row["test_mode"] == 1


def test_record_run_writes_row(tmp_path):
    n = _make_notifier(str(tmp_path))
    today = _today_str()
    with n._sqlite_conn() as conn:
        n._record_run(users_notified=3, test_mode=True, conn=conn)
        row = conn.execute(
            "SELECT * FROM password_expiry_notify_runs WHERE run_date=?", (today,)
        ).fetchone()
    assert row is not None
    assert row["users_notified"] == 3
    assert row["test_mode"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_password_expiry_notifier.py -k "already_ran or already_notified or record_" -v
```

Expected: `FAILED` — `ImportError` or `AttributeError`

- [ ] **Step 3: Add the PasswordExpiryNotifier class to `backend/password_expiry_notifier.py`**

Append to the end of `backend/password_expiry_notifier.py`:

```python

# ---------------------------------------------------------------------------
# PasswordExpiryNotifier
# ---------------------------------------------------------------------------


class PasswordExpiryNotifier:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        self._notify_enabled = PASSWORD_EXPIRY_NOTIFY_ENABLED
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._bg_task: asyncio.Task[None] | None = None
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
                CREATE TABLE IF NOT EXISTS password_expiry_notifications (
                    id                  TEXT PRIMARY KEY,
                    sam_account_name    TEXT NOT NULL,
                    email               TEXT NOT NULL,
                    expiry_date         TEXT NOT NULL,
                    days_until_expiry   INTEGER NOT NULL,
                    notified_at         TEXT NOT NULL,
                    test_mode           SMALLINT NOT NULL DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pen_sam_date
                    ON password_expiry_notifications (sam_account_name, notified_at)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS password_expiry_notify_runs (
                    run_date        TEXT PRIMARY KEY,
                    ran_at          TEXT NOT NULL,
                    users_notified  INTEGER NOT NULL DEFAULT 0,
                    test_mode       SMALLINT NOT NULL DEFAULT 1
                )
            """)

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _already_ran_today(self, conn: sqlite3.Connection) -> bool:
        ph = self._placeholder()
        row = conn.execute(
            f"SELECT 1 FROM password_expiry_notify_runs WHERE run_date = {ph}",
            (_today_str(),),
        ).fetchone()
        return row is not None

    def _already_notified_today(self, sam: str, conn: sqlite3.Connection) -> bool:
        ph = self._placeholder()
        today = _today_str()
        row = conn.execute(
            f"SELECT 1 FROM password_expiry_notifications WHERE sam_account_name = {ph} AND notified_at LIKE {ph}",
            (sam, f"{today}%"),
        ).fetchone()
        return row is not None

    def _record_notification(
        self,
        *,
        sam: str,
        email: str,
        expiry_date: str,
        days: int,
        test_mode: bool,
        conn: sqlite3.Connection,
    ) -> None:
        ph = self._placeholder()
        conn.execute(
            f"""INSERT INTO password_expiry_notifications
                (id, sam_account_name, email, expiry_date, days_until_expiry, notified_at, test_mode)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
            (
                uuid.uuid4().hex,
                sam,
                email,
                expiry_date,
                days,
                _utcnow().isoformat(),
                1 if test_mode else 0,
            ),
        )

    def _record_run(
        self,
        *,
        users_notified: int,
        test_mode: bool,
        conn: sqlite3.Connection,
    ) -> None:
        ph = self._placeholder()
        conn.execute(
            f"""INSERT INTO password_expiry_notify_runs (run_date, ran_at, users_notified, test_mode)
                VALUES ({ph},{ph},{ph},{ph})
                ON CONFLICT (run_date) DO UPDATE SET
                    ran_at = excluded.ran_at,
                    users_notified = excluded.users_notified,
                    test_mode = excluded.test_mode""",
            (_today_str(), _utcnow().isoformat(), users_notified, 1 if test_mode else 0),
        )

    # ------------------------------------------------------------------
    # Daily job
    # ------------------------------------------------------------------

    async def run_daily_job(self) -> None:
        import ad_client as ad
        import email_service

        loop = asyncio.get_event_loop()

        with self._conn() as conn:
            if self._already_ran_today(conn):
                return

        logger.info(
            "Password expiry notifier: starting daily job (test_mode=%s)",
            not self._notify_enabled,
        )

        try:
            result = await loop.run_in_executor(
                None,
                lambda: ad.search_users(page=1, limit=10000),
            )
        except Exception:
            logger.exception("Password expiry notifier: failed to fetch AD users")
            return

        users = result.get("items", [])
        notified = 0

        for user in users:
            sam = user.get("sam_account_name", "")
            email = user.get("email", "")
            display_name = user.get("display_name", "")

            days = _should_notify(
                user,
                max_age_days=AD_MAX_PWD_AGE_DAYS,
                days_before=PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE,
            )
            if days is None:
                continue

            with self._conn() as conn:
                if self._already_notified_today(sam, conn):
                    continue

            last_set = datetime.fromisoformat(user["pwd_last_set"]).replace(tzinfo=timezone.utc)
            expiry_date = (last_set + timedelta(days=AD_MAX_PWD_AGE_DAYS)).date().isoformat()

            if not self._notify_enabled:
                logger.info(
                    "[TEST MODE] Would notify %s <%s> — password expires in %d day(s) on %s",
                    sam, email, days, expiry_date,
                )
            else:
                subject = f"Your password expires in {days} day(s) — action required"
                body = _build_email_body(display_name, days, expiry_date)
                sent = await email_service.send_email(to=[email], subject=subject, html_body=body)
                if not sent:
                    logger.error("Password expiry notifier: failed to send email to %s", email)
                    continue

            with self._conn() as conn:
                self._record_notification(
                    sam=sam,
                    email=email,
                    expiry_date=expiry_date,
                    days=days,
                    test_mode=not self._notify_enabled,
                    conn=conn,
                )
            notified += 1

        with self._conn() as conn:
            self._record_run(
                users_notified=notified,
                test_mode=not self._notify_enabled,
                conn=conn,
            )

        logger.info(
            "Password expiry notifier: daily job complete — %d user(s) notified (test_mode=%s)",
            notified,
            not self._notify_enabled,
        )

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
                await asyncio.sleep(_POLL_INTERVAL)
                await self.run_daily_job()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Password expiry notifier loop error")


password_expiry_notifier = PasswordExpiryNotifier()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_password_expiry_notifier.py -k "already_ran or already_notified or record_" -v
```

Expected: all 7 tests `PASSED`

- [ ] **Step 5: Run full test file**

```bash
cd backend && python -m pytest tests/test_password_expiry_notifier.py -v
```

Expected: all tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend/password_expiry_notifier.py backend/tests/test_password_expiry_notifier.py
git commit -m "feat: add PasswordExpiryNotifier class with DB tracking and background runner"
```

---

## Task 4: Wire into main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add the import**

In `backend/main.py`, after the line `from deactivation_schedule import deactivation_schedule as _deactivation_schedule_store` (line ~51), add:

```python
from password_expiry_notifier import password_expiry_notifier as _password_expiry_notifier
```

- [ ] **Step 2: Start the runner in `_start_deferred_services`**

In `backend/main.py`, inside `_start_deferred_services`, after the block that starts `_deactivation_schedule_store.start_background_runner()` (~line 138), add:

```python
    try:
        _password_expiry_notifier.start_background_runner()
    except Exception:
        logger.exception("Failed to start password expiry notifier")
```

- [ ] **Step 3: Stop the runner in `_stop_leader_services`**

In `backend/main.py`, inside `_stop_leader_services`, after the line `_deactivation_schedule_store.stop_background_runner()` (~line 185), add:

```python
    _password_expiry_notifier.stop_background_runner()
```

- [ ] **Step 4: Verify the backend imports cleanly**

```bash
cd backend && python -c "import main; print('OK')"
```

Expected: `OK` with no import errors.

- [ ] **Step 5: Run the full backend test suite to check for regressions**

```bash
cd backend && python -m pytest tests/ -x -q 2>&1 | tail -20
```

Expected: all existing tests pass, new tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py
git commit -m "feat: wire password expiry notifier into leader-only background services"
```

---

## Verification Checklist

After all tasks complete:

- [ ] `backend/storage_migrations/0024_password_expiry_notifications.sql` exists and creates both tables
- [ ] `config.PASSWORD_EXPIRY_NOTIFY_ENABLED` defaults to `False`
- [ ] `config.AD_MAX_PWD_AGE_DAYS` defaults to `90`
- [ ] `config.PASSWORD_EXPIRY_NOTIFY_DAYS_BEFORE` defaults to `14`
- [ ] All 14 tests in `test_password_expiry_notifier.py` pass
- [ ] `python -c "import main; print('OK')"` succeeds
- [ ] Backend test suite is green

## Enabling for Real Sends

Set in `backend/.env`:

```
PASSWORD_EXPIRY_NOTIFY_ENABLED=true
```

The service will send live emails on its next daily run. Check logs for `Password expiry notifier: daily job complete`.
