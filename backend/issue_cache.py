"""Issue cache with SQLite persistence and incremental background refresh."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from config import DATA_DIR, JIRA_PROJECT
from ai_background_worker import background_ai_worker
from jira_client import JiraClient
from request_type import extract_request_type_name_from_fields, has_request_type
from site_context import SiteScope, filter_issues_for_scope
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)


class _RefreshCancelled(Exception):
    """Raised when a refresh is cancelled via cancel_refresh()."""

# JQL filters
_ALL_JQL = f"project = {JIRA_PROJECT} ORDER BY key ASC"
_FILTERED_JQL = (
    f'project = {JIRA_PROJECT} AND (labels is EMPTY OR labels not in ("oasisdev"))'
)

# Refresh interval in seconds
_REFRESH_INTERVAL = 15
_INCREMENTAL_LOOKBACK_MINUTES = 2
_INCREMENTAL_OVERLAP_MINUTES = 2
_KEY_REFRESH_BATCH_SIZE = 50
_AUTO_TRIAGE_ONE_TIME_BACKFILL_METADATA_KEY = (
    "auto_triage_backfill_older_than_24h_processed_v1"
)
_AUTO_TRIAGE_ONE_TIME_BACKFILL_HOURS = 24


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
        self._auto_triage_running = False
        self._auto_triage_current_key: str | None = None
        self._auto_triage_last_started: datetime | None = None
        self._auto_triage_last_finished: datetime | None = None
        self._auto_triage_backfill_checked = False

        # Refresh progress tracking
        self._refresh_progress: dict[str, Any] = {}
        self._cancel_refresh = False

        # SQLite persistence
        self._db_path = db_path or os.path.join(DATA_DIR, "issues_cache.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

        # Set to True once start_background_refresh() is called.
        # _ensure_initialized() uses this to decide whether to wait for the
        # background task or load synchronously (test / standalone usage).
        self._start_background_called = False

    def _conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path, row_factory=None)

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

    @property
    def warming(self) -> bool:
        return self._start_background_called and not self._initialized

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
        with self._lock:
            result: dict[str, Any] = {
                "initialized": self._initialized,
                "refreshing": self._refreshing,
                "issue_count": len(self._all_issues),
                "filtered_count": len(self._issues),
                "last_refresh": (
                    self._last_refresh.isoformat() if self._last_refresh else None
                ),
            }
            if self._refresh_progress:
                result["refresh_progress"] = dict(self._refresh_progress)
            return result

    def auto_triage_status(self, scope: SiteScope | None = None) -> dict[str, Any]:
        self.ensure_auto_triage_processed_backfill()
        seen = self._load_auto_triage_seen()
        with self._lock:
            issues = list(self._all_issues.values())
            running = self._auto_triage_running
            current_key = self._auto_triage_current_key
            last_started = self._auto_triage_last_started.isoformat() if self._auto_triage_last_started else None
            last_finished = self._auto_triage_last_finished.isoformat() if self._auto_triage_last_finished else None

        if scope in ("primary", "oasisdev"):
            issues = filter_issues_for_scope(issues, scope)
        elif scope == "azure":
            issues = []

        pending_keys = [
            issue.get("key", "")
            for issue in issues
            if issue.get("key") and issue.get("key") not in seen
        ]

        return {
            "running": running,
            "current_key": current_key,
            "pending_count": len(pending_keys),
            "pending_keys": pending_keys[:25],
            "last_started": last_started,
            "last_finished": last_finished,
        }

    def update_cached_field(self, key: str, field: str, value: str | dict[str, str] | None) -> None:
        """Update a field in the cached issue data (in-memory + SQLite).

        Supports: summary, description, priority, request_type, status, assignee, reporter, updated.
        """
        from datetime import datetime, timezone
        with self._lock:
            for store_dict in (self._all_issues, self._issues):
                issue = store_dict.get(key)
                if not issue:
                    continue
                fields = issue.setdefault("fields", {})
                if field == "summary":
                    fields["summary"] = value
                elif field == "description":
                    fields["description"] = value
                elif field == "priority":
                    fields["priority"] = {"name": value}
                elif field == "request_type":
                    fields["customfield_10010"] = {
                        "requestType": {"name": value}
                    }
                elif field == "status":
                    status_obj = fields.get("status") or {}
                    status_obj["name"] = value
                    fields["status"] = status_obj
                elif field == "assignee":
                    if isinstance(value, dict):
                        display_name = value.get("displayName", "")
                        account_id = value.get("accountId", "")
                    else:
                        display_name = value or ""
                        account_id = ""
                    if display_name or account_id:
                        assignee_obj = fields.get("assignee") or {}
                        if isinstance(assignee_obj, dict):
                            assignee_obj["displayName"] = display_name
                            if account_id:
                                assignee_obj["accountId"] = account_id
                        else:
                            assignee_obj = {"displayName": display_name}
                            if account_id:
                                assignee_obj["accountId"] = account_id
                        fields["assignee"] = assignee_obj
                    else:
                        fields["assignee"] = None
                elif field == "reporter":
                    if isinstance(value, dict):
                        display_name = value.get("displayName", "")
                        account_id = value.get("accountId", "")
                    else:
                        display_name = value or ""
                        account_id = ""
                    reporter_obj = fields.get("reporter") or {}
                    if isinstance(reporter_obj, dict):
                        reporter_obj["displayName"] = display_name
                        if account_id:
                            reporter_obj["accountId"] = account_id
                    else:
                        reporter_obj = {"displayName": display_name}
                        if account_id:
                            reporter_obj["accountId"] = account_id
                    fields["reporter"] = reporter_obj
                # Always bump updated timestamp
                fields["updated"] = datetime.now(timezone.utc).isoformat()
        # Persist the updated issue to SQLite
        with self._lock:
            issue = self._all_issues.get(key)
        if issue:
            self._upsert_to_db([issue])

    def update_cached_labels(self, key: str, labels: list[str]) -> None:
        """Update the labels list for a cached issue and re-evaluate its scope.

        When the oasisdev label is removed, the issue moves from the oasisdev
        scope into the primary scope (_issues dict).
        """
        from metrics import is_excluded as _is_excluded
        with self._lock:
            issue = self._all_issues.get(key)
            if issue:
                issue.setdefault("fields", {})["labels"] = labels
                issue["fields"]["updated"] = datetime.now(timezone.utc).isoformat()
                # Re-evaluate scope membership based on new labels
                if _is_excluded(issue):
                    self._issues.pop(key, None)
                else:
                    self._issues[key] = issue
        with self._lock:
            issue = self._all_issues.get(key)
        if issue:
            self._upsert_to_db([issue])

    def upsert_issue(self, issue: dict[str, Any]) -> None:
        """Merge one fresh Jira issue into memory and SQLite.

        This is used for live Jira reads outside the background refresh loop,
        such as opening the ticket drawer. It intentionally does not advance
        ``last_refresh`` because it only updates one issue, not the dataset.
        """
        key = issue.get("key", "")
        if not key:
            return
        if not JiraClient.is_tracked_issue(issue):
            self.evict_issue(key)
            logger.info(
                "Cache: ignored non-tracked issue %s (%s)",
                key,
                JiraClient.tracked_project_key(issue) or "unknown-project",
            )
            return

        fields = issue.setdefault("fields", {})
        if not has_request_type(fields):
            with self._lock:
                cached = self._all_issues.get(key, {})
            cached_fields = cached.get("fields", {})
            cached_name = extract_request_type_name_from_fields(cached_fields)
            if cached_name:
                fields["customfield_10010"] = (
                    cached_fields.get("customfield_10010")
                    or {"requestType": {"name": cached_name}}
                )

        with self._lock:
            self._all_issues[key] = issue
            if JiraClient.is_excluded(issue):
                self._issues.pop(key, None)
            else:
                self._issues[key] = issue

        self._upsert_to_db([issue])

    def evict_issue(self, key: str) -> bool:
        """Remove a single issue from memory and SQLite.

        Used when a ticket is moved to a different Jira board and no longer
        appears in this project's JQL results, leaving a stale cache entry.
        Returns True if the issue was present and removed, False if not found.
        """
        key = key.strip().upper()
        with self._lock:
            in_all = key in self._all_issues
            self._all_issues.pop(key, None)
            self._issues.pop(key, None)
        with self._conn() as conn:
            conn.execute("DELETE FROM issues WHERE key = ?", (key,))
        if in_all:
            logger.info("Cache: evicted issue %s", key)
        return in_all

    def refresh_issue_keys(self, keys: list[str]) -> list[dict[str, Any]]:
        """Re-fetch a specific set of Jira issues and persist the fresh results.

        This is used by targeted live refresh flows, such as refreshing the
        tickets currently displayed in the UI. It intentionally does not
        advance ``last_refresh`` because it only updates part of the dataset.
        """
        # Use a fresh Jira client for targeted refreshes so these requests do
        # not share a requests.Session with the background refresh thread.
        client = JiraClient() if isinstance(self._client, JiraClient) else self._client

        normalized_keys: list[str] = []
        seen: set[str] = set()
        for raw_key in keys:
            key = str(raw_key or "").strip().upper()
            if not key or key in seen:
                continue
            normalized_keys.append(key)
            seen.add(key)

        if not normalized_keys:
            return []

        with self._lock:
            existing_cache = dict(self._all_issues)

        refreshed_by_key: dict[str, dict[str, Any]] = {}
        for i in range(0, len(normalized_keys), _KEY_REFRESH_BATCH_SIZE):
            batch = normalized_keys[i:i + _KEY_REFRESH_BATCH_SIZE]
            jql = f"key in ({','.join(batch)}) ORDER BY key ASC"
            refreshed_batch = client.search_all(jql)
            if refreshed_batch:
                client.enrich_request_types(refreshed_batch, existing_cache=existing_cache)
                self._sync_requestors_best_effort(refreshed_batch, open_only=False)
                self._sync_followup_authority_best_effort(refreshed_batch, force=True)
            for issue in refreshed_batch:
                key = issue.get("key", "")
                if not key:
                    continue
                refreshed_by_key[key] = issue
                existing_cache[key] = issue

        refreshed_issues = [
            refreshed_by_key[key]
            for key in normalized_keys
            if key in refreshed_by_key
        ]

        # Keys not returned by Jira have been moved or deleted — evict them.
        missing_keys = [k for k in normalized_keys if k not in refreshed_by_key]
        if missing_keys:
            logger.info(
                "Cache: evicting %d issue(s) not found in Jira during visible refresh: %s",
                len(missing_keys),
                ", ".join(missing_keys),
            )
            with self._lock:
                for key in missing_keys:
                    self._all_issues.pop(key, None)
                    self._issues.pop(key, None)
            with self._conn() as conn:
                conn.executemany("DELETE FROM issues WHERE key = ?", [(k,) for k in missing_keys])

        if not refreshed_issues:
            return []

        with self._lock:
            for issue in refreshed_issues:
                key = issue.get("key", "")
                self._all_issues[key] = issue
                if JiraClient.is_excluded(issue):
                    self._issues.pop(key, None)
                else:
                    self._issues[key] = issue

        self._upsert_to_db(refreshed_issues)
        logger.info(
            "Cache: refreshed %d/%d specific issues from Jira",
            len(refreshed_issues),
            len(normalized_keys),
        )
        return refreshed_issues

    # ------------------------------------------------------------------
    # SQLite persistence
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the SQLite tables if they don't exist."""
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS issues "
                "(key TEXT PRIMARY KEY, data TEXT, excluded INTEGER)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def _persist_last_refresh(self) -> None:
        """Write _last_refresh timestamp to the metadata table."""
        if not self._last_refresh:
            return
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_refresh', ?)",
                (self._last_refresh.isoformat(),),
            )

    def _restore_last_refresh(self) -> None:
        """Read the persisted last_refresh timestamp from the metadata table."""
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT value FROM metadata WHERE key = 'last_refresh'"
                ).fetchone()
            if row:
                self._last_refresh = datetime.fromisoformat(row[0])
        except Exception:
            pass  # Non-fatal — will fall back to full startup lookback

    def _load_from_db(self) -> bool:
        """Populate in-memory dicts from SQLite. Returns True if rows existed."""
        with self._conn() as conn:
            rows = conn.execute("SELECT key, data, excluded FROM issues").fetchall()
        if not rows:
            return False
        new_all: dict[str, dict[str, Any]] = {}
        new_filtered: dict[str, dict[str, Any]] = {}
        dropped_keys: list[str] = []
        for key, data, excluded in rows:
            issue = json.loads(data)
            if not JiraClient.is_tracked_issue(issue):
                dropped_keys.append(key)
                continue
            new_all[key] = issue
            if not excluded:
                new_filtered[key] = issue
        with self._lock:
            self._all_issues = new_all
            self._issues = new_filtered
            self._initialized = True
        if dropped_keys:
            with self._conn() as conn:
                conn.executemany("DELETE FROM issues WHERE key = ?", [(key,) for key in dropped_keys])
            logger.info(
                "Cache: dropped %d non-tracked issues from SQLite restore: %s",
                len(dropped_keys),
                ", ".join(sorted(dropped_keys)[:10]),
            )
        self._restore_last_refresh()
        logger.info(
            "Cache: restored %d total, %d filtered from SQLite (last Jira sync: %s)",
            len(new_all),
            len(new_filtered),
            self._last_refresh.isoformat() if self._last_refresh else "unknown",
        )
        self.ensure_auto_triage_processed_backfill()
        return True

    def _save_all_to_db(self) -> None:
        """Replace entire DB contents with current in-memory state."""
        with self._conn() as conn:
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
        with self._conn() as conn:
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

    def _prune_non_tracked_issues(self) -> list[str]:
        """Drop cached issues that no longer belong to a tracked Jira board/project."""
        with self._lock:
            dropped_keys = [
                key
                for key, issue in self._all_issues.items()
                if not JiraClient.is_tracked_issue(issue)
            ]
            for key in dropped_keys:
                self._all_issues.pop(key, None)
                self._issues.pop(key, None)
        if dropped_keys:
            with self._conn() as conn:
                conn.executemany("DELETE FROM issues WHERE key = ?", [(key,) for key in dropped_keys])
            logger.info(
                "Cache: pruned %d non-tracked issues: %s",
                len(dropped_keys),
                ", ".join(sorted(dropped_keys)[:10]),
            )
        return dropped_keys

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> None:
        """Block until the cache has been populated at least once.

        In production the background task (started by start_background_refresh)
        loads SQLite and sets _init_event; we just wait on it.  In tests /
        standalone usage the flag is False so we fall back to a direct load.
        """
        if self._initialized:
            return
        if self._start_background_called:
            # Background task is running — wait for it to finish loading.
            self._init_event.wait(timeout=120)
            return
        # Fallback (tests, standalone): load synchronously.
        if not self._init_event.is_set():
            if self._load_from_db():
                self._init_event.set()
                return
            logger.info("Cache: cold start — fetching all issues from Jira (first request will be slow)")
            self._full_fetch()
        else:
            self._init_event.wait(timeout=120)

    async def wait_until_initialized(self, timeout: float | None = None) -> bool:
        """Wait asynchronously for the cache to finish its initial load."""
        if self._initialized:
            return True
        if not self._start_background_called:
            return False
        loop = asyncio.get_running_loop()
        ready = await loop.run_in_executor(None, self._init_event.wait, timeout)
        return bool(ready or self._initialized)

    def _progress_callback(self, phase: str, current: int, total: int) -> None:
        """Update refresh progress state for the status endpoint."""
        if self._cancel_refresh:
            raise _RefreshCancelled()
        self._refresh_progress = {
            "phase": phase,
            "current": current,
            "total": total,
        }

    def cancel_refresh(self) -> bool:
        """Request cancellation of the current refresh. Returns True if a refresh was running."""
        if not self._refreshing:
            return False
        self._cancel_refresh = True
        return True

    def _full_fetch(self) -> None:
        """Fetch ALL issues from Jira and populate both dicts."""
        self._init_event.clear()
        self._refreshing = True
        self._cancel_refresh = False
        self._refresh_progress = {"phase": "starting", "current": 0, "total": len(self._all_issues) or 0}
        try:
            logger.info("Cache: starting full fetch …")
            all_issues = self._client.search_all(_ALL_JQL, progress_callback=self._progress_callback)
            all_issues = [issue for issue in all_issues if JiraClient.is_tracked_issue(issue)]
            logger.info("Cache: fetched %d total issues", len(all_issues))

            # Carry forward existing request type data (free, no API calls)
            if self._all_issues:
                for issue in all_issues:
                    key = issue.get("key", "")
                    cached = self._all_issues.get(key, {})
                    cached_name = extract_request_type_name_from_fields(cached.get("fields", {}))
                    if cached_name:
                        issue.setdefault("fields", {})["customfield_10010"] = {
                            "requestType": {"name": cached_name}
                        }

            self._sync_requestors_best_effort(all_issues, open_only=True)
            self._sync_followup_authority_best_effort(all_issues, recent_days=35)

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
            self._persist_last_refresh()

            logger.info(
                "Cache: populated %d total, %d filtered",
                len(new_all),
                len(new_filtered),
            )
            self.ensure_auto_triage_processed_backfill()
            self._refresh_progress = {"phase": "saving", "current": 0, "total": 0}
            self._save_all_to_db()
        except _RefreshCancelled:
            logger.info("Cache: full refresh cancelled by user")
        finally:
            self._refreshing = False
            self._cancel_refresh = False
            self._refresh_progress = {}
            self._init_event.set()

    # ------------------------------------------------------------------
    # Incremental refresh
    # ------------------------------------------------------------------

    def _get_incremental_lookback_minutes(self, minimum_minutes: int = _INCREMENTAL_LOOKBACK_MINUTES) -> int:
        """Return a safe incremental lookback based on the last successful sync.

        We keep a small overlap so slow loops, brief outages, or Jira indexing lag
        do not create a gap that misses updates.
        """
        if not self._last_refresh:
            return minimum_minutes
        elapsed_minutes = math.ceil(
            max(0.0, (datetime.now(timezone.utc) - self._last_refresh).total_seconds()) / 60
        )
        return max(minimum_minutes, elapsed_minutes + _INCREMENTAL_OVERLAP_MINUTES)

    def _incremental_refresh(self, lookback_minutes: int | None = None) -> list[str]:
        """Fetch only issues updated in the last lookback_minutes and merge.

        Updates both primary and oasisdev scopes from the single shared Jira source.
        Returns a list of issue keys that need auto-triage (not yet processed).
        """
        effective_lookback_minutes = (
            lookback_minutes
            if lookback_minutes is not None
            else self._get_incremental_lookback_minutes()
        )
        self._refreshing = True
        self._cancel_refresh = False
        self._refresh_progress = {"phase": "starting", "current": 0, "total": 0}
        try:
            jql = (
                f'project = {JIRA_PROJECT} AND updated >= "-{effective_lookback_minutes}m" '
                "ORDER BY key ASC"
            )
            logger.info("Cache: incremental refresh with JQL: %s", jql)
            updated_issues = self._client.search_all(jql, progress_callback=self._progress_callback)
            updated_issues = [issue for issue in updated_issues if JiraClient.is_tracked_issue(issue)]
            logger.info("Cache: incremental fetched %d issues", len(updated_issues))

            # Enrich request types for the updated batch
            if updated_issues:
                self._client.enrich_request_types(updated_issues, existing_cache=self._all_issues)
                self._sync_requestors_best_effort(updated_issues, open_only=False)
                self._sync_followup_authority_best_effort(updated_issues, recent_days=35)

            with self._lock:
                for issue in updated_issues:
                    key = issue.get("key", "")
                    self._all_issues[key] = issue
                    if JiraClient.is_excluded(issue):
                        self._issues.pop(key, None)
                    else:
                        self._issues[key] = issue
                self._last_refresh = datetime.now(timezone.utc)
            self._prune_non_tracked_issues()
            self._persist_last_refresh()

            self.ensure_auto_triage_processed_backfill()

            # Return ALL keys not yet auto-triaged (not just updated ones)
            seen = self._load_auto_triage_seen()
            untriaged_keys = [
                key for key, issue in self._issues.items()
                if key not in seen
            ]

            logger.info(
                "Cache: after merge — %d total, %d filtered (%d untriaged)",
                len(self._all_issues),
                len(self._issues),
                len(untriaged_keys),
            )
            if updated_issues:
                self._upsert_to_db(updated_issues)
        except _RefreshCancelled:
            logger.info("Cache: incremental refresh cancelled by user")
            return []
        finally:
            self._refreshing = False
            self._cancel_refresh = False
            self._refresh_progress = {}
        return untriaged_keys

    # ------------------------------------------------------------------
    # Manual refresh
    # ------------------------------------------------------------------

    def trigger_refresh(self) -> None:
        """Trigger a full re-fetch (called from the /api/cache/refresh endpoint)."""
        self._full_fetch()

    def trigger_incremental_refresh(self) -> None:
        """Trigger an incremental refresh using the last successful sync watermark."""
        self._incremental_refresh()

    @staticmethod
    def _sync_requestors_best_effort(
        issues: list[dict[str, Any]],
        *,
        open_only: bool = False,
    ) -> None:
        if not issues:
            return
        try:
            from requestor_sync_service import requestor_sync_service

            requestor_sync_service.reconcile_issues(issues, open_only=open_only)
        except Exception:
            logger.exception("Requestor sync pass failed during Jira cache refresh")

    @staticmethod
    def _sync_followup_authority_best_effort(
        issues: list[dict[str, Any]],
        *,
        force: bool = False,
        recent_days: int = 35,
    ) -> None:
        if not issues:
            return
        try:
            from followup_sync_service import followup_sync_service

            followup_sync_service.reconcile_issues(
                issues,
                force=force,
                recent_days=recent_days,
            )
        except Exception:
            logger.exception("Follow-up authority sync failed during Jira cache refresh")

    def _backfill_recent_followup_authority_from_cache(self, *, recent_days: int = 35) -> int:
        """Populate local authoritative follow-up fields for recent/open cached issues.

        Warm startups can restore a fresh SQLite cache and skip the initial
        incremental Jira refresh, which means recent tickets may not yet have
        the local public-comment follow-up fields. This one-time bootstrap pass
        closes that gap without waiting for those tickets to change again.
        """
        with self._lock:
            candidates = list(self._all_issues.values())
        if not candidates:
            return 0

        self._sync_followup_authority_best_effort(candidates, recent_days=recent_days)

        changed_issues = [
            issue
            for issue in candidates
            if str((issue.get("fields") or {}).get("_movedocs_followup_status") or "").strip()
            in {"Running", "Met", "BREACHED"}
        ]
        if changed_issues:
            self._upsert_to_db(changed_issues)
            logger.info(
                "Cache: bootstrapped local follow-up authority for %d cached issues",
                len(changed_issues),
            )
        return len(changed_issues)

    def enrich_missing_request_types(self) -> int:
        """Enrich all cached issues that are missing request type data.

        Calls the JSM per-ticket API. Returns the number of newly enriched issues.
        This is intended for one-time backfill or manual trigger.
        """
        issues_to_enrich = []
        with self._lock:
            for key, issue in self._all_issues.items():
                if not has_request_type(issue.get("fields", {})):
                    issues_to_enrich.append(issue)

        if not issues_to_enrich:
            logger.info("All cached issues already have request type data")
            return 0

        logger.info("Enriching %d issues missing request type data", len(issues_to_enrich))
        self._client.enrich_request_types(issues_to_enrich)

        # Count how many were actually enriched
        enriched = 0
        for issue in issues_to_enrich:
            if has_request_type(issue.get("fields", {})):
                enriched += 1

        # Persist to DB
        if enriched:
            self._save_all_to_db()
            logger.info("Persisted %d enriched request types to DB", enriched)

        return enriched

    # ------------------------------------------------------------------
    # Rule-based priority enforcement
    # ------------------------------------------------------------------

    # Request types that are always forced to at least High priority
    _ALWAYS_HIGH_REQUEST_TYPES: frozenset[str] = frozenset({"Security Alert"})
    # Priorities considered >= High (do not downgrade these)
    _HIGH_OR_ABOVE: frozenset[str] = frozenset({"High", "Highest"})

    def _apply_priority_rules(self, key: str, issue: dict[str, Any]) -> bool:
        """Enforce rule-based priority overrides. Returns True if a change was made.

        Current rules:
          - Security Alert request type → force priority to High (unless already High/Highest).
        """
        from triage_store import store
        from jira_client import JiraClient

        fields = issue.get("fields", {})
        request_type = extract_request_type_name_from_fields(fields)
        if request_type not in self._ALWAYS_HIGH_REQUEST_TYPES:
            return False

        current_priority = (fields.get("priority") or {}).get("name", "")
        if current_priority in self._HIGH_OR_ABOVE:
            return False

        target = "High"
        try:
            JiraClient().update_priority(key, target)
            store.log_change(key, "priority", current_priority, target, 1.0, "rule:security-alert")
            self.update_cached_field(key, "priority", target)
            logger.info(
                "Priority rule: %s (%s) %s → %s",
                key, request_type, current_priority or "(none)", target,
            )
            return True
        except Exception:
            logger.exception("Priority rule: failed to update %s priority", key)
            return False

    # ------------------------------------------------------------------
    # Auto-triage
    # ------------------------------------------------------------------

    def reset_auto_triage_seen(self) -> None:
        """Clear the in-memory set of auto-triaged keys so all tickets can be re-processed."""
        self._auto_triage_seen = None

    def _load_auto_triage_seen(self) -> set[str]:
        """Lazy-load the set of already-auto-triaged keys from the DB."""
        if self._auto_triage_seen is None:
            from triage_store import store
            self._auto_triage_seen = store.get_auto_triaged_keys()
            logger.info("Auto-triage: loaded %d previously processed keys", len(self._auto_triage_seen))
        return self._auto_triage_seen

    @staticmethod
    def _parse_issue_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        if (
            len(normalized) >= 5
            and normalized[-5] in {"+", "-"}
            and normalized[-3] != ":"
            and normalized[-4:].isdigit()
        ):
            normalized = f"{normalized[:-2]}:{normalized[-2:]}"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def ensure_auto_triage_processed_backfill(self) -> int:
        """Run the one-time legacy processed backfill for already-old tickets.

        This is intentionally a one-time migration: tickets that were already
        older than 24 hours when this rule shipped are marked processed once so
        they do not enter the auto-triage queue. Newer tickets keep the normal
        "process once, then stay processed" lifecycle.
        """
        if self._auto_triage_backfill_checked:
            return 0

        from triage_store import store

        if store.get_metadata(_AUTO_TRIAGE_ONE_TIME_BACKFILL_METADATA_KEY) == "1":
            self._auto_triage_backfill_checked = True
            return 0

        with self._lock:
            issues = list(self._all_issues.values())

        if not issues:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=_AUTO_TRIAGE_ONE_TIME_BACKFILL_HOURS
        )
        keys_to_mark = [
            key
            for issue in issues
            if (key := str(issue.get("key") or "").strip())
            and (
                (created_at := self._parse_issue_datetime(issue.get("fields", {}).get("created")))
                is not None
            )
            and created_at <= cutoff
        ]

        inserted = store.mark_auto_triaged_if_missing(keys_to_mark)
        seen = self._load_auto_triage_seen()
        seen.update(keys_to_mark)
        store.set_metadata(_AUTO_TRIAGE_ONE_TIME_BACKFILL_METADATA_KEY, "1")
        self._auto_triage_backfill_checked = True

        logger.info(
            "Auto-triage: one-time backfill marked %d existing tickets older than %dh as processed (%d newly inserted)",
            len(keys_to_mark),
            _AUTO_TRIAGE_ONE_TIME_BACKFILL_HOURS,
            inserted,
        )
        return inserted

    async def _auto_triage_new_tickets(self, new_keys: list[str], progress: dict | None = None) -> None:
        """Run AI triage on genuinely new tickets and apply high-confidence priority changes."""
        from config import AUTO_TRIAGE_MODEL, OLLAMA_MODEL
        from ai_client import (
            analyze_ticket,
            get_available_models,
            normalize_triage_priority_value,
            select_available_ollama_model,
            validate_suggestions,
        )
        from triage_store import store
        from jira_client import JiraClient

        loop = asyncio.get_running_loop()

        def _resolve_model_id() -> str | None:
            return select_available_ollama_model(
                get_available_models(),
                preferred_model_id=AUTO_TRIAGE_MODEL,
                fallback_model_id=OLLAMA_MODEL,
            )

        model_id = await loop.run_in_executor(None, _resolve_model_id)
        if not model_id:
            logger.warning(
                "Auto-triage: neither preferred model %s nor fallback model %s is available from the active AI provider, skipping",
                AUTO_TRIAGE_MODEL,
                OLLAMA_MODEL,
            )
            return

        self.ensure_auto_triage_processed_backfill()
        seen = self._load_auto_triage_seen()
        keys_to_process = [k for k in new_keys if k not in seen]
        if not keys_to_process:
            return

        logger.info("Auto-triage: processing %d new tickets", len(keys_to_process))
        client = JiraClient()
        with self._lock:
            self._auto_triage_running = True
            self._auto_triage_current_key = None
            self._auto_triage_last_started = datetime.now(timezone.utc)

        try:
            for i, key in enumerate(keys_to_process):
                try:
                    with self._lock:
                        self._auto_triage_current_key = key
                    if progress is not None:
                        if progress.get("cancel"):
                            logger.info("Auto-triage: cancelled by user after %d/%d", i, len(keys_to_process))
                            break
                        progress.update(processed=i, current_key=key)

                    with self._lock:
                        issue = self._all_issues.get(key)
                    if not issue:
                        continue

                    # Apply deterministic rules first (e.g. Security Alert -> High)
                    await loop.run_in_executor(None, self._apply_priority_rules, key, issue)

                    async def _run_ai_triage() -> Any:
                        return await loop.run_in_executor(
                            None, analyze_ticket, issue, model_id
                        )

                    result = await background_ai_worker.run_item(
                        lane="auto_triage",
                        key=key,
                        work=_run_ai_triage,
                    )
                    result.suggestions = validate_suggestions(key, result.suggestions)
                    store.save(result)

                    # Auto-apply priority, request_type, and explicit reporter hints when safe.
                    priority_updated = False
                    request_type_updated = False
                    reporter_updated = False
                    applied_fields: list[str] = []
                    for s in result.suggestions:
                        try:
                            if s.field == "priority" and s.confidence >= 0.7:
                                target_priority = normalize_triage_priority_value(s.suggested_value)
                                await loop.run_in_executor(
                                    None, client.update_priority, key, target_priority
                                )
                                store.log_change(
                                    key, "priority", s.current_value, target_priority,
                                    s.confidence, model_id,
                                )
                                # Update local cache
                                self.update_cached_field(key, "priority", target_priority)
                                priority_updated = True
                                applied_fields.append("priority")
                                logger.info(
                                    "Auto-triage: %s priority %s -> %s (conf=%.2f)",
                                    key, s.current_value, target_priority, s.confidence,
                                )
                            elif s.field == "request_type" and s.confidence >= 0.9:
                                from ai_client import get_request_type_id
                                rt_id = get_request_type_id(s.suggested_value)
                                if rt_id:
                                    await loop.run_in_executor(
                                        None, client.set_request_type, key, rt_id
                                    )
                                    store.log_change(
                                        key, "request_type", s.current_value, s.suggested_value,
                                        s.confidence, model_id,
                                    )
                                    # Update local cache
                                    self.update_cached_field(key, "request_type", s.suggested_value)
                                    request_type_updated = True
                                    applied_fields.append("request_type")
                                    logger.info(
                                        "Auto-triage: %s request_type %s -> %s (conf=%.2f)",
                                        key, s.current_value, s.suggested_value, s.confidence,
                                    )
                            elif s.field == "reporter" and s.confidence >= 0.95:
                                account_id = client.find_user_account_id(s.suggested_value)
                                if account_id:
                                    await loop.run_in_executor(
                                        None, client.update_reporter, key, account_id
                                    )
                                    store.log_change(
                                        key, "reporter", s.current_value, s.suggested_value,
                                        s.confidence, model_id,
                                    )
                                    self.update_cached_field(
                                        key,
                                        "reporter",
                                        {"displayName": s.suggested_value, "accountId": account_id},
                                    )
                                    reporter_updated = True
                                    applied_fields.append("reporter")
                                    logger.info(
                                        "Auto-triage: %s reporter %s -> %s (conf=%.2f)",
                                        key, s.current_value, s.suggested_value, s.confidence,
                                    )
                        except Exception:
                            logger.exception("Auto-triage: failed to apply %s for %s", s.field, key)

                    # If AI reclassified the request type, re-run priority rules - the new type
                    # may now trigger a rule (e.g. newly classified as Security Alert -> High).
                    if request_type_updated and not priority_updated:
                        with self._lock:
                            updated_issue = self._all_issues.get(key, issue)
                        await loop.run_in_executor(
                            None, self._apply_priority_rules, key, updated_issue
                        )

                    # Remove priority and request_type suggestions entirely - auto-triage owns these fields.
                    # Applied ones are already written to Jira; unapplied ones (low confidence) should not
                    # clutter the manual Triage tab since auto-triage has already made a decision.
                    for field in ("priority", "request_type"):
                        store.remove_field(key, field)
                    if reporter_updated:
                        store.remove_field(key, "reporter")

                    store.mark_auto_triaged(key, priority_updated=priority_updated, request_type_updated=request_type_updated)
                    seen.add(key)
                    logger.info("Auto-triage: %s completed (%d suggestions)", key, len(result.suggestions))

                except Exception:
                    logger.exception("Auto-triage: failed for %s", key)

            if progress is not None:
                progress.update(processed=len(keys_to_process))
        finally:
            with self._lock:
                self._auto_triage_running = False
                self._auto_triage_current_key = None
                self._auto_triage_last_finished = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Background task lifecycle
    # ------------------------------------------------------------------

    async def start_background_refresh(self, *, load_only: bool = False) -> None:
        """Start the background init + periodic refresh loop.

        SQLite loading runs inside the task (via run_in_executor) so uvicorn
        can start accepting connections before the load completes.  The first
        request that needs data will block on _init_event, which is set as soon
        as _load_from_db() (or _full_fetch() for a cold start) finishes.
        """
        self._start_background_called = True
        target = self._init_only_loop if load_only else self._init_and_refresh_loop
        self._bg_task = asyncio.create_task(target())

    async def _init_only_loop(self) -> None:
        """Load shared cache state without starting the periodic refresh loop."""
        loop = asyncio.get_running_loop()
        loaded = await loop.run_in_executor(None, self._load_from_db)
        if loaded:
            self._init_event.set()
        else:
            logger.info("Cache: follower cold start — full Jira fetch required")
            await loop.run_in_executor(None, self._full_fetch)
        await loop.run_in_executor(None, self._backfill_recent_followup_authority_from_cache)

    async def _init_and_refresh_loop(self) -> None:
        """Load from SQLite then run the periodic refresh loop."""
        loop = asyncio.get_running_loop()
        loaded = await loop.run_in_executor(None, self._load_from_db)
        if loaded:
            self._init_event.set()
        else:
            # Cold start — no cached data; full Jira fetch required.
            # _full_fetch() sets _init_event in its finally block.
            logger.info("Cache: cold start — full Jira fetch required (this takes a while)")
            await loop.run_in_executor(None, self._full_fetch)
        await loop.run_in_executor(None, self._backfill_recent_followup_authority_from_cache)
        await self._refresh_loop()

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
        """Run incremental refresh every _REFRESH_INTERVAL seconds.

        Runs immediately on startup (to catch changes since last DB snapshot),
        then repeats on the interval.
        """
        first = True
        while True:
            if not first:
                await asyncio.sleep(_REFRESH_INTERVAL)
            if first:
                # Compute lookback from actual downtime so startup catches the gap
                # since the last successful sync without assuming the loop ran on time.
                if self._last_refresh:
                    downtime_minutes = (
                        datetime.now(timezone.utc) - self._last_refresh
                    ).total_seconds() / 60
                    if downtime_minutes < 5:
                        # Data is fresh — skip the startup Jira call entirely.
                        logger.info(
                            "Cache: data is %.1f min old — skipping startup incremental",
                            downtime_minutes,
                        )
                        first = False
                        continue
                    lookback = self._get_incremental_lookback_minutes()
                else:
                    lookback = 60 * 24  # No prior timestamp — cold start, use large lookback
                logger.info("Cache: startup lookback = %d min (downtime-based)", lookback)
            else:
                lookback = None
            first = False
            try:
                refresh_args: tuple[int, ...] = () if lookback is None else (lookback,)
                await asyncio.get_running_loop().run_in_executor(
                    None, self._incremental_refresh, *refresh_args
                )
                # Run alert checks after each refresh
                await self._run_alert_checks()
            except Exception:
                logger.exception("Cache: incremental refresh failed")

    async def _run_alert_checks(self) -> None:
        """Evaluate alert rules and send emails if triggered."""
        try:
            from alert_engine import run_alert_checks
            all_issues = self.get_all_issues()
            sent = 0
            sent += await run_alert_checks(filter_issues_for_scope(all_issues, "primary"), site_scope="primary")
            sent += await run_alert_checks(filter_issues_for_scope(all_issues, "oasisdev"), site_scope="oasisdev")
            if sent:
                logger.info("Alerts: sent %d email(s)", sent)
        except Exception:
            logger.exception("Alert check failed")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
cache = IssueCache()
