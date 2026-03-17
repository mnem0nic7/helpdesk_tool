"""Microsoft Azure and Microsoft Graph client helpers for the Azure portal."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from config import (
    AZURE_COST_LOOKBACK_DAYS,
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


class AzureApiError(RuntimeError):
    """Raised when an Azure REST call fails."""


class AzureClient:
    """Thin REST client for Azure ARM, Resource Graph, Cost, Advisor, and Graph."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._tokens: dict[str, dict[str, Any]] = {}

    @property
    def configured(self) -> bool:
        return bool(ENTRA_TENANT_ID and ENTRA_CLIENT_ID and ENTRA_CLIENT_SECRET)

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
            raise AzureApiError(f"{method} {url} failed ({resp.status_code}): {resp.text[:1000]}")
        if not resp.content:
            return {}
        return resp.json()

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
    def _strip_resource_id(value: str) -> str:
        return value.strip().strip("/")

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
    tags,
    provisioningState = tostring(properties.provisioningState),
    powerState = tostring(properties.extended.instanceView.powerState.code),
    status = tostring(properties.statusOfPrimary)
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
                        "kind": item.get("kind") or "",
                        "location": item.get("location") or "",
                        "subscription_id": item.get("subscriptionId") or "",
                        "resource_group": item.get("resourceGroup") or "",
                        "state": (
                            item.get("powerState")
                            or item.get("provisioningState")
                            or item.get("status")
                            or ""
                        ),
                        "tags": item.get("tags") or {},
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
            select=["id", "displayName", "userPrincipalName", "mail", "accountEnabled"],
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
        grouping_dimension: str | None = None,
        granularity: str = "Daily",
        lookback_days: int | None = None,
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
        payload = self._request(
            "POST",
            f"{_ARM_BASE}{scope_path}/providers/Microsoft.CostManagement/query",
            scope=_ARM_SCOPE,
            params={"api-version": "2025-03-01"},
            json_body={
                "type": "ActualCost",
                "timeframe": "Custom",
                "timePeriod": {
                    "from": start,
                    "to": end,
                },
                "dataset": dataset,
            },
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
                totals[date_value] = totals.get(date_value, 0.0) + float(item.get("totalCost") or 0.0)
        return [
            {"date": date_key, "cost": round(cost, 2), "currency": "USD"}
            for date_key, cost in sorted(totals.items())
        ]

    def get_cost_breakdown(
        self,
        subscriptions: list[dict[str, Any]],
        grouping_dimension: str,
    ) -> list[dict[str, Any]]:
        totals: dict[str, float] = {}
        for scope_path in self._cost_scope_paths(subscriptions):
            for item in self._cost_query(scope_path, grouping_dimension=grouping_dimension, granularity="None"):
                label = str(item.get(grouping_dimension) or "Unspecified").strip() or "Unspecified"
                totals[label] = totals.get(label, 0.0) + float(item.get("totalCost") or 0.0)
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
        return rows[:20]

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
