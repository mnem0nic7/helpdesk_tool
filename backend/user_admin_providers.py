"""Provider adapters for the primary-site user administration workspace."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any

from azure_cache import azure_cache
from azure_client import AzureApiError, AzureClient
from models import UserAdminActionType

logger = logging.getLogger(__name__)

_GRAPH_OBJECT_ROOT = "https://graph.microsoft.com/v1.0"
_PASSWORD_METHOD_ID = "28c10230-6103-485e-b985-444c60001490"
_PROFILE_FIELDS = {
    "display_name": "displayName",
    "department": "department",
    "job_title": "jobTitle",
    "office_location": "officeLocation",
    "company_name": "companyName",
    "mobile_phone": "mobilePhone",
    "business_phones": "businessPhones",
}
_AUTH_METHOD_SEGMENTS = {
    "#microsoft.graph.emailAuthenticationMethod": "emailMethods",
    "#microsoft.graph.fido2AuthenticationMethod": "fido2Methods",
    "#microsoft.graph.microsoftAuthenticatorAuthenticationMethod": "microsoftAuthenticatorMethods",
    "#microsoft.graph.phoneAuthenticationMethod": "phoneMethods",
    "#microsoft.graph.platformCredentialAuthenticationMethod": "platformCredentialMethods",
    "#microsoft.graph.softwareOathAuthenticationMethod": "softwareOathMethods",
    "#microsoft.graph.temporaryAccessPassAuthenticationMethod": "temporaryAccessPassMethods",
    "#microsoft.graph.windowsHelloForBusinessAuthenticationMethod": "windowsHelloForBusinessMethods",
}
_ENTRA_ACTIONS: list[UserAdminActionType] = [
    "disable_sign_in",
    "enable_sign_in",
    "reset_password",
    "revoke_sessions",
    "reset_mfa",
    "unblock_sign_in",
    "update_usage_location",
    "update_profile",
    "set_manager",
    "add_group_membership",
    "remove_group_membership",
    "assign_license",
    "remove_license",
    "add_directory_role",
    "remove_directory_role",
]
_MAILBOX_ACTIONS: list[UserAdminActionType] = [
    "mailbox_add_alias",
    "mailbox_remove_alias",
    "mailbox_set_forwarding",
    "mailbox_clear_forwarding",
    "mailbox_convert_type",
    "mailbox_set_delegates",
]
_DEVICE_ACTIONS: list[UserAdminActionType] = [
    "device_sync",
    "device_retire",
    "device_wipe",
    "device_remote_lock",
    "device_reassign_primary_user",
]


class UserAdminProviderError(RuntimeError):
    """Known user-admin provider failure."""

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def _directory_label(item: dict[str, Any]) -> str:
    if item.get("onPremisesDomainName"):
        return str(item.get("onPremisesDomainName"))
    if str(item.get("userType") or "").strip() == "Guest":
        return "External"
    return "Cloud"


def _safe_graph_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AzureApiError as exc:
        raise UserAdminProviderError(
            str(exc),
            retry_after_seconds=exc.retry_after_seconds(),
        ) from exc


def _compact_list(values: list[str] | None) -> list[str]:
    results: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in results:
            results.append(text)
    return results


def _normalize_reference(item: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(item.get("id") or ""),
        "display_name": str(item.get("displayName") or item.get("display_name") or ""),
        "principal_name": str(item.get("userPrincipalName") or item.get("principal_name") or ""),
        "mail": str(item.get("mail") or ""),
    }


def _license_display_name(item: dict[str, Any]) -> str:
    sku_part_number = str(item.get("skuPartNumber") or "")
    if not sku_part_number:
        return str(item.get("skuId") or "")
    return sku_part_number.replace("_", " ").title()


@dataclass
class EntraAdminProvider:
    client: AzureClient

    @property
    def enabled(self) -> bool:
        return self.client.configured

    @property
    def supported_actions(self) -> list[UserAdminActionType]:
        return list(_ENTRA_ACTIONS)

    def get_user_detail(self, user_id: str) -> dict[str, Any]:
        user = _safe_graph_call(
            self.client.graph_request,
            "GET",
            f"users/{user_id}",
            params={
                "$select": ",".join(
                    [
                        "id",
                        "displayName",
                        "userPrincipalName",
                        "mail",
                        "accountEnabled",
                        "jobTitle",
                        "department",
                        "officeLocation",
                        "companyName",
                        "city",
                        "country",
                        "mobilePhone",
                        "businessPhones",
                        "createdDateTime",
                        "userType",
                        "onPremisesSyncEnabled",
                        "onPremisesDomainName",
                        "onPremisesNetBiosName",
                        "lastPasswordChangeDateTime",
                        "proxyAddresses",
                        "usageLocation",
                        "employeeId",
                        "employeeType",
                        "preferredLanguage",
                    ]
                )
            },
        )
        manager = None
        try:
            manager_payload = _safe_graph_call(
                self.client.graph_request,
                "GET",
                f"users/{user_id}/manager",
                params={"$select": "id,displayName,userPrincipalName,mail"},
            )
            if manager_payload.get("id"):
                manager = _normalize_reference(manager_payload)
        except UserAdminProviderError:
            manager = None

        return {
            "id": str(user.get("id") or ""),
            "display_name": str(user.get("displayName") or ""),
            "principal_name": str(user.get("userPrincipalName") or ""),
            "mail": str(user.get("mail") or ""),
            "enabled": user.get("accountEnabled"),
            "user_type": str(user.get("userType") or "Member"),
            "department": str(user.get("department") or ""),
            "job_title": str(user.get("jobTitle") or ""),
            "office_location": str(user.get("officeLocation") or ""),
            "company_name": str(user.get("companyName") or ""),
            "city": str(user.get("city") or ""),
            "country": str(user.get("country") or ""),
            "mobile_phone": str(user.get("mobilePhone") or ""),
            "business_phones": _compact_list(user.get("businessPhones")),
            "created_datetime": str(user.get("createdDateTime") or ""),
            "last_password_change": str(user.get("lastPasswordChangeDateTime") or ""),
            "on_prem_sync": bool(user.get("onPremisesSyncEnabled")),
            "on_prem_domain": str(user.get("onPremisesDomainName") or ""),
            "on_prem_netbios": str(user.get("onPremisesNetBiosName") or ""),
            "usage_location": str(user.get("usageLocation") or ""),
            "employee_id": str(user.get("employeeId") or ""),
            "employee_type": str(user.get("employeeType") or ""),
            "preferred_language": str(user.get("preferredLanguage") or ""),
            "proxy_addresses": _compact_list(user.get("proxyAddresses")),
            "manager": manager,
            "source_directory": _directory_label(user),
        }

    def _member_of(self, user_id: str) -> list[dict[str, Any]]:
        return _safe_graph_call(
            self.client.graph_paged_get,
            f"users/{user_id}/memberOf",
            params={
                "$select": "id,displayName,mail,description,securityEnabled,groupTypes,userPrincipalName",
                "$top": "999",
            },
        )

    def list_groups(self, user_id: str) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        for item in self._member_of(user_id):
            if not str(item.get("@odata.type") or "").endswith("group"):
                continue
            groups.append(
                {
                    "id": str(item.get("id") or ""),
                    "display_name": str(item.get("displayName") or ""),
                    "mail": str(item.get("mail") or ""),
                    "security_enabled": bool(item.get("securityEnabled")),
                    "group_types": _compact_list(item.get("groupTypes")),
                    "object_type": "group",
                }
            )
        return groups

    def list_roles(self, user_id: str) -> list[dict[str, Any]]:
        roles: list[dict[str, Any]] = []
        for item in self._member_of(user_id):
            if not str(item.get("@odata.type") or "").endswith("directoryRole"):
                continue
            roles.append(
                {
                    "id": str(item.get("id") or ""),
                    "display_name": str(item.get("displayName") or ""),
                    "description": str(item.get("description") or ""),
                    "assignment_type": "direct",
                }
            )
        return roles

    def list_licenses(self, user_id: str) -> list[dict[str, Any]]:
        rows = _safe_graph_call(
            self.client.graph_paged_get,
            f"users/{user_id}/licenseDetails",
            params={"$select": "skuId,skuPartNumber,servicePlans"},
        )
        results: list[dict[str, Any]] = []
        for item in rows:
            disabled_plans: list[str] = []
            for plan in item.get("servicePlans") or []:
                if not isinstance(plan, dict):
                    continue
                if str(plan.get("provisioningStatus") or "").lower() == "disabled":
                    disabled_plans.append(str(plan.get("servicePlanName") or ""))
            results.append(
                {
                    "sku_id": str(item.get("skuId") or ""),
                    "sku_part_number": str(item.get("skuPartNumber") or ""),
                    "display_name": _license_display_name(item),
                    "state": "active",
                    "disabled_plans": [value for value in disabled_plans if value],
                    "assigned_by_group": False,
                }
            )
        return results

    def list_license_catalog(self) -> list[dict[str, str]]:
        rows = _safe_graph_call(
            self.client.graph_paged_get,
            "subscribedSkus",
            params={"$select": "skuId,skuPartNumber"},
        )
        return [
            {
                "sku_id": str(item.get("skuId") or ""),
                "sku_part_number": str(item.get("skuPartNumber") or ""),
                "display_name": _license_display_name(item),
            }
            for item in rows
            if item.get("skuId")
        ]

    def _update_user(self, user_id: str, body: dict[str, Any]) -> None:
        _safe_graph_call(self.client.graph_request, "PATCH", f"users/{user_id}", json_body=body)

    def execute(self, action_type: UserAdminActionType, user_id: str, params: dict[str, Any]) -> dict[str, Any]:
        if action_type == "disable_sign_in":
            before = self.get_user_detail(user_id)
            self._update_user(user_id, {"accountEnabled": False})
            return {
                "provider": "entra",
                "summary": "Disabled sign-in",
                "before_summary": {"enabled": before.get("enabled")},
                "after_summary": {"enabled": False},
            }

        if action_type in {"enable_sign_in", "unblock_sign_in"}:
            before = self.get_user_detail(user_id)
            self._update_user(user_id, {"accountEnabled": True})
            return {
                "provider": "entra",
                "summary": "Enabled sign-in",
                "before_summary": {"enabled": before.get("enabled")},
                "after_summary": {"enabled": True},
            }

        if action_type == "update_usage_location":
            usage_location = str(params.get("usage_location") or "").strip().upper()
            if len(usage_location) != 2:
                raise UserAdminProviderError("usage_location must be a 2-letter country code")
            before = self.get_user_detail(user_id)
            self._update_user(user_id, {"usageLocation": usage_location})
            return {
                "provider": "entra",
                "summary": f"Updated usage location to {usage_location}",
                "before_summary": {"usage_location": before.get("usage_location")},
                "after_summary": {"usage_location": usage_location},
            }

        if action_type == "revoke_sessions":
            _safe_graph_call(self.client.graph_request, "POST", f"users/{user_id}/revokeSignInSessions", json_body={})
            return {
                "provider": "entra",
                "summary": "Revoked active sessions",
                "before_summary": {},
                "after_summary": {"sessions_revoked": True},
            }

        if action_type == "reset_password":
            requested_password = str(params.get("new_password") or "").strip()
            password = requested_password or f"{secrets.token_urlsafe(10)}!Aa1"
            force_change = bool(params.get("force_change_on_next_login", True))
            payload = _safe_graph_call(
                self.client.graph_request,
                "POST",
                f"users/{user_id}/authentication/passwordMethods/{_PASSWORD_METHOD_ID}/resetPassword",
                json_body={
                    "newPassword": password,
                    "requireChangeOnNextSignIn": force_change,
                },
            )
            returned_password = str(payload.get("newPassword") or password)
            return {
                "provider": "entra",
                "summary": "Reset password",
                "before_summary": {},
                "after_summary": {"force_change_on_next_login": force_change},
                "one_time_secret": returned_password,
            }

        if action_type == "reset_mfa":
            methods = _safe_graph_call(
                self.client.graph_paged_get,
                f"users/{user_id}/authentication/methods",
            )
            reset_count = 0
            for method in methods:
                method_id = str(method.get("id") or "").strip()
                odata_type = str(method.get("@odata.type") or "").strip()
                if not method_id or method_id == _PASSWORD_METHOD_ID:
                    continue
                segment = _AUTH_METHOD_SEGMENTS.get(odata_type)
                if not segment:
                    continue
                _safe_graph_call(
                    self.client.graph_request,
                    "DELETE",
                    f"users/{user_id}/authentication/{segment}/{method_id}",
                )
                reset_count += 1
            return {
                "provider": "entra",
                "summary": f"Reset MFA methods ({reset_count})",
                "before_summary": {"method_count": len(methods)},
                "after_summary": {"reset_method_count": reset_count},
            }

        if action_type == "update_profile":
            body: dict[str, Any] = {}
            for source_key, graph_key in _PROFILE_FIELDS.items():
                value = params.get(source_key)
                if value is None:
                    continue
                if source_key == "business_phones":
                    if isinstance(value, list):
                        body[graph_key] = [str(item).strip() for item in value if str(item).strip()]
                    else:
                        body[graph_key] = [item.strip() for item in str(value).split(",") if item.strip()]
                else:
                    body[graph_key] = str(value)
            if not body:
                raise UserAdminProviderError("No profile fields were supplied")
            before = self.get_user_detail(user_id)
            self._update_user(user_id, body)
            after_fields = {key: value for key, value in params.items() if key in _PROFILE_FIELDS}
            return {
                "provider": "entra",
                "summary": "Updated user profile",
                "before_summary": {key: before.get(key) for key in after_fields},
                "after_summary": after_fields,
            }

        if action_type == "set_manager":
            manager_user_id = str(params.get("manager_user_id") or "").strip()
            before = self.get_user_detail(user_id)
            if manager_user_id:
                _safe_graph_call(
                    self.client.graph_request,
                    "PUT",
                    f"users/{user_id}/manager/$ref",
                    json_body={"@odata.id": f"{_GRAPH_OBJECT_ROOT}/directoryObjects/{manager_user_id}"},
                )
            else:
                _safe_graph_call(
                    self.client.graph_request,
                    "DELETE",
                    f"users/{user_id}/manager/$ref",
                )
            return {
                "provider": "entra",
                "summary": "Updated manager assignment",
                "before_summary": {"manager": before.get("manager")},
                "after_summary": {"manager_user_id": manager_user_id},
            }

        if action_type in {"add_group_membership", "remove_group_membership"}:
            group_id = str(params.get("group_id") or "").strip()
            if not group_id:
                raise UserAdminProviderError("group_id is required")
            if action_type == "add_group_membership":
                _safe_graph_call(
                    self.client.graph_request,
                    "POST",
                    f"groups/{group_id}/members/$ref",
                    json_body={"@odata.id": f"{_GRAPH_OBJECT_ROOT}/directoryObjects/{user_id}"},
                )
                summary = "Added user to group"
            else:
                _safe_graph_call(
                    self.client.graph_request,
                    "DELETE",
                    f"groups/{group_id}/members/{user_id}/$ref",
                )
                summary = "Removed user from group"
            return {
                "provider": "entra",
                "summary": summary,
                "before_summary": {"group_id": group_id},
                "after_summary": {"group_id": group_id},
            }

        if action_type in {"assign_license", "remove_license"}:
            sku_id = str(params.get("sku_id") or "").strip()
            if not sku_id:
                raise UserAdminProviderError("sku_id is required")
            payload = {
                "addLicenses": [],
                "removeLicenses": [],
            }
            if action_type == "assign_license":
                payload["addLicenses"] = [
                    {
                        "skuId": sku_id,
                        "disabledPlans": [str(item) for item in params.get("disabled_plans") or []],
                    }
                ]
                summary = "Assigned license"
            else:
                payload["removeLicenses"] = [sku_id]
                summary = "Removed license"
            _safe_graph_call(
                self.client.graph_request,
                "POST",
                f"users/{user_id}/assignLicense",
                json_body=payload,
            )
            return {
                "provider": "entra",
                "summary": summary,
                "before_summary": {"sku_id": sku_id},
                "after_summary": {"sku_id": sku_id},
            }

        if action_type in {"add_directory_role", "remove_directory_role"}:
            role_id = str(params.get("role_id") or "").strip()
            if not role_id:
                raise UserAdminProviderError("role_id is required")
            if action_type == "add_directory_role":
                _safe_graph_call(
                    self.client.graph_request,
                    "POST",
                    f"directoryRoles/{role_id}/members/$ref",
                    json_body={"@odata.id": f"{_GRAPH_OBJECT_ROOT}/directoryObjects/{user_id}"},
                )
                summary = "Added directory role"
            else:
                _safe_graph_call(
                    self.client.graph_request,
                    "DELETE",
                    f"directoryRoles/{role_id}/members/{user_id}/$ref",
                )
                summary = "Removed directory role"
            return {
                "provider": "entra",
                "summary": summary,
                "before_summary": {"role_id": role_id},
                "after_summary": {"role_id": role_id},
            }

        raise UserAdminProviderError(f"Unsupported Entra action: {action_type}")


@dataclass
class MailboxAdminProvider:
    client: AzureClient

    @property
    def enabled(self) -> bool:
        return self.client.configured

    @property
    def supported_actions(self) -> list[UserAdminActionType]:
        return []

    def get_mailbox(self, user_id: str) -> dict[str, Any]:
        user = _safe_graph_call(
            self.client.graph_request,
            "GET",
            f"users/{user_id}",
            params={"$select": "mail,userPrincipalName,proxyAddresses"},
        )
        mailbox_settings: dict[str, Any] = {}
        note = "Mailbox management will unlock when the Exchange provider adapter is configured."
        try:
            mailbox_settings = _safe_graph_call(
                self.client.graph_request,
                "GET",
                f"users/{user_id}/mailboxSettings",
            )
        except UserAdminProviderError:
            mailbox_settings = {}
            note = "Mailbox settings are read-only until the mailbox provider is fully configured."

        aliases: list[str] = []
        primary_address = str(user.get("mail") or user.get("userPrincipalName") or "")
        for raw_value in user.get("proxyAddresses") or []:
            value = str(raw_value or "").strip()
            if not value:
                continue
            if value.startswith("SMTP:"):
                primary_address = value[5:]
                continue
            if value.startswith("smtp:"):
                aliases.append(value[5:])
                continue
            aliases.append(value)

        auto_replies = mailbox_settings.get("automaticRepliesSetting") or {}
        return {
            "primary_address": primary_address,
            "aliases": aliases,
            "forwarding_enabled": False,
            "forwarding_address": "",
            "mailbox_type": str(mailbox_settings.get("userPurpose") or ""),
            "delegate_delivery_mode": str(mailbox_settings.get("delegateMeetingMessageDeliveryOptions") or ""),
            "delegates": [],
            "automatic_replies_status": str(auto_replies.get("status") or ""),
            "provider_enabled": self.enabled,
            "management_supported": False,
            "note": note,
        }

    def execute(self, action_type: UserAdminActionType, user_id: str, params: dict[str, Any]) -> dict[str, Any]:
        del action_type, user_id, params
        raise UserAdminProviderError(
            "Mailbox write actions are not configured yet. Add the Exchange provider adapter to enable them."
        )


@dataclass
class DeviceManagementProvider:
    client: AzureClient

    @property
    def enabled(self) -> bool:
        return self.client.configured

    @property
    def supported_actions(self) -> list[UserAdminActionType]:
        return list(_DEVICE_ACTIONS)

    def list_devices(self, user_id: str) -> list[dict[str, Any]]:
        rows = _safe_graph_call(
            self.client.graph_paged_get,
            f"users/{user_id}/managedDevices",
            params={
                "$select": ",".join(
                    [
                        "id",
                        "deviceName",
                        "operatingSystem",
                        "osVersion",
                        "complianceState",
                        "managementState",
                        "ownerType",
                        "enrollmentType",
                        "lastSyncDateTime",
                        "azureADDeviceId",
                    ]
                )
            },
        )
        devices: list[dict[str, Any]] = []
        for item in rows:
            primary_users: list[dict[str, str]] = []
            device_id = str(item.get("id") or "")
            if device_id:
                try:
                    assigned_users = _safe_graph_call(
                        self.client.graph_paged_get,
                        f"deviceManagement/managedDevices/{device_id}/users",
                        api_version="beta",
                        params={"$select": "id,displayName,userPrincipalName,mail"},
                    )
                    primary_users = [_normalize_reference(user) for user in assigned_users]
                except UserAdminProviderError:
                    primary_users = []
            devices.append(
                {
                    "id": device_id,
                    "device_name": str(item.get("deviceName") or ""),
                    "operating_system": str(item.get("operatingSystem") or ""),
                    "operating_system_version": str(item.get("osVersion") or ""),
                    "compliance_state": str(item.get("complianceState") or ""),
                    "management_state": str(item.get("managementState") or ""),
                    "owner_type": str(item.get("ownerType") or ""),
                    "enrollment_type": str(item.get("enrollmentType") or ""),
                    "last_sync_date_time": str(item.get("lastSyncDateTime") or ""),
                    "azure_ad_device_id": str(item.get("azureADDeviceId") or ""),
                    "primary_users": primary_users,
                }
            )
        return devices

    def execute(self, action_type: UserAdminActionType, user_id: str, params: dict[str, Any]) -> dict[str, Any]:
        del user_id
        device_ids = [str(item).strip() for item in params.get("device_ids") or [] if str(item).strip()]
        if not device_ids:
            raise UserAdminProviderError("device_ids is required")

        action_path = {
            "device_sync": "syncDevice",
            "device_retire": "retire",
            "device_remote_lock": "remoteLock",
        }.get(action_type)
        if action_path:
            for device_id in device_ids:
                _safe_graph_call(
                    self.client.graph_request,
                    "POST",
                    f"deviceManagement/managedDevices/{device_id}/{action_path}",
                    json_body={},
                )
            return {
                "provider": "device_management",
                "summary": f"Queued {action_type.replace('_', ' ')} for {len(device_ids)} device(s)",
                "before_summary": {"device_ids": device_ids},
                "after_summary": {"device_ids": device_ids},
            }

        if action_type == "device_wipe":
            wipe_payload = {
                "keepEnrollmentData": bool(params.get("keep_enrollment_data", False)),
                "keepUserData": bool(params.get("keep_user_data", False)),
                "useProtectedWipe": bool(params.get("use_protected_wipe", False)),
            }
            for device_id in device_ids:
                _safe_graph_call(
                    self.client.graph_request,
                    "POST",
                    f"deviceManagement/managedDevices/{device_id}/wipe",
                    json_body=wipe_payload,
                )
            return {
                "provider": "device_management",
                "summary": f"Queued wipe for {len(device_ids)} device(s)",
                "before_summary": {"device_ids": device_ids},
                "after_summary": {"wipe": True},
            }

        if action_type == "device_reassign_primary_user":
            primary_user_id = str(params.get("primary_user_id") or "").strip()
            if not primary_user_id:
                raise UserAdminProviderError("primary_user_id is required")
            for device_id in device_ids:
                _safe_graph_call(
                    self.client.graph_request,
                    "POST",
                    f"deviceManagement/managedDevices/{device_id}/users/$ref",
                    api_version="beta",
                    json_body={"@odata.id": f"{_GRAPH_OBJECT_ROOT}/users/{primary_user_id}"},
                )
            return {
                "provider": "device_management",
                "summary": f"Reassigned primary user on {len(device_ids)} device(s)",
                "before_summary": {"device_ids": device_ids},
                "after_summary": {"primary_user_id": primary_user_id},
            }

        raise UserAdminProviderError(f"Unsupported device action: {action_type}")


class UserAdminProviderRegistry:
    def __init__(self, client: AzureClient | None = None) -> None:
        self._client = client or azure_cache._client
        self.entra = EntraAdminProvider(self._client)
        self.mailbox = MailboxAdminProvider(self._client)
        self.device_management = DeviceManagementProvider(self._client)

    @property
    def enabled(self) -> bool:
        return self._client.configured

    def provider_for_action(self, action_type: UserAdminActionType):
        if action_type in _ENTRA_ACTIONS:
            return self.entra, "entra"
        if action_type in _MAILBOX_ACTIONS:
            return self.mailbox, "mailbox"
        if action_type in _DEVICE_ACTIONS:
            return self.device_management, "device_management"
        raise UserAdminProviderError(f"Unsupported action type: {action_type}")

    def supported_actions(self) -> list[UserAdminActionType]:
        actions = self.entra.supported_actions + self.mailbox.supported_actions + self.device_management.supported_actions
        return list(dict.fromkeys(actions))

    def get_capabilities(self) -> dict[str, Any]:
        groups = azure_cache.list_directory_objects("groups", search="")
        roles = azure_cache.list_directory_objects("directory_roles", search="")
        ca_groups = [
            item
            for item in groups
            if "conditional access" in str(item.get("display_name") or "").lower()
            or "ca exception" in str(item.get("display_name") or "").lower()
        ]
        return {
            "can_manage_users": True,
            "enabled_providers": {
                "entra": self.entra.enabled,
                "mailbox": self.mailbox.enabled,
                "device_management": self.device_management.enabled,
            },
            "supported_actions": self.supported_actions(),
            "license_catalog": self.entra.list_license_catalog() if self.entra.enabled else [],
            "group_catalog": [_normalize_reference(item) for item in groups],
            "role_catalog": [_normalize_reference(item) for item in roles],
            "conditional_access_exception_groups": [_normalize_reference(item) for item in ca_groups],
        }

    def get_user_detail(self, user_id: str) -> dict[str, Any]:
        return self.entra.get_user_detail(user_id)

    def list_groups(self, user_id: str) -> list[dict[str, Any]]:
        return self.entra.list_groups(user_id)

    def list_licenses(self, user_id: str) -> list[dict[str, Any]]:
        return self.entra.list_licenses(user_id)

    def list_roles(self, user_id: str) -> list[dict[str, Any]]:
        return self.entra.list_roles(user_id)

    def get_mailbox(self, user_id: str) -> dict[str, Any]:
        return self.mailbox.get_mailbox(user_id)

    def list_devices(self, user_id: str) -> list[dict[str, Any]]:
        return self.device_management.list_devices(user_id)

    def execute(self, action_type: UserAdminActionType, user_id: str, params: dict[str, Any]) -> dict[str, Any]:
        provider, _provider_key = self.provider_for_action(action_type)
        return provider.execute(action_type, user_id, params)


user_admin_providers = UserAdminProviderRegistry()
