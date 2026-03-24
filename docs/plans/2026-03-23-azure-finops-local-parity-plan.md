# Azure FinOps Local Parity Plan

## Goal

Extend the existing app into a local-first Azure FinOps platform without replacing the current FastAPI backend, current Azure routes, or current operator workflows.

This plan is the repo execution track for local parity with the Azure FinOps product brief:

- export-backed cost ingestion
- normalized local analytical model
- allocation
- persisted recommendations
- AI cost tracking
- direct action workflows

## Relationship To Existing Roadmap

Keep [2026-03-20-azure-cost-dashboard-roadmap.md](/workspace/altlassian/docs/plans/2026-03-20-azure-cost-dashboard-roadmap.md) as the Azure-native, ADLS, and BI roadmap.

Use this document for the repo-local parity track:

- keep the existing backend
- keep the existing Azure portal shell
- use local DuckDB for analytics
- preserve existing `/api/azure/*` contracts where practical

The two plans are compatible, but they are not the same:

- the March 20 roadmap is the external Azure + BI operating model
- this plan is the local engineering execution model

## Fixed Constraints

- Keep the current FastAPI backend and route structure.
- Keep the existing Azure portal as the product shell.
- Keep SQLite for operational metadata and workflow state.
- Use DuckDB as the local analytical store for cost, allocation, recommendation, and AI-usage facts.
- Prefer additive API changes over breaking route changes.
- Do not introduce Power BI, ADLS SDK migration, Fabric, or ADX as repo dependencies for parity scope.

## Current Starting Point

The repo is no longer at zero for this effort.

- A local export-backed analytics foundation now exists in `backend/azure_finops_service.py`.
- Parsed FOCUS deliveries can now hydrate a local DuckDB store.
- `/api/azure/cost/summary`, `/trend`, and `/breakdown` now prefer export-backed local analytics and fall back to `azure_cache`.
- The Azure Cost page now shows actual and amortized spend plus provenance.
- The export ingestion lane, manifest store, quarantine path, and freshness surfaces already exist from earlier Azure cost work.

This means Phase 1 is partially done and the remaining work is mainly structured build-out, not architecture discovery.

## Status Key

- `done`: acceptance is met for the current story scope.
- `in_progress_repo`: meaningful repo work is landed, but the story is not fully closed yet.
- `blocked_external`: the next meaningful step is mainly outside the repo.
- `not_started`: no meaningful story work is landed yet.

## Phase Map

- Phase 1 Foundation: `FND-001` through `FND-007`
- Phase 2 Allocation Engine: `ALLOC-001` through `ALLOC-005`
- Phase 3 Recommendation Engine: `RECO-001` through `RECO-006`
- Phase 4 AI Cost Tracking: `AI-001` through `AI-005`
- Phase 5 Action Layer: `ACT-001` through `ACT-005`
- Phase 6 Hardening: `OPS-001` through `OPS-004`

## Progress Snapshot

As of `2026-03-23`, the repo has the Phase 1 local foundation in place, including auxiliary pricing and commitment datasets. Export-backed cost context now extends beyond the Cost page into Overview, recommendation-summary surfaces, and explicit source-of-truth signals on cache-backed optimization pages. Persisted recommendation storage, recommendation workflow APIs, the portal-facing recommendation workspace, direct Jira follow-up creation, direct Teams alerting, explicit auth boundaries for the new FinOps APIs, the first million-row local performance baseline, the allocation backend core, the allocation portal workspace, the resource-cost bridge plus AKS visibility lane, safe remediation hooks, the local operator docs, and an authenticated FinOps validation report plus drift surface are now landed. The remaining work is live export validation in a real Azure delivery environment.

Current counts:

- Total stories: `32`
- `done`: `31`
- `in_progress_repo`: `0`
- `blocked_external`: `1`
- `not_started`: `0`

Phase summary:

- Phase 1 Foundation: `6 done`, `0 in_progress_repo`, `1 blocked_external`, `0 not_started`
- Phase 2 Allocation Engine: `5 done`, `0 in_progress_repo`, `0 blocked_external`, `0 not_started`
- Phase 3 Recommendation Engine: `6 done`, `0 in_progress_repo`, `0 blocked_external`, `0 not_started`
- Phase 4 AI Cost Tracking: `5 done`, `0 in_progress_repo`, `0 not_started`
- Phase 5 Action Layer: `5 done`, `0 in_progress_repo`, `0 not_started`
- Phase 6 Hardening: `4 done`, `0 blocked_external`, `0 not_started`

