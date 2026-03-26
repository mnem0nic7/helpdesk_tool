"""Shared SQLite connection helpers for multi-process runtime access."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_BUSY_TIMEOUT_MS = 5000


def connect_sqlite(
    db_path: str | os.PathLike[str],
    *,
    row_factory: sqlite3.Row | None = sqlite3.Row,
    wal: bool = True,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> sqlite3.Connection:
    """Return a SQLite connection configured for shared runtime usage."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout_seconds = max(float(busy_timeout_ms) / 1000.0, 1.0)
    conn = sqlite3.connect(str(path), timeout=timeout_seconds)
    if row_factory is not None:
        conn.row_factory = row_factory
    conn.execute(f"PRAGMA busy_timeout={max(0, int(busy_timeout_ms))}")
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn
