"""Async-friendly runtime service for Azure cost export ingestion."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from azure_export_pipeline import AzureExportPipeline

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _normalize_dataset_name(value: Any) -> str:
    return str(value or "").strip().lower()


class AzureCostExportService:
    """Manage Azure export ingestion as a small background service."""

    def __init__(
        self,
        pipeline: AzureExportPipeline | Any | None = None,
        *,
        root: str | Path | None = None,
        store: Any | None = None,
        staging_root: str | Path | None = None,
        quarantine_root: str | Path | None = None,
        enabled: bool = True,
        poll_interval_seconds: float = 60.0,
        configured_datasets: list[str] | tuple[str, ...] | None = None,
        expected_cadence_hours: int = 24,
    ) -> None:
        if pipeline is None and root is not None:
            pipeline = AzureExportPipeline(
                root,
                store=store,
                staging_root=staging_root,
                quarantine_root=quarantine_root,
            )

        self._pipeline = pipeline
        self._enabled = bool(enabled)
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._configured_datasets = [
            dataset for dataset in (_normalize_dataset_name(item) for item in (configured_datasets or [])) if dataset
        ]
        self._expected_cadence_hours = max(int(expected_cadence_hours or 0), 0)
        self._state_lock = threading.Lock()
        self._sync_lock = asyncio.Lock()
        self._background_task: asyncio.Task[None] | None = None
        self._refreshing = False
        self._last_sync_started_at: str | None = None
        self._last_sync_finished_at: str | None = None
        self._last_success_at: str | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_health_summary: dict[str, Any] = self._load_health_summary()

    def _load_health_summary(self) -> dict[str, Any]:
        health_method = getattr(self._pipeline, "health_summary", None)
        base = {}
        if callable(health_method):
            try:
                base = _to_dict(health_method())
            except Exception:  # pragma: no cover - defensive only
                logger.exception("Azure cost export health summary failed during snapshot")
                base = {}
        return self._evaluate_health(base)

    def _list_delivery_rows(self) -> list[dict[str, Any]]:
        store = getattr(self._pipeline, "store", None)
        list_deliveries = getattr(store, "list_deliveries", None)
        if not callable(list_deliveries):
            return []
        try:
            rows = list_deliveries()
        except Exception:  # pragma: no cover - defensive only
            logger.exception("Azure cost export delivery listing failed during snapshot")
            return []
        normalized: list[dict[str, Any]] = []
        for row in rows or []:
            if isinstance(row, Mapping):
                normalized.append(dict(row))
        return normalized

    def _evaluate_health(self, base_summary: Mapping[str, Any]) -> dict[str, Any]:
        summary = dict(base_summary)
        deliveries = self._list_delivery_rows()
        now = datetime.now(timezone.utc)
        expected_cadence = self._expected_cadence_hours
        configured_datasets = list(self._configured_datasets)
        observed_datasets = sorted(
            {
                dataset
                for dataset in (_normalize_dataset_name(row.get("dataset")) for row in deliveries)
                if dataset
            }
        )
        dataset_names = configured_datasets or observed_datasets
        dataset_health: list[dict[str, Any]] = []
        any_stale = False
        any_waiting = False
        any_error = False

        for dataset_name in dataset_names:
            dataset_rows = [row for row in deliveries if _normalize_dataset_name(row.get("dataset")) == dataset_name]
            latest_delivery = None
            latest_delivery_time = None
            latest_parsed_time = None
            parsed_count = 0
            quarantined_count = 0
            status_counts: Counter[str] = Counter()

            for row in dataset_rows:
                status = str(row.get("parse_status") or "unknown")
                status_counts[status] += 1
                if status == "parsed":
                    parsed_count += 1
                if status == "quarantined":
                    quarantined_count += 1

                delivery_time = _parse_timestamp(row.get("parsed_at")) or _parse_timestamp(row.get("discovered_at"))
                if delivery_time is not None and (latest_delivery_time is None or delivery_time > latest_delivery_time):
                    latest_delivery_time = delivery_time
                    latest_delivery = row

                parsed_time = _parse_timestamp(row.get("parsed_at")) if status == "parsed" else None
                if parsed_time is not None and (latest_parsed_time is None or parsed_time > latest_parsed_time):
                    latest_parsed_time = parsed_time

            stale = False
            state = "waiting"
            reason = "No deliveries recorded yet"
            reference_time = latest_parsed_time or latest_delivery_time
            if dataset_rows:
                if expected_cadence > 0 and reference_time is not None:
                    stale = now - reference_time > timedelta(hours=expected_cadence)
                if stale:
                    state = "stale"
                    reason = (
                        f"No successful delivery within {expected_cadence}h cadence"
                        if latest_parsed_time is not None
                        else f"No recent delivery within {expected_cadence}h cadence"
                    )
                elif parsed_count > 0:
                    state = "healthy"
                    reason = "Recent parsed delivery available"
                elif quarantined_count > 0:
                    state = "error"
                    reason = "Latest deliveries are quarantined"
                else:
                    state = "waiting"
                    reason = "Deliveries discovered but none parsed yet"

            any_stale = any_stale or stale
            any_waiting = any_waiting or state == "waiting"
            any_error = any_error or state == "error"
            dataset_health.append(
                {
                    "dataset": dataset_name,
                    "delivery_count": len(dataset_rows),
                    "parsed_count": parsed_count,
                    "quarantined_count": quarantined_count,
                    "last_delivery_at": latest_delivery_time.isoformat() if latest_delivery_time else None,
                    "last_parsed_at": latest_parsed_time.isoformat() if latest_parsed_time else None,
                    "latest_status": str(latest_delivery.get("parse_status") or "") if latest_delivery else None,
                    "expected_cadence_hours": expected_cadence,
                    "stale": stale,
                    "state": state,
                    "reason": reason,
                    "status_counts": dict(status_counts),
                }
            )

        overall_state = "healthy"
        overall_reason = "Export deliveries are within expected cadence"
        if self._last_error:
            overall_state = "error"
            overall_reason = self._last_error
        elif any_error:
            overall_state = "error"
            overall_reason = "One or more datasets are quarantined without a parsed recovery"
        elif any_stale:
            overall_state = "stale"
            overall_reason = f"One or more datasets missed the {expected_cadence}h cadence"
        elif dataset_health and any_waiting:
            overall_state = "waiting"
            overall_reason = "Waiting for the first successful export delivery"
        elif not dataset_health:
            overall_state = "waiting"
            overall_reason = "No datasets configured or observed yet"

        summary["configured_datasets"] = configured_datasets
        summary["observed_datasets"] = observed_datasets
        summary["expected_cadence_hours"] = expected_cadence
        summary["dataset_health"] = dataset_health
        summary["stale"] = any_stale
        summary["state"] = overall_state
        summary["reason"] = overall_reason
        return summary

    def _sync_result_summary(self, result: Any) -> dict[str, Any]:
        if result is None:
            return {"result_count": 0, "result_type": "NoneType"}

        if isinstance(result, list):
            status_counts: Counter[str] = Counter()
            for item in result:
                manifest: Any = None
                if isinstance(item, Mapping):
                    manifest = item
                else:
                    manifest = getattr(item, "manifest", None)
                if isinstance(manifest, Mapping):
                    status = str(manifest.get("parse_status") or "unknown")
                else:
                    status = type(item).__name__
                status_counts[status] += 1
            return {
                "result_count": len(result),
                "result_type": "list",
                "parse_status_counts": dict(status_counts),
            }

        return {
            "result_count": 1,
            "result_type": type(result).__name__,
        }

    def _set_state(self, **fields: Any) -> None:
        with self._state_lock:
            for key, value in fields.items():
                setattr(self, key, value)

    def _status_snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            status = {
                "enabled": self._enabled,
                "configured": self._pipeline is not None,
                "running": bool(self._background_task and not self._background_task.done()),
                "refreshing": self._refreshing,
                "poll_interval_seconds": self._poll_interval_seconds,
                "last_sync_started_at": self._last_sync_started_at,
                "last_sync_finished_at": self._last_sync_finished_at,
                "last_success_at": self._last_success_at,
                "last_error": self._last_error,
                "last_result": dict(self._last_result or {}),
                "health": dict(self._last_health_summary),
            }
        health = status["health"]
        for key in ("delivery_count", "parsed_count", "quarantined_count", "staged_snapshot_count", "quarantine_artifact_count"):
            health.setdefault(key, 0)
        health.setdefault("latest_delivery", None)
        health.setdefault("status_counts", {})
        health.setdefault("configured_datasets", list(self._configured_datasets))
        health.setdefault("observed_datasets", [])
        health.setdefault("expected_cadence_hours", self._expected_cadence_hours)
        health.setdefault("dataset_health", [])
        health.setdefault("stale", False)
        health.setdefault("state", "disabled" if not self._enabled else "waiting")
        health.setdefault("reason", "Service is disabled" if not self._enabled else "Waiting for export sync")
        return status

    def status(self) -> dict[str, Any]:
        """Return a compact payload for a route or UI."""

        return self._status_snapshot()

    async def start(self) -> bool:
        """Start the background sync loop if the service is enabled."""

        if not self._enabled or self._pipeline is None or self._poll_interval_seconds <= 0:
            return False

        with self._state_lock:
            if self._background_task and not self._background_task.done():
                return False
            loop = asyncio.get_running_loop()
            self._background_task = loop.create_task(self._background_loop())
            return True

    async def stop(self) -> bool:
        """Stop the background sync loop if it is running."""

        with self._state_lock:
            task = self._background_task
            self._background_task = None

        if task is None:
            return False

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    async def run_once(self) -> dict[str, Any]:
        """Run one sync cycle in an executor-friendly way."""

        if not self._enabled or self._pipeline is None:
            return self.status()

        async with self._sync_lock:
            started_at = _utcnow()
            self._set_state(
                _refreshing=True,
                _last_sync_started_at=started_at,
                _last_error=None,
            )

            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, self._pipeline.sync)
            except Exception as exc:
                finished_at = _utcnow()
                self._set_state(
                    _refreshing=False,
                    _last_sync_finished_at=finished_at,
                    _last_error=str(exc),
                )
                raise

            finished_at = _utcnow()
            health = self._load_health_summary()
            self._set_state(
                _refreshing=False,
                _last_sync_finished_at=finished_at,
                _last_success_at=finished_at,
                _last_error=None,
                _last_result=self._sync_result_summary(result),
                _last_health_summary=health or self._last_health_summary,
            )
            return self.status()

    async def _background_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Azure cost export sync failed")
            await asyncio.sleep(self._poll_interval_seconds)
