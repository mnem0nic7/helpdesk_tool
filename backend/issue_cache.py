"""Issue cache with SQLite persistence and incremental background refresh."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR, JIRA_PROJECT
from jira_client import JiraClient
from request_type import extract_request_type_name_from_fields, has_request_type
from site_context import filter_issues_for_scope

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

    def update_cached_field(self, key: str, field: str, value: str) -> None:
        """Update a field in the cached issue data (in-memory + SQLite).

        Supports: summary, description, priority, request_type, status, assignee, updated.
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
                    if value:
                        assignee_obj = fields.get("assignee") or {}
                        if isinstance(assignee_obj, dict):
                            assignee_obj["displayName"] = value
                        else:
                            assignee_obj = {"displayName": value}
                        fields["assignee"] = assignee_obj
                    else:
                        fields["assignee"] = None
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
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
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
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_refresh', ?)",
                (self._last_refresh.isoformat(),),
            )

    def _restore_last_refresh(self) -> None:
        """Read the persisted last_refresh timestamp from the metadata table."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT value FROM metadata WHERE key = 'last_refresh'"
                ).fetchone()
            if row:
                self._last_refresh = datetime.fromisoformat(row[0])
        except Exception:
            pass  # Non-fatal — will fall back to full startup lookback

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
        self._restore_last_refresh()
        logger.info(
            "Cache: restored %d total, %d filtered from SQLite (last Jira sync: %s)",
            len(new_all),
            len(new_filtered),
            self._last_refresh.isoformat() if self._last_refresh else "unknown",
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
            logger.info("Cache: incremental fetched %d issues", len(updated_issues))

            # Enrich request types for the updated batch
            if updated_issues:
                self._client.enrich_request_types(updated_issues, existing_cache=self._all_issues)

            with self._lock:
                for issue in updated_issues:
                    key = issue.get("key", "")
                    self._all_issues[key] = issue
                    if JiraClient.is_excluded(issue):
                        self._issues.pop(key, None)
                    else:
                        self._issues[key] = issue
                self._last_refresh = datetime.now(timezone.utc)
            self._persist_last_refresh()

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

    async def _auto_triage_new_tickets(self, new_keys: list[str], progress: dict | None = None) -> None:
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
        loop = asyncio.get_running_loop()

        for i, key in enumerate(keys_to_process):
            try:
                if progress is not None:
                    if progress.get("cancel"):
                        logger.info("Auto-triage: cancelled by user after %d/%d", i, len(keys_to_process))
                        break
                    progress.update(processed=i, current_key=key)

                with self._lock:
                    issue = self._all_issues.get(key)
                if not issue:
                    continue

                # Apply deterministic rules first (e.g. Security Alert → High)
                await loop.run_in_executor(None, self._apply_priority_rules, key, issue)

                result = await loop.run_in_executor(
                    None, analyze_ticket, issue, AUTO_TRIAGE_MODEL
                )
                result.suggestions = validate_suggestions(key, result.suggestions)
                store.save(result)

                # Auto-apply priority and request_type with confidence >= 0.7
                priority_updated = False
                request_type_updated = False
                applied_fields: list[str] = []
                for s in result.suggestions:
                    try:
                        if s.field == "priority" and s.confidence >= 0.7:
                            await loop.run_in_executor(
                                None, client.update_priority, key, s.suggested_value
                            )
                            store.log_change(
                                key, "priority", s.current_value, s.suggested_value,
                                s.confidence, AUTO_TRIAGE_MODEL,
                            )
                            # Update local cache
                            self.update_cached_field(key, "priority", s.suggested_value)
                            priority_updated = True
                            applied_fields.append("priority")
                            logger.info(
                                "Auto-triage: %s priority %s → %s (conf=%.2f)",
                                key, s.current_value, s.suggested_value, s.confidence,
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
                                    s.confidence, AUTO_TRIAGE_MODEL,
                                )
                                # Update local cache
                                self.update_cached_field(key, "request_type", s.suggested_value)
                                request_type_updated = True
                                applied_fields.append("request_type")
                                logger.info(
                                    "Auto-triage: %s request_type %s → %s (conf=%.2f)",
                                    key, s.current_value, s.suggested_value, s.confidence,
                                )
                    except Exception:
                        logger.exception("Auto-triage: failed to apply %s for %s", s.field, key)

                # If AI reclassified the request type, re-run priority rules — the new type
                # may now trigger a rule (e.g. newly classified as Security Alert → High).
                if request_type_updated and not priority_updated:
                    with self._lock:
                        updated_issue = self._all_issues.get(key, issue)
                    await loop.run_in_executor(
                        None, self._apply_priority_rules, key, updated_issue
                    )

                # Remove priority and request_type suggestions entirely — auto-triage owns these fields.
                # Applied ones are already written to Jira; unapplied ones (low confidence) should not
                # clutter the manual Triage tab since auto-triage has already made a decision.
                for field in ("priority", "request_type"):
                    store.remove_field(key, field)

                store.mark_auto_triaged(key, priority_updated=priority_updated, request_type_updated=request_type_updated)
                seen.add(key)
                logger.info("Auto-triage: %s completed (%d suggestions)", key, len(result.suggestions))

            except Exception:
                logger.exception("Auto-triage: failed for %s", key)

        if progress is not None:
            progress.update(processed=len(keys_to_process))

    # ------------------------------------------------------------------
    # Background task lifecycle
    # ------------------------------------------------------------------

    async def start_background_refresh(self) -> None:
        """Start the background init + periodic refresh loop.

        SQLite loading runs inside the task (via run_in_executor) so uvicorn
        can start accepting connections before the load completes.  The first
        request that needs data will block on _init_event, which is set as soon
        as _load_from_db() (or _full_fetch() for a cold start) finishes.
        """
        self._start_background_called = True
        self._bg_task = asyncio.create_task(self._init_and_refresh_loop())

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
                new_keys = await asyncio.get_running_loop().run_in_executor(
                    None, self._incremental_refresh, *refresh_args
                )
                if new_keys:
                    await self._auto_triage_new_tickets(new_keys)
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
