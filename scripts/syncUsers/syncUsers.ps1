<#
EMAILGISTICS - SYNC USERS POWERSHELL SCRIPT

COPYRIGHT EMAILGISTICS CORP., ALL RIGHT RESERVED.
#>

# Close-Script gracefully closes the script, closing the PSSession if any were opened during the script's runtime
function Close-Script
{
	Write-Host "Closing script..."
	if ($null -ne $session) # check if script opened PSSession, and if so then remove it
	{
		Remove-PSSession $session
	}

	# Sleep for 10 seconds and exit unless the tool is driving a noninteractive run.
	if (-not $env:EMAILGISTICS_NONINTERACTIVE)
	{
		Start-Sleep -Seconds 10
	}
	exit
}

# Test-Version - Verifies that the current powershell version is supported.
function Test-Version
{
	# Get the version of powershell
	$version = (Get-Host | Select-Object Version).Version

	# Check for a valid version
	if (($version.Major -eq 5) -And ($version.Minor -eq 1))
	{
		# Version 5.1 is supported.
		return $true
	}
	elseif ($version.Major -eq 7)
	{
		# Powershell 7 is supported.
		return $true
	} else
	{
		# Any other version of powershell is not supported.
		Write-Host "The installed Powershell version is $($version.Major).$($version.Minor). This script requires PowerShell 5.1 or Powershell 7. Please install one of them to sync your mailbox users."
		return $false
	}
}

# Clear the terminal before starting
Clear-Host

# Verify that the version of powershell is supported for our script.
if ((Test-Version) -eq $false)
{
	# The installed version of powershell is NOT supported, so close the script.
	Close-Script
}

# after a step has finished, wait this many seconds to avoid cluttering stdout
$secondsBetweenSteps = 1

# Set the working directory to the script's directory
$scriptDirectory = "."
Set-Location -Path $scriptDirectory

try {

    $jsonFilePath = Join-Path -Path $scriptDirectory -ChildPath "customerData.json"
    if (Test-Path -Path $jsonFilePath) {
        # Get customer specific variables from dynamically created JSON file
        $customerData = Get-Content -ErrorAction Stop -Raw -Path $jsonFilePath | ConvertFrom-Json
    }
    else {
        $customerData = [pscustomobject]@{}
    }

} catch {

	Write-Host "Error: Could not load `"customerData.json`"."
	Close-Script
}

# set variables based on the customer data
$tokenValidURL = if ($customerData.tokenValidUrl) { $customerData.tokenValidUrl } elseif ($env:EMAILGISTICS_TOKEN_VALID_URL) { $env:EMAILGISTICS_TOKEN_VALID_URL } else { "" }
$userSyncURL = if ($customerData.userSyncUrl) { $customerData.userSyncUrl } elseif ($env:EMAILGISTICS_USER_SYNC_URL) { $env:EMAILGISTICS_USER_SYNC_URL } else { "" }
$authToken = if ($customerData.authToken) { $customerData.authToken } elseif ($env:EMAILGISTICS_AUTH_TOKEN) { $env:EMAILGISTICS_AUTH_TOKEN } else { "" }
$tenantId = if ($customerData.tenantId) { $customerData.tenantId } elseif ($env:EMAILGISTICS_TENANT_ID) { $env:EMAILGISTICS_TENANT_ID } else { "" }
$certificateThumbprint = if ($customerData.certificateThumbprint) { $customerData.certificateThumbprint } elseif ($env:EMAILGISTICS_CERTIFICATE_THUMBPRINT) { $env:EMAILGISTICS_CERTIFICATE_THUMBPRINT } else { "" }
$clientSecret = if ($customerData.clientSecret) { $customerData.clientSecret } elseif ($env:EMAILGISTICS_CLIENT_SECRET) { $env:EMAILGISTICS_CLIENT_SECRET } else { "" }
$appId = if ($customerData.appId) { $customerData.appId } elseif ($env:EMAILGISTICS_APP_ID) { $env:EMAILGISTICS_APP_ID } else { "" }
$organizationDomain = if ($customerData.organizationDomain) { $customerData.organizationDomain } elseif ($env:EMAILGISTICS_ORGANIZATION_DOMAIN) { $env:EMAILGISTICS_ORGANIZATION_DOMAIN } elseif ($env:EXCHANGE_ONLINE_ORGANIZATION) { $env:EXCHANGE_ONLINE_ORGANIZATION } else { "" }
$targetMailbox = if ($env:EMAILGISTICS_TARGET_MAILBOX) { $env:EMAILGISTICS_TARGET_MAILBOX.Trim().ToLowerInvariant() } else { "" }
$syncSecurityGroupsDefault = @("1", "true", "yes", "on") -contains (("$env:EMAILGISTICS_SYNC_SECURITY_GROUPS").Trim().ToLowerInvariant())

$mgGraphAppId = if ($customerData.mgGraphAppId) { $customerData.mgGraphAppId } elseif ($env:MG_GRAPH_APP_ID) { $env:MG_GRAPH_APP_ID } else { "" }

# Device code authentication URLs
$deviceCodeUrl = if ($customerData.deviceCodeUrl) { $customerData.deviceCodeUrl } elseif ($env:EMAILGISTICS_DEVICE_CODE_URL) { $env:EMAILGISTICS_DEVICE_CODE_URL } elseif ($tenantId) { "https://login.microsoftonline.com/$tenantId/oauth2/v2.0/devicecode" } else { "" }
$tokenUrl = if ($customerData.tokenUrl) { $customerData.tokenUrl } elseif ($env:EMAILGISTICS_TOKEN_URL) { $env:EMAILGISTICS_TOKEN_URL } elseif ($tenantId) { "https://login.microsoftonline.com/$tenantId/oauth2/v2.0/token" } else { "" }
$deviceLoginUrl = if ($customerData.deviceLoginUrl) { $customerData.deviceLoginUrl } elseif ($env:EMAILGISTICS_DEVICE_LOGIN_URL) { $env:EMAILGISTICS_DEVICE_LOGIN_URL } else { "https://microsoft.com/devicelogin" }

if (-not $tokenValidURL -or -not $userSyncURL -or -not $authToken) {
    Write-Host "Error: Emailgistics API settings are missing. Provide tokenValidUrl, userSyncUrl, and authToken via customerData.json or environment variables."
    Close-Script
}

$header = @{
	'Content-Type' = 'application/json'
	'eg-token' = $authToken
}

# Set up empty mailboxes array
$mailboxes = @()

# Loop through all onboarded mailboxes and add all the mailbox that wants to the synced
ForEach($mailbox in @($customerData.mailboxes)) {
    if ($targetMailbox -and $mailbox.mailboxAddress -and $mailbox.mailboxAddress.Trim().ToLowerInvariant() -ne $targetMailbox) {
        continue
    }

    # Check if the mailbox does not want to be synchronized
    if ($mailbox.syncMailbox) {

        # Add the mailbox to the mailboxes array
        $mailboxes += $mailbox
    }
}

if ($targetMailbox -and $mailboxes.Count -eq 0) {
    $mailboxes += [pscustomobject]@{
        mailboxAddress = $targetMailbox
        syncMailbox = $true
        syncSecurityGroups = $syncSecurityGroupsDefault
    }
}

if ($mailboxes.Count -eq 0) {
    Write-Host "Error: No Emailgistics mailboxes were configured. Provide customerData.json mailboxes or EMAILGISTICS_TARGET_MAILBOX."
    Close-Script
}

# This function loops through the given array of UPNs and trims the first 32 characters. This is necessary when we
# get a list of deleted users using the '(Get-MgDirectoryDeletedItemAsUser).UserPrincipalName' command because it returns
# a concatenation of the user's ID (without hyphens) and their UPN.
function TrimUPNsOfDeletedUsers
{
    param([String[]]$mailboxUsers)

    ForEach ($mailboxUser in $mailboxUsers)
    {
		$mailboxUser = $mailboxUser.substring(32)
    }

    return $mailboxUsers
}

# Get-ActiveUsers returns the active users from a given array of mailbox users and checks if users are a mail enabled security group
function Get-ActiveUsers
{
    param([Parameter(Mandatory)][String[]]$mailboxUsers, [Parameter(Mandatory)][bool]$syncSecurityGroups)
    # store all data
    $mailboxActiveUsersTemp = @()


    ForEach ($mailboxUser in $mailboxUsers)
    {
		if ($mailboxUser -match "\\") # after sync update
		{
			continue
		}
		else
		{
			try
			{
				Get-User $mailboxUser -ErrorAction Stop -WarningAction SilentlyContinue | Out-Null
				$mailboxActiveUsersTemp += $mailboxUser
			}
			catch
			{
				# check if address is a mail enabled security group
				if (($syncSecurityGroups) -AND (Get-DistributionGroup -Identity $mailboxUser -ErrorAction 'SilentlyContinue')){
					$groupMembers = (Get-DistributionGroupMember -Identity $mailboxUser  -Resultsize Unlimited |Select PrimarySMTPAddress,RecipientType| Where-Object {($_.RecipientType -eq "UserMailbox") -or ($_.RecipientType -eq "MailUniversalSecurityGroup")}).PrimarySMTPAddress
					if ($groupMembers)
					{
						$activeGroupMembers = Get-ActiveUsers $groupMembers $syncSecurityGroups
						ForEach ($activeGroupMember in $activeGroupMembers)
						{
							$mailboxActiveUsersTemp += $activeGroupMember
						}
					}

				}
				continue
			}
		}
    }
    # update mailbox users list with only active users.
    return $mailboxActiveUsersTemp
}

function Poll-Address
{
	 # regex pattern to ensure email address is valid
	$EmailRegex = '^([\w-\.]+)@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.)|(([\w-]+\.)+))([a-zA-Z]{2,6}|[0-9]{1,3})(\]?)$'
	do
    {
         # poll user until their input is valid
        $response = Read-Host -Prompt "`nPlease enter your Microsoft 365 Administrator username (as shown in the Username column of Microsoft 365 Admin Center)"
    }
    until ($response -cmatch "$EmailRegex") # keep generating password until it matches
    return $response
}

