"""Shared Postgres connection and migration helpers."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from psycopg import connect
from psycopg.rows import dict_row

from config import DATABASE_CONNECT_TIMEOUT_SECONDS, DATABASE_URL

logger = logging.getLogger(__name__)

_MIGRATION_LOCK = threading.Lock()
_MIGRATIONS_APPLIED = False
_MIGRATIONS_DIR = Path(__file__).resolve().parent / "storage_migrations"


def postgres_enabled() -> bool:
    return bool(DATABASE_URL)


def connect_postgres(*, row_factory: Any | None = dict_row):
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    kwargs: dict[str, Any] = {"connect_timeout": max(1, int(DATABASE_CONNECT_TIMEOUT_SECONDS))}
    if row_factory is not None:
        kwargs["row_factory"] = row_factory
    return connect(DATABASE_URL, **kwargs)


def ensure_postgres_schema() -> None:
    global _MIGRATIONS_APPLIED
    if _MIGRATIONS_APPLIED or not postgres_enabled():
        return
    with _MIGRATION_LOCK:
        if _MIGRATIONS_APPLIED or not postgres_enabled():
            return
        with connect_postgres() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            applied = {
                str(row["version"])
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
                if path.name in applied:
                    continue
                logger.info("Applying Postgres migration %s", path.name)
                conn.execute(path.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT(version) DO NOTHING",
                    (path.name,),
                )
        _MIGRATIONS_APPLIED = True


def postgres_status() -> dict[str, Any]:
    if not postgres_enabled():
        return {"configured": False, "ready": False, "message": "DATABASE_URL not configured"}
    try:
        ensure_postgres_schema()
        with connect_postgres() as conn:
            row = conn.execute("SELECT 1 AS ok").fetchone()
        return {
            "configured": True,
            "ready": bool(row and row["ok"] == 1),
            "message": "Postgres ready",
        }
    except Exception as exc:
        logger.exception("Postgres health check failed")
        return {
            "configured": True,
            "ready": False,
            "message": str(exc),
        }
