from __future__ import annotations

from pathlib import Path

import pytest

from azure_export_ingestor import FocusExportIngestor


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "azure_focus"
AUX_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "azure_auxiliary"


class _FakeFocusStore:
    def __init__(self) -> None:
        self.manifests: dict[str, dict] = {}
        self.stage_models: dict[str, dict] = {}
        self.quarantine: list[tuple[dict, str | bytes]] = []

    def has_delivery(self, delivery_key: str) -> bool:
        return delivery_key in self.manifests

    def record_manifest(self, manifest: dict) -> None:
        self.manifests[str(manifest["delivery_key"])] = dict(manifest)

    def record_stage_model(self, delivery_key: str, staged_model: dict) -> None:
        self.stage_models[delivery_key] = dict(staged_model)

    def record_quarantine(self, manifest: dict, content: str | bytes) -> None:
        self.quarantine.append((dict(manifest), content))

    def get_manifest(self, delivery_key: str) -> dict | None:
        return self.manifests.get(delivery_key)


def test_discover_pending_deliveries_is_sorted_and_idempotent():
    store = _FakeFocusStore()
    store.record_manifest(
        {
            "dataset": "FOCUS",
            "scope": "subscription",
            "path": "exports/2026-03-18/delivery-a.csv",
            "delivery_time": "2026-03-18T08:00:00+00:00",
            "delivery_key": "exports/2026-03-18/delivery-a.csv",
            "parse_status": "parsed",
            "row_count": 4,
            "error_details": "",
            "summary": {},
            "recorded_at": "2026-03-18T08:00:00+00:00",
        }
    )
    ingestor = FocusExportIngestor(store)

    pending = ingestor.discover_pending_deliveries(
        [
            {"path": "exports/2026-03-19/delivery-b.csv", "scope": "subscription", "delivery_time": "2026-03-19T08:00:00+00:00"},
            {"path": "exports/2026-03-18/delivery-a.csv", "scope": "subscription", "delivery_time": "2026-03-18T08:00:00+00:00"},
            {"path": "exports/2026-03-19/delivery-b.csv", "scope": "subscription", "delivery_time": "2026-03-19T08:00:00+00:00"},
            {"path": "exports/2026-03-17/delivery-c.csv", "scope": "subscription", "delivery_time": "2026-03-17T08:00:00+00:00"},
        ]
    )

    assert [delivery.path for delivery in pending] == [
        "exports/2026-03-17/delivery-c.csv",
        "exports/2026-03-19/delivery-b.csv",
    ]


def test_ingest_delivery_records_manifest_and_stage_snapshot():
    store = _FakeFocusStore()
    ingestor = FocusExportIngestor(store)
    content = (FIXTURE_DIR / "focus_daily_sample.csv").read_text(encoding="utf-8")

    result = ingestor.ingest_delivery(
        {
            "dataset": "FOCUS",
            "scope": "management-group",
            "path": "exports/2026-03-20/focus_daily_sample.csv",
            "delivery_time": "2026-03-20T08:00:00+00:00",
            "delivery_key": "exports/2026-03-20/focus_daily_sample.csv",
        },
        content,
    )

    assert result.was_duplicate is False
    assert result.manifest["parse_status"] == "parsed"
    assert result.manifest["row_count"] == 4
    assert result.manifest["parser_version"] == "focus-csv-v1"
    assert result.manifest["schema_signature"].startswith("sha256:")
    assert result.manifest["schema_compatible"] is True
    assert result.manifest["summary"]["actual_cost_total"] == pytest.approx(25.5)
    assert store.get_manifest("exports/2026-03-20/focus_daily_sample.csv") is not None
    assert store.stage_models["exports/2026-03-20/focus_daily_sample.csv"]["summary"]["row_count"] == 4
    assert store.stage_models["exports/2026-03-20/focus_daily_sample.csv"]["parser_version"] == "focus-csv-v1"
    assert store.stage_models["exports/2026-03-20/focus_daily_sample.csv"]["schema_signature"].startswith("sha256:")


