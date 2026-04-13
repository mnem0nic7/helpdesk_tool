"""Microsoft Azure and Microsoft Graph client helpers for the Azure portal."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from config import (
    AZURE_CONDITIONAL_ACCESS_LOOKBACK_DAYS,
    AZURE_COST_INTER_QUERY_DELAY_SECONDS,
    AZURE_COST_LOOKBACK_DAYS,
    AZURE_COST_MAX_RETRIES,
    AZURE_ROOT_MANAGEMENT_GROUP_ID,
    ENTRA_CLIENT_ID,
    ENTRA_CLIENT_SECRET,
    ENTRA_TENANT_ID,
)

logger = logging.getLogger(__name__)

_ARM_BASE = "https://management.azure.com"
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_LOG_ANALYTICS_BASE = "https://api.loganalytics.azure.com"
_EXCHANGE_ADMIN_BASE = "https://outlook.office365.com/adminapi/v2.0"
_ARM_SCOPE = "https://management.azure.com/.default"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_LOG_ANALYTICS_SCOPE = "https://api.loganalytics.io/.default"
_EXCHANGE_SCOPE = "https://outlook.office365.com/.default"
_TOKEN_SKEW_SECONDS = 60
_GRAPH_ROOT = "https://graph.microsoft.com"
_USER_BASE_SELECT = [
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
    "onPremisesSamAccountName",
    "onPremisesDistinguishedName",
    "lastPasswordChangeDateTime",
    "proxyAddresses",
    "assignedLicenses",
    "usageLocation",
    "employeeId",
    "employeeType",
    "preferredLanguage",
]
_USER_OPTIONAL_SELECT = ["signInActivity"]
_MANAGED_DEVICE_SELECT = [
    "id",
    "deviceName",
    "operatingSystem",
    "osVersion",
    "complianceState",
    "managementState",
    "managedDeviceOwnerType",
    "deviceEnrollmentType",
    "lastSyncDateTime",
    "azureADDeviceId",
]
_MANAGED_DEVICE_FALLBACK_SELECT = [
    "id",
    "deviceName",
    "operatingSystem",
    "osVersion",
    "complianceState",
    "managedDeviceOwnerType",
    "deviceEnrollmentType",
    "lastSyncDateTime",
    "azureADDeviceId",
]


class AzureApiError(RuntimeError):
    """Raised when an Azure REST call fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.headers = {str(key).lower(): str(value) for key, value in (headers or {}).items()}

    def retry_after_seconds(self) -> int | None:
        for header_name in (
            "x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after",
            "retry-after",
        ):
            raw_value = self.headers.get(header_name)
            if not raw_value:
                continue
            try:
                return max(1, int(float(raw_value)))
            except (TypeError, ValueError):
                continue
        return None


def _arm_resource_url(resource_path: str) -> str:
    normalized = str(resource_path or "").strip()
    if not normalized:
        return _ARM_BASE
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return f"{_ARM_BASE}{normalized}"


class AzureCostQueryCoordinator:
    """Serialize Azure Cost Management queries and prioritize export work."""

    def __init__(self, min_gap_seconds: float = 0.0) -> None:
        self._condition = threading.Condition()
        self._active_caller: str | None = None
        self._waiting_exports = 0
        self._active_export_jobs = 0
        self._min_gap_seconds = min_gap_seconds
        self._last_call_end: float | None = None

    @contextmanager
    def claim(self, caller: str):
        is_export = caller == "export"
        gap_needed = 0.0
        with self._condition:
            if is_export:
                self._waiting_exports += 1
            try:
                while self._active_caller is not None or (caller != "export" and self._waiting_exports > 0):
                    self._condition.wait()
                self._active_caller = caller
                if self._min_gap_seconds > 0 and self._last_call_end is not None:
                    elapsed = time.monotonic() - self._last_call_end
                    gap_needed = max(0.0, self._min_gap_seconds - elapsed)
            finally:
                if is_export:
                    self._waiting_exports = max(0, self._waiting_exports - 1)
        if gap_needed > 0:
            time.sleep(gap_needed)
        try:
            yield
        finally:
            with self._condition:
                self._last_call_end = time.monotonic()
                self._active_caller = None
                self._condition.notify_all()

    @contextmanager
    def export_job(self):
        with self._condition:
            self._active_export_jobs += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_export_jobs = max(0, self._active_export_jobs - 1)
                self._condition.notify_all()

    def has_active_export_job(self) -> bool:
        with self._condition:
            return self._active_export_jobs > 0


