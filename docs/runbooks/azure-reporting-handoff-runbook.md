# Azure Reporting Handoff and Provenance Runbook

**Applies to:** Azure reporting handoff surface
**Status:** Draft

## When To Use

Use this runbook when configuring or reviewing the Azure Overview launchpad that points operators toward shared reporting, or when explaining why a page shows cached app data versus governed reporting.

## What This Surface Does

The Azure Overview page is the operator launchpad for reporting. It does three things:

1. Surfaces links to the governed reporting targets.
2. Shows whether those targets are configured.
3. Labels the data source behind the current page so operators know whether they are looking at cached app data, heuristic guidance, or export-backed reporting.

It is not itself the reporting system of record. It is a navigation and provenance surface.

## Environment Variables

The backend reads the reporting configuration from these environment variables:

- `AZURE_REPORTING_POWER_BI_URL`: full URL to the shared Power BI report or app.
- `AZURE_REPORTING_POWER_BI_LABEL`: display label for that target. Default: `Shared Cost Dashboard`.
- `AZURE_REPORTING_COST_ANALYSIS_URL`: full URL to the Azure Cost Analysis entry point or saved view.
- `AZURE_REPORTING_COST_ANALYSIS_LABEL`: display label for that target. Default: `Azure Cost Analysis`.

If a URL is blank, the card stays visible but shows `Not configured yet` instead of an open button.

## Launchpad Behavior

- The Overview page always shows the reporting handoff section because the backend emits the `reporting` object.
- A configured card opens the target in a new browser tab.
- An unconfigured card is a setup signal, not an application failure.
- The launchpad does not proxy auth, create reports, or modify Azure permissions.
- The export health section is separate from the reporting handoff. Export health tells you whether the governed lane is fresh; the handoff cards tell you where to go.

## Source Labels

Use the source badges as provenance hints, not as the primary health signal.

- `Cached app data`: the page is backed by the app's cached Azure snapshots and operational query results. This is the right source for triage, drill-in, and portal-native workflows.
- `Heuristic operational guidance`: the page blends cached Azure data, Advisor signals, and app heuristics. This is useful for operator action, but it is not a finance book of record.
- `Export-backed governed reporting`: the page or card points to the governed lane built from Cost Management exports and BI assets. This is the preferred source for shared reporting, showback, and chargeback.

## Operator Checklist

1. Set the reporting URLs in the backend environment.
2. Reload the app and confirm the Overview page shows both reporting cards.
3. Confirm each configured card has an `Open` button.
4. Confirm unconfigured targets show `Not configured yet`.
5. Confirm the source badges match the intended use of each page.
6. Confirm operators use the export-backed lane for finance-facing reporting and the cached app views for triage.

## Validation Notes

- If the Power BI card is configured but access fails, the issue is in the target platform or identity path, not the app.
- If a card is unconfigured, verify the matching `AZURE_REPORTING_*_URL` value first.
- If the source badge reads `Cached app data`, do not treat the page as governed reporting even if the numbers look complete.

## Escalation

- Escalate missing or stale reporting URLs to the Azure platform owner.
- Escalate broken Power BI access to the report owner or BI admin.
- Escalate export freshness issues to the export pipeline owner.
