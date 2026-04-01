"""Synchronous Tools helper for Emailgistics mailbox onboarding."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from azure_client import AzureApiError, AzureClient
from config import (
    EMAILGISTICS_AUTH_TOKEN,
    EMAILGISTICS_CONFIGURED_MAILBOXES,
    EMAILGISTICS_SYNC_TIMEOUT_SECONDS,
    EMAILGISTICS_SYNC_SECURITY_GROUPS,
    EMAILGISTICS_TOKEN_VALID_URL,
    EMAILGISTICS_USER_SYNC_URL,
    ENTRA_CLIENT_ID,
    ENTRA_CLIENT_SECRET,
    ENTRA_TENANT_ID,
)
from exchange_online_client import (
    ExchangeOnlinePowerShellClient,
    ExchangeOnlinePowerShellError,
    _sanitize_powershell_error_text,
)

EMAILGISTICS_ADDIN_GROUP_NAME = "Emailgistics_UserAddin"
_GRAPH_OBJECT_ROOT = "https://graph.microsoft.com/v1.0"
_STEP_LABELS = {
    "full_access": "Grant Full Access",
    "send_as": "Grant Send As",
    "addin_group": "Add To Emailgistics_UserAddin",
    "sync_users": "Run Emailgistics Sync",
}


class EmailgisticsHelperError(RuntimeError):
    """Known Emailgistics helper failure."""


@dataclass(frozen=True)
class EmailgisticsSyncExecution:
    """Prepared runtime data for one Emailgistics syncUsers.ps1 execution."""

    exchange_client: ExchangeOnlinePowerShellClient
    script_dir: Path
    script_path: Path
    env: dict[str, str]


def _step_payload(key: str, status: str = "pending", message: str = "") -> dict[str, str]:
    return {
        "key": key,
        "label": _STEP_LABELS[key],
        "status": status,
        "message": message,
    }


def _normalized_mailbox(value: Any) -> str:
    return str(value or "").strip().lower()


def _odata_quote(value: str) -> str:
    return str(value or "").replace("'", "''")


@dataclass
class EmailgisticsHelperService:
    client: AzureClient
    exchange_client: ExchangeOnlinePowerShellClient | None = None
    addin_group_name: str = EMAILGISTICS_ADDIN_GROUP_NAME
    sync_script_dir: Path | None = None
    sync_timeout_seconds: int = EMAILGISTICS_SYNC_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.exchange_client is None:
            self.exchange_client = ExchangeOnlinePowerShellClient(self.client)
        if self.sync_script_dir is None:
            self.sync_script_dir = Path(__file__).resolve().parent.parent / "scripts" / "syncUsers"

    def _resolve_user(self, mailbox: str) -> dict[str, str]:
        try:
            payload = self.client.graph_request(
                "GET",
                f"users/{quote(mailbox, safe='')}",
                params={"$select": "id,displayName,userPrincipalName,mail"},
            )
        except AzureApiError as exc:
            raise EmailgisticsHelperError(f"Could not resolve user mailbox {mailbox}: {exc}") from exc
        user_id = str(payload.get("id") or "").strip()
        principal_name = str(payload.get("userPrincipalName") or mailbox).strip() or mailbox
        primary_address = str(payload.get("mail") or principal_name).strip() or principal_name
        if not user_id:
            raise EmailgisticsHelperError(f"Could not resolve user mailbox {mailbox}.")
        return {
            "id": user_id,
            "display_name": str(payload.get("displayName") or "").strip(),
            "principal_name": principal_name,
            "primary_address": primary_address,
        }

    def _resolve_shared_mailbox(self, mailbox: str, *, anchor_mailbox: str) -> dict[str, str]:
        try:
            payload = self.client.exchange_admin_request(
                "Mailbox",
                anchor_mailbox=anchor_mailbox,
                cmdlet_name="Get-Mailbox",
                parameters={"Identity": mailbox},
                select=["DisplayName", "UserPrincipalName", "PrimarySmtpAddress"],
            )
        except AzureApiError as exc:
            raise EmailgisticsHelperError(f"Could not resolve shared mailbox {mailbox}: {exc}") from exc
        rows = payload.get("value") if isinstance(payload, dict) else []
        row = next((item for item in rows or [] if isinstance(item, dict)), None)
        if not row:
            raise EmailgisticsHelperError(f"Shared mailbox {mailbox} was not found in Exchange.")
        principal_name = str(row.get("UserPrincipalName") or mailbox).strip() or mailbox
        primary_address = str(row.get("PrimarySmtpAddress") or principal_name).strip() or principal_name
        return {
            "display_name": str(row.get("DisplayName") or "").strip(),
            "principal_name": principal_name,
            "primary_address": primary_address,
        }

    def _resolve_addin_group(self) -> dict[str, str]:
        try:
            payload = self.client.graph_request(
                "GET",
                "groups",
                params={
                    "$filter": f"displayName eq '{_odata_quote(self.addin_group_name)}'",
                    "$select": "id,displayName,mail",
                },
            )
        except AzureApiError as exc:
            raise EmailgisticsHelperError(f"Could not resolve group {self.addin_group_name}: {exc}") from exc
        rows = payload.get("value") if isinstance(payload, dict) else []
        row = next((item for item in rows or [] if isinstance(item, dict)), None)
        if not row:
            raise EmailgisticsHelperError(f"Group {self.addin_group_name} was not found in Entra.")
        return {
            "id": str(row.get("id") or "").strip(),
            "display_name": str(row.get("displayName") or self.addin_group_name).strip() or self.addin_group_name,
        }

    def _add_user_to_group(self, *, user: dict[str, str], group: dict[str, str]) -> dict[str, str]:
        group_id = str(group.get("id") or "").strip()
        user_id = str(user.get("id") or "").strip()
        if not group_id or not user_id:
            raise EmailgisticsHelperError("Group or user resolution is incomplete.")
        try:
            self.client.graph_request(
                "POST",
                f"groups/{group_id}/members/$ref",
                json_body={"@odata.id": f"{_GRAPH_OBJECT_ROOT}/directoryObjects/{user_id}"},
            )
        except AzureApiError as exc:
            message = str(exc)
            if "added object references already exist" in message.lower():
                return {
                    "status": "already_present",
                    "message": f"{user.get('primary_address') or user.get('principal_name')} is already in {group.get('display_name') or self.addin_group_name}.",
                }
            raise EmailgisticsHelperError(f"Could not add the user to {group.get('display_name') or self.addin_group_name}: {exc}") from exc
        return {
            "status": "completed",
            "message": f"Added {user.get('primary_address') or user.get('principal_name')} to {group.get('display_name') or self.addin_group_name}.",
        }

    def _prepare_sync_users_execution(self, shared_mailbox: str | None = None) -> EmailgisticsSyncExecution:
        script_dir = Path(self.sync_script_dir or "")
        script_path = script_dir / "syncUsers.ps1"
        if not script_path.exists():
            raise EmailgisticsHelperError("The Emailgistics syncUsers.ps1 script is not available on the app runtime.")
        exchange_client = self.exchange_client or ExchangeOnlinePowerShellClient(self.client)
        normalized_shared_mailbox = str(shared_mailbox or "").strip().lower()
        missing_settings: list[str] = []
        if not EMAILGISTICS_TOKEN_VALID_URL:
            missing_settings.append("EMAILGISTICS_TOKEN_VALID_URL")
        if not EMAILGISTICS_USER_SYNC_URL:
            missing_settings.append("EMAILGISTICS_USER_SYNC_URL")
        if not EMAILGISTICS_AUTH_TOKEN:
            missing_settings.append("EMAILGISTICS_AUTH_TOKEN")
        if not ENTRA_TENANT_ID:
            missing_settings.append("ENTRA_TENANT_ID")
        if not ENTRA_CLIENT_ID:
            missing_settings.append("ENTRA_CLIENT_ID")
        if not ENTRA_CLIENT_SECRET:
            missing_settings.append("ENTRA_CLIENT_SECRET")
        if not normalized_shared_mailbox and not EMAILGISTICS_CONFIGURED_MAILBOXES:
            missing_settings.append("EMAILGISTICS_CONFIGURED_MAILBOXES")
        if missing_settings:
            raise EmailgisticsHelperError(
                "Emailgistics automation is not fully configured on the app runtime. Missing "
                + ", ".join(missing_settings)
                + "."
            )
        organization = exchange_client.organization()
        env = os.environ.copy()
        env.update(
            {
                "EMAILGISTICS_NONINTERACTIVE": "1",
                "EMAILGISTICS_TOKEN_VALID_URL": EMAILGISTICS_TOKEN_VALID_URL,
                "EMAILGISTICS_USER_SYNC_URL": EMAILGISTICS_USER_SYNC_URL,
                "EMAILGISTICS_AUTH_TOKEN": EMAILGISTICS_AUTH_TOKEN,
                "EMAILGISTICS_TENANT_ID": ENTRA_TENANT_ID,
                "EMAILGISTICS_APP_ID": ENTRA_CLIENT_ID,
                "EMAILGISTICS_CLIENT_SECRET": ENTRA_CLIENT_SECRET,
                "EMAILGISTICS_ORGANIZATION_DOMAIN": organization,
                "EMAILGISTICS_CONFIGURED_MAILBOXES": ",".join(EMAILGISTICS_CONFIGURED_MAILBOXES),
                "EMAILGISTICS_SYNC_SECURITY_GROUPS": "1" if EMAILGISTICS_SYNC_SECURITY_GROUPS else "0",
                "EXCHANGE_ONLINE_ORGANIZATION": organization,
                "MG_GRAPH_APP_ID": ENTRA_CLIENT_ID,
            }
        )
        if normalized_shared_mailbox:
            env["EMAILGISTICS_TARGET_MAILBOX"] = normalized_shared_mailbox
        else:
            env.pop("EMAILGISTICS_TARGET_MAILBOX", None)
        return EmailgisticsSyncExecution(
            exchange_client=exchange_client,
            script_dir=script_dir,
            script_path=script_path,
            env=env,
        )

    def _run_sync_users_script(
        self,
        shared_mailbox: str | None,
        *,
        execution: EmailgisticsSyncExecution | None = None,
    ) -> dict[str, str]:
        prepared = execution or self._prepare_sync_users_execution(shared_mailbox)
        target_label = str(shared_mailbox or "").strip() or "all configured mailboxes"
        process = subprocess.Popen(
            [prepared.exchange_client.pwsh_path, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(prepared.script_path)],
            cwd=str(prepared.script_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=prepared.env,
        )
        timeout_seconds = max(
            60,
            int(self.sync_timeout_seconds or 0),
            int(prepared.exchange_client.timeout_seconds or 0),
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise EmailgisticsHelperError("Emailgistics syncUsers.ps1 timed out before it finished.") from exc
        output = _sanitize_powershell_error_text(stdout or stderr or "")
        if process.returncode != 0:
            raise EmailgisticsHelperError(output or "Emailgistics syncUsers.ps1 failed.")
        return {
            "status": "completed",
            "message": f"Ran Emailgistics sync for {target_label}.",
            "output": output[:4000],
        }

    def run(self, *, user_mailbox: str, shared_mailbox: str) -> dict[str, Any]:
        normalized_user_mailbox = str(user_mailbox or "").strip()
        normalized_shared_mailbox = str(shared_mailbox or "").strip()
        steps = [
            _step_payload("full_access"),
            _step_payload("send_as"),
            _step_payload("addin_group"),
            _step_payload("sync_users"),
        ]
        response: dict[str, Any] = {
            "status": "failed",
            "user_mailbox": normalized_user_mailbox,
            "shared_mailbox": normalized_shared_mailbox,
            "resolved_user_display_name": "",
            "resolved_user_principal_name": normalized_user_mailbox,
            "resolved_shared_display_name": "",
            "resolved_shared_principal_name": normalized_shared_mailbox,
            "addin_group_name": self.addin_group_name,
            "note": "",
            "error": "",
            "sync_output": "",
            "steps": steps,
        }
        try:
            user = self._resolve_user(normalized_user_mailbox)
            shared = self._resolve_shared_mailbox(
                normalized_shared_mailbox,
                anchor_mailbox=user.get("principal_name") or normalized_user_mailbox,
            )
            group = self._resolve_addin_group()
            response["resolved_user_display_name"] = user.get("display_name") or ""
            response["resolved_user_principal_name"] = user.get("principal_name") or normalized_user_mailbox
            response["resolved_shared_display_name"] = shared.get("display_name") or ""
            response["resolved_shared_principal_name"] = shared.get("primary_address") or shared.get("principal_name") or normalized_shared_mailbox
            sync_execution = self._prepare_sync_users_execution(
                shared.get("primary_address") or shared.get("principal_name") or normalized_shared_mailbox
            )

            full_access = (self.exchange_client or ExchangeOnlinePowerShellClient(self.client)).grant_full_access_permission(
                shared.get("primary_address") or shared.get("principal_name") or normalized_shared_mailbox,
                user.get("primary_address") or user.get("principal_name") or normalized_user_mailbox,
            )
            steps[0] = _step_payload("full_access", str(full_access.get("status") or "completed"), str(full_access.get("message") or ""))

            send_as = (self.exchange_client or ExchangeOnlinePowerShellClient(self.client)).grant_send_as_permission(
                shared.get("primary_address") or shared.get("principal_name") or normalized_shared_mailbox,
                user.get("primary_address") or user.get("principal_name") or normalized_user_mailbox,
            )
            steps[1] = _step_payload("send_as", str(send_as.get("status") or "completed"), str(send_as.get("message") or ""))

            group_step = self._add_user_to_group(user=user, group=group)
            steps[2] = _step_payload("addin_group", str(group_step.get("status") or "completed"), str(group_step.get("message") or ""))

            sync_step = self._run_sync_users_script(
                shared.get("primary_address") or normalized_shared_mailbox,
                execution=sync_execution,
            )
            steps[3] = _step_payload("sync_users", str(sync_step.get("status") or "completed"), str(sync_step.get("message") or ""))
            response["sync_output"] = str(sync_step.get("output") or "")
            response["status"] = "completed"
            response["note"] = (
                f"Emailgistics Helper finished for {response['resolved_user_principal_name']} on "
                f"{response['resolved_shared_principal_name']}."
            )
        except (EmailgisticsHelperError, ExchangeOnlinePowerShellError) as exc:
            response["error"] = str(exc)
            response["note"] = "Emailgistics Helper stopped before all steps completed."
            for step in steps:
                if step["status"] == "pending":
                    step["status"] = "failed"
                    step["message"] = str(exc)
                    break
        return response

    def run_sync_only(self, *, shared_mailbox: str | None) -> dict[str, Any]:
        normalized_shared_mailbox = str(shared_mailbox or "").strip()
        steps = [_step_payload("sync_users")]
        response: dict[str, Any] = {
            "status": "failed",
            "user_mailbox": "",
            "shared_mailbox": normalized_shared_mailbox,
            "resolved_user_display_name": "",
            "resolved_user_principal_name": "",
            "resolved_shared_display_name": "",
            "resolved_shared_principal_name": normalized_shared_mailbox,
            "addin_group_name": self.addin_group_name,
            "note": "",
            "error": "",
            "sync_output": "",
            "steps": steps,
        }
        try:
            resolved_shared_mailbox = ""
            if normalized_shared_mailbox:
                shared = self._resolve_shared_mailbox(
                    normalized_shared_mailbox,
                    anchor_mailbox=normalized_shared_mailbox,
                )
                resolved_shared_mailbox = (
                    shared.get("primary_address") or shared.get("principal_name") or normalized_shared_mailbox
                )
                response["resolved_shared_display_name"] = shared.get("display_name") or ""
                response["resolved_shared_principal_name"] = resolved_shared_mailbox
            sync_execution = self._prepare_sync_users_execution(resolved_shared_mailbox or None)
            sync_step = self._run_sync_users_script(
                resolved_shared_mailbox or None,
                execution=sync_execution,
            )
            steps[0] = _step_payload(
                "sync_users",
                str(sync_step.get("status") or "completed"),
                str(sync_step.get("message") or ""),
            )
            response["sync_output"] = str(sync_step.get("output") or "")
            response["status"] = "completed"
            response["note"] = (
                f"Emailgistics sync finished for {resolved_shared_mailbox}."
                if resolved_shared_mailbox
                else "Emailgistics sync finished for all configured mailboxes."
            )
        except (EmailgisticsHelperError, ExchangeOnlinePowerShellError) as exc:
            response["error"] = str(exc)
            response["note"] = "Emailgistics sync stopped before it could finish."
            steps[0]["status"] = "failed"
            steps[0]["message"] = str(exc)
        return response


emailgistics_helper_service = EmailgisticsHelperService(AzureClient())
