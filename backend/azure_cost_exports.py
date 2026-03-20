"""Runtime singleton for Azure Cost export ingestion."""

from __future__ import annotations

import logging

from azure_cost_export_service import AzureCostExportService
from azure_export_store import AzureExportStore
from config import (
    AZURE_COST_EXPORT_DATASETS,
    AZURE_COST_EXPORT_EXPECTED_CADENCE_HOURS,
    AZURE_COST_EXPORT_MANIFEST_DB_PATH,
    AZURE_COST_EXPORT_POLL_INTERVAL_MINUTES,
    AZURE_COST_EXPORT_QUARANTINE_DIR,
    AZURE_COST_EXPORT_ROOT,
    AZURE_COST_EXPORT_STAGING_DIR,
    AZURE_COST_EXPORTS_ENABLED,
)

logger = logging.getLogger(__name__)


def _build_service() -> AzureCostExportService:
    poll_interval_seconds = max(AZURE_COST_EXPORT_POLL_INTERVAL_MINUTES, 1) * 60
    configured_datasets = [item.strip() for item in AZURE_COST_EXPORT_DATASETS.split(",") if item.strip()]
    if not AZURE_COST_EXPORTS_ENABLED:
        return AzureCostExportService(
            enabled=False,
            poll_interval_seconds=poll_interval_seconds,
            configured_datasets=configured_datasets,
            expected_cadence_hours=AZURE_COST_EXPORT_EXPECTED_CADENCE_HOURS,
        )

    try:
        store = AzureExportStore(db_path=AZURE_COST_EXPORT_MANIFEST_DB_PATH)
        return AzureCostExportService(
            root=AZURE_COST_EXPORT_ROOT,
            store=store,
            staging_root=AZURE_COST_EXPORT_STAGING_DIR,
            quarantine_root=AZURE_COST_EXPORT_QUARANTINE_DIR,
            enabled=True,
            poll_interval_seconds=poll_interval_seconds,
            configured_datasets=configured_datasets,
            expected_cadence_hours=AZURE_COST_EXPORT_EXPECTED_CADENCE_HOURS,
        )
    except Exception:
        logger.exception("Failed to initialize Azure cost export service")
        return AzureCostExportService(
            enabled=False,
            poll_interval_seconds=poll_interval_seconds,
            configured_datasets=configured_datasets,
            expected_cadence_hours=AZURE_COST_EXPORT_EXPECTED_CADENCE_HOURS,
        )


azure_cost_export_service = _build_service()
