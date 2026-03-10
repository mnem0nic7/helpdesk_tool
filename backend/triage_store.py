"""SQLite persistence for AI triage suggestions."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

from config import DATA_DIR
from models import TechnicianScore, TriageResult

logger = logging.getLogger(__name__)


class TriageStore:
    """Simple SQLite store for AI triage suggestions, keyed by issue key."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "triage_suggestions.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
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

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def get(self, key: str) -> TriageResult | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data FROM suggestions WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        return TriageResult(**json.loads(row[0]))

    def get_many(self, keys: list[str]) -> dict[str, TriageResult]:
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT key, data FROM suggestions WHERE key IN ({placeholders})",
                keys,
            ).fetchall()
        return {k: TriageResult(**json.loads(d)) for k, d in rows}

    def save(self, result: TriageResult) -> None:
        now = datetime.now(timezone.utc).isoformat()
        data = result.model_dump_json()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO suggestions "
                "(key, data, model, created_at, updated_at) "
                "VALUES (?, ?, ?, COALESCE("
                "  (SELECT created_at FROM suggestions WHERE key = ?), ?"
                "), ?)",
                (result.key, data, result.model_used, result.key, now, now),
            )

    def delete(self, key: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM suggestions WHERE key = ?", (key,))

    def list_all(self, strip_auto_fields: bool = False) -> list[TriageResult]:
        """Return all stored suggestions.

        If *strip_auto_fields* is True, remove priority and request_type
        suggestions for tickets that have been auto-triaged (those fields are
        handled by the auto-triage pipeline).
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT data FROM suggestions ORDER BY updated_at DESC"
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
                "INSERT INTO auto_triaged (key, processed_at, priority_updated, request_type_updated) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "processed_at = excluded.processed_at, "
                "priority_updated = MAX(priority_updated, excluded.priority_updated), "
                "request_type_updated = MAX(request_type_updated, excluded.request_type_updated)",
                (key, now, int(priority_updated), int(request_type_updated)),
            )

    def get_auto_triaged_keys(self) -> set[str]:
        """Return all keys that have been auto-triaged."""
        with self._conn() as conn:
            rows = conn.execute("SELECT key FROM auto_triaged").fetchall()
        return {row[0] for row in rows}

    def clear_auto_triaged(self) -> None:
        """Delete all rows from auto_triaged so tickets can be re-processed."""
        with self._conn() as conn:
            conn.execute("DELETE FROM auto_triaged")

    def clear_auto_triaged_keys(self, keys: list[str]) -> None:
        """Delete specific keys from auto_triaged so they can be re-processed."""
        if not keys:
            return
        placeholders = ",".join("?" for _ in keys)
        with self._conn() as conn:
            conn.execute(f"DELETE FROM auto_triaged WHERE key IN ({placeholders})", keys)

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
                "INSERT INTO auto_triage_log "
                "(key, field, old_value, new_value, confidence, model, source, approved_by, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (key, field, old_value, new_value, confidence, model, source, approved_by, now),
            )

    def get_triage_log(self, limit: int = 500) -> list[dict]:
        """Return recent triage changes, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT key, field, old_value, new_value, confidence, model, source, approved_by, timestamp "
                "FROM auto_triage_log ORDER BY timestamp DESC LIMIT ?",
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
                "INSERT OR REPLACE INTO technician_scores "
                "(key, data, model, created_at, updated_at) "
                "VALUES (?, ?, ?, COALESCE("
                "  (SELECT created_at FROM technician_scores WHERE key = ?), ?"
                "), ?)",
                (score.key, data, score.model_used, score.key, now, now),
            )

    def list_technician_scores(self, limit: int = 500) -> list[TechnicianScore]:
        """Return technician QA scores, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT data FROM technician_scores ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [TechnicianScore(**json.loads(row[0])) for row in rows]

    def get_technician_scored_keys(self) -> set[str]:
        """Return keys that already have a technician QA score."""
        with self._conn() as conn:
            rows = conn.execute("SELECT key FROM technician_scores").fetchall()
        return {row[0] for row in rows}

    def clear_technician_scores(self) -> None:
        """Delete all technician QA scores."""
        with self._conn() as conn:
            conn.execute("DELETE FROM technician_scores")

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
