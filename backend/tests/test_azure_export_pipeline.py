from __future__ import annotations

import json
from pathlib import Path

import pytest

from azure_export_pipeline import AzureExportPipeline
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


def _write_delivery_parts(
    root: Path,
    *,
    dataset: str,
    scope_key: str,
    delivery_date: str,
    run_id: str,
    files: dict[str, str],
) -> tuple[Path, Path]:
    raw_dir = root / dataset / scope_key / f"delivery_date={delivery_date}" / f"run={run_id}" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for csv_name, content in files.items():
        (raw_dir / csv_name).write_text(content, encoding="utf-8")
    return raw_dir, raw_dir.parent


def _valid_csv() -> str:
    return (
        "UsageDate,ServiceName,SubscriptionName,ResourceGroupName,ResourceId,BillingCurrencyCode,"
        "CostInBillingCurrency,AmortizedCostInBillingCurrency,ChargeType,MeterCategory,ConsumedService\n"
        "2026-03-18,Compute,Prod Subscription,rg-app,/subscriptions/sub-prod/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-01,USD,10.00,8.00,Usage,Compute,Microsoft.Compute\n"
        "2026-03-18,Storage,Prod Subscription,rg-app,/subscriptions/sub-prod/resourceGroups/rg-app/providers/Microsoft.Storage/storageAccounts/st01,USD,5.00,5.00,Usage,Storage,Microsoft.Storage\n"
        "2026-03-19,Compute,Dev Subscription,rg-dev,/subscriptions/sub-dev/resourceGroups/rg-dev/providers/Microsoft.Compute/virtualMachines/vm-02,USD,7.50,6.50,Usage,Compute,Microsoft.Compute\n"
        "2026-03-19,Network,Dev Subscription,rg-net,/subscriptions/sub-dev/resourceGroups/rg-net/providers/Microsoft.Network/publicIPAddresses/pip-01,USD,3.00,3.00,Usage,Network,Microsoft.Network\n"
    )


def _invalid_csv() -> str:
    return (
        "UsageDate,ServiceName,SubscriptionName,ResourceGroupName,ResourceId,BillingCurrencyCode,ChargeType\n"
        "2026-03-18,Compute,Prod Subscription,rg-app,/subscriptions/sub-prod/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-01,USD,Usage\n"
    )


def _fallback_csv_rows() -> str:
    return (
        "UsageDate,ConsumedService,SubscriptionId,ResourceGroupName,Currency,ActualCost,AmortizedCost,ChargeType,MeterCategory\n"
        "2026-03-18,Microsoft.Compute,sub-prod,rg-app,USD,10.00,8.00,Usage,Compute\n"
        "2026-03-19,Microsoft.Storage,sub-prod,rg-app,USD,5.00,5.00,Usage,Storage\n"
    )


def _price_sheet_csv() -> str:
    return (
        "MeterId,MeterName,MeterCategory,MeterSubCategory,MeterRegion,ProductName,ProductId,SkuId,SkuName,ServiceFamily,PriceType,Term,UnitOfMeasure,UnitPrice,MarketPrice,BasePrice,CurrencyCode,EffectiveStartDate,EffectiveEndDate\n"
        "meter-001,Standard D2s v5 Hours,Virtual Machines,General Purpose,eastus,Virtual Machines,prod-001,sku-001,Standard_D2s_v5,Compute,consumption,,1 Hour,0.20,0.25,0.20,USD,2026-03-01,2026-03-31\n"
    )


