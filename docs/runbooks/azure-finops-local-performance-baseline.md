# Azure FinOps Local Performance Baseline

## Purpose

This note records the first checked-in local benchmark baseline for the DuckDB-backed Azure FinOps analytics lane.

It exists to support `OPS-001` in [2026-03-23-azure-finops-local-parity-plan.md](/workspace/altlassian/docs/plans/2026-03-23-azure-finops-local-parity-plan.md) and gives us a measured starting point before allocation joins and later recommendation expansion add more load.

## Benchmark Command

Run from repo root:

```bash
python3 backend/scripts/benchmark_finops_queries.py \
  --cost-records 1000000 \
  --recommendations 50000 \
  --ai-usage-records 200000 \
  --lookback-days 30 \
  --iterations 3 \
  --warmup-iterations 1
```

## Dataset

- Cost records: `1,000,000`
- Recommendations: `50,000`
- AI usage records: `200,000`
- Lookback days: `30`
- Query budget: `2,000 ms`
- Baseline captured on: `2026-03-23`

## Results

| Query | Mean (ms) | P95 (ms) | Max (ms) | Budget | Pass |
| --- | ---: | ---: | ---: | ---: | --- |
| `cost_summary` | `471.304` | `600.872` | `619.619` | `2000` | `yes` |
| `cost_trend` | `294.213` | `344.165` | `351.341` | `2000` | `yes` |
| `cost_breakdown_service` | `309.763` | `354.338` | `359.841` | `2000` | `yes` |
| `cost_breakdown_subscription` | `233.687` | `244.770` | `245.901` | `2000` | `yes` |
| `recommendation_summary` | `201.528` | `254.993` | `262.915` | `2000` | `yes` |
| `recommendation_list_quantified` | `666.328` | `817.178` | `834.926` | `2000` | `yes` |
| `ai_cost_summary` | `192.713` | `231.855` | `235.241` | `2000` | `yes` |
| `ai_cost_trend` | `94.553` | `110.069` | `110.292` | `2000` | `yes` |
| `ai_cost_breakdown_model` | `102.328` | `126.448` | `130.178` | `2000` | `yes` |

## Notes

- The first benchmark pass exposed recommendation-summary and recommendation-list regressions over budget because recommendation filtering and rollups were still happening in Python after loading the full workspace.
- The current baseline includes the follow-up optimization that moved recommendation filtering, ordering, and summary aggregation into DuckDB.
- The cost and AI usage lanes were already comfortably within the `2s` response target at this data volume.
- This baseline covers the current Phase 1, Phase 3, and Phase 4 query surfaces only. Allocation and future AKS joins should extend the same harness instead of creating a separate benchmark path.

## Operational Guidance

- Re-run this benchmark after:
  - allocation tables or allocation-result joins land
  - AKS cost joins land
  - recommendation search semantics expand materially
  - AI usage attribution or pricing logic adds large new dimensions
- Treat a budget miss here as a release warning for the local analytical lane, even if the app still functions correctly.
