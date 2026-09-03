# AskHR/Benefits bot — legacy transport rule cutover

**Do this manually, once, after the AskHR bot has been enabled and verified end-to-end.**
No code path in this repo performs this step — it is a deliberate one-time,
human-triggered action because disabling mail routing is high blast-radius
and hard to reverse quickly if something is wrong.

## Prerequisites

- The AskHR bot (`/askhr-bot` on `hrapp.movedocs.com`) has been enabled for
  at least a few days.
- You have spot-checked that tickets created by the bot in HRD look correct:
  reporter is AskHR/Benefits (not the original sender), the original email
  is attached as `.eml`, and the description includes the original
  sender/date/body.
- You have compared bot-created ticket volume against historical Bcc-forwarded
  ticket volume for the same mailboxes over a comparable period, and they're
  consistent.

## Steps

Connect to Exchange Online PowerShell with an account that can manage
transport rules, then run:

```powershell
Disable-TransportRule -Identity "Forward External Mail to Jira - AskHR" -Confirm:$false
Disable-TransportRule -Identity "Forward Payroll Mail to Jira - AskHR" -Confirm:$false
Disable-TransportRule -Identity "Forward External Mail to Jira - Benefits" -Confirm:$false
Disable-TransportRule -Identity "Forward Payroll Mail to Jira - Benefits" -Confirm:$false
```

Verify each rule shows `State: Disabled` (not deleted — keep them in place
in case you need to re-enable quickly):

```powershell
Get-TransportRule -Identity "Forward External Mail to Jira - AskHR" | Select-Object Name, State
Get-TransportRule -Identity "Forward Payroll Mail to Jira - AskHR" | Select-Object Name, State
Get-TransportRule -Identity "Forward External Mail to Jira - Benefits" | Select-Object Name, State
Get-TransportRule -Identity "Forward Payroll Mail to Jira - Benefits" | Select-Object Name, State
```

## Rollback

Re-enable any rule with `Enable-TransportRule -Identity "<name>"` if the bot
needs to be disabled and mail-flow forwarding restored while you investigate.