def test_pipeline_discovers_ingests_and_persists_artifacts(tmp_path):
    landing_root = tmp_path / "landing-zone"
    staging_root = tmp_path / "staging"
    quarantine_root = tmp_path / "quarantine"
    store = AzureExportStore(db_path=tmp_path / "azure_export_deliveries.db")

    valid_source = _write_delivery(
        landing_root,
        dataset="focus",
        scope_key="subscription__sub-123",
        delivery_date="2026-03-20",
        run_id="run-001",
        csv_name="focus_daily.csv",
        content=_valid_csv(),
    )
    invalid_source = _write_delivery(
        landing_root,
        dataset="focus",
        scope_key="subscription__sub-456",
        delivery_date="2026-03-21",
        run_id="run-002",
        csv_name="focus_bad.csv",
        content=_invalid_csv(),
    )

    pipeline = AzureExportPipeline(
        landing_root,
        store=store,
        staging_root=staging_root,
        quarantine_root=quarantine_root,
    )

    discovered = pipeline.discover_deliveries()
    assert [delivery.delivery_key for delivery in discovered] == [
        str(valid_source.parent),
        str(invalid_source.parent),
    ]

    results = pipeline.sync()
    assert len(results) == 2
    assert {result.manifest["parse_status"] for result in results} == {"parsed", "quarantined"}

    staged_file = staging_root / "focus" / "subscription__sub-123" / "delivery_date=2026-03-20" / "run=run-001" / "staged.json"
    quarantine_file = quarantine_root / "focus" / "subscription__sub-456" / "delivery_date=2026-03-21" / "run=run-002" / "quarantine.json"
    assert staged_file.exists()
    assert quarantine_file.exists()

    staged_model = json.loads(staged_file.read_text(encoding="utf-8"))
    assert staged_model["summary"]["row_count"] == 4
    assert staged_model["summary"]["actual_cost_total"] == pytest.approx(25.5)

    quarantine_payload = json.loads(quarantine_file.read_text(encoding="utf-8"))
    assert quarantine_payload["manifest"]["parse_status"] == "quarantined"
    assert (quarantine_root / "focus" / "subscription__sub-456" / "delivery_date=2026-03-21" / "run=run-002" / "payload.csv").exists()

    valid_row = store.get_delivery_by_path(valid_source.parent)
    invalid_row = store.get_delivery_by_path(invalid_source.parent)
    assert valid_row is not None and valid_row["parse_status"] == "parsed"
    assert invalid_row is not None and invalid_row["parse_status"] == "quarantined"

    summary = pipeline.health_summary()
    assert summary["delivery_count"] == 2
    assert summary["parsed_count"] == 1
    assert summary["quarantined_count"] == 1
    assert summary["staged_snapshot_count"] == 1
    assert summary["quarantine_artifact_count"] == 1
    assert summary["latest_delivery"]["landing_path"] in {str(valid_source.parent), str(invalid_source.parent)}


def test_pipeline_reprocesses_quarantined_delivery_after_input_is_fixed(tmp_path):
    landing_root = tmp_path / "landing-zone"
    store = AzureExportStore(db_path=tmp_path / "azure_export_deliveries.db")
    raw_dir, delivery_dir = _write_delivery_parts(
        landing_root,
        dataset="focus",
        scope_key="subscription__sub-123",
        delivery_date="2026-03-20",
        run_id="run-001",
        files={"focus_bad.csv": _invalid_csv()},
    )

    pipeline = AzureExportPipeline(landing_root, store=store, staging_root=tmp_path / "staging", quarantine_root=tmp_path / "quarantine")

    first_results = pipeline.sync()
    assert len(first_results) == 1
    assert first_results[0].manifest["parse_status"] == "quarantined"

    (raw_dir / "focus_bad.csv").write_text(_fallback_csv_rows(), encoding="utf-8")

    second_results = pipeline.sync()

    assert len(second_results) == 1
    assert second_results[0].manifest["parse_status"] == "parsed"
    assert store.get_delivery_by_path(raw_dir)["parse_status"] == "parsed"
    assert pipeline.health_summary()["parsed_count"] == 1


