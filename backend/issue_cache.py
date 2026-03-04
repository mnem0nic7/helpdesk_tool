"""Issue cache with SQLite persistence and incremental background refresh."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR, JIRA_PROJECT
from jira_client import JiraClient

logger = logging.getLogger(__name__)

# JQL filters
_ALL_JQL = f"project = {JIRA_PROJECT} ORDER BY key ASC"
_FILTERED_JQL = (
    f'project = {JIRA_PROJECT} AND (labels is EMPTY OR labels not in ("oasisdev"))'
)

# Refresh interval in seconds
_REFRESH_INTERVAL = 600  # 10 minutes


class IssueCache:
    """Thread-safe in-memory cache of Jira issues.

    Two views:
      - filtered (excludes oasisdev) — used by metrics/SLA endpoints
      - all issues — used by export
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._client = JiraClient()
        self._lock = threading.Lock()
        self._init_event = threading.Event()

        # Issue dicts keyed by issue key
        self._issues: dict[str, dict[str, Any]] = {}
        self._all_issues: dict[str, dict[str, Any]] = {}

        self._initialized = False
        self._refreshing = False
        self._last_refresh: datetime | None = None
        self._bg_task: asyncio.Task[None] | None = None

        # Auto-triage: keys already processed (lazy-loaded from DB)
        self._auto_triage_seen: set[str] | None = None

        # SQLite persistence
        self._db_path = db_path or os.path.join(DATA_DIR, "issues_cache.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

        # Eagerly restore from SQLite so tickets are available immediately
        if self._load_from_db():
            self._init_event.set()

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def refreshing(self) -> bool:
        return self._refreshing

    @property
    def issue_count(self) -> int:
        return len(self._all_issues)

    @property
    def filtered_count(self) -> int:
        return len(self._issues)

    @property
    def last_refresh(self) -> datetime | None:
        return self._last_refresh

    def get_filtered_issues(self) -> list[dict[str, Any]]:
        """Return filtered issues (excludes oasisdev). Blocks until init."""
        self._ensure_initialized()
        with self._lock:
            return list(self._issues.values())

    def get_all_issues(self) -> list[dict[str, Any]]:
        """Return all issues (including excluded). Blocks until init."""
        self._ensure_initialized()
        with self._lock:
            return list(self._all_issues.values())

    def status(self) -> dict[str, Any]:
        return {
            "initialized": self._initialized,
            "refreshing": self._refreshing,
            "issue_count": len(self._all_issues),
            "filtered_count": len(self._issues),
            "last_refresh": (
                self._last_refresh.isoformat() if self._last_refresh else None
            ),
        }

    # ------------------------------------------------------------------
    # SQLite persistence
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the SQLite table if it doesn't exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS issues "
                "(key TEXT PRIMARY KEY, data TEXT, excluded INTEGER)"
            )

    def _load_from_db(self) -> bool:
        """Populate in-memory dicts from SQLite. Returns True if rows existed."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT key, data, excluded FROM issues").fetchall()
        if not rows:
            return False
        new_all: dict[str, dict[str, Any]] = {}
        new_filtered: dict[str, dict[str, Any]] = {}
        for key, data, excluded in rows:
            issue = json.loads(data)
            new_all[key] = issue
            if not excluded:
                new_filtered[key] = issue
        with self._lock:
            self._all_issues = new_all
            self._issues = new_filtered
            self._initialized = True
            self._last_refresh = datetime.now(timezone.utc)
        logger.info(
            "Cache: restored %d total, %d filtered from SQLite",
            len(new_all),
            len(new_filtered),
        )
        return True

    def _save_all_to_db(self) -> None:
        """Replace entire DB contents with current in-memory state."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM issues")
            conn.executemany(
                "INSERT INTO issues (key, data, excluded) VALUES (?, ?, ?)",
                [
                    (key, json.dumps(issue), int(key not in self._issues))
                    for key, issue in self._all_issues.items()
                ],
            )
        logger.info("Cache: wrote %d issues to SQLite", len(self._all_issues))

    def _upsert_to_db(self, issues: list[dict[str, Any]]) -> None:
        """Upsert a batch of issues into SQLite."""
        with sqlite3.connect(self._db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO issues (key, data, excluded) VALUES (?, ?, ?)",
                [
                    (
                        issue.get("key", ""),
                        json.dumps(issue),
                        int(JiraClient.is_excluded(issue)),
                    )
                    for issue in issues
                ],
            )
        logger.info("Cache: upserted %d issues to SQLite", len(issues))

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> None:
        """Block until the cache has been populated at least once."""
        if self._initialized:
            return
        # If nobody started init yet, do it now (first request triggers it)
        if not self._init_event.is_set():
            # Try loading from SQLite first
            if self._load_from_db():
                self._init_event.set()
                return
            self._full_fetch()
        else:
            # Another thread is doing init — wait for it
            self._init_event.wait()

    def _full_fetch(self) -> None:
        """Fetch ALL issues from Jira and populate both dicts."""
        self._init_event.clear()
        self._refreshing = True
        try:
            logger.info("Cache: starting full fetch …")
            all_issues = self._client.search_all(_ALL_JQL)
            logger.info("Cache: fetched %d total issues", len(all_issues))

            new_all: dict[str, dict[str, Any]] = {}
            new_filtered: dict[str, dict[str, Any]] = {}
            for issue in all_issues:
                key = issue.get("key", "")
                new_all[key] = issue
                if not JiraClient.is_excluded(issue):
                    new_filtered[key] = issue

            with self._lock:
                self._all_issues = new_all
                self._issues = new_filtered
                self._initialized = True
                self._last_refresh = datetime.now(timezone.utc)

            logger.info(
                "Cache: populated %d total, %d filtered",
                len(new_all),
                len(new_filtered),
            )
            self._save_all_to_db()
        finally:
            self._refreshing = False
            self._init_event.set()

    # ------------------------------------------------------------------
    # Incremental refresh
    # ------------------------------------------------------------------

    def _incremental_refresh(self) -> list[str]:
        """Fetch only issues updated in the last refresh interval and merge.

        Returns a list of issue keys that are genuinely new (not previously
        seen in the cache).
        """
        self._refreshing = True
        new_keys: list[str] = []
        try:
            jql = f'project = {JIRA_PROJECT} AND updated >= "-10m" ORDER BY key ASC'
            logger.info("Cache: incremental refresh with JQL: %s", jql)
            updated_issues = self._client.search_all(jql)
            logger.info("Cache: incremental fetched %d issues", len(updated_issues))

            with self._lock:
                for issue in updated_issues:
                    key = issue.get("key", "")
                    if key not in self._all_issues:
                        new_keys.append(key)
                    self._all_issues[key] = issue
                    if JiraClient.is_excluded(issue):
                        self._issues.pop(key, None)
                    else:
                        self._issues[key] = issue
                self._last_refresh = datetime.now(timezone.utc)

            logger.info(
                "Cache: after merge — %d total, %d filtered (%d new)",
                len(self._all_issues),
                len(self._issues),
                len(new_keys),
            )
            if updated_issues:
                self._upsert_to_db(updated_issues)
        finally:
            self._refreshing = False
        return new_keys

    # ------------------------------------------------------------------
    # Manual refresh
    # ------------------------------------------------------------------

    def trigger_refresh(self) -> None:
        """Trigger a full re-fetch (called from the /api/cache/refresh endpoint)."""
        self._full_fetch()

    def trigger_incremental_refresh(self) -> None:
        """Trigger an incremental refresh (last 10 min of changes)."""
        self._incremental_refresh()

    # ------------------------------------------------------------------
    # Auto-triage
    # ------------------------------------------------------------------

    def _load_auto_triage_seen(self) -> set[str]:
        """Lazy-load the set of already-auto-triaged keys from the DB."""
        if self._auto_triage_seen is None:
            from triage_store import store
            self._auto_triage_seen = store.get_auto_triaged_keys()
            logger.info("Auto-triage: loaded %d previously processed keys", len(self._auto_triage_seen))
        return self._auto_triage_seen

    async def _auto_triage_new_tickets(self, new_keys: list[str]) -> None:
        """Run AI triage on genuinely new tickets and apply high-confidence priority changes."""
        from config import AUTO_TRIAGE_MODEL
        from ai_client import analyze_ticket, get_available_models, validate_suggestions
        from triage_store import store
        from jira_client import JiraClient

        # Check model is available
        available_ids = {m.id for m in get_available_models()}
        if AUTO_TRIAGE_MODEL not in available_ids:
            logger.warning("Auto-triage: model %s not available (missing API key?), skipping", AUTO_TRIAGE_MODEL)
            return

        seen = self._load_auto_triage_seen()
        keys_to_process = [k for k in new_keys if k not in seen]
        if not keys_to_process:
            return

        logger.info("Auto-triage: processing %d new tickets", len(keys_to_process))
        client = JiraClient()
        loop = asyncio.get_event_loop()

        for key in keys_to_process:
            try:
                with self._lock:
                    issue = self._all_issues.get(key)
                if not issue:
                    continue

                result = await loop.run_in_executor(
                    None, analyze_ticket, issue, AUTO_TRIAGE_MODEL
                )
                result.suggestions = validate_suggestions(key, result.suggestions)
                store.save(result)

                # Auto-apply priority changes with confidence >= 0.7
                for s in result.suggestions:
                    if s.field == "priority" and s.confidence >= 0.7:
                        await loop.run_in_executor(
                            None, client.update_priority, key, s.suggested_value
                        )
                        logger.info(
                            "Auto-triage: %s priority %s → %s (conf=%.2f)",
                            key, s.current_value, s.suggested_value, s.confidence,
                        )

                store.mark_auto_triaged(key)
                seen.add(key)
                logger.info("Auto-triage: %s completed (%d suggestions)", key, len(result.suggestions))

            except Exception:
                logger.exception("Auto-triage: failed for %s", key)

    # ------------------------------------------------------------------
    # Background task lifecycle
    # ------------------------------------------------------------------

    async def start_background_refresh(self) -> None:
        """Start the periodic background refresh loop."""
        self._bg_task = asyncio.create_task(self._refresh_loop())

    async def stop_background_refresh(self) -> None:
        """Cancel the background refresh loop."""
        if self._bg_task:
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
            self._bg_task = None

    async def _refresh_loop(self) -> None:
        """Run incremental refresh every _REFRESH_INTERVAL seconds."""
        while True:
            await asyncio.sleep(_REFRESH_INTERVAL)
            try:
                new_keys = await asyncio.get_event_loop().run_in_executor(
                    None, self._incremental_refresh
                )
                if new_keys:
                    await self._auto_triage_new_tickets(new_keys)
            except Exception:
                logger.exception("Cache: incremental refresh failed")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
cache = IssueCache()