# Poll-Host accepts a string and prompts the user for a yes or no input, and returns either "yes" or "no"
function Poll-Host
{
    param([Parameter(Mandatory)][String]$prompt) # given $prompt should be a yes/no question

    # poll user until their input is valid
    do
    {
        $response = Read-Host -Prompt $prompt
    }
    until ($response -like "y" -Or $response -like "yes" -Or $response -like "n" -Or $response -like "no") # case insensitive

    if ($response -like "y" -Or $response -like "yes")
    {
        return "yes"
    }
    return "no"
}

# Get-DeviceCodeToken performs the OAuth 2.0 device code flow manually via REST API.
# This bypasses the WAM broker which crashes on PowerShell 7.
function Get-DeviceCodeToken
{
    param(
        [Parameter(Mandatory)][String]$ClientId,
        [Parameter(Mandatory)][String]$Scope,
        [Parameter(Mandatory)][String]$DeviceCodeUri,
        [Parameter(Mandatory)][String]$TokenUri,
        [Parameter(Mandatory)][String]$DeviceLoginUri
    )

    $deviceCodeResponse = Invoke-RestMethod -Method POST -Uri $DeviceCodeUri -Body @{
        client_id = $ClientId
        scope     = $Scope
    }

    Write-Host "`n$($deviceCodeResponse.message)"
    Start-Sleep -Seconds 2
    Start-Process $DeviceLoginUri

    $token = $null
    while ($null -eq $token) {
        Start-Sleep -Seconds $deviceCodeResponse.interval
        try {
            $token = Invoke-RestMethod -Method POST -Uri $TokenUri -Body @{
                grant_type  = "urn:ietf:params:oauth:grant-type:device_code"
                client_id   = $ClientId
                device_code = $deviceCodeResponse.device_code
            }
        }
        catch {
            $errBody = $_.ErrorDetails.Message | ConvertFrom-Json -ErrorAction SilentlyContinue
            if ($errBody.error -eq "authorization_pending") {
                continue
            }
            throw
        }
    }

    return $token
}

# Get-ClientCredentialToken performs the OAuth 2.0 client credentials flow via REST API.
function Get-ClientCredentialToken
{
    param(
        [Parameter(Mandatory)][String]$ClientId,
        [Parameter(Mandatory)][String]$ClientSecret,
        [Parameter(Mandatory)][String]$Scope,
        [Parameter(Mandatory)][String]$TokenUri
    )

    $tokenResponse = Invoke-RestMethod -Method POST -Uri $TokenUri -Body @{
        client_id     = $ClientId
        client_secret = $ClientSecret
        scope         = $Scope
        grant_type    = "client_credentials"
    }

    return $tokenResponse.access_token
}

# Get-LoggedInUserData accepts a string of logged in user email and gets their ID, display name, and email, and returns it as a hash tables
# If multiple values are returned a best match is done to find the ID, display name and email
function Get-LoggedInUserData
{
	param([Parameter(Mandatory)][String]$email)

	# get all user data needed for the request body
	$userInfo = Get-User -Identity $email | Select-Object ExternalDirectoryObjectId, DisplayName, UserPrincipalName
    # create a temp array to store the data before multi-value checks
	$tempData =  @{
		id = $userInfo.ExternalDirectoryObjectId
		displayName = $userInfo.DisplayName
		mail = $userInfo.UserPrincipalName
	}
	# if single value return to calling function
	if($tempData.id.Count -eq 1) {
	    return $tempData
	}
	else {
	    #check if best match can be done., if not error out..
	    if(($tempData.mail.Contains($email) -eq $true) -AND ($tempData.mail.Count -eq $tempData.displayName.Count) -AND ($tempData.mail.Count -eq $tempData.id.Count) ) {
	        # start best match solution
	        # get the correct index
	        $index = (0..($tempData.mail.Count-1)) | where {$tempData.mail[$_] -eq $email}
	        return @{
                id = $userInfo.ExternalDirectoryObjectId[$index]
                displayName = $userInfo.DisplayName[$index]
                mail = $userInfo.UserPrincipalName[$index]
            }
        }
        else {
            Write-Host "Did not receive logged-in user's data..."
            return @{
				id = ""
				displayName = ""
				mail = $email
			}
        }
	}
}

# Get-MailboxUserData accepts a string of a mailbox or user and gets their ID, display name, and email, and returns it as a hash tables
function Get-MailboxUserData
{
	param([Parameter(Mandatory)][String]$mailboxUser)
	# added in to get the right users(active)
    $mailboxUsers = @(Get-ActiveUsers $mailboxUsers $false)

	# get all user data needed for the request body
	$userInfo = Get-User -Identity $mailboxUser | Select-Object ExternalDirectoryObjectId, DisplayName, UserPrincipalName

	return @{
		id = $userInfo.ExternalDirectoryObjectId
		displayName = $userInfo.DisplayName
		mail = $userInfo.UserPrincipalName
	}
}

# Get-MailboxUsersData accepts a string array of mailbox users and gets their ID, display name, and email, and returns it as an array of hash tables
function Get-MailboxUsersData
{
	param([Parameter(Mandatory)][String[]]$mailboxUsers)

	# create empty array
	$data = @()

	ForEach ($mailboxUser in $mailboxUsers)
	{
		# get all user data needed for the request body
		$userInfo = Get-User -RecipientTypeDetails UserMailbox,User -Identity $mailboxUser -ErrorAction 'SilentlyContinue' | Select-Object ExternalDirectoryObjectId, DisplayName, UserPrincipalName
		if ($userInfo) {
			$data += @{
				id = $userInfo.ExternalDirectoryObjectId
				displayName = $userInfo.DisplayName
				mail = $userInfo.UserPrincipalName
			}
		} else {
		    Write-Host -ForegroundColor red "Unable to get user info for $($mailboxUser). Please check the RecipientType of the mailbox in Exchange."
		}
	}

	return $data
}

# Remind user to check the readme
Write-Host "Starting script...`nPlease read the readme file accompanying this script.`n"
Start-Sleep -Seconds 3

# install NuGet to allow Install-Module cmdlet
Write-Host "`nChecking for NuGet package...`n"
if (Get-PackageProvider -ListAvailable -Name NuGet) {
    Write-Host "NuGet package exists..."
}
else {
    Install-PackageProvider -Name NuGet -Force -Scope CurrentUser | Out-Null
}

# remove any sessions created from previous run of script, if any exist (likely after forceful closing)
Write-Host -NoNewLine "Checking for previous sessions opened by Emailgistics..."
$previousSession = Get-PSSession | Where-Object -Property "Name" -like "Emailgistics-SyncUsers"
if ($null -ne $previousSession)
{
	$previousSession | Remove-PSSession
	Write-Host "`nRemoved previous sessions."
}
else
{
	Write-Host " Done"
}
Start-Sleep -Seconds $secondsBetweenSteps

Write-Host -NoNewline "`nChecking if the script can open an additional session..."
# check if user is at maximum amount of opened PSSessions
do
{
	# get a list of open PSSessions
	$openedSessions = Get-PSSession | Where-Object {$_.State -like "Opened" -And $_.ConfigurationName -like "Microsoft.Exchange"}

	# if there are 3 (maximum allowed amount), prompt user to remove/close one so the script doesn't have to force anything
	if ($openedSessions.Length -ge 3)
	{
		Write-Warning "The script cannot add any additional Exchange sessions. Please close a session to continue."
		Read-Host -Prompt "Press Enter to retry"
	}
}
until ($openedSessions.Length -lt 3)

Write-Host " Done"
Start-Sleep -Seconds $secondsBetweenSteps

Write-Host -NoNewline "`nVerifying token..."

ForEach ($mailbox in $mailboxes)
{
    $tokenValidURLCorrected = $tokenValidURL + "?mailboxEmail=" + $mailbox.mailboxAddress
    $response = try { Invoke-RestMethod -UseBasicParsing -Uri $tokenValidURLCorrected -Method Get -Headers $header } catch { $_ }
    if ($null -ne $response.ErrorDetails.Message)
    {
    	Write-Host "`nError: $($response.ErrorDetails.Message)"
    	Write-Host "Please redownload the script and run again."
    	Close-Script
    }
    elseif ($null -ne $response.Exception)
    {
    	Write-Host "`nError: $($response.Exception)"
    	Write-Host "Please redownload the script and run again."
    	Close-Script
    }
}

Write-Host " Done"
Start-Sleep -Seconds $secondsBetweenSteps

# Install Microsoft Graph modules BEFORE ExchangeOnlineManagement to prevent MSAL assembly version conflicts.
# The Graph module must load its MSAL DLL first; if EXO loads an older version first, Connect-MgGraph fails.
Write-Host "`nChecking for required Microsoft.Graph submodules...`n"
#set trusted policy for PSGallery
Set-PSRepository -Name 'PSGallery' -InstallationPolicy Trusted # user won't be prompted about install
if ((Get-Module -ListAvailable -Name Microsoft.Graph.Authentication) -AND (Get-Module -ListAvailable -Name Microsoft.Graph.Users)) {
    Write-Host "Required Microsoft.Graph submodules exist..."
	$authModuleVersion = (Get-Module -ListAvailable -Name Microsoft.Graph.Authentication | Sort-Object Version -Descending | Select-Object -First 1).Version
	$usersModuleVersion = (Get-Module -ListAvailable -Name Microsoft.Graph.Users | Sort-Object Version -Descending | Select-Object -First 1).Version
	if ((($authModuleVersion.Major -eq 2) -And ($authModuleVersion.Minor -eq 6) -And ($authModuleVersion.Build -eq 0)) -OR (($usersModuleVersion.Major -eq 2) -And ($usersModuleVersion.Minor -eq 6) -And ($usersModuleVersion.Build -eq 0))) # Bug in Microsoft Graph Powershell 2.6.0, Upgrade.
	{
		$response = Poll-Host "Microsoft.Graph submodule(s) version 2.6.0 detected (unsupported). Would you like to upgrade? (y/N)"
		if ($response -like "no")
		{
			Write-Host "Please upgrade Microsoft.Graph submodules and run the script again."
			Close-Script
		}else{
			Write-Host -NoNewline "Updating Microsoft.Graph submodules..."
			Update-Module -Name Microsoft.Graph.Authentication -Force
			Update-Module -Name Microsoft.Graph.Users -Force
			Write-Host " Done"
		}
	} else {
		Write-Host "Microsoft.Graph submodules OK."
	}
}
else {
    Write-Host -NoNewline "Installing required Microsoft.Graph submodules..."
    Install-Module -Name Microsoft.Graph.Authentication -Scope CurrentUser
    Install-Module -Name Microsoft.Graph.Users -Scope CurrentUser
    Write-Host " Done"
}
# Pre-load Graph module to ensure its MSAL assemblies are loaded before ExchangeOnlineManagement
Import-Module Microsoft.Graph.Authentication -ErrorAction SilentlyContinue