Current story status:

- `FND-001`: `done` - local DuckDB analytics store exists and is wired into the repo.
- `FND-002`: `done` - parsed FOCUS exports can populate normalized local cost records from the current export lane.
- `FND-003`: `done` - existing Azure cost routes and Azure Cost UI now consume export-backed local analytics with cache fallback.
- `FND-004`: `done` - the analytical model now exposes a field map, field-coverage metrics, and a reconciliation path against staged export summaries and cached totals.
- `FND-005`: `blocked_external` - repo-side validation and drift surfaces are landed, but full completion still requires live scheduled export deliveries for reconciliation and operational validation.
- `FND-006`: `done` - export-backed cost context now feeds Overview, Azure copilot grounding, recommendation-summary surfaces, and explicit provenance on compute and storage pages while keeping cache-backed drill-in behavior visible.
- `FND-007`: `done` - local auxiliary Price Sheet and Reservation Recommendation datasets can now be ingested, versioned, and stored in the local analytics lane.

- `ALLOC-001`: `done` - allocation target dimensions, fallback buckets, and initial shared-cost posture are now fixed in the repo and published in operator-facing docs.
- `ALLOC-002`: `done` - DuckDB now contains versioned allocation rule, run, run-rule, run-dimension, and result tables.
- `ALLOC-003`: `done` - the allocation engine now evaluates tag, regex, percentage, shared, and fallback rules deterministically.
- `ALLOC-004`: `done` - allocation runs, results, residuals, and rule-management APIs now exist without mutating raw cost records.
- `ALLOC-005`: `done` - the Azure portal now includes local Cost by Team and Cost by Application views on top of the allocation run APIs, with direct, fallback, and unallocated totals visible in the workspace.

- `RECO-001`: `done` - the normalized recommendation model now exists in the local FinOps store.
- `RECO-002`: `done` - persisted recommendation tables and refresh-state tracking now exist in DuckDB.
- `RECO-003`: `done` - current savings heuristics and reservation recommendation exports can now be materialized into persisted recommendation rows.
- `RECO-004`: `done` - recommendation list, detail, dismiss, reopen, export, history, and action-state endpoints now exist on the backend.
- `RECO-005`: `done` - export-backed cost facts can now bridge to cached Azure inventory, enrich persisted recommendation cost context, and emit explicit AKS visibility recommendation rows from managed-by cluster joins.
- `RECO-006`: `done` - Azure savings-oriented pages now consume persisted recommendation data instead of relying on ad hoc synthesis only.

- `AI-001`: `done` - AI usage records are emitted from the shared invocation layer, including Azure alert parsing.
- `AI-002`: `done` - provider and model pricing config exists with zero-cost local defaults and model overrides.
- `AI-003`: `done` - AI usage now resolves stable team attribution through explicit ownership, config-backed mappings, and safe built-in defaults by feature and app surface.
- `AI-004`: `done` - AI cost summary, trend, and breakdown APIs exist.
- `AI-005`: `done` - the Azure portal now includes a local AI Cost page with Ollama-backed provider visibility plus model-, app-, and team-based rollups.

- `ACT-001`: `done` - recommendation actions now have a normalized backend contract with explicit statuses, state bindings, metadata hints, and future-script guardrails.
- `ACT-002`: `done` - recommendations can now create Jira follow-up issues with mapped defaults, stored linkage, and failed-action visibility in history.
- `ACT-003`: `done` - recommendations can now send Teams alerts through the existing webhook delivery path with audited success and failure history.
- `ACT-004`: `done` - recommendation export and action history are now exposed through the portal-facing savings workspace.
- `ACT-005`: `done` - allowlisted safe remediation hooks can now run from the recommendation workspace in dry-run-first mode with explicit guardrails and audited history.

- `OPS-001`: `done` - a local benchmark harness now seeds million-row DuckDB datasets, measures the current cost, recommendation, and AI-cost paths, and publishes a checked-in baseline note with all measured queries under the 2 second target.
- `OPS-002`: `done` - the app now exposes an authenticated validation report that compares staged export totals, DuckDB totals, export health, and selected portal outputs with explicit mismatch states and signoff guidance.
- `OPS-003`: `done` - new local FinOps read APIs now require authentication, while direct recommendation actions remain explicitly admin-only.
- `OPS-004`: `done` - local operator docs now cover the analytical store, export sync behavior, provenance, allocation fallback, recommendation actions, AI cost, and safe remediation hooks.

## Architecture Decisions

### Backend

