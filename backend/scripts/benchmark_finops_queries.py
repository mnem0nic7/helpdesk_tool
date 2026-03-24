#!/usr/bin/env python3
"""Seed a local Azure FinOps DuckDB dataset and benchmark key query paths."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from azure_finops_benchmarks import (  # noqa: E402
    DEFAULT_AI_USAGE_COUNT,
    DEFAULT_COST_RECORD_COUNT,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_QUERY_BUDGET_MS,
    DEFAULT_RECOMMENDATION_COUNT,
    create_benchmark_service,
    format_benchmark_report_markdown,
    run_benchmarks,
    seed_benchmark_dataset,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="", help="DuckDB path to use for the benchmark run.")
    parser.add_argument("--cost-records", type=int, default=DEFAULT_COST_RECORD_COUNT)
    parser.add_argument("--recommendations", type=int, default=DEFAULT_RECOMMENDATION_COUNT)
    parser.add_argument("--ai-usage-records", type=int, default=DEFAULT_AI_USAGE_COUNT)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--warmup-iterations", type=int, default=1)
    parser.add_argument("--budget-ms", type=float, default=DEFAULT_QUERY_BUDGET_MS)
    parser.add_argument("--output-json", default="", help="Optional path for the benchmark JSON payload.")
    parser.add_argument("--output-markdown", default="", help="Optional path for the markdown benchmark report.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = create_benchmark_service(args.db_path or None, default_lookback_days=args.lookback_days)
    dataset = seed_benchmark_dataset(
        service,
        cost_record_count=args.cost_records,
        recommendation_count=args.recommendations,
        ai_usage_count=args.ai_usage_records,
        lookback_days=args.lookback_days,
    )
    report = run_benchmarks(
        service,
        iterations=args.iterations,
        warmup_iterations=args.warmup_iterations,
        budget_ms=args.budget_ms,
    )
    payload = {
        "service_db_path": str(service._db_path),
        "dataset": dataset,
        "report": report,
    }

    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    markdown = format_benchmark_report_markdown(report, dataset, service_db_path=str(service._db_path))
    if args.output_markdown:
        output_markdown = Path(args.output_markdown)
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        output_markdown.write_text(markdown, encoding="utf-8")

    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
