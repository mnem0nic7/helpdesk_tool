# Azure FinOps Local Operator Guide

## Purpose

This guide is the operator-facing map for the local Azure FinOps lane inside `azure.movedocs.com`.

It explains:

- where the local FinOps data comes from
- which pages use export-backed analytics versus cache-backed operational data
- how allocation, recommendations, AI cost, and direct actions work
- what fallback and provenance signals mean
- what to check first when something looks wrong

## Local Architecture

The local parity model keeps the existing backend and Azure portal shell.

Operational stores:

- SQLite:
  - export delivery manifests
  - job state
  - alerts
  - workflow and audit metadata
- DuckDB:
  - normalized cost records
  - allocation rules and runs
  - persisted recommendations
  - AI usage records

Primary backend components:

- [azure_export_store.py](/workspace/altlassian/backend/azure_export_store.py)
- [azure_export_ingestor.py](/workspace/altlassian/backend/azure_export_ingestor.py)
- [azure_finops_service.py](/workspace/altlassian/backend/azure_finops_service.py)
- [routes_azure.py](/workspace/altlassian/backend/routes_azure.py)

## Data Flow

### 1. Export deliveries land

The export lane stages and parses Azure Cost Management deliveries from the configured local export root.

Current dataset families used by the local FinOps lane:

- `FOCUS`
- `Price Sheet`
- `Reservation Recommendations`

### 2. Deliveries sync into DuckDB

The local FinOps service imports parsed deliveries into normalized analytical tables.

Core facts:

- `cost_records`
- `price_sheet_rows`
- `reservation_recommendation_rows`
- `recommendations`
- `ai_usage_records`
- allocation tables

### 3. Existing Azure routes read from local analytics first

The current route families stay in place, but the source of truth shifts under them when local analytical data is available.

## Provenance By Surface

Use page badges and context callouts as source-of-truth hints.

### Export-backed analytical surfaces

- Azure Cost
- Azure AI Cost
- Azure Allocation
- Azure recommendation summary and recommendation workspace context
- Overview cost context

These are the right local surfaces for:

- cost visibility
- showback
- recommendation prioritization
- AI usage tracking

### Cache-backed operational drill-in surfaces

- Azure Resources
- Azure Compute
- Azure Storage
- Azure AVD cleanup
- most live inventory and identity drill-in pages

These stay valuable for operator action and validation, but they are not the finance-grade analytical source of truth.

### Mixed surfaces

- Azure Savings
- Azure Copilot grounding

These use persisted recommendation and/or export-backed cost context, while still relying on operational cache data for some drill-in details.

## Allocation Operations

The allocation engine is non-destructive.

Raw `cost_records` never change. Operators work with versioned rules and immutable runs.

Key policy:

- target dimensions:
  - `team`
  - `application`
  - `product`
- visible fallback buckets:
  - `Unassigned Team`
  - `Unassigned Application`
  - `Unassigned Product`
- visible shared buckets:
  - `Shared Team Costs`
  - `Shared Application Costs`
  - `Shared Product Costs`

Current portal workspace:

- [AzureAllocationPage.tsx](/workspace/altlassian/frontend/src/pages/AzureAllocationPage.tsx)

Related runbook:

- [azure-finops-allocation-engine.md](/workspace/altlassian/docs/runbooks/azure-finops-allocation-engine.md)

Operator interpretation:

- `direct` means a rule matched and assigned ownership explicitly
- `shared` means a deliberate split rule allocated a shared cost
- `fallback` means cost stayed visible in an unassigned bucket

If fallback stays high, tighten rules rather than hiding the bucket.

## Recommendation Operations

Recommendations now come from persisted local storage, not only ad hoc cache synthesis.

Current capabilities:

- list and detail
- dismiss and reopen
- action-state updates
- CSV/XLSX export
- Jira ticket creation
- Teams alerting
- safe remediation hook execution

Portal workspace:

- [AzureSavingsPage.tsx](/workspace/altlassian/frontend/src/pages/AzureSavingsPage.tsx)

Recommendation actions are admin-only.

History is the audit source for:

- ticket creation
- alert delivery
- dry-run and safe-hook execution
- failures and operator notes

## AI Cost Operations

All AI usage is expected to flow through Ollama in this deployment.

Current AI cost lane:

- provider and model rollups
- feature/app/team attribution
- local zero-cost or configured-cost pricing

Portal workspace:

- [AzureAICostPage.tsx](/workspace/altlassian/frontend/src/pages/AzureAICostPage.tsx)

If a non-Ollama provider appears in the AI Cost page, treat that as a regression.

## Safe Remediation Hooks

Safe hooks are allowlisted commands that receive structured JSON over stdin.

Guardrails:

- admin-only
- no arbitrary shell input from the portal
- allowlist comes from environment configuration
- dry-run is the default
- apply mode must be explicitly allowed per hook
- every run writes recommendation history

Focused runbook:

- [azure-finops-safe-remediation-hooks.md](/workspace/altlassian/docs/runbooks/azure-finops-safe-remediation-hooks.md)

## Performance Baseline

The million-row local analytical benchmark is checked in here:

- [azure-finops-local-performance-baseline.md](/workspace/altlassian/docs/runbooks/azure-finops-local-performance-baseline.md)

Current checked-in target:

- key analytical queries stay under `2s`

## Live Validation Status

One story is still external and remains the last non-doc blocker for full parity signoff:

- `FND-005` live export-backed validation

This means:

- the repo implementation is in place
- local synthetic and targeted verification is in place
- the authenticated validation and drift surface is now available in `/api/azure/finops/validation` and on the Azure Cost page
- live Azure delivery validation still needs a real environment window

## Troubleshooting

### Cost page or allocation page shows no data

Check:

1. export ingestion is enabled and parsed deliveries exist
2. DuckDB path is writable
3. `/api/azure/finops/status` shows available data
4. `/api/azure/finops/validation` shows whether signoff is blocked by missing deliveries, freshness warnings, or reconciliation drift

### Recommendation counts look wrong

Check:

1. export-backed recommendation inputs were imported
2. cached Azure inventory refreshed recently
3. the recommendation workspace source badges match the expected lane

### Allocation run is all fallback

Check:

1. the relevant rule is enabled in the latest version
2. the rule targets the same dimension as the run
3. the condition matches normalized field values, not portal labels

### AI Cost page shows another provider

Check:

1. Ollama is still the active provider in config
2. shared AI invocation paths were not bypassed
3. no stale non-Ollama usage records were written unexpectedly

### Safe hook action is blocked

Check:

1. `AZURE_FINOPS_SAFE_SCRIPT_HOOKS_JSON` is configured
2. the hook matches the recommendation category and opportunity type
3. the recommendation is not dismissed
4. apply mode is only attempted on hooks that explicitly allow it

## Operator Checklist

1. Confirm export deliveries are landing and parsing.
2. Confirm DuckDB-backed cost summary loads on the Cost page.
3. Confirm the FinOps Validation section on the Cost page shows the expected delivery health and reconciliation state.
4. Confirm the Allocation page has a recent run and visible fallback buckets.
5. Confirm the Savings page can show recommendation history and action contract state.
6. Confirm the AI Cost page shows Ollama-only usage.
7. Use live validation and reconciliation checks before treating the local lane as fully signed off for production finance reporting.