- Keep FastAPI.
- Keep current route modules.
- Keep `azure_cache` for live operational drill-in and fallback behavior.
- Add local analytical services under the current routes rather than replacing them.

### Data Stores

- SQLite remains the store for delivery metadata, jobs, alerts, and workflow state.
- DuckDB becomes the source of truth for analytical facts and local FinOps derivations.

### API Stability

- Preserve `/api/azure/cost/*`.
- Extend payloads additively with provenance and amortized fields.
- Migrate existing route families behind the same backend rather than replacing them.
- Add new API families only when the new capability is real:
  - `/api/azure/allocations/*`
  - `/api/azure/recommendations/*`
  - `/api/azure/ai-costs/*`

### UI Direction

- Evolve existing Azure Cost, Savings, Compute, and Storage views.
- Add new local pages for Allocation and AI Cost when the backend model is ready.
- Keep finance- and engineering-facing cost workflows inside the current portal for parity scope.

## Story Backlog

Execution constraint for every story below:

- keep the existing FastAPI backend
- keep current route families additive-first
- migrate existing Azure pages behind the current backend instead of replacing them with a new service or shell

### Phase 1 Foundation

- [ ] `FND-001` Stand up the local DuckDB analytical store. Priority: `Done`
  Acceptance: DuckDB file path is configurable; analytical tables exist; the backend can initialize the store without replacing the current app runtime.
  Status: `done`

- [ ] `FND-002` Load parsed FOCUS deliveries into normalized local cost records. Priority: `Done`
  Acceptance: Parsed FOCUS deliveries can populate normalized `CostRecord` rows with date, subscription, group, resource, service, meter, location, actual cost, amortized cost, usage quantity, tags, pricing model, and delivery provenance.
  Status: `done`

- [ ] `FND-003` Migrate existing cost routes to export-backed reads with fallback. Priority: `Done`
  Acceptance: `/api/azure/cost/summary`, `/trend`, and `/breakdown` prefer DuckDB-backed data and fall back cleanly to existing cached data when exports are unavailable.
  Status: `done`

- [ ] `FND-004` Harden the local `CostRecord` model and reconciliation path. Priority: `Now`
  Acceptance: The analytical model documents its field mapping; field coverage is expanded for tags, usage quantity, pricing model, and identifiers; one reconciliation path exists for comparing export-backed totals against staged export summaries and current cache outputs.
  Dependencies: `FND-001`, `FND-002`, `FND-003`
  Status: `done`

- [ ] `FND-005` Validate live export-backed operation in a real environment. Priority: `Now`
  Acceptance: Live scheduled deliveries populate DuckDB; expected freshness is visible; actual and amortized totals reconcile against live exports for the configured window; failure modes are documented.
  Dependencies: `FND-004`
  Status: `blocked_external`

- [ ] `FND-006` Expand the export-backed source-of-truth surface beyond the Cost page. Priority: `Now`
  Acceptance: Export-backed cost analytics are wired into the intended app-native source-of-truth surfaces such as Overview cost context, copilot grounding inputs, and future recommendation or allocation dependencies; fallback behavior remains explicit where cache-backed drill-in still owns the experience.
  Dependencies: `FND-004`
  Status: `done`

- [ ] `FND-007` Add local auxiliary dataset inputs for recommendation parity. Priority: `Now`
  Acceptance: The local analytics lane can ingest and version the non-FOCUS inputs needed for defensible savings estimates and commitment parity, starting with local Price Sheet and Reservation Recommendation style datasets or equivalent normalized inputs.
  Dependencies: `FND-004`
  Status: `done`

### Phase 2 Allocation Engine

- [ ] `ALLOC-001` Fix allocation target dimensions, fallback buckets, and shared-cost posture. Priority: `Now`
  Acceptance: The repo has one explicit definition for target dimensions such as team, application, and product; fallback buckets are named; the initial showback versus shared-cost posture is explicit enough to implement without churn.
  Dependencies: `FND-004`, `FND-006`
  Status: `done`

- [ ] `ALLOC-002` Add local allocation rule tables. Priority: `Now`
  Acceptance: DuckDB contains `allocation_rules` and `allocation_runs` or equivalent tables; rules can be versioned and attributed to a run.
  Dependencies: `ALLOC-001`
  Status: `done`

- [ ] `ALLOC-003` Implement rule evaluation in this order: tag, regex, percentage, shared, fallback. Priority: `Now`
  Acceptance: The engine applies rule types deterministically; fallback captures all otherwise-unallocated cost.
  Dependencies: `ALLOC-002`
  Status: `done`

