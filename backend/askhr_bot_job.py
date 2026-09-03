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
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from config import ASKHR_BOT_ENABLED_DEFAULT, DATA_DIR
from jira_client import JiraClient
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
        self._jira = JiraClient()

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
            # Keep this schema byte-for-byte identical to
            # storage_migrations/0029_askhr_bot.sql -- SQLite and Postgres
            # schemas must never drift. The primary key is composite because
            # the same email (same Message-ID) can be addressed to both
            # AskHR@ and Benefits@, and each mailbox must get its own ticket.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS askhr_bot_messages (
                    internet_message_id TEXT NOT NULL,
                    mailbox             TEXT NOT NULL,
                    graph_message_id    TEXT NOT NULL,
                    subject             TEXT NOT NULL DEFAULT '',
                    sender_email        TEXT NOT NULL DEFAULT '',
                    received_at         TEXT NOT NULL DEFAULT '',
                    status              TEXT NOT NULL,
                    jira_issue_key      TEXT,
                    error               TEXT,
                    processed_at        TEXT NOT NULL,
                    PRIMARY KEY (mailbox, internet_message_id)
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
        if not domains:
            # Fail CLOSED. get_transport_rule_domains() returns [] both for a
            # genuinely empty ExceptIfSenderDomainIs and for a degraded
            # Exchange response with no `domains` key at all -- and an empty
            # trusted_domains list means _should_process() treats *every*
            # sender as external, so one Exchange hiccup would mass-file HRD
            # tickets for internal mail for a full
            # domain_refresh_interval_seconds. Treat empty as
            # "refresh unavailable": keep the previous (possibly stale but
            # non-empty) list AND the previous trusted_domains_refreshed_at, so
            # the next cycle retries immediately and the staleness is visible
            # on /api/askhr-bot/status without needing a new field.
            logger.warning(
                "AskHR bot: trusted-domain refresh returned no domains for transport rule %r; "
                "keeping the previously cached list (last refreshed %r) and retrying next cycle",
                _TRANSPORT_RULE_IDENTITY,
                settings["trusted_domains_refreshed_at"] or "never",
            )
            return
        self._update_settings(
            trusted_domains=domains,
            trusted_domains_refreshed_at=_utcnow().isoformat(),
        )

    # ------------------------------------------------------------------
    # Ticket creation + attachment orchestration
    # ------------------------------------------------------------------

    def _azure_client(self):
        import azure_cache

        return azure_cache.azure_cache._client

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
        # The JiraClient session sets a *default* `Content-Type: application/json`
        # header at construction. requests.Session.merge_setting() only fills in a
        # per-call header from the session default when the per-call headers dict
        # doesn't already mention that key at all — it does NOT get displaced later
        # by the multipart encoder, because PreparedRequest.prepare_body() only sets
        # its own auto-computed `multipart/form-data; boundary=...` Content-Type when
        # no Content-Type header is already present after merging. So a bare
        # `headers={"X-Atlassian-Token": "no-check"}` here would silently ship the
        # session's stale `application/json` Content-Type on a multipart body,
        # corrupting the upload (missing boundary). Explicitly setting
        # `"Content-Type": None` in the per-call headers causes merge_setting() to
        # drop the key entirely (it deletes any merged key whose value is None),
        # so the multipart encoder can set the correct header. Verified empirically
        # in tests/test_askhr_bot_job.py.
        upload_response = self._jira.session.post(
            upload_url,
            files=files,
            headers={"X-Atlassian-Token": "no-check", "Content-Type": None},
            timeout=self._jira._TIMEOUT,
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

    # ------------------------------------------------------------------
    # Mailbox polling cycle
    # ------------------------------------------------------------------

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
            "ON CONFLICT (mailbox, internet_message_id) DO UPDATE SET "
            "graph_message_id = excluded.graph_message_id, status = excluded.status, "
            "jira_issue_key = excluded.jira_issue_key, "
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

    def _existing_message_row(
        self, mailbox: str, internet_message_id: str, conn: sqlite3.Connection
    ) -> dict[str, Any] | None:
        # Scoped by mailbox as well as Message-ID: the same email can land in
        # both AskHR@ and Benefits@, and each mailbox tracks its own ticket, so
        # a Message-ID-only lookup would let whichever mailbox is polled second
        # see the first one's row and silently skip creating its own ticket.
        ph = self._placeholder()
        row = conn.execute(
            f"SELECT status, jira_issue_key FROM askhr_bot_messages "
            f"WHERE mailbox = {ph} AND internet_message_id = {ph}",
            (mailbox, internet_message_id),
        ).fetchone()
        return dict(row) if row is not None else None

    async def _poll_mailbox(self, mailbox: str, settings: dict[str, Any]) -> None:
        import asyncio

        mailbox_address = MAILBOXES[mailbox]["address"]
        checkpoint_key = f"{mailbox}_checkpoint_at"
        checkpoint = settings[checkpoint_key]
        lookback = settings["lookback_minutes"]
        # NOTE on Z-suffix handling: Microsoft Graph's receivedDateTime (and any
        # checkpoint value we derive from it below) is UTC with a literal "Z"
        # suffix, e.g. "2026-09-03T11:00:00Z". datetime.fromisoformat() only
        # gained native "Z" support in Python 3.11 -- this repo's backend venv is
        # 3.12 (verified via `backend/.venv/bin/python --version`), so no
        # `.replace("Z", "+00:00")` normalization is required here. See
        # tests/test_askhr_bot_job.py::test_poll_mailbox_lookback_window_handles_z_suffixed_checkpoint
        # for an end-to-end check of this exact path.
        if checkpoint:
            since = datetime.fromisoformat(checkpoint) - timedelta(minutes=lookback)
        else:
            since = _utcnow() - timedelta(minutes=lookback)
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
        latest_received_dt: datetime | None = None

        for graph_message in graph_messages:
            internet_message_id = str(graph_message.get("internetMessageId") or "").strip()
            if not internet_message_id:
                continue
            received_raw = str(graph_message.get("receivedDateTime") or "")
            received_dt = datetime.fromisoformat(received_raw) if received_raw else None
            # Normalize to "+00:00" (rather than storing the raw "Z" form) so a
            # checkpoint written here parses identically however it's re-read.
            received_at = received_dt.isoformat() if received_dt is not None else received_raw
            if received_dt is not None and (latest_received_dt is None or received_dt > latest_received_dt):
                latest_received_dt = received_dt

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
                existing = self._existing_message_row(mailbox, internet_message_id, conn)

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

        if latest_received_dt is not None:
            self._update_settings(**{checkpoint_key: latest_received_dt.isoformat()})

    async def run_cycle(self) -> None:
        import asyncio

        settings = self._get_settings()
        if not settings["enabled"]:
            return
        # _refresh_trusted_domains_if_needed() can do blocking subprocess I/O
        # (Exchange Online PowerShell via pwsh, up to the configured timeout,
        # ~240s) when the cached trusted-domain list is stale. run_cycle is
        # awaited directly from the shared FastAPI event loop, so calling it
        # synchronously here would stall every other request and background
        # service on that loop for the duration -- run it off-loop, matching
        # the run_in_executor pattern quarantine_release_job.py's
        # run_hourly_job already uses for the same class of blocking call.
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._refresh_trusted_domains_if_needed)
        settings = self._get_settings()
        for mailbox in MAILBOXES:
            await self._poll_mailbox(mailbox, settings)

    # ------------------------------------------------------------------
    # Background runner
    # ------------------------------------------------------------------

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


askhr_bot_job = AskHrBotJob()
