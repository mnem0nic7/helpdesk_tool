# Azure FinOps Allocation Engine

## Purpose

The local allocation engine turns export-backed Azure cost facts into non-destructive showback runs without changing the raw `cost_records` source data.

The backend implementation lives in:

- [azure_finops_service.py](/workspace/altlassian/backend/azure_finops_service.py)
- [routes_azure.py](/workspace/altlassian/backend/routes_azure.py)

## Fixed Policy

Target dimensions:

- `team`
- `application`
- `product`

Named fallback buckets:

- `team` -> `Unassigned Team`
- `application` -> `Unassigned Application`
- `product` -> `Unassigned Product`

Named shared buckets:

- `team` -> `Shared Team Costs`
- `application` -> `Shared Application Costs`
- `product` -> `Shared Product Costs`

Shared-cost posture:

- Shared costs stay visible in explicit named shared buckets until an intentional split rule allocates them.
- Fallback is not hidden. If cost does not match a direct or shared rule, it lands in the dimension-specific `Unassigned ...` bucket.

## Supported Rule Types

Rules are evaluated in this order:

1. `tag`
2. `regex`
3. `percentage`
4. `shared`
5. fallback

Supported match fields:

- `subscription_id`
- `subscription_name`
- `resource_group`
- `resource_name`
- `resource_id`
- `service_name`
- `meter_category`
- `location`
- `pricing_model`
- `charge_type`
- `scope_key`
- `currency`
- `tags.<key>`

Rule payload examples:

```json
{
  "name": "Tag based team owner",
  "rule_type": "tag",
  "target_dimension": "team",
  "priority": 10,
  "condition": {
    "tag_key": "team",
    "tag_value": "Platform"
  },
  "allocation": {
    "value": "Platform Team"
  }
}
```

```json
{
  "name": "Split shared networking",
  "rule_type": "shared",
  "target_dimension": "team",
  "priority": 40,
  "condition": {
    "field": "resource_group",
    "pattern": "^rg-shared$"
  },
  "allocation": {
    "splits": [
      {"value": "Infra Shared", "percentage": 50},
      {"value": "Security Shared", "percentage": 50}
    ]
  }
}
```

Notes:

- `percentage` accepts either `0-1` fractions or `0-100` percentages.
- `shared` split percentages must total `100%`.
- Fallback is implicit and is not stored as a user-managed rule.

## Persistence Model

DuckDB tables:

- `allocation_rules`
- `allocation_runs`
- `allocation_run_rules`
- `allocation_run_dimensions`
- `allocation_results`

Key behaviors:

- Rules are versioned by `rule_id` + `rule_version`.
- Runs store the exact rule versions used at execution time.
- Raw `cost_records` remain unchanged.
- Results are materialized per run and per target dimension.

## API Surface

Authenticated read routes:

- `GET /api/azure/allocations/policy`
- `GET /api/azure/allocations/status`
- `GET /api/azure/allocations/rules`
- `GET /api/azure/allocations/runs`
- `GET /api/azure/allocations/runs/{run_id}`
- `GET /api/azure/allocations/runs/{run_id}/results?dimension=team`
- `GET /api/azure/allocations/runs/{run_id}/residuals?dimension=team`

Admin-only mutation routes:

- `POST /api/azure/allocations/rules`
- `POST /api/azure/allocations/rules/{rule_id}/deactivate`
- `POST /api/azure/allocations/runs`

## Residual Interpretation

The engine guarantees run-level coverage by assigning unmatched cost to the dimension fallback bucket.

In this implementation:

- `direct_allocated_*` means cost allocated by explicit tag, regex, percentage, or shared rules.
- `residual_*` means cost that fell through to the dimension fallback bucket.
- `total_allocated_* = direct_allocated_* + residual_*`

This keeps allocation honest:

- nothing disappears
- fallback-assigned cost is measurable
- operators can target the biggest unassigned buckets with better rules

## Operator Workflow

1. Create or version rules through the allocation rule API.
2. Trigger a run for one or more dimensions.
3. Review run summaries and residual buckets.
4. Tighten rules where fallback buckets stay high.
5. Repeat until the allocation mix is good enough to expose in the portal UI.

## Troubleshooting

If a run shows only fallback buckets:

- verify the rule is still enabled in the latest version
- confirm the rule targets the same dimension as the run
- confirm the condition field exists on `cost_records`
- confirm regex patterns match the normalized field values, not portal labels

If a shared rule fails validation:

- make sure every split has a non-empty `value`
- make sure split percentages total `100%`

If a rule change does not affect an old run:

- that is expected
- runs are immutable snapshots of the rule versions used when the run executed