class AzureClient:
    """Thin REST client for Azure ARM, Resource Graph, Cost, Advisor, and Graph."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._tokens: dict[str, dict[str, Any]] = {}
        self._cost_query_coordinator = AzureCostQueryCoordinator(
            min_gap_seconds=AZURE_COST_INTER_QUERY_DELAY_SECONDS
        )

    @property
    def configured(self) -> bool:
        return bool(ENTRA_TENANT_ID and ENTRA_CLIENT_ID and ENTRA_CLIENT_SECRET)

    @property
    def cost_query_coordinator(self) -> AzureCostQueryCoordinator:
        return self._cost_query_coordinator

    def _get_token(self, scope: str) -> str:
        if not self.configured:
            raise AzureApiError("Azure portal is not configured: missing Entra app credentials")

        cached = self._tokens.get(scope)
        now = time.time()
        if cached and cached["expires_at"] > now + _TOKEN_SKEW_SECONDS:
            return str(cached["access_token"])

        token_url = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/oauth2/v2.0/token"
        resp = self._session.post(
            token_url,
            data={
                "client_id": ENTRA_CLIENT_ID,
                "client_secret": ENTRA_CLIENT_SECRET,
                "grant_type": "client_credentials",
                "scope": scope,
            },
            timeout=30,
        )
        if not resp.ok:
            raise AzureApiError(
                f"Azure token request failed ({resp.status_code}): {resp.text[:500]}"
            )
        payload = resp.json()
        access_token = payload.get("access_token")
        expires_in = int(payload.get("expires_in") or 3600)
        if not access_token:
            raise AzureApiError("Azure token response did not include an access token")
        self._tokens[scope] = {
            "access_token": access_token,
            "expires_at": now + expires_in,
        }
        return str(access_token)

    def _request(
        self,
        method: str,
        url: str,
        *,
        scope: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        resp = self._raw_request(
            method,
            url,
            scope=scope,
            params=params,
            json_body=json_body,
            headers=headers,
        )
        if not resp.content:
            return {}
        return resp.json()

    def _raw_request(
        self,
        method: str,
        url: str,
        *,
        scope: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        request_headers = {
            "Authorization": f"Bearer {self._get_token(scope)}",
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)
        resp = self._session.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=request_headers,
            timeout=60,
        )
        if not resp.ok:
            raise AzureApiError(
                f"{method} {url} failed ({resp.status_code}): {resp.text[:1000]}",
                status_code=resp.status_code,
                headers=dict(resp.headers),
            )
        return resp

    def _cost_management_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        caller: str = "default",
    ) -> dict[str, Any]:
        with self._cost_query_coordinator.claim(caller):
            for attempt in range(AZURE_COST_MAX_RETRIES):
                try:
                    return self._request(method, url, scope=_ARM_SCOPE, params=params, json_body=json_body)
                except AzureApiError as exc:
                    if exc.status_code == 429 and attempt < AZURE_COST_MAX_RETRIES - 1:
                        delay = exc.retry_after_seconds() or (2 ** (attempt + 1))
                        logger.warning(
                            "Azure Cost Management throttled (attempt %d/%d); retrying in %ss: %s",
                            attempt + 1,
                            AZURE_COST_MAX_RETRIES,
                            delay,
                            exc,
                        )
                        time.sleep(delay)
                        continue
                    raise
            raise AssertionError("unreachable")

    def _paged_get(
        self,
        url: str,
        *,
        scope: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url = url
        next_params = params
        while next_url:
            payload = self._request(
                "GET",
                next_url,
                scope=scope,
                params=next_params,
                headers=headers,
            )
            value = payload.get("value")
            if isinstance(value, list):
                items.extend([item for item in value if isinstance(item, dict)])
            next_url = payload.get("nextLink") or payload.get("@odata.nextLink") or ""
            next_params = None
        return items

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        if len(text) == 10:
            text = f"{text}T00:00:00+00:00"
        elif text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _cost_amount(item: dict[str, Any]) -> float:
        for key in ("totalCost", "PreTaxCost", "Cost", "cost"):
            raw_value = item.get(key)
            if raw_value in (None, ""):
                continue
            try:
                return float(raw_value)
            except (TypeError, ValueError):
                continue
        return 0.0

    @staticmethod
    def _strip_resource_id(value: str) -> str:
        return value.strip().strip("/")

    @staticmethod
    def _resource_parent_id(value: Any) -> str:
        resource_id = str(value or "").strip().strip("/")
        if not resource_id:
            return ""
        parts = resource_id.split("/")
        try:
            providers_index = parts.index("providers")
        except ValueError:
            return ""
        trailing = parts[providers_index + 1 :]
        if len(trailing) <= 3:
            return ""
        return "/" + "/".join(parts[:-2])

    @staticmethod
    def _resource_id_segment(resource_id: Any, segment_name: str) -> str:
        normalized = str(resource_id or "").strip().strip("/")
        if not normalized:
            return ""
        parts = normalized.split("/")
        segment_lower = segment_name.lower()
        for index, part in enumerate(parts[:-1]):
            if part.lower() == segment_lower:
                return parts[index + 1]
        return ""

    @staticmethod
    def _walk_path(item: Any, path: tuple[str, ...]) -> Any:
        current = item
        for segment in path:
            if not isinstance(current, dict):
                return None
            current = current.get(segment)
        return current

    @classmethod
    def _resource_id_list(
        cls,
        value: Any,
        *path_options: tuple[str, ...],
    ) -> list[str]:
        results: list[str] = []

        def append_if_present(candidate: Any) -> None:
            text = str(candidate or "").strip()
            if text and text not in results:
                results.append(text)

        if isinstance(value, str):
            append_if_present(value)
            return results
        if not isinstance(value, list):
            return results

        for item in value:
            if isinstance(item, str):
                append_if_present(item)
                continue
            if not isinstance(item, dict):
                continue
            for path in path_options:
                candidate = cls._walk_path(item, path)
                if candidate:
                    append_if_present(candidate)
                    break
        return results

    @staticmethod
    def _log_analytics_table_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
        tables = payload.get("tables")
        if not isinstance(tables, list):
            return []

        rows: list[dict[str, Any]] = []
        for table in tables:
            if not isinstance(table, dict):
                continue
            columns = table.get("columns")
            raw_rows = table.get("rows")
            if not isinstance(columns, list) or not isinstance(raw_rows, list):
                continue
            names = [str(column.get("name") or "") for column in columns if isinstance(column, dict)]
            if not names:
                continue
            for raw_row in raw_rows:
                if not isinstance(raw_row, list):
                    continue
                mapped: dict[str, Any] = {}
                for index, column_name in enumerate(names):
                    if not column_name:
                        continue
                    mapped[column_name] = raw_row[index] if index < len(raw_row) else None
                rows.append(mapped)
        return rows

    def list_subscriptions(self) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"{_ARM_BASE}/subscriptions",
            scope=_ARM_SCOPE,
            params={"api-version": "2022-12-01"},
        )
        value = payload.get("value") or []
        subscriptions: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            subscription_id = str(item.get("subscriptionId") or item.get("id") or "").strip()
            if not subscription_id:
                continue
            subscriptions.append(
                {
                    "subscription_id": subscription_id,
                    "display_name": item.get("displayName") or subscription_id,
                    "state": item.get("state") or "",
                    "tenant_id": item.get("tenantId") or "",
                    "authorization_source": item.get("authorizationSource") or "",
                }
            )
        return subscriptions

    def list_management_groups(self) -> list[dict[str, Any]]:
        if AZURE_ROOT_MANAGEMENT_GROUP_ID:
            items = self._paged_get(
                f"{_ARM_BASE}/providers/Microsoft.Management/managementGroups/{AZURE_ROOT_MANAGEMENT_GROUP_ID}/descendants",
                scope=_ARM_SCOPE,
                params={"api-version": "2020-05-01"},
            )
        else:
            items = self._paged_get(
                f"{_ARM_BASE}/providers/Microsoft.Management/managementGroups",
                scope=_ARM_SCOPE,
                params={"api-version": "2020-05-01"},
            )

        groups: list[dict[str, Any]] = []
        for item in items:
            item_type = str(item.get("type") or "")
            if "managementGroups" not in item_type:
                continue
            properties = item.get("properties") or {}
            parent = properties.get("parent") or {}
            groups.append(
                {
                    "id": item.get("id") or "",
                    "name": item.get("name") or "",
                    "display_name": properties.get("displayName") or item.get("name") or "",
                    "parent_id": parent.get("id") or "",
                    "parent_display_name": (parent.get("displayName") or ""),
                    "group_type": item_type,
                }
            )
        return groups

    def list_role_assignments(self, subscription_ids: Iterable[str]) -> list[dict[str, Any]]:
        assignments: list[dict[str, Any]] = []
        for subscription_id in subscription_ids:
            if not subscription_id:
                continue
            rows = self._paged_get(
                f"{_ARM_BASE}/subscriptions/{subscription_id}/providers/Microsoft.Authorization/roleAssignments",
                scope=_ARM_SCOPE,
                params={"api-version": "2022-04-01"},
            )
            for item in rows:
                properties = item.get("properties") or {}
                scope_value = str(properties.get("scope") or "")
                assignments.append(
                    {
                        "id": item.get("id") or "",
                        "scope": scope_value,
                        "subscription_id": subscription_id,
                        "principal_id": properties.get("principalId") or "",
                        "principal_type": properties.get("principalType") or "",
                        "role_definition_id": properties.get("roleDefinitionId") or "",
                        "role_name": properties.get("roleDefinitionName") or "",
                    }
                )
        return assignments

    def list_role_definitions(self, subscription_ids: Iterable[str]) -> list[dict[str, Any]]:
        definitions: list[dict[str, Any]] = []
        for subscription_id in subscription_ids:
            if not subscription_id:
                continue
            rows = self._paged_get(
                f"{_ARM_BASE}/subscriptions/{subscription_id}/providers/Microsoft.Authorization/roleDefinitions",
                scope=_ARM_SCOPE,
                params={"api-version": "2022-04-01"},
            )
            for item in rows:
                properties = item.get("properties") or {}
                role_id = str(item.get("id") or "")
                role_guid = str(item.get("name") or role_id.rsplit("/", 1)[-1] or "").strip()
                definitions.append(
                    {
                        "id": role_id,
                        "subscription_id": subscription_id,
                        "role_guid": role_guid,
                        "role_name": properties.get("roleName") or properties.get("displayName") or role_guid,
                        "description": properties.get("description") or "",
                    }
                )
        return definitions

    def list_reservations(self) -> list[dict[str, Any]]:
        rows = self._paged_get(
            f"{_ARM_BASE}/providers/Microsoft.Capacity/reservations",
            scope=_ARM_SCOPE,
            params={"api-version": "2022-11-01"},
        )

        now = datetime.now(timezone.utc)
        results: list[dict[str, Any]] = []
        for item in rows:
            properties = item.get("properties") or {}
            reserved_resource_type = str(properties.get("reservedResourceType") or "").strip()
            if reserved_resource_type.lower() != "virtualmachines":
                continue

            sku_payload = item.get("sku") or {}
            sku_name = ""
            if isinstance(sku_payload, dict):
                sku_name = str(sku_payload.get("name") or "").strip()
            elif sku_payload:
                sku_name = str(sku_payload).strip()
            if not sku_name:
                sku_name = str(properties.get("skuName") or "").strip() or "Unknown"

            quantity_raw = properties.get("quantity") or 0
            try:
                quantity = int(float(quantity_raw))
            except (TypeError, ValueError):
                quantity = 0
            if quantity <= 0:
                continue

            expiry = self._parse_datetime(
                properties.get("expiryDateTime")
                or properties.get("expiryDate")
            )
            if expiry and expiry <= now:
                continue

            if bool(properties.get("archived")):
                continue

            provisioning_state = str(
                properties.get("provisioningState")
                or properties.get("displayProvisioningState")
                or ""
            ).strip()
            if provisioning_state and provisioning_state.lower() not in {"succeeded"}:
                continue

            reserved_properties = properties.get("reservedResourceProperties") or {}
            applied_scopes = properties.get("appliedScopes") or []
            results.append(
                {
                    "id": item.get("id") or "",
                    "name": item.get("name") or "",
                    "display_name": properties.get("displayName") or item.get("name") or "",
                    "sku": sku_name,
                    "quantity": quantity,
                    "location": item.get("location") or "",
                    "reserved_resource_type": reserved_resource_type,
                    "applied_scope_type": properties.get("appliedScopeType") or "",
                    "display_provisioning_state": properties.get("displayProvisioningState") or "",
                    "provisioning_state": properties.get("provisioningState") or "",
                    "term": properties.get("term") or "",
                    "renew": bool(properties.get("renew")),
                    "expiry_date_time": expiry.isoformat() if expiry else "",
                    "instance_flexibility": reserved_properties.get("instanceFlexibility") or "",
                    "applied_scopes": [scope for scope in applied_scopes if isinstance(scope, str)],
                }
            )
        return results

    def list_avd_host_pools(self, subscription_ids: Iterable[str]) -> list[dict[str, Any]]:
        host_pools: list[dict[str, Any]] = []
        for subscription_id in subscription_ids:
            if not subscription_id:
                continue
            rows = self._paged_get(
                f"{_ARM_BASE}/subscriptions/{subscription_id}/providers/Microsoft.DesktopVirtualization/hostPools",
                scope=_ARM_SCOPE,
                params={"api-version": "2024-04-03"},
            )
            for item in rows:
                properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
                host_pool_id = str(item.get("id") or "").strip()
                host_pools.append(
                    {
                        "id": host_pool_id,
                        "name": str(item.get("name") or self._resource_id_segment(host_pool_id, "hostPools") or ""),
                        "subscription_id": subscription_id,
                        "resource_group": self._resource_id_segment(host_pool_id, "resourceGroups"),
                        "location": str(item.get("location") or ""),
                        "host_pool_type": str(properties.get("hostPoolType") or ""),
                        "personal_desktop_assignment_type": str(
                            properties.get("personalDesktopAssignmentType") or ""
                        ),
                        "friendly_name": str(properties.get("friendlyName") or ""),
                    }
                )
        return host_pools

    def list_avd_session_hosts(self, host_pool_resource_id: str) -> list[dict[str, Any]]:
        normalized_host_pool_id = str(host_pool_resource_id or "").strip()
        if not normalized_host_pool_id:
            return []

        rows = self._paged_get(
            f"{_arm_resource_url(normalized_host_pool_id)}/sessionHosts",
            scope=_ARM_SCOPE,
            params={"api-version": "2024-04-03"},
        )
        host_pool_name = self._resource_id_segment(normalized_host_pool_id, "hostPools")
        subscription_id = self._resource_id_segment(normalized_host_pool_id, "subscriptions")
        resource_group = self._resource_id_segment(normalized_host_pool_id, "resourceGroups")

        session_hosts: list[dict[str, Any]] = []
        for item in rows:
            properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
            session_host_id = str(item.get("id") or "").strip()
            session_host_name = self._resource_id_segment(session_host_id, "sessionHosts")
            session_hosts.append(
                {
                    "id": session_host_id,
                    "name": str(item.get("name") or ""),
                    "session_host_name": session_host_name or str(item.get("name") or "").split("/")[-1],
                    "subscription_id": subscription_id,
                    "resource_group": resource_group,
                    "location": str(item.get("location") or ""),
                    "host_pool_id": normalized_host_pool_id,
                    "host_pool_name": host_pool_name,
                    "vm_resource_id": str(properties.get("resourceId") or ""),
                    "assigned_user": str(properties.get("assignedUser") or ""),
                    "assigned_user_principal": str(properties.get("userPrincipalName") or ""),
                    "status": str(properties.get("status") or ""),
                    "allow_new_session": properties.get("allowNewSession"),
                    "last_heartbeat_utc": str(
                        properties.get("lastHeartBeat") or properties.get("lastHeartbeat") or ""
                    ),
                }
            )
        return session_hosts

    def list_resource_diagnostic_settings(self, resource_id: str) -> list[dict[str, Any]]:
        normalized_resource_id = str(resource_id or "").strip()
        if not normalized_resource_id:
            return []

        rows = self._paged_get(
            f"{_arm_resource_url(normalized_resource_id)}/providers/Microsoft.Insights/diagnosticSettings",
            scope=_ARM_SCOPE,
            params={"api-version": "2021-05-01-preview"},
        )
        settings: list[dict[str, Any]] = []
        for item in rows:
            properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
            normalized_logs: list[dict[str, Any]] = []
            for raw_log in properties.get("logs") or []:
                if not isinstance(raw_log, dict):
                    continue
                normalized_logs.append(
                    {
                        "category": str(raw_log.get("category") or ""),
                        "category_group": str(raw_log.get("categoryGroup") or ""),
                        "enabled": bool(raw_log.get("enabled")),
                    }
                )
            settings.append(
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "workspace_id": str(properties.get("workspaceId") or ""),
                    "logs": normalized_logs,
                }
            )
        return settings

    def list_resource_metrics(
        self,
        resource_id: str,
        metric_names: Iterable[str],
        *,
        start_time: datetime,
        end_time: datetime,
        interval: str = "PT1M",
    ) -> dict[str, list[dict[str, Any]]]:
        normalized_resource_id = str(resource_id or "").strip()
        requested_metric_names = [str(name or "").strip() for name in metric_names if str(name or "").strip()]
        if not normalized_resource_id or not requested_metric_names:
            return {}

        payload = self._request(
            "GET",
            f"{_arm_resource_url(normalized_resource_id)}/providers/Microsoft.Insights/metrics",
            scope=_ARM_SCOPE,
            params={
                "api-version": "2018-01-01",
                "metricnames": ",".join(requested_metric_names),
                "timespan": f"{start_time.astimezone(timezone.utc).isoformat()}/{end_time.astimezone(timezone.utc).isoformat()}",
                "interval": interval,
                "aggregation": "Average",
            },
        )

        metrics_by_name: dict[str, list[dict[str, Any]]] = {name: [] for name in requested_metric_names}
        for item in payload.get("value") or []:
            if not isinstance(item, dict):
                continue
            metric_name = str(((item.get("name") or {}) if isinstance(item.get("name"), dict) else {}).get("value") or "")
            if not metric_name:
                metric_name = str(item.get("displayDescription") or item.get("name") or "")
            if metric_name not in metrics_by_name:
                continue

            metric_points: list[dict[str, Any]] = []
            for timeseries in item.get("timeseries") or []:
                if not isinstance(timeseries, dict):
                    continue
                for raw_point in timeseries.get("data") or []:
                    if not isinstance(raw_point, dict):
                        continue
                    timestamp = str(raw_point.get("timeStamp") or "").strip()
                    average = raw_point.get("average")
                    try:
                        value = float(average) if average is not None else None
                    except (TypeError, ValueError):
                        value = None
                    if timestamp:
                        metric_points.append({"timestamp": timestamp, "value": value})

            metric_points.sort(key=lambda point: str(point.get("timestamp") or ""))
            metrics_by_name[metric_name] = metric_points

        return metrics_by_name

    def get_log_analytics_workspace(self, workspace_resource_id: str) -> dict[str, Any]:
        normalized_workspace_id = str(workspace_resource_id or "").strip()
        if not normalized_workspace_id:
            return {}

        payload = self._request(
            "GET",
            _arm_resource_url(normalized_workspace_id),
            scope=_ARM_SCOPE,
            params={"api-version": "2023-09-01"},
        )
        properties = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
        customer_id = str(properties.get("customerId") or "").strip()
        return {
            "id": str(payload.get("id") or normalized_workspace_id),
            "name": str(payload.get("name") or self._resource_id_segment(normalized_workspace_id, "workspaces") or ""),
            "subscription_id": self._resource_id_segment(normalized_workspace_id, "subscriptions"),
            "resource_group": self._resource_id_segment(normalized_workspace_id, "resourceGroups"),
            "location": str(payload.get("location") or ""),
            "customer_id": customer_id,
        }

    def query_log_analytics_workspace(
        self,
        workspace_customer_id: str,
        query: str,
        *,
        timespan: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_customer_id = str(workspace_customer_id or "").strip()
        if not normalized_customer_id:
            return []

        body: dict[str, Any] = {"query": query}
        if timespan:
            body["timespan"] = timespan
        payload = self._request(
            "POST",
            f"{_LOG_ANALYTICS_BASE}/v1/workspaces/{normalized_customer_id}/query",
            scope=_LOG_ANALYTICS_SCOPE,
            json_body=body,
            headers={"Content-Type": "application/json"},
        )
        return self._log_analytics_table_rows(payload)

    def query_resources(self, subscription_ids: list[str]) -> list[dict[str, Any]]:
        if not subscription_ids:
            return []

        query = """
