# Azure Cost Dashboard Roadmap

## Goal

Move the current Azure cost experience from a custom, cache-backed operations portal to a two-layer model:

1. Azure Cost Management for native analysis, budgets, anomaly detection, and governance controls.
2. Cost Management exports to lake storage as the reporting source for Power BI and later FinOps-scale analytics.

## Current State

The repo already has a strong Azure operations portal, but it is not yet structured like a Cost Management export and BI platform.

- Cost data is pulled directly from the Azure Cost Management query API at request-refresh time, not from exported datasets.
- The backend builds its own cached snapshots for cost trend, cost breakdowns, advisor recommendations, and synthesized savings opportunities.
- The frontend exposes this data through an Azure-specific portal with pages for overview, cost, savings, compute, storage, alerts, and account health.
- The repo has export features today, but they are app-generated CSV/XLSX outputs for VM coverage, RI excess, savings opportunities, and VM cost workbooks rather than Cost Management exports to ADLS Gen2.
- There is no repo evidence of Power BI datasets, Fabric assets, ADLS export orchestration, FOCUS ingestion, price sheet ingestion, reservation recommendation ingestion, budgets, anomaly workflows, tag inheritance automation, or cost allocation workflows.

## Keep / Change

### Keep

- Keep the existing Azure portal as the engineering and operations cockpit.
- Keep the existing live cache for fast drill-in on resources, VMs, reservations, and synthesized savings actions.
- Keep the existing savings heuristics and alerts as a product differentiator for operators.

### Change

- Stop treating the custom portal as the only reporting layer.
- Make Azure Cost Management the native source for exploration, budgets, saved views, and anomaly monitoring.
- Add an export-backed analytics layer for finance, showback, chargeback, and commitment reporting.
- Treat Power BI as the shared reporting surface for finance and engineering stakeholders.

## Gap Analysis

### 1. Native Cost Management governance is missing

The current app surfaces cached Azure data and app-level alerts, but not Azure-native budgets, anomaly alerts, scheduled alerts, saved Cost Analysis views, tag inheritance, or cost allocation constructs.

Impact:

- Finance and engineering do not yet share one governed source for budget and anomaly workflows.
- The current alerting model is application-owned instead of using Azure Cost Management controls where they fit best.

### 2. The data pipeline is query-driven, not export-driven

Current cost ingestion is built around direct Cost Management query API calls and cached snapshot refreshes.

Impact:

- Reporting depends on repeated query execution and cache freshness.
- There is no durable lake-backed dataset for Power BI, historical reconciliation, or downstream FinOps tooling.
- Scale, refresh time, and cross-team reuse will eventually be constrained by the app cache model.

### 3. Reporting is portal-native, not BI-native

The frontend already exposes useful operational views, but it does not match the desired Power BI operating model with executive summary, cost drivers, waste/actions, commitments/discounts, and chargeback/allocation pages backed by export data.

Impact:

- Current views are excellent for operators, but weaker for finance-style reporting, trend governance, and repeatable stakeholder distribution.
- There is no semantic model that can be reused outside the app.

### 4. Export support exists, but at the wrong layer

Current exports are generated from application snapshots and job queues. They are useful operationally, but they are not Azure Cost Management exports like FOCUS, Price sheet, or Reservation recommendations.

Impact:

- Exported workbooks help one-off analysis but do not create a reusable analytics foundation.
- The app is still responsible for shaping downstream reporting data instead of handing off to a standardized export pipeline.

### 5. Commitment reporting is partial

The repo already understands reservation inventory, RI coverage gaps, and excess reservations, but it does not ingest reservation recommendations, reservation details, reservation transactions, or savings plan utilization datasets.

Impact:

- Commitment strategy is visible, but still partially heuristic and intentionally unquantified in parts of the UI.
- Monthly commitment review workflows will remain incomplete until export datasets are added.

## Recommended Target Shape

Use the repo as an operator-facing Azure portal on top of a broader FinOps data platform.

- Azure Cost Management:
  Native cost analysis, saved views, budgets, anomaly review, scheduled alerts.
- ADLS Gen2:
  Durable landing zone for Cost Management exports.
- Export datasets:
  FOCUS first, then Price sheet and Reservation recommendations, with Reservation details and Reservation transactions as phase-two additions.
- Power BI:
  Shared finance and engineering dashboard using the export datasets.
- Existing app:
  Continue serving operational drill-down, synthesized savings actions, VM optimization, alerting, and copilot experiences.

## Roadmap

### Phase 0: Align ownership and reporting scope

Duration: 3 to 5 days

- Confirm billing model and supported reporting scope: billing profile, management group, or subscription.
- Decide whether the app remains engineering-first while Power BI becomes the shared finance/showback surface.
- Define the canonical business dimensions: application, environment, owner, cost center, business unit.
- Decide whether chargeback will be informational only at first or whether you need shared-cost allocation from day one.

Exit criteria:

- One agreed reporting scope.
- One agreed tag dictionary.
- One owner each for FinOps, Azure platform, and BI.

### Phase 1: Enable native Azure Cost Management controls

Duration: 1 week

- Create and document the required Cost Analysis saved views.
- Configure budgets at the top reporting scope and a few high-risk subscopes.
- Turn on Azure-native anomaly monitoring where supported.
- Configure scheduled summaries or action-group based notifications for finance and engineering leads.
- Document required Azure roles separately from app roles.

Repo impact:

- Mostly documentation and operational runbooks.
- Add the operator handoff note in `docs/runbooks/azure-reporting-handoff-runbook.md` so the Azure Overview launchpad and source badges are easy to interpret.
- Optional future enhancement: expose deep links from the Azure portal pages into the matching Azure Cost Analysis saved views.

Exit criteria:

