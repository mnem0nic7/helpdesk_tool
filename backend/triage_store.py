"""SQLite persistence for AI triage suggestions."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

from config import DATA_DIR
from models import TriageResult

logger = logging.getLogger(__name__)


class TriageStore:
    """Simple SQLite store for AI triage suggestions, keyed by issue key."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "triage_suggestions.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS suggestions "
                "(key TEXT PRIMARY KEY, data TEXT, model TEXT, "
                "created_at TEXT, updated_at TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS auto_triaged "
                "(key TEXT PRIMARY KEY, processed_at TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS auto_triage_log "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "key TEXT NOT NULL, field TEXT NOT NULL, "
                "old_value TEXT, new_value TEXT, confidence REAL, "
                "model TEXT, source TEXT NOT NULL DEFAULT 'auto', "
                "approved_by TEXT, timestamp TEXT NOT NULL)"
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

    def list_all(self) -> list[TriageResult]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT data FROM suggestions ORDER BY updated_at DESC"
            ).fetchall()
        return [TriageResult(**json.loads(row[0])) for row in rows]

    # ------------------------------------------------------------------
    # Auto-triage tracking
    # ------------------------------------------------------------------

    def mark_auto_triaged(self, key: str) -> None:
        """Record that a ticket has been auto-triaged."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO auto_triaged (key, processed_at) VALUES (?, ?)",
                (key, now),
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