def test_pipeline_combines_multiple_csv_files_in_one_delivery(tmp_path):
    landing_root = tmp_path / "landing-zone"
    staging_root = tmp_path / "staging"
    quarantine_root = tmp_path / "quarantine"
    store = AzureExportStore(db_path=tmp_path / "azure_export_deliveries.db")
    raw_dir, delivery_dir = _write_delivery_parts(
        landing_root,
        dataset="focus",
        scope_key="subscription__sub-123",
        delivery_date="2026-03-20",
        run_id="run-001",
        files={
            "focus-part-1.csv": (
                "UsageDate,ServiceName,SubscriptionName,ResourceGroupName,ResourceId,BillingCurrencyCode,"
                "CostInBillingCurrency,AmortizedCostInBillingCurrency,ChargeType,MeterCategory,ConsumedService\n"
                "2026-03-18,Compute,Prod Subscription,rg-app,/subscriptions/sub-prod/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-01,USD,10.00,8.00,Usage,Compute,Microsoft.Compute\n"
                "2026-03-18,Storage,Prod Subscription,rg-app,/subscriptions/sub-prod/resourceGroups/rg-app/providers/Microsoft.Storage/storageAccounts/st01,USD,5.00,5.00,Usage,Storage,Microsoft.Storage\n"
            ),
            "focus-part-2.csv": (
                "UsageDate,ServiceName,SubscriptionName,ResourceGroupName,ResourceId,BillingCurrencyCode,"
                "CostInBillingCurrency,AmortizedCostInBillingCurrency,ChargeType,MeterCategory,ConsumedService\n"
                "2026-03-19,Compute,Dev Subscription,rg-dev,/subscriptions/sub-dev/resourceGroups/rg-dev/providers/Microsoft.Compute/virtualMachines/vm-02,USD,7.50,6.50,Usage,Compute,Microsoft.Compute\n"
                "2026-03-19,Network,Dev Subscription,rg-net,/subscriptions/sub-dev/resourceGroups/rg-net/providers/Microsoft.Network/publicIPAddresses/pip-01,USD,3.00,3.00,Usage,Network,Microsoft.Network\n"
            ),
        },
    )

    pipeline = AzureExportPipeline(
        landing_root,
        store=store,
        staging_root=staging_root,
        quarantine_root=quarantine_root,
    )

    discovered = pipeline.discover_deliveries()
    assert len(discovered) == 1
    assert len(discovered[0].source_files) == 2

    results = pipeline.sync()

    assert len(results) == 1
    assert results[0].manifest["row_count"] == 4
    staged_file = staging_root / "focus" / "subscription__sub-123" / "delivery_date=2026-03-20" / "run=run-001" / "staged.json"
    assert staged_file.exists()
    staged_model = json.loads(staged_file.read_text(encoding="utf-8"))
    assert staged_model["summary"]["row_count"] == 4
    assert staged_model["summary"]["actual_cost_total"] == pytest.approx(25.5)
    assert store.get_delivery_by_path(raw_dir)["row_count"] == 4


def test_pipeline_sync_is_idempotent_for_already_ingested_deliveries(tmp_path):
    landing_root = tmp_path / "landing-zone"
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

    pipeline = AzureExportPipeline(landing_root, store=store, staging_root=tmp_path / "staging", quarantine_root=tmp_path / "quarantine")

    first_results = pipeline.sync()
    second_results = pipeline.sync()

    assert len(first_results) == 1
    assert len(second_results) == 0
    assert pipeline.health_summary()["delivery_count"] == 1


def test_pipeline_ingests_non_focus_auxiliary_dataset(tmp_path):
    landing_root = tmp_path / "landing-zone"
    staging_root = tmp_path / "staging"
    quarantine_root = tmp_path / "quarantine"
    store = AzureExportStore(db_path=tmp_path / "azure_export_deliveries.db")

    _write_delivery(
        landing_root,
        dataset="price-sheet",
        scope_key="subscription__sub-123",
        delivery_date="2026-03-20",
        run_id="run-001",
        csv_name="price_sheet.csv",
        content=_price_sheet_csv(),
    )

    pipeline = AzureExportPipeline(
        landing_root,
        store=store,
        staging_root=staging_root,
        quarantine_root=quarantine_root,
    )

    results = pipeline.sync()

    assert len(results) == 1
    assert results[0].manifest["parse_status"] == "parsed"
    assert results[0].manifest["parser_version"] == "price-sheet-csv-v1"
    staged_file = staging_root / "price-sheet" / "subscription__sub-123" / "delivery_date=2026-03-20" / "run=run-001" / "staged.json"
    assert staged_file.exists()