- Budgets active.
- Saved views standardized.
- Anomaly and scheduled alert coverage defined.

### Phase 2: Build the export landing zone

Duration: 1 to 2 weeks

- Provision an ADLS Gen2 storage account and folder layout for cost exports.
- Configure Cost Management exports for:
  FOCUS
  Price sheet
  Reservation recommendations
- Add optional exports for Reservation details and Reservation transactions if commitment reporting is in scope for v1.
- Define a lightweight ingestion contract:
  export path conventions
  partitioning
  freshness checks
  retention
  schema version notes

Repo impact:

- Add a small configuration surface for external export locations and freshness metadata if the app should display export health.
- Do not replace the current live cache yet.

Exit criteria:

- Daily exports land successfully.
- Export freshness can be verified without opening the portal manually.

### Phase 3: Stand up Power BI as the shared reporting layer

Duration: 1 to 2 weeks

- Build the initial Power BI model from export data, starting with FOCUS.
- Add Price sheet enrichment where pricing fields are incomplete.
- Add reservation recommendation reporting for commitment opportunities.
- Implement the five-page dashboard:
  Executive summary
  Cost drivers
  Waste and actions
  Commitments and discounts
  Chargeback / allocation

Repo impact:

- Minimal code change is required unless you want:
  links from the app to the published Power BI report
  an embedded Power BI tab
  export freshness surfaced in the Azure portal overview

Exit criteria:

- One shared dashboard used by finance and engineering.
- Daily refresh working from exports.
- Executive, engineering, and chargeback views all available.

### Phase 4: Integrate the portal with the BI layer

Duration: 3 to 5 days

- Add links or embedded entry points from the current Azure portal to Power BI pages.
- Add export freshness and data-source provenance to the Azure Overview page.
- Decide which current portal views should remain app-native versus redirect to Power BI.
- Keep app-native pages where the portal adds operational value:
  VM optimization
  storage cleanup
  reservation gap heuristics
  custom alerting
  copilot workflows

Exit criteria:

- Clear user journey between Azure portal operations and BI reporting.
- No ambiguity about where to go for finance versus remediation workflows.

### Phase 5: Close commitment and chargeback gaps

Duration: 1 week

- Add reservation details and transactions if not already present.
- Add savings plan utilization if your agreement and tooling support require it.
- Implement chargeback/showback logic using export data and allocation rules.
- Revisit the current unquantified commitment heuristics and replace them with export-backed metrics where possible.

Exit criteria:

- Commitment review is backed by durable datasets, not only heuristics.
- Chargeback and shared-cost reporting are reproducible.

### Phase 6: Scale path

Trigger only if needed.

- Move from direct storage reporting to FinOps hubs if refresh times, volume, or tenant count become a problem.
- Consider Azure Data Explorer or Fabric Real-Time Intelligence only after the export-backed Power BI layer is stable and visibly constrained.

## Story Backlog

### Phase-to-Story Map

- Phase 0: `GOV-001`, `GOV-002`, `GOV-003`, `GOV-004`
- Phase 1: `GOV-005`, `GOV-006`, `GOV-007`
- Phase 2: `DATA-001`, `DATA-002`, `DATA-003`, `DATA-004`, `DATA-006`, `DATA-007`, `DATA-008`
- Phase 3: `BI-001`, `BI-002`, `BI-003`, `BI-004`, `BI-005`, `BI-006`, `BI-007`, `BI-008`, `BI-009`
- Phase 4: `APP-001`, `APP-002`, `APP-003`, `APP-004`, `APP-005`, `APP-006`, `APP-007`, `APP-008`, `DATA-009`
- Phase 5: `DATA-005`, `DATA-010`, `BI-011`, `BI-012`
- Phase 6: `BI-010`

### Progress Update

As of `2026-03-20`, the repo groundwork is materially ahead of the full program. Most remaining work is now external to the repo: Azure signoff, Azure RBAC and provisioning, live Cost Management exports, and Power BI assets.

Status key:

- `done`: acceptance is met for the current story scope.
- `in_progress_repo`: meaningful repo work is landed, but the story is not fully closed yet.
- `blocked_external`: the next meaningful step is mainly outside the repo.
- `not_started`: no meaningful story work has been landed yet.

Current counts:

- Total stories: `37`
- `done`: `1`
- `in_progress_repo`: `6`
- `blocked_external`: `17`
- `not_started`: `13`

Phase summary:

- Phase 0: `3 blocked_external`, `1 not_started`
- Phase 1: `3 not_started`
- Phase 2: `2 in_progress_repo`, `3 blocked_external`, `2 not_started`
- Phase 3: `9 blocked_external`
- Phase 4: `1 done`, `4 in_progress_repo`, `2 blocked_external`, `2 not_started`
- Phase 5: `4 not_started`
- Phase 6: `1 not_started`

Current story status:

- `GOV-001`: `blocked_external` - scope decision and billing hierarchy drafts exist, but finance and engineering signoff is still external.
- `GOV-002`: `blocked_external` - ownership matrix, access matrix, and access-request runbook exist, but real DRI assignment and Azure RBAC are still external.
- `GOV-003`: `blocked_external` - tag policy, baseline audit, and remediation runbook exist, but ratification, inheritance decisions, and remediation ownership are still external.
- `GOV-004`: `not_started` - the showback versus shared-cost allocation decision does not yet have a dedicated repo artifact.
- `GOV-005`: `not_started` - no saved-view catalog or launch-URL pack is published yet.
- `GOV-006`: `not_started` - budgets, anomaly monitoring, and scheduled notifications are still Azure-side setup work.
- `GOV-007`: `not_started` - the governance operating cadence and app handoff boundary are not yet published as a dedicated artifact.

