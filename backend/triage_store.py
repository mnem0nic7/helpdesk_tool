"""SQLite persistence for AI triage suggestions."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

from config import DATA_DIR
from models import TechnicianScore, TriageResult
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_AUTO_TRIAGE_ACTIVITY_BACKFILL_METADATA_KEY = "auto_triage_activity_backfill_v1"
_AUTO_TRIAGE_ACTIVITY_OUTCOMES = frozenset({"changed", "no_change", "failed", "backfill"})


class TriageStore:
    """Simple SQLite store for AI triage suggestions, keyed by issue key."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "triage_suggestions.db")
        self._use_postgres = postgres_enabled() and db_path is None
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()
        self.ensure_auto_triage_activity_backfill()

    def _sqlite_conn(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path, row_factory=None)

    def _placeholder(self) -> str:
        return "%s" if self._use_postgres else "?"

    def _conn(self):
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres(row_factory=None)
        return self._sqlite_conn()

    def _backfill_from_sqlite_if_needed(self) -> None:
        if not self._use_postgres or not os.path.exists(self._db_path):
            return
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM triage_suggestions").fetchone()
            if row and int(row[0]) > 0:
                return
        with self._sqlite_conn() as sqlite_conn:
            metadata_rows = sqlite_conn.execute("SELECT key, value FROM metadata").fetchall()
            suggestion_rows = sqlite_conn.execute(
                "SELECT key, data, model, created_at, updated_at FROM suggestions"
            ).fetchall()
            auto_triaged_rows = sqlite_conn.execute(
                "SELECT key, processed_at, priority_updated, request_type_updated FROM auto_triaged"
            ).fetchall()
            log_rows = sqlite_conn.execute(
                "SELECT key, field, old_value, new_value, confidence, model, source, approved_by, timestamp FROM auto_triage_log"
            ).fetchall()
            technician_rows = sqlite_conn.execute(
                "SELECT key, data, model, created_at, updated_at FROM technician_scores"
            ).fetchall()
            try:
                activity_rows = sqlite_conn.execute(
                    "SELECT key, outcome, source, processed_at, model, fields_changed, error, legacy_backfill "
                    "FROM auto_triage_activity"
                ).fetchall()
            except sqlite3.OperationalError:
                activity_rows = []
        with self._conn() as conn:
            if metadata_rows:
                conn.executemany(
                    """
                    INSERT INTO triage_metadata (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    metadata_rows,
                )
            if suggestion_rows:
                conn.executemany(
                    """
                    INSERT INTO triage_suggestions (key, data, model, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    suggestion_rows,
                )
            if auto_triaged_rows:
                conn.executemany(
                    """
                    INSERT INTO triage_auto_triaged (key, processed_at, priority_updated, request_type_updated)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    auto_triaged_rows,
                )
            if log_rows:
                conn.executemany(
                    """
                    INSERT INTO triage_auto_triage_log (
                        key, field, old_value, new_value, confidence, model, source, approved_by, timestamp
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    log_rows,
                )
            if technician_rows:
                conn.executemany(
                    """
                    INSERT INTO triage_technician_scores (key, data, model, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    technician_rows,
                )
            if activity_rows:
                conn.executemany(
                    """
                    INSERT INTO triage_auto_triage_activity (
                        key, outcome, source, processed_at, model, fields_changed, error, legacy_backfill
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    activity_rows,
                )

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            self._backfill_from_sqlite_if_needed()
            return
        with connect_sqlite(self._db_path, row_factory=None) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS suggestions "
                "(key TEXT PRIMARY KEY, data TEXT, model TEXT, "
                "created_at TEXT, updated_at TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS auto_triaged "
                "(key TEXT PRIMARY KEY, processed_at TEXT, "
                "priority_updated INTEGER DEFAULT 0, "
                "request_type_updated INTEGER DEFAULT 0)"
            )
            # Migrate: add columns if they don't exist (idempotent)
            try:
                conn.execute("ALTER TABLE auto_triaged ADD COLUMN priority_updated INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE auto_triaged ADD COLUMN request_type_updated INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            conn.execute(
                "CREATE TABLE IF NOT EXISTS auto_triage_log "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "key TEXT NOT NULL, field TEXT NOT NULL, "
                "old_value TEXT, new_value TEXT, confidence REAL, "
                "model TEXT, source TEXT NOT NULL DEFAULT 'auto', "
                "approved_by TEXT, timestamp TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS technician_scores "
                "(key TEXT PRIMARY KEY, data TEXT NOT NULL, model TEXT, "
                "created_at TEXT, updated_at TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS auto_triage_activity "
                "(key TEXT PRIMARY KEY, outcome TEXT NOT NULL, "
                "source TEXT NOT NULL DEFAULT 'auto', processed_at TEXT NOT NULL, "
                "model TEXT, fields_changed TEXT NOT NULL DEFAULT '[]', "
                "error TEXT, legacy_backfill INTEGER NOT NULL DEFAULT 0)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_triage_log_timestamp "
                "ON auto_triage_log(timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_suggestions_updated_at "
                "ON suggestions(updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auto_triage_activity_processed_at "
                "ON auto_triage_activity(processed_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auto_triage_activity_outcome "
                "ON auto_triage_activity(outcome, processed_at DESC)"
            )

    @staticmethod
    def _normalize_activity_key(key: str) -> str:
        return str(key or "").strip().upper()

    @staticmethod
    def _normalize_activity_outcome(outcome: str) -> str:
        normalized = str(outcome or "").strip().lower()
        if normalized not in _AUTO_TRIAGE_ACTIVITY_OUTCOMES:
            raise ValueError(f"Unsupported auto-triage activity outcome: {outcome}")
        return normalized

    @staticmethod
    def _normalize_fields_changed(fields_changed: list[str] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for field in fields_changed or []:
            value = str(field or "").strip()
            if not value or value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        return normalized

    @staticmethod
    def _chunked(values: list[str], size: int = 500) -> list[list[str]]:
        return [values[index:index + size] for index in range(0, len(values), size)]

    def get(self, key: str) -> TriageResult | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT data FROM {'triage_suggestions' if self._use_postgres else 'suggestions'} WHERE key = {self._placeholder()}",
                (key,),
            ).fetchone()
        if not row:
            return None
        return TriageResult(**json.loads(row[0]))

    def get_many(self, keys: list[str]) -> dict[str, TriageResult]:
        if not keys:
            return {}
        placeholders = ",".join(self._placeholder() for _ in keys)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT key, data FROM {'triage_suggestions' if self._use_postgres else 'suggestions'} WHERE key IN ({placeholders})",
                keys,
            ).fetchall()
        return {k: TriageResult(**json.loads(d)) for k, d in rows}

    def save(self, result: TriageResult) -> None:
        now = datetime.now(timezone.utc).isoformat()
        data = result.model_dump_json()
        with self._conn() as conn:
            conn.execute(
                (
                    """
                    INSERT INTO triage_suggestions (key, data, model, created_at, updated_at)
                    VALUES (%s, %s, %s, COALESCE((SELECT created_at FROM triage_suggestions WHERE key = %s), %s), %s)
                    ON CONFLICT(key) DO UPDATE SET
                        data = excluded.data,
                        model = excluded.model,
                        updated_at = excluded.updated_at
                    """
                    if self._use_postgres
                    else
                    "INSERT OR REPLACE INTO suggestions "
                    "(key, data, model, created_at, updated_at) "
                    "VALUES (?, ?, ?, COALESCE("
                    "  (SELECT created_at FROM suggestions WHERE key = ?), ?"
                    "), ?)"
                ),
                (result.key, data, result.model_used, result.key, now, now),
            )

    def delete(self, key: str) -> None:
        with self._conn() as conn:
            conn.execute(
                f"DELETE FROM {'triage_suggestions' if self._use_postgres else 'suggestions'} WHERE key = {self._placeholder()}",
                (key,),
            )

    def list_all(self, strip_auto_fields: bool = False) -> list[TriageResult]:
        """Return all stored suggestions.

        If *strip_auto_fields* is True, remove priority and request_type
        suggestions for tickets that have been auto-triaged (those fields are
        handled by the auto-triage pipeline).
        """
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT data FROM {'triage_suggestions' if self._use_postgres else 'suggestions'} ORDER BY updated_at DESC"
            ).fetchall()
        results = [TriageResult(**json.loads(row[0])) for row in rows]
        if strip_auto_fields:
            triaged = self.get_auto_triaged_keys()
            cleaned: list[TriageResult] = []
            for r in results:
                if r.key in triaged:
                    r.suggestions = [
                        s for s in r.suggestions
                        if s.field not in ("priority", "request_type")
                    ]
                if r.suggestions:
                    cleaned.append(r)
            return cleaned
        return results

    # ------------------------------------------------------------------
    # Auto-triage tracking
    # ------------------------------------------------------------------

    def mark_auto_triaged(
        self,
        key: str,
        priority_updated: bool = False,
        request_type_updated: bool = False,
    ) -> None:
        """Record that a ticket has been auto-triaged with which fields were updated."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                (
                    "INSERT INTO triage_auto_triaged (key, processed_at, priority_updated, request_type_updated) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT(key) DO UPDATE SET "
                    "processed_at = excluded.processed_at, "
                    "priority_updated = GREATEST(triage_auto_triaged.priority_updated, excluded.priority_updated), "
                    "request_type_updated = GREATEST(triage_auto_triaged.request_type_updated, excluded.request_type_updated)"
                    if self._use_postgres
                    else
                    "INSERT INTO auto_triaged (key, processed_at, priority_updated, request_type_updated) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET "
                    "processed_at = excluded.processed_at, "
                    "priority_updated = MAX(priority_updated, excluded.priority_updated), "
                    "request_type_updated = MAX(request_type_updated, excluded.request_type_updated)"
                ),
                (key, now, int(priority_updated), int(request_type_updated)),
            )

    def mark_auto_triaged_if_missing(self, keys: list[str]) -> int:
        """Record keys as processed without overwriting existing processed rows."""
        normalized_keys = [
            str(key or "").strip().upper()
            for key in keys
            if str(key or "").strip()
        ]
        if not normalized_keys:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        rows = [(key, now, 0, 0) for key in dict.fromkeys(normalized_keys)]
        with self._conn() as conn:
            if self._use_postgres:
                existing = {
                    row[0]
                    for row in conn.execute(
                        f"SELECT key FROM triage_auto_triaged WHERE key IN ({','.join(self._placeholder() for _ in normalized_keys)})",
                        normalized_keys,
                    ).fetchall()
                }
                new_rows = [row for row in rows if row[0] not in existing]
                if new_rows:
                    conn.executemany(
                        """
                        INSERT INTO triage_auto_triaged (key, processed_at, priority_updated, request_type_updated)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT(key) DO NOTHING
                        """,
                        new_rows,
                    )
                return len(new_rows)
            conn.executemany(
                "INSERT OR IGNORE INTO auto_triaged (key, processed_at, priority_updated, request_type_updated) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
            return conn.total_changes

    def get_auto_triaged_keys(self) -> set[str]:
        """Return all keys that have been auto-triaged."""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT key FROM {'triage_auto_triaged' if self._use_postgres else 'auto_triaged'}"
            ).fetchall()
        return {row[0] for row in rows}

    def clear_auto_triaged(self) -> None:
        """Delete all rows from auto_triaged so tickets can be re-processed."""
        with self._conn() as conn:
            conn.execute(f"DELETE FROM {'triage_auto_triaged' if self._use_postgres else 'auto_triaged'}")
            conn.execute(
                f"DELETE FROM {'triage_auto_triage_activity' if self._use_postgres else 'auto_triage_activity'}"
            )

    def clear_auto_triaged_keys(self, keys: list[str]) -> None:
        """Delete specific keys from auto_triaged so they can be re-processed."""
        normalized_keys = [
            self._normalize_activity_key(key)
            for key in keys
            if self._normalize_activity_key(key)
        ]
        if not normalized_keys:
            return
        with self._conn() as conn:
            for chunk in self._chunked(normalized_keys):
                placeholders = ",".join(self._placeholder() for _ in chunk)
                conn.execute(
                    f"DELETE FROM {'triage_auto_triaged' if self._use_postgres else 'auto_triaged'} WHERE key IN ({placeholders})",
                    chunk,
                )
                conn.execute(
                    f"DELETE FROM {'triage_auto_triage_activity' if self._use_postgres else 'auto_triage_activity'} WHERE key IN ({placeholders})",
                    chunk,
                )

    def record_auto_triage_activity(
        self,
        key: str,
        outcome: str,
        *,
        source: str = "auto",
        processed_at: str | None = None,
        model: str | None = None,
        fields_changed: list[str] | None = None,
        error: str | None = None,
        legacy_backfill: bool = False,
    ) -> None:
        normalized_key = self._normalize_activity_key(key)
        if not normalized_key:
            return
        normalized_outcome = self._normalize_activity_outcome(outcome)
        fields_payload = json.dumps(self._normalize_fields_changed(fields_changed))
        timestamp = str(processed_at or datetime.now(timezone.utc).isoformat())
        params = (
            normalized_key,
            normalized_outcome,
            str(source or "auto"),
            timestamp,
            str(model or "") or None,
            fields_payload,
            str(error or "") or None,
            int(bool(legacy_backfill)),
        )
        with self._conn() as conn:
            conn.execute(
                (
                    """
                    INSERT INTO triage_auto_triage_activity (
                        key, outcome, source, processed_at, model, fields_changed, error, legacy_backfill
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(key) DO UPDATE SET
                        outcome = excluded.outcome,
                        source = excluded.source,
                        processed_at = excluded.processed_at,
                        model = excluded.model,
                        fields_changed = excluded.fields_changed,
                        error = excluded.error,
                        legacy_backfill = excluded.legacy_backfill
                    """
                    if self._use_postgres
                    else
                    """
                    INSERT INTO auto_triage_activity (
                        key, outcome, source, processed_at, model, fields_changed, error, legacy_backfill
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        outcome = excluded.outcome,
                        source = excluded.source,
                        processed_at = excluded.processed_at,
                        model = excluded.model,
                        fields_changed = excluded.fields_changed,
                        error = excluded.error,
                        legacy_backfill = excluded.legacy_backfill
                    """
                ),
                params,
            )

    def record_auto_triage_activities_if_missing(self, entries: list[dict[str, object]]) -> int:
        normalized_entries: list[tuple[str, str, str, str, str | None, str, str | None, int]] = []
        for entry in entries:
            normalized_key = self._normalize_activity_key(str(entry.get("key") or ""))
            if not normalized_key:
                continue
            normalized_entries.append(
                (
                    normalized_key,
                    self._normalize_activity_outcome(str(entry.get("outcome") or "")),
                    str(entry.get("source") or "auto"),
                    str(entry.get("processed_at") or datetime.now(timezone.utc).isoformat()),
                    str(entry.get("model") or "") or None,
                    json.dumps(self._normalize_fields_changed(entry.get("fields_changed"))),  # type: ignore[arg-type]
                    str(entry.get("error") or "") or None,
                    int(bool(entry.get("legacy_backfill"))),
                )
            )
        if not normalized_entries:
            return 0

        deduped_rows: list[tuple[str, str, str, str, str | None, str, str | None, int]] = []
        seen_keys: set[str] = set()
        for row in normalized_entries:
            if row[0] in seen_keys:
                continue
            deduped_rows.append(row)
            seen_keys.add(row[0])

        with self._conn() as conn:
            activity_table = "triage_auto_triage_activity" if self._use_postgres else "auto_triage_activity"
            existing_keys: set[str] = set()
            keys = [row[0] for row in deduped_rows]
            for chunk in self._chunked(keys):
                placeholders = ",".join(self._placeholder() for _ in chunk)
                existing_keys.update(
                    row[0]
                    for row in conn.execute(
                        f"SELECT key FROM {activity_table} WHERE key IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
            insert_rows = [row for row in deduped_rows if row[0] not in existing_keys]
            if not insert_rows:
                return 0
            conn.executemany(
                (
                    """
                    INSERT INTO triage_auto_triage_activity (
                        key, outcome, source, processed_at, model, fields_changed, error, legacy_backfill
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(key) DO NOTHING
                    """
                    if self._use_postgres
                    else
                    """
                    INSERT OR IGNORE INTO auto_triage_activity (
                        key, outcome, source, processed_at, model, fields_changed, error, legacy_backfill
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """
                ),
                insert_rows,
            )
            return len(insert_rows)

    def list_auto_triage_activity(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT key, outcome, source, processed_at, model, fields_changed, error, legacy_backfill "
                f"FROM {'triage_auto_triage_activity' if self._use_postgres else 'auto_triage_activity'} "
                f"ORDER BY processed_at DESC"
            ).fetchall()
        results: list[dict] = []
        for row in rows:
            try:
                fields_changed = json.loads(row[5] or "[]")
            except Exception:
                fields_changed = []
            results.append(
                {
                    "key": row[0],
                    "outcome": row[1],
                    "source": row[2],
                    "processed_at": row[3],
                    "model": row[4],
                    "fields_changed": fields_changed if isinstance(fields_changed, list) else [],
                    "error": row[6],
                    "legacy_backfill": bool(row[7]),
                }
            )
        return results

    def get_auto_triage_activity_keys(self, outcomes: list[str] | None = None) -> set[str]:
        allowed_outcomes = (
            {self._normalize_activity_outcome(outcome) for outcome in outcomes}
            if outcomes
            else None
        )
        keys: set[str] = set()
        for entry in self.list_auto_triage_activity():
            if allowed_outcomes and entry["outcome"] not in allowed_outcomes:
                continue
            keys.add(str(entry["key"] or ""))
        return keys

    def ensure_auto_triage_activity_backfill(self) -> int:
        if self.get_metadata(_AUTO_TRIAGE_ACTIVITY_BACKFILL_METADATA_KEY) == "1":
            return 0

        auto_triaged_table = "triage_auto_triaged" if self._use_postgres else "auto_triaged"
        log_table = "triage_auto_triage_log" if self._use_postgres else "auto_triage_log"

        with self._conn() as conn:
            auto_triaged_rows = conn.execute(
                f"SELECT key, processed_at FROM {auto_triaged_table}"
            ).fetchall()
            if not auto_triaged_rows:
                return 0
            log_rows = conn.execute(
                f"SELECT key, field, model, timestamp FROM {log_table} ORDER BY timestamp ASC"
            ).fetchall()

        existing_activity_keys = self.get_auto_triage_activity_keys()
        if all(self._normalize_activity_key(row[0]) in existing_activity_keys for row in auto_triaged_rows):
            self.set_metadata(_AUTO_TRIAGE_ACTIVITY_BACKFILL_METADATA_KEY, "1")
            return 0

        changed_by_key: dict[str, dict[str, object]] = {}
        for row in log_rows:
            key = self._normalize_activity_key(row[0])
            if not key:
                continue
            entry = changed_by_key.setdefault(
                key,
                {
                    "fields_changed": [],
                    "model": None,
                    "processed_at": None,
                },
            )
            fields_changed = entry["fields_changed"]
            if isinstance(fields_changed, list) and row[1] and row[1] not in fields_changed:
                fields_changed.append(row[1])
            entry["model"] = row[2]
            entry["processed_at"] = row[3]

        backfill_entries: list[dict[str, object]] = []
        for key, processed_at in auto_triaged_rows:
            normalized_key = self._normalize_activity_key(key)
            if not normalized_key or normalized_key in existing_activity_keys:
                continue
            changed_entry = changed_by_key.get(normalized_key)
            if changed_entry:
                backfill_entries.append(
                    {
                        "key": normalized_key,
                        "outcome": "changed",
                        "source": "migration",
                        "processed_at": changed_entry.get("processed_at") or processed_at,
                        "model": changed_entry.get("model"),
                        "fields_changed": changed_entry.get("fields_changed") or [],
                        "error": None,
                        "legacy_backfill": False,
                    }
                )
            else:
                backfill_entries.append(
                    {
                        "key": normalized_key,
                        "outcome": "backfill",
                        "source": "migration",
                        "processed_at": processed_at,
                        "model": None,
                        "fields_changed": [],
                        "error": None,
                        "legacy_backfill": True,
                    }
                )

        inserted = self.record_auto_triage_activities_if_missing(backfill_entries)
        self.set_metadata(_AUTO_TRIAGE_ACTIVITY_BACKFILL_METADATA_KEY, "1")
        return inserted

    def get_metadata(self, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT value FROM {'triage_metadata' if self._use_postgres else 'metadata'} WHERE key = {self._placeholder()}",
                (key,),
            ).fetchone()
        return str(row[0]) if row else None

    def set_metadata(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                (
                    "INSERT INTO triage_metadata (key, value) VALUES (%s, %s) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                    if self._use_postgres
                    else
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)"
                ),
                (key, value),
            )

    def log_change(
        self,
        key: str,
        field: str,
        old_value: str,
        new_value: str,
        confidence: float,
        model: str,
        source: str = "auto",
        approved_by: str | None = None,
    ) -> None:
        """Record an AI triage change applied to Jira.

        source: 'auto' for auto-triage, 'user' for manually approved.
        approved_by: email of the user who approved (for source='user').
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                (
                    "INSERT INTO triage_auto_triage_log "
                    "(key, field, old_value, new_value, confidence, model, source, approved_by, timestamp) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    if self._use_postgres
                    else
                    "INSERT INTO auto_triage_log "
                    "(key, field, old_value, new_value, confidence, model, source, approved_by, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (key, field, old_value, new_value, confidence, model, source, approved_by, now),
            )

    def get_triage_log(self, limit: int = 500, search: str = "") -> list[dict]:
        """Return recent triage changes, newest first."""
        normalized_search = search.strip().lower()
        with self._conn() as conn:
            log_table = "triage_auto_triage_log" if self._use_postgres else "auto_triage_log"
            if normalized_search:
                rows = conn.execute(
                    f"SELECT key, field, old_value, new_value, confidence, model, source, approved_by, timestamp "
                    f"FROM {log_table} "
                    f"WHERE lower(coalesce(key, '')) LIKE {self._placeholder()} "
                    f"OR lower(coalesce(field, '')) LIKE {self._placeholder()} "
                    f"OR lower(coalesce(old_value, '')) LIKE {self._placeholder()} "
                    f"OR lower(coalesce(new_value, '')) LIKE {self._placeholder()} "
                    f"OR lower(coalesce(model, '')) LIKE {self._placeholder()} "
                    f"OR lower(coalesce(source, '')) LIKE {self._placeholder()} "
                    f"OR lower(coalesce(approved_by, '')) LIKE {self._placeholder()} "
                    f"ORDER BY timestamp DESC LIMIT {self._placeholder()}",
                    tuple([f"%{normalized_search}%"] * 7 + [limit]),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT key, field, old_value, new_value, confidence, model, source, approved_by, timestamp "
                    f"FROM {log_table} ORDER BY timestamp DESC LIMIT {self._placeholder()}",
                    (limit,),
                ).fetchall()
        return [
            {
                "key": r[0],
                "field": r[1],
                "old_value": r[2],
                "new_value": r[3],
                "confidence": r[4],
                "model": r[5],
                "source": r[6],
                "approved_by": r[7],
                "timestamp": r[8],
            }
            for r in rows
        ]

    def save_technician_score(self, score: TechnicianScore) -> None:
        """Insert or update a technician QA score for a ticket."""
        now = datetime.now(timezone.utc).isoformat()
        data = score.model_dump_json()
        with self._conn() as conn:
            conn.execute(
                (
                    "INSERT INTO triage_technician_scores "
                    "(key, data, model, created_at, updated_at) "
                    "VALUES (%s, %s, %s, COALESCE((SELECT created_at FROM triage_technician_scores WHERE key = %s), %s), %s) "
                    "ON CONFLICT(key) DO UPDATE SET data = excluded.data, model = excluded.model, updated_at = excluded.updated_at"
                    if self._use_postgres
                    else
                    "INSERT OR REPLACE INTO technician_scores "
                    "(key, data, model, created_at, updated_at) "
                    "VALUES (?, ?, ?, COALESCE("
                    "  (SELECT created_at FROM technician_scores WHERE key = ?), ?"
                    "), ?)"
                ),
                (score.key, data, score.model_used, score.key, now, now),
            )

    def list_technician_scores(self, limit: int = 500) -> list[TechnicianScore]:
        """Return technician QA scores, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT data FROM {'triage_technician_scores' if self._use_postgres else 'technician_scores'} ORDER BY updated_at DESC LIMIT {self._placeholder()}",
                (limit,),
            ).fetchall()
        return [TechnicianScore(**json.loads(row[0])) for row in rows]

    def get_technician_score(self, key: str) -> TechnicianScore | None:
        """Return the technician QA score for a specific ticket, if present."""
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT data FROM {'triage_technician_scores' if self._use_postgres else 'technician_scores'} WHERE key = {self._placeholder()} LIMIT 1",
                (key,),
            ).fetchone()
        if not row:
            return None
        return TechnicianScore(**json.loads(row[0]))

    def get_technician_scored_keys(self) -> set[str]:
        """Return keys that already have a technician QA score."""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT key FROM {'triage_technician_scores' if self._use_postgres else 'technician_scores'}"
            ).fetchall()
        return {row[0] for row in rows}

    def clear_technician_scores(self) -> None:
        """Delete all technician QA scores."""
        with self._conn() as conn:
            conn.execute(f"DELETE FROM {'triage_technician_scores' if self._use_postgres else 'technician_scores'}")

    # ------------------------------------------------------------------
    # Per-field manipulation
    # ------------------------------------------------------------------

    def remove_field(self, key: str, field: str) -> TriageResult | None:
        """Remove a single field from a suggestion. Deletes the whole row if no
        suggestions remain. Returns the updated result or None if deleted."""
        result = self.get(key)
        if not result:
            return None
        result.suggestions = [s for s in result.suggestions if s.field != field]
        if not result.suggestions:
            self.delete(key)
            return None
        self.save(result)
        return result

    def __repr__(self) -> str:
        return f"TriageStore(db={self._db_path})"


# Module-level singleton
store = TriageStore()