Start-Sleep -Seconds $secondsBetweenSteps

# Install Exchange Online module if not already installed
Write-Host "`nChecking for ExchangeOnlineManagement module...`n"
$installedEXOModule = Get-Module -ListAvailable -Name ExchangeOnlineManagement | Sort-Object Version -Descending | Select-Object -First 1
if ($installedEXOModule) {
    if ($installedEXOModule.Version.Major -gt 2) {
        Write-Host "ExchangeOnlineManagement module exists..."
    } else {
        $response = Poll-Host "`nYou are using a lower version of ExchangeOnlineManagement which might cause issues. Would you like to upgrade? (y/N)"
        if ($response -like "yes")
        {
            Write-Host "Uninstalling lower version of ExchangeOnlineManagement..."
            Uninstall-Module -Name ExchangeOnlineManagement -AllVersions

            Write-Host -NoNewline "Installing ExchangeOnlineManagement module..."
            Install-Module -Name ExchangeOnlineManagement -Scope CurrentUser
            Write-Host " Done"
        }
        else
        {
            Write-Host "Keeping current version. Continuing..."
        }
        $installedEXOModule = Get-Module -ListAvailable -Name ExchangeOnlineManagement | Sort-Object Version -Descending | Select-Object -First 1
    }
}
else {
    Write-Host -NoNewline "Installing ExchangeOnlineManagement module..."
    Install-Module -Name ExchangeOnlineManagement -Scope CurrentUser
    Write-Host " Done"
    $installedEXOModule = Get-Module -ListAvailable -Name ExchangeOnlineManagement | Sort-Object Version -Descending | Select-Object -First 1
}

# PowerShell 7: Ensure ExchangeOnlineManagement >= 3.7.2 for -DisableWAM support
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $installedEXOModule = Get-Module -ListAvailable -Name ExchangeOnlineManagement | Sort-Object Version -Descending | Select-Object -First 1
    if ($installedEXOModule -and $installedEXOModule.Version -lt [version]"3.7.2") {
        Write-Host "ExchangeOnlineManagement $($installedEXOModule.Version) detected. Upgrading for PowerShell 7 compatibility..."
        Uninstall-Module -Name ExchangeOnlineManagement -AllVersions -Force -WarningAction SilentlyContinue
        Install-Module -Name ExchangeOnlineManagement -Scope CurrentUser -Force -WarningAction SilentlyContinue
        Write-Host "ExchangeOnlineManagement upgraded."
        $installedEXOModule = Get-Module -ListAvailable -Name ExchangeOnlineManagement | Sort-Object Version -Descending | Select-Object -First 1
    }
}

Start-Sleep -Seconds $secondsBetweenSteps

# set flags for upcoming loop
$successfulAuth = $false
$noninteractive = $false # default behaviour will be interactive execution

# check if all properties required for noninteractive execution have been provided
if (($tenantId) -AND ($appId) -AND ($organizationDomain) -AND (($certificateThumbprint) -OR ($clientSecret))) {
    Write-Host "`nRunning script in noninteractive mode..."
    $noninteractive = $true
}

# Detect PowerShell 7 and prompt for authentication mode (interactive only)
$useDeviceAuth = $false
if ($noninteractive -eq $false) {
    $psVer = (Get-Host | Select-Object Version).Version
    if ($psVer.Major -ge 7)
    {
        Write-Host "`nPowerShell 7 detected. Please select an authentication method:"
        Write-Host "Press '1': Standard login (interactive browser)"
        Write-Host "Press '2': Device code authentication`n"
        do
        {
            $authChoice = Read-Host "Please make a selection"
        }
        until ($authChoice -eq '1' -Or $authChoice -eq '2')

        if ($authChoice -eq '2')
        {
            if (-not $mgGraphAppId -or -not $deviceCodeUrl -or -not $tokenUrl -or -not $deviceLoginUrl) {
                Write-Host "Device code authentication is not fully configured for this script."
                Close-Script
            }
            $useDeviceAuth = $true
            Write-Host "Selected: Device code authentication"
        }
        else
        {
            Write-Host "Selected: Standard login"
        }
    }
}