- `DATA-001`: `blocked_external` - the landing-zone contract, runbook, and metadata store foundation exist, but real ADLS Gen2 provisioning and RBAC validation are still external.
- `DATA-002`: `blocked_external` - FOCUS ingestion scaffolding is landed, but completion requires live scheduled FOCUS deliveries.
- `DATA-003`: `not_started` - Price Sheet ingestion is not implemented yet.
- `DATA-004`: `not_started` - Reservation Recommendations ingestion is not implemented yet.
- `DATA-005`: `not_started` - optional Reservation Details and Transactions pipelines are not implemented yet.
- `DATA-006`: `blocked_external` - export freshness and health are surfaced in-product, but completion depends on live dataset cadence and real deliveries.
- `DATA-007`: `in_progress_repo` - schema and parser version tracking is implemented for the current FOCUS lane, but broader dataset coverage is still ahead.
- `DATA-008`: `in_progress_repo` - config, provenance, reporting handoff, and export health touchpoints are landed, but the full migration and dataset config surface is not fully closed.
- `DATA-009`: `not_started` - `/api/azure/cost/*` is still query-driven and has not been cut over to export-backed reads.
- `DATA-010`: `not_started` - savings-plan utilization ingestion is not implemented or documented yet.

- `BI-001`: `blocked_external` - live exports and a real Power BI refresh path are still missing.
- `BI-002`: `blocked_external` - no semantic model or star schema exists yet, and it depends on upstream BI and governance milestones.
- `BI-003`: `blocked_external` - measures and reconciliation rules depend on a real semantic layer and export-backed data.
- `BI-004`: `blocked_external` - no Power BI report shell, workspace, or distribution model exists yet.
- `BI-005`: `blocked_external` - the Executive Summary page depends on BI foundations that are not in place yet.
- `BI-006`: `blocked_external` - the Cost Drivers page depends on the semantic layer, measures, and report shell.
- `BI-007`: `blocked_external` - the Waste and Actions page depends on export-backed BI assets that do not exist yet.
- `BI-008`: `blocked_external` - the Commitments and Discounts page depends on BI foundations plus live recommendation data.
- `BI-009`: `blocked_external` - the Chargeback and Allocation page depends on BI foundations and an allocation posture decision.
- `BI-010`: `not_started` - scale-up triggers should wait until the base BI layer is running in production.
- `BI-011`: `not_started` - later commitments-page expansion work should wait for the base BI layer and optional datasets.
- `BI-012`: `not_started` - later shared-cost allocation deepening should wait for baseline showback.

- `APP-001`: `in_progress_repo` - the Overview now separates governed reporting handoff from operational workflows, but there is no explicit published IA or nav split yet.
- `APP-002`: `in_progress_repo` - the Overview launchpad exists with Power BI and Cost Analysis targets, unconfigured handling, and explanatory copy, but it still depends on real external targets and final IA.
- `APP-003`: `blocked_external` - Cost Analysis deep-link mapping depends on published saved views and final IA decisions.
- `APP-004`: `blocked_external` - the minimal Power BI handoff target exists, but the full integration shell depends on a real BI report.
- `APP-005`: `done` - export freshness and provenance are surfaced in-product separately from cache freshness, with source badges and fallback messaging.
- `APP-006`: `not_started` - the retained-vs-redirected page matrix is not yet published.
- `APP-007`: `in_progress_repo` - Cost, Overview, and Savings now show source badges and reporting handoff copy, but the broader route matrix and labeling cleanup are not fully finished.
- `APP-008`: `in_progress_repo` - targeted tests and operator docs exist for the launchpad and provenance surface, but the broader blended-experience coverage is not fully complete.

Current next queue:

1. External signoff for `GOV-001`, `GOV-002`, and `GOV-003`
2. ADLS Gen2 provisioning and RBAC validation for `DATA-001`
3. Live scheduled FOCUS export landing for `DATA-002` and `DATA-006`
4. Azure Cost Analysis saved-view publication for `GOV-005` and `APP-003`
5. Power BI workspace, report shell, and refresh path for `BI-001` through `BI-004`

### Governance Stories

- [ ] `GOV-001` Lock reporting scope and billing hierarchy. Priority: `Now`
  Why: Budgets, saved views, anomalies, and exports only work predictably when v1 has one canonical governance scope.
  Acceptance: The v1 scope of record is documented as billing profile, management group, or subscription; supported child scopes and high-risk subscopes are named; finance and engineering agree this is the reporting scope of record.
  Dependencies: None.

- [ ] `GOV-002` Establish cost governance ownership and Azure access matrix. Priority: `Now`
  Why: Native Cost Management controls introduce Azure RBAC and operating ownership that are different from current app roles.
  Acceptance: DRIs are named for FinOps, Azure platform, BI, and app integration; required Azure permissions for Cost Analysis, budgets, anomaly review, and export setup are documented; the access-request path is defined.
  Dependencies: `GOV-001`.

- [ ] `GOV-003` Standardize the v1 tag dictionary and compliance policy. Priority: `Now`
  Why: Showback, chargeback, and BI slicing will be unreliable without canonical business dimensions.
  Acceptance: Canonical tag keys and value rules exist for application, environment, owner, cost center, and business unit; required vs optional tags are documented; the remediation path for missing tags is assigned; the decision on tag inheritance timing is recorded.
  Dependencies: `GOV-001`, `GOV-002`.

- [ ] `GOV-004` Decide v1 showback and shared-cost allocation posture. Priority: `Now`
  Why: The BI and export design depends on whether v1 is informational showback only or includes shared-cost allocation.
  Acceptance: The decision is documented as showback only or showback plus shared-cost allocation; if allocation is in scope, shared-cost pools, drivers, ownership, and exceptions are defined; if not, the deferral boundary is explicit.
  Dependencies: `GOV-001`, `GOV-003`.

