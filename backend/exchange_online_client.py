"""Exchange Online PowerShell helpers for mailbox delegation lookup."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from azure_client import AzureApiError, AzureClient
from config import (
    EXCHANGE_DELEGATE_SCAN_TIMEOUT_SECONDS,
    EXCHANGE_ONLINE_ORGANIZATION,
    EXCHANGE_POWERSHELL_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class ExchangeOnlinePowerShellError(RuntimeError):
    """Raised when Exchange Online PowerShell execution fails."""


class ExchangeOnlinePowerShellCancelled(ExchangeOnlinePowerShellError):
    """Raised when Exchange Online PowerShell work is cancelled by the user."""


def _organization_domains(payload: dict[str, Any]) -> list[str]:
    rows = payload.get("value") if isinstance(payload.get("value"), list) else [payload]
    domains: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        verified_domains = row.get("verifiedDomains") if isinstance(row.get("verifiedDomains"), list) else []
        preferred = sorted(
            [
                item
                for item in verified_domains
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ],
            key=lambda item: (
                not bool(item.get("isInitial")),
                not str(item.get("name") or "").strip().lower().endswith(".onmicrosoft.com"),
                str(item.get("name") or "").strip().lower(),
            ),
        )
        for item in preferred:
            name = str(item.get("name") or "").strip()
            if name and name not in domains:
                domains.append(name)
    return domains


@dataclass
class ExchangeOnlinePowerShellClient:
    """Run targeted Exchange Online PowerShell delegate queries with an app token."""

    azure_client: AzureClient
    organization_override: str = EXCHANGE_ONLINE_ORGANIZATION
    timeout_seconds: int = EXCHANGE_POWERSHELL_TIMEOUT_SECONDS
    _organization_cache: str | None = None

    @property
    def pwsh_path(self) -> str:
        return shutil.which("pwsh") or ""

    @property
    def configured(self) -> bool:
        return bool(self.azure_client.configured and self.pwsh_path)

    def organization(self) -> str:
        if self.organization_override:
            return self.organization_override
        if self._organization_cache:
            return self._organization_cache
        try:
            payload = self.azure_client.graph_request(
                "GET",
                "organization",
                params={"$select": "verifiedDomains"},
            )
        except AzureApiError as exc:
            raise ExchangeOnlinePowerShellError(
                "Exchange Online PowerShell could not determine the organization domain from Microsoft Graph."
            ) from exc
        domains = _organization_domains(payload)
        if not domains:
            raise ExchangeOnlinePowerShellError(
                "Exchange Online PowerShell could not determine an Exchange organization domain. "
                "Set EXCHANGE_ONLINE_ORGANIZATION to the tenant's primary .onmicrosoft.com domain."
            )
        self._organization_cache = domains[0]
        return self._organization_cache

    def _run_script(
        self,
        script_body: str,
        *,
        extra_env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> Any:
        if not self.azure_client.configured:
            raise ExchangeOnlinePowerShellError("Exchange Online PowerShell requires configured Entra app credentials.")
        if not self.pwsh_path:
            raise ExchangeOnlinePowerShellError("Exchange Online PowerShell is unavailable because pwsh is not installed.")

        access_token = self.azure_client.exchange_access_token()
        organization = self.organization()
        script = f"""
$ErrorActionPreference = 'Stop'
Import-Module ExchangeOnlineManagement
Connect-ExchangeOnline `
  -AccessToken $env:EXO_ACCESS_TOKEN `
  -Organization $env:EXO_ORGANIZATION `
  -ShowBanner:$false `
  -ShowProgress:$false `
  -SkipLoadingFormatData `
  -CommandName @(
    'Get-Mailbox',
    'Get-EXOMailboxPermission',
    'Get-EXORecipientPermission',
    'Disconnect-ExchangeOnline'
  ) | Out-Null
