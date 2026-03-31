"""Provider adapters for the primary-site user administration workspace."""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

from azure_cache import azure_cache
from azure_client import AzureApiError, AzureClient
from exchange_online_client import ExchangeOnlinePowerShellClient, ExchangeOnlinePowerShellError
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
_MAILBOX_DELEGATE_PERMISSION_TYPES = ["send_on_behalf", "send_as", "full_access"]


def _emit_progress(progress_callback: Callable[[dict[str, Any]], None] | None, **payload: Any) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(payload)
    except Exception:
        logger.warning("Mailbox delegate progress callback failed", exc_info=True)


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


def _message_rule_label(key: str) -> str:
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", str(key or "")).strip().replace("_", " ")
    if not words:
        return ""
    label = words[0].upper() + words[1:]
    return label.replace("Id", "ID")


def _message_rule_recipient_text(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value or "").strip()
    email = value.get("emailAddress")
    if isinstance(email, dict):
        address = str(email.get("address") or "").strip()
        name = str(email.get("name") or "").strip()
        if address and name and name.lower() != address.lower():
            return f"{name} <{address}>"
        return address or name
    for key in ("address", "mail", "userPrincipalName", "displayName", "name", "id"):
        text = str(value.get(key) or "").strip()
        if text:
            return text
    return ""


def _message_rule_value_texts(value: Any) -> list[str]:
    if value is None or value is False:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        results: list[str] = []
        for item in value:
            for text in _message_rule_value_texts(item):
                if text and text not in results:
                    results.append(text)
        return results
    if isinstance(value, dict):
        recipient_text = _message_rule_recipient_text(value)
        if recipient_text:
            return [recipient_text]
        minimum = value.get("minimumSize")
        maximum = value.get("maximumSize")
        if minimum is not None or maximum is not None:
            if minimum is not None and maximum is not None:
                return [f"{minimum} to {maximum}"]
            if minimum is not None:
                return [f">= {minimum}"]
            return [f"<= {maximum}"]
        results: list[str] = []
        for nested_key, nested_value in value.items():
            if nested_key.startswith("@odata"):
                continue
            nested_label = _message_rule_label(nested_key)
            for text in _message_rule_value_texts(nested_value):
                if not text:
                    continue
                entry = f"{nested_label}: {text}" if nested_label else text
                if entry not in results:
                    results.append(entry)
        return results
    return [str(value)]


def _mail_folder_label(item: dict[str, Any]) -> str:
    display_name = str(item.get("displayName") or "").strip()
    if display_name:
        return display_name
    return ""


def _summarize_message_rule_section(
    section: Any,
    *,
    section_name: str,
    folder_labels: dict[str, str] | None = None,
) -> list[str]:
    if not isinstance(section, dict):
        return []
    resolved_folder_labels = folder_labels or {}
    results: list[str] = []
    for key, value in section.items():
        if key.startswith("@odata") or value in (None, "", [], {}, False):
            continue
        label = _message_rule_label(key)
        if section_name == "actions" and key == "stopProcessingRules" and value is True:
            results.append("Stop processing more rules")
            continue
        if section_name == "actions" and key in {"moveToFolder", "copyToFolder"}:
            folder_id = str(value or "").strip()
            if not folder_id:
                continue
            folder_text = resolved_folder_labels.get(folder_id, folder_id)
            summary = f"{label}: {folder_text}" if label else folder_text
            if summary not in results:
                results.append(summary)
            continue
        if isinstance(value, bool):
            if value:
                results.append(label)
            continue
        values = _message_rule_value_texts(value)
        if not values:
            continue
        joined = ", ".join(values)
        summary = f"{label}: {joined}" if label else joined
        if summary not in results:
            results.append(summary)
    return results