- [ ] `ALLOC-004` Materialize allocation results and expose allocation APIs non-destructively. Priority: `Next`
  Acceptance: Raw cost records remain unchanged; allocation outputs are produced per run; total allocated plus residual equals source cost; the backend exposes runs, allocation results by dimension, unallocated residuals, and rule-management endpoints.
  Dependencies: `ALLOC-003`
  Status: `done`

- [ ] `ALLOC-005` Add Cost by Team and Cost by Application views. Priority: `Next`
  Acceptance: The Azure portal exposes local allocation views with direct cost, fallback-assigned cost, and unallocated totals.
  Dependencies: `ALLOC-004`
  Status: `done`

### Phase 3 Recommendation Engine

- [ ] `RECO-001` Define the normalized recommendation model. Priority: `Now`
  Acceptance: Recommendation storage captures type, resource, potential savings, effort, confidence, status, timestamps, and dismissal or action state.
  Dependencies: `FND-004`
  Status: `done`

- [ ] `RECO-002` Add persisted recommendation tables. Priority: `Now`
  Acceptance: DuckDB or SQLite stores normalized recommendations and action state without relying on transient cache snapshots.
  Dependencies: `RECO-001`
  Status: `done`

- [ ] `RECO-003` Extract current savings heuristics into a recommendation service. Priority: `Now`
  Acceptance: VM rightsizing, idle resource, storage or network cleanup, and commitment heuristics feed persisted recommendation rows.
  Dependencies: `RECO-002`, `FND-007`
  Status: `done`

- [ ] `RECO-004` Add recommendation APIs and workflow state transitions. Priority: `Next`
  Acceptance: The backend exposes recommendation list, detail, dismiss, reopen, export, and action-state endpoints.
  Dependencies: `RECO-003`
  Status: `done`

- [ ] `RECO-005` Add AKS cost visibility, cross-store joins, and recommendation inputs. Priority: `Next`
  Acceptance: Export-backed cost facts can be joined to current cache-backed Azure inventory and resource-level metadata; a resource-cost bridge exists for savings parity; node pool costs are aggregated and mapped to AKS recommendations or explicit AKS visibility records.
  Dependencies: `RECO-003`, `FND-006`, `FND-007`
  Status: `done`

- [ ] `RECO-006` Repoint Savings, Compute, and Storage pages to persisted recommendations. Priority: `Next`
  Acceptance: Existing Azure savings-oriented pages use persisted recommendation data rather than ad hoc synthesis only.
  Dependencies: `RECO-004`, `RECO-005`
  Status: `done`

### Phase 4 AI Cost Tracking

- [ ] `AI-001` Emit local AI usage records from the shared AI invocation layer. Priority: `Now`
  Acceptance: Every AI call records provider, model, feature surface, actor, latency, request count, and token estimate, including flows that bypass the current public `ai_client.py` helpers.
  Dependencies: `FND-004`
  Status: `done`

- [ ] `AI-002` Add provider and model pricing configuration. Priority: `Now`
  Acceptance: Pricing config can represent local Ollama zero-cost or estimated cost, later Azure OpenAI unit pricing, and token-estimation helpers for providers that do not return usage directly.
  Dependencies: `AI-001`
  Status: `done`

- [ ] `AI-003` Map AI usage to app and team dimensions. Priority: `Next`
  Acceptance: Usage can be rolled up by feature, app surface, actor, and team when that mapping exists, using explicit ownership mapping and allocation-aligned dimensions where available.
  Dependencies: `AI-001`, `AI-002`, `ALLOC-001`
  Status: `done`

- [ ] `AI-004` Add AI cost APIs. Priority: `Next`
  Acceptance: The backend exposes cost by model, cost by app, cost by team, and estimated cost per request trends.
  Dependencies: `AI-001`, `AI-002`
  Status: `done`

- [ ] `AI-005` Add AI cost UI. Priority: `Next`
  Acceptance: The Azure portal includes a local AI Cost page with model-, app-, and team-based rollups.
  Dependencies: `AI-004`
  Status: `done`

### Phase 5 Action Layer

- [ ] `ACT-001` Define the recommendation action contract. Priority: `Now`
  Acceptance: Recommendation actions have a normalized model for create-ticket, send-alert, export, and future safe-script flows.
  Dependencies: `RECO-001`
  Status: `done`

