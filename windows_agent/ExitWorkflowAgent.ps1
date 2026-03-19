[CmdletBinding()]
param(
  [string]$ConfigPath = (Join-Path $PSScriptRoot "exit-agent.config.json")
)

$ErrorActionPreference = "Stop"

function Write-AgentLog {
  param([string]$Message)
  $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Write-Host "[$timestamp] $Message"
}

function ConvertTo-Hashtable {
  param([object]$InputObject)

  if ($null -eq $InputObject) {
    return $null
  }

  if ($InputObject -is [System.Collections.IDictionary]) {
    $hash = @{}
    foreach ($key in $InputObject.Keys) {
      $hash[$key] = ConvertTo-Hashtable $InputObject[$key]
    }
    return $hash
  }

  if (($InputObject -is [System.Collections.IEnumerable]) -and -not ($InputObject -is [string])) {
    $items = @()
    foreach ($item in $InputObject) {
      $items += ,(ConvertTo-Hashtable $item)
    }
    return $items
  }

  if ($InputObject.PSObject -and $InputObject.PSObject.Properties.Count -gt 0) {
    $hash = @{}
    foreach ($property in $InputObject.PSObject.Properties) {
      $hash[$property.Name] = ConvertTo-Hashtable $property.Value
    }
    return $hash
  }

  return $InputObject
}