- [ ] `GOV-005` Publish the standard Azure Cost Analysis saved-view pack. Priority: `Next`
  Why: Azure Cost Management needs a shared native exploration surface for finance and engineering.
  Acceptance: Saved views exist for top-scope overview, service drivers, subscription and resource-group drill-in, tag-based views, and anomaly follow-up; sharing conventions and launch URLs are documented.
  Dependencies: `GOV-001`, `GOV-003`.

- [ ] `GOV-006` Configure budget, anomaly, and scheduled notification guardrails. Priority: `Next`
  Why: Native governance controls are a core part of the target model and should stop living only in app-owned alerting.
  Acceptance: Budgets are active at the canonical scope and chosen high-risk subscopes; anomaly monitoring is enabled where supported; scheduled summaries or action-group based notifications are configured; at least one notification path is test-verified.
  Dependencies: `GOV-001`, `GOV-002`, `GOV-004`, `GOV-005`.

- [ ] `GOV-007` Define the governance operating cadence and app handoff boundary. Priority: `Next`
  Why: Azure-native controls and the app must have clear ownership boundaries and review rhythms.
  Acceptance: Daily anomaly review, weekly budget and tag hygiene review, and monthly governance review are defined; Azure-native ownership vs app ownership is documented; app-owned Azure alerts are explicitly positioned as parallel operational tooling rather than the source of truth for cost governance.
  Dependencies: `GOV-005`, `GOV-006`.

### Data Pipeline Stories

- [ ] `DATA-001` Provision the ADLS Gen2 landing zone and export path contract. Priority: `Now`
  Why: Every export-backed workflow depends on a durable storage layout and RBAC model.
  Acceptance: One ADLS Gen2 landing zone is provisioned; dataset paths are standardized by dataset, scope, and delivery date or run; RBAC, retention, and lifecycle rules are validated and documented.
  Dependencies: `GOV-001`, `GOV-002`.

- [ ] `DATA-002` Enable FOCUS export and staged ingestion. Priority: `Now`
  Why: FOCUS is the main replacement for current live query-backed cost summary, trend, and breakdown reads.
  Acceptance: Daily FOCUS exports land in ADLS; ingestion records path, scope, delivery time, row count, and parse status in a manifest; a staged model exists for the columns needed by cost summary, trend, and breakdown consumers.
  Dependencies: `DATA-001`.

- [ ] `DATA-003` Ingest Price Sheet as a versioned pricing dimension. Priority: `Next`
  Why: Price enrichment is needed for pricing gaps, allocation logic, and commitment analysis.
  Acceptance: Price Sheet exports land on their expected cadence; staged pricing rows are effective-dated or versioned; downstream joins surface unmatched pricing rows explicitly.
  Dependencies: `DATA-001`, `DATA-002`.

- [ ] `DATA-004` Ingest Reservation Recommendations as export-backed commitment opportunities. Priority: `Next`
  Why: Current commitment gaps and excesses are heuristic and partially unquantified.
  Acceptance: Reservation Recommendation exports land daily; a normalized recommendation dataset is produced by scope, SKU, region, term, and savings fields; downstream consumers can distinguish export-backed commitment opportunities from heuristic rows.
  Dependencies: `DATA-001`, `DATA-002`.

- [ ] `DATA-005` Add optional Reservation Details and Reservation Transactions pipelines behind scope flags. Priority: `Later`
  Why: Commitment reporting depth should be extensible without forcing extra datasets into v1.
  Acceptance: Reservation Details and Transactions can be enabled or disabled per environment; when disabled the system reports not in scope rather than failed; when enabled they share the same manifest, freshness, and schema checks as core exports.
  Dependencies: `DATA-001`, `GOV-004`.

- [ ] `DATA-010` Add a savings-plan utilization ingestion path if supported. Priority: `Later`
  Why: Phase 5 calls for savings-plan utilization review, but the backlog needs an explicit data story to make that possible.
  Acceptance: The team confirms the supported source for savings-plan utilization data; if available, the data lands with the same freshness and provenance rules as other commitment datasets; if unavailable, the roadmap records it as unsupported rather than silently omitting it.
  Dependencies: `GOV-001`, `DATA-001`.

- [ ] `DATA-006` Build export freshness and delivery health checks. Priority: `Now`
  Why: The app currently shows only cache freshness and needs export health before it can point users to governed reporting.
  Acceptance: A checker marks each enabled dataset as healthy, stale, missing, or parse-failed; last successful delivery time and lag are recorded; backend APIs can expose this status without manual Azure inspection.
  Dependencies: `DATA-002` and whichever export datasets are enabled.

- [ ] `DATA-007` Implement schema and parser version tracking. Priority: `Next`
  Why: Export schemas will drift over time and should not silently break ingestion.
  Acceptance: Every ingested delivery records dataset name, schema signature, parser version, and compatibility result; additive changes do not break ingestion; incompatible deliveries are quarantined while the last good staged output remains available.
  Dependencies: `DATA-002`, `DATA-003`, `DATA-004`, and `DATA-005` if optional reservation datasets are enabled.

- [ ] `DATA-008` Add repo config and provenance touchpoints for export-backed reporting. Priority: `Next`
  Why: Current config only models cache and workbook export behavior, not ADLS-backed reporting.
  Acceptance: Backend config supports export roots, enabled datasets, expected cadence, and migration flags; overview or status APIs include export freshness and provenance alongside cache status; the UI can render export health without breaking current payloads.
  Dependencies: `DATA-006`.

