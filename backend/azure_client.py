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
_ARM_SCOPE = "https://management.azure.com/.default"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_TOKEN_SKEW_SECONDS = 60
_GRAPH_ROOT = "https://graph.microsoft.com"


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
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
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
        if not resp.content:
            return {}
        return resp.json()

    def _cost_management_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
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
    diskIOPS         = tolong(properties.diskIOPSReadWrite)
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
        json_body: dict[str, Any] | None = None,
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

    def list_users(self) -> list[dict[str, Any]]:
        return self.list_graph_collection_custom(
            "users",
            select=[
                "id", "displayName", "userPrincipalName", "mail", "accountEnabled",
                "jobTitle", "department", "officeLocation", "companyName",
                "city", "country", "mobilePhone", "businessPhones",
                "createdDateTime", "userType", "onPremisesSyncEnabled",
                "onPremisesDomainName", "onPremisesNetBiosName",
                "lastPasswordChangeDateTime", "proxyAddresses",
            ],
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
            select=["id", "appId", "displayName", "signInAudience"],
        )

    def list_directory_roles(self) -> list[dict[str, Any]]:
        # Graph directoryRoles rejects custom page sizes, so omit $top.
        return self.list_graph_collection_custom(
            "directoryRoles",
            select=["id", "displayName", "description"],
            page_size=None,
        )

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
            f"{_ARM_BASE}{scope_path}/providers/Microsoft.CostManagement/query",
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
