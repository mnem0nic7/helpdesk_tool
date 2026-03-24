from __future__ import annotations

import json
import sys
from pathlib import Path

from azure_export_pipeline import AzureExportPipeline
from azure_export_store import AzureExportStore
from azure_finops_safe_hooks import AzureFinOpsSafeHookRunner
from azure_finops_service import AzureFinOpsService


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "azure_focus"
AUX_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "azure_auxiliary"


def _example_safe_hook_runner() -> AzureFinOpsSafeHookRunner:
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "azure_finops_safe_hook_echo.py"
    return AzureFinOpsSafeHookRunner(
        {
            "vm_echo": {
                "label": "VM Echo",
                "description": "Preview the VM remediation path.",
                "command": [sys.executable, str(script_path)],
                "allowed_categories": ["compute"],
                "allowed_opportunity_types": ["idle_vm_attached_cost"],
                "default_dry_run": True,
                "allow_apply": False,
            }
        }
    )


def _write_focus_delivery(root: Path, *, run_id: str = "run-001") -> None:
    raw_dir = root / "focus" / "subscription__sub-prod" / "delivery_date=2026-03-20" / f"run={run_id}" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    sample = (FIXTURE_DIR / "focus_daily_sample.csv").read_text(encoding="utf-8")
    (raw_dir / "focus_daily_sample.csv").write_text(sample, encoding="utf-8")