- [ ] `DATA-009` Run a phased migration from query-driven cache reads to export-backed cost reads. Priority: `Next`
  Why: The current `/api/azure/cost/*` surface is query-driven, so cutover should be controlled and measurable.
  Acceptance: Export-backed read models exist for cost summary, trend, service or subscription or resource-group breakdowns, and commitment opportunities; feature flags support side-by-side comparison with current outputs; VM and resource drill-in stays cache-backed until explicitly migrated.
  Dependencies: `DATA-002`, `DATA-003`, `DATA-004`, `DATA-006`, `DATA-007`, `DATA-008`.

### BI Stories

- [ ] `BI-001` Build export-backed Power BI staging datasets. Priority: `Next`
  Why: Power BI should refresh from durable exports rather than the live portal cache or app-generated workbook exports.
  Acceptance: FOCUS, Price Sheet, and Reservation Recommendations are available to Power BI through one governed refresh path; each load captures source path, export date, row count, schema version, and freshness state; report refresh does not depend on portal APIs.
  Dependencies: `DATA-002`, `DATA-003`, `DATA-004`.

- [ ] `BI-002` Stand up the semantic layer and star schema. Priority: `Next`
  Why: Finance and engineering need one reusable model instead of page-specific report logic.
  Acceptance: The model cleanly separates fact tables from date, scope, subscription, service or meter, resource group, and business dimensions; grain and relationships are documented; missing or late tags are handled explicitly.
  Dependencies: `BI-001`, `GOV-003`, `GOV-004`.

- [ ] `BI-003` Author core measures and reconciliation rules. Priority: `Next`
  Why: Totals, variances, allocations, and savings must reconcile before the dashboard becomes a source of truth.
  Acceptance: Shared measures exist for total cost, period variance, run rate, share percent, allocated vs unallocated cost, commitment KPIs, and quantified savings; measure definitions are documented; totals reconcile to source exports within an agreed tolerance.
  Dependencies: `BI-002`.

- [ ] `BI-004` Create the five-page report shell and distribution model. Priority: `Next`
  Why: The report needs one publishable artifact with shared navigation, slicers, and audience access from day one.
  Acceptance: One report contains Executive Summary, Cost Drivers, Waste and Actions, Commitments and Discounts, and Chargeback or Allocation pages; shared slicers exist for date, scope, subscription, app, environment, owner, cost center, and business unit; workspace, app audience, and refresh ownership are defined.
  Dependencies: `BI-001`, `BI-002`, `BI-003`.

- [ ] `BI-005` Deliver the Executive Summary page. Priority: `Next`
  Why: Stakeholders need one common summary view for spend health, variance, and freshness.
  Acceptance: The page shows total spend, month-over-month change, current run rate, top service, top subscription, top resource group, allocation completeness, and last successful refresh; users can drill into deeper pages from summary visuals.
  Dependencies: `BI-003`, `BI-004`.

- [ ] `BI-006` Deliver the Cost Drivers page. Priority: `Next`
  Why: Finance-style analysis needs repeatable driver breakdowns beyond the current portal's top-N widgets.
  Acceptance: The page breaks cost down by service, subscription, resource group, and business dimensions; visuals show amount, share percent, and prior-period variance; filtering works from top scope to lower-scope detail without redefining measures.
  Dependencies: `BI-002`, `BI-003`, `BI-004`.

- [ ] `BI-007` Deliver the Waste and Actions page. Priority: `Next`
  Why: BI should summarize waste and action areas while leaving detailed remediation in the app.
  Acceptance: The page surfaces export-backed waste or action buckets and quantified savings totals; quantified items are clearly separated from planning-only items; remediation links point back to the portal's cost, savings, compute, or storage workflows when relevant.
  Dependencies: `BI-003`, `BI-004`.

- [ ] `BI-008` Deliver the Commitments and Discounts page. Priority: `Next`
  Why: Commitment reporting is currently partial and should become durable and reviewable.
  Acceptance: The page shows reservation recommendations, commitment opportunity value, coverage or utilization metrics, and quantified vs planning-only commitment items; the model leaves room for Reservation Details, Reservation Transactions, and savings plan data without redesign.
  Dependencies: `BI-001`, `BI-003`, `BI-004`, `DATA-004`, optionally `DATA-005`.

- [ ] `BI-009` Deliver the Chargeback and Allocation page. Priority: `Next`
  Why: Chargeback and shared-cost reporting are one of the biggest gaps between the current portal and the target architecture, and the five-page BI shell should include a baseline page in v1.
  Acceptance: The page ships in v1 with direct-cost showback by app, environment, owner, cost center, and business unit; the page clearly identifies whether shared-cost allocation is active or deferred; totals reconcile to source cost; the page structure supports later shared-cost allocation without redesign.
  Dependencies: `BI-002`, `BI-003`, `BI-004`, `GOV-004`.

- [ ] `BI-010` Define scale-up triggers and the migration decision playbook. Priority: `Later`
  Why: The roadmap explicitly avoids moving to FinOps hubs, Fabric, or ADX until there is measured need.
  Acceptance: Thresholds are defined for refresh duration or failure rate, model size or data volume, tenant count, and concurrency; those signals are reviewed regularly; any move beyond storage-backed Power BI is tied to measured thresholds rather than preference.
  Dependencies: `BI-004`, `BI-005`, `BI-006`, `BI-007`, `BI-008`, `BI-009`, and later `BI-011`/`BI-012` if those expansion stories ship, all in production.

- [ ] `BI-011` Extend the Commitments and Discounts page with savings-plan and optional reservation depth. Priority: `Later`
  Why: The v1 commitments page should land in Phase 3, but Phase 5 still needs a story for deeper telemetry.
  Acceptance: The commitments page incorporates savings-plan utilization when supported and adds optional Reservation Details or Reservation Transactions fields without redesign; the page clearly distinguishes v1 reservation recommendations from later deep-detail datasets.
  Dependencies: `BI-008`, `DATA-005`, `DATA-010`.