do
{
	# wrap following cmdlet calls in a try/catch to silently handle errors/exceptions
	try
	{
        # initially set variable to $null for comparison in the catch section to check for cancellation
        if ($noninteractive -eq $false) {
            # get global admin Microsoft 365 UserPrincipalName
            Write-Host "`nPlease enter Exchange Administrator credentials."
            $userCredential = Poll-Address
        }

        Write-Host -NoNewline "Connecting to Microsoft Graph Powershell..."

        if ($noninteractive -eq $true) {
            if ($certificateThumbprint) {
                # Noninteractive login with certificate thumbprint
                Connect-MgGraph -TenantId $tenantId -ApplicationId $appId -CertificateThumbprint $certificateThumbprint -NoWelcome
            }
            else {
                # Noninteractive login with client secret app credentials
                $mgGraphScope = "https://graph.microsoft.com/.default"
                $mgToken = Get-ClientCredentialToken -ClientId $appId -ClientSecret $clientSecret -Scope $mgGraphScope -TokenUri $tokenUrl
                $secureToken = ConvertTo-SecureString $mgToken -AsPlainText -Force
                Connect-MgGraph -AccessToken $secureToken -NoWelcome
            }
        }
        elseif ($useDeviceAuth)
        {
            try
            {
                Write-Host "`nUsing device code authentication for Microsoft Graph..."
                $mgGraphScope = "https://graph.microsoft.com/User.Read https://graph.microsoft.com/Directory.Read.All offline_access"
                $mgToken = Get-DeviceCodeToken -ClientId $mgGraphAppId -Scope $mgGraphScope -DeviceCodeUri $deviceCodeUrl -TokenUri $tokenUrl -DeviceLoginUri $deviceLoginUrl
                $secureToken = ConvertTo-SecureString $mgToken.access_token -AsPlainText -Force
                Connect-MgGraph -AccessToken $secureToken -NoWelcome
            }
            catch
            {
                Write-Host "`nDevice code authentication failed. Would you like to try standard login instead?"
                $fallbackChoice = Poll-Host "Switch to standard login? (y/N)"
                if ($fallbackChoice -like "yes") {
                    $useDeviceAuth = $false
                    Write-Host "Switching to standard login..."
                    Connect-MgGraph -TenantId $tenantId -Scopes "User.Read","Directory.Read.All" -NoWelcome
                } else {
                    Write-Host "`nPlease re-enter the Administrator credentials."
                    $mgGraphScope = "https://graph.microsoft.com/User.Read https://graph.microsoft.com/Directory.Read.All offline_access"
                    $mgToken = Get-DeviceCodeToken -ClientId $mgGraphAppId -Scope $mgGraphScope -DeviceCodeUri $deviceCodeUrl -TokenUri $tokenUrl -DeviceLoginUri $deviceLoginUrl
                    $secureToken = ConvertTo-SecureString $mgToken.access_token -AsPlainText -Force
                    Connect-MgGraph -AccessToken $secureToken -NoWelcome
                }
            }
        }
        else
        {
            # Regular login with credentials
            Connect-MgGraph -TenantId $tenantId -Scopes "User.Read","Directory.Read.All" -NoWelcome
        }

        Write-Host " Done"

        # validate Graph session and check for cached credential mismatch (interactive mode only)
        $mgContext = Get-MgContext

        if ($noninteractive -eq $false) {
            $expectedAccount = $userCredential.Trim().ToLowerInvariant()
            $actualAccount = if ($mgContext.Account) { $mgContext.Account.Trim().ToLowerInvariant() } else { "" }

            if ([string]::IsNullOrEmpty($actualAccount))
            {
                Write-Host "`n--- Graph Session Diagnostics ---"
                Write-Host "Graph Account: $($mgContext.Account)"
                Write-Host "Graph TenantId: $($mgContext.TenantId)"
                Write-Host "Graph AuthType: $($mgContext.AuthType)"
                Write-Host "Graph Scopes: $($mgContext.Scopes -join ', ')"
                Write-Host "Entered Credential: $userCredential"
                Write-Host "Graph authentication failed - no account in context. Retrying..."
                try { Disconnect-MgGraph -ErrorAction SilentlyContinue | Out-Null } catch {}
                try { Clear-MgContext -ErrorAction SilentlyContinue | Out-Null } catch {}
                Connect-MgGraph -TenantId $tenantId -Scopes "User.Read","Directory.Read.All" -NoWelcome -ErrorAction Stop
                $mgContext = Get-MgContext
                Write-Host "Retry Graph Account: $($mgContext.Account)"
                Write-Host "--- End Graph Session Diagnostics ---"
            }
            elseif ($actualAccount -ne $expectedAccount)
            {
                Write-Host "`n--- Graph Session Diagnostics ---"
                Write-Host "Graph Account: $($mgContext.Account)"
                Write-Host "Graph TenantId: $($mgContext.TenantId)"
                Write-Host "Graph AuthType: $($mgContext.AuthType)"
                Write-Host "Graph Scopes: $($mgContext.Scopes -join ', ')"
                Write-Host "Entered Credential: $userCredential"
                Write-Host "Cached credential mismatch detected. Graph session is for '$($mgContext.Account)' but expected '$userCredential'. Reconnecting..."
                try { Disconnect-MgGraph -ErrorAction SilentlyContinue | Out-Null } catch {}
                try { Clear-MgContext -ErrorAction SilentlyContinue | Out-Null } catch {}
                Connect-MgGraph -TenantId $tenantId -Scopes "User.Read","Directory.Read.All" -NoWelcome -ErrorAction Stop
                $mgContext = Get-MgContext
                $actualAccount2 = if ($mgContext.Account) { $mgContext.Account.Trim().ToLowerInvariant() } else { "" }
                if ($actualAccount2 -ne $expectedAccount)
                {
                    Write-Host "WARNING: Graph is still authenticated as '$($mgContext.Account)' instead of '$userCredential'. Please select the correct account."
                }
                else
                {
                    Write-Host "Reconnected Graph Account: $($mgContext.Account)"
                }
                Write-Host "--- End Graph Session Diagnostics ---"
            }
        }

        Start-Sleep -Seconds $secondsBetweenSteps

		Write-Host -NoNewline "`nCreate new ExchangeOnline Session..."

        if ($noninteractive -eq $true) {
            if ($certificateThumbprint) {
                # Noninteractive login with certificate thumbprint
                Connect-ExchangeOnline -CertificateThumbprint $certificateThumbprint -AppID $appId -Organization $organizationDomain -ShowBanner:$false
            }
            else {
                # Noninteractive login with client secret app credentials
                $exoScope = "https://outlook.office365.com/.default"
                $exoToken = Get-ClientCredentialToken -ClientId $appId -ClientSecret $clientSecret -Scope $exoScope -TokenUri $tokenUrl
                $secureExoToken = ConvertTo-SecureString $exoToken -AsPlainText -Force
                Connect-ExchangeOnline -AccessToken $secureExoToken -Organization $organizationDomain -ShowBanner:$false
            }
        }
        elseif ($useDeviceAuth)
        {
            Write-Host "`nUsing device code authentication for Exchange Online..."
            Write-Host "Opening browser for device login..."
            Start-Process $deviceLoginUrl
            Connect-ExchangeOnline -Device -UserPrincipalName $userCredential -ShowBanner:$false
        }
        elseif ($PSVersionTable.PSVersion.Major -ge 7)
        {
            Connect-ExchangeOnline -UserPrincipalName $userCredential -ShowBanner:$false -DisableWAM
        }
        else
        {
            # Regular login with credentials
            Connect-ExchangeOnline -UserPrincipalName $userCredential -ShowBanner:$false
        }

		Write-Host " Done"
        if ($noninteractive -eq $false) {
            Write-Host "Exchange Online connected with UserPrincipalName: $userCredential"
        }
		Start-Sleep -Seconds $secondsBetweenSteps

		if ($noninteractive -eq $true) {
		    # This is a noninteractive execution, so if execution has been successful up to this point then we must have logged in correctly.
            $successfulAuth = $true
		}
		else
		{
		    # ensure user has sufficient permissions
            # NOTE: The DisplayName property will have the roles.
            $userRoles = $null
            $roleCheckUserId = $userCredential

            # Attempt 1: Use the entered credential (email/UPN)
            try
            {
                $userRoles = Get-MgUserMemberOfAsDirectoryRole -UserId $roleCheckUserId -ErrorAction Stop
            }
            catch
            {
                Write-Host "`n--- Role Check Diagnostics ---"
                Write-Host "Attempting Get-MgUserMemberOfAsDirectoryRole with UserId: '$roleCheckUserId' (Type: $($roleCheckUserId.GetType().Name))"
                Write-Host "Role check with entered credential failed: $($_.Exception.Message)"
                Write-Host "ErrorCode: $($_.FullyQualifiedErrorId)"

                # Attempt 2: Use the Graph context account if different
                $graphAccount = (Get-MgContext).Account
                if ($graphAccount -and $graphAccount -ne $roleCheckUserId)
                {
                    Write-Host "Retrying with Graph context account: '$graphAccount'"
                    try
                    {
                        $userRoles = Get-MgUserMemberOfAsDirectoryRole -UserId $graphAccount -ErrorAction Stop
                        Write-Host "Role check succeeded with Graph context account."
                    }
                    catch
                    {
                        Write-Host "Role check with Graph context account failed: $($_.Exception.Message)"
                    }
                }

                # Attempt 3: Use the user's Object ID
                if ($null -eq $userRoles)
                {
                    $lookupId = if ($graphAccount) { $graphAccount } else { $roleCheckUserId }
                    Write-Host "Retrying with Object ID lookup for: '$lookupId'"
                    try
                    {
                        $mgUser = Get-MgUser -UserId $lookupId -ErrorAction Stop
                        Write-Host "Found user - ObjectId: $($mgUser.Id), UPN: $($mgUser.UserPrincipalName), Mail: $($mgUser.Mail)"
                        $userRoles = Get-MgUserMemberOfAsDirectoryRole -UserId $mgUser.Id -ErrorAction Stop
                        Write-Host "Role check succeeded with Object ID."
                    }
                    catch
                    {
                        Write-Host "Role check with Object ID failed: $($_.Exception.Message)"
                    }
                }

                if ($null -ne $userRoles)
                {
                    Write-Host "Roles found: $($userRoles.DisplayName -join ', ')"
                }
                else
                {
                    Write-Host "WARNING: Could not retrieve user roles after all attempts."
                }
                Write-Host "--- End Role Check Diagnostics ---"
            }

            # if roles could not be retrieved, do not proceed
            if (-not $userRoles)
            {
                Write-Host "Unable to retrieve directory roles. Cannot validate privileges."
                Read-Host "`nPress Enter to try again..."
            }
            # if the logged in user's email is in the adminUsers list, they are an admin and can continue running the script
            elseif (($userRoles.DisplayName -contains 'Exchange Service Administrator') -OR ($userRoles.DisplayName -contains 'Exchange Administrator') -OR ($userRoles.DisplayName -contains 'Company Administrator') -OR ($userRoles.DisplayName -contains 'Global Administrator'))
            {
                # set successfulAuth flag to true and break out of the loop
                $successfulAuth = $true
            }
            else
            {
                # go back to start of the loop
                Write-Host "This account does not have the required administrator privileges."
                Read-Host "`nPress Enter to log in as a different user..."

                Remove-PSSession $session
            }
		}
	}
	catch
	{
		# if the user wants to cancel, close script
		if (($null -eq $userCredential) -AND ($noninteractive -eq $false))
		{
			Write-Host "Login cancelled."
			Close-Script
		}
		elseif ($noninteractive -eq $true)
		{
		    Write-Host -Foreground Red $_
            Write-Host "`nThe provided credentials are invalid. Please verify that the certificate thumbprint, app ID, and organization are correct and that the application has the necessary privileges."
            Close-Script
		}
		else
		{
		    # Pipe the error message to the console
		    Write-Host -Foreground Red $_

			Write-Host "Failed to connect to Microsoft Graph or Exchange Online. Please try again."
		}
	}
}
until ($successfulAuth)

Write-Host "Login successful.`n"

Write-Host -NoNewline "Gathering user data..."

# create empty array for the hash tables that will be appended
$hashBody = @()

# loop through mailboxes to get user data per mailbox
ForEach ($mailbox in $mailboxes)
{
	$mailboxUsers = (Get-EXORecipientPermission $mailbox.mailboxAddress | Where-Object {($_.IsInherited -eq $false) -and -not ($_.Trustee -like "NT AUTHORITY\SELF")}).Trustee
    if ($mailboxUsers)
    {
        # return active users
        $mailboxUsers = Get-ActiveUsers $mailboxUsers $mailbox.syncSecurityGroups | Select-Object -Unique
        if ($mailboxUsers)
        {
            if ($noninteractive -eq $false) {
                # This is an interactive execution
                $hashBody += @{
                    sharedMailboxInfo = Get-MailboxUserData $mailbox.mailboxAddress
                    exchangeAdmin = Get-LoggedInUserData $userCredential
                    usersList = @(Get-MailboxUsersData $mailboxUsers) # wrap response into array to prevent type coercion from array to object
                }
            }
            else
            {
                $hashBody += @{
                    sharedMailboxInfo = Get-MailboxUserData $mailbox.mailboxAddress
                    exchangeAdmin = @{
                        id = ""
                        displayName = ""
                        mail = ""
                    }
                    usersList = @(Get-MailboxUsersData $mailboxUsers) # wrap response into array to prevent type coercion from array to object
                }
            }
        }
        else
        {
            Write-Host "Did not receive Mailbox Users List from Microsoft"
            Write-Host "Please redownload the script and try again later."
            Close-Script
        }
    }
    else
    {
        Write-Host "Did not receive Mailbox Users List from Microsoft"
		$mailboxRecipients= Get-EXORecipientPermission $mailbox.mailboxAddress
		Write-Host "retrieved mailbox recipients of"$mailbox
		Write-Output $mailboxRecipients
        Write-Host "Please redownload the script and try again later."
    	Close-Script
    }

}
Write-Host " Done"
Start-Sleep -Seconds $secondsBetweenSteps

Write-Host -NoNewline "Reporting users data to Emailgistics..."

