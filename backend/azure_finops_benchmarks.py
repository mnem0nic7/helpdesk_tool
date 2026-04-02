"""Local performance and scale benchmarks for Azure FinOps analytics."""

from __future__ import annotations

import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from azure_finops_service import AzureFinOpsService


DEFAULT_COST_RECORD_COUNT = 1_000_000
DEFAULT_RECOMMENDATION_COUNT = 50_000
DEFAULT_AI_USAGE_COUNT = 200_000
DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_QUERY_BUDGET_MS = 2_000.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 3)
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return round(ordered[lower], 3)
    weight = rank - lower
    return round((ordered[lower] * (1 - weight)) + (ordered[upper] * weight), 3)


def _result_hint(value: Any) -> dict[str, Any]:
    if value is None:
        return {"kind": "none"}
    if isinstance(value, list):
        return {
            "kind": "list",
            "row_count": len(value),
        }
    if isinstance(value, dict):
        hint: dict[str, Any] = {
            "kind": "dict",
            "key_count": len(value),
        }
        for key in ("record_count", "total_opportunities", "usage_record_count", "request_count", "top_model"):
            if key in value:
                hint[key] = value.get(key)
        return hint
    return {
        "kind": type(value).__name__,
        "value": str(value),
    }


def create_benchmark_service(
    db_path: str | Path | None = None,
    *,
    default_lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> AzureFinOpsService:
    if db_path is None:
        fd, tmp_path = tempfile.mkstemp(prefix="azure-finops-bench-", suffix=".duckdb")
        os.close(fd)
        Path(tmp_path).unlink(missing_ok=True)
        db_path = tmp_path
    return AzureFinOpsService(db_path=db_path, default_lookback_days=default_lookback_days)


def seed_benchmark_dataset(
    service: AzureFinOpsService,
    *,
    cost_record_count: int = DEFAULT_COST_RECORD_COUNT,
    recommendation_count: int = DEFAULT_RECOMMENDATION_COUNT,
    ai_usage_count: int = DEFAULT_AI_USAGE_COUNT,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, int]:
    cost_record_count = max(int(cost_record_count), 1)
    recommendation_count = max(int(recommendation_count), 1)
    ai_usage_count = max(int(ai_usage_count), 1)
    lookback_days = max(int(lookback_days), 1)

    with service._lock:
        conn = service._connect()
        try:
            conn.execute("DELETE FROM recommendation_action_events")
            conn.execute("DELETE FROM recommendation_refresh_state")
            conn.execute("DELETE FROM recommendations")
            conn.execute("DELETE FROM reservation_recommendation_rows")
            conn.execute("DELETE FROM price_sheet_rows")
            conn.execute("DELETE FROM ai_usage_records")
            conn.execute("DELETE FROM finops_delivery_imports")
            conn.execute("DELETE FROM cost_records")

            conn.execute(
                f"""
                INSERT INTO cost_records
                SELECT
                    'bench-cost-' || CAST(i AS VARCHAR) AS cost_record_id,
                    DATE '2026-03-23' - CAST((i % {lookback_days}) AS INTEGER) AS date,
                    'sub-' || LPAD(CAST(i % 50 AS VARCHAR), 2, '0') AS subscription_id,
                    'Subscription ' || CAST(i % 50 AS VARCHAR) AS subscription_name,
                    'rg-' || LPAD(CAST(i % 200 AS VARCHAR), 3, '0') AS resource_group,
                    'resource-' || CAST(i AS VARCHAR) AS resource_name,
                    '/subscriptions/sub-' || LPAD(CAST(i % 50 AS VARCHAR), 2, '0')
                        || '/resourceGroups/rg-' || LPAD(CAST(i % 200 AS VARCHAR), 3, '0')
                        || '/providers/Microsoft.'
                        || CASE
                            WHEN i % 6 = 0 THEN 'Compute/virtualMachines/resource-'
                            WHEN i % 6 = 1 THEN 'Storage/storageAccounts/resource-'
                            WHEN i % 6 = 2 THEN 'Network/publicIPAddresses/resource-'
                            WHEN i % 6 = 3 THEN 'ContainerService/managedClusters/resource-'
                            WHEN i % 6 = 4 THEN 'Compute/disks/resource-'
                            ELSE 'Web/sites/resource-'
                        END
                        || CAST(i AS VARCHAR) AS resource_id,
                    CASE
                        WHEN i % 6 = 0 THEN 'Compute'
                        WHEN i % 6 = 1 THEN 'Storage'
                        WHEN i % 6 = 2 THEN 'Networking'
                        WHEN i % 6 = 3 THEN 'Containers'
                        WHEN i % 6 = 4 THEN 'Compute'
                        ELSE 'App Service'
                    END AS service_name,
                    CASE
                        WHEN i % 6 = 0 THEN 'Virtual Machines'
                        WHEN i % 6 = 1 THEN 'Storage'
                        WHEN i % 6 = 2 THEN 'Networking'
                        WHEN i % 6 = 3 THEN 'Containers'
                        WHEN i % 6 = 4 THEN 'Disks'
                        ELSE 'App Service'
                    END AS meter_category,
                    CASE
                        WHEN i % 4 = 0 THEN 'eastus'
                        WHEN i % 4 = 1 THEN 'westus2'
                        WHEN i % 4 = 2 THEN 'centralus'
                        ELSE 'eastus2'
                    END AS location,
                    ROUND(((i % 1000) + 1) * 0.013, 6) AS cost_actual,
                    ROUND((((i % 1000) + 1) * 0.013) * CASE WHEN i % 10 = 0 THEN 0.85 ELSE 1.0 END, 6) AS cost_amortized,
                    ROUND(((i % 200) + 1) * 0.5, 3) AS usage_quantity,
                    '{{"team":"team-' || CAST(i % 20 AS VARCHAR) || '","app":"app-' || CAST(i % 100 AS VARCHAR) || '"}}' AS tags_json,
                    CASE
                        WHEN i % 12 = 0 THEN 'reservation'
                        WHEN i % 9 = 0 THEN 'savings plan'
                        ELSE 'on-demand'
                    END AS pricing_model,
                    CASE
                        WHEN i % 7 = 0 THEN 'Purchase'
                        ELSE 'Usage'
                    END AS charge_type,
                    CASE
                        WHEN i % 3 = 0 THEN 'subscription__shared'
                        WHEN i % 3 = 1 THEN 'subscription__prod'
                        ELSE 'subscription__dev'
                    END AS scope_key,
                    'USD' AS currency,
                    'bench-focus-' || CAST(i % 32 AS VARCHAR) AS source_delivery_key
                FROM range({cost_record_count}) AS t(i)
                """
            )

            conn.execute(
                f"""
                INSERT INTO recommendations
                SELECT
                    'bench-rec-' || CAST(i AS VARCHAR) AS recommendation_id,
                    CASE
                        WHEN i % 5 = 0 THEN 'compute'
                        WHEN i % 5 = 1 THEN 'storage'
                        WHEN i % 5 = 2 THEN 'commitment'
                        WHEN i % 5 = 3 THEN 'network'
                        ELSE 'other'
                    END AS category,
                    CASE
                        WHEN i % 5 = 0 THEN 'rightsizing'
                        WHEN i % 5 = 1 THEN 'unattached_managed_disk'
                        WHEN i % 5 = 2 THEN 'reservation_purchase'
                        WHEN i % 5 = 3 THEN 'idle_public_ip'
                        ELSE 'misc_cleanup'
                    END AS opportunity_type,
                    CASE WHEN i % 4 = 0 THEN 'advisor' ELSE 'heuristic' END AS source,
                    'Synthetic recommendation ' || CAST(i AS VARCHAR) AS title,
                    'Synthetic recommendation summary ' || CAST(i AS VARCHAR) AS summary,
                    'sub-' || LPAD(CAST(i % 50 AS VARCHAR), 2, '0') AS subscription_id,
                    'Subscription ' || CAST(i % 50 AS VARCHAR) AS subscription_name,
                    'rg-' || LPAD(CAST(i % 200 AS VARCHAR), 3, '0') AS resource_group,
                    CASE
                        WHEN i % 4 = 0 THEN 'eastus'
                        WHEN i % 4 = 1 THEN 'westus2'
                        WHEN i % 4 = 2 THEN 'centralus'
                        ELSE 'eastus2'
                    END AS location,
                    '/subscriptions/sub-' || LPAD(CAST(i % 50 AS VARCHAR), 2, '0')
                        || '/resourceGroups/rg-' || LPAD(CAST(i % 200 AS VARCHAR), 3, '0')
                        || '/providers/Microsoft.Compute/virtualMachines/resource-' || CAST(i AS VARCHAR) AS resource_id,
                    'resource-' || CAST(i AS VARCHAR) AS resource_name,
                    'Microsoft.Compute/virtualMachines' AS resource_type,
                    ROUND(((i % 500) + 50) * 1.1, 2) AS current_monthly_cost,
                    ROUND(((i % 150) + 5) * 0.75, 2) AS estimated_monthly_savings,
                    'USD' AS currency,
                    CASE WHEN i % 9 = 0 THEN FALSE ELSE TRUE END AS quantified,
                    CASE WHEN i % 5 = 2 THEN 'Export-backed reservation heuristic' ELSE 'Synthetic heuristic' END AS estimate_basis,
                    CASE
                        WHEN i % 3 = 0 THEN 'low'
                        WHEN i % 3 = 1 THEN 'medium'
                        ELSE 'high'
                    END AS effort,
                    CASE
                        WHEN i % 3 = 0 THEN 'low'
                        WHEN i % 3 = 1 THEN 'medium'
                        ELSE 'high'
                    END AS risk,
                    CASE
                        WHEN i % 3 = 0 THEN 'high'
                        WHEN i % 3 = 1 THEN 'medium'
                        ELSE 'low'
                    END AS confidence,
                    '["Review utilization","Apply change"]' AS recommended_steps_json,
                    '[{{"label":"Signal","value":"Synthetic benchmark"}}]' AS evidence_json,
                    'https://portal.azure.com/' AS portal_url,
                    '/azure/savings' AS follow_up_route,
                    CASE WHEN i % 11 = 0 THEN 'dismissed' ELSE 'open' END AS lifecycle_status,
                    CASE
                        WHEN i % 13 = 0 THEN 'ticket_created'
                        WHEN i % 7 = 0 THEN 'alert_sent'
                        ELSE 'none'
                    END AS action_state,
                    CASE WHEN i % 11 = 0 THEN 'Benchmark dismissed' ELSE '' END AS dismissed_reason,
                    'bench-reco-v1' AS source_version,
                    TIMESTAMP '2026-03-23 12:00:00' AS source_refreshed_at,
                    TIMESTAMP '2026-03-23 12:00:00' AS created_at,
                    TIMESTAMP '2026-03-23 12:00:00' AS updated_at
                FROM range({recommendation_count}) AS t(i)
                """
            )

            conn.execute(
                f"""
                INSERT INTO recommendation_refresh_state (
                    snapshot_name,
                    source_version,
                    source_refreshed_at,
                    row_count,
                    refreshed_at
                )
                VALUES (
                    'default',
                    'bench-reco-v1',
                    TIMESTAMP '2026-03-23 12:00:00',
                    {recommendation_count},
                    TIMESTAMP '2026-03-23 12:05:00'
                )
                """
            )

            conn.execute(
                f"""
                INSERT INTO ai_usage_records
                SELECT
                    'bench-ai-' || CAST(i AS VARCHAR) AS usage_id,
                    TIMESTAMP '2026-03-23 12:00:00' - CAST((i % {lookback_days}) AS INTEGER) * INTERVAL 1 DAY AS recorded_at,
                    DATE '2026-03-23' - CAST((i % {lookback_days}) AS INTEGER) AS recorded_date,
                    'ollama' AS provider,
                    CASE
                        WHEN i % 3 = 0 THEN 'qwen3.5:4b'
                        WHEN i % 3 = 1 THEN 'nemotron-3-nano:4b'
                        ELSE 'nemotron-3-nano:4b'
                    END AS model_id,
                    CASE
                        WHEN i % 4 = 0 THEN 'azure_cost_copilot'
                        WHEN i % 4 = 1 THEN 'ticket_auto_triage'
                        WHEN i % 4 = 2 THEN 'technician_qa'
                        ELSE 'knowledge_base'
                    END AS feature_surface,
                    CASE
                        WHEN i % 4 = 0 THEN 'azure'
                        WHEN i % 4 = 1 THEN 'tickets'
                        WHEN i % 4 = 2 THEN 'tickets'
                        ELSE 'knowledge_base'
                    END AS app_surface,
                    CASE WHEN i % 10 = 0 THEN 'system' ELSE 'user' END AS actor_type,
                    'actor-' || CAST(i % 250 AS VARCHAR) AS actor_id,
                    CASE
                        WHEN i % 3 = 0 THEN 'FinOps'
                        WHEN i % 3 = 1 THEN 'Helpdesk'
                        ELSE 'Knowledge'
                    END AS team,
                    1 AS request_count,
                    CAST(((i % 1200) + 250) AS BIGINT) AS input_tokens,
                    CAST(((i % 600) + 80) AS BIGINT) AS output_tokens,
                    CAST(((i % 1800) + 330) AS BIGINT) AS estimated_tokens,
                    ROUND(((i % 900) + 20) * 1.0, 3) AS latency_ms,
                    ROUND((((i % 1800) + 330) / 1000000.0) * 0.18, 6) AS estimated_cost,
                    'USD' AS currency,
                    'benchmark' AS pricing_source,
                    'succeeded' AS status,
                    '' AS error_text,
                    '{{"benchmark":true}}' AS metadata_json
                FROM range({ai_usage_count}) AS t(i)
                """
            )
        finally:
            conn.close()

    return {
        "cost_records": cost_record_count,
        "recommendations": recommendation_count,
        "ai_usage_records": ai_usage_count,
        "lookback_days": lookback_days,
    }


def _benchmark_case(
    *,
    name: str,
    description: str,
    fn: Callable[[], Any],
    iterations: int,
    warmup_iterations: int,
    budget_ms: float,
) -> dict[str, Any]:
    for _ in range(max(int(warmup_iterations), 0)):
        fn()

    durations_ms: list[float] = []
    last_result: Any = None
    for _ in range(max(int(iterations), 1)):
        started = time.perf_counter()
        last_result = fn()
        durations_ms.append((time.perf_counter() - started) * 1000.0)

    mean_ms = round(statistics.fmean(durations_ms), 3)
    return {
        "name": name,
        "description": description,
        "iterations": max(int(iterations), 1),
        "warmup_iterations": max(int(warmup_iterations), 0),
        "budget_ms": round(float(budget_ms), 3),
        "min_ms": round(min(durations_ms), 3),
        "mean_ms": mean_ms,
        "median_ms": round(statistics.median(durations_ms), 3),
        "p95_ms": _percentile(durations_ms, 0.95),
        "max_ms": round(max(durations_ms), 3),
        "within_budget": mean_ms <= float(budget_ms),
        "result_hint": _result_hint(last_result),
    }


def run_benchmarks(
    service: AzureFinOpsService,
    *,
    iterations: int = 5,
    warmup_iterations: int = 1,
    budget_ms: float = DEFAULT_QUERY_BUDGET_MS,
) -> dict[str, Any]:
    cases = [
        (
            "cost_summary",
            "Top-line export-backed cost summary for the current lookback window.",
            lambda: service.get_cost_summary(),
        ),
        (
            "cost_trend",
            "Daily export-backed cost trend for the current lookback window.",
            lambda: service.get_cost_trend(),
        ),
        (
            "cost_breakdown_service",
            "Cost breakdown by service.",
            lambda: service.get_cost_breakdown("service"),
        ),
        (
            "cost_breakdown_subscription",
            "Cost breakdown by subscription.",
            lambda: service.get_cost_breakdown("subscription"),
        ),
        (
            "recommendation_summary",
            "Persisted recommendation summary rollup.",
            lambda: service.get_recommendation_summary(),
        ),
        (
            "recommendation_list_quantified",
            "Filtered quantified recommendation listing.",
            lambda: service.list_recommendations(category="compute", quantified_only=True),
        ),
        (
            "ai_cost_summary",
            "AI usage summary over the current lookback window.",
            lambda: service.get_ai_cost_summary(),
        ),
        (
            "ai_cost_trend",
            "AI usage trend over the current lookback window.",
            lambda: service.get_ai_cost_trend(),
        ),
        (
            "ai_cost_breakdown_model",
            "AI usage breakdown by model.",
            lambda: service.get_ai_cost_breakdown("model"),
        ),
    ]
    results = [
        _benchmark_case(
            name=name,
            description=description,
            fn=fn,
            iterations=iterations,
            warmup_iterations=warmup_iterations,
            budget_ms=budget_ms,
        )
        for name, description, fn in cases
    ]
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "query_budget_ms": round(float(budget_ms), 3),
        "benchmarks": results,
        "all_within_budget": all(bool(item["within_budget"]) for item in results),
    }


