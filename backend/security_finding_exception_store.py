"""Durable storage for Azure security finding exceptions."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR
from sqlite_utils import connect_sqlite

_STATUS_ACTIVE = "active"
_STATUS_RESTORED = "restored"
_ALL_FINDINGS_KEY = "all-findings"
_ALL_FINDINGS_LABEL = "All user-security findings"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    return str(value or "").strip()


class SecurityFindingExceptionStore:
    """SQLite-backed storage for approved security finding exceptions."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(DATA_DIR, "security_finding_exceptions.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self):
        return connect_sqlite(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS security_finding_exceptions (
                    exception_id TEXT NOT NULL PRIMARY KEY,
                    scope TEXT NOT NULL,
                    finding_key TEXT NOT NULL DEFAULT 'all-findings',
                    finding_label TEXT NOT NULL DEFAULT 'All user-security findings',
                    entity_id TEXT NOT NULL,
                    entity_label TEXT NOT NULL DEFAULT '',
                    entity_subtitle TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by_email TEXT NOT NULL DEFAULT '',
                    created_by_name TEXT NOT NULL DEFAULT '',
                    updated_by_email TEXT NOT NULL DEFAULT '',
                    updated_by_name TEXT NOT NULL DEFAULT ''
                );
                """
            )
            columns = {
                _text(row["name"]) if hasattr(row, "__getitem__") else _text(row[1])
                for row in conn.execute("PRAGMA table_info(security_finding_exceptions)").fetchall()
            }
            if "finding_key" not in columns:
                conn.execute(
                    f"ALTER TABLE security_finding_exceptions ADD COLUMN finding_key TEXT NOT NULL DEFAULT '{_ALL_FINDINGS_KEY}'"
                )
            if "finding_label" not in columns:
                conn.execute(
                    f"ALTER TABLE security_finding_exceptions ADD COLUMN finding_label TEXT NOT NULL DEFAULT '{_ALL_FINDINGS_LABEL}'"
                )
            conn.execute(
                """
                UPDATE security_finding_exceptions
                SET
                    finding_key = CASE
                        WHEN TRIM(COALESCE(finding_key, '')) = '' THEN ?
                        ELSE TRIM(finding_key)
                    END,
                    finding_label = CASE
                        WHEN TRIM(COALESCE(finding_label, '')) = '' THEN ?
                        ELSE TRIM(finding_label)
                    END
                WHERE TRIM(COALESCE(finding_key, '')) = '' OR TRIM(COALESCE(finding_label, '')) = ''
                """,
                (_ALL_FINDINGS_KEY, _ALL_FINDINGS_LABEL),
            )
            conn.executescript(
                """
                DROP INDEX IF EXISTS idx_security_finding_exceptions_scope_entity;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_security_finding_exceptions_scope_entity_finding
                    ON security_finding_exceptions (scope, entity_id, finding_key);
                CREATE INDEX IF NOT EXISTS idx_security_finding_exceptions_scope_status
                    ON security_finding_exceptions (scope, status, updated_at DESC);
                """
            )
            conn.commit()

    def _row_to_payload(self, row: Any) -> dict[str, Any]:
        return {
            "exception_id": _text(row["exception_id"]),
            "scope": _text(row["scope"]) or "directory_user",
            "finding_key": _text(row["finding_key"]) or _ALL_FINDINGS_KEY,
            "finding_label": _text(row["finding_label"]) or _ALL_FINDINGS_LABEL,
            "entity_id": _text(row["entity_id"]),
            "entity_label": _text(row["entity_label"]),
            "entity_subtitle": _text(row["entity_subtitle"]),
            "reason": _text(row["reason"]),
            "status": _text(row["status"]) or _STATUS_ACTIVE,
            "created_at": _text(row["created_at"]),
            "updated_at": _text(row["updated_at"]),
            "created_by_email": _text(row["created_by_email"]),
            "created_by_name": _text(row["created_by_name"]),
            "updated_by_email": _text(row["updated_by_email"]),
            "updated_by_name": _text(row["updated_by_name"]),
        }

    def get_exception(self, exception_id: str) -> dict[str, Any] | None:
        exception_id_text = _text(exception_id)
        if not exception_id_text:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT
                    exception_id,
                    scope,
                    finding_key,
                    finding_label,
                    entity_id,
                    entity_label,
                    entity_subtitle,
                    reason,
                    status,
                    created_at,
                    updated_at,
                    created_by_email,
                    created_by_name,
                    updated_by_email,
                    updated_by_name
                FROM security_finding_exceptions
                WHERE exception_id = ?
                """,
                (exception_id_text,),
            ).fetchone()
        return self._row_to_payload(row) if row else None

    def list_exceptions(self, *, scope: str, active_only: bool = True) -> list[dict[str, Any]]:
        scope_text = _text(scope)
        if not scope_text:
            return []
        where = "WHERE scope = ?"
        params: list[Any] = [scope_text]
        if active_only:
            where += " AND status = ?"
            params.append(_STATUS_ACTIVE)
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    exception_id,
                    scope,
                    finding_key,
                    finding_label,
                    entity_id,
                    entity_label,
                    entity_subtitle,
                    reason,
                    status,
                    created_at,
                    updated_at,
                    created_by_email,
                    created_by_name,
                    updated_by_email,
                    updated_by_name
                FROM security_finding_exceptions
                {where}
                ORDER BY updated_at DESC, entity_label ASC, entity_id ASC
                """,
                params,
            ).fetchall()
        return [self._row_to_payload(row) for row in rows]

    def get_active_entity_ids(self, scope: str, finding_keys: set[str] | None = None) -> set[str]:
        normalized_keys = {_text(item) for item in (finding_keys or set()) if _text(item)}
        return {
            _text(item.get("entity_id"))
            for item in self.list_exceptions(scope=scope, active_only=True)
            if _text(item.get("entity_id"))
            and (
                not normalized_keys
                or _text(item.get("finding_key")) == _ALL_FINDINGS_KEY
                or _text(item.get("finding_key")) in normalized_keys
            )
        }

    def upsert_exception(
        self,
        *,
        scope: str,
        finding_key: str = _ALL_FINDINGS_KEY,
        finding_label: str = _ALL_FINDINGS_LABEL,
        entity_id: str,
        entity_label: str = "",
        entity_subtitle: str = "",
        reason: str,
        actor_email: str = "",
        actor_name: str = "",
    ) -> dict[str, Any]:
        scope_text = _text(scope)
        finding_key_text = _text(finding_key) or _ALL_FINDINGS_KEY
        finding_label_text = _text(finding_label) or _ALL_FINDINGS_LABEL
        entity_id_text = _text(entity_id)
        if not scope_text or not entity_id_text:
            raise ValueError("Scope, finding_key, and entity_id are required.")

        timestamp = _utcnow_iso()
        reason_text = _text(reason)
        actor_email_text = _text(actor_email)
        actor_name_text = _text(actor_name)

        with self._lock:
            with self._conn() as conn:
                existing = conn.execute(
                    """
                    SELECT exception_id, created_at, created_by_email, created_by_name
                    FROM security_finding_exceptions
                    WHERE scope = ? AND entity_id = ? AND finding_key = ?
                    """,
                    (scope_text, entity_id_text, finding_key_text),
                ).fetchone()

                if existing:
                    exception_id = _text(existing["exception_id"])
                    conn.execute(
                        """
                        UPDATE security_finding_exceptions
                        SET
                            finding_label = ?,
                            entity_label = ?,
                            entity_subtitle = ?,
                            reason = ?,
                            status = ?,
                            updated_at = ?,
                            updated_by_email = ?,
                            updated_by_name = ?
                        WHERE exception_id = ?
                        """,
                        (
                            finding_label_text,
                            _text(entity_label),
                            _text(entity_subtitle),
                            reason_text,
                            _STATUS_ACTIVE,
                            timestamp,
                            actor_email_text,
                            actor_name_text,
                            exception_id,
                        ),
                    )
                else:
                    exception_id = uuid.uuid4().hex
                    conn.execute(
                        """
                        INSERT INTO security_finding_exceptions (
                            exception_id,
                            scope,
                            finding_key,
                            finding_label,
                            entity_id,
                            entity_label,
                            entity_subtitle,
                            reason,
                            status,
                            created_at,
                            updated_at,
                            created_by_email,
                            created_by_name,
                            updated_by_email,
                            updated_by_name
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            exception_id,
                            scope_text,
                            finding_key_text,
                            finding_label_text,
                            entity_id_text,
                            _text(entity_label),
                            _text(entity_subtitle),
                            reason_text,
                            _STATUS_ACTIVE,
                            timestamp,
                            timestamp,
                            actor_email_text,
                            actor_name_text,
                            actor_email_text,
                            actor_name_text,
                        ),
                    )
                conn.commit()

        payload = self.get_exception(exception_id)
        if payload is None:
            raise RuntimeError("Failed to load saved security finding exception.")
        return payload

    def restore_exception(
        self,
        exception_id: str,
        *,
        actor_email: str = "",
        actor_name: str = "",
    ) -> dict[str, Any] | None:
        exception_id_text = _text(exception_id)
        if not exception_id_text:
            return None

        timestamp = _utcnow_iso()
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT exception_id FROM security_finding_exceptions WHERE exception_id = ?",
                    (exception_id_text,),
                ).fetchone()
                if not row:
                    return None
                conn.execute(
                    """
                    UPDATE security_finding_exceptions
                    SET
                        status = ?,
                        updated_at = ?,
                        updated_by_email = ?,
                        updated_by_name = ?
                    WHERE exception_id = ?
                    """,
                    (
                        _STATUS_RESTORED,
                        timestamp,
                        _text(actor_email),
                        _text(actor_name),
                        exception_id_text,
                    ),
                )
                conn.commit()

        return self.get_exception(exception_id_text)


security_finding_exception_store = SecurityFindingExceptionStore()