function Get-AgentConfig {
  param([string]$Path)

  if (-not (Test-Path -LiteralPath $Path)) {
    throw "Config file not found: $Path"
  }

  $config = ConvertTo-Hashtable (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
  foreach ($key in @("baseUrl", "sharedSecret", "agentId")) {
    if (-not $config[$key]) {
      throw "Missing required config key: $key"
    }
  }
  return $config
}

function Invoke-AgentApi {
  param(
    [hashtable]$Config,
    [ValidateSet("GET", "POST")]
    [string]$Method,
    [string]$Path,
    [hashtable]$Body = @{}
  )

  $url = ($Config.baseUrl.TrimEnd("/") + $Path)
  $headers = @{
    "Content-Type" = "application/json"
    "x-user-exit-agent-secret" = [string]$Config.sharedSecret
  }

  if ($Method -eq "GET") {
    return Invoke-RestMethod -Method Get -Uri $url -Headers $headers
  }

  return Invoke-RestMethod -Method Post -Uri $url -Headers $headers -Body ($Body | ConvertTo-Json -Depth 8)
}

function Get-ProfileConfig {
  param(
    [hashtable]$Config,
    [string]$ProfileKey
  )

  if (-not $ProfileKey) {
    throw "Step did not include a profile key"
  }
  $profiles = $Config.profiles
  if (-not $profiles.ContainsKey($ProfileKey)) {
    throw "Profile '$ProfileKey' is not configured on this agent"
  }
  return $profiles[$ProfileKey]
}

function Start-StepHeartbeat {
  param(
    [hashtable]$Config,
    [string]$StepId
  )

  $heartbeatSeconds = if ($Config.ContainsKey("heartbeatSeconds")) { [int]$Config.heartbeatSeconds } else { 20 }
  $interval = [Math]::Max(10, $heartbeatSeconds)
  $baseUrl = [string]$Config.baseUrl
  $secret = [string]$Config.sharedSecret
  $agentId = [string]$Config.agentId

  return Start-Job -Name "exit-heartbeat-$StepId" -ScriptBlock {
    param($BaseUrl, $Secret, $AgentId, $ClaimedStepId, $HeartbeatInterval)
    $headers = @{
      "Content-Type" = "application/json"
      "x-user-exit-agent-secret" = $Secret
    }
    $body = @{ agent_id = $AgentId } | ConvertTo-Json
    while ($true) {
      try {
        Invoke-RestMethod `
          -Method Post `
          -Uri ($BaseUrl.TrimEnd("/") + "/api/user-exit/agent/steps/$ClaimedStepId/heartbeat") `
          -Headers $headers `
          -Body $body | Out-Null
      } catch {
        Write-Host "Heartbeat failed for $ClaimedStepId: $($_.Exception.Message)"
      }
      Start-Sleep -Seconds $HeartbeatInterval
    }
  } -ArgumentList $baseUrl, $secret, $agentId, $StepId, $interval
}

function Stop-StepHeartbeat {
  param($HeartbeatJob)

  if ($null -eq $HeartbeatJob) {
    return
  }
  try {
    Stop-Job -Job $HeartbeatJob -ErrorAction SilentlyContinue | Out-Null
  } finally {
    Remove-Job -Job $HeartbeatJob -ErrorAction SilentlyContinue | Out-Null
  }
}

function Remove-DirectGroupMemberships {
  param(
    [object]$User,
    [string]$Server
  )

  $removed = @()
  $groups = Get-ADPrincipalGroupMembership -Identity $User -Server $Server |
    Where-Object { $_.Name -ne "Domain Users" }

  foreach ($group in $groups) {
    Remove-ADGroupMember -Identity $group -Members $User -Confirm:$false -Server $Server
    $removed += [string]$group.Name
  }

  return $removed
}

function Invoke-OnPremDeprovision {
  param(
    [hashtable]$Config,
    [hashtable]$Step
  )

  Import-Module ActiveDirectory

  $profile = Get-ProfileConfig -Config $Config -ProfileKey $Step.profile_key
  $payload = ConvertTo-Hashtable $Step.payload
  $server = [string]$profile.defaultDomainController
  $sam = [string]$Step.on_prem_sam_account_name
  if (-not $sam) {
    throw "Missing on-prem SAM account name"
  }

  $adUser = Get-ADUser `
    -Identity $sam `
    -Server $server `
    -Properties Enabled, DistinguishedName, mailNickname, manager, telephoneNumber, otherTelephone, mobile, ipPhone, facsimileTelephoneNumber, physicalDeliveryOfficeName, msDS-cloudExtensionAttribute1, msExchAssistantName, msExchHideFromAddressLists

  $before = @{
    enabled = [bool]$adUser.Enabled
    distinguished_name = [string]$adUser.DistinguishedName
    office = [string]$adUser.physicalDeliveryOfficeName
  }

  $removedGroups = Remove-DirectGroupMemberships -User $adUser -Server $server
  $mailNickname = "disabled.$sam"

  Set-ADUser `
    -Identity $adUser `
    -Server $server `
    -Enabled:$false `
    -Office "DISABLED" `
    -Clear @("manager", "telephoneNumber", "otherTelephone", "mobile", "ipPhone", "facsimileTelephoneNumber", "msDS-cloudExtensionAttribute1") `
    -Replace @{
      mailNickname = $mailNickname
      msExchAssistantName = "HideFromGAL"
      msExchHideFromAddressLists = $true
    }

  if ($profile.disabledOu) {
    Move-ADObject -Identity $adUser.DistinguishedName -TargetPath $profile.disabledOu -Server $server
  }

  $updated = Get-ADUser `
    -Identity $sam `
    -Server $server `
    -Properties Enabled, DistinguishedName, physicalDeliveryOfficeName, msExchHideFromAddressLists

  return @{
    summary = "Disabled AD account, removed non-default groups, updated hide-from-GAL attributes, and moved the user to the disabled OU."
    before_summary = $before
    after_summary = @{
      enabled = [bool]$updated.Enabled
      distinguished_name = [string]$updated.DistinguishedName
      office = [string]$updated.physicalDeliveryOfficeName
      hidden_from_address_lists = [bool]$updated.msExchHideFromAddressLists
      removed_group_count = $removedGroups.Count
      removed_groups = $removedGroups
      target_mail_nickname = $mailNickname
    }
  }
}

function Ensure-ExchangeCommand {
  param([hashtable]$Config, [string]$ProfileKey)

  if (Get-Command Set-Mailbox -ErrorAction SilentlyContinue) {
    return $null
  }

  $profile = Get-ProfileConfig -Config $Config -ProfileKey $ProfileKey
  if (-not $profile.exchangeConnectionUri) {
    throw "Exchange cmdlets are unavailable and no exchangeConnectionUri is configured for profile '$ProfileKey'"
  }

  Write-AgentLog "Opening remote Exchange session for profile '$ProfileKey'"
  $session = New-PSSession `
    -ConfigurationName Microsoft.Exchange `
    -ConnectionUri $profile.exchangeConnectionUri `
    -Authentication Kerberos

  Import-PSSession $session -DisableNameChecking -AllowClobber | Out-Null
  return $session
}

function Invoke-MailboxConvertType {
  param(
    [hashtable]$Config,
    [hashtable]$Step
  )

  $payload = ConvertTo-Hashtable $Step.payload
  $mailboxIdentity = if ($payload.ContainsKey("mail") -and $payload.mail) {
    [string]$payload.mail
  } else {
    [string]$payload.user_principal_name
  }
  if (-not $mailboxIdentity) {
    throw "Missing mailbox identity"
  }

  $session = $null
  try {
    $session = Ensure-ExchangeCommand -Config $Config -ProfileKey $Step.profile_key
    $mailbox = Get-Mailbox -Identity $mailboxIdentity
    $before = @{
      mailbox_type = [string]$mailbox.RecipientTypeDetails
      hidden_from_address_lists = [bool]$mailbox.HiddenFromAddressListsEnabled
    }

    Set-Mailbox -Identity $mailboxIdentity -Type Shared -HiddenFromAddressListsEnabled:$true
    $updated = Get-Mailbox -Identity $mailboxIdentity

    return @{
      summary = "Converted the mailbox to Shared and hid it from address lists."
      before_summary = $before
      after_summary = @{
        mailbox_type = [string]$updated.RecipientTypeDetails
        hidden_from_address_lists = [bool]$updated.HiddenFromAddressListsEnabled
      }
    }
  } finally {
    if ($null -ne $session) {
      Remove-PSSession -Session $session -ErrorAction SilentlyContinue
    }
  }
}

function Invoke-WorkflowStep {
  param(
    [hashtable]$Config,
    [hashtable]$Step
  )

  switch ([string]$Step.step_key) {
    "exit_on_prem_deprovision" { return Invoke-OnPremDeprovision -Config $Config -Step $Step }
    "mailbox_convert_type" { return Invoke-MailboxConvertType -Config $Config -Step $Step }
    default { throw "Unsupported step key '$($Step.step_key)'" }
  }
}

function Claim-NextStep {
  param([hashtable]$Config)

  return Invoke-AgentApi `
    -Config $Config `
    -Method POST `
    -Path "/api/user-exit/agent/steps/claim" `
    -Body @{
      agent_id = [string]$Config.agentId
      profile_keys = @($Config.profiles.Keys)
    }
}

function Complete-Step {
  param(
    [hashtable]$Config,
    [string]$StepId,
    [ValidateSet("completed", "failed", "skipped")]
    [string]$Status,
    [string]$Summary,
    [string]$ErrorText,
    [hashtable]$BeforeSummary,
    [hashtable]$AfterSummary
  )

  Invoke-AgentApi `
    -Config $Config `
    -Method POST `
    -Path "/api/user-exit/agent/steps/$StepId/complete" `
    -Body @{
      agent_id = [string]$Config.agentId
      status = $Status
      summary = $Summary
      error = $ErrorText
      before_summary = $BeforeSummary
      after_summary = $AfterSummary
    } | Out-Null
}

$config = Get-AgentConfig -Path $ConfigPath
$pollValue = if ($config.ContainsKey("pollSeconds")) { [int]$config.pollSeconds } else { 10 }
$pollSeconds = [Math]::Max(5, $pollValue)

Write-AgentLog "User exit workflow agent starting as '$($config.agentId)'"

while ($true) {
  try {
    $step = ConvertTo-Hashtable (Claim-NextStep -Config $config)
    if ($null -eq $step) {
      Start-Sleep -Seconds $pollSeconds
      continue
    }

    Write-AgentLog "Claimed step $($step.step_key) for $($step.user_principal_name)"
    $heartbeatJob = Start-StepHeartbeat -Config $config -StepId $step.step_id

    try {
      $result = Invoke-WorkflowStep -Config $config -Step $step
      $beforeSummary = if ($null -ne $result.before_summary) { ConvertTo-Hashtable $result.before_summary } else { @{} }
      $afterSummary = if ($null -ne $result.after_summary) { ConvertTo-Hashtable $result.after_summary } else { @{} }
      Complete-Step `
        -Config $config `
        -StepId $step.step_id `
        -Status "completed" `
        -Summary ([string]$result.summary) `
        -ErrorText "" `
        -BeforeSummary $beforeSummary `
        -AfterSummary $afterSummary
      Write-AgentLog "Completed step $($step.step_key)"
    } catch {
      $message = $_.Exception.Message
      Complete-Step `
        -Config $config `
        -StepId $step.step_id `
        -Status "failed" `
        -Summary "Failed" `
        -ErrorText $message `
        -BeforeSummary @{} `
        -AfterSummary @{}
      Write-AgentLog "Step $($step.step_key) failed: $message"
    } finally {
      Stop-StepHeartbeat -HeartbeatJob $heartbeatJob
    }
  } catch {
    Write-AgentLog "Agent loop error: $($_.Exception.Message)"
    Start-Sleep -Seconds $pollSeconds
  }
}
