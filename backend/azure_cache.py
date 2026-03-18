"""SQLite-backed cache for the Azure portal datasets."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from azure_client import AzureApiError, AzureClient
from config import (
    AZURE_COST_LOOKBACK_DAYS,
    AZURE_COST_REFRESH_MINUTES,
    AZURE_DIRECTORY_REFRESH_MINUTES,
    AZURE_INVENTORY_REFRESH_MINUTES,
    DATA_DIR,
)

logger = logging.getLogger(__name__)

_DATASET_CONFIG: dict[str, dict[str, Any]] = {
    "inventory": {
        "label": "Inventory",
        "interval_minutes": AZURE_INVENTORY_REFRESH_MINUTES,
        "snapshots": ["subscriptions", "management_groups", "resources", "role_assignments", "reservations"],
    },
    "directory": {
        "label": "Identity",
        "interval_minutes": AZURE_DIRECTORY_REFRESH_MINUTES,
        "snapshots": ["users", "groups", "service_principals", "applications", "directory_roles"],
    },
    "cost": {
        "label": "Cost",
        "interval_minutes": AZURE_COST_REFRESH_MINUTES,
        "snapshots": [
            "cost_summary",
            "cost_trend",
            "cost_by_service",
            "cost_by_subscription",
            "cost_by_resource_group",
            "cost_by_resource_id",
            "cost_by_resource_id_status",
            "advisor",
        ],
    },
}


class AzureCache:
    """Thread-safe Azure snapshot cache with periodic background refresh."""

    def __init__(self, db_path: str | None = None) -> None:
        self._client = AzureClient()
        self._db_path = db_path or os.path.join(DATA_DIR, "azure_cache.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._snapshots: dict[str, Any] = {}
        self._dataset_state: dict[str, dict[str, Any]] = {
            key: {
                "key": key,
                "label": config["label"],
                "configured": self._client.configured,
                "refreshing": False,
                "interval_minutes": int(config["interval_minutes"]),
                "item_count": 0,
                "last_refresh": None,
                "error": None,
            }
            for key, config in _DATASET_CONFIG.items()
        }
        self._initialized = False
        self._refreshing = False
        self._bg_task: asyncio.Task[None] | None = None
        self._start_called = False
        self._init_db()
        self._load_from_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_status (
                    dataset_key TEXT PRIMARY KEY,
                    updated_at TEXT,
                    error TEXT
                )
                """
            )
            conn.commit()

    def _load_from_db(self) -> None:
        with self._conn() as conn:
            for row in conn.execute("SELECT name, payload, updated_at FROM snapshots"):
                try:
                    self._snapshots[str(row["name"])] = json.loads(str(row["payload"]))
                except json.JSONDecodeError:
                    logger.warning("Skipping invalid Azure snapshot %s", row["name"])
            for row in conn.execute("SELECT dataset_key, updated_at, error FROM dataset_status"):
                dataset_key = str(row["dataset_key"])
                if dataset_key in self._dataset_state:
                    self._dataset_state[dataset_key]["last_refresh"] = row["updated_at"]
                    self._dataset_state[dataset_key]["error"] = row["error"] or None
        for dataset_key in self._dataset_state:
            self._dataset_state[dataset_key]["item_count"] = self._dataset_item_count(dataset_key)
        self._initialized = any(state["last_refresh"] for state in self._dataset_state.values())

    def _persist_snapshot(self, name: str, payload: Any) -> None:
        serialized = json.dumps(payload)
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO snapshots (name, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (name, serialized, updated_at),
            )
            conn.commit()

    def _persist_dataset_status(self, dataset_key: str, updated_at: str | None, error: str | None) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO dataset_status (dataset_key, updated_at, error)
                VALUES (?, ?, ?)
                ON CONFLICT(dataset_key) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    error = excluded.error
                """,
                (dataset_key, updated_at, error or ""),
            )
            conn.commit()

    def _dataset_item_count(self, dataset_key: str) -> int:
        count = 0
        for snapshot_name in _DATASET_CONFIG[dataset_key]["snapshots"]:
            payload = self._snapshots.get(snapshot_name)
            if isinstance(payload, list):
                count += len(payload)
            elif payload:
                count += 1
        return count

    def _set_dataset_status(self, dataset_key: str, *, updated_at: str | None, error: str | None) -> None:
        self._dataset_state[dataset_key]["configured"] = self._client.configured
        self._dataset_state[dataset_key]["last_refresh"] = updated_at
        self._dataset_state[dataset_key]["error"] = error
        self._dataset_state[dataset_key]["item_count"] = self._dataset_item_count(dataset_key)
        self._persist_dataset_status(dataset_key, updated_at, error)

    async def start_background_refresh(self) -> None:
        if self._bg_task and not self._bg_task.done():
            return
        self._start_called = True
        loop = asyncio.get_running_loop()
        self._bg_task = loop.create_task(self._background_loop())

    async def stop_background_refresh(self) -> None:
        if not self._bg_task:
            return
        self._bg_task.cancel()
        try:
            await self._bg_task
        except asyncio.CancelledError:
            pass
        self._bg_task = None

    async def _background_loop(self) -> None:
        while True:
            try:
                await asyncio.get_running_loop().run_in_executor(None, self.refresh_due_datasets)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Azure background refresh failed")
            await asyncio.sleep(60)

    @property
    def configured(self) -> bool:
        return self._client.configured

    def _snapshot(self, name: str) -> Any:
        with self._lock:
            value = self._snapshots.get(name)
            return deepcopy(value)

    def _update_snapshots(self, snapshot_map: dict[str, Any]) -> None:
        with self._lock:
            for name, payload in snapshot_map.items():
                self._snapshots[name] = payload
        for name, payload in snapshot_map.items():
            self._persist_snapshot(name, payload)

    def status(self) -> dict[str, Any]:
        with self._lock:
            datasets = [dict(item) for item in self._dataset_state.values()]
            last_refreshes = [item["last_refresh"] for item in datasets if item["last_refresh"]]
            return {
                "configured": self._client.configured,
                "initialized": self._initialized,
                "refreshing": self._refreshing,
                "last_refresh": max(last_refreshes) if last_refreshes else None,
                "datasets": datasets,
            }

    def _dataset_due(self, dataset_key: str) -> bool:
        state = self._dataset_state[dataset_key]
        if not state["last_refresh"]:
            return True
        last_refresh = datetime.fromisoformat(str(state["last_refresh"]).replace("Z", "+00:00"))
        interval = timedelta(minutes=int(state["interval_minutes"]))
        return datetime.now(timezone.utc) - last_refresh >= interval

    def refresh_due_datasets(self) -> None:
        if not self._client.configured:
            with self._lock:
                self._initialized = True
                for dataset_key in self._dataset_state:
                    self._dataset_state[dataset_key]["configured"] = False
                    if not self._dataset_state[dataset_key]["error"]:
                        self._dataset_state[dataset_key]["error"] = "Azure client credentials are not configured"
            return

        due = [key for key in _DATASET_CONFIG if self._dataset_due(key)]
        if not due:
            return
        self.refresh_datasets(due)

    def trigger_refresh(self) -> None:
        self.refresh_datasets(list(_DATASET_CONFIG.keys()), force=True)

    def refresh_datasets(self, dataset_keys: list[str], *, force: bool = False) -> None:
        del force  # kept for parity with other cache interfaces
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True
            for dataset_key in dataset_keys:
                if dataset_key in self._dataset_state:
                    self._dataset_state[dataset_key]["refreshing"] = True

        try:
            if "inventory" in dataset_keys:
                self._refresh_inventory()
            if "directory" in dataset_keys:
                self._refresh_directory()
            if "cost" in dataset_keys:
                self._refresh_cost()
            with self._lock:
                self._initialized = True
        finally:
            with self._lock:
                self._refreshing = False
                for dataset_key in dataset_keys:
                    if dataset_key in self._dataset_state:
                        self._dataset_state[dataset_key]["refreshing"] = False

    def _refresh_inventory(self) -> None:
        try:
            subscriptions = self._client.list_subscriptions()
            sub_name_by_id = {
                item["subscription_id"]: item["display_name"]
                for item in subscriptions
            }
            management_groups: list[dict[str, Any]] = []
            try:
                management_groups = self._client.list_management_groups()
            except AzureApiError as exc:
                message = str(exc)
                if "managementGroups/read" in message or "AuthorizationFailed" in message:
                    logger.warning(
                        "Azure management groups unavailable for this principal; continuing inventory refresh without them: %s",
                        exc,
                    )
                else:
                    raise
            resources = self._client.query_resources(list(sub_name_by_id))
            for item in resources:
                item["subscription_name"] = sub_name_by_id.get(item.get("subscription_id", ""), "")
            role_assignments = self._client.list_role_assignments(list(sub_name_by_id))
            reservations: list[dict[str, Any]] = []
            reservation_status = {"available": False, "error": None}
            try:
                reservations = self._client.list_reservations()
                reservation_status = {"available": True, "error": None}
            except AzureApiError as exc:
                logger.warning(
                    "Azure reservations unavailable for this principal; continuing inventory refresh without them: %s",
                    exc,
                )
                reservation_status = {"available": False, "error": str(exc)}
            self._update_snapshots(
                {
                    "subscriptions": subscriptions,
                    "management_groups": management_groups,
                    "resources": resources,
                    "role_assignments": role_assignments,
                    "reservations": reservations,
                    "reservation_status": reservation_status,
                }
            )
            updated_at = datetime.now(timezone.utc).isoformat()
            self._set_dataset_status("inventory", updated_at=updated_at, error=None)
        except AzureApiError as exc:
            logger.warning("Azure inventory refresh failed: %s", exc)
            self._set_dataset_status("inventory", updated_at=self._dataset_state["inventory"]["last_refresh"], error=str(exc))

    @staticmethod
    def _normalize_user(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id") or "",
            "display_name": item.get("displayName") or "",
            "object_type": "user",
            "principal_name": item.get("userPrincipalName") or "",
            "mail": item.get("mail") or "",
            "enabled": item.get("accountEnabled"),
            "app_id": "",
            "extra": {},
        }

    @staticmethod
    def _normalize_group(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id") or "",
            "display_name": item.get("displayName") or "",
            "object_type": "group",
            "principal_name": "",
            "mail": item.get("mail") or "",
            "enabled": item.get("securityEnabled"),
            "app_id": "",
            "extra": {
                "group_types": ",".join(item.get("groupTypes") or []),
            },
        }

    @staticmethod
    def _normalize_service_principal(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id") or "",
            "display_name": item.get("displayName") or "",
            "object_type": "enterprise_app",
            "principal_name": "",
            "mail": "",
            "enabled": item.get("accountEnabled"),
            "app_id": item.get("appId") or "",
            "extra": {
                "service_principal_type": item.get("servicePrincipalType") or "",
            },
        }

    @staticmethod
    def _normalize_application(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id") or "",
            "display_name": item.get("displayName") or "",
            "object_type": "app_registration",
            "principal_name": "",
            "mail": "",
            "enabled": None,
            "app_id": item.get("appId") or "",
            "extra": {
                "sign_in_audience": item.get("signInAudience") or "",
            },
        }

    @staticmethod
    def _normalize_directory_role(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id") or "",
            "display_name": item.get("displayName") or "",
            "object_type": "directory_role",
            "principal_name": "",
            "mail": "",
            "enabled": None,
            "app_id": "",
            "extra": {
                "description": item.get("description") or "",
            },
        }

    def _refresh_directory(self) -> None:
        try:
            users = [self._normalize_user(item) for item in self._client.list_users()]
            groups = [self._normalize_group(item) for item in self._client.list_groups()]
            service_principals = [
                self._normalize_service_principal(item)
                for item in self._client.list_service_principals()
            ]
            applications = [
                self._normalize_application(item)
                for item in self._client.list_applications()
            ]
            directory_roles = [
                self._normalize_directory_role(item)
                for item in self._client.list_directory_roles()
            ]
            self._update_snapshots(
                {
                    "users": users,
                    "groups": groups,
                    "service_principals": service_principals,
                    "applications": applications,
                    "directory_roles": directory_roles,
                }
            )
            updated_at = datetime.now(timezone.utc).isoformat()
            self._set_dataset_status("directory", updated_at=updated_at, error=None)
        except AzureApiError as exc:
            logger.warning("Azure directory refresh failed: %s", exc)
            self._set_dataset_status("directory", updated_at=self._dataset_state["directory"]["last_refresh"], error=str(exc))

    def _refresh_cost(self) -> None:
        try:
            subscriptions = self._snapshot("subscriptions") or self._client.list_subscriptions()
            if not subscriptions:
                raise AzureApiError("No Azure subscriptions were returned for cost analysis")
            trend = self._client.get_cost_trend(subscriptions)
            by_service = self._client.get_cost_breakdown(subscriptions, "ServiceName")
            by_subscription = self._client.get_cost_breakdown(subscriptions, "SubscriptionName")
            by_resource_group = self._client.get_cost_breakdown(subscriptions, "ResourceGroupName")
            by_resource_id: list[dict[str, Any]] = []
            by_resource_id_status = {"available": False, "error": None}
            for attempt in range(3):
                try:
                    by_resource_id = self._client.get_cost_breakdown(
                        subscriptions,
                        "ResourceId",
                        limit=None,
                    )
                    by_resource_id_status = {"available": True, "error": None}
                    break
                except AzureApiError as exc:
                    message = str(exc)
                    if exc.status_code == 429 and attempt < 2:
                        delay_seconds = exc.retry_after_seconds() or (2 * (attempt + 1))
                        logger.warning(
                            "Azure cost by resource id hit throttling; retrying in %ss: %s",
                            delay_seconds,
                            exc,
                        )
                        time.sleep(delay_seconds)
                        continue
                    logger.warning(
                        "Azure cost by resource id is unavailable for this principal; continuing cost refresh without it: %s",
                        exc,
                    )
                    by_resource_id_status = {"available": False, "error": message}
                    break
            advisor = self._client.list_advisor_recommendations(subscriptions)
            summary = {
                "lookback_days": AZURE_COST_LOOKBACK_DAYS,
                "total_cost": round(sum(float(item.get("cost") or 0.0) for item in trend), 2),
                "currency": "USD",
                "top_service": (by_service[0]["label"] if by_service else ""),
                "top_subscription": (by_subscription[0]["label"] if by_subscription else ""),
                "top_resource_group": (by_resource_group[0]["label"] if by_resource_group else ""),
                "recommendation_count": len(advisor),
                "potential_monthly_savings": round(
                    sum(float(item.get("monthly_savings") or 0.0) for item in advisor),
                    2,
                ),
            }
            self._update_snapshots(
                {
                    "cost_summary": summary,
                    "cost_trend": trend,
                    "cost_by_service": by_service,
                    "cost_by_subscription": by_subscription,
                    "cost_by_resource_group": by_resource_group,
                    "cost_by_resource_id": by_resource_id,
                    "cost_by_resource_id_status": by_resource_id_status,
                    "advisor": advisor,
                }
            )
            updated_at = datetime.now(timezone.utc).isoformat()
            self._set_dataset_status("cost", updated_at=updated_at, error=None)
        except AzureApiError as exc:
            logger.warning("Azure cost refresh failed: %s", exc)
            self._set_dataset_status("cost", updated_at=self._dataset_state["cost"]["last_refresh"], error=str(exc))

    def get_overview(self) -> dict[str, Any]:
        subscriptions = self._snapshot("subscriptions") or []
        management_groups = self._snapshot("management_groups") or []
        resources = self._snapshot("resources") or []
        role_assignments = self._snapshot("role_assignments") or []
        users = self._snapshot("users") or []
        groups = self._snapshot("groups") or []
        service_principals = self._snapshot("service_principals") or []
        applications = self._snapshot("applications") or []
        directory_roles = self._snapshot("directory_roles") or []
        cost_summary = self._snapshot("cost_summary") or {
            "lookback_days": AZURE_COST_LOOKBACK_DAYS,
            "total_cost": 0.0,
            "currency": "USD",
            "top_service": "",
            "top_subscription": "",
            "top_resource_group": "",
            "recommendation_count": 0,
            "potential_monthly_savings": 0.0,
        }
        status = self.status()
        return {
            "subscriptions": len(subscriptions),
            "management_groups": len(management_groups),
            "resources": len(resources),
            "role_assignments": len(role_assignments),
            "users": len(users),
            "groups": len(groups),
            "enterprise_apps": len(service_principals),
            "app_registrations": len(applications),
            "directory_roles": len(directory_roles),
            "cost": cost_summary,
            "datasets": status["datasets"],
            "last_refresh": status["last_refresh"],
        }

    def list_resources(
        self,
        *,
        search: str = "",
        subscription_id: str = "",
        resource_group: str = "",
        resource_type: str = "",
        location: str = "",
        state: str = "",
        tag_key: str = "",
        tag_value: str = "",
    ) -> dict[str, Any]:
        all_resources = self._snapshot("resources") or []
        search_lower = search.strip().lower()
        subscription_filter = subscription_id.strip().lower()
        group_filter = resource_group.strip().lower()
        type_filter = resource_type.strip().lower()
        location_filter = location.strip().lower()
        state_filter = state.strip().lower()
        tag_key_filter = tag_key.strip().lower()
        tag_value_filter = tag_value.strip().lower()

        matched: list[dict[str, Any]] = []
        for item in all_resources:
            if search_lower:
                haystack = " ".join(
                    str(item.get(field) or "")
                    for field in ("name", "resource_type", "subscription_name", "resource_group", "location", "sku_name", "vm_size")
                ).lower()
                haystack += " " + " ".join(
                    f"{key}:{value}" for key, value in (item.get("tags") or {}).items()
                ).lower()
                if search_lower not in haystack:
                    continue
            if subscription_filter and str(item.get("subscription_id") or "").lower() != subscription_filter:
                continue
            if group_filter and str(item.get("resource_group") or "").lower() != group_filter:
                continue
            if type_filter and str(item.get("resource_type") or "").lower() != type_filter:
                continue
            if location_filter and str(item.get("location") or "").lower() != location_filter:
                continue
            if state_filter and state_filter not in str(item.get("state") or "").lower():
                continue
            if tag_key_filter:
                tags = {str(key).lower(): str(value or "").lower() for key, value in (item.get("tags") or {}).items()}
                if tag_key_filter not in tags:
                    continue
                if tag_value_filter and tags.get(tag_key_filter, "") != tag_value_filter:
                    continue
            matched.append(item)
        return {
            "resources": matched,
            "matched_count": len(matched),
            "total_count": len(all_resources),
        }

    @staticmethod
    def _is_virtual_machine(item: dict[str, Any]) -> bool:
        return str(item.get("resource_type") or "").lower() == "microsoft.compute/virtualmachines"

    @staticmethod
    def _vm_size(item: dict[str, Any]) -> str:
        return str(item.get("vm_size") or item.get("sku_name") or "").strip() or "Unknown"

    @staticmethod
    def _vm_power_state(item: dict[str, Any]) -> str:
        raw = str(item.get("state") or "").strip()
        if not raw:
            return "Unknown"
        value = raw.split("/", 1)[-1] if "/" in raw else raw
        value = value.replace("_", " ").replace("-", " ").strip()
        return value.title() if value else "Unknown"

    @staticmethod
    def _normalize_resource_id(value: Any) -> str:
        return str(value or "").strip().strip("/").lower()

    @staticmethod
    def _resource_display_name(value: Any) -> str:
        text = str(value or "").strip().strip("/")
        if not text:
            return ""
        return text.split("/")[-1]

    def list_virtual_machines(
        self,
        *,
        search: str = "",
        subscription_id: str = "",
        resource_group: str = "",
        location: str = "",
        state: str = "",
        size: str = "",
    ) -> dict[str, Any]:
        all_resources = self._snapshot("resources") or []
        all_vms = [item for item in all_resources if self._is_virtual_machine(item)]

        search_lower = search.strip().lower()
        subscription_filter = subscription_id.strip().lower()
        group_filter = resource_group.strip().lower()
        location_filter = location.strip().lower()
        state_filter = state.strip().lower()
        size_filter = size.strip().lower()

        matched: list[dict[str, Any]] = []
        for item in all_vms:
            vm_size = self._vm_size(item)
            power_state = self._vm_power_state(item)
            if search_lower:
                haystack = " ".join(
                    [
                        str(item.get("name") or ""),
                        str(item.get("subscription_name") or ""),
                        str(item.get("resource_group") or ""),
                        str(item.get("location") or ""),
                        vm_size,
                        power_state,
                    ]
                ).lower()
                haystack += " " + " ".join(
                    f"{key}:{value}" for key, value in (item.get("tags") or {}).items()
                ).lower()
                if search_lower not in haystack:
                    continue
            if subscription_filter and str(item.get("subscription_id") or "").lower() != subscription_filter:
                continue
            if group_filter and str(item.get("resource_group") or "").lower() != group_filter:
                continue
            if location_filter and str(item.get("location") or "").lower() != location_filter:
                continue
            if state_filter and state_filter not in power_state.lower():
                continue
            if size_filter and size_filter != vm_size.lower():
                continue

            row = dict(item)
            row["size"] = vm_size
            row["power_state"] = power_state
            matched.append(row)

        by_size_counts: dict[str, int] = defaultdict(int)
        by_state_counts: dict[str, int] = defaultdict(int)
        running_vms = 0
        deallocated_vms = 0
        for item in all_vms:
            vm_size = self._vm_size(item)
            power_state = self._vm_power_state(item)
            by_size_counts[vm_size] += 1
            by_state_counts[power_state] += 1
            if power_state.lower() == "running":
                running_vms += 1
            if power_state.lower() == "deallocated":
                deallocated_vms += 1

        by_size = self.get_vm_coverage_by_sku()
        by_state = [
            {"label": label, "count": count}
            for label, count in sorted(by_state_counts.items(), key=lambda item: (-item[1], item[0].lower()))
        ]
        reservation_status = self._get_reservation_status()

        return {
            "vms": matched,
            "matched_count": len(matched),
            "total_count": len(all_vms),
            "summary": {
                "total_vms": len(all_vms),
                "running_vms": running_vms,
                "deallocated_vms": deallocated_vms,
                "distinct_sizes": len(by_size_counts),
            },
            "by_size": by_size,
            "by_state": by_state,
            "reservation_data_available": bool(reservation_status["available"]),
            "reservation_error": reservation_status.get("error"),
        }

    def list_directory_objects(self, snapshot_name: str, *, search: str = "") -> list[dict[str, Any]]:
        rows = self._snapshot(snapshot_name) or []
        search_lower = search.strip().lower()
        if not search_lower:
            return rows
        result: list[dict[str, Any]] = []
        for item in rows:
            haystack = " ".join(
                [
                    str(item.get("display_name") or ""),
                    str(item.get("principal_name") or ""),
                    str(item.get("mail") or ""),
                    str(item.get("app_id") or ""),
                    " ".join(f"{key}:{value}" for key, value in (item.get("extra") or {}).items()),
                ]
            ).lower()
            if search_lower in haystack:
                result.append(item)
        return result

    def get_cost_summary(self) -> dict[str, Any]:
        return self._snapshot("cost_summary") or {
            "lookback_days": AZURE_COST_LOOKBACK_DAYS,
            "total_cost": 0.0,
            "currency": "USD",
            "top_service": "",
            "top_subscription": "",
            "top_resource_group": "",
            "recommendation_count": 0,
            "potential_monthly_savings": 0.0,
        }

    def get_cost_trend(self) -> list[dict[str, Any]]:
        return self._snapshot("cost_trend") or []

    def get_cost_breakdown(self, group_by: str) -> list[dict[str, Any]]:
        snapshot_name = {
            "service": "cost_by_service",
            "subscription": "cost_by_subscription",
            "resource_group": "cost_by_resource_group",
        }.get(group_by, "cost_by_service")
        return self._snapshot(snapshot_name) or []

    def get_advisor(self) -> list[dict[str, Any]]:
        return self._snapshot("advisor") or []

    def _get_resource_cost_status(self) -> dict[str, Any]:
        status = self._snapshot("cost_by_resource_id_status")
        if isinstance(status, dict):
            return {
                "available": bool(status.get("available")),
                "error": status.get("error"),
            }
        return {"available": False, "error": None}

    def _resource_cost_index(self) -> dict[str, dict[str, Any]]:
        rows = self._snapshot("cost_by_resource_id") or []
        index: dict[str, dict[str, Any]] = {}
        for item in rows:
            key = self._normalize_resource_id(item.get("label"))
            if key:
                index[key] = item
        return index

    def _targeted_resource_cost_index(
        self,
        resources: list[dict[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        resource_ids_by_subscription: dict[str, list[str]] = defaultdict(list)
        for item in resources:
            subscription_id = str(item.get("subscription_id") or "").strip()
            resource_id = str(item.get("id") or "").strip()
            if not subscription_id or not resource_id:
                continue
            resource_ids_by_subscription[subscription_id].append(resource_id)

        if not resource_ids_by_subscription:
            return {}, {"available": False, "error": "No subscription-scoped resources are available for targeted cost lookup"}

        rows: list[dict[str, Any]] = []
        try:
            for subscription_id, resource_ids in resource_ids_by_subscription.items():
                rows.extend(self._client.get_cost_by_resource_ids(subscription_id, resource_ids))
        except AzureApiError as exc:
            logger.warning(
                "Azure targeted resource cost query is unavailable for VM detail: %s",
                exc,
            )
            return {}, {"available": False, "error": str(exc)}

        index: dict[str, dict[str, Any]] = {}
        for item in rows:
            key = self._normalize_resource_id(item.get("label"))
            if key:
                index[key] = item
        return index, {"available": True, "error": None}

    def _get_reservation_status(self) -> dict[str, Any]:
        status = self._snapshot("reservation_status")
        if isinstance(status, dict):
            return {
                "available": bool(status.get("available")),
                "error": status.get("error"),
            }
        return {"available": False, "error": None}

    @staticmethod
    def _normalize_region(value: Any) -> str:
        region = str(value or "").strip().lower()
        return region or "unknown"

    def get_vm_reservations_by_sku(self) -> list[dict[str, Any]]:
        reservations = self._snapshot("reservations") or []
        counts: dict[str, int] = defaultdict(int)
        for item in reservations:
            sku = str(item.get("sku") or "").strip() or "Unknown"
            try:
                quantity = int(item.get("quantity") or 0)
            except (TypeError, ValueError):
                quantity = 0
            if quantity <= 0:
                continue
            counts[sku] += quantity

        return [
            {"sku": sku, "reserved_instance_count": count}
            for sku, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
        ]

    def get_vm_reservations_by_sku_region(self) -> list[dict[str, Any]]:
        reservations = self._snapshot("reservations") or []
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for item in reservations:
            sku = str(item.get("sku") or "").strip() or "Unknown"
            region = self._normalize_region(item.get("location"))
            try:
                quantity = int(item.get("quantity") or 0)
            except (TypeError, ValueError):
                quantity = 0
            if quantity <= 0:
                continue
            counts[(sku, region)] += quantity

        return [
            {
                "sku": sku,
                "region": region,
                "reserved_instance_count": count,
            }
            for (sku, region), count in sorted(
                counts.items(),
                key=lambda item: (-item[1], item[0][0].lower(), item[0][1].lower()),
            )
        ]

    def get_vm_excess_reservation_report(self) -> list[dict[str, Any]]:
        reservation_status = self._get_reservation_status()
        if not reservation_status["available"]:
            return []

        reservation_names: dict[tuple[str, str], list[str]] = defaultdict(list)
        for item in self._snapshot("reservations") or []:
            sku = str(item.get("sku") or "").strip() or "Unknown"
            region = self._normalize_region(item.get("location"))
            try:
                quantity = int(item.get("quantity") or 0)
            except (TypeError, ValueError):
                quantity = 0
            if quantity <= 0:
                continue

            display_name = (
                str(item.get("display_name") or "").strip()
                or str(item.get("name") or "").strip()
                or str(item.get("id") or "").strip()
            )
            if display_name and display_name not in reservation_names[(sku, region)]:
                reservation_names[(sku, region)].append(display_name)

        rows: list[dict[str, Any]] = []
        for item in self.get_vm_coverage_by_sku():
            if str(item.get("coverage_status") or "") != "excess":
                continue

            sku = str(item.get("label") or "").strip() or "Unknown"
            region = self._normalize_region(item.get("region"))
            delta = item.get("delta")
            if delta is None:
                continue

            rows.append(
                {
                    "label": sku,
                    "region": region,
                    "vm_count": int(item.get("vm_count") or 0),
                    "reserved_instance_count": int(item.get("reserved_instance_count") or 0),
                    "excess_count": abs(int(delta)),
                    "active_reservation_names": sorted(reservation_names.get((sku, region), []), key=str.lower),
                }
            )

        rows.sort(
            key=lambda item: (
                -int(item.get("excess_count") or 0),
                -int(item.get("reserved_instance_count") or 0),
                str(item.get("label") or "").lower(),
                str(item.get("region") or "").lower(),
            )
        )
        return rows

    def get_vm_coverage_by_sku(self) -> list[dict[str, Any]]:
        vm_rows = self.get_vm_inventory_by_sku()
        vm_counts: dict[tuple[str, str], int] = defaultdict(int)
        for item in vm_rows:
            sku = str(item.get("sku") or "Unknown")
            region = self._normalize_region(item.get("region"))
            vm_counts[(sku, region)] += int(item.get("count") or 0)

        reservation_status = self._get_reservation_status()
        reservation_counts: dict[tuple[str, str], int] = defaultdict(int)
        if reservation_status["available"]:
            for item in self.get_vm_reservations_by_sku_region():
                sku = str(item.get("sku") or "Unknown")
                region = self._normalize_region(item.get("region"))
                reservation_counts[(sku, region)] += int(item.get("reserved_instance_count") or 0)

        sku_regions = set(vm_counts)
        if reservation_status["available"]:
            sku_regions.update(reservation_counts)

        rows: list[dict[str, Any]] = []
        for sku, region in sku_regions:
            vm_count = int(vm_counts.get((sku, region)) or 0)
            reserved_instance_count = (
                int(reservation_counts.get((sku, region)) or 0)
                if reservation_status["available"]
                else None
            )
            delta = (
                vm_count - reserved_instance_count
                if reserved_instance_count is not None
                else None
            )
            if delta is None:
                coverage_status = "unavailable"
            elif delta > 0:
                coverage_status = "needed"
            elif delta < 0:
                coverage_status = "excess"
            else:
                coverage_status = "balanced"
            rows.append(
                {
                    "label": sku,
                    "region": region,
                    "vm_count": vm_count,
                    "reserved_instance_count": reserved_instance_count,
                    "delta": delta,
                    "coverage_status": coverage_status,
                }
            )

        if reservation_status["available"]:
            rows.sort(
                key=lambda item: (
                    -abs(int(item.get("delta") or 0)),
                    -max(
                        int(item.get("vm_count") or 0),
                        int(item.get("reserved_instance_count") or 0),
                    ),
                    str(item.get("label") or "").lower(),
                    str(item.get("region") or "").lower(),
                )
            )
        else:
            rows.sort(
                key=lambda item: (
                    -int(item.get("vm_count") or 0),
                    str(item.get("label") or "").lower(),
                    str(item.get("region") or "").lower(),
                )
            )
        return rows

    def get_vm_inventory_by_sku(self) -> list[dict[str, Any]]:
        resources = self._snapshot("resources") or []
        counts: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in resources:
            resource_type = str(item.get("resource_type") or "").lower()
            if resource_type != "microsoft.compute/virtualmachines":
                continue

            sku = str(item.get("vm_size") or item.get("sku_name") or "").strip() or "Unknown"
            subscription_id = str(item.get("subscription_id") or "").strip()
            subscription_name = str(item.get("subscription_name") or "").strip()
            region = self._normalize_region(item.get("location"))
            key = (subscription_id, sku, region)
            row = counts.setdefault(
                key,
                {
                    "subscription_id": subscription_id,
                    "subscription_name": subscription_name,
                    "sku": sku,
                    "region": region,
                    "count": 0,
                },
            )
            row["count"] += 1

        return sorted(
            counts.values(),
            key=lambda item: (
                -(int(item.get("count") or 0)),
                str(item.get("subscription_name") or item.get("subscription_id") or "").lower(),
                str(item.get("sku") or "").lower(),
                str(item.get("region") or "").lower(),
            ),
        )

    def get_vm_inventory_summary(self) -> dict[str, Any]:
        rows = self.get_vm_inventory_by_sku()
        coverage_rows = self.get_vm_coverage_by_sku()
        reservation_status = self._get_reservation_status()
        total_vm_count = sum(int(item.get("count") or 0) for item in rows)
        by_sku: dict[str, int] = defaultdict(int)
        by_subscription: dict[str, int] = defaultdict(int)

        for item in rows:
            sku = str(item.get("sku") or "Unknown")
            subscription_name = str(item.get("subscription_name") or item.get("subscription_id") or "Unknown")
            count = int(item.get("count") or 0)
            by_sku[sku] += count
            by_subscription[subscription_name] += count

        sku_rows = [
            {"sku": sku, "count": count}
            for sku, count in sorted(by_sku.items(), key=lambda item: (-item[1], item[0].lower()))
        ]
        subscription_rows = [
            {"subscription_name": subscription_name, "count": count}
            for subscription_name, count in sorted(by_subscription.items(), key=lambda item: (-item[1], item[0].lower()))
        ]

        return {
            "total_vm_count": total_vm_count,
            "sku_count": len(sku_rows),
            "by_sku": sku_rows,
            "by_subscription": subscription_rows,
            "by_subscription_and_sku": rows,
            "reservation_data_available": bool(reservation_status["available"]),
            "reservation_error": reservation_status.get("error"),
            "total_reserved_instances": (
                sum(int(item.get("reserved_instance_count") or 0) for item in coverage_rows)
                if reservation_status["available"]
                else None
            ),
            "by_sku_coverage": coverage_rows,
        }

    def get_virtual_machine_detail(self, resource_id: str) -> dict[str, Any] | None:
        normalized_vm_id = self._normalize_resource_id(resource_id)
        if not normalized_vm_id:
            return None

        resources = self._snapshot("resources") or []
        resource_by_id: dict[str, dict[str, Any]] = {}
        children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        managed_by_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        attached_vm_index: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for item in resources:
            normalized_id = self._normalize_resource_id(item.get("id"))
            if not normalized_id:
                continue
            resource_by_id[normalized_id] = item

            parent_id = self._normalize_resource_id(item.get("parent_resource_id"))
            if parent_id:
                children_by_parent[parent_id].append(item)

            managed_by = self._normalize_resource_id(item.get("managed_by"))
            if managed_by:
                managed_by_index[managed_by].append(item)

            attached_vm_id = self._normalize_resource_id(item.get("attached_vm_id"))
            if attached_vm_id:
                attached_vm_index[attached_vm_id].append(item)

        vm_item = resource_by_id.get(normalized_vm_id)
        if not vm_item or not self._is_virtual_machine(vm_item):
            return None

        relationship_priority = {
            "Virtual machine": 100,
            "OS disk": 90,
            "Data disk": 85,
            "Network interface": 80,
            "Public IP": 70,
            "Child resource": 60,
            "Managed by VM": 50,
            "Attached VM resource": 40,
            "Associated resource": 10,
        }
        associated_by_id: dict[str, tuple[str, int]] = {}

        def mark_related(target_resource_id: Any, relationship: str) -> None:
            normalized_target = self._normalize_resource_id(target_resource_id)
            if not normalized_target:
                return
            priority = relationship_priority.get(relationship, 0)
            current = associated_by_id.get(normalized_target)
            if current and current[1] >= priority:
                return
            associated_by_id[normalized_target] = (relationship, priority)

        mark_related(vm_item.get("id"), "Virtual machine")

        network_interface_ids = list(vm_item.get("network_interface_ids") or [])
        os_disk_id = vm_item.get("os_disk_id")
        data_disk_ids = list(vm_item.get("data_disk_ids") or [])

        for nic_id in network_interface_ids:
            mark_related(nic_id, "Network interface")
        if os_disk_id:
            mark_related(os_disk_id, "OS disk")
        for disk_id in data_disk_ids:
            mark_related(disk_id, "Data disk")

        for child in children_by_parent.get(normalized_vm_id, []):
            mark_related(child.get("id"), "Child resource")
        for item in managed_by_index.get(normalized_vm_id, []):
            mark_related(item.get("id"), "Managed by VM")
        for item in attached_vm_index.get(normalized_vm_id, []):
            mark_related(item.get("id"), "Attached VM resource")

        for nic_id in network_interface_ids:
            nic = resource_by_id.get(self._normalize_resource_id(nic_id))
            if not nic:
                continue
            for public_ip_id in nic.get("public_ip_ids") or []:
                mark_related(public_ip_id, "Public IP")

        associated_items = [
            resource_by_id[normalized_id]
            for normalized_id in associated_by_id
            if normalized_id in resource_by_id
        ]

        resource_cost_status = self._get_resource_cost_status()
        resource_cost_index = self._resource_cost_index() if resource_cost_status["available"] else {}
        if not resource_cost_status["available"] and associated_items:
            resource_cost_index, resource_cost_status = self._targeted_resource_cost_index(associated_items)

        associated_resources: list[dict[str, Any]] = []
        known_cost_count = 0
        total_cost = 0.0
        vm_cost = 0.0

        for normalized_id, (relationship, priority) in associated_by_id.items():
            item = resource_by_id.get(normalized_id)
            cost_row = resource_cost_index.get(normalized_id)
            cost_value: float | None
            if resource_cost_status["available"]:
                if cost_row:
                    cost_value = round(float(cost_row.get("amount") or 0.0), 2)
                    known_cost_count += 1
                else:
                    cost_value = 0.0
            else:
                cost_value = None

            if cost_value is not None:
                total_cost += cost_value
                if relationship == "Virtual machine":
                    vm_cost = cost_value

            associated_resources.append(
                {
                    "id": item.get("id") if item else f"/{normalized_id}",
                    "name": (
                        (item.get("name") if item else "")
                        or self._resource_display_name(item.get("id") if item else normalized_id)
                    ),
                    "resource_type": item.get("resource_type") if item else "",
                    "relationship": relationship,
                    "subscription_id": item.get("subscription_id") if item else "",
                    "subscription_name": item.get("subscription_name") if item else "",
                    "resource_group": item.get("resource_group") if item else "",
                    "location": item.get("location") if item else "",
                    "state": item.get("state") if item else "",
                    "cost": cost_value,
                    "currency": str((cost_row or {}).get("currency") or "USD"),
                    "_priority": priority,
                }
            )

        associated_resources.sort(
            key=lambda item: (
                -int(item.pop("_priority", 0)),
                -(float(item.get("cost") or 0.0) if item.get("cost") is not None else -1.0),
                str(item.get("name") or "").lower(),
            )
        )

        vm_row = dict(vm_item)
        vm_row["size"] = self._vm_size(vm_item)
        vm_row["power_state"] = self._vm_power_state(vm_item)

        cost_summary = self.get_cost_summary()
        total_cost_value = round(total_cost, 2) if resource_cost_status["available"] else None
        vm_cost_value = round(vm_cost, 2) if resource_cost_status["available"] else None
        related_resource_cost = (
            round(total_cost - vm_cost, 2)
            if resource_cost_status["available"]
            else None
        )

        return {
            "vm": vm_row,
            "associated_resources": associated_resources,
            "cost": {
                "lookback_days": int(cost_summary.get("lookback_days") or AZURE_COST_LOOKBACK_DAYS),
                "currency": str(cost_summary.get("currency") or "USD"),
                "cost_data_available": bool(resource_cost_status["available"]),
                "cost_error": resource_cost_status.get("error"),
                "total_cost": total_cost_value,
                "vm_cost": vm_cost_value,
                "related_resource_cost": related_resource_cost,
                "priced_resource_count": known_cost_count,
            },
        }

    def get_grounding_context(self) -> dict[str, Any]:
        return {
            "overview": self.get_overview(),
            "cost_summary": self.get_cost_summary(),
            "cost_trend": (self.get_cost_trend() or [])[-14:],
            "cost_by_service": (self.get_cost_breakdown("service") or [])[:8],
            "cost_by_subscription": (self.get_cost_breakdown("subscription") or [])[:8],
            "cost_by_resource_group": (self.get_cost_breakdown("resource_group") or [])[:8],
            "vm_inventory_summary": self.get_vm_inventory_summary(),
            "advisor": (self.get_advisor() or [])[:10],
        }


azure_cache = AzureCache()