- [ ] `BI-012` Deepen chargeback from showback to shared-cost allocation. Priority: `Later`
  Why: The baseline chargeback page can ship in v1, but shared-cost allocation logic is deeper work that belongs in the Phase 5 hardening pass.
  Acceptance: Shared-cost allocation rules are implemented when approved; allocated plus unallocated cost reconciles to source totals; the page can compare direct cost, allocated cost, and unallocated residuals by business dimension.
  Dependencies: `BI-009`, `GOV-004`.

### App Integration Stories

- [ ] `APP-001` Define the Azure reporting information architecture and nav split. Priority: `Next`
  Why: Users need a clear distinction between operator workflows in the app and governed reporting outside the app.
  Acceptance: Azure navigation and overview clearly separate operational pages from reporting or governance entry points; labels distinguish app-native remediation from external reporting; no current operator route breaks.
  Dependencies: `GOV-001`, `APP-006`.

- [ ] `APP-002` Add an Overview reporting launchpad. Priority: `Next`
  Why: The easiest integration win is a clear reporting handoff from the current Azure Overview page.
  Acceptance: Azure Overview includes links to Power BI and Azure Cost Analysis; each link explains when to use it; missing configuration or access-denied states are handled in-product; overview cards identify whether data is cached app data or external governed reporting.
  Dependencies: `APP-001`, `GOV-005`, `BI-004`, `DATA-008`.

- [ ] `APP-003` Map deep links from app context into Azure Cost Analysis. Priority: `Next`
  Why: Current cost UX is cache-backed and cannot yet hand users into native exploration or saved views.
  Acceptance: Overview and Cost can open mapped Cost Analysis views; handoff preserves scope or filter context where practical; fallback behavior exists when a saved view is unavailable.
  Dependencies: `GOV-005`, `APP-001`.

- [ ] `APP-004` Implement the Power BI integration shell and page handoffs. Priority: `Next`
  Why: Power BI access should follow one intentional pattern rather than scattered links.
  Acceptance: The product supports a configured Power BI entry pattern; users can reach all five BI pages from the app; embed or link-out errors are surfaced cleanly; launch behavior is testable and documented.
  Dependencies: `BI-004`, `APP-001`.

- [ ] `APP-005` Surface export freshness and provenance in-product. Priority: `Next`
  Why: The app currently exposes cache freshness only, which will be misleading once reporting uses exports.
  Acceptance: Overview or the global Azure status bar show export freshness separately from cache freshness; provenance labels explain whether a view is cached, heuristic, or export-backed; stale export states include actionable messaging.
  Dependencies: `DATA-006`, `DATA-008`.

- [ ] `APP-006` Publish the retained-vs-redirected page matrix. Priority: `Next`
  Why: The portal remains the operator cockpit, but finance and governance journeys should land in the right surface by default.
  Acceptance: A page matrix defines which routes stay app-native and which reporting journeys route to Power BI or Cost Analysis; `/cost` is explicitly positioned as an operational summary rather than the canonical finance dashboard; existing bookmarks remain valid.
  Dependencies: `GOV-007`, `BI-004`.

- [ ] `APP-007` Clarify current cost and savings UX with source badges and copy updates. Priority: `Next`
  Why: Current Cost and Savings pages look authoritative even though they are based on cached data and heuristics.
  Acceptance: Cost, Overview, and Savings surfaces show concise source badges such as cached, heuristic, or export-backed; app-generated workbook exports are labeled as operational exports rather than Cost Management exports; finance-oriented calls to action point to Power BI or Cost Analysis where appropriate.
  Dependencies: `APP-005`, `APP-006`.

- [ ] `APP-008` Add integration tests and operator docs for the blended experience. Priority: `Next`
  Why: The integrated experience introduces new config, routing, and fallback behavior that is easy to regress.
  Acceptance: Frontend tests cover navigation, launchpad links, configured and unconfigured states, and retained-route behavior; backend tests cover export freshness and provenance contracts; docs explain required config and troubleshooting for Power BI and Cost Analysis handoffs.
  Dependencies: `APP-001` through `APP-007`.

## Execution Board

### Start Queue

These are the first five stories to start or queue because they unlock the most downstream work:

1. `GOV-001`
2. `GOV-002`
3. `DATA-001`
4. `GOV-003`
5. `DATA-002`

### Hard Gates

- `GOV-001` is the root gate for the entire program.
- `GOV-002` gates meaningful data and export setup work.
- `GOV-003` gates showback/allocation policy and BI dimension design.
- `DATA-001` gates all export-backed ingestion and BI work.
- `DATA-002`, `DATA-003`, and `DATA-004` together gate export-backed BI and cutover work.
- `GOV-005` -> `GOV-006` -> `GOV-007` is the governance chain for native Cost Management handoff.
- `DATA-006` -> `DATA-008` gates export freshness/provenance in the app.
- `BI-001` -> `BI-002` -> `BI-003` -> `BI-004` is the main BI critical path.
- `APP-006` -> `APP-001` gates the reporting IA and later app handoff work.

### Wave Plan

- Wave 1: `GOV-001`
- Wave 2: `GOV-002`
- Wave 3: `GOV-003`, `DATA-001`
- Wave 4: `GOV-004`, `GOV-005`, `DATA-002`
- Wave 5: `GOV-006`, `DATA-003`, `DATA-004`, `DATA-006`, `DATA-007`
- Wave 6: `GOV-007`, `DATA-008`, `BI-001`
- Wave 7: `BI-002`, `BI-003`, `DATA-009`, `APP-005`
- Wave 8: `BI-004`
- Wave 9: `BI-005`, `BI-006`, `BI-008`, `BI-009`, `BI-007`
- Wave 10: `APP-006`, `APP-001`
- Wave 11: `APP-002`, `APP-003`, `APP-004`, `APP-007`, `DATA-005`, `DATA-010`, `BI-011`, `BI-012`
- Wave 12: `BI-010`, `APP-008`