- [ ] `ACT-002` Add direct Jira ticket creation for recommendations. Priority: `Next`
  Acceptance: A recommendation can create a Jira issue with mapped fields, stored linkage, and error visibility.
  Dependencies: `ACT-001`, `RECO-004`
  Notes: This story includes the missing Jira issue-creation path plus the project, issue-type, and field-mapping decisions needed to make recommendation ticketing real.
  Status: `done`

- [ ] `ACT-003` Add direct Teams alerts for recommendations. Priority: `Next`
  Acceptance: A recommendation can send a Teams notification using existing alert plumbing, with audit status stored.
  Dependencies: `ACT-001`, `RECO-004`
  Status: `done`

- [ ] `ACT-004` Add recommendation export and action history. Priority: `Next`
  Acceptance: Users can export recommendation lists and inspect historical actions from the portal.
  Dependencies: `ACT-001`, `RECO-004`
  Status: `done`

- [ ] `ACT-005` Add safe action hooks for later remediation. Priority: `Later`
  Acceptance: The system supports safe script or workflow hooks behind explicit guardrails, without auto-enabling destructive actions.
  Dependencies: `ACT-001`, `ACT-002`, `ACT-003`
  Status: `done`

### Phase 6 Hardening

- [ ] `OPS-001` Add local performance and scale benchmarks. Priority: `Next`
  Acceptance: Million-row analytical load tests exist locally; key summary and breakdown queries stay within the agreed response budget; benchmark notes are checked in.
  Dependencies: `FND-004`, `ALLOC-003`, `RECO-003`
  Status: `done`

- [ ] `OPS-002` Add live reconciliation and drift checks. Priority: `Next`
  Acceptance: The app can compare staged export totals, DuckDB totals, and selected portal outputs; mismatches are surfaced clearly.
  Dependencies: `FND-005`
  Status: `done`

- [ ] `OPS-003` Apply RBAC-ready boundaries to new local FinOps APIs. Priority: `Next`
  Acceptance: Read and write operations for allocations, recommendations, and actions follow the existing auth model and respect admin-only mutations where needed.
  Dependencies: `ALLOC-004`, `RECO-004`, `ACT-001`
  Status: `done`

- [ ] `OPS-004` Publish local FinOps operator docs. Priority: `Next`
  Acceptance: Runbooks cover the local analytical store, export sync behavior, provenance, fallback behavior, and troubleshooting for the new FinOps surfaces.
  Dependencies: `FND-005`, `ALLOC-005`, `RECO-006`, `AI-005`, `ACT-004`
  Status: `done`

## Execution Board

### Start Queue

1. `FND-005`

### Hard Gates

- `OPS-001` is now complete, so later phases have a checked-in local baseline for the current cost, recommendation, and AI-cost query surfaces.
- `FND-006` is now complete and has unblocked later lanes that need the export-backed cost model to be the app's broader source of truth rather than a Cost-page-only lane.
- `FND-007` is now complete and has unblocked defensible savings estimates plus commitment-parity stories that need more than FOCUS-only inputs.
- `ALLOC-001` -> `ALLOC-002` -> `ALLOC-003` -> `ALLOC-004` -> `ALLOC-005` is now complete; the allocation backend and portal lane are both landed.
- `RECO-001` -> `RECO-002` -> `RECO-003` -> `RECO-004` -> `RECO-005` is now complete; the recommendation backend lane is functionally in place.
- `ACT-001` -> `ACT-005` is now complete; the direct-action lane includes Jira, Teams, export, and guarded safe-hook execution.
- `OPS-002` is now complete and has reduced the remaining live-validation work to gathering real Azure delivery evidence.
- `FND-005` is the final external gate and stays blocked until real deliveries are in place.

### Wave Plan

- Wave 1: `FND-005`

### Parallel Batches

- No repo-safe implementation work remains in this plan.
- The remaining parity work is external validation against live Azure export deliveries.

## Current Next Queue

### 1. `FND-005` Validate live export-backed operation

- Use real scheduled deliveries to confirm that the local analytical lane stays healthy with actual Azure exports, not only synthetic benchmark data.
- Confirm that the allocation workspace remains correct once live export-backed cost records are arriving on schedule.

### 2. Repo-Safe Lane Status

- No additional repo-safe implementation stories remain.
- The local parity track is now waiting on live export validation evidence.
- Keep destructive remediation out of scope for v1.

## Completion Definition

This local parity plan is complete when:

- export-backed local cost analytics are stable and reconciled
- all cost is allocatable through local rules with explicit fallback
- recommendations are persisted and drive the savings-oriented UI
- AI usage and cost are visible locally
- users can act on recommendations directly from the app
- operator docs and performance checks exist for the shipped scope
