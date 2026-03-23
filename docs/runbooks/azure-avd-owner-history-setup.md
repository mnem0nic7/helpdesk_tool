# Azure AVD Owner History Setup

This dashboard resolves Azure Virtual Desktop cleanup owners in this order:

1. `sessionHost.properties.assignedUser`
2. Latest successful `WVDConnections` user from Log Analytics
3. `Unassigned`

The cleanup tracker is intentionally limited to `Personal` host pools.

## Required Azure setup

Each personal AVD host pool must have diagnostic settings that send connection logs to a Log Analytics workspace.

Minimum requirements:

- Diagnostic settings exist on the host pool resource.
- The setting sends logs to a Log Analytics workspace.
- Connection logs are enabled.
  Acceptable for the app's fallback logic:
  - `Connection`
  - `allLogs`
  - `Audit`

If those settings are missing, the dashboard will keep the desktop unassigned and show `owner_history_status = missing_diagnostics`.

## Required app permissions

The app identity must be able to:

- Read AVD host pools
- Read AVD session hosts
- Read diagnostic settings on host pools
- Read the target Log Analytics workspace resource
- Query the target Log Analytics workspace

Recommended minimum access:

- Reader on the subscriptions or resource groups that contain the AVD host pools
- Reader on the Log Analytics workspace resource
- Log Analytics API permission with workspace read/query access

If workspace lookup or query access is missing, the dashboard will show `owner_history_status = query_failed`.

## Validation checklist

- Confirm the host pool is `Personal`.
- Confirm `assignedUser` appears on `sessionHosts` for directly assigned desktops.
- Confirm the host pool diagnostic setting targets a Log Analytics workspace.
- Confirm `WVDConnections` contains rows for `SessionHostAzureVmId` and `UserName`.
- Confirm the app identity can query the workspace.

## Useful references

- AVD session hosts REST API:
  https://learn.microsoft.com/en-us/rest/api/desktopvirtualization/session-hosts/list?view=rest-desktopvirtualization-2024-04-03
- AVD diagnostics in Log Analytics:
  https://learn.microsoft.com/en-us/azure/virtual-desktop/diagnostics-log-analytics
- `WVDConnections` table reference:
  https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/wvdconnections
- Log Analytics query API:
  https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/access-api