### Parallel Batches

- `GOV-003` and `DATA-001` can run in parallel.
- `GOV-004` and `GOV-005` can run in parallel once `GOV-003` is ratified.
- `DATA-003` and `DATA-004` can run in parallel after `DATA-002` has established the export ingestion pattern.
- `BI-005`, `BI-006`, `BI-008`, and `BI-009` can run in parallel after `BI-004`.
- `APP-002`, `APP-003`, and `APP-004` can run in parallel after `APP-001`, once their external targets are ready.

### V1 Assumption

Waves 1 through 10 assume a recommendation-only commitment v1 built from FOCUS, Price Sheet, and Reservation Recommendations. If Reservation Details or Reservation Transactions are pulled into v1, move `DATA-005` ahead of `DATA-007` and `BI-008`.

### Lane Notes

- Governance lane:
  Most of the real configuration work happens outside the repo in Azure Cost Management. The repo contribution is mainly decision records, runbooks, ownership matrices, and saved-view catalogs.
- Data lane:
  Build a parallel export lane rather than overloading the live ARM query path. A clean shape is new modules such as `azure_export_store.py` and `azure_export_ingestor.py`, started from [`main.py`](/workspace/altlassian/backend/main.py), with tests patterned after existing Azure cache/export tests.
- Data lane before provisioning:
  The repo-side foundation can start before ADLS is live: manifest store, parser interfaces, fixture-driven ingestion tests, health evaluator, schema/quarantine handling, config flags, provenance payloads, and cutover plumbing.
- BI lane:
  The smallest viable BI v1 is `BI-001` through `BI-009`: one published five-page report, export-backed refresh only, direct-cost showback only, and no dependency on portal embedding.
- App lane:
  The first useful app slice should be read-only: export health in the Azure status/overview surfaces plus one governed-reporting panel on Overview with link-outs to Power BI and Cost Analysis. Do not embed Power BI or reroute `/cost` in the first ship.

## First-Wave Task Packets

These packets turn the first five queued stories into concrete work. The main rule for the first wave is simple: treat `GOV-001`, `GOV-002`, and `DATA-001` as externally gated stories with useful repo prep, and treat `GOV-003` and `DATA-002` as the most productive places to build in parallel while Azure-side decisions and provisioning catch up.

### First-Wave Working Model

- Use two lanes first: governance and data.
- For a two-person team, one person owns `GOV-001` -> `GOV-002` -> `GOV-003` while the other owns `DATA-001` contract work and `DATA-002` scaffolding.
- For a three-person team, split `GOV-001`, `GOV-002` plus `GOV-003`, and the data lane across three owners.
- Do not spread a small team across five separate owners; the real bottlenecks are scope, access, and landing-zone readiness.
- The first efficient parallel point is after scope and access are underway: run `GOV-003` and `DATA-001` in parallel, then move directly into `DATA-002`.

### `GOV-001` Reporting Scope Decision Packet

- Story intent:
  Choose the canonical reporting scope of record for Cost Management, exports, Power BI, and downstream accountability.
- Repo work that can start now:
  Draft a reporting-scope decision record, inventory the current billing hierarchy and candidate rollup scopes, and create a reusable template for future scope decisions.
- Proposed artifacts:
  `docs/governance/2026-03-20-gov-001-reporting-scope-decision.md`
  `docs/governance/2026-03-20-gov-001-billing-hierarchy-inventory.md`
  `docs/templates/reporting-scope-decision-template.md`
- Inputs to capture:
  Agreement model, highest supported governing scope, allowed child scopes, high-risk subscriptions or resource groups, finance owner, engineering owner, and sign-off date.
- External work required:
  Finance and engineering must ratify the canonical scope and confirm any agreement-type constraints, especially where management-group behavior differs by billing model.
- Repo grounding:
  Use the existing subscription and management-group inventory surfaces as the appendix source rather than re-discovering this manually.
- Completion gate:
  `GOV-001` is done only when the decision record is signed off, the canonical scope is named, child-scope exceptions are listed, and the scope is stable enough for budgets, exports, and BI to target without rework.

### `GOV-002` Ownership And Access Packet

- Story intent:
  Name the DRIs and define the Azure-side RBAC required to build and operate the target architecture.
- Repo work that can start now:
  Draft the ownership matrix, build the access matrix, and write the access-request runbook that separates app auth from Azure RBAC.
- Proposed artifacts:
  `docs/governance/2026-03-20-gov-002-cost-governance-ownership-matrix.md`
  `docs/governance/2026-03-20-gov-002-azure-access-matrix.md`
  `docs/runbooks/azure-cost-governance-access-request-runbook.md`
- Required role coverage:
  Cost Management Contributor for builders, Cost Management Reader for viewers, Storage Account Contributor or equivalent storage write and read rights for export targets, and Monitoring Contributor or equivalent action-group rights where scheduled responses are automated. The matrix should also name the export writer, ingestion reader, and break-glass owner identities.
- External work required:
  Real people must be assigned to finance, platform, engineering, and break-glass ownership; Azure RBAC must be applied and validated outside the repo.
- Repo grounding:
  The repo already distinguishes application admin concerns from Azure-side access and already inventories Azure role assignments, so the docs should mirror those boundaries.
- Completion gate:
  `GOV-002` is done only when DRIs are named, required roles are assigned at the chosen scope and storage target, and the request path for future access changes is documented and tested.

