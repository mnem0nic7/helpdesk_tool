from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from azure_cost_export_service import AzureCostExportService
from azure_export_store import AzureExportStore


def _write_delivery(
    root: Path,
    *,
    dataset: str,
    scope_key: str,
    delivery_date: str,
    run_id: str,
    csv_name: str,
    content: str,
) -> Path:
    raw_dir = root / dataset / scope_key / f"delivery_date={delivery_date}" / f"run={run_id}" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    source_file = raw_dir / csv_name
    source_file.write_text(content, encoding="utf-8")
    return source_file


def _valid_csv() -> str:
    return (
        "UsageDate,ServiceName,SubscriptionName,ResourceGroupName,ResourceId,BillingCurrencyCode,"
        "CostInBillingCurrency,AmortizedCostInBillingCurrency,ChargeType,MeterCategory,ConsumedService\n"
        "2026-03-18,Compute,Prod Subscription,rg-app,/subscriptions/sub-prod/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-01,USD,10.00,8.00,Usage,Compute,Microsoft.Compute\n"
    )


class _FakePipeline:
    def __init__(
        self,
        *,
        result: list[dict] | None = None,
        health_factory=None,
        boom: Exception | None = None,
        deliveries: list[dict] | None = None,
    ) -> None:
        self.result = result if result is not None else []
        self.health_factory = health_factory
        self.boom = boom
        self.sync_calls = 0
        self.sync_thread_names: list[str] = []
        self.store = _FakeStore(deliveries or [])

    def sync(self):
        self.sync_calls += 1
        self.sync_thread_names.append(threading.current_thread().name)
        if self.boom is not None:
            raise self.boom
        return list(self.result)

    def health_summary(self):
        if callable(self.health_factory):
            return dict(self.health_factory())
        if isinstance(self.health_factory, dict):
            return dict(self.health_factory)
        return {
            "delivery_count": self.sync_calls,
            "parsed_count": self.sync_calls,
            "quarantined_count": 0,
            "staged_snapshot_count": 0,
            "quarantine_artifact_count": 0,
            "status_counts": {"parsed": self.sync_calls},
            "latest_delivery": None,
        }


class _FakeStore:
    def __init__(self, deliveries: list[dict]) -> None:
        self._deliveries = [dict(row) for row in deliveries]

    def list_deliveries(self) -> list[dict]:
        return [dict(row) for row in self._deliveries]


@pytest.mark.asyncio
async def test_service_can_wrap_a_real_pipeline_from_root(tmp_path):
    landing_root = tmp_path / "landing-zone"
    staging_root = tmp_path / "staging"
    quarantine_root = tmp_path / "quarantine"
    store = AzureExportStore(db_path=tmp_path / "azure_export_deliveries.db")
    _write_delivery(
        landing_root,
        dataset="focus",
        scope_key="subscription__sub-123",
        delivery_date="2026-03-20",
        run_id="run-001",
        csv_name="focus_daily.csv",
        content=_valid_csv(),
    )

    service = AzureCostExportService(
        root=landing_root,
        store=store,
        staging_root=staging_root,
        quarantine_root=quarantine_root,
        poll_interval_seconds=0.01,
        configured_datasets=["focus"],
        expected_cadence_hours=24,
    )

    status = await service.run_once()

    assert status["enabled"] is True
    assert status["configured"] is True
    assert status["refreshing"] is False
    assert status["last_error"] is None
    assert status["last_result"]["result_count"] == 1
    assert status["health"]["delivery_count"] == 1
    assert status["health"]["parsed_count"] == 1
    assert status["health"]["state"] == "healthy"
    assert status["health"]["configured_datasets"] == ["focus"]
    assert status["health"]["dataset_health"][0]["dataset"] == "focus"
    assert (staging_root / "focus" / "subscription__sub-123" / "delivery_date=2026-03-20" / "run=run-001" / "staged.json").exists()


@pytest.mark.asyncio
async def test_disabled_service_is_a_noop(tmp_path):
    pipeline = _FakePipeline(health_factory={"delivery_count": 7, "parsed_count": 7})
    service = AzureCostExportService(
        pipeline=pipeline,
        enabled=False,
        poll_interval_seconds=0.01,
        configured_datasets=["focus"],
        expected_cadence_hours=24,
    )

    assert await service.start() is False
    status = await service.run_once()

    assert pipeline.sync_calls == 0
    assert status["enabled"] is False
    assert status["configured"] is True
    assert status["running"] is False
    assert status["refreshing"] is False
    assert status["health"]["configured_datasets"] == ["focus"]
    assert status["health"]["expected_cadence_hours"] == 24


@pytest.mark.asyncio
async def test_run_once_uses_executor_and_updates_status():
    pipeline = _FakePipeline(result=[{"parse_status": "parsed"}], health_factory={"delivery_count": 1, "parsed_count": 1})
    service = AzureCostExportService(pipeline=pipeline, enabled=True, poll_interval_seconds=0.01)
    main_thread = threading.current_thread().name

    status = await service.run_once()

    assert pipeline.sync_calls == 1
    assert pipeline.sync_thread_names[0] != main_thread
    assert status["last_error"] is None
    assert status["last_result"]["result_count"] == 1
    assert status["last_result"]["parse_status_counts"] == {"parsed": 1}
    assert status["health"]["delivery_count"] == 1


@pytest.mark.asyncio
async def test_background_loop_can_start_and_stop():
    pipeline = _FakePipeline()
    service = AzureCostExportService(pipeline=pipeline, enabled=True, poll_interval_seconds=0.01)

    assert await service.start() is True
    await asyncio.sleep(0.05)
    assert await service.stop() is True

    assert pipeline.sync_calls >= 2
    assert service.status()["running"] is False


@pytest.mark.asyncio
async def test_run_once_records_last_error_when_pipeline_fails():
    pipeline = _FakePipeline(boom=RuntimeError("boom"))
    service = AzureCostExportService(pipeline=pipeline, enabled=True, poll_interval_seconds=0.01)

    with pytest.raises(RuntimeError, match="boom"):
        await service.run_once()

    status = service.status()
    assert pipeline.sync_calls == 1
    assert status["last_error"] == "boom"
    assert status["refreshing"] is False
    assert status["last_success_at"] is None


def test_status_marks_dataset_stale_when_latest_delivery_misses_expected_cadence():
    stale_time = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    pipeline = _FakePipeline(
        deliveries=[
            {
                "dataset": "focus",
                "parse_status": "parsed",
                "discovered_at": stale_time,
                "parsed_at": stale_time,
                "landing_path": "/tmp/focus/raw",
            }
        ]
    )
    service = AzureCostExportService(
        pipeline=pipeline,
        enabled=True,
        poll_interval_seconds=60,
        configured_datasets=["FOCUS"],
        expected_cadence_hours=24,
    )

    status = service.status()

    assert status["health"]["stale"] is True
    assert status["health"]["state"] == "stale"
    assert status["health"]["dataset_health"][0]["dataset"] == "focus"
    assert status["health"]["dataset_health"][0]["stale"] is True


def test_status_reports_waiting_for_first_delivery_for_configured_dataset():
    pipeline = _FakePipeline(deliveries=[])
    service = AzureCostExportService(
        pipeline=pipeline,
        enabled=True,
        poll_interval_seconds=60,
        configured_datasets=["FOCUS"],
        expected_cadence_hours=24,
    )

    status = service.status()

    assert status["health"]["state"] == "waiting"
    assert status["health"]["dataset_health"][0]["dataset"] == "focus"
    assert status["health"]["dataset_health"][0]["state"] == "waiting"