def _write_auxiliary_delivery(root: Path, dataset: str, filename: str, fixture_name: str, *, run_id: str) -> None:
    raw_dir = root / dataset / "subscription__sub-prod" / "delivery_date=2026-03-20" / f"run={run_id}" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    sample = (AUX_FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")
    (raw_dir / filename).write_text(sample, encoding="utf-8")


def _seed_allocation_cost_records(service: AzureFinOpsService) -> None:
    rows = [
        (
            "cost-001",
            "2026-03-20",
            "sub-prod",
            "Prod Subscription",
            "rg-tag",
            "vm-platform-01",
            "/subscriptions/sub-prod/resourceGroups/rg-tag/providers/Microsoft.Compute/virtualMachines/vm-platform-01",
            "Compute",
            "Compute",
            "eastus",
            100.0,
            100.0,
            1.0,
            json.dumps({"team": "Platform"}),
            "on-demand",
            "Usage",
            "subscription__sub-prod",
            "USD",
            "seed-delivery",
        ),
        (
            "cost-002",
            "2026-03-20",
            "sub-prod",
            "Prod Subscription",
            "rg-aks",
            "vm-aks-01",
            "/subscriptions/sub-prod/resourceGroups/rg-aks/providers/Microsoft.Compute/virtualMachines/vm-aks-01",
            "Compute",
            "Compute",
            "eastus",
            80.0,
            80.0,
            1.0,
            "{}",
            "on-demand",
            "Usage",
            "subscription__sub-prod",
            "USD",
            "seed-delivery",
        ),
        (
            "cost-003",
            "2026-03-20",
            "sub-prod",
            "Prod Subscription",
            "rg-percent",
            "st-percent-01",
            "/subscriptions/sub-prod/resourceGroups/rg-percent/providers/Microsoft.Storage/storageAccounts/st-percent-01",
            "Storage",
            "Storage",
            "eastus",
            60.0,
            60.0,
            1.0,
            "{}",
            "on-demand",
            "Usage",
            "subscription__sub-prod",
            "USD",
            "seed-delivery",
        ),
        (
            "cost-004",
            "2026-03-20",
            "sub-prod",
            "Prod Subscription",
            "rg-shared",
            "pip-shared-01",
            "/subscriptions/sub-prod/resourceGroups/rg-shared/providers/Microsoft.Network/publicIPAddresses/pip-shared-01",
            "Network",
            "Network",
            "eastus",
            40.0,
            40.0,
            1.0,
            "{}",
            "on-demand",
            "Usage",
            "subscription__sub-prod",
            "USD",
            "seed-delivery",
        ),
        (
            "cost-005",
            "2026-03-20",
            "sub-prod",
            "Prod Subscription",
            "rg-misc",
            "disk-misc-01",
            "/subscriptions/sub-prod/resourceGroups/rg-misc/providers/Microsoft.Compute/disks/disk-misc-01",
            "Storage",
            "Storage",
            "eastus",
            20.0,
            20.0,
            1.0,
            "{}",
            "on-demand",
            "Usage",
            "subscription__sub-prod",
            "USD",
            "seed-delivery",
        ),
    ]
    conn = service._connect()
    try:
        conn.executemany(
            """
            INSERT INTO cost_records (
                cost_record_id,
                date,
                subscription_id,
                subscription_name,
                resource_group,
                resource_name,
                resource_id,
                service_name,
                meter_category,
                location,
                cost_actual,
                cost_amortized,
                usage_quantity,
                tags_json,
                pricing_model,
                charge_type,
                scope_key,
                currency,
                source_delivery_key
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    finally:
        conn.close()


def test_sync_from_export_store_populates_local_cost_analytics(tmp_path):
    export_root = tmp_path / "exports"
    staging_root = tmp_path / "staged"
    quarantine_root = tmp_path / "quarantine"
    manifest_db = tmp_path / "azure_export_deliveries.db"
    finops_db = tmp_path / "azure_finops.duckdb"

    _write_focus_delivery(export_root)

    store = AzureExportStore(db_path=manifest_db)
    pipeline = AzureExportPipeline(
        export_root,
        store=store,
        staging_root=staging_root,
        quarantine_root=quarantine_root,
    )
    results = pipeline.sync()

    assert len(results) == 1
    assert results[0].manifest["parse_status"] == "parsed"

    service = AzureFinOpsService(db_path=finops_db, default_lookback_days=30)
    sync_result = service.sync_from_export_store(store)

    assert sync_result["imported_count"] == 1
    assert service.has_cost_data() is True

    summary = service.get_cost_summary()
    assert summary is not None
    assert summary["total_actual_cost"] == 25.5
    assert summary["total_amortized_cost"] == 22.5
    assert summary["top_service"] == "Compute"
    assert summary["top_subscription"] == "Prod Subscription"
    assert summary["record_count"] == 4
    assert summary["source"] == "exports"

    trend = service.get_cost_trend()
    assert [row["date"] for row in trend] == ["2026-03-18", "2026-03-19"]
    assert trend[0]["actual_cost"] == 15.0
    assert trend[0]["amortized_cost"] == 13.0

    by_service = service.get_cost_breakdown("service")
    assert by_service[0]["label"] == "Compute"
    assert by_service[0]["actual_cost"] == 17.5
    assert by_service[0]["amortized_cost"] == 14.5


def test_sync_from_export_store_is_idempotent_for_unchanged_delivery(tmp_path):
    export_root = tmp_path / "exports"
    staging_root = tmp_path / "staged"
    quarantine_root = tmp_path / "quarantine"
    manifest_db = tmp_path / "azure_export_deliveries.db"
    finops_db = tmp_path / "azure_finops.duckdb"

    _write_focus_delivery(export_root)

    store = AzureExportStore(db_path=manifest_db)
    pipeline = AzureExportPipeline(
        export_root,
        store=store,
        staging_root=staging_root,
        quarantine_root=quarantine_root,
    )
    pipeline.sync()

    service = AzureFinOpsService(db_path=finops_db, default_lookback_days=30)
    first = service.sync_from_export_store(store)
    second = service.sync_from_export_store(store)

    assert first["imported_count"] == 1
    assert second["imported_count"] == 0
    assert second["skipped_count"] == 1

    summary = service.get_cost_summary()
    assert summary is not None
    assert summary["record_count"] == 4


def test_finops_status_and_reconciliation_surface_field_map(tmp_path):
    export_root = tmp_path / "exports"
    staging_root = tmp_path / "staged"
    quarantine_root = tmp_path / "quarantine"
    manifest_db = tmp_path / "azure_export_deliveries.db"
    finops_db = tmp_path / "azure_finops.duckdb"

    _write_focus_delivery(export_root)

    store = AzureExportStore(db_path=manifest_db)
    pipeline = AzureExportPipeline(
        export_root,
        store=store,
        staging_root=staging_root,
        quarantine_root=quarantine_root,
    )
    pipeline.sync()

    service = AzureFinOpsService(db_path=finops_db, default_lookback_days=30)
    service.sync_from_export_store(store)

    status = service.get_status()
    reconciliation = service.get_cost_reconciliation({"total_cost": 25.5})
    validation = service.get_validation_report(
        {"total_cost": 25.5},
        {
            "health": {
                "state": "healthy",
                "reason": "Recent parsed delivery available",
                "expected_cadence_hours": 24,
            }
        },
    )

    assert status["available"] is True
    assert status["record_count"] == 4
    assert "subscriptionId" in status["field_map"]["fields"]
    assert status["field_coverage"]["pricing_model_pct"] == 1.0

    assert reconciliation["available"] is True
    assert reconciliation["latest_import"]["delivery_key"]
    assert reconciliation["duckdb_delivery_summary"]["row_count"] == 4
    assert reconciliation["export_delivery_summary"]["total_actual_cost"] == 25.5
    assert reconciliation["deltas"]["delivery_actual_cost_delta"] == 0.0

    assert validation["available"] is True
    assert validation["overall_state"] == "warning"
    assert validation["signoff_ready"] is False
    assert validation["check_counts"]["pass"] >= 1
    assert validation["check_counts"]["warning"] >= 1
    assert any(check["key"] == "delivery_actual_cost" and check["state"] == "pass" for check in validation["checks"])
    assert any(check["key"] == "scheduled_deliveries" and check["state"] == "warning" for check in validation["checks"])


def test_sync_from_export_store_imports_auxiliary_datasets_and_surfaces_counts(tmp_path):
    export_root = tmp_path / "exports"
    staging_root = tmp_path / "staged"
    quarantine_root = tmp_path / "quarantine"
    manifest_db = tmp_path / "azure_export_deliveries.db"
    finops_db = tmp_path / "azure_finops.duckdb"

    _write_focus_delivery(export_root)
    _write_auxiliary_delivery(
        export_root,
        "price-sheet",
        "price_sheet_sample.csv",
        "price_sheet_sample.csv",
        run_id="run-002",
    )
    _write_auxiliary_delivery(
        export_root,
        "reservation-recommendations",
        "reservation_recommendations_sample.csv",
        "reservation_recommendations_sample.csv",
        run_id="run-003",
    )

    store = AzureExportStore(db_path=manifest_db)
    pipeline = AzureExportPipeline(
        export_root,
        store=store,
        staging_root=staging_root,
        quarantine_root=quarantine_root,
    )
    pipeline.sync()

    service = AzureFinOpsService(db_path=finops_db, default_lookback_days=30)
    sync_result = service.sync_from_export_store(store)
    status = service.get_status()

    assert sync_result["imported_by_family"]["focus"] == 1
    assert sync_result["imported_by_family"]["price_sheet"] == 1
    assert sync_result["imported_by_family"]["reservation_recommendations"] == 1
    assert status["auxiliary_datasets"]["price_sheet"]["row_count"] == 2
    assert status["auxiliary_datasets"]["reservation_recommendations"]["row_count"] == 2


def test_recommendation_snapshot_prefers_export_commitment_rows(tmp_path):
    export_root = tmp_path / "exports"
    staging_root = tmp_path / "staged"
    quarantine_root = tmp_path / "quarantine"
    manifest_db = tmp_path / "azure_export_deliveries.db"
    finops_db = tmp_path / "azure_finops.duckdb"

    _write_focus_delivery(export_root)
    _write_auxiliary_delivery(
        export_root,
        "reservation-recommendations",
        "reservation_recommendations_sample.csv",
        "reservation_recommendations_sample.csv",
        run_id="run-004",
    )

    store = AzureExportStore(db_path=manifest_db)
    pipeline = AzureExportPipeline(
        export_root,
        store=store,
        staging_root=staging_root,
        quarantine_root=quarantine_root,
    )
    pipeline.sync()

    service = AzureFinOpsService(db_path=finops_db, default_lookback_days=30)
    service.sync_from_export_store(store)

    refresh = service.refresh_recommendations_snapshot(
        [
            {
                "id": "cache-commitment",
                "category": "commitment",
                "opportunity_type": "reservation_coverage_gap",
                "source": "heuristic",
                "title": "Legacy commitment heuristic",
                "summary": "Legacy heuristic summary.",
                "subscription_id": "sub-prod",
                "subscription_name": "Prod Subscription",
                "estimated_monthly_savings": 10.0,
                "currency": "USD",
                "quantified": True,
                "effort": "medium",
                "risk": "low",
                "confidence": "medium",
                "recommended_steps": [],
                "evidence": [],
            },
            {
                "id": "cache-storage",
                "category": "storage",
                "opportunity_type": "unattached_managed_disk",
                "source": "heuristic",
                "title": "Delete unattached disk",
                "summary": "Disk is no longer attached.",
                "subscription_id": "sub-prod",
                "subscription_name": "Prod Subscription",
                "resource_group": "rg-prod",
                "resource_name": "disk-1",
                "resource_type": "Microsoft.Compute/disks",
                "estimated_monthly_savings": 12.5,
                "currency": "USD",
                "quantified": True,
                "effort": "low",
                "risk": "low",
                "confidence": "high",
                "recommended_steps": ["Delete the disk if it is unused."],
                "evidence": [{"label": "State", "value": "Unattached"}],
            },
        ],
        cache_source_version="2026-03-23T12:00:00+00:00",
        cache_source_refreshed_at="2026-03-23T12:00:00+00:00",
    )

    recommendations = service.list_recommendations()
    summary = service.get_recommendation_summary()
    detail = service.get_recommendation("cache-storage")

    assert refresh["available"] is True
    assert len(recommendations) == 3
    assert all(item["id"] != "cache-commitment" for item in recommendations)
    assert any(item["opportunity_type"] == "reservation_purchase" for item in recommendations)
    assert summary is not None
    assert summary["total_opportunities"] == 3
    assert summary["quantified_opportunities"] == 3
    assert detail is not None
    assert detail["resource_name"] == "disk-1"
    assert service.get_status()["recommendations"]["row_count"] == 3


def test_recommendation_workflow_updates_and_history(tmp_path):
    finops_db = tmp_path / "azure_finops.duckdb"
    service = AzureFinOpsService(db_path=finops_db, default_lookback_days=30)
    service.refresh_recommendations_snapshot(
        [
            {
                "id": "rec-1",
                "category": "storage",
                "opportunity_type": "unattached_managed_disk",
                "source": "heuristic",
                "title": "Delete unattached disk",
                "summary": "Disk is no longer attached.",
                "subscription_id": "sub-prod",
                "subscription_name": "Prod Subscription",
                "resource_group": "rg-prod",
                "resource_name": "disk-1",
                "resource_type": "Microsoft.Compute/disks",
                "estimated_monthly_savings": 12.5,
                "currency": "USD",
                "quantified": True,
                "effort": "low",
                "risk": "low",
                "confidence": "high",
                "recommended_steps": ["Delete the disk if it is unused."],
                "evidence": [{"label": "State", "value": "Unattached"}],
            }
        ],
        cache_source_version="2026-03-23T12:00:00+00:00",
        cache_source_refreshed_at="2026-03-23T12:00:00+00:00",
    )

    dismissed = service.dismiss_recommendation(
        "rec-1",
        reason="Owner confirmed cleanup is deferred until quarter end.",
        actor_type="user",
        actor_id="admin@example.com",
    )
    action_updated = service.update_recommendation_action_state(
        "rec-1",
        action_state="ticket_created",
        action_type="create_ticket",
        actor_type="user",
        actor_id="admin@example.com",
        note="Created Jira follow-up.",
        metadata={"ticket_key": "OIT-999"},
    )
    reopened = service.reopen_recommendation(
        "rec-1",
        actor_type="user",
        actor_id="admin@example.com",
        note="Reopened after cost review.",
    )
    history = service.list_recommendation_action_history("rec-1")
    current = service.get_recommendation("rec-1")

    assert dismissed is not None
    assert dismissed["lifecycle_status"] == "dismissed"
    assert dismissed["dismissed_reason"] == "Owner confirmed cleanup is deferred until quarter end."
    assert action_updated is not None
    assert action_updated["action_state"] == "ticket_created"
    assert reopened is not None
    assert reopened["lifecycle_status"] == "open"
    assert reopened["dismissed_reason"] == ""
    assert current is not None
    assert current["action_state"] == "ticket_created"
    assert len(history) == 3
    assert history[0]["action_type"] == "reopen"
    assert history[1]["metadata"]["ticket_key"] == "OIT-999"


def test_recommendation_action_contract_reflects_status_and_safe_hooks(tmp_path):
    finops_db = tmp_path / "azure_finops.duckdb"
    service = AzureFinOpsService(
        db_path=finops_db,
        default_lookback_days=30,
        safe_hook_runner=_example_safe_hook_runner(),
    )
    service.refresh_recommendations_snapshot(
        [
            {
                "id": "rec-3",
                "category": "compute",
                "opportunity_type": "idle_vm_attached_cost",
                "source": "heuristic",
                "title": "Clean up idle VM attached costs",
                "summary": "Stopped VM still has billed attachments.",
            }
        ],
        cache_source_version="2026-03-23T12:00:00+00:00",
        cache_source_refreshed_at="2026-03-23T12:00:00+00:00",
    )
    service.update_recommendation_action_state(
        "rec-3",
        action_state="ticket_created",
        action_type="create_ticket",
        actor_type="user",
        actor_id="admin@example.com",
        note="Created Jira follow-up.",
        metadata={"ticket_key": "OIT-123"},
    )

    contract = service.get_recommendation_action_contract("rec-3")

    assert contract is not None
    assert contract["recommendation_id"] == "rec-3"
    create_ticket = next(item for item in contract["actions"] if item["action_type"] == "create_ticket")
    send_alert = next(item for item in contract["actions"] if item["action_type"] == "send_alert")
    export_action = next(item for item in contract["actions"] if item["action_type"] == "export")
    safe_script = next(item for item in contract["actions"] if item["action_type"] == "run_safe_script")

    assert create_ticket["status"] == "completed"
    assert create_ticket["can_execute"] is False
    assert create_ticket["latest_event"]["metadata"]["ticket_key"] == "OIT-123"
    assert send_alert["status"] == "available"
    assert send_alert["pending_action_state"] == "alert_pending"
    assert export_action["status"] == "available"
    assert export_action["repeatable"] is True
    assert safe_script["status"] == "available"
    assert safe_script["options"][0]["key"] == "vm_echo"
    assert safe_script["options"][0]["default_dry_run"] is True


def test_run_recommendation_safe_hook_records_dry_run_history(tmp_path):
    finops_db = tmp_path / "azure_finops.duckdb"
    service = AzureFinOpsService(
        db_path=finops_db,
        default_lookback_days=30,
        safe_hook_runner=_example_safe_hook_runner(),
    )
    service.refresh_recommendations_snapshot(
        [
            {
                "id": "rec-script",
                "category": "compute",
                "opportunity_type": "idle_vm_attached_cost",
                "source": "heuristic",
                "title": "Clean up idle VM attached costs",
                "summary": "Stopped VM still has billed attachments.",
                "resource_name": "vm-1",
            }
        ],
        cache_source_version="2026-03-23T12:00:00+00:00",
        cache_source_refreshed_at="2026-03-23T12:00:00+00:00",
    )

    result = service.run_recommendation_safe_hook(
        "rec-script",
        hook_key="vm_echo",
        dry_run=True,
        actor_type="user",
        actor_id="admin@example.com",
        note="Preview cleanup steps.",
    )
    history = service.list_recommendation_action_history("rec-script")
    current = service.get_recommendation("rec-script")

    assert result is not None
    assert result["action_status"] == "dry_run"
    assert "completed in dry run mode" in result["output_excerpt"]
    assert current is not None
    assert current["action_state"] == "none"
    assert history[0]["action_type"] == "run_safe_script"
    assert history[0]["action_status"] == "dry_run"
    assert history[0]["metadata"]["hook_key"] == "vm_echo"


def test_update_recommendation_action_state_rejects_unknown_state(tmp_path):
    finops_db = tmp_path / "azure_finops.duckdb"
    service = AzureFinOpsService(db_path=finops_db, default_lookback_days=30)
    service.refresh_recommendations_snapshot(
        [
            {
                "id": "rec-2",
                "category": "network",
                "opportunity_type": "unattached_public_ip",
                "source": "heuristic",
                "title": "Release unattached public IP",
                "summary": "The address is not in use.",
            }
        ],
        cache_source_version="2026-03-23T12:00:00+00:00",
        cache_source_refreshed_at="2026-03-23T12:00:00+00:00",
    )

    try:
        service.update_recommendation_action_state("rec-2", action_state="totally_invalid")
    except ValueError as exc:
        assert "Unsupported recommendation action state" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected ValueError for unsupported action state")


def test_record_recommendation_action_event_persists_failed_event_without_state_change(tmp_path):
    finops_db = tmp_path / "azure_finops.duckdb"
    service = AzureFinOpsService(db_path=finops_db, default_lookback_days=30)
    service.refresh_recommendations_snapshot(
        [
            {
                "id": "rec-4",
                "category": "compute",
                "opportunity_type": "rightsizing",
                "source": "heuristic",
                "title": "Right-size VM vm-1",
                "summary": "VM appears oversized for current utilization.",
            }
        ],
        cache_source_version="2026-03-23T12:00:00+00:00",
        cache_source_refreshed_at="2026-03-23T12:00:00+00:00",
    )

    updated = service.record_recommendation_action_event(
        "rec-4",
        action_type="create_ticket",
        action_status="failed",
        actor_type="user",
        actor_id="admin@example.com",
        note="Jira create failed.",
        metadata={"error": "Jira unavailable"},
    )
    history = service.list_recommendation_action_history("rec-4")

    assert updated is not None
    assert updated["action_state"] == "none"
    assert history[0]["action_type"] == "create_ticket"
    assert history[0]["action_status"] == "failed"
    assert history[0]["metadata"]["error"] == "Jira unavailable"


def test_ai_usage_rollups_and_pricing(tmp_path):
    finops_db = tmp_path / "azure_finops.duckdb"
    service = AzureFinOpsService(
        db_path=finops_db,
        default_lookback_days=30,
        ai_pricing_config={
            "providers": {"ollama": {"input_per_1k_tokens": 0.0, "output_per_1k_tokens": 0.0, "currency": "USD"}},
            "models": {"gpt-4.1": {"input_per_1k_tokens": 0.01, "output_per_1k_tokens": 0.03, "currency": "USD"}},
        },
    )

    service.record_ai_usage(
        provider="gpt-provider",
        model_id="gpt-4.1",
        feature_surface="azure_cost_copilot",
        app_surface="azure_portal",
        actor_type="user",
        actor_id="user@example.com",
        request_count=1,
        input_tokens=1000,
        output_tokens=500,
        estimated_tokens=1500,
        latency_ms=125.0,
    )
    service.record_ai_usage(
        provider="ollama",
        model_id="qwen2.5:7b",
        feature_surface="ticket_auto_triage",
        app_surface="tickets",
        actor_type="system",
        actor_id="auto-triage",
        request_count=1,
        input_tokens=200,
        output_tokens=100,
        estimated_tokens=300,
        latency_ms=40.0,
    )

    summary = service.get_ai_cost_summary()
    trend = service.get_ai_cost_trend()
    by_model = service.get_ai_cost_breakdown("model")

    assert summary is not None
    assert summary["request_count"] == 2
    assert summary["estimated_cost"] == 0.025
    assert summary["top_model"] == "gpt-4.1"
    assert trend[0]["estimated_tokens"] == 1800
    assert by_model[0]["label"] == "gpt-4.1"
    assert by_model[0]["estimated_cost"] == 0.025


def test_allocation_policy_and_rule_versioning(tmp_path):
    service = AzureFinOpsService(db_path=tmp_path / "azure_finops.duckdb", default_lookback_days=30)

    policy = service.get_allocation_policy()
    assert policy["shared_cost_posture"]["mode"] == "showback_named_shared_buckets"
    assert policy["target_dimensions"][0]["fallback_bucket"] == "Unassigned Team"

    first = service.upsert_allocation_rule(
        name="Allocate AKS RG to platform",
        description="Initial regex rule.",
        rule_type="regex",
        target_dimension="team",
        priority=10,
        condition={"field": "resource_group", "pattern": "^rg-aks$"},
        allocation={"value": "Platform Team"},
        actor_id="finops@example.com",
    )
    second = service.upsert_allocation_rule(
        rule_id=first["rule_id"],
        name="Allocate AKS RG to AKS team",
        description="Updated regex rule.",
        rule_type="regex",
        target_dimension="team",
        priority=5,
        condition={"field": "resource_group", "pattern": "^rg-aks$"},
        allocation={"value": "AKS Team"},
        actor_id="finops@example.com",
    )

    assert first["rule_version"] == 1
    assert second["rule_version"] == 2
    assert second["allocation"]["value"] == "AKS Team"

    latest_rules = service.list_allocation_rules()
    all_versions = service.list_allocation_rules(include_inactive=True, include_all_versions=True)
    assert len(latest_rules) == 1
    assert len([row for row in all_versions if row["rule_id"] == first["rule_id"]]) == 2

    status = service.get_allocation_status()
    assert status["active_rule_count"] == 1
    assert status["rule_version_count"] == 2


def test_run_allocation_materializes_results_with_full_coverage(tmp_path):
    service = AzureFinOpsService(db_path=tmp_path / "azure_finops.duckdb", default_lookback_days=30)
    _seed_allocation_cost_records(service)

    service.upsert_allocation_rule(
        name="Tag based team owner",
        rule_type="tag",
        target_dimension="team",
        priority=10,
        condition={"tag_key": "team", "tag_value": "Platform"},
        allocation={"value": "Platform Team"},
        actor_id="finops@example.com",
    )
    service.upsert_allocation_rule(
        name="AKS regex owner",
        rule_type="regex",
        target_dimension="team",
        priority=20,
        condition={"field": "resource_group", "pattern": "^rg-aks$"},
        allocation={"value": "AKS Team"},
        actor_id="finops@example.com",
    )
    service.upsert_allocation_rule(
        name="Partial percentage owner",
        rule_type="percentage",
        target_dimension="team",
        priority=30,
        condition={"field": "resource_group", "equals": "rg-percent"},
        allocation={"value": "Ops Team", "percentage": 25},
        actor_id="finops@example.com",
    )
    service.upsert_allocation_rule(
        name="Shared networking split",
        rule_type="shared",
        target_dimension="team",
        priority=40,
        condition={"field": "resource_group", "pattern": "^rg-shared$"},
        allocation={
            "splits": [
                {"value": "Infra Shared", "percentage": 50},
                {"value": "Security Shared", "percentage": 50},
            ]
        },
        actor_id="finops@example.com",
    )

    run = service.run_allocation(
        actor_id="finops@example.com",
        target_dimensions=["team"],
        run_label="Initial team allocation",
        note="Seed run",
    )

    assert run["status"] == "completed"
    assert run["target_dimensions"] == ["team"]
    assert run["dimensions"][0]["target_dimension"] == "team"
    assert run["dimensions"][0]["source_actual_cost"] == 300.0
    assert run["dimensions"][0]["direct_allocated_actual_cost"] == 235.0
    assert run["dimensions"][0]["residual_actual_cost"] == 65.0
    assert run["dimensions"][0]["total_allocated_actual_cost"] == 300.0
    assert run["dimensions"][0]["coverage_pct"] == 1.0
    assert len(run["rule_versions"]) == 4

    results = service.list_allocation_results(run["run_id"], target_dimension="team")
    by_value = {row["allocation_value"]: row for row in results}
    assert by_value["Platform Team"]["allocated_actual_cost"] == 100.0
    assert by_value["AKS Team"]["allocated_actual_cost"] == 80.0
    assert by_value["Ops Team"]["allocated_actual_cost"] == 15.0
    assert by_value["Infra Shared"]["allocated_actual_cost"] == 20.0
    assert by_value["Security Shared"]["allocated_actual_cost"] == 20.0
    assert by_value["Unassigned Team"]["allocated_actual_cost"] == 65.0

    residuals = service.list_allocation_residuals(run["run_id"], target_dimension="team")
    assert residuals == [
        {
            "allocation_value": "Unassigned Team",
            "bucket_type": "fallback",
            "allocation_method": "fallback",
            "source_record_count": 2,
            "allocated_actual_cost": 65.0,
            "allocated_amortized_cost": 65.0,
            "allocated_usage_quantity": 1.75,
        }
    ]

    status = service.get_allocation_status()
    assert status["run_count"] == 1
    assert status["latest_run"]["run_id"] == run["run_id"]


def test_resource_cost_bridge_and_aks_visibility_enrich_recommendations(tmp_path):
    service = AzureFinOpsService(db_path=tmp_path / "azure_finops.duckdb", default_lookback_days=30)

    cluster_id = (
        "/subscriptions/sub-prod/resourceGroups/rg-aks/providers/"
        "Microsoft.ContainerService/managedClusters/cluster-1"
    )
    vmss_system_id = (
        "/subscriptions/sub-prod/resourceGroups/MC_rg-aks_cluster-1_eastus/providers/"
        "Microsoft.Compute/virtualMachineScaleSets/aks-systempool-vmss"
    )
    vmss_user_id = (
        "/subscriptions/sub-prod/resourceGroups/MC_rg-aks_cluster-1_eastus/providers/"
        "Microsoft.Compute/virtualMachineScaleSets/aks-userpool-vmss"
    )
    lb_id = (
        "/subscriptions/sub-prod/resourceGroups/MC_rg-aks_cluster-1_eastus/providers/"
        "Microsoft.Network/loadBalancers/kubernetes"
    )
    vm_id = (
        "/subscriptions/sub-prod/resourceGroups/rg-app/providers/"
        "Microsoft.Compute/virtualMachines/vm-01"
    )

    conn = service._connect()
    try:
        conn.executemany(
            """
            INSERT INTO cost_records (
                cost_record_id,
                date,
                subscription_id,
                subscription_name,
                resource_group,
                resource_name,
                resource_id,
                service_name,
                meter_category,
                location,
                cost_actual,
                cost_amortized,
                usage_quantity,
                tags_json,
                pricing_model,
                charge_type,
                scope_key,
                currency,
                source_delivery_key
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("bridge-1", "2026-03-20", "sub-prod", "Prod Subscription", "rg-aks", "cluster-1", cluster_id, "Containers", "Container Service", "eastus", 5.0, 5.0, 1.0, "{}", "on-demand", "Usage", "subscription__sub-prod", "USD", "seed"),
                ("bridge-2", "2026-03-20", "sub-prod", "Prod Subscription", "MC_rg-aks_cluster-1_eastus", "aks-systempool-vmss", vmss_system_id, "Compute", "Compute", "eastus", 90.0, 90.0, 1.0, "{}", "on-demand", "Usage", "subscription__sub-prod", "USD", "seed"),
                ("bridge-3", "2026-03-20", "sub-prod", "Prod Subscription", "MC_rg-aks_cluster-1_eastus", "aks-userpool-vmss", vmss_user_id, "Compute", "Compute", "eastus", 30.0, 30.0, 1.0, "{}", "on-demand", "Usage", "subscription__sub-prod", "USD", "seed"),
                ("bridge-4", "2026-03-20", "sub-prod", "Prod Subscription", "MC_rg-aks_cluster-1_eastus", "kubernetes", lb_id, "Network", "Network", "eastus", 20.0, 20.0, 1.0, "{}", "on-demand", "Usage", "subscription__sub-prod", "USD", "seed"),
                ("bridge-5", "2026-03-20", "sub-prod", "Prod Subscription", "rg-app", "vm-01", vm_id, "Compute", "Compute", "eastus", 50.0, 50.0, 1.0, "{}", "on-demand", "Usage", "subscription__sub-prod", "USD", "seed"),
            ],
        )
    finally:
        conn.close()

    cache_resources = [
        {
            "id": cluster_id,
            "name": "cluster-1",
            "resource_type": "Microsoft.ContainerService/managedClusters",
            "subscription_id": "sub-prod",
            "resource_group": "rg-aks",
            "location": "eastus",
            "managed_by": "",
            "tags": {},
        },
        {
            "id": vmss_system_id,
            "name": "aks-systempool-vmss",
            "resource_type": "Microsoft.Compute/virtualMachineScaleSets",
            "subscription_id": "sub-prod",
            "resource_group": "MC_rg-aks_cluster-1_eastus",
            "location": "eastus",
            "managed_by": cluster_id,
            "tags": {"aks-managed-poolName": "systempool"},
        },
        {
            "id": vmss_user_id,
            "name": "aks-userpool-vmss",
            "resource_type": "Microsoft.Compute/virtualMachineScaleSets",
            "subscription_id": "sub-prod",
            "resource_group": "MC_rg-aks_cluster-1_eastus",
            "location": "eastus",
            "managed_by": cluster_id,
            "tags": {"aks-managed-poolName": "userpool"},
        },
        {
            "id": lb_id,
            "name": "kubernetes",
            "resource_type": "Microsoft.Network/loadBalancers",
            "subscription_id": "sub-prod",
            "resource_group": "MC_rg-aks_cluster-1_eastus",
            "location": "eastus",
            "managed_by": cluster_id,
            "tags": {},
        },
        {
            "id": vm_id,
            "name": "vm-01",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "subscription_id": "sub-prod",
            "resource_group": "rg-app",
            "location": "eastus",
            "managed_by": "",
            "tags": {},
        },
    ]

    bridge = service.get_resource_cost_bridge_summary(cache_resources)
    assert bridge["matched_resource_count"] == 5
    assert bridge["cluster_detected_count"] == 4
    assert bridge["bridged_actual_cost"] == 195.0

    aks_rows = service.list_aks_cost_visibility(cache_resources)
    assert len(aks_rows) == 1
    aks = aks_rows[0]
    assert aks["resource_name"] == "cluster-1"
    assert aks["current_monthly_cost"] == 145.0
    assert aks["aks_visibility"]["node_pools"][0]["label"] == "systempool"
    assert aks["aks_visibility"]["node_pools"][0]["actual_cost"] == 90.0

    service.refresh_recommendations_snapshot(
        [
            {
                "id": "vm-rightsize-1",
                "category": "compute",
                "opportunity_type": "rightsizing",
                "source": "heuristic",
                "title": "Right-size vm-01",
                "summary": "VM appears oversized.",
                "subscription_id": "sub-prod",
                "subscription_name": "Prod Subscription",
                "resource_group": "rg-app",
                "resource_id": vm_id,
                "resource_name": "vm-01",
                "resource_type": "",
                "current_monthly_cost": None,
                "currency": "USD",
                "quantified": False,
                "evidence": [],
            }
        ],
        cache_source_version="cache-v1",
        cache_source_refreshed_at="2026-03-23T12:00:00+00:00",
        cache_resources=cache_resources,
        inventory_source_version="inventory-v1",
    )

    recommendations = service.list_recommendations()
    by_id = {item["id"]: item for item in recommendations}
    assert by_id["vm-rightsize-1"]["current_monthly_cost"] == 50.0
    assert by_id["vm-rightsize-1"]["resource_type"] == "Microsoft.Compute/virtualMachines"
    assert any(
        row["label"] == "Export-backed current monthly cost"
        for row in by_id["vm-rightsize-1"]["evidence"]
    )
    aks_recommendation = next(item for item in recommendations if item["opportunity_type"] == "aks_cluster_cost_visibility")
    assert aks_recommendation["resource_name"] == "cluster-1"
    assert aks_recommendation["current_monthly_cost"] == 145.0
