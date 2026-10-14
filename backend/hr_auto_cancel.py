"""Automatically move HR-board tickets from configured sender domains (osidigital.com) to "Cancelled by HR".

A leader-only loop looks at tickets created in the last ``HR_AUTO_CANCEL_LOOKBACK_MINUTES`` that are still in their
initial ("To Do" category) status. If the reporter's email is on a listed domain it applies the project's transition
whose target status is ``HR_AUTO_CANCEL_STATUS`` and leaves one internal note. A durable once-only ledger
(``hr_auto_cancel_actions``) means a ticket someone reopens is never cancelled a second time, and a blue/green overlap
cannot act twice. A project whose workflow has no such status (LIBTA today) is recorded ``no_transition`` and left alone.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from config import (
    DATA_DIR,
    HR_AUTO_CANCEL_ENABLED,
    HR_AUTO_CANCEL_LOOKBACK_MINUTES,
    HR_AUTO_CANCEL_POLL_SECONDS,
    HR_AUTO_CANCEL_PROJECTS,
    HR_AUTO_CANCEL_SENDER_DOMAINS,
    HR_AUTO_CANCEL_STATUS,
)
from jira_client import JiraClient
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

RESULT_PENDING = "pending"
RESULT_CANCELLED = "cancelled"
RESULT_NO_TRANSITION = "no_transition"
RESULT_FAILED = "failed"
_MAX_ATTEMPTS = 5
_DB_PATH = os.path.join(DATA_DIR, "hr_auto_cancel.db")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sender_email(fields: dict[str, Any]) -> str:
    """Lowercased email of the reporter (the creator if the reporter's is hidden); '' if neither is visible."""
    for role in ("reporter", "creator"):
        email = str(((fields.get(role) or {}).get("emailAddress")) or "").strip().lower()
        if "@" in email:
            return email
    return ""


def matches_domain(email: str, domains: list[str]) -> bool:
    domain = email.rpartition("@")[2]
    return bool(domain) and any(domain == d or domain.endswith("." + d) for d in domains)


class HrAutoCancelJob:
    def __init__(self, db_path: str | None = None, *, jira: Any = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._use_postgres = postgres_enabled() and db_path is None
        self._jira = jira
        self._bg_task: asyncio.Task[None] | None = None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _ph(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _conn(self):
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return connect_sqlite(self._db_path)

    def _jira_client(self) -> Any:
        if self._jira is None:
            self._jira = JiraClient()
        return self._jira

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            return
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS hr_auto_cancel_actions (
                    issue_key      TEXT PRIMARY KEY,
                    project_key    TEXT NOT NULL DEFAULT '',
                    sender         TEXT NOT NULL DEFAULT '',
                    from_status    TEXT NOT NULL DEFAULT '',
                    to_status      TEXT NOT NULL DEFAULT '',
                    result         TEXT NOT NULL DEFAULT 'pending',
                    attempts       INTEGER NOT NULL DEFAULT 0,
                    first_seen_at  TEXT NOT NULL,
                    acted_at       TEXT NOT NULL DEFAULT '',
                    error          TEXT NOT NULL DEFAULT ''
                )"""
            )

    # ------------------------------------------------------------------ ledger

    def get_row(self, key: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(f"SELECT * FROM hr_auto_cancel_actions WHERE issue_key = {self._ph()}", (key,)).fetchone()
        return dict(row) if row is not None else None

    def list_rows(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                f"SELECT * FROM hr_auto_cancel_actions ORDER BY first_seen_at DESC LIMIT {int(limit)}").fetchall()]

    def summary(self) -> dict[str, Any]:
        with self._conn() as conn:
            counts = {r["result"]: int(r["cnt"]) for r in conn.execute(
                "SELECT result, COUNT(*) AS cnt FROM hr_auto_cancel_actions GROUP BY result").fetchall()}
        return {"counts": {k: counts.get(k, 0) for k in (RESULT_CANCELLED, RESULT_PENDING, RESULT_NO_TRANSITION, RESULT_FAILED)}}

    def _claim(self, key: str, project: str, sender: str, from_status: str, now: datetime) -> bool:
        """Record the ticket once; False if a ledger row exists (already handled, or another runner has it)."""
        ph = self._ph()
        with self._conn() as conn:
            cur = conn.execute(
                f"""INSERT INTO hr_auto_cancel_actions (issue_key, project_key, sender, from_status, first_seen_at)
                    VALUES ({ph},{ph},{ph},{ph},{ph}) ON CONFLICT (issue_key) DO NOTHING""",
                (key, project, sender, from_status, now.isoformat()),
            )
            return bool(cur.rowcount)

    def _resolve(self, key: str, result: str, now: datetime, *, to_status: str = "", error: str = "") -> None:
        ph = self._ph()
        with self._conn() as conn:
            conn.execute(
                f"""UPDATE hr_auto_cancel_actions
                    SET result = {ph}, acted_at = {ph}, to_status = {ph}, error = {ph}, attempts = attempts + 1
                    WHERE issue_key = {ph}""",
                (result, now.isoformat(), to_status, error[:1000], key),
            )

    # ------------------------------------------------------------------ core

    def _candidates(self) -> list[dict[str, Any]]:
        projects = ", ".join(HR_AUTO_CANCEL_PROJECTS)
        jql = (
            f'project in ({projects}) AND statusCategory = "To Do" '
            f"AND created >= -{int(HR_AUTO_CANCEL_LOOKBACK_MINUTES)}m ORDER BY created ASC"
        )
        out = []
        for issue in self._jira_client().search_all(jql, fields=["reporter", "creator", "status", "project"]):
            fields = issue.get("fields") or {}
            email = sender_email(fields)
            if email and matches_domain(email, HR_AUTO_CANCEL_SENDER_DOMAINS):
                out.append({
                    "key": str(issue["key"]),
                    "project": str((fields.get("project") or {}).get("key") or ""),
                    "sender": email,
                    "status": str((fields.get("status") or {}).get("name") or ""),
                })
        return out

    def preview(self) -> list[dict[str, Any]]:
        """What the next cycle would cancel right now (nothing already in the ledger). Read-only."""
        return [c for c in self._candidates() if self.get_row(c["key"]) is None]

    def _transition_id(self, key: str) -> str | None:
        for t in self._jira_client().get_transitions(key):
            if str((t.get("to") or {}).get("name") or "").strip().lower() == HR_AUTO_CANCEL_STATUS.lower():
                return str(t["id"])
        return None

    def _act(self, cand: dict[str, Any], now: datetime) -> None:
        key = cand["key"]
        jira = self._jira_client()
        try:
            transition_id = self._transition_id(key)
            if transition_id is None:
                self._resolve(key, RESULT_NO_TRANSITION, now,
                              error=f"{cand['project']} has no '{HR_AUTO_CANCEL_STATUS}' transition from '{cand['status']}'")
                return
            jira.transition_issue(key, transition_id)
        except Exception as exc:  # noqa: BLE001 - recorded and retried while inside the lookback window
            logger.warning("HR auto-cancel %s failed: %s", key, exc)
            self._resolve(key, RESULT_FAILED, now, error=f"{type(exc).__name__}: {exc}")
            return
        self._resolve(key, RESULT_CANCELLED, now, to_status=HR_AUTO_CANCEL_STATUS)
        try:
            jira.add_internal_comment(
                key,
                f"Automatically set to '{HR_AUTO_CANCEL_STATUS}': the request came from {cand['sender']}, "
                f"a sender domain on the HR auto-cancel list ({', '.join(HR_AUTO_CANCEL_SENDER_DOMAINS)}). "
                "Reopen the ticket if this was wrong; it will not be cancelled again.",
            )
        except Exception:
            logger.exception("HR auto-cancel: cancelled %s but could not add the internal note", key)
        logger.info("HR auto-cancel: %s (%s) -> %s", key, cand["sender"], HR_AUTO_CANCEL_STATUS)

    def run_cycle_sync(self, now: datetime | None = None) -> dict[str, int]:
        now = now or _utcnow()
        acted = retried = 0
        for cand in self._candidates():
            row = self.get_row(cand["key"])
            if row is None:
                if not self._claim(cand["key"], cand["project"], cand["sender"], cand["status"], now):
                    continue  # another runner claimed it
                self._act(cand, now)
                acted += 1
            elif row["result"] == RESULT_FAILED and int(row["attempts"]) < _MAX_ATTEMPTS:
                self._act(cand, now)
                retried += 1
        return {"cancelled_or_attempted": acted, "retried": retried}

    async def run_cycle(self) -> dict[str, int]:
        return await asyncio.to_thread(self.run_cycle_sync)

    def start_background_runner(self) -> None:
        self._bg_task = asyncio.get_event_loop().create_task(self._run_loop())

    def stop_background_runner(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()

    async def _run_loop(self) -> None:
        while True:
            try:
                if HR_AUTO_CANCEL_ENABLED:
                    await self.run_cycle()
                await asyncio.sleep(max(15, HR_AUTO_CANCEL_POLL_SECONDS))
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("HR auto-cancel loop error")
                await asyncio.sleep(120)


hr_auto_cancel_job = HrAutoCancelJob()
