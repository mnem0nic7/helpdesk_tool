"""SQLite-backed delivery metadata store for Azure Cost exports.

This store is the first durable layer for export-backed reporting. It keeps
delivery metadata, staged models, and quarantine payloads separate from the
existing live Azure cache so the export lane can evolve independently.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_ALLOWED_PARSE_STATUSES = {"discovered", "staged", "parsed", "quarantined", "failed"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_path(value: str | Path | None) -> str:
    if value is None:
        return ""
    return str(value) if isinstance(value, Path) else str(value)


def _coerce_text(value: Any | None) -> str:
    return "" if value is None else str(value)


def _coerce_date_text(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return date.fromisoformat(value[:10]).isoformat()
    raise TypeError(f"Unsupported delivery date value: {type(value)!r}")


def _coerce_timestamp(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _default_data_dir() -> Path:
    env_value = os.getenv("DATA_DIR", "").strip()
    if env_value:
        return Path(env_value)
    return Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class ExportDeliveryMetadata:
    """Normalized metadata for one exported delivery."""

    dataset: str
    scope_key: str
    delivery_date: date | datetime | str
    run_id: str
    landing_path: str | Path
    delivery_key: str = ""
    parse_status: str = "discovered"
    row_count: int = 0
    manifest_path: str | Path = ""
    discovered_at: datetime | str | None = None
    parsed_at: datetime | str | None = None
    error_message: str | None = None
    summary: dict[str, Any] | None = None
    source_etag: str | None = None
    source_size_bytes: int = 0
    delivery_id: str = ""

    def to_row(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["delivery_date"] = _coerce_date_text(self.delivery_date)
        payload["landing_path"] = _coerce_path(self.landing_path)
        payload["manifest_path"] = _coerce_path(self.manifest_path)
        payload["delivery_key"] = _coerce_text(self.delivery_key) or payload["landing_path"]
        payload["run_id"] = _coerce_text(self.run_id)
        payload["discovered_at"] = _coerce_timestamp(self.discovered_at) or _utcnow()
        payload["parsed_at"] = _coerce_timestamp(self.parsed_at)
        payload["error_message"] = _coerce_text(self.error_message) or None
        payload["summary_json"] = json.dumps(self.summary or {}, sort_keys=True)
        payload["source_etag"] = _coerce_text(self.source_etag) or None
        payload["parse_status"] = _coerce_text(self.parse_status) or "discovered"
        payload["row_count"] = int(self.row_count)
        payload["source_size_bytes"] = int(self.source_size_bytes)
        payload["delivery_id"] = _coerce_text(self.delivery_id) or uuid.uuid4().hex
        return payload


class AzureExportStore:
    """SQLite-backed delivery metadata, staged models, and quarantine store."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or (_default_data_dir() / "azure_export_deliveries.db"))
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS export_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    dataset TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    delivery_date TEXT NOT NULL,
                    run_id TEXT NOT NULL DEFAULT '',
                    delivery_key TEXT NOT NULL UNIQUE,
                    landing_path TEXT NOT NULL UNIQUE,
                    manifest_path TEXT NOT NULL DEFAULT '',
                    parse_status TEXT NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    discovered_at TEXT NOT NULL,
                    parsed_at TEXT,
                    error_message TEXT,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    source_etag TEXT,
                    source_size_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_export_deliveries_dataset_scope
                ON export_deliveries(dataset, scope_key)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_export_deliveries_status
                ON export_deliveries(parse_status)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS export_stage_models (
                    delivery_key TEXT PRIMARY KEY,
                    stage_model_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS export_quarantine (
                    delivery_key TEXT PRIMARY KEY,
                    manifest_json TEXT NOT NULL,
                    content TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _coerce_record(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        payload = dict(row)
        payload["row_count"] = int(payload.get("row_count") or 0)
        payload["source_size_bytes"] = int(payload.get("source_size_bytes") or 0)
        try:
            payload["summary"] = json.loads(str(payload.get("summary_json") or "{}"))
        except json.JSONDecodeError:
            payload["summary"] = {}
        return payload

    def _validate_status(self, value: str) -> str:
        status = _coerce_text(value) or "discovered"
        if status not in _ALLOWED_PARSE_STATUSES:
            raise ValueError(f"Unsupported parse status: {status!r}")
        return status

    def record_delivery(self, metadata: ExportDeliveryMetadata | dict[str, Any]) -> dict[str, Any]:
        """Insert or update a delivery record keyed by landing path."""

        payload = metadata.to_row() if isinstance(metadata, ExportDeliveryMetadata) else dict(metadata)
        payload["dataset"] = _coerce_text(payload.get("dataset"))
        payload["scope_key"] = _coerce_text(payload.get("scope_key"))
        payload["delivery_date"] = _coerce_date_text(payload.get("delivery_date"))
        payload["run_id"] = _coerce_text(payload.get("run_id"))
        payload["landing_path"] = _coerce_path(payload.get("landing_path"))
        payload["delivery_key"] = _coerce_text(payload.get("delivery_key")) or payload["landing_path"]
        payload["manifest_path"] = _coerce_path(payload.get("manifest_path"))
        payload["parse_status"] = self._validate_status(payload.get("parse_status", "discovered"))
        payload["row_count"] = int(payload.get("row_count") or 0)
        payload["discovered_at"] = _coerce_timestamp(payload.get("discovered_at")) or _utcnow()
        payload["parsed_at"] = _coerce_timestamp(payload.get("parsed_at"))
        payload["error_message"] = _coerce_text(payload.get("error_message")) or None
        payload["summary_json"] = json.dumps(payload.get("summary") or {}, sort_keys=True)
        payload["source_etag"] = _coerce_text(payload.get("source_etag")) or None
        payload["source_size_bytes"] = int(payload.get("source_size_bytes") or 0)
        payload["delivery_id"] = _coerce_text(payload.get("delivery_id")) or uuid.uuid4().hex
        payload["created_at"] = _utcnow()
        payload["updated_at"] = payload["created_at"]

        if not payload["dataset"]:
            raise ValueError("dataset is required")
        if not payload["scope_key"]:
            raise ValueError("scope_key is required")
        if not payload["landing_path"]:
            raise ValueError("landing_path is required")

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO export_deliveries (
                    delivery_id,
                    dataset,
                    scope_key,
                    delivery_date,
                    run_id,
                    delivery_key,
                    landing_path,
                    manifest_path,
                    parse_status,
                    row_count,
                    discovered_at,
                    parsed_at,
                    error_message,
                    summary_json,
                    source_etag,
                    source_size_bytes,
                    created_at,
                    updated_at
                )
                VALUES (
                    :delivery_id,
                    :dataset,
                    :scope_key,
                    :delivery_date,
                    :run_id,
                    :delivery_key,
                    :landing_path,
                    :manifest_path,
                    :parse_status,
                    :row_count,
                    :discovered_at,
                    :parsed_at,
                    :error_message,
                    :summary_json,
                    :source_etag,
                    :source_size_bytes,
                    :created_at,
                    :updated_at
                )
                ON CONFLICT(landing_path) DO UPDATE SET
                    dataset = excluded.dataset,
                    scope_key = excluded.scope_key,
                    delivery_date = excluded.delivery_date,
                    run_id = excluded.run_id,
                    delivery_key = excluded.delivery_key,
                    manifest_path = excluded.manifest_path,
                    parse_status = excluded.parse_status,
                    row_count = excluded.row_count,
                    discovered_at = excluded.discovered_at,
                    parsed_at = excluded.parsed_at,
                    error_message = excluded.error_message,
                    summary_json = excluded.summary_json,
                    source_etag = excluded.source_etag,
                    source_size_bytes = excluded.source_size_bytes,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
            conn.commit()
        return self.get_delivery_by_path(payload["landing_path"]) or {}

    def get_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM export_deliveries WHERE delivery_id = ?",
                (_coerce_text(delivery_id),),
            ).fetchone()
        return self._coerce_record(row)

    def get_delivery_by_path(self, landing_path: str | Path) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM export_deliveries WHERE landing_path = ?",
                (_coerce_path(landing_path),),
            ).fetchone()
        return self._coerce_record(row)

    def get_delivery_by_key(self, delivery_key: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM export_deliveries WHERE delivery_key = ?",
                (_coerce_text(delivery_key),),
            ).fetchone()
        return self._coerce_record(row)

    def list_deliveries(
        self,
        *,
        dataset: str | None = None,
        scope_key: str | None = None,
        parse_status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if dataset is not None:
            clauses.append("dataset = ?")
            params.append(dataset)
        if scope_key is not None:
            clauses.append("scope_key = ?")
            params.append(scope_key)
        if parse_status is not None:
            clauses.append("parse_status = ?")
            params.append(self._validate_status(parse_status))

        sql = "SELECT * FROM export_deliveries"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY discovered_at ASC, delivery_id ASC"

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._coerce_record(row) for row in rows if row is not None]

    def update_delivery(self, delivery_id: str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return self.get_delivery(delivery_id)

        allowed = {
            "dataset",
            "scope_key",
            "delivery_date",
            "run_id",
            "delivery_key",
            "landing_path",
            "manifest_path",
            "parse_status",
            "row_count",
            "discovered_at",
            "parsed_at",
            "error_message",
            "summary",
            "source_etag",
            "source_size_bytes",
        }
        updates: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Unsupported delivery field: {key}")
            if key in {
                "dataset",
                "scope_key",
                "run_id",
                "delivery_key",
                "landing_path",
                "manifest_path",
                "source_etag",
                "error_message",
            }:
                updates[key] = _coerce_text(value) if value is not None else None
            elif key == "delivery_date":
                updates[key] = _coerce_date_text(value)
            elif key == "parse_status":
                updates[key] = self._validate_status(value)
            elif key == "summary":
                updates["summary_json"] = json.dumps(value or {}, sort_keys=True)
            elif key in {"row_count", "source_size_bytes"}:
                updates[key] = int(value or 0)
            elif key in {"discovered_at", "parsed_at"}:
                updates[key] = _coerce_timestamp(value)

        updates["updated_at"] = _utcnow()

        assignments = ", ".join(f"{column} = :{column}" for column in updates)
        updates["delivery_id"] = delivery_id

        with self._conn() as conn:
            conn.execute(
                f"UPDATE export_deliveries SET {assignments} WHERE delivery_id = :delivery_id",
                updates,
            )
            conn.commit()
        return self.get_delivery(delivery_id)

    def has_delivery(self, delivery_key: str) -> bool:
        return self.get_delivery_by_key(delivery_key) is not None

    def get_manifest(self, delivery_key: str) -> dict[str, Any] | None:
        record = self.get_delivery_by_key(delivery_key)
        if record is None:
            return None
        return {
            "dataset": record["dataset"],
            "scope": record["scope_key"],
            "path": record["landing_path"],
            "delivery_time": record["discovered_at"],
            "delivery_key": record["delivery_key"],
            "parse_status": record["parse_status"],
            "row_count": record["row_count"],
            "error_details": record["error_message"] or "",
            "summary": record.get("summary") or {},
            "recorded_at": record["updated_at"],
        }

    def record_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        delivery_time = (
            manifest.get("delivery_time")
            or manifest.get("discovered_at")
            or manifest.get("recorded_at")
            or _utcnow()
        )
        return self.record_delivery(
            {
                "dataset": manifest.get("dataset") or "",
                "scope_key": manifest.get("scope") or manifest.get("scope_key") or "",
                "delivery_date": str(delivery_time)[:10],
                "run_id": manifest.get("run_id") or "",
                "delivery_key": manifest.get("delivery_key") or manifest.get("path") or "",
                "landing_path": manifest.get("path") or manifest.get("delivery_key") or "",
                "manifest_path": manifest.get("manifest_path") or "",
                "parse_status": manifest.get("parse_status") or "discovered",
                "row_count": manifest.get("row_count") or 0,
                "discovered_at": delivery_time,
                "parsed_at": manifest.get("parsed_at"),
                "error_message": manifest.get("error_details") or manifest.get("error_message"),
                "summary": manifest.get("summary") or {},
            }
        )

    def record_stage_model(self, delivery_key: str, staged_model: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO export_stage_models (delivery_key, stage_model_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(delivery_key) DO UPDATE SET
                    stage_model_json = excluded.stage_model_json,
                    updated_at = excluded.updated_at
                """,
                (_coerce_text(delivery_key), json.dumps(staged_model, sort_keys=True), _utcnow()),
            )
            conn.commit()

    def get_stage_model(self, delivery_key: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT stage_model_json FROM export_stage_models WHERE delivery_key = ?",
                (_coerce_text(delivery_key),),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["stage_model_json"]))

    def record_quarantine(self, manifest: dict[str, Any], content: str | bytes) -> None:
        delivery_key = _coerce_text(manifest.get("delivery_key") or manifest.get("path"))
        payload = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO export_quarantine (delivery_key, manifest_json, content, recorded_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(delivery_key) DO UPDATE SET
                    manifest_json = excluded.manifest_json,
                    content = excluded.content,
                    recorded_at = excluded.recorded_at
                """,
                (delivery_key, json.dumps(manifest, sort_keys=True), payload, _utcnow()),
            )
            conn.commit()

    def get_quarantine(self, delivery_key: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT manifest_json, content, recorded_at FROM export_quarantine WHERE delivery_key = ?",
                (_coerce_text(delivery_key),),
            ).fetchone()
        if row is None:
            return None
        return {
            "manifest": json.loads(str(row["manifest_json"])),
            "content": str(row["content"]),
            "recorded_at": str(row["recorded_at"]),
        }
