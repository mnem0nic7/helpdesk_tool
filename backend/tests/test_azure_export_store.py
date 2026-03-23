from __future__ import annotations

import logging
import sqlite3
from datetime import date

import pytest

from azure_export_store import AzureExportStore, ExportDeliveryMetadata


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
