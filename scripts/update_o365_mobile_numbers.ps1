<#
Bulk update mobile numbers from Excel/CSV.

Primary use case:
- Update on-prem AD `mobile` for directory-synced users (recommended).

Optional use case:
- Update cloud users in Microsoft Graph (`mobilePhone`).

Input columns expected:
- Email
- Mobile (Home)   (or Mobile)
- Active          (optional; if present and not Yes/True/1, row is skipped by default)

Examples:
  # AD (recommended for synced users)
  .\update_o365_mobile_numbers.ps1 \
	-SourceFile "C:\Temp\Users_2026-04-16T15_53_40.610Z.xlsx" \
	-Target AD \
	-ReportPath "C:\Temp\mobile_update_results_ad.csv"

  # Graph (cloud-only users)
  .\update_o365_mobile_numbers.ps1 \
	-SourceFile "C:\Temp\Users_2026-04-16T15_53_40.610Z.xlsx" \
	-Target Graph \
	-ReportPath "C:\Temp\mobile_update_results_graph.csv"

  # Dry-run
  .\update_o365_mobile_numbers.ps1 -SourceFile "C:\Temp\Users.xlsx" -Target AD -WhatIf
#>

[CmdletBinding()]
param(
	[Parameter(Mandatory = $true)]
	[string]$SourceFile,

	[ValidateSet('AD', 'Graph')]
	[string]$Target = 'AD',

	[string]$WorksheetName,

	[string]$ReportPath = (Join-Path -Path $PWD -ChildPath "mobile_update_results.csv"),

	[switch]$IncludeInactive,

	[switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Info {
	param([string]$Message)
	Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Warn {
	param([string]$Message)
	Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Test-Truthy {
	param([string]$Value)
	$normalized = ($Value | ForEach-Object { "$_".Trim().ToLowerInvariant() })
	return @('yes', 'true', '1', 'y') -contains $normalized
}

function Resolve-HeaderName {
	param(
		[string[]]$Available,
		[string[]]$Candidates
	)
	foreach ($candidate in $Candidates) {
		foreach ($name in $Available) {
			if ($name -ieq $candidate) {
				return $name
			}
		}
	}
	return $null
}

function Ensure-ImportExcel {
	if (Get-Module -ListAvailable -Name ImportExcel) {
		Import-Module ImportExcel -ErrorAction Stop
		return
	}

	Write-Info "ImportExcel module not found. Installing for current user..."
	Install-Module ImportExcel -Scope CurrentUser -Force -AllowClobber -ErrorAction Stop
	Import-Module ImportExcel -ErrorAction Stop
}

function Load-InputRows {
	param(
		[string]$Path,
		[string]$SheetName
	)

	if (-not (Test-Path -LiteralPath $Path)) {
		throw "Source file not found: $Path"
	}

	$ext = [IO.Path]::GetExtension($Path).ToLowerInvariant()
	if ($ext -eq '.csv') {
		return Import-Csv -LiteralPath $Path
	}

	if ($ext -eq '.xlsx') {
		Ensure-ImportExcel
		if ($SheetName) {
			return Import-Excel -Path $Path -WorksheetName $SheetName
		}
		return Import-Excel -Path $Path
	}

	throw "Unsupported file extension '$ext'. Use .xlsx or .csv"
}

function Ensure-ADModule {
	if (-not (Get-Module -ListAvailable -Name ActiveDirectory)) {
		throw "ActiveDirectory module not found. Install RSAT AD PowerShell tools first."
	}
	Import-Module ActiveDirectory -ErrorAction Stop
}

function Ensure-GraphModule {
	if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Users)) {
		Write-Info "Microsoft.Graph.Users module not found. Installing for current user..."
		Install-Module Microsoft.Graph.Users -Scope CurrentUser -Force -AllowClobber -ErrorAction Stop
	}
	Import-Module Microsoft.Graph.Users -ErrorAction Stop

	if (-not (Get-MgContext)) {
		Write-Info "Connecting to Microsoft Graph..."
		Connect-MgGraph -Scopes 'User.ReadWrite.All' -NoWelcome
	}
}

function Update-MobileInAD {
	param(
		[string]$Email,
		[string]$Mobile,
		[switch]$DoWhatIf
	)

	$escaped = $Email.Replace("'", "''")
	$user = Get-ADUser -Filter "(mail -eq '$escaped') -or (UserPrincipalName -eq '$escaped')" -Properties mail, userPrincipalName, mobile -ErrorAction SilentlyContinue | Select-Object -First 1
	if (-not $user) {
		return @{ status = 'not_found'; message = 'AD user not found by mail/UPN'; sam = '' }
	}

	if ($DoWhatIf) {
		return @{ status = 'whatif'; message = 'Would update AD mobile'; sam = $user.SamAccountName }
	}

	Set-ADUser -Identity $user.SamAccountName -MobilePhone $Mobile -ErrorAction Stop
	return @{ status = 'success'; message = 'Updated AD mobile'; sam = $user.SamAccountName }
}

function Update-MobileInGraph {
	param(
		[string]$Email,
		[string]$Mobile,
		[switch]$DoWhatIf
	)

	if ($DoWhatIf) {
		return @{ status = 'whatif'; message = 'Would update Graph mobilePhone'; user = $Email }
	}

	Update-MgUser -UserId $Email -MobilePhone $Mobile -ErrorAction Stop
	return @{ status = 'success'; message = 'Updated Graph mobilePhone'; user = $Email }
}

try {
	Write-Info "Loading rows from $SourceFile"
	$rows = @(Load-InputRows -Path $SourceFile -SheetName $WorksheetName)
	if ($rows.Count -eq 0) {
		throw "No rows found in source file"
	}

	$first = $rows[0]
	$props = @($first.PSObject.Properties.Name)

	$emailCol = Resolve-HeaderName -Available $props -Candidates @('Email', 'email', 'UserPrincipalName', 'UPN')
	$mobileCol = Resolve-HeaderName -Available $props -Candidates @('Mobile (Home)', 'Mobile', 'mobile', 'MobilePhone', 'mobilePhone')
	$activeCol = Resolve-HeaderName -Available $props -Candidates @('Active', 'active', 'IsActive')

	if (-not $emailCol) {
		throw "Could not find email column. Expected one of: Email, UserPrincipalName, UPN"
	}
	if (-not $mobileCol) {
		throw "Could not find mobile column. Expected one of: Mobile (Home), Mobile, MobilePhone"
	}

	if ($Target -eq 'AD') {
		Ensure-ADModule
	} else {
		Ensure-GraphModule
	}

	$results = New-Object System.Collections.Generic.List[object]
	$totalCandidates = 0

	foreach ($row in $rows) {
		$email = ("$($row.$emailCol)").Trim()
		$mobile = ("$($row.$mobileCol)").Trim()
		$active = if ($activeCol) { ("$($row.$activeCol)").Trim() } else { '' }

		if (-not $email -or -not $mobile) {
			continue
		}

		if (-not $IncludeInactive -and $activeCol -and -not (Test-Truthy -Value $active)) {
			continue
		}

		$totalCandidates++

		try {
			if ($Target -eq 'AD') {
				$r = Update-MobileInAD -Email $email -Mobile $mobile -DoWhatIf:$WhatIf
				$results.Add([pscustomobject]@{
					email = $email
					mobile_phone = $mobile
					target = 'AD'
					status = $r.status
					sam_account_name = $r.sam
					detail = $r.message
				})
			} else {
				$r = Update-MobileInGraph -Email $email -Mobile $mobile -DoWhatIf:$WhatIf
				$results.Add([pscustomobject]@{
					email = $email
					mobile_phone = $mobile
					target = 'Graph'
					status = $r.status
					sam_account_name = ''
					detail = $r.message
				})
			}
		}
		catch {
			$results.Add([pscustomobject]@{
				email = $email
				mobile_phone = $mobile
				target = $Target
				status = 'failed'
				sam_account_name = ''
				detail = $_.Exception.Message
			})
		}
	}

	$results | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $ReportPath

	$success = @($results | Where-Object { $_.status -eq 'success' }).Count
	$failed = @($results | Where-Object { $_.status -eq 'failed' }).Count
	$notFound = @($results | Where-Object { $_.status -eq 'not_found' }).Count
	$whatifCount = @($results | Where-Object { $_.status -eq 'whatif' }).Count

	Write-Host ""
	Write-Host "Completed mobile update run:" -ForegroundColor Green
	Write-Host "  Target:           $Target"
	Write-Host "  Candidate rows:   $totalCandidates"
	Write-Host "  Success:          $success"
	Write-Host "  Not found:        $notFound"
	Write-Host "  Failed:           $failed"
	Write-Host "  WhatIf:           $whatifCount"
	Write-Host "  Report:           $ReportPath"

	if ($Target -eq 'Graph' -and $failed -gt 0) {
		Write-Warn "If errors mention directory-synced/on-prem mastered users, run with -Target AD instead."
	}
}
catch {
	Write-Error $_.Exception.Message
	exit 1
}