try {{
{script_body}
}}
finally {{
  Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
}}
""".strip()
        env = os.environ.copy()
        env["EXO_ACCESS_TOKEN"] = access_token
        env["EXO_ORGANIZATION"] = organization
        for key, value in (extra_env or {}).items():
            env[key] = value

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".ps1", delete=False) as handle:
            handle.write(script)
            script_path = Path(handle.name)
        timeout_seconds = max(30, int(timeout_seconds or self.timeout_seconds or 240))
        try:
            process = subprocess.Popen(
                [self.pwsh_path, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                if cancel_requested and cancel_requested():
                    process.kill()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    raise ExchangeOnlinePowerShellCancelled("Exchange Online PowerShell cancelled by user.")
                if time.monotonic() >= deadline:
                    process.kill()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    raise ExchangeOnlinePowerShellError(
                        f"Exchange Online PowerShell timed out after {timeout_seconds} seconds."
                    )
                time.sleep(0.25)
            stdout, stderr = process.communicate()
        finally:
            script_path.unlink(missing_ok=True)

        stdout = (stdout or "").strip()
        stderr = (stderr or "").strip()
        if process.returncode != 0:
            message = stderr or stdout or "Unknown Exchange Online PowerShell failure."
            raise ExchangeOnlinePowerShellError(message[:4000])
        if not stdout:
            return {}
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            logger.warning("Unexpected Exchange Online PowerShell output: %s", stdout[:1000])
            raise ExchangeOnlinePowerShellError("Exchange Online PowerShell returned non-JSON output.") from exc

    def get_mailbox_delegate_permissions(
        self,
        mailbox_identifier: str,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        mailbox = str(mailbox_identifier or "").strip()
        if not mailbox:
            raise ExchangeOnlinePowerShellError("mailbox is required")
        payload = self._run_script(
            """
$mailboxIdentity = $env:MAILBOX_IDENTITY
$sendAs = @(
  Get-EXORecipientPermission -Identity $mailboxIdentity -ResultSize Unlimited |
    Where-Object { $_.AccessRights -contains 'SendAs' -and $_.Deny -ne $true } |
    ForEach-Object {
      [pscustomobject]@{
        Identity = $_.Identity
        Trustee = $_.Trustee
        AccessRights = @($_.AccessRights)
      }
    }
)
$fullAccess = @(
  Get-EXOMailboxPermission -Identity $mailboxIdentity |
    Where-Object {
      $_.AccessRights -contains 'FullAccess' -and
      $_.Deny -ne $true -and
      $_.IsInherited -ne $true -and
      $_.User.ToString() -ne 'NT AUTHORITY\\SELF'
    } |
    ForEach-Object {
      [pscustomobject]@{
        Identity = $_.Identity
        User = $_.User.ToString()
        AccessRights = @($_.AccessRights)
        IsInherited = [bool]$_.IsInherited
        Deny = [bool]$_.Deny
      }
    }
)
[pscustomobject]@{
  send_as = $sendAs
  full_access = $fullAccess
} | ConvertTo-Json -Depth 8 -Compress
            """.strip(),
            extra_env={"MAILBOX_IDENTITY": mailbox},
            cancel_requested=cancel_requested,
        )
        return payload if isinstance(payload, dict) else {}

    def get_send_as_mailboxes_for_user(
        self,
        user_identifier: str,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        user = str(user_identifier or "").strip()
        if not user:
            raise ExchangeOnlinePowerShellError("user is required")
        payload = self._run_script(
            """
$delegateUser = $env:DELEGATE_USER
$mailboxes = @(
  Get-EXORecipientPermission -Trustee $delegateUser -ResultSize Unlimited |
    Where-Object { $_.AccessRights -contains 'SendAs' -and $_.Deny -ne $true } |
    ForEach-Object {
      $identity = $_.Identity
      [pscustomobject]@{
        Identity = $identity
        DisplayName = $identity
        UserPrincipalName = $identity
        PrimarySmtpAddress = $identity
        PermissionTypes = @('send_as')
      }
    }
)
[pscustomobject]@{
  mailboxes = $mailboxes
} | ConvertTo-Json -Depth 8 -Compress
""".strip(),
            extra_env={"DELEGATE_USER": user},
            cancel_requested=cancel_requested,
        )
        return payload if isinstance(payload, dict) else {}

    def get_full_access_mailboxes_for_user(
        self,
        user_identifier: str,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        user = str(user_identifier or "").strip()
        if not user:
            raise ExchangeOnlinePowerShellError("user is required")
        payload = self._run_script(
            """