def format_benchmark_report_markdown(report: dict[str, Any], dataset: dict[str, int], *, service_db_path: str) -> str:
    lines = [
        "# Azure FinOps Local Benchmark Report",
        "",
        "## Dataset",
        "",
        f"- DuckDB path: `{service_db_path}`",
        f"- Cost records: `{dataset['cost_records']:,}`",
        f"- Recommendations: `{dataset['recommendations']:,}`",
        f"- AI usage records: `{dataset['ai_usage_records']:,}`",
        f"- Lookback days: `{dataset['lookback_days']}`",
        f"- Query budget: `{report['query_budget_ms']:.0f} ms`",
        "",
        "## Results",
        "",
        "| Query | Mean (ms) | P95 (ms) | Max (ms) | Budget | Pass |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report.get("benchmarks") or []:
        lines.append(
            "| "
            f"{row['name']} | {row['mean_ms']:.3f} | {row['p95_ms']:.3f} | {row['max_ms']:.3f} | "
            f"{row['budget_ms']:.0f} | {'yes' if row['within_budget'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Result Hints",
            "",
        ]
    )
    for row in report.get("benchmarks") or []:
        lines.append(f"- `{row['name']}`: {json.dumps(row.get('result_hint') or {}, sort_keys=True)}")
    lines.extend(
        [
            "",
            f"All benchmarks within budget: `{'yes' if report.get('all_within_budget') else 'no'}`",
        ]
    )
    return "\n".join(lines) + "\n"