def _coerce_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_mailbox_rule(item: dict[str, Any], *, folder_labels: dict[str, str] | None = None) -> dict[str, Any]:
    conditions = item.get("conditions") if isinstance(item.get("conditions"), dict) else {}
    exceptions = item.get("exceptions") if isinstance(item.get("exceptions"), dict) else {}
    actions = item.get("actions") if isinstance(item.get("actions"), dict) else {}
    return {
        "id": str(item.get("id") or ""),
        "display_name": str(item.get("displayName") or ""),
        "sequence": _coerce_optional_int(item.get("sequence")),
        "is_enabled": bool(item.get("isEnabled")),
        "has_error": bool(item.get("hasError")),
        "stop_processing_rules": bool(actions.get("stopProcessingRules")),
        "conditions_summary": _summarize_message_rule_section(conditions, section_name="conditions"),
        "exceptions_summary": _summarize_message_rule_section(exceptions, section_name="exceptions"),
        "actions_summary": _summarize_message_rule_section(
            actions,
            section_name="actions",
            folder_labels=folder_labels,
        ),
    }


def _normalized_mailbox_identifier(value: Any) -> str:
    return str(value or "").strip().lower()


def _exchange_string_list(value: Any) -> list[str]:
    results: list[str] = []
    for item in value or []:
        text = str(item or "").strip()
        if text:
            results.append(text)
    return results


def _mailbox_delegate_display_name(raw_value: str, *, mail: str) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    if text.endswith(">") and "<" in text:
        prefix, _, suffix = text.rpartition("<")
        candidate_mail = suffix[:-1].strip()
        if candidate_mail and _normalized_mailbox_identifier(candidate_mail) == _normalized_mailbox_identifier(mail):
            text = prefix.strip().strip('"')
    if _normalized_mailbox_identifier(text) == _normalized_mailbox_identifier(mail):
        return ""
    return text


def _delegate_entry_identity(item: dict[str, Any]) -> str:
    for key in ("identity", "mail", "principal_name", "display_name"):
        text = str(item.get(key) or "").strip()
        if text:
            return text
    return ""


def _build_delegate_entry(*, identity: str = "", display_name: str = "", principal_name: str = "", mail: str = "") -> dict[str, Any]:
    normalized_identity = str(identity or "").strip()
    normalized_principal_name = str(principal_name or "").strip()
    normalized_mail = str(mail or "").strip()
    normalized_display_name = str(display_name or "").strip()
    resolved_identity = normalized_identity or normalized_mail or normalized_principal_name or normalized_display_name
    return {
        "identity": resolved_identity,
        "display_name": normalized_display_name,
        "principal_name": normalized_principal_name,
        "mail": normalized_mail,
        "permission_types": [],
    }


def _parse_exchange_trustee(value: Any) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return _build_delegate_entry()
    if text.endswith(">") and "<" in text:
        prefix, _, suffix = text.rpartition("<")
        candidate_mail = suffix[:-1].strip()
        display_name = prefix.strip().strip('"')
        if candidate_mail:
            return _build_delegate_entry(
                identity=candidate_mail,
                display_name=display_name,
                principal_name=candidate_mail,
                mail=candidate_mail,
            )
    if "@" in text and "\\" not in text and " " not in text:
        return _build_delegate_entry(
            identity=text,
            display_name="",
            principal_name=text,
            mail=text,
        )
    return _build_delegate_entry(identity=text, display_name=text)


