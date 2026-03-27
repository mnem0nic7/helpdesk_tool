from __future__ import annotations

import logging
import sqlite3
from datetime import date
from typing import Any

import pytest

import azure_export_store as azure_export_store_module
from azure_export_store import AzureExportStore, ExportDeliveryMetadata


class _PostgresSqliteProxy:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @staticmethod
    def _translate(sql: str) -> str:
        return sql.replace("%s", "?")

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> sqlite3.Cursor:
        return self._conn.execute(self._translate(sql), params)

    def executemany(self, sql: str, seq_of_params: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        return self._conn.executemany(self._translate(sql), seq_of_params)

    def commit(self) -> None:
        self._conn.commit()

    def __enter__(self) -> _PostgresSqliteProxy:
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return self._conn.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def test_record_delivery_upserts_by_landing_path(tmp_path):
    store = AzureExportStore(db_path=tmp_path / "azure_export_deliveries.db")
    landing_path = tmp_path / "landing-zone" / "focus" / "subscription__sub-123" / "delivery_date=2026-03-20" / "run=run-001" / "raw"
    manifest_path = landing_path.parent / "manifest"

    first = store.record_delivery(
        ExportDeliveryMetadata(
            dataset="focus",
            scope_key="subscription__sub-123",
            delivery_date=date(2026, 3, 20),
            run_id="run-001",
            landing_path=landing_path,
            manifest_path=manifest_path,
            parse_status="discovered",
            row_count=10,
        )
    )

    second = store.record_delivery(
        ExportDeliveryMetadata(
            dataset="focus",
            scope_key="subscription__sub-123",
            delivery_date=date(2026, 3, 20),
            run_id="run-001",
            landing_path=landing_path,
            manifest_path=manifest_path,
            parse_status="parsed",
            row_count=42,
            parser_version="focus-csv-v1",
            schema_signature="sha256:abc123",
            schema_compatible=True,
            delivery_id="different-id",
        )
    )

    assert first["delivery_id"] == second["delivery_id"]
    assert second["parse_status"] == "parsed"
    assert second["row_count"] == 42

    fetched = store.get_delivery(second["delivery_id"])
    assert fetched is not None
    assert fetched["landing_path"] == str(landing_path)
    assert fetched["parser_version"] == "focus-csv-v1"
    assert fetched["schema_signature"] == "sha256:abc123"
    assert fetched["schema_compatible"] is True
    assert store.get_delivery_by_path(landing_path)["delivery_id"] == second["delivery_id"]

    listed = store.list_deliveries(dataset="focus", scope_key="subscription__sub-123", parse_status="parsed")
    assert len(listed) == 1
    assert listed[0]["delivery_id"] == second["delivery_id"]
    manifest = store.get_manifest(second["delivery_key"])
    assert manifest is not None
    assert manifest["parser_version"] == "focus-csv-v1"
    assert manifest["schema_signature"] == "sha256:abc123"
    assert manifest["schema_compatible"] is True


def test_update_delivery_rejects_unknown_fields_and_validates_status(tmp_path):
    store = AzureExportStore(db_path=tmp_path / "azure_export_deliveries.db")
    landing_path = tmp_path / "landing-zone" / "focus" / "management_group__contoso" / "delivery_date=2026-03-20" / "run=run-002" / "raw"

    created = store.record_delivery(
        {
            "dataset": "focus",
            "scope_key": "management_group__contoso",
            "delivery_date": "2026-03-20",
            "run_id": "run-002",
            "landing_path": landing_path,
        }
    )

    updated = store.update_delivery(
        created["delivery_id"],
        parse_status="failed",
        row_count=0,
        error_message="missing column",
        parser_version="focus-csv-v1",
        schema_signature="sha256:def456",
        schema_compatible=False,
    )

    assert updated is not None
    assert updated["parse_status"] == "failed"
    assert updated["error_message"] == "missing column"
    assert updated["parser_version"] == "focus-csv-v1"
    assert updated["schema_signature"] == "sha256:def456"
    assert updated["schema_compatible"] is False

    with pytest.raises(ValueError, match="Unsupported delivery field"):
        store.update_delivery(created["delivery_id"], not_a_field="value")

    with pytest.raises(ValueError, match="Unsupported parse status"):
        store.update_delivery(created["delivery_id"], parse_status="unknown")


def test_get_delivery_logs_invalid_summary_json_and_falls_back_to_empty_dict(tmp_path, caplog):
    store = AzureExportStore(db_path=tmp_path / "azure_export_deliveries.db")
    landing_path = tmp_path / "landing-zone" / "focus" / "subscription__sub-123" / "delivery_date=2026-03-20" / "run=run-003" / "raw"

    created = store.record_delivery(
        {
            "dataset": "focus",
            "scope_key": "subscription__sub-123",
            "delivery_date": "2026-03-20",
            "run_id": "run-003",
            "landing_path": landing_path,
            "summary": {"ok": True},
        }
    )

    with sqlite3.connect(store._db_path) as conn:
        conn.execute(
            "UPDATE export_deliveries SET summary_json = ? WHERE delivery_id = ?",
            ("{not valid json", created["delivery_id"]),
        )
        conn.commit()

    with caplog.at_level(logging.ERROR):
        fetched = store.get_delivery(created["delivery_id"])

    assert fetched is not None
    assert fetched["summary"] == {}
    assert any(
        f"Failed to decode summary_json for delivery {created['delivery_id']}" in record.getMessage()
        for record in caplog.records
    )


def test_postgres_mode_backfills_and_persists_export_records(tmp_path, monkeypatch):
    legacy_db_path = tmp_path / "azure_export_deliveries.db"
    postgres_db_path = tmp_path / "azure_export_deliveries_postgres.db"

    legacy_store = AzureExportStore(db_path=legacy_db_path)
    legacy_store.record_delivery(
        {
            "delivery_id": "legacy-delivery",
            "dataset": "focus",
            "scope_key": "subscription__sub-123",
            "delivery_date": "2026-03-20",
            "run_id": "run-001",
            "delivery_key": "legacy-key",
            "landing_path": tmp_path / "landing" / "legacy",
            "summary": {"legacy": True},
            "parse_status": "parsed",
        }
    )
    legacy_store.record_stage_model("legacy-key", {"rows": 12})
    legacy_store.record_quarantine({"delivery_key": "legacy-key"}, "bad payload")

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(azure_export_store_module, "postgres_enabled", lambda: True)
    monkeypatch.setattr(azure_export_store_module, "ensure_postgres_schema", lambda: None)

    def fake_connect_postgres(*, row_factory=sqlite3.Row):
        conn = sqlite3.connect(postgres_db_path)
        conn.row_factory = row_factory
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
                parser_version TEXT NOT NULL DEFAULT '',
                schema_signature TEXT NOT NULL DEFAULT '',
                schema_compatible INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
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
        return _PostgresSqliteProxy(conn)

    monkeypatch.setattr(azure_export_store_module, "connect_postgres", fake_connect_postgres)

    store = AzureExportStore()

    delivery = store.get_delivery("legacy-delivery")
    assert delivery is not None
    assert delivery["parse_status"] == "parsed"
    assert delivery["summary"] == {"legacy": True}
    assert store.get_stage_model("legacy-key") == {"rows": 12}
    assert store.get_quarantine("legacy-key") is not None

    recorded = store.record_delivery(
        {
            "dataset": "focus",
            "scope_key": "subscription__sub-456",
            "delivery_date": "2026-03-21",
            "run_id": "run-002",
            "delivery_key": "new-key",
            "landing_path": tmp_path / "landing" / "new",
            "parse_status": "staged",
        }
    )
    assert recorded["delivery_key"] == "new-key"


def test_explicit_db_path_stays_on_sqlite_even_when_postgres_is_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(azure_export_store_module, "postgres_enabled", lambda: True)

    def fail_connect_postgres(*args, **kwargs):
        raise AssertionError("connect_postgres should not be used when db_path is explicit")

    monkeypatch.setattr(azure_export_store_module, "connect_postgres", fail_connect_postgres)

    store = AzureExportStore(db_path=tmp_path / "azure_export_deliveries.db")
    created = store.record_delivery(
        {
            "dataset": "focus",
            "scope_key": "subscription__sub-123",
            "delivery_date": "2026-03-20",
            "run_id": "run-003",
            "delivery_key": "sqlite-key",
            "landing_path": tmp_path / "landing" / "sqlite",
        }
    )

    assert created["delivery_key"] == "sqlite-key"