Resources
| project
    id,
    name,
    type,
    kind,
    location,
    subscriptionId,
    resourceGroup,
    managedBy,
    skuName = tostring(sku.name),
    vmSize = tostring(properties.hardwareProfile.vmSize),
    vmInstanceId = tostring(properties.vmId),
    virtualMachineId = tostring(properties.virtualMachine.id),
    networkInterfaces = properties.networkProfile.networkInterfaces,
    osDiskId = tostring(properties.storageProfile.osDisk.managedDisk.id),
    dataDisks = properties.storageProfile.dataDisks,
    ipConfigurations = properties.ipConfigurations,
    tags,
    provisioningState = tostring(properties.provisioningState),
    powerState = tostring(properties.extended.instanceView.powerState.code),
    status           = tostring(properties.statusOfPrimary),
    diskSizeGB       = toint(properties.diskSizeGB),
    diskState        = tostring(properties.diskState),
    accessTier       = tostring(properties.accessTier),
    sourceResourceId = tostring(properties.creationData.sourceResourceId),
    createdTime      = tostring(coalesce(properties.timeCreated, systemData.createdAt)),
    diskIOPS         = tolong(properties.diskIOPSReadWrite),
    avdAssignedUser  = tostring(properties.assignedUser),
    avdResourceId    = tostring(properties.resourceId),
    avdUserPrincipal = tostring(properties.userPrincipalName),
    avdCreateTime    = tostring(properties.createTime)