$delegateUser = $env:DELEGATE_USER
$allMailboxes = @(Get-Mailbox -ResultSize Unlimited)
$mailboxIdentities = @(
  foreach ($mailbox in $allMailboxes) {
    if ($mailbox.UserPrincipalName) {
      $mailbox.UserPrincipalName
    }
    elseif ($mailbox.PrimarySmtpAddress) {
      $mailbox.PrimarySmtpAddress.ToString()
    }
  }
)
$fullAccess = @()
$fullAccessErrors = @()
$batchSize = 50
for ($offset = 0; $offset -lt $mailboxIdentities.Count; $offset += $batchSize) {
  $batch = @($mailboxIdentities | Select-Object -Skip $offset -First $batchSize)
  if ($batch.Count -eq 0) {
    continue
  }

  $attempt = 0
  while ($true) {
    $attempt++
    $batchErrors = @()
    $batchMatches = @(
      $batch |
        Get-EXOMailboxPermission -User $delegateUser -ErrorAction SilentlyContinue -ErrorVariable +batchErrors |
        Where-Object {
          $_.AccessRights -contains 'FullAccess' -and
          $_.Deny -ne $true -and
          $_.IsInherited -ne $true -and
          $_.User.ToString() -ne 'NT AUTHORITY\\SELF'
        } |
        Select-Object -ExpandProperty Identity -Unique
    )
    $retryableErrors = @(
      $batchErrors |
        Where-Object {
          $_.Exception.Message -match 'Resource temporarily unavailable'
        }
    )
    if ($retryableErrors.Count -gt 0 -and $attempt -lt 3) {
      Start-Sleep -Seconds 2
      continue
    }

    $fullAccess += $batchMatches
    $fullAccessErrors += $batchErrors
    break
  }
}
$fullAccess = @($fullAccess | Sort-Object -Unique)
$unexpectedFullAccessErrors = @(
  $fullAccessErrors |
    Where-Object {
      $_.Exception.Message -notmatch 'No permissions were found for the user:' -and
      $_.Exception.Message -notmatch 'Resource temporarily unavailable'
    }
)
if ($unexpectedFullAccessErrors.Count -gt 0) {
  throw $unexpectedFullAccessErrors[0]
}
[pscustomobject]@{
  mailbox_count_scanned = $allMailboxes.Count
  mailboxes = @(
    foreach ($identity in $fullAccess) {
      $mailbox = Get-Mailbox -Identity $identity
      [pscustomobject]@{
        Identity = $identity
        DisplayName = $mailbox.DisplayName
        UserPrincipalName = $mailbox.UserPrincipalName
        PrimarySmtpAddress = $mailbox.PrimarySmtpAddress.ToString()
        PermissionTypes = @('full_access')
      }
    }
  )
} | ConvertTo-Json -Depth 8 -Compress
""".strip(),
            extra_env={"DELEGATE_USER": user},
            timeout_seconds=max(EXCHANGE_DELEGATE_SCAN_TIMEOUT_SECONDS, int(self.timeout_seconds or 0)),
            cancel_requested=cancel_requested,
        )
        return payload if isinstance(payload, dict) else {}

    def get_delegate_mailboxes_for_user(
        self,
        user_identifier: str,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        user = str(user_identifier or "").strip()
        if not user:
            raise ExchangeOnlinePowerShellError("user is required")
        send_as_payload = self.get_send_as_mailboxes_for_user(user, cancel_requested=cancel_requested)
        payload = self.get_full_access_mailboxes_for_user(user, cancel_requested=cancel_requested)
        send_as_mailboxes = send_as_payload.get("mailboxes") if isinstance(send_as_payload, dict) else []
        full_access_mailboxes = payload.get("mailboxes") if isinstance(payload, dict) else []
        return {
            "mailbox_count_scanned": int(payload.get("mailbox_count_scanned") or 0) if isinstance(payload, dict) else 0,
            "mailboxes": [*(send_as_mailboxes or []), *(full_access_mailboxes or [])],
        }
