<#
One-time (idempotent) tenant bootstrap for the Teams message retention feature
(retention.movedocs.com). Run this whenever the retention service account is
first provisioned, or re-provisioned after a disaster-recovery rebuild.

Why this exists: Microsoft Graph's channel-message soft-delete endpoint
enforces the same "Owners can delete sent messages" Teams Messaging Policy
setting a real Teams owner would need in the client — this cannot be granted
via Microsoft Graph at all, only via the MicrosoftTeams PowerShell module.
Without it, the retention service account can read and preview messages
(ChannelMessage.Read.All) but every delete call 403s with
"AclCheckFailed-Delete Message ... does not have the desired capability
DeleteOthersMessage", even after the account is a team owner.

Prerequisites (see the "Teams message retention" section of CLAUDE.md for the
full chain this is one link in):
  - The app registration's SERVICE PRINCIPAL (not just the retention-svc user)
    must hold the Microsoft Entra "Teams Administrator" directory role — this
    is what Application-based auth to the Teams PowerShell module uses for its
    RBAC, per Microsoft's own docs. Assign it once via the Entra portal or
    Graph (`POST /directoryRoles/{teamsAdminRoleId}/members/$ref` with the
    service principal's object id) before running this script.
  - No Graph API permission needs to be added to the app registration for the
    "Skype and Teams Tenant Admin API" resource — Microsoft's docs explicitly
    warn that configuring one can cause failures.

This script authenticates app-only (client_credentials, the same
Entra app registration already used for RETENTION_GRAPH_CLIENT_ID/SECRET in
backend/.env) via Connect-MicrosoftTeams -AccessTokens, so it needs no
interactive sign-in and no certificate.

Usage:
  pwsh ./bootstrap_retention_messaging_policy.ps1 `
    -ApplicationId <RETENTION_GRAPH_CLIENT_ID> `
    -ClientSecret <RETENTION_GRAPH_CLIENT_SECRET> `
    -TenantId <RETENTION_GRAPH_TENANT_ID> `
    -ServiceAccountUpn retention-svc@librasolutionsgroup.com
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ApplicationId,

    [Parameter(Mandatory = $true)]
    [string]$ClientSecret,

    [Parameter(Mandatory = $true)]
    [string]$TenantId,

    [Parameter(Mandatory = $true)]
    [string]$ServiceAccountUpn,

    [string]$PolicyName = 'RetentionServiceAccount'
)

$ErrorActionPreference = 'Stop'
Import-Module MicrosoftTeams

# Teams PowerShell app-only auth needs two separate client_credentials tokens
# for the same app: one for Graph, one for the "Skype and Teams Tenant Admin
# API" resource (fixed resource id, not a real app in this tenant's directory
# so it can't be looked up by name).
$graphTokenBody = @{
    Grant_Type    = 'client_credentials'
    Scope         = 'https://graph.microsoft.com/.default'
    Client_Id     = $ApplicationId
    Client_Secret = $ClientSecret
}
$graphToken = Invoke-RestMethod -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -Method POST -Body $graphTokenBody |
    Select-Object -ExpandProperty access_token

$teamsTokenBody = @{
    Grant_Type    = 'client_credentials'
    Scope         = '48ac35b8-9aa8-4d74-927d-1f4a14a0b239/.default'
    Client_Id     = $ApplicationId
    Client_Secret = $ClientSecret
}
$teamsToken = Invoke-RestMethod -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -Method POST -Body $teamsTokenBody |
    Select-Object -ExpandProperty access_token

Connect-MicrosoftTeams -AccessTokens @("$graphToken", "$teamsToken") | Out-Null
Write-Output "Connected to Teams PowerShell as application $ApplicationId"

try {
    $existing = Get-CsTeamsMessagingPolicy -Identity $PolicyName -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-CsTeamsMessagingPolicy -Identity $PolicyName -AllowOwnerDeleteMessage $true | Out-Null
        Write-Output "Created messaging policy '$PolicyName' (AllowOwnerDeleteMessage = true)"
    }
    else {
        # Idempotent: re-running this script after the policy already exists
        # should still guarantee the one setting this feature depends on,
        # even if someone edited the policy for an unrelated reason since.
        Set-CsTeamsMessagingPolicy -Identity $PolicyName -AllowOwnerDeleteMessage $true | Out-Null
        Write-Output "Messaging policy '$PolicyName' already existed; ensured AllowOwnerDeleteMessage = true"
    }

    Grant-CsTeamsMessagingPolicy -PolicyName $PolicyName -Identity $ServiceAccountUpn
    Write-Output "Granted '$PolicyName' to $ServiceAccountUpn"
}
finally {
    Disconnect-MicrosoftTeams -Confirm:$false | Out-Null
}
