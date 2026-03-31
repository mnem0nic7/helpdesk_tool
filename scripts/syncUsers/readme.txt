Important Note - 25 April 2023

A change has been made to how the user sync process works. Previously, Emailgistics ignored security groups added as shared mailbox members, so each user had to be added individually in order to be recognized by Emailgistics. Now, the sync process correctly recognizes mail-enabled security groups in the member list, allowing you to maintain mailbox membership using those groups if you prefer.

In order to avoid unexpected users being added to Emailgistics, you should check the member lists of each of your Emailgistics mailboxes to see if there are any security groups there. If so, make sure you want all the users in the group(s) added as Emailgistics users. If you don't, you can edit or remove the security group. If for some reason you need to have a security group as part of the mailbox but don't want its members added to Emailgistics, contact Support.

---

This folder contains a PowerShell script called "syncUsers.ps1" and a customer-specific settings file called "customerData.json".

The script supports PowerShell 5.1 and PowerShell 7. It will not run on legacy versions or unsupported versions. On PowerShell 7, you will be offered a choice between standard browser login and device code authentication.

The script supports two execution modes:
    - Interactive: Prompts you for your Microsoft 365 administrator credentials and authenticates via browser or device code
    - Noninteractive: Uses an App Registration for automated execution and supports either a certificate thumbprint or client secret. Runtime settings can come from customerData.json or environment variables.

In order to run the script, you must have the ability to run scripts on your computer. The script will run with any execution policy other than "Restricted". If the access policy is set to restricted, you can change it by running the following PowerShell command:
"Set-ExecutionPolicy -Scope CurrentUser RemoteSigned"

Make sure to sign in with your Microsoft 365 administrator credentials. You must be a Global Administrator or an Exchange Administrator. Without sufficient permissions, the script will not continue.

The script was written with transparency in mind, and we encourage you to go through it to see exactly what we are doing. Everything is clearly and thoroughly documented.

If for any reason you force quit the script during execution, and it doesn't work when you retry it, redownload the script and try it again.


What does this script do?

The script requires the following modules (it will install them automatically if they are not present):
    - NuGet package provider
    - Microsoft.Graph.Authentication - must be loaded before ExchangeOnlineManagement to prevent MSAL assembly version conflicts
    - Microsoft.Graph.Users - for user directory lookups and admin role validation
    - ExchangeOnlineManagement - for Exchange Online mailbox operations (PowerShell 7 requires v3.7.2 or higher)

Here's a list of everything that the script does:
    - Remove any previous sessions unclosed from previous executions of the script
    - Install NuGet, Microsoft.Graph submodules, and ExchangeOnlineManagement if they are not already present (Graph is loaded first to prevent MSAL assembly conflicts)
    - Prompt to upgrade if Microsoft.Graph submodule v2.6.0 (unsupported) or ExchangeOnlineManagement v2.x is detected
    - Verify the authentication token with the Emailgistics server for each mailbox
    - Prompt you for your Microsoft 365 administrator username (interactive mode) or use certificate-based authentication (noninteractive mode)
    - Allow environment-backed noninteractive execution for targeted shared-mailbox sync runs or sync-all reruns backed by configured mailbox lists
    - Connect to Microsoft Graph with the required permissions (User.Read, Directory.Read.All)
    - Validate the Graph session and detect cached credential mismatches (interactive mode)
    - Connect to Exchange Online
    - Validate the logged-in user has Global Administrator or Exchange Administrator roles via Microsoft Graph (interactive mode)
    - For each mailbox configured for sync: get the delegated users with SendAs permissions, resolve mail-enabled security group members, and filter to active users only
    - Gather user data (shared mailbox info, exchange admin info, and users list) for each mailbox
    - Send the user data to the Emailgistics server and report added/removed users and any rule changes

What the script checks for:
    - PowerShell is version 5.1 or 7
    - Required modules are installed and at supported versions (prompts to upgrade if outdated)
    - Make sure a new session can be opened (maximum of 3 concurrent Exchange sessions)
    - Authentication token is valid for each mailbox
    - Logged in user has Global Administrator or Exchange Administrator roles (via Microsoft Graph role check, interactive mode only)
    - Graph credential mismatch detection (handles cached credential issues, interactive mode only)
