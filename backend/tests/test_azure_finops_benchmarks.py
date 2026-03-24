from __future__ import annotations

from azure_finops_benchmarks import (
    create_benchmark_service,
    format_benchmark_report_markdown,
    run_benchmarks,
    seed_benchmark_dataset,
)


def test_finops_benchmark_harness_seeds_and_reports(tmp_path):
    service = create_benchmark_service(tmp_path / "bench.duckdb", default_lookback_days=7)
    dataset = seed_benchmark_dataset(
        service,
        cost_record_count=5_000,
        recommendation_count=500,
        ai_usage_count=1_000,
        lookback_days=7,
    )

    assert dataset == {
        "cost_records": 5_000,
        "recommendations": 500,
        "ai_usage_records": 1_000,
        "lookback_days": 7,
    }
    assert service.get_status()["record_count"] == 5_000
    assert service.get_recommendation_summary() is not None
    assert service.get_ai_cost_summary() is not None

    report = run_benchmarks(service, iterations=1, warmup_iterations=0, budget_ms=10_000)

    assert report["all_within_budget"] is True
    assert {row["name"] for row in report["benchmarks"]} == {
        "cost_summary",
        "cost_trend",
        "cost_breakdown_service",
        "cost_breakdown_subscription",
        "recommendation_summary",
        "recommendation_list_quantified",
        "ai_cost_summary",
        "ai_cost_trend",
        "ai_cost_breakdown_model",
    }

    markdown = format_benchmark_report_markdown(report, dataset, service_db_path=str(service._db_path))
    assert "# Azure FinOps Local Benchmark Report" in markdown
    assert "cost_summary" in markdown
    assert "recommendation_summary" in markdown
