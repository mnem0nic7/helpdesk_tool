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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS password_expiry_notifier_settings (
                    id          INTEGER PRIMARY KEY DEFAULT 1,
                    enabled     SMALLINT NOT NULL DEFAULT 0,
                    updated_at  TEXT NOT NULL DEFAULT '',
                    updated_by  TEXT NOT NULL DEFAULT ''
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

    def _get_notify_enabled(self) -> bool:
        """Read enabled from DB settings row; fall back to env-var default."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT enabled FROM password_expiry_notifier_settings WHERE id = 1"
            ).fetchone()
        return bool(row["enabled"]) if row is not None else self._notify_enabled

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

        notify_enabled = self._get_notify_enabled()

        logger.info(
            "Password expiry notifier: starting daily job (test_mode=%s)",
            not notify_enabled,
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

            if not notify_enabled:
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
                    test_mode=not notify_enabled,
                    conn=conn,
                )
            notified += 1

        with self._conn() as conn:
            self._record_run(
                users_notified=notified,
                test_mode=not notify_enabled,
                conn=conn,
            )

        logger.info(
            "Password expiry notifier: daily job complete — %d user(s) notified (test_mode=%s)",
            notified,
            not notify_enabled,
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