$errorFlag = $false
ForEach ($item in $hashBody) {
	Write-Host "`nReporting users data for shared mailbox: $($item.sharedMailboxInfo.mail)"
	$body = ConvertTo-Json $item -Depth 3
	$userSyncUrlCorrected = $userSyncUrl + "?mailboxId=" + $item.sharedMailboxInfo.id
	$response = try { Invoke-RestMethod -UseBasicParsing -Uri $userSyncUrlCorrected -Method Post -ContentType 'application/json; charset=utf-8' -Headers $header -Body $body } catch { $_ }
	if ($null -ne $response.ErrorDetails.Message)
	{
		$errorFlag = $true
		Write-Host "`nError: $($response.ErrorDetails.Message)"
	} elseif ($null -ne $response.Exception)
	{
		$errorFlag = $true
		Write-Host "`nError: $($response.Exception)"
	} else {
		$mailboxID = $response.statusInfo | Get-Member | Where-Object {$_.MemberType -eq "NoteProperty"} | Select-Object -ExpandProperty "Name"
		$adddedUsers = $response.statusInfo.$mailboxID.addedUsers
		$removedUsers = $response.statusInfo.$mailboxID.removedUsers
		$mailboxStatus = $response.statusInfo.$mailboxId.status

		if ($mailboxStatus -ne "OK"){
			$errorFlag = $true
			Write-Host "`nError syncing users for $($response.sharedMailboxEmail): $($mailboxStatus)"
		}else {
			Write-Host "`nUsers have been successfully synced for $($response.sharedMailboxEmail)."
		}

		if ($adddedUsers.Length -gt 0 -Or $removedUsers.Length -gt 0)
		{
			if ($adddedUsers.Length -gt 0)
			{
				Write-Host "Users added to $($response.sharedMailboxEmail): "
				Write-Host "`t$adddedUsers"
			}

			if ($removedUsers.Length -gt 0)
			{
				Write-Host "Users removed from $($response.sharedMailboxEmail): "
				Write-Host "`t$removedUsers"

				if ($null -ne $response.modifiedRulesStatuses -and $response.modifiedRulesStatuses.Length -gt 0)
				{
					Write-Host "Changes to rules for $($response.sharedMailboxEmail):"
					ForEach ($msg in $response.modifiedRulesStatuses)
					{
						Write-Host "`t$msg"
					}
				}
			}
		}
		else
		{
			Write-Host "No changes in users for $($response.sharedMailboxEmail)."
		}
	}
}

Write-Host " Done"
Start-Sleep -Seconds $secondsBetweenSteps

if ($errorFlag) {
	Write-Host "Please redownload the script and try again later."
}

Close-Script