def test_ingest_delivery_records_quarantine_manifest_for_malformed_content():
    store = _FakeFocusStore()
    ingestor = FocusExportIngestor(store)
    content = (FIXTURE_DIR / "focus_malformed_missing_cost.csv").read_text(encoding="utf-8")

    result = ingestor.ingest_delivery(
        {
            "dataset": "FOCUS",
            "scope": "subscription",
            "path": "exports/2026-03-20/focus_malformed_missing_cost.csv",
            "delivery_time": "2026-03-20T08:00:00+00:00",
        },
        content,
    )

    assert result.staged_model is None
    assert result.manifest["parse_status"] == "quarantined"
    assert result.manifest["parser_version"] == "focus-csv-v1"
    assert result.manifest["schema_signature"].startswith("sha256:")
    assert result.manifest["schema_compatible"] is False
    assert "missing required columns" in result.manifest["error_details"]
    assert store.get_manifest("exports/2026-03-20/focus_malformed_missing_cost.csv") is not None
    assert store.quarantine


def test_ingest_delivery_retries_quarantined_delivery_after_fix():
    store = _FakeFocusStore()
    ingestor = FocusExportIngestor(store)
    bad_content = (FIXTURE_DIR / "focus_malformed_missing_cost.csv").read_text(encoding="utf-8")
    good_content = (FIXTURE_DIR / "focus_fallback_headers.csv").read_text(encoding="utf-8")
    delivery = {
        "dataset": "FOCUS",
        "scope": "subscription",
        "path": "exports/2026-03-20/focus_retry.csv",
        "delivery_time": "2026-03-20T08:00:00+00:00",
    }

    first = ingestor.ingest_delivery(delivery, bad_content)
    pending_after_quarantine = ingestor.discover_pending_deliveries([delivery])
    second = ingestor.ingest_delivery(delivery, good_content)

    assert first.manifest["parse_status"] == "quarantined"
    assert len(pending_after_quarantine) == 1
    assert second.was_duplicate is False
    assert second.manifest["parse_status"] == "parsed"
    assert second.manifest["schema_compatible"] is True
    assert store.get_manifest("exports/2026-03-20/focus_retry.csv")["parse_status"] == "parsed"
    assert store.stage_models["exports/2026-03-20/focus_retry.csv"]["summary"]["row_count"] == 2


def test_ingest_delivery_returns_existing_manifest_for_duplicate_delivery():
    store = _FakeFocusStore()
    ingestor = FocusExportIngestor(store)
    content = (FIXTURE_DIR / "focus_daily_sample.csv").read_text(encoding="utf-8")

    first = ingestor.ingest_delivery(
        {
            "dataset": "FOCUS",
            "scope": "subscription",
            "path": "exports/2026-03-20/focus_daily_sample.csv",
            "delivery_time": "2026-03-20T08:00:00+00:00",
        },
        content,
    )
    second = ingestor.ingest_delivery(
        {
            "dataset": "FOCUS",
            "scope": "subscription",
            "path": "exports/2026-03-20/focus_daily_sample.csv",
            "delivery_time": "2026-03-20T08:00:00+00:00",
        },
        content,
    )

    assert first.manifest["parse_status"] == "parsed"
    assert second.was_duplicate is True
    assert second.manifest["parse_status"] == "parsed"
    assert len(store.manifests) == 1


def test_ingest_delivery_supports_price_sheet_dataset():
    store = _FakeFocusStore()
    ingestor = FocusExportIngestor(store)
    content = (AUX_FIXTURE_DIR / "price_sheet_sample.csv").read_text(encoding="utf-8")

    result = ingestor.ingest_delivery(
        {
            "dataset": "price-sheet",
            "scope": "subscription",
            "path": "exports/2026-03-20/price_sheet.csv",
            "delivery_time": "2026-03-20T08:00:00+00:00",
        },
        content,
    )

    assert result.manifest["parse_status"] == "parsed"
    assert result.manifest["parser_version"] == "price-sheet-csv-v1"
    assert result.staged_model is not None
    assert result.staged_model["dataset_family"] == "price_sheet"
    assert result.staged_model["summary"]["row_count"] == 2


def test_ingest_delivery_supports_reservation_recommendations_dataset():
    store = _FakeFocusStore()
    ingestor = FocusExportIngestor(store)
    content = (AUX_FIXTURE_DIR / "reservation_recommendations_sample.csv").read_text(encoding="utf-8")

    result = ingestor.ingest_delivery(
        {
            "dataset": "reservation-recommendations",
            "scope": "subscription",
            "path": "exports/2026-03-20/reservation_recommendations.csv",
            "delivery_time": "2026-03-20T08:00:00+00:00",
        },
        content,
    )

    assert result.manifest["parse_status"] == "parsed"
    assert result.manifest["parser_version"] == "reservation-recommendations-csv-v1"
    assert result.staged_model is not None
    assert result.staged_model["dataset_family"] == "reservation_recommendations"
    assert result.staged_model["summary"]["row_count"] == 2