### `GOV-003` Tag Policy And Compliance Packet

- Story intent:
  Standardize the business dimensions that every cost record should answer and define the first compliance baseline.
- Repo work that can start now:
  Draft the tag dictionary, produce a baseline audit from current resource-tag data, create a remediation runbook, and prepare a reusable template.
- Proposed artifacts:
  `docs/governance/2026-03-20-gov-003-tag-dictionary-and-compliance-policy.md`
  `docs/governance/2026-03-20-gov-003-tag-baseline-audit.csv`
  `docs/runbooks/tag-remediation-runbook.md`
  `docs/templates/tag-dictionary-template.md`
- Minimum tag set:
  `application_service`, `environment`, `owner`, `cost_center`, and `business_unit`.
- Decision points to record:
  Required versus optional tags, allowed value rules, and whether tag inheritance is enabled in v1 or deferred with a documented remediation plan.
- Repo grounding:
  Start from the existing resource-tag inventory and missing-tag evaluation already present in the Azure cache and alerting code.
- External work required:
  Policy ratification, inheritance enablement, and Azure-side remediation enforcement still need platform and finance approval.
- Completion gate:
  `GOV-003` is done only when the tag dictionary is ratified, the inheritance decision is documented, baseline noncompliance is measured, remediation ownership exists, and the policy is ready to feed BI dimensions and showback logic.

### `DATA-001` ADLS Landing-Zone Packet

- Story intent:
  Stand up the durable export destination that every export-backed reporting flow depends on.
- Repo work that can start now:
  Define the landing-zone path contract, decide whether ingestion reads from ADLS directly or from a mounted or synced path, confirm the export writer and ingestion reader identity model from `GOV-002`, add config placeholders, add a contract validator, add a lightweight export metadata store, and write the operator runbook.
- Proposed backend work:
  `backend/config.py`
  `backend/.env.example`
  `backend/azure_export_contract.py`
  `backend/azure_export_store.py`
  `backend/tests/test_azure_export_contract.py`
  `backend/tests/test_azure_export_store.py`
- Path contract must define:
  Storage account and filesystem naming, dataset roots, scope keys, `delivery_date=` or `run=` semantics, and reserved areas for `raw`, `staged`, `manifest`, and `quarantine`.
- External work required:
  Provision the HNS-enabled ADLS Gen2 landing zone, apply RBAC, retention, and lifecycle rules, and validate real write, list, and read behavior.
- Repo grounding:
  This repo currently models cache and workbook exports, not ADLS-backed reporting, so this work should create a new export lane rather than extending the workbook path.
- Completion gate:
  `DATA-001` is done only when one real ADLS Gen2 landing zone exists for the chosen v1 scope, the dataset path contract is fixed, and RBAC, retention, and lifecycle settings have been validated with a documented smoke test.

### `DATA-002` FOCUS Ingestion Packet

- Story intent:
  Ingest the first real Cost Management export dataset and prove it can drive the current summary and breakdown read models.
- Repo work that can start now:
  Add config for FOCUS ingestion, implement delivery discovery against the `DATA-001` contract, build the manifest store, implement a parser and staging model, add worker or poller wiring, and write reconciliation tests against the current cost-consumer shape.
- Proposed backend work:
  `backend/config.py`
  `backend/.env.example`
  `backend/main.py`
  `backend/azure_export_ingestor.py`
  `backend/azure_export_store.py`
  `backend/azure_focus_staging.py`
  `backend/tests/test_azure_export_ingestor.py`
  `backend/tests/test_azure_focus_staging.py`
  `backend/tests/fixtures/azure_focus/`
- Manifest requirements:
  Track `dataset`, `scope`, `path`, `delivery_time`, `row_count`, `parse_status`, and error details so later freshness and provenance features do not need a redesign.
- Initial normalized output:
  Stage the fields needed by existing consumers first: usage date, cost amount and currency, service label, subscription, resource group, and scope identifiers.
- Repo grounding:
  Keep this parallel to the live ARM query path. Follow the worker and store patterns already used by the Azure cache and VM export jobs rather than folding export logic into direct-query code.
- External work required:
  A real scheduled daily FOCUS export must land in the `DATA-001` landing zone before the story is actually closed.
- Completion gate:
  `DATA-002` is done only when at least one real scheduled FOCUS delivery lands in the agreed path, the ingestor records a successful manifest row, and the staged dataset can produce the inputs needed for current summary, trend, and breakdown consumers without falling back to live Cost Management queries.

## Repo-Specific Implementation Notes

This roadmap should not start with a rewrite of the current Azure portal. The existing product already provides value that the target architecture does not replace.

- The current `AzureCostPage` is a strong operational summary and should stay.
- The current `AzureSavingsPage`, `AzureComputeOptimizationPage`, and `AzureStoragePage` already provide optimization workflows that Power BI should complement, not absorb.
- The current Azure alerts system is useful for product-level workflows even after budgets and anomaly alerts move into Azure-native controls.
- The first integration win is likely a new overview card or tab showing export freshness plus links into Power BI and Cost Analysis.

## Suggested Delivery Order

If we want the fastest path to a useful v1, do the work in this order:

1. Scope and governance decisions.
2. Azure-native Cost Management setup.
3. ADLS export landing zone.
4. Power BI dashboard.
5. App integration points.
6. Commitment and chargeback depth work.

## Definition of Done for the Program

- Azure Cost Management is the default place for native cost exploration and budget governance.
- Daily Cost Management exports land in ADLS Gen2.
- Power BI is the shared reporting layer for finance and engineering.
- The existing Azure portal remains the operator-facing remediation surface.
- Commitment and chargeback reporting are based on durable export data rather than only app heuristics.