# SIG # Begin signature block
# MIIukwYJKoZIhvcNAQcCoIIuhDCCLoACAQExDzANBglghkgBZQMEAgEFADB5Bgor
# BgEEAYI3AgEEoGswaTA0BgorBgEEAYI3AgEeMCYCAwEAAAQQH8w7YFlLCE63JNLG
# KX7zUQIBAAIBAAIBAAIBAAIBADAxMA0GCWCGSAFlAwQCAQUABCA5CBhT+oBNwR+f
# SAGMJjPrpgd0KDFG+foeIZIMXzqCyqCCEfwwggVvMIIEV6ADAgECAhBI/JO0YFWU
# jTanyYqJ1pQWMA0GCSqGSIb3DQEBDAUAMHsxCzAJBgNVBAYTAkdCMRswGQYDVQQI
# DBJHcmVhdGVyIE1hbmNoZXN0ZXIxEDAOBgNVBAcMB1NhbGZvcmQxGjAYBgNVBAoM
# EUNvbW9kbyBDQSBMaW1pdGVkMSEwHwYDVQQDDBhBQUEgQ2VydGlmaWNhdGUgU2Vy
# dmljZXMwHhcNMjEwNTI1MDAwMDAwWhcNMjgxMjMxMjM1OTU5WjBWMQswCQYDVQQG
# EwJHQjEYMBYGA1UEChMPU2VjdGlnbyBMaW1pdGVkMS0wKwYDVQQDEyRTZWN0aWdv
# IFB1YmxpYyBDb2RlIFNpZ25pbmcgUm9vdCBSNDYwggIiMA0GCSqGSIb3DQEBAQUA
# A4ICDwAwggIKAoICAQCN55QSIgQkdC7/FiMCkoq2rjaFrEfUI5ErPtx94jGgUW+s
# hJHjUoq14pbe0IdjJImK/+8Skzt9u7aKvb0Ffyeba2XTpQxpsbxJOZrxbW6q5KCD
# J9qaDStQ6Utbs7hkNqR+Sj2pcaths3OzPAsM79szV+W+NDfjlxtd/R8SPYIDdub7
# P2bSlDFp+m2zNKzBenjcklDyZMeqLQSrw2rq4C+np9xu1+j/2iGrQL+57g2extme
# me/G3h+pDHazJyCh1rr9gOcB0u/rgimVcI3/uxXP/tEPNqIuTzKQdEZrRzUTdwUz
# T2MuuC3hv2WnBGsY2HH6zAjybYmZELGt2z4s5KoYsMYHAXVn3m3pY2MeNn9pib6q
# RT5uWl+PoVvLnTCGMOgDs0DGDQ84zWeoU4j6uDBl+m/H5x2xg3RpPqzEaDux5mcz
# mrYI4IAFSEDu9oJkRqj1c7AGlfJsZZ+/VVscnFcax3hGfHCqlBuCF6yH6bbJDoEc
# QNYWFyn8XJwYK+pF9e+91WdPKF4F7pBMeufG9ND8+s0+MkYTIDaKBOq3qgdGnA2T
# OglmmVhcKaO5DKYwODzQRjY1fJy67sPV+Qp2+n4FG0DKkjXp1XrRtX8ArqmQqsV/
# AZwQsRb8zG4Y3G9i/qZQp7h7uJ0VP/4gDHXIIloTlRmQAOka1cKG8eOO7F/05QID
# AQABo4IBEjCCAQ4wHwYDVR0jBBgwFoAUoBEKIz6W8Qfs4q8p74Klf9AwpLQwHQYD
# VR0OBBYEFDLrkpr/NZZILyhAQnAgNpFcF4XmMA4GA1UdDwEB/wQEAwIBhjAPBgNV
# HRMBAf8EBTADAQH/MBMGA1UdJQQMMAoGCCsGAQUFBwMDMBsGA1UdIAQUMBIwBgYE
# VR0gADAIBgZngQwBBAEwQwYDVR0fBDwwOjA4oDagNIYyaHR0cDovL2NybC5jb21v
# ZG9jYS5jb20vQUFBQ2VydGlmaWNhdGVTZXJ2aWNlcy5jcmwwNAYIKwYBBQUHAQEE
# KDAmMCQGCCsGAQUFBzABhhhodHRwOi8vb2NzcC5jb21vZG9jYS5jb20wDQYJKoZI
# hvcNAQEMBQADggEBABK/oe+LdJqYRLhpRrWrJAoMpIpnuDqBv0WKfVIHqI0fTiGF
# OaNrXi0ghr8QuK55O1PNtPvYRL4G2VxjZ9RAFodEhnIq1jIV9RKDwvnhXRFAZ/ZC
# J3LFI+ICOBpMIOLbAffNRk8monxmwFE2tokCVMf8WPtsAO7+mKYulaEMUykfb9gZ
# pk+e96wJ6l2CxouvgKe9gUhShDHaMuwV5KZMPWw5c9QLhTkg4IUaaOGnSDip0TYl
# d8GNGRbFiExmfS9jzpjoad+sPKhdnckcW67Y8y90z7h+9teDnRGWYpquRRPaf9xH
# +9/DUp/mBlXpnYzyOmJRvOwkDynUWICE5EV7WtgwggYaMIIEAqADAgECAhBiHW0M
# UgGeO5B5FSCJIRwKMA0GCSqGSIb3DQEBDAUAMFYxCzAJBgNVBAYTAkdCMRgwFgYD
# VQQKEw9TZWN0aWdvIExpbWl0ZWQxLTArBgNVBAMTJFNlY3RpZ28gUHVibGljIENv
# ZGUgU2lnbmluZyBSb290IFI0NjAeFw0yMTAzMjIwMDAwMDBaFw0zNjAzMjEyMzU5
# NTlaMFQxCzAJBgNVBAYTAkdCMRgwFgYDVQQKEw9TZWN0aWdvIExpbWl0ZWQxKzAp
# BgNVBAMTIlNlY3RpZ28gUHVibGljIENvZGUgU2lnbmluZyBDQSBSMzYwggGiMA0G
# CSqGSIb3DQEBAQUAA4IBjwAwggGKAoIBgQCbK51T+jU/jmAGQ2rAz/V/9shTUxjI
# ztNsfvxYB5UXeWUzCxEeAEZGbEN4QMgCsJLZUKhWThj/yPqy0iSZhXkZ6Pg2A2NV
# DgFigOMYzB2OKhdqfWGVoYW3haT29PSTahYkwmMv0b/83nbeECbiMXhSOtbam+/3
# 6F09fy1tsB8je/RV0mIk8XL/tfCK6cPuYHE215wzrK0h1SWHTxPbPuYkRdkP05Zw
# mRmTnAO5/arnY83jeNzhP06ShdnRqtZlV59+8yv+KIhE5ILMqgOZYAENHNX9SJDm
# +qxp4VqpB3MV/h53yl41aHU5pledi9lCBbH9JeIkNFICiVHNkRmq4TpxtwfvjsUe
# dyz8rNyfQJy/aOs5b4s+ac7IH60B+Ja7TVM+EKv1WuTGwcLmoU3FpOFMbmPj8pz4
# 4MPZ1f9+YEQIQty/NQd/2yGgW+ufflcZ/ZE9o1M7a5Jnqf2i2/uMSWymR8r2oQBM
# dlyh2n5HirY4jKnFH/9gRvd+QOfdRrJZb1sCAwEAAaOCAWQwggFgMB8GA1UdIwQY
# MBaAFDLrkpr/NZZILyhAQnAgNpFcF4XmMB0GA1UdDgQWBBQPKssghyi47G9IritU
# pimqF6TNDDAOBgNVHQ8BAf8EBAMCAYYwEgYDVR0TAQH/BAgwBgEB/wIBADATBgNV
# HSUEDDAKBggrBgEFBQcDAzAbBgNVHSAEFDASMAYGBFUdIAAwCAYGZ4EMAQQBMEsG
# A1UdHwREMEIwQKA+oDyGOmh0dHA6Ly9jcmwuc2VjdGlnby5jb20vU2VjdGlnb1B1
# YmxpY0NvZGVTaWduaW5nUm9vdFI0Ni5jcmwwewYIKwYBBQUHAQEEbzBtMEYGCCsG
# AQUFBzAChjpodHRwOi8vY3J0LnNlY3RpZ28uY29tL1NlY3RpZ29QdWJsaWNDb2Rl
# U2lnbmluZ1Jvb3RSNDYucDdjMCMGCCsGAQUFBzABhhdodHRwOi8vb2NzcC5zZWN0
# aWdvLmNvbTANBgkqhkiG9w0BAQwFAAOCAgEABv+C4XdjNm57oRUgmxP/BP6YdURh
# w1aVcdGRP4Wh60BAscjW4HL9hcpkOTz5jUug2oeunbYAowbFC2AKK+cMcXIBD0Zd
# OaWTsyNyBBsMLHqafvIhrCymlaS98+QpoBCyKppP0OcxYEdU0hpsaqBBIZOtBajj
# cw5+w/KeFvPYfLF/ldYpmlG+vd0xqlqd099iChnyIMvY5HexjO2AmtsbpVn0OhNc
# WbWDRF/3sBp6fWXhz7DcML4iTAWS+MVXeNLj1lJziVKEoroGs9Mlizg0bUMbOalO
# hOfCipnx8CaLZeVme5yELg09Jlo8BMe80jO37PU8ejfkP9/uPak7VLwELKxAMcJs
# zkyeiaerlphwoKx1uHRzNyE6bxuSKcutisqmKL5OTunAvtONEoteSiabkPVSZ2z7
# 6mKnzAfZxCl/3dq3dUNw4rg3sTCggkHSRqTqlLMS7gjrhTqBmzu1L90Y1KWN/Y5J
# KdGvspbOrTfOXyXvmPL6E52z1NZJ6ctuMFBQZH3pwWvqURR8AgQdULUvrxjUYbHH
# j95Ejza63zdrEcxWLDX6xWls/GDnVNueKjWUH3fTv1Y8Wdho698YADR7TNx8X8z2
# Bev6SivBBOHY+uqiirZtg0y9ShQoPzmCcn63Syatatvx157YK9hlcPmVoa1oDE5/
# L9Uo2bC5a4CH2RwwggZnMIIEz6ADAgECAhA+fd8RheSZm8qwwUqFluQ9MA0GCSqG
# SIb3DQEBDAUAMFQxCzAJBgNVBAYTAkdCMRgwFgYDVQQKEw9TZWN0aWdvIExpbWl0
# ZWQxKzApBgNVBAMTIlNlY3RpZ28gUHVibGljIENvZGUgU2lnbmluZyBDQSBSMzYw
# HhcNMjQwNDEwMDAwMDAwWhcNMjcwNDEwMjM1OTU5WjBZMQswCQYDVQQGEwJDQTEQ
# MA4GA1UECAwHT250YXJpbzEbMBkGA1UECgwSRW1haWxnaXN0aWNzIENvcnAuMRsw
# GQYDVQQDDBJFbWFpbGdpc3RpY3MgQ29ycC4wggIiMA0GCSqGSIb3DQEBAQUAA4IC
# DwAwggIKAoICAQCoqZrS/OLxt780Ba4urxYAqnNVinLXVdUMP2iE/HrdBIgmYv0r
# 1HClkd4idJY7rjcSytuc2mnsnPqh+BU18SyOWpX8xXREs3B4Zr5MhN5uFNflQIJM
# M9wS2XV+cX3R63VXp0py1mOR1MQKamKQqVshpqI5qXLmSNmN6EbmoPActgsy9eK5
# RFlSxbOgfaTbqS6kblDKALDK44vvZSm6uW4mc3Q1Ymdd4RCuk3kgz1PVZ06cF+zl
# Ae196ogxtZ79FY/qvrqqcQwzhmZ21sLLseAS3dBuxWpkiM3gDVBZWMyAgDLCx0EG
# Yb/XvlXDOLeMQN7wrd6/OhY3n/r1ll/ToWgk/0joT0HPjtLwUyEJW/kx/178fDrR
# qZLuWuXh6bIofn8YuuHb4OvimqAzvaU+XkesRJwVYMZmpO+i54HmFs1K8w4sTgj7
# iIRFen9Y3CgNkoT95YlV+8wMSBuMGPyRx+x4+/8P9Ky9aNmUNg7p81Dstjmpm07U
# lUa5ErnZBq5J3Rw9N3YWH1BnYPjtXYkK3ZLSaLX+dvqa2FzVxw4iRISCGU42QvFC
# vpwFwianOFGcn0alEk+/fBAENTOQABrZ4Af9ZNjYcgwQIH9shAAHsJg9zfvbMot3
# IzrpmFa9uAecpIJNiNoOzik8D6nmMUocZIEDgrgXeuEQNndvMrtOZzIjdQIDAQAB
# o4IBrjCCAaowHwYDVR0jBBgwFoAUDyrLIIcouOxvSK4rVKYpqhekzQwwHQYDVR0O
# BBYEFNf8xvHO3OhRvrgXQz+4tHLBkXoXMA4GA1UdDwEB/wQEAwIHgDAMBgNVHRMB
# Af8EAjAAMBMGA1UdJQQMMAoGCCsGAQUFBwMDMEoGA1UdIARDMEEwNQYMKwYBBAGy
# MQECAQMCMCUwIwYIKwYBBQUHAgEWF2h0dHBzOi8vc2VjdGlnby5jb20vQ1BTMAgG
# BmeBDAEEATBJBgNVHR8EQjBAMD6gPKA6hjhodHRwOi8vY3JsLnNlY3RpZ28uY29t
# L1NlY3RpZ29QdWJsaWNDb2RlU2lnbmluZ0NBUjM2LmNybDB5BggrBgEFBQcBAQRt
# MGswRAYIKwYBBQUHMAKGOGh0dHA6Ly9jcnQuc2VjdGlnby5jb20vU2VjdGlnb1B1
# YmxpY0NvZGVTaWduaW5nQ0FSMzYuY3J0MCMGCCsGAQUFBzABhhdodHRwOi8vb2Nz
# cC5zZWN0aWdvLmNvbTAjBgNVHREEHDAagRhzdXBwb3J0QGVuYWlsZ2lzdGljcy5j
# b20wDQYJKoZIhvcNAQEMBQADggGBAC5dm8Fap2vJvKLzXjJpBkVeG9i5QEMag3Me
# CxlFJKhYOSePgg2RT3whKPns6W1/iJH8XmAva0K+ZrzigC40TqjVDZq6HYJjya43
# 6I5u0nCUzb3Ue0XWx/FOaJEh9yJQHuy0AxnLDDk79/UTzqMUkSdHhgznlOseNziB
# d53m3wsTq/1Ln5PDNwGcMFFU7qTXPsyhK3Nj+loLrBiRvZAI/idCst85V1/aa9Zp
# TnkBHHEISqkdbc+jiukAkkWR4o46YcQ/MSo6LLtxcNlDAA1H1RiRhGq26Ana606v
# AAzEHOnEUOE2qQ03cvFTT3al5IQKgG3pKzSMUK1mxIUo1mIkwtlKLq30Zak/H94M
# SX1FJcmTKOkHhuitCecVrQpWCWshU7EJZ9v+9PJu7gfmMghUXEB7NGIkQzoIufBH
# xDgSY75m1rnqpYth5IhWyGmP3Tr8RQQohCAIBKqMnAa9kk7xB9BmmfPMsC9WQwxf
# hrNlT7Buvx/Aa9y91XGtw7KH1goJSTGCG+0wghvpAgEBMGgwVDELMAkGA1UEBhMC
# R0IxGDAWBgNVBAoTD1NlY3RpZ28gTGltaXRlZDErMCkGA1UEAxMiU2VjdGlnbyBQ
# dWJsaWMgQ29kZSBTaWduaW5nIENBIFIzNgIQPn3fEYXkmZvKsMFKhZbkPTANBglg
# hkgBZQMEAgEFAKB8MBAGCisGAQQBgjcCAQwxAjAAMBkGCSqGSIb3DQEJAzEMBgor
# BgEEAYI3AgEEMBwGCisGAQQBgjcCAQsxDjAMBgorBgEEAYI3AgEVMC8GCSqGSIb3
# DQEJBDEiBCAY9r9dUd2OOuHgtXiH0gL9RkUmclv3xCpG+QDkSP7cwDANBgkqhkiG
# 9w0BAQEFAASCAgAhOl1YGUMDURhAlhYLEXff4fDEip1CYqVq1j0g1XI/sFQ94cxv
# +JU17lammaRYS6i3JhyW4AMxFjtjzQs93DQ0JLnJNwnIqQtRYnS41G93Ia3p6ewg
# YvdYQ6SbsGTWIrSRlvqycrwTFeMPGWKhXPiDwpG3NdWkKvju8TZxP3PGwgeQrDQV
# qAtkDd7bgblkQ7ZsgGWcgUs8KF2JH2IqgZ7kwnp7Y6WTTGMYJqsnQUV6AWfUcNnP
# ZrmeeO3UVlDAb+xDuJWIybOvLwh02ctx3OpFoFt93Yl0Gmxse5163vDiKfczhaL5
# u5ORD5JPoTTb2fBfE64U/bBqI6d/X8665QGvQ9cM5VGGb08Up5A1JCDvJWgEX38E
# P5BdOdHApJkQWIunlXuUa/Syy1njnu7z/yQhZ2JZ9waDfb6qY+JYiPWDkNHnBeIb
# HtNRNXrZ1WUBIzctDkTdJJrzSE3RqaZlMsxkvV7yJ42zTqHqrzQ2YDPCM2GF4L2g
# KP3bIuevjEXFoUCCqUiRfsJ+KQl18Dx3Wia9ppleSm0c9Ytmh04rh4PpWA2PFqer
# AKgLvoiJidbcs613BNxPRq0AG66Fbhnc0e5yIlZ0UzfMPOUgaVj7uDzYe6Rn6nnu
# eFgUaY0TnQSkLFdzoRDbUD1/Fe68RUJ6gsfj9JrA+GFQtIQyYB6VgVLd2qGCGNgw
# ghjUBgorBgEEAYI3AwMBMYIYxDCCGMAGCSqGSIb3DQEHAqCCGLEwghitAgEDMQ8w
# DQYJYIZIAWUDBAICBQAwgfgGCyqGSIb3DQEJEAEEoIHoBIHlMIHiAgEBBgorBgEE
# AbIxAgEBMDEwDQYJYIZIAWUDBAIBBQAEIPxaMJxgc1FwpZ7vljn2385gOyfWHPdB
# px9Z43KGHTUzAhUAr3EtyVD0fgfdooDRLtquvjgAw0YYDzIwMjYwMzExMTcwNjU1
# WqB2pHQwcjELMAkGA1UEBhMCR0IxFzAVBgNVBAgTDldlc3QgWW9ya3NoaXJlMRgw
# FgYDVQQKEw9TZWN0aWdvIExpbWl0ZWQxMDAuBgNVBAMTJ1NlY3RpZ28gUHVibGlj
# IFRpbWUgU3RhbXBpbmcgU2lnbmVyIFIzNqCCEwQwggZiMIIEyqADAgECAhEApCk7
# bh7d16c0CIetek63JDANBgkqhkiG9w0BAQwFADBVMQswCQYDVQQGEwJHQjEYMBYG
# A1UEChMPU2VjdGlnbyBMaW1pdGVkMSwwKgYDVQQDEyNTZWN0aWdvIFB1YmxpYyBU
# aW1lIFN0YW1waW5nIENBIFIzNjAeFw0yNTAzMjcwMDAwMDBaFw0zNjAzMjEyMzU5
# NTlaMHIxCzAJBgNVBAYTAkdCMRcwFQYDVQQIEw5XZXN0IFlvcmtzaGlyZTEYMBYG
# A1UEChMPU2VjdGlnbyBMaW1pdGVkMTAwLgYDVQQDEydTZWN0aWdvIFB1YmxpYyBU
# aW1lIFN0YW1waW5nIFNpZ25lciBSMzYwggIiMA0GCSqGSIb3DQEBAQUAA4ICDwAw
# ggIKAoICAQDThJX0bqRTePI9EEt4Egc83JSBU2dhrJ+wY7JgReuff5KQNhMuzVyt
# zD+iXazATVPMHZpH/kkiMo1/vlAGFrYN2P7g0Q8oPEcR3h0SftFNYxxMh+bj3ZNb
# bYjwt8f4DsSHPT+xp9zoFuw0HOMdO3sWeA1+F8mhg6uS6BJpPwXQjNSHpVTCgd1g
# OmKWf12HSfSbnjl3kDm0kP3aIUAhsodBYZsJA1imWqkAVqwcGfvs6pbfs/0GE4BJ
# 2aOnciKNiIV1wDRZAh7rS/O+uTQcb6JVzBVmPP63k5xcZNzGo4DOTV+sM1nVrDyc
# WEYS8bSS0lCSeclkTcPjQah9Xs7xbOBoCdmahSfg8Km8ffq8PhdoAXYKOI+wlaJj
# +PbEuwm6rHcm24jhqQfQyYbOUFTKWFe901VdyMC4gRwRAq04FH2VTjBdCkhKts5P
# y7H73obMGrxN1uGgVyZho4FkqXA8/uk6nkzPH9QyHIED3c9CGIJ098hU4Ig2xRjh
# TbengoncXUeo/cfpKXDeUcAKcuKUYRNdGDlf8WnwbyqUblj4zj1kQZSnZud5Etmj
# IdPLKce8UhKl5+EEJXQp1Fkc9y5Ivk4AZacGMCVG0e+wwGsjcAADRO7Wga89r/jJ
# 56IDK773LdIsL3yANVvJKdeeS6OOEiH6hpq2yT+jJ/lHa9zEdqFqMwIDAQABo4IB
# jjCCAYowHwYDVR0jBBgwFoAUX1jtTDF6omFCjVKAurNhlxmiMpswHQYDVR0OBBYE
# FIhhjKEqN2SBKGChmzHQjP0sAs5PMA4GA1UdDwEB/wQEAwIGwDAMBgNVHRMBAf8E
# AjAAMBYGA1UdJQEB/wQMMAoGCCsGAQUFBwMIMEoGA1UdIARDMEEwNQYMKwYBBAGy
# MQECAQMIMCUwIwYIKwYBBQUHAgEWF2h0dHBzOi8vc2VjdGlnby5jb20vQ1BTMAgG
# BmeBDAEEAjBKBgNVHR8EQzBBMD+gPaA7hjlodHRwOi8vY3JsLnNlY3RpZ28uY29t
# L1NlY3RpZ29QdWJsaWNUaW1lU3RhbXBpbmdDQVIzNi5jcmwwegYIKwYBBQUHAQEE
# bjBsMEUGCCsGAQUFBzAChjlodHRwOi8vY3J0LnNlY3RpZ28uY29tL1NlY3RpZ29Q
# dWJsaWNUaW1lU3RhbXBpbmdDQVIzNi5jcnQwIwYIKwYBBQUHMAGGF2h0dHA6Ly9v
# Y3NwLnNlY3RpZ28uY29tMA0GCSqGSIb3DQEBDAUAA4IBgQACgT6khnJRIfllqS49
# Uorh5ZvMSxNEk4SNsi7qvu+bNdcuknHgXIaZyqcVmhrV3PHcmtQKt0blv/8t8DE4
# bL0+H0m2tgKElpUeu6wOH02BjCIYM6HLInbNHLf6R2qHC1SUsJ02MWNqRNIT6GQL
# 0Xm3LW7E6hDZmR8jlYzhZcDdkdw0cHhXjbOLsmTeS0SeRJ1WJXEzqt25dbSOaaK7
# vVmkEVkOHsp16ez49Bc+Ayq/Oh2BAkSTFog43ldEKgHEDBbCIyba2E8O5lPNan+B
# QXOLuLMKYS3ikTcp/Qw63dxyDCfgqXYUhxBpXnmeSO/WA4NwdwP35lWNhmjIpNVZ
# vhWoxDL+PxDdpph3+M5DroWGTc1ZuDa1iXmOFAK4iwTnlWDg3QNRsRa9cnG3FBBp
# VHnHOEQj4GMkrOHdNDTbonEeGvZ+4nSZXrwCW4Wv2qyGDBLlKk3kUW1pIScDCpm/
# chL6aUbnSsrtbepdtbCLiGanKVR/KC1gsR0tC6Q0RfWOI4owggYUMIID/KADAgEC
# AhB6I67aU2mWD5HIPlz0x+M/MA0GCSqGSIb3DQEBDAUAMFcxCzAJBgNVBAYTAkdC
# MRgwFgYDVQQKEw9TZWN0aWdvIExpbWl0ZWQxLjAsBgNVBAMTJVNlY3RpZ28gUHVi
# bGljIFRpbWUgU3RhbXBpbmcgUm9vdCBSNDYwHhcNMjEwMzIyMDAwMDAwWhcNMzYw
# MzIxMjM1OTU5WjBVMQswCQYDVQQGEwJHQjEYMBYGA1UEChMPU2VjdGlnbyBMaW1p
# dGVkMSwwKgYDVQQDEyNTZWN0aWdvIFB1YmxpYyBUaW1lIFN0YW1waW5nIENBIFIz
# NjCCAaIwDQYJKoZIhvcNAQEBBQADggGPADCCAYoCggGBAM2Y2ENBq26CK+z2M34m
# NOSJjNPvIhKAVD7vJq+MDoGD46IiM+b83+3ecLvBhStSVjeYXIjfa3ajoW3cS3El
# cJzkyZlBnwDEJuHlzpbN4kMH2qRBVrjrGJgSlzzUqcGQBaCxpectRGhhnOSwcjPM
# I3G0hedv2eNmGiUbD12OeORN0ADzdpsQ4dDi6M4YhoGE9cbY11XxM2AVZn0GiOUC
# 9+XE0wI7CQKfOUfigLDn7i/WeyxZ43XLj5GVo7LDBExSLnh+va8WxTlA+uBvq1KO
# 8RSHUQLgzb1gbL9Ihgzxmkdp2ZWNuLc+XyEmJNbD2OIIq/fWlwBp6KNL19zpHsOD
# LIsgZ+WZ1AzCs1HEK6VWrxmnKyJJg2Lv23DlEdZlQSGdF+z+Gyn9/CRezKe7WNyx
# Rf4e4bwUtrYE2F5Q+05yDD68clwnweckKtxRaF0VzN/w76kOLIaFVhf5sMM/caEZ
# LtOYqYadtn034ykSFaZuIBU9uCSrKRKTPJhWvXk4CllgrwIDAQABo4IBXDCCAVgw
# HwYDVR0jBBgwFoAU9ndq3T/9ARP/FqFsggIv0Ao9FCUwHQYDVR0OBBYEFF9Y7Uwx
# eqJhQo1SgLqzYZcZojKbMA4GA1UdDwEB/wQEAwIBhjASBgNVHRMBAf8ECDAGAQH/
# AgEAMBMGA1UdJQQMMAoGCCsGAQUFBwMIMBEGA1UdIAQKMAgwBgYEVR0gADBMBgNV
# HR8ERTBDMEGgP6A9hjtodHRwOi8vY3JsLnNlY3RpZ28uY29tL1NlY3RpZ29QdWJs
# aWNUaW1lU3RhbXBpbmdSb290UjQ2LmNybDB8BggrBgEFBQcBAQRwMG4wRwYIKwYB
# BQUHMAKGO2h0dHA6Ly9jcnQuc2VjdGlnby5jb20vU2VjdGlnb1B1YmxpY1RpbWVT
# dGFtcGluZ1Jvb3RSNDYucDdjMCMGCCsGAQUFBzABhhdodHRwOi8vb2NzcC5zZWN0
# aWdvLmNvbTANBgkqhkiG9w0BAQwFAAOCAgEAEtd7IK0ONVgMnoEdJVj9TC1ndK/H
# YiYh9lVUacahRoZ2W2hfiEOyQExnHk1jkvpIJzAMxmEc6ZvIyHI5UkPCbXKspioY
# MdbOnBWQUn733qMooBfIghpR/klUqNxx6/fDXqY0hSU1OSkkSivt51UlmJElUICZ
# YBodzD3M/SFjeCP59anwxs6hwj1mfvzG+b1coYGnqsSz2wSKr+nDO+Db8qNcTbJZ
# RAiSazr7KyUJGo1c+MScGfG5QHV+bps8BX5Oyv9Ct36Y4Il6ajTqV2ifikkVtB3R
# NBUgwu/mSiSUice/Jp/q8BMk/gN8+0rNIE+QqU63JoVMCMPY2752LmESsRVVoypJ
# Vt8/N3qQ1c6FibbcRabo3azZkcIdWGVSAdoLgAIxEKBeNh9AQO1gQrnh1TA8ldXu
# JzPSuALOz1Ujb0PCyNVkWk7hkhVHfcvBfI8NtgWQupiaAeNHe0pWSGH2opXZYKYG
# 4Lbukg7HpNi/KqJhue2Keak6qH9A8CeEOB7Eob0Zf+fU+CCQaL0cJqlmnx9HCDxF
# +3BLbUufrV64EbTI40zqegPZdA+sXCmbcZy6okx/SjwsusWRItFA3DE8MORZeFb6
# BmzBtqKJ7l939bbKBy2jvxcJI98Va95Q5JnlKor3m0E7xpMeYRriWklUPsetMSf2
# NvUQa/E5vVyefQIwggaCMIIEaqADAgECAhA2wrC9fBs656Oz3TbLyXVoMA0GCSqG
# SIb3DQEBDAUAMIGIMQswCQYDVQQGEwJVUzETMBEGA1UECBMKTmV3IEplcnNleTEU
# MBIGA1UEBxMLSmVyc2V5IENpdHkxHjAcBgNVBAoTFVRoZSBVU0VSVFJVU1QgTmV0
# d29yazEuMCwGA1UEAxMlVVNFUlRydXN0IFJTQSBDZXJ0aWZpY2F0aW9uIEF1dGhv
# cml0eTAeFw0yMTAzMjIwMDAwMDBaFw0zODAxMTgyMzU5NTlaMFcxCzAJBgNVBAYT
# AkdCMRgwFgYDVQQKEw9TZWN0aWdvIExpbWl0ZWQxLjAsBgNVBAMTJVNlY3RpZ28g
# UHVibGljIFRpbWUgU3RhbXBpbmcgUm9vdCBSNDYwggIiMA0GCSqGSIb3DQEBAQUA
# A4ICDwAwggIKAoICAQCIndi5RWedHd3ouSaBmlRUwHxJBZvMWhUP2ZQQRLRBQIF3
# FJmp1OR2LMgIU14g0JIlL6VXWKmdbmKGRDILRxEtZdQnOh2qmcxGzjqemIk8et8s
# E6J+N+Gl1cnZocew8eCAawKLu4TRrCoqCAT8uRjDeypoGJrruH/drCio28aqIVEn
# 45NZiZQI7YYBex48eL78lQ0BrHeSmqy1uXe9xN04aG0pKG9ki+PC6VEfzutu6Q3I
# cZZfm00r9YAEp/4aeiLhyaKxLuhKKaAdQjRaf/h6U13jQEV1JnUTCm511n5avv4N
# +jSVwd+Wb8UMOs4netapq5Q/yGyiQOgjsP/JRUj0MAT9YrcmXcLgsrAimfWY3MzK
# m1HCxcquinTqbs1Q0d2VMMQyi9cAgMYC9jKc+3mW62/yVl4jnDcw6ULJsBkOkrcP
# LUwqj7poS0T2+2JMzPP+jZ1h90/QpZnBkhdtixMiWDVgh60KmLmzXiqJc6lGwqoU
# qpq/1HVHm+Pc2B6+wCy/GwCcjw5rmzajLbmqGygEgaj/OLoanEWP6Y52Hflef3XL
# vYnhEY4kSirMQhtberRvaI+5YsD3XVxHGBjlIli5u+NrLedIxsE88WzKXqZjj9Zi
# 5ybJL2WjeXuOTbswB7XjkZbErg7ebeAQUQiS/uRGZ58NHs57ZPUfECcgJC+v2wID
# AQABo4IBFjCCARIwHwYDVR0jBBgwFoAUU3m/WqorSs9UgOHYm8Cd8rIDZsswHQYD
# VR0OBBYEFPZ3at0//QET/xahbIICL9AKPRQlMA4GA1UdDwEB/wQEAwIBhjAPBgNV
# HRMBAf8EBTADAQH/MBMGA1UdJQQMMAoGCCsGAQUFBwMIMBEGA1UdIAQKMAgwBgYE
# VR0gADBQBgNVHR8ESTBHMEWgQ6BBhj9odHRwOi8vY3JsLnVzZXJ0cnVzdC5jb20v
# VVNFUlRydXN0UlNBQ2VydGlmaWNhdGlvbkF1dGhvcml0eS5jcmwwNQYIKwYBBQUH
# AQEEKTAnMCUGCCsGAQUFBzABhhlodHRwOi8vb2NzcC51c2VydHJ1c3QuY29tMA0G
# CSqGSIb3DQEBDAUAA4ICAQAOvmVB7WhEuOWhxdQRh+S3OyWM637ayBeR7djxQ8Si
# hTnLf2sABFoB0DFR6JfWS0snf6WDG2gtCGflwVvcYXZJJlFfym1Doi+4PfDP8s0c
# qlDmdfyGOwMtGGzJ4iImyaz3IBae91g50QyrVbrUoT0mUGQHbRcF57olpfHhQESt
# z5i6hJvVLFV/ueQ21SM99zG4W2tB1ExGL98idX8ChsTwbD/zIExAopoe3l6JrzJt
# Pxj8V9rocAnLP2C8Q5wXVVZcbw4x4ztXLsGzqZIiRh5i111TW7HV1AtsQa6vXy63
# 3vCAbAOIaKcLAo/IU7sClyZUk62XD0VUnHD+YvVNvIGezjM6CRpcWed/ODiptK+e
# vDKPU2K6synimYBaNH49v9Ih24+eYXNtI38byt5kIvh+8aW88WThRpv8lUJKaPn3
# 7+YHYafob9Rg7LyTrSYpyZoBmwRWSE4W6iPjB7wJjJpH29308ZkpKKdpkiS9WNsf
# /eeUtvRrtIEiSJHN899L1P4l6zKVsdrUu1FX1T/ubSrsxrYJD+3f3aKg6yxdbugo
# t06YwGXXiy5UUGZvOu3lXlxA+fC13dQ5OlL2gIb5lmF6Ii8+CQOYDwXM+yd9dbmo
# cQsHjcRPsccUd5E9FiswEqORvz8g3s+jR3SFCgXhN4wz7NgAnOgpCdUo4uDyllU9
# PzGCBJIwggSOAgEBMGowVTELMAkGA1UEBhMCR0IxGDAWBgNVBAoTD1NlY3RpZ28g
# TGltaXRlZDEsMCoGA1UEAxMjU2VjdGlnbyBQdWJsaWMgVGltZSBTdGFtcGluZyBD
# QSBSMzYCEQCkKTtuHt3XpzQIh616TrckMA0GCWCGSAFlAwQCAgUAoIIB+TAaBgkq
# hkiG9w0BCQMxDQYLKoZIhvcNAQkQAQQwHAYJKoZIhvcNAQkFMQ8XDTI2MDMxMTE3
# MDY1NVowPwYJKoZIhvcNAQkEMTIEMGc2gqIN74w9f9vc6iMbKXhcaYResn6gluUx
# UCEvQwqEhjZjNVoH47qDHgT+8pOsPzCCAXoGCyqGSIb3DQEJEAIMMYIBaTCCAWUw
# ggFhMBYEFDjJFIEQRLTcZj6T1HRLgUGGqbWxMIGHBBTGrlTkeIbxfD1VEkiMacNK
# evnC3TBvMFukWTBXMQswCQYDVQQGEwJHQjEYMBYGA1UEChMPU2VjdGlnbyBMaW1p
# dGVkMS4wLAYDVQQDEyVTZWN0aWdvIFB1YmxpYyBUaW1lIFN0YW1waW5nIFJvb3Qg
# UjQ2AhB6I67aU2mWD5HIPlz0x+M/MIG8BBSFPWMtk4KCYXzQkDXEkd6SwULaxzCB
# ozCBjqSBizCBiDELMAkGA1UEBhMCVVMxEzARBgNVBAgTCk5ldyBKZXJzZXkxFDAS
# BgNVBAcTC0plcnNleSBDaXR5MR4wHAYDVQQKExVUaGUgVVNFUlRSVVNUIE5ldHdv
# cmsxLjAsBgNVBAMTJVVTRVJUcnVzdCBSU0EgQ2VydGlmaWNhdGlvbiBBdXRob3Jp
# dHkCEDbCsL18Gzrno7PdNsvJdWgwDQYJKoZIhvcNAQEBBQAEggIAAwcVw6BKA/8N
# 9myL6PjecmNyIMLg4MjJxzA9xbkwB82VzZIsA7x3YcdUyM/kUSGj17r0dWaFjCQr
# ThzULvV4XnQEskuNSDXua9hX6uABl35XnPfylTikqW4W4SXNQu72QfjanKjsiEsx
# ivK13TT380uAQn928kP+1Z0ehUxMOxS404Qlpe7Z0vT9ABA0WPub2StUDVuiym4x
# ScIxXNbcxRoT9M2CoJ8uP0UQAvYV7F1Bg68P4U5A3ExrmxnDIgD7O2ho/jTByXGT
# 0qWBQoM2PTsYtHZ8HR6DNw4Enhm/YHWSAHuieQveZMcbQHGAwwGUWbJENOJ8bGv8
# ZfNjNNHKrFxl4/WkkJiKMXqA2F7U3y5Zdp2oGgXrvp3CelwZJ5cESrq+qE0nKuLu
# 5Eh4Fn4aFxxUm9LkXYODVv5mQt+Kjj03jJQeE/hJcEr/iITxOR9gX10gQ1UpW89/
# sWGvHfHCxTdGKpxtYL9dmvuQUOneUpuhiioNQ9mZQ0x/OuQfs9QM+x4vOSK16dB7
# fa+/r3XZwBi0orUDRd0mlB6rsMi2NT+t4ZkQpot/Gasa0CnaT510UaoPsapnJ5fE
# co+a6xqm19pBXOBzmUj6FsVcX2c6RBhmmGEEr2dgfaSASeTXQhNBpEy7spXFg4iU
# l74+1FvzFrrNNM+eyVCHZ8LE6SiYuXE=
# SIG # End signature block
