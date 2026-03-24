"""Runtime singleton for local Azure FinOps analytics."""

from __future__ import annotations

import logging
from pathlib import Path

from azure_export_store import AzureExportStore
from azure_finops_service import AzureFinOpsService
from config import (
    AZURE_COST_EXPORT_MANIFEST_DB_PATH,
    AZURE_COST_LOOKBACK_DAYS,
    AZURE_FINOPS_AI_PRICING,
    AZURE_FINOPS_DUCKDB_PATH,
)

logger = logging.getLogger(__name__)


def _build_service() -> AzureFinOpsService:
    service = AzureFinOpsService(
        db_path=AZURE_FINOPS_DUCKDB_PATH,
        default_lookback_days=AZURE_COST_LOOKBACK_DAYS,
        ai_pricing_config=AZURE_FINOPS_AI_PRICING,
    )
    manifest_db_path = Path(AZURE_COST_EXPORT_MANIFEST_DB_PATH)
    if manifest_db_path.exists():
        try:
            service.sync_from_export_store(AzureExportStore(db_path=manifest_db_path))
        except Exception:
            logger.exception("Failed to hydrate local Azure FinOps analytics from export deliveries")
    return service


azure_finops_service = _build_service()
