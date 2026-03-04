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

    def __repr__(self) -> str:
        return f"TriageStore(db={self._db_path})"


# Module-level singleton
store = TriageStore()