def _merge_delegate_permissions(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for entry in entries:
        identity = _normalized_mailbox_identifier(_delegate_entry_identity(entry))
        if not identity:
            continue
        existing = merged.get(identity)
        if existing is None:
            existing = {
                "identity": str(entry.get("identity") or _delegate_entry_identity(entry) or "").strip(),
                "display_name": str(entry.get("display_name") or "").strip(),
                "principal_name": str(entry.get("principal_name") or "").strip(),
                "mail": str(entry.get("mail") or "").strip(),
                "permission_types": [],
            }
            merged[identity] = existing
        else:
            if not existing["display_name"]:
                existing["display_name"] = str(entry.get("display_name") or "").strip()
            if not existing["principal_name"]:
                existing["principal_name"] = str(entry.get("principal_name") or "").strip()
            if not existing["mail"]:
                existing["mail"] = str(entry.get("mail") or "").strip()
        for permission_type in entry.get("permission_types") or []:
            text = str(permission_type or "").strip()
            if text and text not in existing["permission_types"]:
                existing["permission_types"].append(text)

    results = list(merged.values())
    results.sort(
        key=lambda item: (
            _normalized_mailbox_identifier(item.get("display_name") or item.get("mail") or item.get("principal_name") or item.get("identity")),
            _normalized_mailbox_identifier(item.get("mail") or item.get("principal_name") or item.get("identity")),
        )
    )
    return results


def _permission_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {permission_type: 0 for permission_type in _MAILBOX_DELEGATE_PERMISSION_TYPES}
    for entry in entries:
        for permission_type in entry.get("permission_types") or []:
            text = str(permission_type or "").strip()
            if text in counts:
                counts[text] += 1
    return counts


def _merge_mailbox_matches(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for entry in entries:
        identity = _normalized_mailbox_identifier(entry.get("identity") or entry.get("primary_address") or entry.get("principal_name"))
        if not identity:
            continue
        existing = merged.get(identity)
        if existing is None:
            existing = {
                "identity": str(entry.get("identity") or entry.get("primary_address") or entry.get("principal_name") or "").strip(),
                "display_name": str(entry.get("display_name") or "").strip(),
                "principal_name": str(entry.get("principal_name") or "").strip(),
                "primary_address": str(entry.get("primary_address") or "").strip(),
                "permission_types": [],
            }
            merged[identity] = existing
        else:
            if not existing["display_name"]:
                existing["display_name"] = str(entry.get("display_name") or "").strip()
            if not existing["principal_name"]:
                existing["principal_name"] = str(entry.get("principal_name") or "").strip()
            if not existing["primary_address"]:
                existing["primary_address"] = str(entry.get("primary_address") or "").strip()
        for permission_type in entry.get("permission_types") or []:
            text = str(permission_type or "").strip()
            if text and text not in existing["permission_types"]:
                existing["permission_types"].append(text)

    results = list(merged.values())
    results.sort(
        key=lambda item: (
            _normalized_mailbox_identifier(item.get("display_name") or item.get("primary_address") or item.get("principal_name") or item.get("identity")),
            _normalized_mailbox_identifier(item.get("primary_address") or item.get("principal_name") or item.get("identity")),
        )
    )
    return results


def _exchange_send_on_behalf_delegates(item: dict[str, Any]) -> list[dict[str, Any]]:
    delegates = _exchange_string_list(item.get("GrantSendOnBehalfTo"))
    delegate_display_names = _exchange_string_list(item.get("GrantSendOnBehalfToWithDisplayNames"))
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, delegate in enumerate(delegates):
        normalized_delegate = _normalized_mailbox_identifier(delegate)
        if not normalized_delegate or normalized_delegate in seen:
            continue
        seen.add(normalized_delegate)
        display_name = ""
        if index < len(delegate_display_names):
            display_name = _mailbox_delegate_display_name(delegate_display_names[index], mail=delegate)
        entry = _build_delegate_entry(
            identity=delegate,
            display_name=display_name,
            principal_name=delegate,
            mail=delegate,
        )
        entry["permission_types"] = ["send_on_behalf"]
        results.append(entry)
    return results


def _exchange_mailbox_match(item: dict[str, Any]) -> dict[str, Any]:
    primary_address = str(item.get("PrimarySmtpAddress") or item.get("UserPrincipalName") or "").strip()
    principal_name = str(item.get("UserPrincipalName") or primary_address).strip()
    return {
        "identity": str(item.get("Identity") or primary_address or principal_name).strip(),
        "display_name": str(item.get("DisplayName") or primary_address or principal_name).strip(),
        "principal_name": principal_name,
        "primary_address": primary_address or principal_name,
        "permission_types": [],
    }


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
        user = _safe_graph_call(self.client.get_user, user_id)
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
        sign_in = user.get("signInActivity") if isinstance(user.get("signInActivity"), dict) else {}
        assigned_licenses = user.get("assignedLicenses") if isinstance(user.get("assignedLicenses"), list) else []
        sku_map = {
            str(item.get("sku_id") or item.get("skuId") or "").strip().lower(): str(
                item.get("sku_part_number") or item.get("skuPartNumber") or ""
            ).strip()
            for item in self.list_license_catalog()
            if item.get("sku_id") or item.get("skuId")
        }
        sku_part_numbers: list[str] = []
        for item in assigned_licenses:
            if not isinstance(item, dict):
                continue
            sku_id = str(item.get("skuId") or "").strip()
            if not sku_id:
                continue
            label = sku_map.get(sku_id.lower()) or sku_id
            if label and label not in sku_part_numbers:
                sku_part_numbers.append(label)

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
            "on_prem_sam_account_name": str(user.get("onPremisesSamAccountName") or ""),
            "on_prem_distinguished_name": str(user.get("onPremisesDistinguishedName") or ""),
            "usage_location": str(user.get("usageLocation") or ""),
            "employee_id": str(user.get("employeeId") or ""),
            "employee_type": str(user.get("employeeType") or ""),
            "preferred_language": str(user.get("preferredLanguage") or ""),
            "proxy_addresses": _compact_list(user.get("proxyAddresses")),
            "is_licensed": len(sku_part_numbers) > 0,
            "license_count": len(sku_part_numbers),
            "sku_part_numbers": sku_part_numbers,
            "last_interactive_utc": str(sign_in.get("lastSignInDateTime") or ""),
            "last_interactive_local": azure_cache._format_local_datetime_text(sign_in.get("lastSignInDateTime") or ""),
            "last_noninteractive_utc": str(sign_in.get("lastNonInteractiveSignInDateTime") or ""),
            "last_noninteractive_local": azure_cache._format_local_datetime_text(sign_in.get("lastNonInteractiveSignInDateTime") or ""),
            "last_successful_utc": str(sign_in.get("lastSuccessfulSignInDateTime") or ""),
            "last_successful_local": azure_cache._format_local_datetime_text(sign_in.get("lastSuccessfulSignInDateTime") or ""),
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
        rows = _safe_graph_call(self.client.list_subscribed_skus)
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

    def remove_direct_cloud_group_memberships(self, user_id: str) -> dict[str, Any]:
        removed_groups: list[str] = []
        skipped_dynamic: list[str] = []
        skipped_on_prem: list[str] = []
        skipped_unsupported: list[str] = []
        failures: list[str] = []

        for item in self._member_of(user_id):
            if not str(item.get("@odata.type") or "").endswith("group"):
                continue
            group_id = str(item.get("id") or "").strip()
            if not group_id:
                continue
            group_name = str(item.get("displayName") or group_id)
            try:
                detail = _safe_graph_call(
                    self.client.graph_request,
                    "GET",
                    f"groups/{group_id}",
                    params={
                        "$select": ",".join(
                            [
                                "id",
                                "displayName",
                                "groupTypes",
                                "mailEnabled",
                                "securityEnabled",
                                "membershipRule",
                                "onPremisesSyncEnabled",
                            ]
                        )
                    },
                )
            except UserAdminProviderError as exc:
                failures.append(f"{group_name}: {exc}")
                continue

            group_types = _compact_list(detail.get("groupTypes"))
            if detail.get("membershipRule") or "DynamicMembership" in group_types:
                skipped_dynamic.append(group_name)
                continue
            if detail.get("onPremisesSyncEnabled"):
                skipped_on_prem.append(group_name)
                continue

            is_unified = "Unified" in group_types
            is_mail = bool(detail.get("mailEnabled"))
            is_security = bool(detail.get("securityEnabled"))
            if not (is_unified or is_mail or is_security):
                skipped_unsupported.append(group_name)
                continue

            try:
                _safe_graph_call(
                    self.client.graph_request,
                    "DELETE",
                    f"groups/{group_id}/members/{user_id}/$ref",
                )
                removed_groups.append(group_name)
            except UserAdminProviderError as exc:
                failures.append(f"{group_name}: {exc}")

        if failures:
            raise UserAdminProviderError("; ".join(failures[:5]))

        return {
            "provider": "entra",
            "summary": f"Removed {len(removed_groups)} direct cloud group membership(s)",
            "before_summary": {"group_count": len(removed_groups) + len(skipped_dynamic) + len(skipped_on_prem)},
            "after_summary": {
                "removed_groups": removed_groups,
                "removed_count": len(removed_groups),
                "skipped_dynamic": skipped_dynamic,
                "skipped_on_prem": skipped_on_prem,
                "skipped_unsupported": skipped_unsupported,
            },
        }

    def remove_all_direct_licenses(self, user_id: str) -> dict[str, Any]:
        direct_licenses = [item for item in self.list_licenses(user_id) if not item.get("assigned_by_group")]
        removed: list[str] = []
        failures: list[str] = []
        for license_item in direct_licenses:
            sku_id = str(license_item.get("sku_id") or "").strip()
            label = str(license_item.get("display_name") or license_item.get("sku_part_number") or sku_id)
            if not sku_id:
                continue
            try:
                self.execute("remove_license", user_id, {"sku_id": sku_id})
                removed.append(label)
            except UserAdminProviderError as exc:
                failures.append(f"{label}: {exc}")
        if failures:
            raise UserAdminProviderError("; ".join(failures[:5]))
        return {
            "provider": "entra",
            "summary": f"Removed {len(removed)} direct license(s)",
            "before_summary": {"license_count": len(direct_licenses)},
            "after_summary": {"removed_licenses": removed, "removed_count": len(removed)},
        }

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
    exchange_powershell: ExchangeOnlinePowerShellClient | None = None

    _EXCHANGE_MAILBOX_SELECT = [
        "DisplayName",
        "UserPrincipalName",
        "PrimarySmtpAddress",
        "GrantSendOnBehalfTo",
        "GrantSendOnBehalfToWithDisplayNames",
    ]
    _EXCHANGE_MAILBOX_SCAN_SELECT = [
        "DisplayName",
        "UserPrincipalName",
        "PrimarySmtpAddress",
        "GrantSendOnBehalfTo",
    ]

    @property
    def enabled(self) -> bool:
        return self.client.configured

    @property
    def supported_actions(self) -> list[UserAdminActionType]:
        return []

    def __post_init__(self) -> None:
        if self.exchange_powershell is None:
            self.exchange_powershell = ExchangeOnlinePowerShellClient(self.client)

    def _resolve_mail_folder_labels(self, user_id: str, rows: list[dict[str, Any]]) -> dict[str, str]:
        folder_ids: list[str] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            actions = item.get("actions") if isinstance(item.get("actions"), dict) else {}
            for key in ("moveToFolder", "copyToFolder"):
                folder_id = str(actions.get(key) or "").strip()
                if folder_id and folder_id not in folder_ids:
                    folder_ids.append(folder_id)
        if not folder_ids:
            return {}

        resolved_labels: dict[str, str] = {}
        for start in range(0, len(folder_ids), 20):
            batch_folder_ids = folder_ids[start:start + 20]
            requests_payload = [
                {
                    "id": str(index),
                    "method": "GET",
                    "url": (
                        f"/users/{quote(user_id, safe='')}/mailFolders/{quote(folder_id, safe='')}"
                        "?$select=id,displayName,parentFolderId"
                    ),
                }
                for index, folder_id in enumerate(batch_folder_ids)
            ]
            try:
                batch_response = _safe_graph_call(self.client.graph_batch_request, requests_payload)
            except UserAdminProviderError:
                logger.warning("Mailbox folder label lookup failed for %s; using raw folder IDs instead", user_id)
                return {}

            responses = batch_response.get("responses") if isinstance(batch_response, dict) else []
            response_map = {str(index): folder_id for index, folder_id in enumerate(batch_folder_ids)}
            for response in responses or []:
                if not isinstance(response, dict):
                    continue
                folder_id = response_map.get(str(response.get("id") or ""))
                if not folder_id:
                    continue
                status = int(response.get("status") or 0)
                if status >= 400:
                    continue
                body = response.get("body") if isinstance(response.get("body"), dict) else {}
                label = _mail_folder_label(body)
                if label:
                    resolved_labels[folder_id] = label
        return resolved_labels

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

    def list_mailbox_rules(self, mailbox_identifier: str) -> dict[str, Any]:
        mailbox = str(mailbox_identifier or "").strip()
        if not mailbox:
            raise UserAdminProviderError("mailbox is required")
        if not self.enabled:
            return {
                "mailbox": mailbox,
                "display_name": "",
                "principal_name": mailbox,
                "primary_address": "",
                "provider_enabled": False,
                "note": "Mailbox rule lookup requires a configured Microsoft Graph connection.",
                "rule_count": 0,
                "rules": [],
            }

        user = _safe_graph_call(
            self.client.graph_request,
            "GET",
            f"users/{mailbox}",
            params={"$select": "id,displayName,mail,userPrincipalName"},
        )
        user_id = str(user.get("id") or mailbox).strip()
        rows = _safe_graph_call(
            self.client.graph_paged_get,
            f"users/{user_id}/mailFolders/inbox/messageRules",
            params={"$top": "999"},
        )
        folder_labels = self._resolve_mail_folder_labels(user_id, rows)
        rules = [
            _normalize_mailbox_rule(item, folder_labels=folder_labels)
            for item in rows
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        ]
        rules.sort(key=lambda item: (item.get("sequence") is None, item.get("sequence") or 0, str(item.get("display_name") or "").lower()))

        primary_address = str(user.get("mail") or user.get("userPrincipalName") or mailbox)
        return {
            "mailbox": mailbox,
            "display_name": str(user.get("displayName") or ""),
            "principal_name": str(user.get("userPrincipalName") or mailbox),
            "primary_address": primary_address,
            "provider_enabled": True,
            "note": "Rules are listed read-only from the mailbox Inbox." if rules else "No Inbox rules were found for this mailbox.",
            "rule_count": len(rules),
            "rules": rules,
        }

    def _exchange_delegate_permissions_for_mailbox(self, mailbox_identifier: str) -> dict[str, Any]:
        try:
            return self.exchange_powershell.get_mailbox_delegate_permissions(mailbox_identifier) if self.exchange_powershell else {}
        except ExchangeOnlinePowerShellError as exc:
            raise UserAdminProviderError(str(exc)) from exc

    def _exchange_delegate_mailboxes_for_user(self, user_identifier: str) -> dict[str, Any]:
        try:
            return self.exchange_powershell.get_delegate_mailboxes_for_user(user_identifier) if self.exchange_powershell else {}
        except ExchangeOnlinePowerShellError as exc:
            raise UserAdminProviderError(str(exc)) from exc

    def _exchange_send_as_mailboxes_for_user(self, user_identifier: str) -> dict[str, Any]:
        try:
            return self.exchange_powershell.get_send_as_mailboxes_for_user(user_identifier) if self.exchange_powershell else {}
        except AttributeError:
            return self._exchange_delegate_mailboxes_for_user(user_identifier)
        except ExchangeOnlinePowerShellError as exc:
            raise UserAdminProviderError(str(exc)) from exc

    def _exchange_full_access_mailboxes_for_user(self, user_identifier: str) -> dict[str, Any]:
        try:
            return self.exchange_powershell.get_full_access_mailboxes_for_user(user_identifier) if self.exchange_powershell else {}
        except AttributeError:
            return self._exchange_delegate_mailboxes_for_user(user_identifier)
        except ExchangeOnlinePowerShellError as exc:
            raise UserAdminProviderError(str(exc)) from exc

    def _normalize_send_as_entries(self, rows: Any) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            entry = _parse_exchange_trustee(row.get("Trustee"))
            if not _delegate_entry_identity(entry):
                continue
            entry["permission_types"] = ["send_as"]
            entries.append(entry)
        return entries

    def _normalize_full_access_entries(self, rows: Any) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            entry = _parse_exchange_trustee(row.get("User"))
            if not _delegate_entry_identity(entry):
                continue
            entry["permission_types"] = ["full_access"]
            entries.append(entry)
        return entries

    def list_mailbox_delegates(self, mailbox_identifier: str) -> dict[str, Any]:
        mailbox = str(mailbox_identifier or "").strip()
        if not mailbox:
            raise UserAdminProviderError("mailbox is required")
        if not self.enabled:
            return {
                "mailbox": mailbox,
                "display_name": "",
                "principal_name": mailbox,
                "primary_address": "",
                "provider_enabled": False,
                "supported_permission_types": list(_MAILBOX_DELEGATE_PERMISSION_TYPES),
                "permission_counts": _permission_counts([]),
                "note": "Mailbox delegation lookup requires configured Exchange and Graph connections.",
                "delegate_count": 0,
                "delegates": [],
            }

        payload = _safe_graph_call(
            self.client.exchange_admin_request,
            "Mailbox",
            anchor_mailbox=mailbox,
            cmdlet_name="Get-Mailbox",
            parameters={
                "Identity": mailbox,
                "IncludeGrantSendOnBehalfToWithDisplayNames": True,
            },
            select=self._EXCHANGE_MAILBOX_SELECT,
        )
        rows = payload.get("value") if isinstance(payload, dict) else []
        row = next((item for item in rows or [] if isinstance(item, dict)), None)
        if not row:
            raise UserAdminProviderError(f"Exchange did not return a mailbox for {mailbox}")

        mailbox_summary = _exchange_mailbox_match(row)
        send_on_behalf = _exchange_send_on_behalf_delegates(row)
        exchange_permissions = self._exchange_delegate_permissions_for_mailbox(mailbox_summary.get("principal_name") or mailbox)
        delegates = _merge_delegate_permissions(
            send_on_behalf
            + self._normalize_send_as_entries(exchange_permissions.get("send_as"))
            + self._normalize_full_access_entries(exchange_permissions.get("full_access"))
        )
        permission_counts = _permission_counts(delegates)
        return {
            "mailbox": mailbox,
            **mailbox_summary,
            "provider_enabled": True,
            "supported_permission_types": list(_MAILBOX_DELEGATE_PERMISSION_TYPES),
            "permission_counts": permission_counts,
            "note": (
                "Mailbox delegates are listed read-only from Exchange Online for Send on behalf, Send As, and Full Access."
                if delegates
                else "No Send on behalf, Send As, or Full Access delegates were found for this mailbox."
            ),
            "delegate_count": len(delegates),
            "delegates": delegates,
        }

    def list_delegate_mailboxes_for_user(
        self,
        user_identifier: str,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        user = str(user_identifier or "").strip()
        if not user:
            raise UserAdminProviderError("user is required")
        if not self.enabled:
            return {
                "user": user,
                "display_name": "",
                "principal_name": user,
                "primary_address": user,
                "provider_enabled": False,
                "supported_permission_types": list(_MAILBOX_DELEGATE_PERMISSION_TYPES),
                "permission_counts": _permission_counts([]),
                "note": "Mailbox delegation lookup requires configured Exchange and Graph connections.",
                "mailbox_count": 0,
                "scanned_mailbox_count": 0,
                "mailboxes": [],
            }

        _emit_progress(
            progress_callback,
            phase="resolving_user",
            progress_current=1,
            progress_total=4,
            progress_message="Resolving the requested user identity",
        )

        resolved_display_name = ""
        resolved_principal_name = user
        resolved_primary_address = user
        try:
            user_row = _safe_graph_call(
                self.client.graph_request,
                "GET",
                f"users/{quote(user, safe='')}",
                params={"$select": "displayName,userPrincipalName,mail"},
            )
        except UserAdminProviderError:
            user_row = {}
        if isinstance(user_row, dict):
            resolved_display_name = str(user_row.get("displayName") or "").strip()
            resolved_principal_name = str(user_row.get("userPrincipalName") or user).strip() or user
            resolved_primary_address = str(user_row.get("mail") or resolved_principal_name or user).strip() or user

        rows = _safe_graph_call(
            self.client.exchange_admin_paged_request,
            "Mailbox",
            anchor_mailbox=resolved_principal_name or user,
            cmdlet_name="Get-Mailbox",
            parameters={"ResultSize": 500},
            select=self._EXCHANGE_MAILBOX_SCAN_SELECT,
        )
        _emit_progress(
            progress_callback,
            phase="scanning_send_on_behalf",
            progress_current=2,
            progress_total=4,
            progress_message=f"Scanned {len(rows):,} Exchange mailboxes for Send on behalf",
            scanned_mailbox_count=len(rows),
        )

        normalized_user = _normalized_mailbox_identifier(user)
        matches: list[dict[str, str]] = []
        for row in rows:
            delegates = _exchange_send_on_behalf_delegates(row)
            if any(_normalized_mailbox_identifier(item.get("mail")) == normalized_user for item in delegates):
                mailbox_match = _exchange_mailbox_match(row)
                mailbox_match["permission_types"] = ["send_on_behalf"]
                matches.append(mailbox_match)

        _emit_progress(
            progress_callback,
            phase="scanning_exchange_permissions",
            progress_current=3,
            progress_total=4,
            progress_message="Checking Exchange permissions for Send As and Full Access",
            scanned_mailbox_count=len(rows),
        )
        partial_note = ""
        send_as_matches = self._exchange_send_as_mailboxes_for_user(resolved_principal_name or user)
        for row in send_as_matches.get("mailboxes") or []:
            if not isinstance(row, dict):
                continue
            mailbox_match = _exchange_mailbox_match(row)
            mailbox_match["permission_types"] = [
                str(permission_type or "").strip()
                for permission_type in row.get("PermissionTypes") or row.get("permission_types") or []
                if str(permission_type or "").strip()
            ]
            matches.append(mailbox_match)

        try:
            full_access_matches = self._exchange_full_access_mailboxes_for_user(resolved_principal_name or user)
        except UserAdminProviderError as exc:
            if "timed out" in str(exc).lower():
                partial_note = " Full Access matches are not fully included because the org-wide Full Access scan timed out."
                full_access_matches = {"mailbox_count_scanned": len(rows), "mailboxes": []}
            else:
                raise

        for row in full_access_matches.get("mailboxes") or []:
            if not isinstance(row, dict):
                continue
            mailbox_match = _exchange_mailbox_match(row)
            mailbox_match["permission_types"] = [
                str(permission_type or "").strip()
                for permission_type in row.get("PermissionTypes") or row.get("permission_types") or []
                if str(permission_type or "").strip()
            ]
            matches.append(mailbox_match)

        matches = _merge_mailbox_matches(matches)
        permission_counts = _permission_counts(matches)
        scanned_mailbox_count = max(
            len(rows),
            int(send_as_matches.get("mailbox_count_scanned") or 0),
            int(full_access_matches.get("mailbox_count_scanned") or 0),
        )
        _emit_progress(
            progress_callback,
            phase="merging_results",
            progress_current=4,
            progress_total=4,
            progress_message=f"Finalizing results across {scanned_mailbox_count:,} mailboxes",
            scanned_mailbox_count=scanned_mailbox_count,
        )
        return {
            "user": user,
            "display_name": resolved_display_name,
            "principal_name": resolved_principal_name,
            "primary_address": resolved_primary_address,
            "provider_enabled": True,
            "supported_permission_types": list(_MAILBOX_DELEGATE_PERMISSION_TYPES),
            "permission_counts": permission_counts,
            "note": (
                f"Scanned {scanned_mailbox_count:,} mailboxes for Send on behalf, Send As, and Full Access.{partial_note}"
                if matches
                else f"No delegate mailbox access was found after scanning {scanned_mailbox_count:,} mailboxes.{partial_note}"
            ),
            "mailbox_count": len(matches),
            "scanned_mailbox_count": scanned_mailbox_count,
            "mailboxes": matches,
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

    def list_mailbox_rules(self, mailbox_identifier: str) -> dict[str, Any]:
        return self.mailbox.list_mailbox_rules(mailbox_identifier)

    def list_mailbox_delegates(self, mailbox_identifier: str) -> dict[str, Any]:
        return self.mailbox.list_mailbox_delegates(mailbox_identifier)

    def list_delegate_mailboxes_for_user(self, user_identifier: str) -> dict[str, Any]:
        return self.mailbox.list_delegate_mailboxes_for_user(user_identifier)

    def list_devices(self, user_id: str) -> list[dict[str, Any]]:
        return self.device_management.list_devices(user_id)

    def execute(self, action_type: UserAdminActionType, user_id: str, params: dict[str, Any]) -> dict[str, Any]:
        provider, _provider_key = self.provider_for_action(action_type)
        return provider.execute(action_type, user_id, params)


user_admin_providers = UserAdminProviderRegistry()
