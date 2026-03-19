# User Exit Workflow Agent

This folder contains the Windows-side companion agent for the primary `it-app` user exit workflow.

What it does:

- Polls `it-app.movedocs.com` for queued `windows_agent` workflow steps
- Executes native Active Directory and Exchange PowerShell actions
- Heartbeats step leases while work is running
- Posts structured success/failure results back to the app

Current automated step support:

- `exit_on_prem_deprovision`
  - Disable the AD account
  - Remove non-default group memberships
  - Clear manager and telephone fields
  - Set office to `DISABLED`
  - Update Exchange-related hide-from-GAL attributes
  - Move the object to the configured disabled OU
- `mailbox_convert_type`
  - Convert the mailbox to `Shared`
  - Hide the mailbox from address lists

Setup:

1. Copy `exit-agent.config.sample.json` to `exit-agent.config.json`
2. Fill in:
   - `baseUrl`
   - `sharedSecret`
   - `agentId`
   - per-profile AD/Exchange settings for `canyon`, `khm`, and `oasis`
3. Run the script from an elevated PowerShell session on a domain-joined Windows host:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\ExitWorkflowAgent.ps1 -ConfigPath .\exit-agent.config.json
```

Notes:

- The Linux web app never remotes directly into Windows. This agent uses pull-mode polling only.
- The shared secret must match `USER_EXIT_AGENT_SHARED_SECRET` on the backend.
- The host should have the `ActiveDirectory` module installed and either:
  - local Exchange management cmdlets available, or
  - remote PowerShell access to an Exchange endpoint via `exchangeConnectionUri`