"""
        rows: list[dict[str, Any]] = []
        skip_token: str | None = None
        while True:
            options: dict[str, Any] = {"resultFormat": "objectArray", "$top": 1000}
            if skip_token:
                options["$skipToken"] = skip_token
            payload = self._request(
                "POST",
                f"{_ARM_BASE}/providers/Microsoft.ResourceGraph/resources",
                scope=_ARM_SCOPE,
                params={"api-version": "2022-10-01"},
                json_body={
                    "subscriptions": subscription_ids,
                    "query": query,
                    "options": options,
                },
            )
            data = payload.get("data") or []
            for item in data:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    {
                        "id": item.get("id") or "",
                        "name": item.get("name") or "",
                        "resource_type": item.get("type") or "",
                        "parent_resource_id": self._resource_parent_id(item.get("id") or ""),
                        "managed_by": item.get("managedBy") or "",
                        "attached_vm_id": item.get("virtualMachineId") or "",
                        "network_interface_ids": self._resource_id_list(item.get("networkInterfaces"), ("id",)),
                        "os_disk_id": str(item.get("osDiskId") or "").strip(),
                        "data_disk_ids": self._resource_id_list(item.get("dataDisks"), ("managedDisk", "id")),
                        "public_ip_ids": self._resource_id_list(
                            item.get("ipConfigurations"),
                            ("properties", "publicIPAddress", "id"),
                        ),
                        "kind": item.get("kind") or "",
                        "location": item.get("location") or "",
                        "subscription_id": item.get("subscriptionId") or "",
                        "resource_group": item.get("resourceGroup") or "",
                        "sku_name": item.get("skuName") or "",
                        "vm_size": item.get("vmSize") or "",
                        "vm_instance_id": str(item.get("vmInstanceId") or "").strip(),
                        "state": (
                            item.get("powerState")
                            or item.get("provisioningState")
                            or item.get("status")
                            or ""
                        ),
                        "created_time": item.get("createdTime") or "",
                        "tags": item.get("tags") or {},
                        "disk_size_gb":       item.get("diskSizeGB"),
                        "disk_state":         item.get("diskState") or "",
                        "access_tier":        item.get("accessTier") or "",
                        "source_resource_id": item.get("sourceResourceId") or "",
                        "disk_iops":          item.get("diskIOPS"),
                        "avd_assigned_user":  item.get("avdAssignedUser") or "",
                        "avd_resource_id":    item.get("avdResourceId") or "",
                        "avd_user_principal": item.get("avdUserPrincipal") or "",
                        "avd_create_time":    item.get("avdCreateTime") or "",
                    }
                )
            skip_token = payload.get("$skipToken") or payload.get("skipToken")
            if not skip_token:
                break
        return rows

    def list_graph_collection(self, path: str, *, select: list[str]) -> list[dict[str, Any]]:
        url = f"{_GRAPH_BASE}/{path}"
        params = {"$select": ",".join(select), "$top": "999"}
        return self._paged_get(url, scope=_GRAPH_SCOPE, params=params)

    @staticmethod
    def _graph_url(path: str, *, api_version: str = "v1.0") -> str:
        normalized = path.lstrip("/")
        return f"{_GRAPH_ROOT}/{api_version}/{normalized}"

    def graph_request(
        self,
        method: str,
        path: str,
        *,
        api_version: str = "v1.0",
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            method,
            self._graph_url(path, api_version=api_version),
            scope=_GRAPH_SCOPE,
            params=params,
            json_body=json_body,
            headers=headers,
        )

    def graph_raw_request(
        self,
        method: str,
        path: str,
        *,
        api_version: str = "v1.0",
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        return self._raw_request(
            method,
            self._graph_url(path, api_version=api_version),
            scope=_GRAPH_SCOPE,
            params=params,
            json_body=json_body,
            headers=headers,
        )

    def graph_paged_get(
        self,
        path: str,
        *,
        api_version: str = "v1.0",
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        return self._paged_get(
            self._graph_url(path, api_version=api_version),
            scope=_GRAPH_SCOPE,
            params=params,
            headers=headers,
        )

    def list_graph_collection_custom(
        self,
        path: str,
        *,
        select: list[str],
        page_size: int | None = 999,
    ) -> list[dict[str, Any]]:
        url = f"{_GRAPH_BASE}/{path}"
        params = {"$select": ",".join(select)}
        if page_size is not None:
            params["$top"] = str(page_size)
        return self._paged_get(url, scope=_GRAPH_SCOPE, params=params)

    def get_user_drive(self, user_id: str) -> dict[str, Any]:
        return self.graph_request("GET", f"users/{user_id}/drive")

    def get_user_drive_root(self, user_id: str) -> dict[str, Any]:
        return self.graph_request("GET", f"users/{user_id}/drive/root")

    def list_user_drive_children(self, user_id: str, folder_id: str) -> list[dict[str, Any]]:
        normalized_folder_id = str(folder_id or "").strip()
        path = f"users/{user_id}/drive/root/children" if normalized_folder_id == "root" else f"users/{user_id}/drive/items/{normalized_folder_id}/children"
        return self.graph_paged_get(path, params={"$top": "999"})

    def create_user_drive_folder(self, user_id: str, parent_id: str, name: str) -> dict[str, Any]:
        normalized_parent_id = str(parent_id or "").strip()
        path = f"users/{user_id}/drive/root/children" if normalized_parent_id == "root" else f"users/{user_id}/drive/items/{normalized_parent_id}/children"
        return self.graph_request(
            "POST",
            path,
            json_body={
                "name": name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "rename",
            },
            headers={"Content-Type": "application/json"},
        )

    def graph_batch_request(self, requests_payload: list[dict[str, Any]]) -> dict[str, Any]:
        return self.graph_request(
            "POST",
            "$batch",
            json_body={"requests": requests_payload},
            headers={"Content-Type": "application/json"},
        )

    @staticmethod
    def _exchange_anchor_mailbox(anchor_mailbox: str) -> str:
        normalized = str(anchor_mailbox or "").strip()
        if not normalized:
            raise AzureApiError("Exchange Admin API requires a routing mailbox value")
        for prefix in ("AAD-UPN:", "AAD-SMTP:", "OID:", "MBX:", "APP:"):
            if normalized.startswith(prefix):
                return normalized
        return f"AAD-UPN:{normalized}"

    def exchange_admin_request(
        self,
        endpoint: str,
        *,
        anchor_mailbox: str,
        cmdlet_name: str,
        parameters: dict[str, Any] | None = None,
        select: list[str] | None = None,
        next_link: str | None = None,
    ) -> dict[str, Any]:
        normalized_endpoint = str(endpoint or "").strip().strip("/")
        if not normalized_endpoint and not next_link:
            raise AzureApiError("Exchange Admin API endpoint is required")
        params = None
        if not next_link and select:
            params = {"$select": ",".join(select)}
        url = str(next_link or "").strip() or f"{_EXCHANGE_ADMIN_BASE}/{ENTRA_TENANT_ID}/{normalized_endpoint}"
        return self._request(
            "POST",
            url,
            scope=_EXCHANGE_SCOPE,
            params=params,
            json_body={
                "CmdletInput": {
                    "CmdletName": cmdlet_name,
                    "Parameters": parameters or {},
                }
            },
            headers={
                "Content-Type": "application/json",
                "X-AnchorMailbox": self._exchange_anchor_mailbox(anchor_mailbox),
            },
        )

    def exchange_admin_paged_request(
        self,
        endpoint: str,
        *,
        anchor_mailbox: str,
        cmdlet_name: str,
        parameters: dict[str, Any] | None = None,
        select: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_link: str | None = None
        while True:
            payload = self.exchange_admin_request(
                endpoint,
                anchor_mailbox=anchor_mailbox,
                cmdlet_name=cmdlet_name,
                parameters=parameters,
                select=select,
                next_link=next_link,
            )
            value = payload.get("value")
            if isinstance(value, list):
                items.extend([item for item in value if isinstance(item, dict)])
            next_link = str(payload.get("@odata.nextLink") or "").strip() or None
            if not next_link:
                return items

    def exchange_access_token(self) -> str:
        return self._get_token(_EXCHANGE_SCOPE)

    def list_users(self) -> list[dict[str, Any]]:
        full_select = [* _USER_BASE_SELECT, *_USER_OPTIONAL_SELECT]
        try:
            return self.list_graph_collection_custom("users", select=full_select)
        except AzureApiError as exc:
            message = str(exc).lower()
            if "signinactivity" not in message and "auditlog.read.all" not in message:
                raise
            logger.warning(
                "Microsoft Graph signInActivity is unavailable for this principal; continuing directory refresh without it: %s",
                exc,
            )
            return self.list_graph_collection_custom("users", select=_USER_BASE_SELECT)

    def get_user(self, user_id: str) -> dict[str, Any]:
        full_select = [*_USER_BASE_SELECT, *_USER_OPTIONAL_SELECT]
        params = {"$select": ",".join(full_select)}
        try:
            return self.graph_request("GET", f"users/{user_id}", params=params)
        except AzureApiError as exc:
            message = str(exc).lower()
            if "signinactivity" not in message and "auditlog.read.all" not in message:
                raise
            logger.warning(
                "Microsoft Graph signInActivity is unavailable for targeted user refresh %s; continuing without it: %s",
                user_id,
                exc,
            )
            return self.graph_request("GET", f"users/{user_id}", params={"$select": ",".join(_USER_BASE_SELECT)})

    def list_subscribed_skus(self) -> list[dict[str, Any]]:
        return self.graph_paged_get(
            "subscribedSkus",
            params={"$select": "skuId,skuPartNumber"},
        )

    def list_groups(self) -> list[dict[str, Any]]:
        return self.list_graph_collection_custom(
            "groups",
            select=["id", "displayName", "mail", "securityEnabled", "groupTypes"],
        )

    def list_service_principals(self) -> list[dict[str, Any]]:
        return self.list_graph_collection_custom(
            "servicePrincipals",
            select=["id", "appId", "displayName", "servicePrincipalType", "accountEnabled"],
        )

    def list_applications(self) -> list[dict[str, Any]]:
        return self.list_graph_collection_custom(
            "applications",
            select=[
                "id",
                "appId",
                "displayName",
                "signInAudience",
                "createdDateTime",
                "publisherDomain",
                "notes",
                "passwordCredentials",
                "keyCredentials",
                "verifiedPublisher",
            ],
        )

    def list_application_owners(self, application_ids: list[str]) -> dict[str, dict[str, Any]]:
        normalized_ids = [str(item).strip() for item in application_ids if str(item).strip()]
        owners_by_application: dict[str, dict[str, Any]] = {
            application_id: {"owners": [], "owner_lookup_error": ""}
            for application_id in normalized_ids
        }
        if not normalized_ids:
            return owners_by_application

        owner_select = "id,displayName,userPrincipalName,mail,appId"
        for start in range(0, len(normalized_ids), 20):
            chunk = normalized_ids[start : start + 20]
            requests_payload = [
                {
                    "id": str(index),
                    "method": "GET",
                    "url": f"/applications/{application_id}/owners?$select={owner_select}&$top=50",
                }
                for index, application_id in enumerate(chunk, start=1)
            ]
            payload = self.graph_batch_request(requests_payload)
            responses = payload.get("responses")
            if not isinstance(responses, list):
                for application_id in chunk:
                    owners_by_application[application_id]["owner_lookup_error"] = "Missing Microsoft Graph batch response."
                continue

            request_id_to_application = {
                str(index): application_id for index, application_id in enumerate(chunk, start=1)
            }
            for response in responses:
                if not isinstance(response, dict):
                    continue
                response_id = str(response.get("id") or "")
                application_id = request_id_to_application.get(response_id)
                if not application_id:
                    continue
                status_code = int(response.get("status") or 0)
                if status_code != 200:
                    body = response.get("body") if isinstance(response.get("body"), dict) else {}
                    message = ""
                    if isinstance(body.get("error"), dict):
                        message = str(body["error"].get("message") or "")
                    owners_by_application[application_id]["owner_lookup_error"] = (
                        message or f"Microsoft Graph owner lookup returned {status_code}."
                    )
                    continue
                body = response.get("body") if isinstance(response.get("body"), dict) else {}
                value = body.get("value") if isinstance(body.get("value"), list) else []
                owners_by_application[application_id]["owners"] = [
                    item for item in value if isinstance(item, dict)
                ]
                if body.get("@odata.nextLink"):
                    owners_by_application[application_id]["owner_lookup_error"] = (
                        "Owner list truncated to the first 50 records."
                    )

        return owners_by_application

    def list_directory_roles(self) -> list[dict[str, Any]]:
        # Graph directoryRoles rejects custom page sizes, so omit $top.
        return self.list_graph_collection_custom(
            "directoryRoles",
            select=["id", "displayName", "description"],
            page_size=None,
        )

    def list_directory_role_members(self, role_ids: list[str]) -> dict[str, dict[str, Any]]:
        normalized_ids = [str(item).strip() for item in role_ids if str(item).strip()]
        members_by_role: dict[str, dict[str, Any]] = {
            role_id: {"members": [], "member_lookup_error": "", "truncated": False}
            for role_id in normalized_ids
        }
        if not normalized_ids:
            return members_by_role

        member_select = "id,displayName,description,mail,userPrincipalName,appId,accountEnabled,securityEnabled,userType"
        for start in range(0, len(normalized_ids), 20):
            chunk = normalized_ids[start : start + 20]
            requests_payload = [
                {
                    "id": str(index),
                    "method": "GET",
                    "url": f"/directoryRoles/{role_id}/members?$select={member_select}&$top=100",
                }
                for index, role_id in enumerate(chunk, start=1)
            ]
            payload = self.graph_batch_request(requests_payload)
            responses = payload.get("responses")
            if not isinstance(responses, list):
                for role_id in chunk:
                    members_by_role[role_id]["member_lookup_error"] = "Missing Microsoft Graph batch response."
                continue

            request_id_to_role = {
                str(index): role_id for index, role_id in enumerate(chunk, start=1)
            }
            for response in responses:
                if not isinstance(response, dict):
                    continue
                response_id = str(response.get("id") or "")
                role_id = request_id_to_role.get(response_id)
                if not role_id:
                    continue
                status_code = int(response.get("status") or 0)
                if status_code != 200:
                    body = response.get("body") if isinstance(response.get("body"), dict) else {}
                    message = ""
                    if isinstance(body.get("error"), dict):
                        message = str(body["error"].get("message") or "")
                    members_by_role[role_id]["member_lookup_error"] = (
                        message or f"Microsoft Graph directory role member lookup returned {status_code}."
                    )
                    continue
                body = response.get("body") if isinstance(response.get("body"), dict) else {}
                value = body.get("value") if isinstance(body.get("value"), list) else []
                members_by_role[role_id]["members"] = [
                    item for item in value if isinstance(item, dict)
                ]
                if body.get("@odata.nextLink"):
                    members_by_role[role_id]["truncated"] = True
        return members_by_role

    @staticmethod
    def _graph_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            result.append(text)
        return result

    @staticmethod
    def _graph_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return value is not None

    @classmethod
    def _normalize_conditional_access_policy(cls, item: dict[str, Any]) -> dict[str, Any]:
        conditions = item.get("conditions") if isinstance(item.get("conditions"), dict) else {}
        users = conditions.get("users") if isinstance(conditions.get("users"), dict) else {}
        applications = conditions.get("applications") if isinstance(conditions.get("applications"), dict) else {}
        grant_controls = item.get("grantControls") if isinstance(item.get("grantControls"), dict) else {}
        session_controls = item.get("sessionControls") if isinstance(item.get("sessionControls"), dict) else {}
        authentication_strength = (
            grant_controls.get("authenticationStrength")
            if isinstance(grant_controls.get("authenticationStrength"), dict)
            else {}
        )
        enabled_session_controls = [
            key
            for key, raw_value in session_controls.items()
            if cls._graph_truthy(raw_value)
        ]
        return {
            "id": str(item.get("id") or ""),
            "display_name": str(item.get("displayName") or ""),
            "state": str(item.get("state") or ""),
            "created_date_time": str(item.get("createdDateTime") or ""),
            "modified_date_time": str(item.get("modifiedDateTime") or ""),
            "include_users": cls._graph_string_list(users.get("includeUsers")),
            "exclude_users": cls._graph_string_list(users.get("excludeUsers")),
            "include_groups": cls._graph_string_list(users.get("includeGroups")),
            "exclude_groups": cls._graph_string_list(users.get("excludeGroups")),
            "include_roles": cls._graph_string_list(users.get("includeRoles")),
            "exclude_roles": cls._graph_string_list(users.get("excludeRoles")),
            "include_guests_or_external": users.get("includeGuestsOrExternalUsers") is not None,
            "exclude_guests_or_external": users.get("excludeGuestsOrExternalUsers") is not None,
            "include_applications": cls._graph_string_list(applications.get("includeApplications")),
            "exclude_applications": cls._graph_string_list(applications.get("excludeApplications")),
            "include_user_actions": cls._graph_string_list(applications.get("includeUserActions")),
            "grant_controls": cls._graph_string_list(grant_controls.get("builtInControls")),
            "custom_authentication_factors": cls._graph_string_list(grant_controls.get("customAuthenticationFactors")),
            "terms_of_use": cls._graph_string_list(grant_controls.get("termsOfUse")),
            "authentication_strength": str(authentication_strength.get("displayName") or ""),
            "session_controls": enabled_session_controls,
        }

    @staticmethod
    def _looks_like_conditional_access_audit(item: dict[str, Any]) -> bool:
        parts = [
            str(item.get("activityDisplayName") or ""),
            str(item.get("category") or ""),
            str(item.get("loggedByService") or ""),
        ]
        for target in item.get("targetResources") or []:
            if not isinstance(target, dict):
                continue
            parts.append(str(target.get("displayName") or ""))
            parts.append(str(target.get("type") or ""))
        haystack = " ".join(parts).lower()
        return "conditional access" in haystack

    @classmethod
    def _normalize_conditional_access_audit(cls, item: dict[str, Any]) -> dict[str, Any]:
        initiated_by = item.get("initiatedBy") if isinstance(item.get("initiatedBy"), dict) else {}
        initiated_user = initiated_by.get("user") if isinstance(initiated_by.get("user"), dict) else {}
        initiated_app = initiated_by.get("app") if isinstance(initiated_by.get("app"), dict) else {}
        initiated_by_type = "unknown"
        initiated_by_display_name = ""
        initiated_by_principal_name = ""
        if initiated_user:
            initiated_by_type = "user"
            initiated_by_display_name = str(initiated_user.get("displayName") or "")
            initiated_by_principal_name = str(
                initiated_user.get("userPrincipalName") or initiated_user.get("mail") or ""
            )
        elif initiated_app:
            initiated_by_type = "app"
            initiated_by_display_name = str(initiated_app.get("displayName") or "")
            initiated_by_principal_name = str(
                initiated_app.get("servicePrincipalName") or initiated_app.get("appId") or ""
            )

        target_policy_id = ""
        target_policy_name = ""
        modified_properties: list[str] = []
        for target in item.get("targetResources") or []:
            if not isinstance(target, dict):
                continue
            if not target_policy_id:
                target_policy_id = str(target.get("id") or "")
            if not target_policy_name:
                target_policy_name = str(target.get("displayName") or "")
            for prop in target.get("modifiedProperties") or []:
                if not isinstance(prop, dict):
                    continue
                property_name = str(prop.get("displayName") or prop.get("name") or "").strip()
                if property_name and property_name not in modified_properties:
                    modified_properties.append(property_name)

        return {
            "id": str(item.get("id") or ""),
            "activity_date_time": str(item.get("activityDateTime") or ""),
            "activity_display_name": str(item.get("activityDisplayName") or ""),
            "category": str(item.get("category") or ""),
            "logged_by_service": str(item.get("loggedByService") or ""),
            "result": str(item.get("result") or ""),
            "initiated_by_type": initiated_by_type,
            "initiated_by_display_name": initiated_by_display_name,
            "initiated_by_principal_name": initiated_by_principal_name,
            "target_policy_id": target_policy_id,
            "target_policy_name": target_policy_name,
            "modified_properties": modified_properties,
        }

    def list_conditional_access_policies(self) -> list[dict[str, Any]]:
        rows = self.graph_paged_get(
            "identity/conditionalAccess/policies",
            params={
                "$select": ",".join(
                    [
                        "id",
                        "displayName",
                        "createdDateTime",
                        "modifiedDateTime",
                        "state",
                        "conditions",
                        "grantControls",
                        "sessionControls",
                    ]
                ),
                "$top": "200",
            },
        )
        return [self._normalize_conditional_access_policy(item) for item in rows if isinstance(item, dict)]

    def list_conditional_access_audit_events(self, lookback_days: int | None = None) -> list[dict[str, Any]]:
        window_days = max(1, int(lookback_days or AZURE_CONDITIONAL_ACCESS_LOOKBACK_DAYS))
        window_start = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = self.graph_paged_get(
            "auditLogs/directoryAudits",
            params={
                "$filter": f"activityDateTime ge {window_start} and category eq 'Policy'",
                "$select": ",".join(
                    [
                        "id",
                        "activityDateTime",
                        "activityDisplayName",
                        "category",
                        "loggedByService",
                        "result",
                        "initiatedBy",
                        "targetResources",
                    ]
                ),
                "$orderby": "activityDateTime desc",
                "$top": "200",
            },
        )
        return [
            self._normalize_conditional_access_audit(item)
            for item in rows
            if isinstance(item, dict) and self._looks_like_conditional_access_audit(item)
        ]

    def list_managed_device_primary_users(self, device_ids: list[str]) -> dict[str, dict[str, Any]]:
        normalized_ids = [str(item).strip() for item in device_ids if str(item).strip()]
        users_by_device: dict[str, dict[str, Any]] = {
            device_id: {"users": [], "primary_user_lookup_error": "", "truncated": False}
            for device_id in normalized_ids
        }
        if not normalized_ids:
            return users_by_device

        user_select = "id,displayName,userPrincipalName,mail"
        for start in range(0, len(normalized_ids), 20):
            chunk = normalized_ids[start : start + 20]
            requests_payload = [
                {
                    "id": str(index),
                    "method": "GET",
                    "url": f"/deviceManagement/managedDevices/{device_id}/users?$select={user_select}&$top=20",
                }
                for index, device_id in enumerate(chunk, start=1)
            ]
            payload = self.graph_request(
                "POST",
                "$batch",
                api_version="beta",
                json_body={"requests": requests_payload},
                headers={"Content-Type": "application/json"},
            )
            responses = payload.get("responses")
            if not isinstance(responses, list):
                for device_id in chunk:
                    users_by_device[device_id]["primary_user_lookup_error"] = "Missing Microsoft Graph batch response."
                continue

            request_id_to_device = {
                str(index): device_id for index, device_id in enumerate(chunk, start=1)
            }
            for response in responses:
                if not isinstance(response, dict):
                    continue
                response_id = str(response.get("id") or "")
                device_id = request_id_to_device.get(response_id)
                if not device_id:
                    continue
                status_code = int(response.get("status") or 0)
                if status_code != 200:
                    body = response.get("body") if isinstance(response.get("body"), dict) else {}
                    message = ""
                    if isinstance(body.get("error"), dict):
                        message = str(body["error"].get("message") or "")
                    users_by_device[device_id]["primary_user_lookup_error"] = (
                        message or f"Microsoft Graph primary user lookup returned {status_code}."
                    )
                    continue
                body = response.get("body") if isinstance(response.get("body"), dict) else {}
                value = body.get("value") if isinstance(body.get("value"), list) else []
                users_by_device[device_id]["users"] = [
                    item for item in value if isinstance(item, dict)
                ]
                if body.get("@odata.nextLink"):
                    users_by_device[device_id]["truncated"] = True

        return users_by_device

    def list_managed_devices(self) -> list[dict[str, Any]]:
        params = {
            "$select": ",".join(_MANAGED_DEVICE_SELECT),
            "$top": "999",
        }
        try:
            rows = self.graph_paged_get(
                "deviceManagement/managedDevices",
                params=params,
            )
        except AzureApiError as exc:
            message = str(exc).lower()
            if (
                "parsing odata select and expand failed" not in message
                and "could not find a property named" not in message
            ):
                raise
            logger.warning(
                "Microsoft Graph managed-device list rejected one or more selected properties; retrying with the stable device field set: %s",
                exc,
            )
            rows = self.graph_paged_get(
                "deviceManagement/managedDevices",
                params={
                    "$select": ",".join(_MANAGED_DEVICE_FALLBACK_SELECT),
                    "$top": "999",
                },
            )
        primary_users_by_device = self.list_managed_device_primary_users(
            [str(item.get("id") or "") for item in rows if str(item.get("id") or "").strip()]
        )

        devices: list[dict[str, Any]] = []
        for item in rows:
            device_id = str(item.get("id") or "").strip()
            primary_info = primary_users_by_device.get(device_id) if device_id else {}
            primary_users = primary_info.get("users") if isinstance(primary_info.get("users"), list) else []
            devices.append(
                {
                    "id": device_id,
                    "device_name": str(item.get("deviceName") or ""),
                    "operating_system": str(item.get("operatingSystem") or ""),
                    "operating_system_version": str(item.get("osVersion") or ""),
                    "compliance_state": str(item.get("complianceState") or ""),
                    "management_state": str(item.get("managementState") or ""),
                    "owner_type": str(item.get("managedDeviceOwnerType") or item.get("ownerType") or ""),
                    "enrollment_type": str(item.get("deviceEnrollmentType") or item.get("enrollmentType") or ""),
                    "last_sync_date_time": str(item.get("lastSyncDateTime") or ""),
                    "azure_ad_device_id": str(item.get("azureADDeviceId") or ""),
                    "primary_users": [
                        {
                            "id": str(user.get("id") or ""),
                            "display_name": str(user.get("displayName") or user.get("userPrincipalName") or user.get("mail") or ""),
                            "principal_name": str(user.get("userPrincipalName") or user.get("mail") or ""),
                            "mail": str(user.get("mail") or ""),
                        }
                        for user in primary_users
                        if isinstance(user, dict)
                    ],
                    "primary_user_lookup_error": str(primary_info.get("primary_user_lookup_error") or ""),
                    "primary_user_lookup_truncated": bool(primary_info.get("truncated")),
                }
            )
        return devices

    _SECURITY_ALERT_SELECT = [
        "id", "title", "severity", "status", "category",
        "createdDateTime", "lastUpdateDateTime",
        "serviceSource", "detectionSource", "productName",
        "description", "recommendedActions",
        "evidence", "incidentId",
    ]

    def list_security_alerts(
        self,
        *,
        severities: list[str] | None = None,
        lookback_hours: int = 48,
        top: int = 200,
    ) -> list[dict[str, Any]]:
        """Poll Graph /security/alerts_v2 for recent Defender alerts."""
        since = (
            datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        filter_parts = [f"createdDateTime ge {since}"]
        if severities:
            quoted = ", ".join(f"'{s}'" for s in severities)
            filter_parts.append(f"severity in ({quoted})")
        params: dict[str, Any] = {
            "$filter": " and ".join(filter_parts),
            "$select": ",".join(self._SECURITY_ALERT_SELECT),
            "$top": str(min(top, 999)),
            "$orderby": "createdDateTime desc",
        }
        try:
            return self.graph_paged_get("security/alerts_v2", params=params)
        except AzureApiError as exc:
            logger.warning("list_security_alerts failed: %s", exc)
            return []

    @staticmethod
    def _cost_range(days: int | None = None) -> tuple[str, str]:
        lookback_days = days or AZURE_COST_LOOKBACK_DAYS
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=lookback_days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        return start.isoformat(), end.isoformat()

    def _cost_scope_paths(self, subscriptions: list[dict[str, Any]]) -> list[str]:
        if AZURE_ROOT_MANAGEMENT_GROUP_ID:
            return [f"/providers/Microsoft.Management/managementGroups/{AZURE_ROOT_MANAGEMENT_GROUP_ID}"]
        return [f"/subscriptions/{item['subscription_id']}" for item in subscriptions if item.get("subscription_id")]

    def _cost_query(
        self,
        scope_path: str,
        *,
        cost_type: str = "ActualCost",
        grouping_dimension: str | None = None,
        granularity: str = "Daily",
        lookback_days: int | None = None,
        filter_dimension: str | None = None,
        filter_values: list[str] | None = None,
        caller: str = "default",
    ) -> list[dict[str, Any]]:
        start, end = self._cost_range(lookback_days)
        dataset: dict[str, Any] = {
            "granularity": granularity,
            "aggregation": {
                "totalCost": {
                    "name": "PreTaxCost",
                    "function": "Sum",
                }
            },
        }
        if grouping_dimension:
            dataset["grouping"] = [
                {
                    "type": "Dimension",
                    "name": grouping_dimension,
                }
            ]
        if filter_dimension and filter_values:
            dataset["filter"] = {
                "dimensions": {
                    "name": filter_dimension,
                    "operator": "In",
                    "values": filter_values,
                }
            }
        payload = self._cost_management_request(
            "POST",
            f"{_arm_resource_url(scope_path)}/providers/Microsoft.CostManagement/query",
            params={"api-version": "2025-03-01"},
            json_body={
                "type": cost_type,
                "timeframe": "Custom",
                "timePeriod": {
                    "from": start,
                    "to": end,
                },
                "dataset": dataset,
            },
            caller=caller,
        )
        properties = payload.get("properties") or {}
        columns = [str(item.get("name") or "") for item in (properties.get("columns") or [])]
        rows = properties.get("rows") or []
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, list):
                continue
            item = {columns[index]: row[index] for index in range(min(len(columns), len(row)))}
            normalized.append(item)
        return normalized

    def get_cost_trend(self, subscriptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        totals: dict[str, float] = {}
        for scope_path in self._cost_scope_paths(subscriptions):
            for item in self._cost_query(scope_path, granularity="Daily"):
                raw_date = item.get("UsageDate") or item.get("date") or item.get("usageDate")
                if raw_date is None:
                    continue
                date_value = str(raw_date)
                if date_value.isdigit() and len(date_value) == 8:
                    date_value = (
                        f"{date_value[0:4]}-{date_value[4:6]}-{date_value[6:8]}"
                    )
                totals[date_value] = totals.get(date_value, 0.0) + self._cost_amount(item)
        return [
            {"date": date_key, "cost": round(cost, 2), "currency": "USD"}
            for date_key, cost in sorted(totals.items())
        ]

    def get_cost_breakdown(
        self,
        subscriptions: list[dict[str, Any]],
        grouping_dimension: str,
        *,
        limit: int | None = 20,
        cost_type: str = "ActualCost",
        force_subscription_scope: bool = False,
    ) -> list[dict[str, Any]]:
        totals: dict[str, float] = {}
        scope_paths = (
            [f"/subscriptions/{item['subscription_id']}" for item in subscriptions if item.get("subscription_id")]
            if force_subscription_scope
            else self._cost_scope_paths(subscriptions)
        )
        for scope_path in scope_paths:
            for item in self._cost_query(
                scope_path,
                cost_type=cost_type,
                grouping_dimension=grouping_dimension,
                granularity="None",
            ):
                label = str(item.get(grouping_dimension) or "Unspecified").strip() or "Unspecified"
                totals[label] = totals.get(label, 0.0) + self._cost_amount(item)
        grand_total = sum(totals.values()) or 0.0
        rows = [
            {
                "label": label,
                "amount": round(amount, 2),
                "currency": "USD",
                "share": round((amount / grand_total) if grand_total else 0.0, 4),
            }
            for label, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)
        ]
        if limit is None:
            return rows
        return rows[:limit]

    def get_cost_by_resource_ids(
        self,
        subscription_id: str,
        resource_ids: list[str],
        *,
        lookback_days: int | None = None,
        chunk_size: int = 20,
        cost_type: str = "AmortizedCost",
        caller: str = "default",
        max_attempts: int = 3,
    ) -> list[dict[str, Any]]:
        normalized_ids: list[str] = []
        seen: set[str] = set()
        for resource_id in resource_ids:
            value = str(resource_id or "").strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized_ids.append(value)

        if not subscription_id or not normalized_ids:
            return []

        totals: dict[str, float] = {}
        currencies: dict[str, str] = {}
        scope_path = f"/subscriptions/{subscription_id}"
        attempts = max(1, int(max_attempts))
        effective_chunk_size = max(1, int(chunk_size))
        for index in range(0, len(normalized_ids), effective_chunk_size):
            chunk = normalized_ids[index : index + effective_chunk_size]
            for attempt in range(attempts):
                try:
                    rows = self._cost_query(
                        scope_path,
                        cost_type=cost_type,
                        grouping_dimension="ResourceId",
                        granularity="None",
                        lookback_days=lookback_days,
                        filter_dimension="ResourceId",
                        filter_values=chunk,
                        caller=caller,
                    )
                    for item in rows:
                        label = str(item.get("ResourceId") or "Unspecified").strip() or "Unspecified"
                        totals[label] = totals.get(label, 0.0) + self._cost_amount(item)
                        currencies[label] = str(item.get("Currency") or currencies.get(label) or "USD")
                    break
                except AzureApiError as exc:
                    if exc.status_code == 429 and attempt < attempts - 1:
                        delay_seconds = exc.retry_after_seconds() or (2 ** (attempt + 1))
                        logger.warning(
                            "Azure targeted resource cost query hit throttling; retrying in %ss: %s",
                            delay_seconds,
                            exc,
                        )
                        time.sleep(delay_seconds)
                        continue
                    raise

        grand_total = sum(totals.values()) or 0.0
        return [
            {
                "label": label,
                "amount": round(amount, 2),
                "currency": currencies.get(label, "USD"),
                "share": round((amount / grand_total) if grand_total else 0.0, 4),
            }
            for label, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)
        ]

    def list_advisor_recommendations(
        self,
        subscriptions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        subscription_names = {
            item.get("subscription_id", ""): item.get("display_name", "")
            for item in subscriptions
        }
        for subscription_id in subscription_names:
            rows = self._paged_get(
                f"{_ARM_BASE}/subscriptions/{subscription_id}/providers/Microsoft.Advisor/recommendations",
                scope=_ARM_SCOPE,
                params={"api-version": "2025-01-01"},
            )
            for item in rows:
                properties = item.get("properties") or {}
                category = str(properties.get("category") or "")
                if category.lower() != "cost":
                    continue
                extended = properties.get("extendedProperties") or {}
                annual = float(
                    extended.get("annualSavingsAmount")
                    or extended.get("savingsAmount")
                    or 0.0
                )
                monthly = annual / 12 if annual else float(extended.get("monthlySavingsAmount") or 0.0)
                description = (properties.get("shortDescription") or {}).get("problem") or ""
                title = (properties.get("shortDescription") or {}).get("solution") or ""
                results.append(
                    {
                        "id": item.get("id") or "",
                        "category": category or "Cost",
                        "impact": properties.get("impact") or "",
                        "recommendation_type": properties.get("recommendationTypeId") or "",
                        "title": title or properties.get("description") or "Advisor recommendation",
                        "description": description or properties.get("description") or "",
                        "subscription_id": subscription_id,
                        "subscription_name": subscription_names.get(subscription_id, ""),
                        "resource_id": ((properties.get("resourceMetadata") or {}).get("resourceId") or ""),
                        "annual_savings": round(annual, 2),
                        "monthly_savings": round(monthly, 2),
                        "currency": str(extended.get("currency") or "USD"),
                    }
                )
        results.sort(key=lambda item: item.get("annual_savings", 0.0), reverse=True)
        return results[:50]
