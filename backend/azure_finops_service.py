"""Local analytics service for Azure FinOps cost reporting.

This service keeps the existing FastAPI backend and route surface intact while
adding an export-backed analytical store underneath the Azure cost views.
"""

from __future__ import annotations

from collections import defaultdict
import json
import logging
import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import duckdb

from azure_auxiliary_staging import dataset_descriptor
from azure_finops_safe_hooks import AzureFinOpsSafeHookRunner, azure_finops_safe_hook_runner

logger = logging.getLogger(__name__)

_USAGE_QUANTITY_FIELDS = (
    "ConsumedQuantity",
    "UsageQuantity",
    "Quantity",
    "ConsumedServiceQuantity",
)
_LOCATION_FIELDS = (
    "Location",
    "RegionName",
    "ResourceLocation",
    "ResourceLocationName",
)
_RESOURCE_NAME_FIELDS = ("ResourceName", "InstanceName", "Resource")
_PRICING_MODEL_FIELDS = ("PricingModel", "PricingCategory", "CommitmentDiscountType")
_TAG_FIELDS = ("Tags", "tags")

_SUBSCRIPTION_ID_RE = re.compile(r"/subscriptions/([^/]+)", re.IGNORECASE)
_RESOURCE_GROUP_RE = re.compile(r"/resourceGroups/([^/]+)", re.IGNORECASE)
_DEFAULT_ALLOCATION_DIMENSIONS = ("team", "application", "product")
_VALID_ALLOCATION_RULE_TYPES = ("tag", "regex", "percentage", "shared")
_VALID_ALLOCATION_DIMENSIONS = set(_DEFAULT_ALLOCATION_DIMENSIONS)
_VALID_ALLOCATION_MATCH_FIELDS = {
    "subscription_id",
    "subscription_name",
    "resource_group",
    "resource_name",
    "resource_id",
    "service_name",
    "meter_category",
    "location",
    "pricing_model",
    "charge_type",
    "scope_key",
    "currency",
}
_VALIDATION_COST_TOLERANCE = 0.01
_VALIDATION_CACHE_WARNING_DELTA = 1.0
_VALIDATION_MIN_DELIVERIES_FOR_SIGNOFF = 2
_VALIDATION_ESSENTIAL_FIELD_COVERAGE_THRESHOLD = 0.95
_ALLOCATION_POLICY = {
    "version": 1,
    "target_dimensions": [
        {
            "dimension": "team",
            "label": "Team",
            "fallback_bucket": "Unassigned Team",
            "shared_bucket": "Shared Team Costs",
            "description": "Primary showback owner for the engineering or support team accountable for the spend.",
        },
        {
            "dimension": "application",
            "label": "Application",
            "fallback_bucket": "Unassigned Application",
            "shared_bucket": "Shared Application Costs",
            "description": "Application or service aligned showback bucket for engineering-facing cost ownership.",
        },
        {
            "dimension": "product",
            "label": "Product",
            "fallback_bucket": "Unassigned Product",
            "shared_bucket": "Shared Product Costs",
            "description": "Business-facing product or capability bucket used for product rollups and showback.",
        },
    ],
    "shared_cost_posture": {
        "mode": "showback_named_shared_buckets",
        "description": (
            "Shared platform or cross-cutting costs stay visible in explicit named shared buckets until a deliberate "
            "split rule allocates them across the chosen dimension."
        ),
    },
    "supported_rule_types": list(_VALID_ALLOCATION_RULE_TYPES),
    "supported_match_fields": sorted(_VALID_ALLOCATION_MATCH_FIELDS),
}

_COST_RECORD_FIELD_MAP: dict[str, dict[str, Any]] = {
    "date": {
        "normalized_column": "date",
        "description": "Usage date for the exported cost row.",
        "source_priority": ["usage_date", "raw.UsageDate", "raw.Date"],
    },
    "subscriptionId": {
        "normalized_column": "subscription_id",
        "description": "Subscription identifier, sourced directly or inferred from resource ID.",
        "source_priority": ["raw.SubscriptionId", "resource_id"],
    },
    "subscriptionName": {
        "normalized_column": "subscription_name",
        "description": "Friendly subscription name from the export row.",
        "source_priority": ["subscription_name", "raw.SubscriptionName"],
    },
    "resourceGroup": {
        "normalized_column": "resource_group",
        "description": "Resource group for the cost row.",
        "source_priority": ["resource_group_name", "raw.ResourceGroupName", "resource_id"],
    },
    "resourceName": {
        "normalized_column": "resource_name",
        "description": "Leaf resource name for the cost row.",
        "source_priority": ["raw.ResourceName", "raw.InstanceName", "resource_id"],
    },
    "resourceId": {
        "normalized_column": "resource_id",
        "description": "Azure resource ID tied to the exported cost line item.",
        "source_priority": ["resource_id", "raw.ResourceId"],
    },
    "serviceName": {
        "normalized_column": "service_name",
        "description": "Service or consumed service used for grouped reporting.",
        "source_priority": ["service_name", "consumed_service", "raw.ServiceName", "raw.ConsumedService"],
    },
    "meterCategory": {
        "normalized_column": "meter_category",
        "description": "Meter category for the exported cost line item.",
        "source_priority": ["meter_category", "raw.MeterCategory"],
    },
    "location": {
        "normalized_column": "location",
        "description": "Azure region associated with the line item when present.",
        "source_priority": ["raw.Location", "raw.RegionName", "raw.ResourceLocation", "raw.ResourceLocationName"],
    },
    "costActual": {
        "normalized_column": "cost_actual",
        "description": "Actual cost in billing currency.",
        "source_priority": ["actual_cost", "raw.CostInBillingCurrency"],
    },
    "costAmortized": {
        "normalized_column": "cost_amortized",
        "description": "Amortized cost in billing currency.",
        "source_priority": ["amortized_cost", "raw.AmortizedCostInBillingCurrency"],
    },
    "usageQuantity": {
        "normalized_column": "usage_quantity",
        "description": "Usage quantity or consumed quantity for the line item.",
        "source_priority": list(_USAGE_QUANTITY_FIELDS),
    },
    "tags": {
        "normalized_column": "tags_json",
        "description": "Normalized JSON object of tags for the line item.",
        "source_priority": list(_TAG_FIELDS),
    },
    "pricingModel": {
        "normalized_column": "pricing_model",
        "description": "Normalized pricing model classification.",
        "source_priority": list(_PRICING_MODEL_FIELDS) + ["charge_type"],
    },
    "chargeType": {
        "normalized_column": "charge_type",
        "description": "Original charge type from the export line item.",
        "source_priority": ["charge_type", "raw.ChargeType"],
    },
    "scopeKey": {
        "normalized_column": "scope_key",
        "description": "Configured reporting scope for the export delivery.",
        "source_priority": ["delivery.scope_key"],
    },
    "currency": {
        "normalized_column": "currency",
        "description": "Billing currency for the line item.",
        "source_priority": ["currency", "raw.BillingCurrencyCode", "raw.Currency"],
    },
    "sourceDeliveryKey": {
        "normalized_column": "source_delivery_key",
        "description": "Delivery manifest key used for import provenance.",
        "source_priority": ["delivery.delivery_key"],
    },
}

_RECOMMENDATION_STATUS_OPEN = "open"
_RECOMMENDATION_STATUS_DISMISSED = "dismissed"
_RECOMMENDATION_STATUS_ACCEPTED = "accepted"
_RECOMMENDATION_ACTION_STATE_NONE = "none"
_VALID_RECOMMENDATION_LIFECYCLE_STATES = {
    _RECOMMENDATION_STATUS_OPEN,
    _RECOMMENDATION_STATUS_DISMISSED,
    _RECOMMENDATION_STATUS_ACCEPTED,
}
_VALID_RECOMMENDATION_ACTION_STATES = {
    _RECOMMENDATION_ACTION_STATE_NONE,
    "reviewed",
    "ticket_pending",
    "ticket_created",
    "alert_pending",
    "alert_sent",
    "exported",
    "script_pending",
    "script_executed",
}
_RECOMMENDATION_ACTION_CONTRACTS: dict[str, dict[str, Any]] = {
    "create_ticket": {
        "label": "Create Jira ticket",
        "description": "Create a Jira follow-up for the recommendation and persist the linked workflow state.",
        "category": "jira",
        "pending_action_state": "ticket_pending",
        "completed_action_state": "ticket_created",
        "repeatable": False,
        "requires_admin": True,
        "note_placeholder": "Add an operator note for the Jira follow-up.",
        "metadata_fields": [
            {"key": "project_key", "label": "Project key", "description": "Optional Jira project override.", "required": False},
            {"key": "issue_type", "label": "Issue type", "description": "Optional Jira issue type override.", "required": False},
            {"key": "summary", "label": "Ticket summary", "description": "Optional summary override for the created ticket.", "required": False},
        ],
    },
    "send_alert": {
        "label": "Send Teams alert",
        "description": "Send a Teams or operator-facing alert using the existing alert plumbing and persist the alert workflow state.",
        "category": "teams",
        "pending_action_state": "alert_pending",
        "completed_action_state": "alert_sent",
        "repeatable": True,
        "requires_admin": True,
        "note_placeholder": "Add an operator note for the Teams alert.",
        "metadata_fields": [
            {"key": "channel", "label": "Target channel", "description": "Optional Teams channel or webhook label.", "required": False},
            {
                "key": "teams_webhook_url",
                "label": "Webhook override",
                "description": "Optional Teams webhook override when the default FinOps channel is not the right destination.",
                "required": False,
            },
        ],
    },
    "export": {
        "label": "Export recommendation",
        "description": "Export the recommendation through the existing CSV/XLSX workspace without mutating the recommendation itself.",
        "category": "export",
        "pending_action_state": "",
        "completed_action_state": "exported",
        "repeatable": True,
        "requires_admin": True,
        "note_placeholder": "Add an operator note for this export if needed.",
        "metadata_fields": [
            {"key": "format", "label": "Format", "description": "Export format such as csv or xlsx.", "required": False},
        ],
    },
    "run_safe_script": {
        "label": "Run safe script",
        "description": "Run an allowlisted safe remediation hook with explicit guardrails. Destructive remediation stays out of scope for v1.",
        "category": "script",
        "pending_action_state": "script_pending",
        "completed_action_state": "script_executed",
        "repeatable": True,
        "requires_admin": True,
        "note_placeholder": "Add an operator note for the safe remediation hook run.",
        "metadata_fields": [
            {"key": "hook_key", "label": "Hook", "description": "Allowlisted safe remediation hook identifier.", "required": False},
            {"key": "dry_run", "label": "Dry run", "description": "Run the hook in dry-run mode unless the allowlist explicitly permits apply mode.", "required": False},
        ],
    },
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _pick_first(mapping: Mapping[str, Any], candidates: Iterable[str]) -> str:
    for candidate in candidates:
        text = _text(mapping.get(candidate))
        if text:
            return text
    return ""


def _parse_iso_date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _validation_check(
    key: str,
    label: str,
    state: str,
    detail: str,
    *,
    source_a: str = "",
    source_b: str = "",
    metric: str = "",
    actual: Any = None,
    expected: Any = None,
    delta: Any = None,
    tolerance: Any = None,
    unit: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "key": key,
        "label": label,
        "state": state,
        "detail": detail,
    }
    if source_a:
        payload["source_a"] = source_a
    if source_b:
        payload["source_b"] = source_b
    if metric:
        payload["metric"] = metric
    if actual is not None:
        payload["actual"] = actual
    if expected is not None:
        payload["expected"] = expected
    if delta is not None:
        payload["delta"] = delta
    if tolerance is not None:
        payload["tolerance"] = tolerance
    if unit:
        payload["unit"] = unit
    return payload


def _subscription_id_from_resource_id(resource_id: str) -> str:
    match = _SUBSCRIPTION_ID_RE.search(_text(resource_id))
    return match.group(1).strip() if match else ""


def _resource_group_from_resource_id(resource_id: str) -> str:
    match = _RESOURCE_GROUP_RE.search(_text(resource_id))
    return match.group(1).strip() if match else ""


def _resource_name_from_resource_id(resource_id: str) -> str:
    text = _text(resource_id).rstrip("/")
    if not text:
        return ""
    return text.split("/")[-1].strip()


def _normalize_resource_id(value: Any) -> str:
    return _text(value).strip("/").lower()


def _resource_type_from_resource_id(resource_id: Any) -> str:
    parts = [segment for segment in _text(resource_id).strip("/").split("/") if segment]
    if not parts:
        return ""
    try:
        provider_index = next(index for index, part in enumerate(parts) if part.lower() == "providers")
    except StopIteration:
        return ""
    if provider_index + 2 >= len(parts):
        return ""
    namespace = parts[provider_index + 1]
    type_parts: list[str] = []
    for index in range(provider_index + 2, len(parts), 2):
        type_parts.append(parts[index])
    if not type_parts:
        return ""
    return f"{namespace}/{'/'.join(type_parts)}"


def _resource_lookup_key(subscription_id: Any, resource_group: Any, resource_name: Any) -> tuple[str, str, str]:
    return (_text(subscription_id).lower(), _text(resource_group).lower(), _text(resource_name).lower())


def _aks_cluster_id_from_resource_id(resource_id: Any) -> str:
    parts = [segment for segment in _text(resource_id).strip("/").split("/") if segment]
    lowered = [segment.lower() for segment in parts]
    try:
        providers_index = lowered.index("providers")
    except ValueError:
        return ""
    if providers_index + 3 >= len(parts):
        return ""
    if lowered[providers_index + 1] != "microsoft.containerservice":
        return ""
    if lowered[providers_index + 2] != "managedclusters":
        return ""
    return "/" + "/".join(parts[: providers_index + 4])


def _aks_node_pool_name(resource: Mapping[str, Any]) -> str:
    tags = resource.get("tags")
    if isinstance(tags, Mapping):
        normalized_tags = {str(key).strip().lower(): _text(value) for key, value in tags.items() if _text(key)}
        for key in (
            "aks-managed-poolname",
            "poolname",
            "agentpool",
            "agentpoolname",
            "kubernetes.azure.com/agentpool",
            "nodepool",
        ):
            value = _text(normalized_tags.get(key))
            if value:
                return value
    resource_name = _text(resource.get("name"))
    if resource_name.startswith("aks-") and "-vmss" in resource_name:
        middle = resource_name[4:].split("-vmss", 1)[0]
        if middle:
            return middle
    return ""


def _parse_tags(value: Any) -> dict[str, str]:
    text = _text(value)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {str(key): _text(raw_value) for key, raw_value in parsed.items() if _text(key)}
    except json.JSONDecodeError:
        pass

    result: dict[str, str] = {}
    for separator in (";", ","):
        parts = [segment.strip() for segment in text.split(separator)]
        if len(parts) <= 1:
            continue
        for part in parts:
            if "=" in part:
                key, raw_value = part.split("=", 1)
            elif ":" in part:
                key, raw_value = part.split(":", 1)
            else:
                continue
            key_text = _text(key)
            if key_text:
                result[key_text] = _text(raw_value)
        if result:
            return result
    return result


def _parse_json_list(value: Any) -> list[Any]:
    text = _text(value)
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _parse_json_object(value: Any) -> dict[str, Any]:
    text = _text(value)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_pricing_model(raw: Mapping[str, Any], charge_type: str) -> str:
    combined = " ".join(_pick_first(raw, (field,)) for field in _PRICING_MODEL_FIELDS)
    combined = f"{combined} {charge_type}".strip().lower()
    if "savings plan" in combined or "savingsplan" in combined:
        return "savings plan"
    if "reservation" in combined or "reserved" in combined:
        return "reservation"
    if "spot" in combined:
        return "spot"
    return "on-demand"


def _allocation_dimension_policy(dimension: str) -> dict[str, Any]:
    for item in _ALLOCATION_POLICY["target_dimensions"]:
        if item["dimension"] == dimension:
            return dict(item)
    raise ValueError(f"Unsupported allocation dimension: {dimension}")


def _normalize_allocation_dimensions(dimensions: Iterable[str] | None) -> list[str]:
    values = [_text(item).lower() for item in (dimensions or []) if _text(item)]
    if not values:
        return list(_DEFAULT_ALLOCATION_DIMENSIONS)
    normalized: list[str] = []
    for value in values:
        if value not in _VALID_ALLOCATION_DIMENSIONS:
            raise ValueError(f"Unsupported allocation dimension: {value}")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _normalize_fraction(value: Any, *, field_name: str) -> float:
    amount = _float(value)
    if amount <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    if amount > 1:
        if amount > 100:
            raise ValueError(f"{field_name} must be between 0 and 1 or 0 and 100")
        amount = amount / 100.0
    if amount > 1:
        raise ValueError(f"{field_name} must not exceed 100 percent")
    return round(amount, 6)


def _normalize_condition_payload(rule_type: str, condition: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(condition or {})
    normalized: dict[str, Any] = {}
    if not payload:
        if rule_type in {"tag", "regex"}:
            raise ValueError(f"{rule_type} rules require a condition")
        return normalized

    tag_key = _text(payload.get("tag_key"))
    if tag_key:
        normalized["tag_key"] = tag_key
        tag_value = _text(payload.get("tag_value") or payload.get("equals"))
        if tag_value:
            normalized["tag_value"] = tag_value
        values = payload.get("values")
        if isinstance(values, list):
            normalized_values = [_text(item) for item in values if _text(item)]
            if normalized_values:
                normalized["values"] = normalized_values
        pattern = _text(payload.get("pattern"))
        if pattern:
            re.compile(pattern)
            normalized["pattern"] = pattern
        return normalized

    field = _text(payload.get("field"))
    if field:
        if field not in _VALID_ALLOCATION_MATCH_FIELDS and not field.startswith("tags."):
            raise ValueError(f"Unsupported allocation match field: {field}")
        normalized["field"] = field
        equals = _text(payload.get("equals"))
        if equals:
            normalized["equals"] = equals
        values = payload.get("values")
        if isinstance(values, list):
            normalized_values = [_text(item) for item in values if _text(item)]
            if normalized_values:
                normalized["values"] = normalized_values
        pattern = _text(payload.get("pattern"))
        if pattern:
            re.compile(pattern)
            normalized["pattern"] = pattern
        elif rule_type == "regex":
            raise ValueError("Regex rules require a regex pattern")
        return normalized

    if rule_type in {"tag", "regex"}:
        raise ValueError(f"{rule_type} rules require either tag_key or field in the condition")
    return normalized


def _normalize_allocation_payload(rule_type: str, allocation: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(allocation or {})
    if rule_type == "shared":
        splits = payload.get("splits")
        if not isinstance(splits, list) or not splits:
            raise ValueError("Shared allocation rules require a non-empty splits list")
        normalized_splits: list[dict[str, Any]] = []
        total = 0.0
        for item in splits:
            if not isinstance(item, Mapping):
                continue
            value = _text(item.get("value"))
            if not value:
                raise ValueError("Shared allocation splits require a target value")
            percentage = _normalize_fraction(item.get("percentage"), field_name="split percentage")
            total += percentage
            normalized_splits.append({"value": value, "percentage": percentage})
        if not normalized_splits:
            raise ValueError("Shared allocation rules require valid split rows")
        if abs(total - 1.0) > 0.0001:
            raise ValueError("Shared allocation split percentages must total 100 percent")
        return {"splits": normalized_splits}

    value = _text(payload.get("value"))
    if not value:
        raise ValueError("Allocation rules require a non-empty allocation value")

    normalized = {"value": value}
    if rule_type == "percentage":
        normalized["percentage"] = _normalize_fraction(payload.get("percentage"), field_name="percentage")
    return normalized


def _latest_rule_select_sql() -> str:
    return """
        SELECT
            rule_id,
            rule_version,
            name,
            description,
            rule_type,
            target_dimension,
            priority,
            enabled,
            condition_json,
            allocation_json,
            created_by,
            created_at,
            superseded_at
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (PARTITION BY rule_id ORDER BY rule_version DESC) AS rule_rank
            FROM allocation_rules
        )
        WHERE rule_rank = 1
    """


class AzureFinOpsService:
    """Small local analytics store for export-backed Azure cost reporting."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        default_lookback_days: int = 30,
        ai_pricing_config: Mapping[str, Any] | None = None,
        safe_hook_runner: AzureFinOpsSafeHookRunner | None = None,
    ) -> None:
        self._db_path = str(db_path)
        self._default_lookback_days = max(int(default_lookback_days or 0), 1)
        self._ai_pricing_config = dict(ai_pricing_config or {})
        self._safe_hook_runner = safe_hook_runner or azure_finops_safe_hook_runner
        self._lock = threading.RLock()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self._db_path)

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cost_records (
                        cost_record_id VARCHAR,
                        date DATE,
                        subscription_id VARCHAR,
                        subscription_name VARCHAR,
                        resource_group VARCHAR,
                        resource_name VARCHAR,
                        resource_id VARCHAR,
                        service_name VARCHAR,
                        meter_category VARCHAR,
                        location VARCHAR,
                        cost_actual DOUBLE,
                        cost_amortized DOUBLE,
                        usage_quantity DOUBLE,
                        tags_json VARCHAR,
                        pricing_model VARCHAR,
                        charge_type VARCHAR,
                        scope_key VARCHAR,
                        currency VARCHAR,
                        source_delivery_key VARCHAR
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS finops_delivery_imports (
                        delivery_key VARCHAR,
                        dataset VARCHAR,
                        scope_key VARCHAR,
                        manifest_path VARCHAR,
                        parsed_at TIMESTAMP,
                        row_count BIGINT,
                        source_updated_at TIMESTAMP,
                        source_updated_at_text VARCHAR,
                        imported_at TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_usage_records (
                        usage_id VARCHAR,
                        recorded_at TIMESTAMP,
                        recorded_date DATE,
                        provider VARCHAR,
                        model_id VARCHAR,
                        feature_surface VARCHAR,
                        app_surface VARCHAR,
                        actor_type VARCHAR,
                        actor_id VARCHAR,
                        team VARCHAR,
                        request_count INTEGER,
                        input_tokens BIGINT,
                        output_tokens BIGINT,
                        estimated_tokens BIGINT,
                        latency_ms DOUBLE,
                        estimated_cost DOUBLE,
                        currency VARCHAR,
                        pricing_source VARCHAR,
                        status VARCHAR,
                        error_text VARCHAR,
                        metadata_json VARCHAR
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS price_sheet_rows (
                        price_row_id VARCHAR,
                        meter_id VARCHAR,
                        meter_name VARCHAR,
                        meter_category VARCHAR,
                        meter_subcategory VARCHAR,
                        meter_region VARCHAR,
                        product_id VARCHAR,
                        product_name VARCHAR,
                        sku_id VARCHAR,
                        sku_name VARCHAR,
                        service_family VARCHAR,
                        price_type VARCHAR,
                        term VARCHAR,
                        unit_of_measure VARCHAR,
                        unit_price DOUBLE,
                        market_price DOUBLE,
                        base_price DOUBLE,
                        currency VARCHAR,
                        billing_currency VARCHAR,
                        effective_start_date DATE,
                        effective_end_date DATE,
                        scope_key VARCHAR,
                        source_delivery_key VARCHAR,
                        raw_json VARCHAR
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reservation_recommendation_rows (
                        recommendation_row_id VARCHAR,
                        subscription_id VARCHAR,
                        location VARCHAR,
                        sku_name VARCHAR,
                        resource_type VARCHAR,
                        scope VARCHAR,
                        term VARCHAR,
                        lookback_period DOUBLE,
                        recommended_quantity DOUBLE,
                        recommended_quantity_normalized DOUBLE,
                        net_savings DOUBLE,
                        cost_without_reserved_instances DOUBLE,
                        total_cost_with_reserved_instances DOUBLE,
                        meter_id VARCHAR,
                        instance_flexibility_ratio DOUBLE,
                        first_usage_date DATE,
                        scope_key VARCHAR,
                        source_delivery_key VARCHAR,
                        raw_json VARCHAR
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS recommendations (
                        recommendation_id VARCHAR,
                        category VARCHAR,
                        opportunity_type VARCHAR,
                        source VARCHAR,
                        title VARCHAR,
                        summary VARCHAR,
                        subscription_id VARCHAR,
                        subscription_name VARCHAR,
                        resource_group VARCHAR,
                        location VARCHAR,
                        resource_id VARCHAR,
                        resource_name VARCHAR,
                        resource_type VARCHAR,
                        current_monthly_cost DOUBLE,
                        estimated_monthly_savings DOUBLE,
                        currency VARCHAR,
                        quantified BOOLEAN,
                        estimate_basis VARCHAR,
                        effort VARCHAR,
                        risk VARCHAR,
                        confidence VARCHAR,
                        recommended_steps_json VARCHAR,
                        evidence_json VARCHAR,
                        portal_url VARCHAR,
                        follow_up_route VARCHAR,
                        lifecycle_status VARCHAR,
                        action_state VARCHAR,
                        dismissed_reason VARCHAR,
                        source_version VARCHAR,
                        source_refreshed_at TIMESTAMP,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS recommendation_refresh_state (
                        snapshot_name VARCHAR,
                        source_version VARCHAR,
                        source_refreshed_at TIMESTAMP,
                        row_count BIGINT,
                        refreshed_at TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS recommendation_action_events (
                        event_id VARCHAR,
                        recommendation_id VARCHAR,
                        action_type VARCHAR,
                        action_status VARCHAR,
                        actor_type VARCHAR,
                        actor_id VARCHAR,
                        note VARCHAR,
                        metadata_json VARCHAR,
                        created_at TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS allocation_rules (
                        rule_id VARCHAR,
                        rule_version INTEGER,
                        name VARCHAR,
                        description VARCHAR,
                        rule_type VARCHAR,
                        target_dimension VARCHAR,
                        priority INTEGER,
                        enabled BOOLEAN,
                        condition_json VARCHAR,
                        allocation_json VARCHAR,
                        created_by VARCHAR,
                        created_at TIMESTAMP,
                        superseded_at TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS allocation_runs (
                        run_id VARCHAR,
                        run_label VARCHAR,
                        trigger_type VARCHAR,
                        triggered_by VARCHAR,
                        note VARCHAR,
                        status VARCHAR,
                        target_dimensions_json VARCHAR,
                        policy_version INTEGER,
                        source_record_count BIGINT,
                        created_at TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS allocation_run_rules (
                        run_id VARCHAR,
                        rule_id VARCHAR,
                        rule_version INTEGER,
                        target_dimension VARCHAR,
                        rule_type VARCHAR,
                        priority INTEGER,
                        snapshot_json VARCHAR
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS allocation_run_dimensions (
                        run_id VARCHAR,
                        target_dimension VARCHAR,
                        source_record_count BIGINT,
                        source_actual_cost DOUBLE,
                        source_amortized_cost DOUBLE,
                        source_usage_quantity DOUBLE,
                        direct_allocated_actual_cost DOUBLE,
                        direct_allocated_amortized_cost DOUBLE,
                        direct_allocated_usage_quantity DOUBLE,
                        residual_actual_cost DOUBLE,
                        residual_amortized_cost DOUBLE,
                        residual_usage_quantity DOUBLE,
                        total_allocated_actual_cost DOUBLE,
                        total_allocated_amortized_cost DOUBLE,
                        total_allocated_usage_quantity DOUBLE,
                        coverage_pct DOUBLE,
                        created_at TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS allocation_results (
                        run_id VARCHAR,
                        cost_record_id VARCHAR,
                        date DATE,
                        target_dimension VARCHAR,
                        allocation_value VARCHAR,
                        bucket_type VARCHAR,
                        source_rule_id VARCHAR,
                        source_rule_version INTEGER,
                        allocation_method VARCHAR,
                        share_fraction DOUBLE,
                        allocated_actual_cost DOUBLE,
                        allocated_amortized_cost DOUBLE,
                        allocated_usage_quantity DOUBLE,
                        subscription_id VARCHAR,
                        subscription_name VARCHAR,
                        resource_group VARCHAR,
                        resource_name VARCHAR,
                        resource_id VARCHAR,
                        service_name VARCHAR,
                        meter_category VARCHAR,
                        location VARCHAR,
                        pricing_model VARCHAR,
                        charge_type VARCHAR,
                        scope_key VARCHAR,
                        currency VARCHAR,
                        source_delivery_key VARCHAR,
                        tags_json VARCHAR
                    )
                    """
                )
                import_columns = {
                    row[1] if isinstance(row, tuple) else row["name"]
                    for row in conn.execute("PRAGMA table_info('finops_delivery_imports')").fetchall()
                }
                if "source_updated_at_text" not in import_columns:
                    conn.execute(
                        "ALTER TABLE finops_delivery_imports ADD COLUMN source_updated_at_text VARCHAR"
                    )
                allocation_result_columns = {
                    row[1] if isinstance(row, tuple) else row["name"]
                    for row in conn.execute("PRAGMA table_info('allocation_results')").fetchall()
                }
                if "date" not in allocation_result_columns:
                    conn.execute("ALTER TABLE allocation_results ADD COLUMN date DATE")
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_cost_records_date
                    ON cost_records(date)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_cost_records_subscription
                    ON cost_records(subscription_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_cost_records_group
                    ON cost_records(resource_group)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_ai_usage_records_date
                    ON ai_usage_records(recorded_date)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_ai_usage_records_model
                    ON ai_usage_records(model_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_ai_usage_records_feature
                    ON ai_usage_records(feature_surface)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_price_sheet_rows_delivery
                    ON price_sheet_rows(source_delivery_key)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_reservation_recommendation_rows_delivery
                    ON reservation_recommendation_rows(source_delivery_key)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_recommendations_category
                    ON recommendations(category)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_recommendations_subscription
                    ON recommendations(subscription_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_recommendation_action_events_recommendation
                    ON recommendation_action_events(recommendation_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_allocation_rules_rule
                    ON allocation_rules(rule_id, rule_version)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_allocation_rules_dimension
                    ON allocation_rules(target_dimension, enabled, priority)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_allocation_runs_created
                    ON allocation_runs(created_at)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_allocation_run_rules_run
                    ON allocation_run_rules(run_id, target_dimension)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_allocation_run_dimensions_run
                    ON allocation_run_dimensions(run_id, target_dimension)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_allocation_results_run
                    ON allocation_results(run_id, target_dimension, bucket_type)
                    """
                )
            finally:
                conn.close()

    def _load_staged_model(self, delivery: Mapping[str, Any], store: Any | None = None) -> dict[str, Any] | None:
        delivery_key = _text(delivery.get("delivery_key"))
        if store is not None:
            getter = getattr(store, "get_stage_model", None)
            if callable(getter):
                try:
                    staged = getter(delivery_key)
                except Exception:
                    logger.exception("Failed to load staged model for delivery %s from store", delivery_key)
                else:
                    if isinstance(staged, Mapping):
                        return dict(staged)

        manifest_path_text = _text(delivery.get("manifest_path"))
        if not manifest_path_text:
            return None
        manifest_path = Path(manifest_path_text)
        staged_path = manifest_path.with_name("staged.json")
        if not staged_path.exists():
            return None
        try:
            payload = json.loads(staged_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to load staged model from %s", staged_path)
            return None
        return payload if isinstance(payload, dict) else None

    def _source_updated_at(self, delivery: Mapping[str, Any]) -> datetime | None:
        return (
            _parse_iso_datetime(delivery.get("parsed_at"))
            or _parse_iso_datetime(delivery.get("updated_at"))
            or _parse_iso_datetime(delivery.get("discovered_at"))
        )

    def _source_updated_at_text(self, delivery: Mapping[str, Any]) -> str:
        updated_at = self._source_updated_at(delivery)
        return updated_at.isoformat() if updated_at is not None else ""

    def _latest_cost_date(self) -> date | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT MAX(date) FROM cost_records").fetchone()
            finally:
                conn.close()
        latest_date = row[0] if row else None
        if isinstance(latest_date, datetime):
            return latest_date.date()
        if isinstance(latest_date, date):
            return latest_date
        return _parse_iso_date(latest_date)

    def _latest_ai_usage_date(self) -> date | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT MAX(recorded_date) FROM ai_usage_records").fetchone()
            finally:
                conn.close()
        latest_date = row[0] if row else None
        if isinstance(latest_date, datetime):
            return latest_date.date()
        if isinstance(latest_date, date):
            return latest_date
        return _parse_iso_date(latest_date)

    def _pricing_entry(self, provider: str, model_id: str) -> dict[str, Any]:
        config = self._ai_pricing_config
        models = config.get("models")
        if isinstance(models, Mapping):
            model_entry = models.get(model_id)
            if isinstance(model_entry, Mapping):
                payload = dict(model_entry)
                payload.setdefault("source", f"models.{model_id}")
                return payload
        providers = config.get("providers")
        if isinstance(providers, Mapping):
            provider_entry = providers.get(provider)
            if isinstance(provider_entry, Mapping):
                payload = dict(provider_entry)
                payload.setdefault("source", f"providers.{provider}")
                return payload
        return {"input_per_1k_tokens": 0.0, "output_per_1k_tokens": 0.0, "currency": "USD", "source": "default_zero"}

    def estimate_ai_cost(
        self,
        *,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, Any]:
        pricing = self._pricing_entry(provider, model_id)
        input_rate = _float(
            pricing.get("input_per_1k_tokens")
            or pricing.get("input_cost_per_1k_tokens")
            or pricing.get("input_cost_per_1k")
        )
        output_rate = _float(
            pricing.get("output_per_1k_tokens")
            or pricing.get("output_cost_per_1k_tokens")
            or pricing.get("output_cost_per_1k")
        )
        currency = _text(pricing.get("currency") or "USD") or "USD"
        estimated_cost = round(((input_tokens / 1000.0) * input_rate) + ((output_tokens / 1000.0) * output_rate), 6)
        return {
            "estimated_cost": estimated_cost,
            "currency": currency,
            "pricing_source": _text(pricing.get("source") or "default_zero") or "default_zero",
            "input_rate_per_1k_tokens": input_rate,
            "output_rate_per_1k_tokens": output_rate,
        }

    def _needs_import(self, conn: duckdb.DuckDBPyConnection, delivery: Mapping[str, Any]) -> bool:
        delivery_key = _text(delivery.get("delivery_key"))
        row = conn.execute(
            """
            SELECT source_updated_at_text, row_count
            FROM finops_delivery_imports
            WHERE delivery_key = ?
            LIMIT 1
            """,
            [delivery_key],
        ).fetchone()
        if row is None:
            return True
        imported_updated_at = _text(row[0])
        imported_row_count = int(row[1] or 0)
        source_updated_at = self._source_updated_at_text(delivery)
        source_row_count = int(delivery.get("row_count") or 0)
        if imported_row_count != source_row_count:
            return True
        if not source_updated_at:
            return False
        if not imported_updated_at:
            return True
        return imported_updated_at != source_updated_at

    def _normalize_cost_record(
        self,
        row: Mapping[str, Any],
        *,
        scope_key: str,
        delivery_key: str,
    ) -> tuple[Any, ...] | None:
        usage_date = _parse_iso_date(row.get("usage_date"))
        if usage_date is None:
            return None
        raw = row.get("raw")
        raw_mapping = dict(raw) if isinstance(raw, Mapping) else {}
        resource_id = _text(row.get("resource_id")) or _pick_first(raw_mapping, ("ResourceId",))
        subscription_id = _pick_first(raw_mapping, ("SubscriptionId",)) or _subscription_id_from_resource_id(resource_id)
        subscription_name = _text(row.get("subscription_name")) or subscription_id
        resource_group = (
            _text(row.get("resource_group_name"))
            or _pick_first(raw_mapping, ("ResourceGroupName",))
            or _resource_group_from_resource_id(resource_id)
        )
        resource_name = _pick_first(raw_mapping, _RESOURCE_NAME_FIELDS) or _resource_name_from_resource_id(resource_id)
        service_name = (
            _text(row.get("service_name"))
            or _text(row.get("consumed_service"))
            or _pick_first(raw_mapping, ("ServiceName", "ConsumedService", "MeterCategory"))
        )
        meter_category = _text(row.get("meter_category")) or _pick_first(raw_mapping, ("MeterCategory",))
        location = _pick_first(raw_mapping, _LOCATION_FIELDS)
        currency = _text(row.get("currency")) or _pick_first(raw_mapping, ("BillingCurrencyCode", "Currency"))
        charge_type = _text(row.get("charge_type")) or _pick_first(raw_mapping, ("ChargeType",))
        tags = {}
        for field in _TAG_FIELDS:
            tags = _parse_tags(raw_mapping.get(field))
            if tags:
                break
        pricing_model = _normalize_pricing_model(raw_mapping, charge_type)
        usage_quantity = _float(_pick_first(raw_mapping, _USAGE_QUANTITY_FIELDS))
        row_number = int(row.get("row_number") or 0)
        return (
            f"{delivery_key}:{row_number or resource_id or resource_name or usage_date.isoformat()}",
            usage_date.isoformat(),
            subscription_id,
            subscription_name,
            resource_group,
            resource_name,
            resource_id,
            service_name,
            meter_category,
            location,
            _float(row.get("actual_cost")),
            _float(row.get("amortized_cost")),
            usage_quantity,
            json.dumps(tags, sort_keys=True),
            pricing_model,
            charge_type,
            scope_key,
            currency,
            delivery_key,
        )

    def _normalize_price_sheet_row(
        self,
        row: Mapping[str, Any],
        *,
        scope_key: str,
        delivery_key: str,
    ) -> tuple[Any, ...] | None:
        row_number = _int(row.get("row_number"))
        meter_id = _text(row.get("meter_id"))
        product_id = _text(row.get("product_id"))
        sku_id = _text(row.get("sku_id"))
        if not (meter_id or product_id or sku_id):
            return None
        return (
            f"{delivery_key}:{row_number or meter_id or product_id or sku_id}",
            meter_id,
            _text(row.get("meter_name")),
            _text(row.get("meter_category")),
            _text(row.get("meter_subcategory")),
            _text(row.get("meter_region")),
            product_id,
            _text(row.get("product_name")),
            sku_id,
            _text(row.get("sku_name")),
            _text(row.get("service_family")),
            _text(row.get("price_type")),
            _text(row.get("term")),
            _text(row.get("unit_of_measure")),
            _float(row.get("unit_price")),
            _float(row.get("market_price")),
            _float(row.get("base_price")),
            _text(row.get("currency")) or "USD",
            _text(row.get("billing_currency")) or _text(row.get("currency")) or "USD",
            _parse_iso_date(row.get("effective_start_date")),
            _parse_iso_date(row.get("effective_end_date")),
            scope_key,
            delivery_key,
            json.dumps(dict(row.get("raw") or {}), sort_keys=True),
        )

    def _normalize_reservation_recommendation_row(
        self,
        row: Mapping[str, Any],
        *,
        scope_key: str,
        delivery_key: str,
    ) -> tuple[Any, ...] | None:
        row_number = _int(row.get("row_number"))
        sku_name = _text(row.get("sku_name"))
        subscription_id = _text(row.get("subscription_id"))
        if not (sku_name or subscription_id):
            return None
        return (
            f"{delivery_key}:{row_number or sku_name or subscription_id}",
            subscription_id,
            _text(row.get("location")),
            sku_name,
            _text(row.get("resource_type")),
            _text(row.get("scope")),
            _text(row.get("term")),
            _float(row.get("lookback_period")),
            _float(row.get("recommended_quantity")),
            _float(row.get("recommended_quantity_normalized")),
            _float(row.get("net_savings")),
            _float(row.get("cost_without_reserved_instances")),
            _float(row.get("total_cost_with_reserved_instances")),
            _text(row.get("meter_id")),
            _float(row.get("instance_flexibility_ratio")),
            _parse_iso_date(row.get("first_usage_date")),
            scope_key,
            delivery_key,
            json.dumps(dict(row.get("raw") or {}), sort_keys=True),
        )

    @staticmethod
    def _resource_group_label(item: Mapping[str, Any]) -> str:
        group = _text(item.get("resource_group"))
        if not group:
            return ""
        subscription = _text(item.get("subscription_name") or item.get("subscription_id"))
        return f"{subscription} / {group}" if subscription else group

    @staticmethod
    def _recommendation_sort_key(item: Mapping[str, Any]) -> tuple[float, int, int, int, str]:
        savings_value = item.get("estimated_monthly_savings")
        savings_sort = -(float(savings_value) if savings_value is not None else -1.0)
        effort_rank = {"low": 0, "medium": 1, "high": 2}.get(_text(item.get("effort")).lower(), 99)
        risk_rank = {"low": 0, "medium": 1, "high": 2}.get(_text(item.get("risk")).lower(), 99)
        confidence_rank = {"high": 0, "medium": 1, "low": 2}.get(_text(item.get("confidence")).lower(), 99)
        return (
            savings_sort,
            effort_rank,
            risk_rank,
            confidence_rank,
            _text(item.get("title")).lower(),
        )

    @staticmethod
    def _aggregate_savings_rows(
        items: list[dict[str, Any]],
        label_getter: Any,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for item in items:
            label = _text(label_getter(item))
            if not label:
                continue
            bucket = buckets.setdefault(
                label,
                {"label": label, "count": 0, "estimated_monthly_savings": 0.0},
            )
            bucket["count"] += 1
            bucket["estimated_monthly_savings"] += _float(item.get("estimated_monthly_savings"))

        rows = list(buckets.values())
        rows.sort(
            key=lambda row: (
                -_float(row.get("estimated_monthly_savings")),
                -_int(row.get("count")),
                _text(row.get("label")).lower(),
            )
        )
        if limit is not None:
            rows = rows[:limit]
        for row in rows:
            row["estimated_monthly_savings"] = round(_float(row.get("estimated_monthly_savings")), 2)
        return rows

    @staticmethod
    def _aggregate_count_rows(
        items: list[dict[str, Any]],
        field_name: str,
        *,
        order: list[str],
    ) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for item in items:
            label = _text(item.get(field_name)).lower()
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1
        return [{"label": label, "count": counts[label]} for label in order if counts.get(label)]

    @staticmethod
    def _recommendation_order_sql() -> str:
        return """
            CASE WHEN estimated_monthly_savings IS NULL THEN 1 ELSE 0 END ASC,
            estimated_monthly_savings DESC,
            CASE LOWER(COALESCE(effort, ''))
                WHEN 'low' THEN 0
                WHEN 'medium' THEN 1
                WHEN 'high' THEN 2
                ELSE 99
            END ASC,
            CASE LOWER(COALESCE(risk, ''))
                WHEN 'low' THEN 0
                WHEN 'medium' THEN 1
                WHEN 'high' THEN 2
                ELSE 99
            END ASC,
            CASE LOWER(COALESCE(confidence, ''))
                WHEN 'high' THEN 0
                WHEN 'medium' THEN 1
                WHEN 'low' THEN 2
                ELSE 99
            END ASC,
            LOWER(COALESCE(title, '')) ASC
        """

    @staticmethod
    def _recommendation_select_columns_sql() -> str:
        return """
            recommendation_id,
            category,
            opportunity_type,
            source,
            title,
            summary,
            subscription_id,
            subscription_name,
            resource_group,
            location,
            resource_id,
            resource_name,
            resource_type,
            current_monthly_cost,
            estimated_monthly_savings,
            currency,
            quantified,
            estimate_basis,
            effort,
            risk,
            confidence,
            recommended_steps_json,
            evidence_json,
            portal_url,
            follow_up_route,
            lifecycle_status,
            action_state,
            dismissed_reason,
            source_version,
            source_refreshed_at,
            created_at,
            updated_at
        """

    @staticmethod
    def _build_recommendation_filter_sql(
        *,
        search: str = "",
        category: str = "",
        opportunity_type: str = "",
        subscription_id: str = "",
        resource_group: str = "",
        effort: str = "",
        risk: str = "",
        confidence: str = "",
        quantified_only: bool = False,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        def _add_exact(field_name: str, value: str) -> None:
            text = _text(value).lower()
            if not text:
                return
            clauses.append(f"LOWER(COALESCE({field_name}, '')) = ?")
            params.append(text)

        _add_exact("category", category)
        _add_exact("opportunity_type", opportunity_type)
        _add_exact("subscription_id", subscription_id)
        _add_exact("resource_group", resource_group)
        _add_exact("effort", effort)
        _add_exact("risk", risk)
        _add_exact("confidence", confidence)
        if quantified_only:
            clauses.append("quantified = TRUE")

        search_text = _text(search).lower()
        if search_text:
            clauses.append(
                """
                LOWER(
                    COALESCE(title, '') || ' ' ||
                    COALESCE(summary, '') || ' ' ||
                    COALESCE(resource_name, '') || ' ' ||
                    COALESCE(resource_type, '') || ' ' ||
                    COALESCE(subscription_name, '') || ' ' ||
                    COALESCE(subscription_id, '') || ' ' ||
                    COALESCE(resource_group, '') || ' ' ||
                    COALESCE(location, '') || ' ' ||
                    COALESCE(category, '') || ' ' ||
                    COALESCE(opportunity_type, '') || ' ' ||
                    COALESCE(recommended_steps_json, '') || ' ' ||
                    COALESCE(evidence_json, '')
                ) LIKE ?
                """
            )
            params.append(f"%{search_text}%")

        if not clauses:
            return "", params
        return "WHERE " + " AND ".join(clauses), params

    def _reservation_export_recommendations(self, conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            WITH subscription_names AS (
                SELECT
                    subscription_id,
                    MIN(COALESCE(NULLIF(subscription_name, ''), subscription_id)) AS subscription_name
                FROM cost_records
                GROUP BY subscription_id
            ),
            price_lookup AS (
                SELECT
                    meter_id,
                    MIN(COALESCE(NULLIF(product_name, ''), NULLIF(meter_name, ''), NULLIF(sku_name, ''))) AS product_name,
                    MIN(NULLIF(unit_of_measure, '')) AS unit_of_measure,
                    MIN(currency) AS currency,
                    MIN(unit_price) AS unit_price
                FROM price_sheet_rows
                GROUP BY meter_id
            )
            SELECT
                r.recommendation_row_id,
                r.subscription_id,
                COALESCE(s.subscription_name, r.subscription_id) AS subscription_name,
                r.location,
                r.sku_name,
                r.resource_type,
                r.scope,
                r.term,
                r.lookback_period,
                r.recommended_quantity,
                r.recommended_quantity_normalized,
                r.net_savings,
                r.cost_without_reserved_instances,
                r.total_cost_with_reserved_instances,
                r.meter_id,
                r.instance_flexibility_ratio,
                r.first_usage_date,
                r.scope_key,
                r.source_delivery_key,
                COALESCE(p.product_name, '') AS product_name,
                COALESCE(p.unit_of_measure, '') AS unit_of_measure,
                COALESCE(p.currency, 'USD') AS currency,
                p.unit_price
            FROM reservation_recommendation_rows AS r
            LEFT JOIN subscription_names AS s
                ON s.subscription_id = r.subscription_id
            LEFT JOIN price_lookup AS p
                ON p.meter_id = r.meter_id
            ORDER BY r.net_savings DESC, r.subscription_id ASC, r.sku_name ASC
            """
        ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            recommended_quantity = _float(row[9])
            term = _text(row[7]) or "Reservation"
            product_name = _text(row[19])
            title_name = product_name or _text(row[4]) or "Reserved capacity"
            evidence: list[dict[str, str]] = [
                {"label": "Subscription", "value": _text(row[2]) or _text(row[1])},
                {"label": "Term", "value": term},
                {"label": "Scope", "value": _text(row[6]) or "Shared"},
                {"label": "Recommended quantity", "value": str(int(recommended_quantity) if recommended_quantity.is_integer() else recommended_quantity)},
            ]
            if _text(row[3]):
                evidence.append({"label": "Location", "value": _text(row[3])})
            if _float(row[11]) > 0:
                evidence.append({"label": "Estimated monthly savings", "value": f"{round(_float(row[11]), 2)} {_text(row[21]) or 'USD'}"})
            if _float(row[12]) > 0:
                evidence.append({"label": "Current monthly cost", "value": f"{round(_float(row[12]), 2)} {_text(row[21]) or 'USD'}"})
            if _float(row[13]) > 0:
                evidence.append({"label": "Projected monthly cost with reservation", "value": f"{round(_float(row[13]), 2)} {_text(row[21]) or 'USD'}"})
            if _text(row[20]):
                evidence.append({"label": "Unit of measure", "value": _text(row[20])})
            if row[22] is not None and _float(row[22]) > 0:
                evidence.append({"label": "Observed unit price", "value": f"{round(_float(row[22]), 4)} {_text(row[21]) or 'USD'}"})
            result.append(
                {
                    "id": f"reservation-export:{_text(row[17])}:{_text(row[0])}",
                    "category": "commitment",
                    "opportunity_type": "reservation_purchase",
                    "source": "heuristic",
                    "title": f"Purchase {title_name} reservation",
                    "summary": (
                        f"Azure Cost Management reservation recommendations suggest buying "
                        f"{recommended_quantity:g} x {title_name} in {_text(row[3]) or 'the target region'} "
                        f"for a {term.lower()} term."
                    ),
                    "subscription_id": _text(row[1]),
                    "subscription_name": _text(row[2]),
                    "resource_group": "",
                    "location": _text(row[3]),
                    "resource_id": "",
                    "resource_name": _text(row[4]),
                    "resource_type": _text(row[5]) or "Microsoft.Compute/virtualMachines",
                    "current_monthly_cost": round(_float(row[12]), 2) if _float(row[12]) > 0 else None,
                    "estimated_monthly_savings": round(_float(row[11]), 2) if _float(row[11]) > 0 else None,
                    "currency": _text(row[21]) or "USD",
                    "quantified": _float(row[11]) > 0,
                    "estimate_basis": "Azure Cost Management reservation recommendations export.",
                    "effort": "medium",
                    "risk": "low",
                    "confidence": "high",
                    "recommended_steps": [
                        "Validate that the covered workload has steady baseline usage.",
                        "Confirm the reservation scope and term with the service owner.",
                        "Purchase the reservation once sizing and ownership are confirmed.",
                    ],
                    "evidence": evidence,
                    "portal_url": "https://portal.azure.com/",
                    "follow_up_route": "/azure/savings",
                }
            )
        return result

    def _normalize_recommendation_record(
        self,
        item: Mapping[str, Any],
        *,
        source_version: str,
        source_refreshed_at: datetime | None,
        existing_state: Mapping[str, Any] | None,
    ) -> tuple[Any, ...]:
        recommendation_id = _text(item.get("id")) or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        created_at = (
            _parse_iso_datetime(existing_state.get("created_at")) if isinstance(existing_state, Mapping) else None
        ) or now
        lifecycle_status = (
            _text(existing_state.get("lifecycle_status")) if isinstance(existing_state, Mapping) else ""
        ) or _RECOMMENDATION_STATUS_OPEN
        action_state = (
            _text(existing_state.get("action_state")) if isinstance(existing_state, Mapping) else ""
        ) or _RECOMMENDATION_ACTION_STATE_NONE
        dismissed_reason = _text(existing_state.get("dismissed_reason")) if isinstance(existing_state, Mapping) else ""
        return (
            recommendation_id,
            _text(item.get("category")) or "other",
            _text(item.get("opportunity_type")),
            _text(item.get("source")) or "heuristic",
            _text(item.get("title")) or "Azure recommendation",
            _text(item.get("summary")),
            _text(item.get("subscription_id")),
            _text(item.get("subscription_name")),
            _text(item.get("resource_group")),
            _text(item.get("location")),
            _text(item.get("resource_id")),
            _text(item.get("resource_name")),
            _text(item.get("resource_type")),
            _float(item.get("current_monthly_cost")) if item.get("current_monthly_cost") is not None else None,
            _float(item.get("estimated_monthly_savings")) if item.get("estimated_monthly_savings") is not None else None,
            _text(item.get("currency")) or "USD",
            bool(item.get("quantified")),
            _text(item.get("estimate_basis")),
            _text(item.get("effort")) or "medium",
            _text(item.get("risk")) or "medium",
            _text(item.get("confidence")) or "medium",
            json.dumps(list(item.get("recommended_steps") or []), sort_keys=False),
            json.dumps(list(item.get("evidence") or []), sort_keys=False),
            _text(item.get("portal_url")),
            _text(item.get("follow_up_route")),
            lifecycle_status,
            action_state,
            dismissed_reason,
            source_version,
            source_refreshed_at,
            created_at,
            now,
        )

    def _hydrate_recommendation_rows(self, rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "id": _text(row[0]),
                    "category": _text(row[1]) or "other",
                    "opportunity_type": _text(row[2]),
                    "source": _text(row[3]) or "heuristic",
                    "title": _text(row[4]),
                    "summary": _text(row[5]),
                    "subscription_id": _text(row[6]),
                    "subscription_name": _text(row[7]),
                    "resource_group": _text(row[8]),
                    "location": _text(row[9]),
                    "resource_id": _text(row[10]),
                    "resource_name": _text(row[11]),
                    "resource_type": _text(row[12]),
                    "current_monthly_cost": round(_float(row[13]), 2) if row[13] is not None else None,
                    "estimated_monthly_savings": round(_float(row[14]), 2) if row[14] is not None else None,
                    "currency": _text(row[15]) or "USD",
                    "quantified": bool(row[16]),
                    "estimate_basis": _text(row[17]),
                    "effort": _text(row[18]) or "medium",
                    "risk": _text(row[19]) or "medium",
                    "confidence": _text(row[20]) or "medium",
                    "recommended_steps": _parse_json_list(row[21]),
                    "evidence": _parse_json_list(row[22]),
                    "portal_url": _text(row[23]),
                    "follow_up_route": _text(row[24]),
                    "lifecycle_status": _text(row[25]) or _RECOMMENDATION_STATUS_OPEN,
                    "action_state": _text(row[26]) or _RECOMMENDATION_ACTION_STATE_NONE,
                    "dismissed_reason": _text(row[27]),
                    "source_version": _text(row[28]),
                    "source_refreshed_at": _text(row[29]),
                    "created_at": _text(row[30]),
                    "updated_at": _text(row[31]),
                }
            )
        return result

    def _current_recommendation_source_version(
        self,
        conn: duckdb.DuckDBPyConnection,
        cache_source_version: str,
        inventory_source_version: str = "",
    ) -> tuple[str, datetime | None]:
        cost_import = self._latest_import_metadata(dataset_family="focus")
        cost_version = ""
        cost_refreshed_at = None
        if cost_import is not None:
            cost_version = (
                _text(cost_import.get("source_updated_at_text"))
                or _text(cost_import.get("imported_at"))
                or _text(cost_import.get("delivery_key"))
            )
            cost_refreshed_at = _parse_iso_datetime(
                cost_import.get("source_updated_at") or cost_import.get("imported_at")
            )
        reservation_import = self._latest_import_metadata(dataset_family="reservation_recommendations")
        reservation_version = ""
        reservation_refreshed_at = None
        if reservation_import is not None:
            reservation_version = (
                _text(reservation_import.get("source_updated_at_text"))
                or _text(reservation_import.get("imported_at"))
                or _text(reservation_import.get("delivery_key"))
            )
            reservation_refreshed_at = _parse_iso_datetime(
                reservation_import.get("source_updated_at") or reservation_import.get("imported_at")
            )
        refreshed_candidates = [item for item in (cost_refreshed_at, reservation_refreshed_at) if item is not None]
        refreshed_at = max(refreshed_candidates) if refreshed_candidates else None
        composite = (
            f"cache:{cache_source_version or 'none'}"
            f"|inventory:{inventory_source_version or 'none'}"
            f"|cost:{cost_version or 'none'}"
            f"|reservation:{reservation_version or 'none'}"
        )
        return composite, refreshed_at

    def refresh_recommendations_snapshot(
        self,
        opportunities: list[Mapping[str, Any]],
        *,
        cache_source_version: str = "",
        cache_source_refreshed_at: str = "",
        cache_resources: list[Mapping[str, Any]] | None = None,
        inventory_source_version: str = "",
        snapshot_name: str = "azure_savings_workspace",
    ) -> dict[str, Any]:
        source_refreshed_at = _parse_iso_datetime(cache_source_refreshed_at)
        with self._lock:
            conn = self._connect()
            try:
                source_version, export_refreshed_at = self._current_recommendation_source_version(
                    conn,
                    cache_source_version,
                    inventory_source_version=inventory_source_version,
                )
                if source_refreshed_at is None or (export_refreshed_at is not None and export_refreshed_at > source_refreshed_at):
                    source_refreshed_at = export_refreshed_at

                refresh_state = conn.execute(
                    """
                    SELECT source_version, row_count
                    FROM recommendation_refresh_state
                    WHERE snapshot_name = ?
                    LIMIT 1
                    """,
                    [snapshot_name],
                ).fetchone()
                existing_state_rows = conn.execute(
                    """
                    SELECT recommendation_id, lifecycle_status, action_state, dismissed_reason, created_at
                    FROM recommendations
                    """
                ).fetchall()
                existing_state = {
                    _text(row[0]): {
                        "lifecycle_status": _text(row[1]),
                        "action_state": _text(row[2]),
                        "dismissed_reason": _text(row[3]),
                        "created_at": _text(row[4]),
                    }
                    for row in existing_state_rows
                }

                export_opportunities = self._reservation_export_recommendations(conn)
                cache_payload = [dict(item) for item in opportunities if isinstance(item, Mapping)]
                bridge_rows = self._resource_cost_bridge_rows(cache_resources or [])
                bridge_by_id = {
                    _normalize_resource_id(item.get("resource_id")): item
                    for item in bridge_rows["rows"]
                    if _normalize_resource_id(item.get("resource_id"))
                }
                bridge_by_lookup = {
                    _resource_lookup_key(item.get("subscription_id"), item.get("resource_group"), item.get("resource_name")): item
                    for item in bridge_rows["rows"]
                    if all(
                        _resource_lookup_key(item.get("subscription_id"), item.get("resource_group"), item.get("resource_name"))
                    )
                }
                for item in cache_payload:
                    bridge_row = None
                    resource_id = _normalize_resource_id(item.get("resource_id"))
                    if resource_id:
                        bridge_row = bridge_by_id.get(resource_id)
                    if bridge_row is None:
                        bridge_row = bridge_by_lookup.get(
                            _resource_lookup_key(
                                item.get("subscription_id"),
                                item.get("resource_group"),
                                item.get("resource_name"),
                            )
                        )
                    if bridge_row is None:
                        continue
                    if item.get("current_monthly_cost") in (None, "", 0, 0.0):
                        item["current_monthly_cost"] = round(_float(bridge_row.get("actual_cost")), 2)
                    if not _text(item.get("resource_type")):
                        item["resource_type"] = _text(bridge_row.get("inventory_resource_type"))
                    evidence = list(item.get("evidence") or [])
                    evidence.append(
                        {
                            "label": "Export-backed current monthly cost",
                            "value": f"{round(_float(bridge_row.get('actual_cost')), 2)} {_text(bridge_row.get('currency') or 'USD')}",
                        }
                    )
                    item["evidence"] = evidence
                    estimate_basis = _text(item.get("estimate_basis"))
                    if "resource-cost bridge" not in estimate_basis.lower():
                        item["estimate_basis"] = (
                            f"{estimate_basis} " if estimate_basis else ""
                        ) + "Current monthly cost bridged from export-backed cost facts joined to Azure inventory."
                if export_opportunities:
                    cache_payload = [item for item in cache_payload if _text(item.get("category")).lower() != "commitment"]
                aks_visibility_rows = self.list_aks_cost_visibility(cache_resources or [])
                combined = cache_payload + export_opportunities + aks_visibility_rows
                normalized = [
                    self._normalize_recommendation_record(
                        item,
                        source_version=source_version,
                        source_refreshed_at=source_refreshed_at,
                        existing_state=existing_state.get(_text(item.get("id"))),
                    )
                    for item in combined
                ]
                if refresh_state and _text(refresh_state[0]) == source_version and _int(refresh_state[1]) == len(normalized):
                    return {
                        "available": self.has_recommendations(),
                        "refreshed": False,
                        "reason": "already_current",
                        "row_count": len(normalized),
                        "source_version": source_version,
                    }

                conn.execute("DELETE FROM recommendations")
                if normalized:
                    conn.executemany(
                        """
                        INSERT INTO recommendations (
                            recommendation_id,
                            category,
                            opportunity_type,
                            source,
                            title,
                            summary,
                            subscription_id,
                            subscription_name,
                            resource_group,
                            location,
                            resource_id,
                            resource_name,
                            resource_type,
                            current_monthly_cost,
                            estimated_monthly_savings,
                            currency,
                            quantified,
                            estimate_basis,
                            effort,
                            risk,
                            confidence,
                            recommended_steps_json,
                            evidence_json,
                            portal_url,
                            follow_up_route,
                            lifecycle_status,
                            action_state,
                            dismissed_reason,
                            source_version,
                            source_refreshed_at,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        normalized,
                    )
                conn.execute("DELETE FROM recommendation_refresh_state WHERE snapshot_name = ?", [snapshot_name])
                conn.execute(
                    """
                    INSERT INTO recommendation_refresh_state (
                        snapshot_name,
                        source_version,
                        source_refreshed_at,
                        row_count,
                        refreshed_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [snapshot_name, source_version, source_refreshed_at, len(normalized), datetime.now(timezone.utc)],
                )
            finally:
                conn.close()

        return {
            "available": self.has_recommendations(),
            "refreshed": True,
            "row_count": len(normalized),
            "source_version": source_version,
        }

    def _recommendation_exists(self, conn: duckdb.DuckDBPyConnection, recommendation_id: str) -> bool:
        row = conn.execute(
            """
            SELECT 1
            FROM recommendations
            WHERE recommendation_id = ?
            LIMIT 1
            """,
            [recommendation_id],
        ).fetchone()
        return row is not None

    def _record_recommendation_action_event(
        self,
        conn: duckdb.DuckDBPyConnection,
        *,
        recommendation_id: str,
        action_type: str,
        action_status: str,
        actor_type: str = "",
        actor_id: str = "",
        note: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc)
        payload = {
            "event_id": str(uuid.uuid4()),
            "recommendation_id": recommendation_id,
            "action_type": _text(action_type),
            "action_status": _text(action_status),
            "actor_type": _text(actor_type),
            "actor_id": _text(actor_id),
            "note": _text(note),
            "metadata_json": json.dumps(dict(metadata or {}), sort_keys=True, default=str),
            "created_at": created_at,
        }
        conn.execute(
            """
            INSERT INTO recommendation_action_events (
                event_id,
                recommendation_id,
                action_type,
                action_status,
                actor_type,
                actor_id,
                note,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                payload["event_id"],
                payload["recommendation_id"],
                payload["action_type"],
                payload["action_status"],
                payload["actor_type"],
                payload["actor_id"],
                payload["note"],
                payload["metadata_json"],
                payload["created_at"],
            ],
        )
        return {
            "event_id": payload["event_id"],
            "recommendation_id": payload["recommendation_id"],
            "action_type": payload["action_type"],
            "action_status": payload["action_status"],
            "actor_type": payload["actor_type"],
            "actor_id": payload["actor_id"],
            "note": payload["note"],
            "metadata": dict(metadata or {}),
            "created_at": created_at.isoformat(),
        }

    def _update_recommendation_state(
        self,
        *,
        recommendation_id: str,
        lifecycle_status: str | None = None,
        action_state: str | None = None,
        dismissed_reason: str | None = None,
        action_type: str,
        action_status: str,
        actor_type: str = "",
        actor_id: str = "",
        note: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        recommendation_id = _text(recommendation_id)
        if not recommendation_id:
            return None
        lifecycle_status_text = _text(lifecycle_status).lower() if lifecycle_status is not None else None
        action_state_text = _text(action_state).lower() if action_state is not None else None
        if lifecycle_status_text is not None and lifecycle_status_text not in _VALID_RECOMMENDATION_LIFECYCLE_STATES:
            raise ValueError(f"Unsupported recommendation lifecycle status: {lifecycle_status}")
        if action_state_text is not None and action_state_text not in _VALID_RECOMMENDATION_ACTION_STATES:
            raise ValueError(f"Unsupported recommendation action state: {action_state}")

        with self._lock:
            conn = self._connect()
            try:
                if not self._recommendation_exists(conn, recommendation_id):
                    return None
                assignments: list[str] = ["updated_at = ?"]
                values: list[Any] = [datetime.now(timezone.utc)]
                if lifecycle_status_text is not None:
                    assignments.append("lifecycle_status = ?")
                    values.append(lifecycle_status_text)
                if action_state_text is not None:
                    assignments.append("action_state = ?")
                    values.append(action_state_text)
                if dismissed_reason is not None:
                    assignments.append("dismissed_reason = ?")
                    values.append(_text(dismissed_reason))
                values.append(recommendation_id)
                conn.execute(
                    f"""
                    UPDATE recommendations
                    SET {", ".join(assignments)}
                    WHERE recommendation_id = ?
                    """,
                    values,
                )
                event = self._record_recommendation_action_event(
                    conn,
                    recommendation_id=recommendation_id,
                    action_type=action_type,
                    action_status=action_status,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    note=note,
                    metadata=metadata,
                )
            finally:
                conn.close()

        payload = self.get_recommendation(recommendation_id)
        if payload is None:
            return None
        payload["last_action_event"] = event
        return payload

    def dismiss_recommendation(
        self,
        recommendation_id: str,
        *,
        reason: str = "",
        actor_type: str = "",
        actor_id: str = "",
    ) -> dict[str, Any] | None:
        return self._update_recommendation_state(
            recommendation_id=recommendation_id,
            lifecycle_status=_RECOMMENDATION_STATUS_DISMISSED,
            dismissed_reason=reason,
            action_type="dismiss",
            action_status="completed",
            actor_type=actor_type,
            actor_id=actor_id,
            note=reason,
            metadata={"dismissed_reason": _text(reason)},
        )

    def reopen_recommendation(
        self,
        recommendation_id: str,
        *,
        actor_type: str = "",
        actor_id: str = "",
        note: str = "",
    ) -> dict[str, Any] | None:
        return self._update_recommendation_state(
            recommendation_id=recommendation_id,
            lifecycle_status=_RECOMMENDATION_STATUS_OPEN,
            dismissed_reason="",
            action_type="reopen",
            action_status="completed",
            actor_type=actor_type,
            actor_id=actor_id,
            note=note,
        )

    def update_recommendation_action_state(
        self,
        recommendation_id: str,
        *,
        action_state: str,
        action_type: str = "",
        actor_type: str = "",
        actor_id: str = "",
        note: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        action_state_text = _text(action_state).lower() or _RECOMMENDATION_ACTION_STATE_NONE
        return self._update_recommendation_state(
            recommendation_id=recommendation_id,
            action_state=action_state_text,
            action_type=_text(action_type) or "action_state_update",
            action_status="completed",
            actor_type=actor_type,
            actor_id=actor_id,
            note=note,
            metadata={**dict(metadata or {}), "action_state": action_state_text},
        )

    def record_recommendation_action_event(
        self,
        recommendation_id: str,
        *,
        action_type: str,
        action_status: str,
        actor_type: str = "",
        actor_id: str = "",
        note: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self._update_recommendation_state(
            recommendation_id=recommendation_id,
            action_type=action_type,
            action_status=action_status,
            actor_type=actor_type,
            actor_id=actor_id,
            note=note,
            metadata=metadata,
        )

    def list_recommendation_action_history(self, recommendation_id: str) -> list[dict[str, Any]]:
        recommendation_id = _text(recommendation_id)
        if not recommendation_id:
            return []
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT
                        event_id,
                        recommendation_id,
                        action_type,
                        action_status,
                        actor_type,
                        actor_id,
                        note,
                        metadata_json,
                        created_at
                    FROM recommendation_action_events
                    WHERE recommendation_id = ?
                    ORDER BY created_at DESC, event_id DESC
                    """,
                    [recommendation_id],
                ).fetchall()
            finally:
                conn.close()
        return [
            {
                "event_id": _text(row[0]),
                "recommendation_id": _text(row[1]),
                "action_type": _text(row[2]),
                "action_status": _text(row[3]),
                "actor_type": _text(row[4]),
                "actor_id": _text(row[5]),
                "note": _text(row[6]),
                "metadata": json.loads(_text(row[7]) or "{}") if _text(row[7]) else {},
                "created_at": _text(row[8]),
            }
            for row in rows
        ]

    def get_recommendation_action_contract(self, recommendation_id: str) -> dict[str, Any] | None:
        recommendation = self.get_recommendation(recommendation_id)
        if recommendation is None:
            return None

        lifecycle_status = _text(recommendation.get("lifecycle_status")).lower() or _RECOMMENDATION_STATUS_OPEN
        current_action_state = _text(recommendation.get("action_state")).lower() or _RECOMMENDATION_ACTION_STATE_NONE
        history = self.list_recommendation_action_history(recommendation_id)
        latest_event_by_type: dict[str, dict[str, Any]] = {}
        for event in history:
            action_type = _text(event.get("action_type")).lower()
            if action_type and action_type not in latest_event_by_type:
                latest_event_by_type[action_type] = dict(event)

        actions: list[dict[str, Any]] = []
        for action_type, definition in _RECOMMENDATION_ACTION_CONTRACTS.items():
            pending_action_state = _text(definition.get("pending_action_state"))
            completed_action_state = _text(definition.get("completed_action_state"))
            blocked_reason = ""
            status = "available"
            can_execute = True
            repeatable = bool(definition.get("repeatable"))
            options: list[dict[str, Any]] = []

            if action_type == "run_safe_script":
                options = self.list_recommendation_safe_hooks(recommendation)
                repeatable = True
                if not options:
                    status = "blocked"
                    can_execute = False
                    blocked_reason = "No safe remediation hooks are configured for this recommendation."
            if lifecycle_status == _RECOMMENDATION_STATUS_DISMISSED and action_type != "export":
                status = "blocked"
                can_execute = False
                blocked_reason = "Reopen the recommendation before using this action."
            elif pending_action_state and current_action_state == pending_action_state:
                status = "pending"
                can_execute = False
            elif completed_action_state and current_action_state == completed_action_state:
                status = "completed"
                can_execute = repeatable

            latest_event = dict(latest_event_by_type.get(action_type) or {})
            actions.append(
                {
                    "action_type": action_type,
                    "label": _text(definition.get("label")),
                    "description": _text(definition.get("description")),
                    "category": _text(definition.get("category")),
                    "status": status,
                    "can_execute": can_execute,
                    "requires_admin": bool(definition.get("requires_admin", True)),
                    "repeatable": repeatable,
                    "pending_action_state": pending_action_state,
                    "completed_action_state": completed_action_state,
                    "current_action_state": current_action_state,
                    "blocked_reason": blocked_reason,
                    "note_placeholder": _text(definition.get("note_placeholder")),
                    "metadata_fields": list(definition.get("metadata_fields") or []),
                    "options": options,
                    "latest_event": latest_event,
                }
            )

        return {
            "recommendation_id": _text(recommendation.get("id")),
            "lifecycle_status": lifecycle_status,
            "current_action_state": current_action_state,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "actions": actions,
        }

    def list_recommendation_safe_hooks(self, recommendation: Mapping[str, Any] | None) -> list[dict[str, Any]]:
        if recommendation is None or self._safe_hook_runner is None:
            return []
        return self._safe_hook_runner.list_hooks_for_recommendation(recommendation)

    def run_recommendation_safe_hook(
        self,
        recommendation_id: str,
        *,
        hook_key: str = "",
        dry_run: bool = True,
        actor_type: str = "user",
        actor_id: str = "",
        note: str = "",
    ) -> dict[str, Any] | None:
        recommendation = self.get_recommendation(recommendation_id)
        if recommendation is None:
            return None
        if self._safe_hook_runner is None:
            raise ValueError("No safe remediation hooks are configured for this recommendation.")

        result = self._safe_hook_runner.execute_hook(
            recommendation,
            hook_key=hook_key,
            dry_run=bool(dry_run),
            actor_id=actor_id,
            note=note,
        )
        metadata = {
            "hook_key": _text(result.get("hook_key")),
            "hook_label": _text(result.get("hook_label")),
            "dry_run": bool(result.get("dry_run")),
            "duration_ms": _int(result.get("duration_ms")),
            "exit_code": result.get("exit_code"),
            "output_excerpt": _text(result.get("output_excerpt")),
        }
        if _text(result.get("stderr_excerpt")):
            metadata["stderr_excerpt"] = _text(result.get("stderr_excerpt"))

        if not bool(result.get("success")):
            error_text = _text(result.get("error")) or "Safe remediation hook failed."
            metadata["error"] = error_text
            self.record_recommendation_action_event(
                recommendation_id,
                action_type="run_safe_script",
                action_status="failed",
                actor_type=actor_type,
                actor_id=actor_id,
                note=note,
                metadata=metadata,
            )
            raise RuntimeError(error_text)

        if bool(result.get("dry_run")):
            updated_recommendation = self.record_recommendation_action_event(
                recommendation_id,
                action_type="run_safe_script",
                action_status="dry_run",
                actor_type=actor_type,
                actor_id=actor_id,
                note=note,
                metadata=metadata,
            )
        else:
            updated_recommendation = self.update_recommendation_action_state(
                recommendation_id,
                action_state="script_executed",
                action_type="run_safe_script",
                actor_type=actor_type,
                actor_id=actor_id,
                note=note or f"Executed safe remediation hook {_text(result.get('hook_label')) or _text(result.get('hook_key'))}.",
                metadata=metadata,
            )

        return {
            "recommendation": updated_recommendation or recommendation,
            "hook_key": _text(result.get("hook_key")),
            "hook_label": _text(result.get("hook_label")),
            "action_status": _text(result.get("action_status")),
            "dry_run": bool(result.get("dry_run")),
            "started_at": _text(result.get("started_at")),
            "completed_at": _text(result.get("completed_at")),
            "duration_ms": _int(result.get("duration_ms")),
            "exit_code": result.get("exit_code"),
            "output_excerpt": _text(result.get("output_excerpt")),
        }

    def sync_from_export_store(self, store: Any | None) -> dict[str, Any]:
        """Import parsed Azure export deliveries from the existing export lane."""

        lister = getattr(store, "list_deliveries", None) if store is not None else None
        if not callable(lister):
            return {"available": self.has_cost_data(), "delivery_count": 0, "imported_count": 0, "skipped_count": 0}

        try:
            try:
                raw_deliveries = lister(parse_status="parsed") or []
            except TypeError:
                raw_deliveries = lister() or []
            deliveries = [
                dict(row)
                for row in raw_deliveries
                if isinstance(row, Mapping) and _text(row.get("parse_status")).lower() in {"", "parsed"}
            ]
        except Exception:
            logger.exception("Failed to list parsed Azure export deliveries for local FinOps sync")
            return {"available": self.has_cost_data(), "delivery_count": 0, "imported_count": 0, "skipped_count": 0}

        imported_count = 0
        skipped_count = 0
        imported_by_family: dict[str, int] = {}
        if not deliveries:
            return {
                "available": False,
                "delivery_count": 0,
                "imported_count": 0,
                "skipped_count": 0,
            }

        with self._lock:
            conn = self._connect()
            try:
                for delivery in deliveries:
                    delivery_key = _text(delivery.get("delivery_key"))
                    if not delivery_key:
                        skipped_count += 1
                        continue
                    staged_model = self._load_staged_model(delivery, store)
                    if not staged_model:
                        skipped_count += 1
                        continue
                    if not self._needs_import(conn, delivery):
                        skipped_count += 1
                        continue
                    descriptor = dataset_descriptor(delivery.get("dataset"))
                    dataset_family = descriptor.dataset_family

                    rows = staged_model.get("rows")
                    stage_rows = rows if isinstance(rows, list) else []
                    if dataset_family == "focus":
                        normalized = [
                            payload
                            for payload in (
                                self._normalize_cost_record(
                                    row,
                                    scope_key=_text(delivery.get("scope_key")),
                                    delivery_key=delivery_key,
                                )
                                for row in stage_rows
                                if isinstance(row, Mapping)
                            )
                            if payload is not None
                        ]
                        conn.execute("DELETE FROM cost_records WHERE source_delivery_key = ?", [delivery_key])
                        if normalized:
                            conn.executemany(
                                """
                                INSERT INTO cost_records (
                                    cost_record_id,
                                    date,
                                    subscription_id,
                                    subscription_name,
                                    resource_group,
                                    resource_name,
                                    resource_id,
                                    service_name,
                                    meter_category,
                                    location,
                                    cost_actual,
                                    cost_amortized,
                                    usage_quantity,
                                    tags_json,
                                    pricing_model,
                                    charge_type,
                                    scope_key,
                                    currency,
                                    source_delivery_key
                                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                normalized,
                            )
                    elif dataset_family == "price_sheet":
                        normalized = [
                            payload
                            for payload in (
                                self._normalize_price_sheet_row(
                                    row,
                                    scope_key=_text(delivery.get("scope_key")),
                                    delivery_key=delivery_key,
                                )
                                for row in stage_rows
                                if isinstance(row, Mapping)
                            )
                            if payload is not None
                        ]
                        conn.execute("DELETE FROM price_sheet_rows WHERE source_delivery_key = ?", [delivery_key])
                        if normalized:
                            conn.executemany(
                                """
                                INSERT INTO price_sheet_rows (
                                    price_row_id,
                                    meter_id,
                                    meter_name,
                                    meter_category,
                                    meter_subcategory,
                                    meter_region,
                                    product_id,
                                    product_name,
                                    sku_id,
                                    sku_name,
                                    service_family,
                                    price_type,
                                    term,
                                    unit_of_measure,
                                    unit_price,
                                    market_price,
                                    base_price,
                                    currency,
                                    billing_currency,
                                    effective_start_date,
                                    effective_end_date,
                                    scope_key,
                                    source_delivery_key,
                                    raw_json
                                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                normalized,
                            )
                    elif dataset_family == "reservation_recommendations":
                        normalized = [
                            payload
                            for payload in (
                                self._normalize_reservation_recommendation_row(
                                    row,
                                    scope_key=_text(delivery.get("scope_key")),
                                    delivery_key=delivery_key,
                                )
                                for row in stage_rows
                                if isinstance(row, Mapping)
                            )
                            if payload is not None
                        ]
                        conn.execute("DELETE FROM reservation_recommendation_rows WHERE source_delivery_key = ?", [delivery_key])
                        if normalized:
                            conn.executemany(
                                """
                                INSERT INTO reservation_recommendation_rows (
                                    recommendation_row_id,
                                    subscription_id,
                                    location,
                                    sku_name,
                                    resource_type,
                                    scope,
                                    term,
                                    lookback_period,
                                    recommended_quantity,
                                    recommended_quantity_normalized,
                                    net_savings,
                                    cost_without_reserved_instances,
                                    total_cost_with_reserved_instances,
                                    meter_id,
                                    instance_flexibility_ratio,
                                    first_usage_date,
                                    scope_key,
                                    source_delivery_key,
                                    raw_json
                                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                normalized,
                            )
                    else:
                        skipped_count += 1
                        continue
                    conn.execute("DELETE FROM finops_delivery_imports WHERE delivery_key = ?", [delivery_key])
                    conn.execute(
                        """
                        INSERT INTO finops_delivery_imports (
                            delivery_key,
                                dataset,
                                scope_key,
                                manifest_path,
                                parsed_at,
                                row_count,
                                source_updated_at,
                                source_updated_at_text,
                                imported_at
                            )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            delivery_key,
                            _text(delivery.get("dataset")),
                            _text(delivery.get("scope_key")),
                            _text(delivery.get("manifest_path")),
                            _text(delivery.get("parsed_at")) or None,
                            int(delivery.get("row_count") or 0),
                            self._source_updated_at(delivery),
                            self._source_updated_at_text(delivery),
                            datetime.now(timezone.utc),
                        ],
                    )
                    imported_count += 1
                    imported_by_family[dataset_family] = imported_by_family.get(dataset_family, 0) + 1
            finally:
                conn.close()

        return {
            "available": self.has_cost_data(),
            "delivery_count": len(deliveries),
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "imported_by_family": imported_by_family,
        }

    def has_cost_data(self) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT COUNT(*) FROM cost_records").fetchone()
            finally:
                conn.close()
        return bool(int((row or [0])[0] or 0))

    def has_ai_usage(self) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT COUNT(*) FROM ai_usage_records").fetchone()
            finally:
                conn.close()
        return bool(int((row or [0])[0] or 0))

    def has_recommendations(self) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()
            finally:
                conn.close()
        return bool(int((row or [0])[0] or 0))

    def get_cost_field_map(self) -> dict[str, Any]:
        return {
            "version": 1,
            "normalized_model": "CostRecord",
            "fields": json.loads(json.dumps(_COST_RECORD_FIELD_MAP)),
        }

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                cost_row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS record_count,
                        COUNT(DISTINCT source_delivery_key) AS delivery_count,
                        COUNT(DISTINCT subscription_id) AS subscription_count,
                        COUNT(DISTINCT COALESCE(NULLIF(service_name, ''), 'Unknown')) AS service_count,
                        COUNT(DISTINCT COALESCE(NULLIF(resource_group, ''), 'Unknown')) AS resource_group_count,
                        MIN(date) AS coverage_start,
                        MAX(date) AS coverage_end,
                        SUM(CASE WHEN COALESCE(tags_json, '') NOT IN ('', '{}') THEN 1 ELSE 0 END) AS tagged_records,
                        SUM(CASE WHEN usage_quantity > 0 THEN 1 ELSE 0 END) AS usage_quantity_records,
                        SUM(CASE WHEN COALESCE(pricing_model, '') != '' THEN 1 ELSE 0 END) AS pricing_model_records,
                        SUM(CASE WHEN COALESCE(resource_id, '') != '' THEN 1 ELSE 0 END) AS resource_id_records
                    FROM cost_records
                    """
                ).fetchone()
                import_row = conn.execute(
                    """
                    SELECT COUNT(*), MAX(imported_at), MAX(parsed_at)
                    FROM finops_delivery_imports
                    """
                ).fetchone()
                ai_row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS usage_records,
                        COALESCE(SUM(request_count), 0) AS request_count,
                        COALESCE(SUM(estimated_cost), 0) AS total_estimated_cost,
                        MIN(recorded_date) AS window_start,
                        MAX(recorded_date) AS window_end
                    FROM ai_usage_records
                    """
                ).fetchone()
                auxiliary_row = conn.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM price_sheet_rows) AS price_sheet_rows,
                        (SELECT COUNT(DISTINCT source_delivery_key) FROM price_sheet_rows) AS price_sheet_deliveries,
                        (SELECT COUNT(*) FROM reservation_recommendation_rows) AS reservation_rows,
                        (SELECT COUNT(DISTINCT source_delivery_key) FROM reservation_recommendation_rows) AS reservation_deliveries,
                        (SELECT COUNT(*) FROM recommendations) AS recommendation_rows,
                        (SELECT MAX(refreshed_at) FROM recommendation_refresh_state) AS recommendation_refreshed_at
                    """
                ).fetchone()
                allocation_row = conn.execute(
                    f"""
                    SELECT
                        (SELECT COUNT(*) FROM allocation_rules) AS rule_versions,
                        (SELECT COUNT(*) FROM ({_latest_rule_select_sql()}) latest_rules WHERE enabled = TRUE) AS active_rules,
                        (SELECT COUNT(*) FROM allocation_runs) AS allocation_runs,
                        (SELECT MAX(created_at) FROM allocation_runs) AS last_run_at,
                        (SELECT COUNT(*) FROM allocation_results) AS allocation_result_rows
                    """
                ).fetchone()
            finally:
                conn.close()

        record_count = _int(cost_row[0] if cost_row else 0)
        coverage = {
            "tags_pct": round((_int(cost_row[7] if cost_row else 0) / record_count) if record_count else 0.0, 4),
            "usage_quantity_pct": round((_int(cost_row[8] if cost_row else 0) / record_count) if record_count else 0.0, 4),
            "pricing_model_pct": round((_int(cost_row[9] if cost_row else 0) / record_count) if record_count else 0.0, 4),
            "resource_id_pct": round((_int(cost_row[10] if cost_row else 0) / record_count) if record_count else 0.0, 4),
        }
        return {
            "available": record_count > 0,
            "record_count": record_count,
            "delivery_count": _int(cost_row[1] if cost_row else 0),
            "subscription_count": _int(cost_row[2] if cost_row else 0),
            "service_count": _int(cost_row[3] if cost_row else 0),
            "resource_group_count": _int(cost_row[4] if cost_row else 0),
            "coverage_start": _text(cost_row[5] if cost_row else ""),
            "coverage_end": _text(cost_row[6] if cost_row else ""),
            "field_coverage": coverage,
            "field_map": self.get_cost_field_map(),
            "imports": {
                "count": _int(import_row[0] if import_row else 0),
                "last_imported_at": _text(import_row[1] if import_row else ""),
                "last_parsed_at": _text(import_row[2] if import_row else ""),
            },
            "ai_usage": {
                "available": _int(ai_row[0] if ai_row else 0) > 0,
                "usage_record_count": _int(ai_row[0] if ai_row else 0),
                "request_count": _int(ai_row[1] if ai_row else 0),
                "total_estimated_cost": round(_float(ai_row[2] if ai_row else 0), 6),
                "window_start": _text(ai_row[3] if ai_row else ""),
                "window_end": _text(ai_row[4] if ai_row else ""),
            },
            "auxiliary_datasets": {
                "price_sheet": {
                    "row_count": _int(auxiliary_row[0] if auxiliary_row else 0),
                    "delivery_count": _int(auxiliary_row[1] if auxiliary_row else 0),
                },
                "reservation_recommendations": {
                    "row_count": _int(auxiliary_row[2] if auxiliary_row else 0),
                    "delivery_count": _int(auxiliary_row[3] if auxiliary_row else 0),
                },
            },
            "recommendations": {
                "available": _int(auxiliary_row[4] if auxiliary_row else 0) > 0,
                "row_count": _int(auxiliary_row[4] if auxiliary_row else 0),
                "last_refreshed_at": _text(auxiliary_row[5] if auxiliary_row else ""),
            },
            "allocations": {
                "policy": self.get_allocation_policy(),
                "rule_version_count": _int(allocation_row[0] if allocation_row else 0),
                "active_rule_count": _int(allocation_row[1] if allocation_row else 0),
                "run_count": _int(allocation_row[2] if allocation_row else 0),
                "last_run_at": _text(allocation_row[3] if allocation_row else ""),
                "result_row_count": _int(allocation_row[4] if allocation_row else 0),
            },
        }

    def get_allocation_policy(self) -> dict[str, Any]:
        return json.loads(json.dumps(_ALLOCATION_POLICY))

    def _hydrate_allocation_rule_rows(self, rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
        hydrated: list[dict[str, Any]] = []
        for row in rows or []:
            hydrated.append(
                {
                    "rule_id": _text(row[0]),
                    "rule_version": _int(row[1]),
                    "name": _text(row[2]),
                    "description": _text(row[3]),
                    "rule_type": _text(row[4]).lower(),
                    "target_dimension": _text(row[5]).lower(),
                    "priority": _int(row[6]),
                    "enabled": bool(row[7]),
                    "condition": _parse_json_object(row[8]),
                    "allocation": _parse_json_object(row[9]),
                    "created_by": _text(row[10]),
                    "created_at": _text(row[11]),
                    "superseded_at": _text(row[12]),
                }
            )
        return hydrated

    def _latest_allocation_rule_rows(
        self,
        conn: duckdb.DuckDBPyConnection,
        *,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        where_sql = "" if include_inactive else "WHERE enabled = TRUE"
        rows = conn.execute(
            f"""
            SELECT *
            FROM ({_latest_rule_select_sql()}) AS latest_rules
            {where_sql}
            ORDER BY target_dimension ASC, priority ASC, name ASC, rule_id ASC
            """
        ).fetchall()
        return self._hydrate_allocation_rule_rows(rows)

    def get_allocation_rule(self, rule_id: str) -> dict[str, Any] | None:
        rule_id = _text(rule_id)
        if not rule_id:
            return None
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM ({_latest_rule_select_sql()}) AS latest_rules
                    WHERE rule_id = ?
                    """,
                    [rule_id],
                ).fetchall()
            finally:
                conn.close()
        hydrated = self._hydrate_allocation_rule_rows(rows)
        return hydrated[0] if hydrated else None

    def list_allocation_rules(
        self,
        *,
        include_inactive: bool = False,
        include_all_versions: bool = False,
    ) -> list[dict[str, Any]]:
        if include_all_versions:
            base_sql = """
                SELECT
                    rule_id,
                    rule_version,
                    name,
                    description,
                    rule_type,
                    target_dimension,
                    priority,
                    enabled,
                    condition_json,
                    allocation_json,
                    created_by,
                    created_at,
                    superseded_at
                FROM allocation_rules
            """
        else:
            base_sql = _latest_rule_select_sql()
        where_sql = "" if include_inactive else "WHERE enabled = TRUE"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM ({base_sql}) AS allocation_rules_view
                    {where_sql}
                    ORDER BY target_dimension ASC, priority ASC, created_at ASC, rule_id ASC, rule_version DESC
                    """
                ).fetchall()
            finally:
                conn.close()
        return self._hydrate_allocation_rule_rows(rows)

    def get_allocation_status(self) -> dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                rule_counts = conn.execute(
                    f"""
                    SELECT
                        (SELECT COUNT(*) FROM allocation_rules) AS rule_versions,
                        (SELECT COUNT(*) FROM ({_latest_rule_select_sql()}) latest_rules WHERE enabled = TRUE) AS active_rules,
                        (SELECT COUNT(*) FROM ({_latest_rule_select_sql()}) latest_rules WHERE enabled = FALSE) AS inactive_rules,
                        (SELECT COUNT(*) FROM allocation_runs) AS run_count,
                        (SELECT MAX(created_at) FROM allocation_runs) AS last_run_at
                    """
                ).fetchone()
            finally:
                conn.close()
        latest_run = self.list_allocation_runs(limit=1)
        return {
            "available": self.has_cost_data(),
            "policy": self.get_allocation_policy(),
            "rule_version_count": _int(rule_counts[0] if rule_counts else 0),
            "active_rule_count": _int(rule_counts[1] if rule_counts else 0),
            "inactive_rule_count": _int(rule_counts[2] if rule_counts else 0),
            "run_count": _int(rule_counts[3] if rule_counts else 0),
            "last_run_at": _text(rule_counts[4] if rule_counts else ""),
            "latest_run": latest_run[0] if latest_run else None,
        }

    def upsert_allocation_rule(
        self,
        *,
        name: str,
        rule_type: str,
        target_dimension: str,
        priority: int = 100,
        condition: Mapping[str, Any] | None = None,
        allocation: Mapping[str, Any] | None = None,
        description: str = "",
        enabled: bool = True,
        actor_id: str = "",
        rule_id: str = "",
    ) -> dict[str, Any]:
        name = _text(name)
        if not name:
            raise ValueError("Allocation rule name is required")
        rule_type = _text(rule_type).lower()
        if rule_type not in _VALID_ALLOCATION_RULE_TYPES:
            raise ValueError(f"Unsupported allocation rule type: {rule_type}")
        target_dimension = _text(target_dimension).lower()
        if target_dimension not in _VALID_ALLOCATION_DIMENSIONS:
            raise ValueError(f"Unsupported allocation target dimension: {target_dimension}")
        normalized_condition = _normalize_condition_payload(rule_type, condition)
        normalized_allocation = _normalize_allocation_payload(rule_type, allocation)
        now = datetime.now(timezone.utc)
        priority = max(_int(priority), 1)
        rule_id = _text(rule_id) or str(uuid.uuid4())
        created_by = _text(actor_id)

        with self._lock:
            conn = self._connect()
            try:
                previous_row = conn.execute(
                    """
                    SELECT
                        rule_id,
                        rule_version
                    FROM allocation_rules
                    WHERE rule_id = ?
                    ORDER BY rule_version DESC
                    LIMIT 1
                    """,
                    [rule_id],
                ).fetchone()
                next_version = 1
                if previous_row is not None:
                    next_version = _int(previous_row[1]) + 1
                    conn.execute(
                        """
                        UPDATE allocation_rules
                        SET superseded_at = ?
                        WHERE rule_id = ? AND rule_version = ?
                        """,
                        [now, rule_id, _int(previous_row[1])],
                    )
                conn.execute(
                    """
                    INSERT INTO allocation_rules (
                        rule_id,
                        rule_version,
                        name,
                        description,
                        rule_type,
                        target_dimension,
                        priority,
                        enabled,
                        condition_json,
                        allocation_json,
                        created_by,
                        created_at,
                        superseded_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    [
                        rule_id,
                        next_version,
                        name,
                        _text(description),
                        rule_type,
                        target_dimension,
                        priority,
                        bool(enabled),
                        json.dumps(normalized_condition, sort_keys=True),
                        json.dumps(normalized_allocation, sort_keys=True),
                        created_by,
                        now,
                    ],
                )
            finally:
                conn.close()
        payload = self.get_allocation_rule(rule_id)
        if payload is None:
            raise RuntimeError("Allocation rule write did not persist")
        return payload

    def deactivate_allocation_rule(self, rule_id: str, *, actor_id: str = "") -> dict[str, Any] | None:
        latest = self.get_allocation_rule(rule_id)
        if latest is None:
            return None
        if not latest.get("enabled"):
            return latest
        return self.upsert_allocation_rule(
            rule_id=_text(latest.get("rule_id")),
            name=_text(latest.get("name")),
            description=_text(latest.get("description")),
            rule_type=_text(latest.get("rule_type")),
            target_dimension=_text(latest.get("target_dimension")),
            priority=_int(latest.get("priority")),
            condition=latest.get("condition") or {},
            allocation=latest.get("allocation") or {},
            enabled=False,
            actor_id=actor_id,
        )

    def _allocation_record_value(self, record: Mapping[str, Any], field: str) -> str:
        field = _text(field)
        if not field:
            return ""
        if field.startswith("tags."):
            tags = record.get("tags")
            if isinstance(tags, Mapping):
                return _text(tags.get(field.split(".", 1)[1]))
            return ""
        return _text(record.get(field))

    def _allocation_condition_matches(self, record: Mapping[str, Any], condition: Mapping[str, Any] | None) -> bool:
        payload = dict(condition or {})
        if not payload:
            return True
        if payload.get("tag_key"):
            value = self._allocation_record_value(record, f"tags.{_text(payload.get('tag_key'))}")
        else:
            value = self._allocation_record_value(record, _text(payload.get("field")))
        if not value and not payload.get("pattern") and not payload.get("values") and not payload.get("equals") and not payload.get("tag_value"):
            return False
        exact = _text(payload.get("tag_value") or payload.get("equals"))
        if exact:
            return value.lower() == exact.lower()
        values = payload.get("values")
        if isinstance(values, list) and values:
            normalized_values = {_text(item).lower() for item in values if _text(item)}
            return value.lower() in normalized_values
        pattern = _text(payload.get("pattern"))
        if pattern:
            try:
                return re.search(pattern, value, flags=re.IGNORECASE) is not None
            except re.error:
                logger.exception("Invalid allocation rule regex pattern: %s", pattern)
                return False
        return bool(value)

    def _load_cost_records_for_allocation(self, conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT
                cost_record_id,
                date,
                subscription_id,
                subscription_name,
                resource_group,
                resource_name,
                resource_id,
                service_name,
                meter_category,
                location,
                cost_actual,
                cost_amortized,
                usage_quantity,
                tags_json,
                pricing_model,
                charge_type,
                scope_key,
                currency,
                source_delivery_key
            FROM cost_records
            ORDER BY date ASC, subscription_id ASC, resource_group ASC, resource_name ASC, cost_record_id ASC
            """
        ).fetchall()
        return [
            {
                "cost_record_id": _text(row[0]),
                "date": _text(row[1]),
                "subscription_id": _text(row[2]),
                "subscription_name": _text(row[3]),
                "resource_group": _text(row[4]),
                "resource_name": _text(row[5]),
                "resource_id": _text(row[6]),
                "service_name": _text(row[7]),
                "meter_category": _text(row[8]),
                "location": _text(row[9]),
                "cost_actual": _float(row[10]),
                "cost_amortized": _float(row[11]),
                "usage_quantity": _float(row[12]),
                "tags_json": _text(row[13]),
                "tags": _parse_tags(row[13]),
                "pricing_model": _text(row[14]),
                "charge_type": _text(row[15]),
                "scope_key": _text(row[16]),
                "currency": _text(row[17] or "USD") or "USD",
                "source_delivery_key": _text(row[18]),
            }
            for row in rows
        ]

    def run_allocation(
        self,
        *,
        actor_id: str = "",
        target_dimensions: Iterable[str] | None = None,
        run_label: str = "",
        note: str = "",
        trigger_type: str = "manual",
    ) -> dict[str, Any]:
        dimensions = _normalize_allocation_dimensions(target_dimensions)
        created_at = datetime.now(timezone.utc)
        run_id = str(uuid.uuid4())
        with self._lock:
            conn = self._connect()
            try:
                rules = self._latest_allocation_rule_rows(conn)
                rules_by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for rule in rules:
                    if rule["target_dimension"] in dimensions:
                        rules_by_dimension[rule["target_dimension"]].append(rule)

                cost_records = self._load_cost_records_for_allocation(conn)
                source_record_count = len(cost_records)
                policy = self.get_allocation_policy()
                policy_version = _int(policy.get("version"))

                result_rows: list[list[Any]] = []
                run_rule_rows: list[list[Any]] = []
                run_dimension_rows: list[list[Any]] = []
                for dimension in dimensions:
                    dimension_policy = _allocation_dimension_policy(dimension)
                    fallback_bucket = _text(dimension_policy.get("fallback_bucket"))
                    dimension_rules = rules_by_dimension.get(dimension, [])
                    for rule in dimension_rules:
                        run_rule_rows.append(
                            [
                                run_id,
                                rule["rule_id"],
                                rule["rule_version"],
                                dimension,
                                rule["rule_type"],
                                rule["priority"],
                                json.dumps(rule, sort_keys=True, default=str),
                            ]
                        )

                    source_actual = 0.0
                    source_amortized = 0.0
                    source_usage = 0.0
                    residual_actual = 0.0
                    residual_amortized = 0.0
                    residual_usage = 0.0
                    direct_actual = 0.0
                    direct_amortized = 0.0
                    direct_usage = 0.0

                    for record in cost_records:
                        source_actual += record["cost_actual"]
                        source_amortized += record["cost_amortized"]
                        source_usage += record["usage_quantity"]
                        remaining_fraction = 1.0

                        for rule in dimension_rules:
                            if remaining_fraction <= 0.000001:
                                break
                            if not self._allocation_condition_matches(record, rule.get("condition") or {}):
                                continue
                            allocation_payload = rule.get("allocation") or {}
                            bucket_type = "direct"
                            allocation_method = _text(rule.get("rule_type"))
                            if allocation_method == "shared":
                                for split in allocation_payload.get("splits") or []:
                                    fraction = min(remaining_fraction, _float(split.get("percentage")))
                                    if fraction <= 0:
                                        continue
                                    result_rows.append(
                                        [
                                            run_id,
                                            record["cost_record_id"],
                                            record["date"] or None,
                                            dimension,
                                            _text(split.get("value")),
                                            "shared",
                                            rule["rule_id"],
                                            rule["rule_version"],
                                            allocation_method,
                                            fraction,
                                            round(record["cost_actual"] * fraction, 6),
                                            round(record["cost_amortized"] * fraction, 6),
                                            round(record["usage_quantity"] * fraction, 6),
                                            record["subscription_id"],
                                            record["subscription_name"],
                                            record["resource_group"],
                                            record["resource_name"],
                                            record["resource_id"],
                                            record["service_name"],
                                            record["meter_category"],
                                            record["location"],
                                            record["pricing_model"],
                                            record["charge_type"],
                                            record["scope_key"],
                                            record["currency"],
                                            record["source_delivery_key"],
                                            record["tags_json"],
                                        ]
                                    )
                                remaining_fraction = 0.0
                                break
                            if allocation_method == "percentage":
                                fraction = min(remaining_fraction, _float(allocation_payload.get("percentage")))
                            else:
                                fraction = remaining_fraction
                            if fraction <= 0:
                                continue
                            result_rows.append(
                                [
                                    run_id,
                                    record["cost_record_id"],
                                    record["date"] or None,
                                    dimension,
                                    _text(allocation_payload.get("value")),
                                    bucket_type,
                                    rule["rule_id"],
                                    rule["rule_version"],
                                    allocation_method,
                                    fraction,
                                    round(record["cost_actual"] * fraction, 6),
                                    round(record["cost_amortized"] * fraction, 6),
                                    round(record["usage_quantity"] * fraction, 6),
                                    record["subscription_id"],
                                    record["subscription_name"],
                                    record["resource_group"],
                                    record["resource_name"],
                                    record["resource_id"],
                                    record["service_name"],
                                    record["meter_category"],
                                    record["location"],
                                    record["pricing_model"],
                                    record["charge_type"],
                                    record["scope_key"],
                                    record["currency"],
                                    record["source_delivery_key"],
                                    record["tags_json"],
                                ]
                            )
                            remaining_fraction -= fraction

                        remaining_fraction = max(remaining_fraction, 0.0)
                        if remaining_fraction > 0.000001:
                            result_rows.append(
                                [
                                    run_id,
                                    record["cost_record_id"],
                                    record["date"] or None,
                                    dimension,
                                    fallback_bucket,
                                    "fallback",
                                    "",
                                    0,
                                    "fallback",
                                    remaining_fraction,
                                    round(record["cost_actual"] * remaining_fraction, 6),
                                    round(record["cost_amortized"] * remaining_fraction, 6),
                                    round(record["usage_quantity"] * remaining_fraction, 6),
                                    record["subscription_id"],
                                    record["subscription_name"],
                                    record["resource_group"],
                                    record["resource_name"],
                                    record["resource_id"],
                                    record["service_name"],
                                    record["meter_category"],
                                    record["location"],
                                    record["pricing_model"],
                                    record["charge_type"],
                                    record["scope_key"],
                                    record["currency"],
                                    record["source_delivery_key"],
                                    record["tags_json"],
                                ]
                            )
                            residual_actual += record["cost_actual"] * remaining_fraction
                            residual_amortized += record["cost_amortized"] * remaining_fraction
                            residual_usage += record["usage_quantity"] * remaining_fraction

                    matching_rows = [row for row in result_rows if row[3] == dimension]
                    for row in matching_rows:
                        if row[5] == "fallback":
                            continue
                        direct_actual += _float(row[9 + 1])
                        direct_amortized += _float(row[10 + 1])
                        direct_usage += _float(row[11 + 1])

                    total_allocated_actual = direct_actual + residual_actual
                    total_allocated_amortized = direct_amortized + residual_amortized
                    total_allocated_usage = direct_usage + residual_usage
                    coverage_pct = round((total_allocated_actual / source_actual) if source_actual else 1.0, 6)
                    run_dimension_rows.append(
                        [
                            run_id,
                            dimension,
                            source_record_count,
                            round(source_actual, 6),
                            round(source_amortized, 6),
                            round(source_usage, 6),
                            round(direct_actual, 6),
                            round(direct_amortized, 6),
                            round(direct_usage, 6),
                            round(residual_actual, 6),
                            round(residual_amortized, 6),
                            round(residual_usage, 6),
                            round(total_allocated_actual, 6),
                            round(total_allocated_amortized, 6),
                            round(total_allocated_usage, 6),
                            coverage_pct,
                            created_at,
                        ]
                    )

                conn.execute(
                    """
                    INSERT INTO allocation_runs (
                        run_id,
                        run_label,
                        trigger_type,
                        triggered_by,
                        note,
                        status,
                        target_dimensions_json,
                        policy_version,
                        source_record_count,
                        created_at,
                        completed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        run_id,
                        _text(run_label),
                        _text(trigger_type) or "manual",
                        _text(actor_id),
                        _text(note),
                        "completed",
                        json.dumps(dimensions),
                        policy_version,
                        source_record_count,
                        created_at,
                        datetime.now(timezone.utc),
                    ],
                )
                if run_rule_rows:
                    conn.executemany(
                        """
                        INSERT INTO allocation_run_rules (
                            run_id,
                            rule_id,
                            rule_version,
                            target_dimension,
                            rule_type,
                            priority,
                            snapshot_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        run_rule_rows,
                    )
                if run_dimension_rows:
                    conn.executemany(
                        """
                        INSERT INTO allocation_run_dimensions (
                            run_id,
                            target_dimension,
                            source_record_count,
                            source_actual_cost,
                            source_amortized_cost,
                            source_usage_quantity,
                            direct_allocated_actual_cost,
                            direct_allocated_amortized_cost,
                            direct_allocated_usage_quantity,
                            residual_actual_cost,
                            residual_amortized_cost,
                            residual_usage_quantity,
                            total_allocated_actual_cost,
                            total_allocated_amortized_cost,
                            total_allocated_usage_quantity,
                            coverage_pct,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        run_dimension_rows,
                    )
                if result_rows:
                    conn.executemany(
                        """
                        INSERT INTO allocation_results (
                            run_id,
                            cost_record_id,
                            date,
                            target_dimension,
                            allocation_value,
                            bucket_type,
                            source_rule_id,
                            source_rule_version,
                            allocation_method,
                            share_fraction,
                            allocated_actual_cost,
                            allocated_amortized_cost,
                            allocated_usage_quantity,
                            subscription_id,
                            subscription_name,
                            resource_group,
                            resource_name,
                            resource_id,
                            service_name,
                            meter_category,
                            location,
                            pricing_model,
                            charge_type,
                            scope_key,
                            currency,
                            source_delivery_key,
                            tags_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        result_rows,
                    )
            finally:
                conn.close()
        payload = self.get_allocation_run(run_id)
        if payload is None:
            raise RuntimeError("Allocation run did not persist")
        return payload

    def _allocation_dimension_summaries(
        self,
        conn: duckdb.DuckDBPyConnection,
        run_id: str,
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT
                target_dimension,
                source_record_count,
                source_actual_cost,
                source_amortized_cost,
                source_usage_quantity,
                direct_allocated_actual_cost,
                direct_allocated_amortized_cost,
                direct_allocated_usage_quantity,
                residual_actual_cost,
                residual_amortized_cost,
                residual_usage_quantity,
                total_allocated_actual_cost,
                total_allocated_amortized_cost,
                total_allocated_usage_quantity,
                coverage_pct,
                created_at
            FROM allocation_run_dimensions
            WHERE run_id = ?
            ORDER BY target_dimension ASC
            """,
            [run_id],
        ).fetchall()
        summaries: list[dict[str, Any]] = []
        for row in rows or []:
            summaries.append(
                {
                    "target_dimension": _text(row[0]),
                    "source_record_count": _int(row[1]),
                    "source_actual_cost": round(_float(row[2]), 6),
                    "source_amortized_cost": round(_float(row[3]), 6),
                    "source_usage_quantity": round(_float(row[4]), 6),
                    "direct_allocated_actual_cost": round(_float(row[5]), 6),
                    "direct_allocated_amortized_cost": round(_float(row[6]), 6),
                    "direct_allocated_usage_quantity": round(_float(row[7]), 6),
                    "residual_actual_cost": round(_float(row[8]), 6),
                    "residual_amortized_cost": round(_float(row[9]), 6),
                    "residual_usage_quantity": round(_float(row[10]), 6),
                    "total_allocated_actual_cost": round(_float(row[11]), 6),
                    "total_allocated_amortized_cost": round(_float(row[12]), 6),
                    "total_allocated_usage_quantity": round(_float(row[13]), 6),
                    "coverage_pct": round(_float(row[14]), 6),
                    "created_at": _text(row[15]),
                }
            )
        return summaries

    def list_allocation_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT
                        run_id,
                        run_label,
                        trigger_type,
                        triggered_by,
                        note,
                        status,
                        target_dimensions_json,
                        policy_version,
                        source_record_count,
                        created_at,
                        completed_at
                    FROM allocation_runs
                    ORDER BY created_at DESC, run_id DESC
                    LIMIT ?
                    """,
                    [max(_int(limit), 1)],
                ).fetchall()
                payloads = []
                for row in rows or []:
                    run_id = _text(row[0])
                    payloads.append(
                        {
                            "run_id": run_id,
                            "run_label": _text(row[1]),
                            "trigger_type": _text(row[2]),
                            "triggered_by": _text(row[3]),
                            "note": _text(row[4]),
                            "status": _text(row[5]),
                            "target_dimensions": _parse_json_list(row[6]),
                            "policy_version": _int(row[7]),
                            "source_record_count": _int(row[8]),
                            "created_at": _text(row[9]),
                            "completed_at": _text(row[10]),
                            "dimensions": self._allocation_dimension_summaries(conn, run_id),
                        }
                    )
            finally:
                conn.close()
        return payloads

    def get_allocation_run(self, run_id: str) -> dict[str, Any] | None:
        run_id = _text(run_id)
        if not run_id:
            return None
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT
                        run_id,
                        run_label,
                        trigger_type,
                        triggered_by,
                        note,
                        status,
                        target_dimensions_json,
                        policy_version,
                        source_record_count,
                        created_at,
                        completed_at
                    FROM allocation_runs
                    WHERE run_id = ?
                    LIMIT 1
                    """,
                    [run_id],
                ).fetchone()
                if row is None:
                    return None
                rule_rows = conn.execute(
                    """
                    SELECT
                        rule_id,
                        rule_version,
                        target_dimension,
                        rule_type,
                        priority,
                        snapshot_json
                    FROM allocation_run_rules
                    WHERE run_id = ?
                    ORDER BY target_dimension ASC, priority ASC, rule_id ASC
                    """,
                    [run_id],
                ).fetchall()
                dimensions = self._allocation_dimension_summaries(conn, run_id)
            finally:
                conn.close()
        return {
            "run_id": _text(row[0]),
            "run_label": _text(row[1]),
            "trigger_type": _text(row[2]),
            "triggered_by": _text(row[3]),
            "note": _text(row[4]),
            "status": _text(row[5]),
            "target_dimensions": _parse_json_list(row[6]),
            "policy_version": _int(row[7]),
            "source_record_count": _int(row[8]),
            "created_at": _text(row[9]),
            "completed_at": _text(row[10]),
            "dimensions": dimensions,
            "rule_versions": [
                {
                    "rule_id": _text(rule_row[0]),
                    "rule_version": _int(rule_row[1]),
                    "target_dimension": _text(rule_row[2]),
                    "rule_type": _text(rule_row[3]),
                    "priority": _int(rule_row[4]),
                    "snapshot": _parse_json_object(rule_row[5]),
                }
                for rule_row in rule_rows or []
            ],
        }

    def list_allocation_results(
        self,
        run_id: str,
        *,
        target_dimension: str,
        bucket_type: str = "",
    ) -> list[dict[str, Any]]:
        run_id = _text(run_id)
        target_dimension = _text(target_dimension).lower()
        if target_dimension not in _VALID_ALLOCATION_DIMENSIONS:
            raise ValueError(f"Unsupported allocation dimension: {target_dimension}")
        bucket_type = _text(bucket_type).lower()
        params: list[Any] = [run_id, target_dimension]
        bucket_filter_sql = ""
        if bucket_type:
            params.append(bucket_type)
            bucket_filter_sql = "AND bucket_type = ?"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT
                        allocation_value,
                        bucket_type,
                        allocation_method,
                        COUNT(DISTINCT cost_record_id) AS source_record_count,
                        COALESCE(SUM(allocated_actual_cost), 0) AS allocated_actual_cost,
                        COALESCE(SUM(allocated_amortized_cost), 0) AS allocated_amortized_cost,
                        COALESCE(SUM(allocated_usage_quantity), 0) AS allocated_usage_quantity
                    FROM allocation_results
                    WHERE run_id = ? AND target_dimension = ?
                    {bucket_filter_sql}
                    GROUP BY 1, 2, 3
                    ORDER BY allocated_actual_cost DESC, allocation_value ASC
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()
        return [
            {
                "allocation_value": _text(row[0]),
                "bucket_type": _text(row[1]),
                "allocation_method": _text(row[2]),
                "source_record_count": _int(row[3]),
                "allocated_actual_cost": round(_float(row[4]), 6),
                "allocated_amortized_cost": round(_float(row[5]), 6),
                "allocated_usage_quantity": round(_float(row[6]), 6),
            }
            for row in rows or []
        ]

    def list_allocation_residuals(self, run_id: str, *, target_dimension: str) -> list[dict[str, Any]]:
        return self.list_allocation_results(run_id, target_dimension=target_dimension, bucket_type="fallback")

    def _latest_import_metadata(self, dataset_family: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT
                        delivery_key,
                        dataset,
                        scope_key,
                        manifest_path,
                        parsed_at,
                        row_count,
                        source_updated_at,
                        source_updated_at_text,
                        imported_at
                    FROM finops_delivery_imports
                    ORDER BY imported_at DESC NULLS LAST, parsed_at DESC NULLS LAST
                    """
                ).fetchall()
            finally:
                conn.close()
        for row in rows or []:
            record = {
                "delivery_key": _text(row[0]),
                "dataset": _text(row[1]),
                "scope_key": _text(row[2]),
                "manifest_path": _text(row[3]),
                "parsed_at": _text(row[4]),
                "row_count": _int(row[5]),
                "source_updated_at": _text(row[6]) or _text(row[7]),
                "source_updated_at_text": _text(row[7]),
                "imported_at": _text(row[8]),
            }
            if dataset_family is None or dataset_descriptor(record["dataset"]).dataset_family == dataset_family:
                return record
        return None

    def get_cost_reconciliation(self, cache_summary: Mapping[str, Any] | None = None) -> dict[str, Any]:
        latest_import = self._latest_import_metadata()
        summary = self.get_cost_summary()
        if latest_import is None or summary is None:
            return {
                "available": False,
                "reason": "No export-backed cost imports are available yet",
                "latest_import": latest_import,
            }

        delivery_key = _text(latest_import.get("delivery_key"))
        with self._lock:
            conn = self._connect()
            try:
                delivery_row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS row_count,
                        COALESCE(SUM(cost_actual), 0) AS total_actual_cost,
                        COALESCE(SUM(cost_amortized), 0) AS total_amortized_cost,
                        MIN(date) AS coverage_start,
                        MAX(date) AS coverage_end
                    FROM cost_records
                    WHERE source_delivery_key = ?
                    """,
                    [delivery_key],
                ).fetchone()
            finally:
                conn.close()

        staged_summary: dict[str, Any] = {}
        manifest_path_text = _text(latest_import.get("manifest_path"))
        manifest_path = Path(manifest_path_text) if manifest_path_text else None
        staged_path = manifest_path.with_name("staged.json") if manifest_path is not None else None
        if staged_path and staged_path.exists():
            try:
                staged_payload = json.loads(staged_path.read_text(encoding="utf-8"))
                if isinstance(staged_payload, Mapping):
                    summary_payload = staged_payload.get("summary")
                    if isinstance(summary_payload, Mapping):
                        staged_summary = dict(summary_payload)
            except (OSError, json.JSONDecodeError):
                logger.exception("Failed to load staged export summary from %s", staged_path)

        export_delivery_summary = {
            "row_count": _int(staged_summary.get("row_count")),
            "total_actual_cost": round(_float(staged_summary.get("actual_cost_total")), 2),
            "total_amortized_cost": round(_float(staged_summary.get("amortized_cost_total")), 2),
            "window_start": _text(staged_summary.get("usage_date_start")),
            "window_end": _text(staged_summary.get("usage_date_end")),
        }
        duckdb_delivery_summary = {
            "row_count": _int(delivery_row[0] if delivery_row else 0),
            "total_actual_cost": round(_float(delivery_row[1] if delivery_row else 0), 2),
            "total_amortized_cost": round(_float(delivery_row[2] if delivery_row else 0), 2),
            "window_start": _text(delivery_row[3] if delivery_row else ""),
            "window_end": _text(delivery_row[4] if delivery_row else ""),
        }
        cache_payload = dict(cache_summary or {})
        return {
            "available": True,
            "latest_import": latest_import,
            "export_delivery_summary": export_delivery_summary,
            "duckdb_delivery_summary": duckdb_delivery_summary,
            "current_window_summary": summary,
            "cache_summary": cache_payload,
            "deltas": {
                "delivery_row_count_delta": duckdb_delivery_summary["row_count"] - export_delivery_summary["row_count"],
                "delivery_actual_cost_delta": round(
                    duckdb_delivery_summary["total_actual_cost"] - export_delivery_summary["total_actual_cost"],
                    2,
                ),
                "delivery_amortized_cost_delta": round(
                    duckdb_delivery_summary["total_amortized_cost"] - export_delivery_summary["total_amortized_cost"],
                    2,
                ),
                "cache_total_cost_delta": round(
                    summary["total_actual_cost"] - _float(cache_payload.get("total_cost")),
                    2,
                ),
            },
        }

    def get_validation_report(
        self,
        cache_summary: Mapping[str, Any] | None = None,
        export_status: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        status = self.get_status()
        reconciliation = self.get_cost_reconciliation(cache_summary)
        export_payload = dict(export_status or {})
        export_health = dict(export_payload.get("health") or {})
        checks: list[dict[str, Any]] = []
        check_counts = {"pass": 0, "warning": 0, "fail": 0, "unavailable": 0}

        def add_check(payload: dict[str, Any]) -> None:
            state = _text(payload.get("state")) or "unavailable"
            if state not in check_counts:
                check_counts[state] = 0
            check_counts[state] += 1
            checks.append(payload)

        latest_import = dict(reconciliation.get("latest_import") or {})
        latest_import_time = (
            _parse_iso_datetime(latest_import.get("source_updated_at"))
            or _parse_iso_datetime(latest_import.get("imported_at"))
            or _parse_iso_datetime(latest_import.get("parsed_at"))
        )
        now = datetime.now(timezone.utc)
        latest_import_age_hours = round(((now - latest_import_time).total_seconds() / 3600), 2) if latest_import_time else None

        if not reconciliation.get("available"):
            export_state = _text(export_health.get("state")).lower()
            export_reason = _text(export_health.get("reason")) or "No export delivery health is available yet."
            if export_state in {"stale", "error"}:
                add_check(
                    _validation_check(
                        "export_health",
                        "Export delivery health",
                        "fail",
                        export_reason,
                        actual=export_state,
                    )
                )
            elif export_state:
                add_check(
                    _validation_check(
                        "export_health",
                        "Export delivery health",
                        "warning",
                        export_reason,
                        actual=export_state,
                    )
                )
            else:
                add_check(
                    _validation_check(
                        "export_health",
                        "Export delivery health",
                        "unavailable",
                        export_reason,
                    )
                )
            add_check(
                _validation_check(
                    "export_backed_data",
                    "Export-backed cost imports",
                    "warning",
                    _text(reconciliation.get("reason")) or "No export-backed cost imports are available yet.",
                )
            )
            return {
                "available": False,
                "overall_state": "blocked",
                "overall_label": "Waiting for export-backed deliveries",
                "signoff_ready": False,
                "signoff_reason": "No export-backed cost imports are available yet.",
                "latest_import": latest_import or None,
                "latest_import_age_hours": latest_import_age_hours,
                "export_health": export_health,
                "reconciliation": reconciliation,
                "drift_summary": {},
                "thresholds": {
                    "cost_tolerance": _VALIDATION_COST_TOLERANCE,
                    "cache_warning_delta": _VALIDATION_CACHE_WARNING_DELTA,
                    "min_deliveries_for_signoff": _VALIDATION_MIN_DELIVERIES_FOR_SIGNOFF,
                    "essential_field_coverage_threshold": _VALIDATION_ESSENTIAL_FIELD_COVERAGE_THRESHOLD,
                },
                "checks": checks,
                "check_counts": check_counts,
                "selected_portal_outputs": {
                    "cache_summary": dict(cache_summary or {}),
                    "export_window_summary": {},
                },
            }

        imports = dict(status.get("imports") or {})
        import_count = _int(imports.get("count"))
        field_coverage = dict(status.get("field_coverage") or {})
        deltas = dict(reconciliation.get("deltas") or {})
        staged_summary = dict(reconciliation.get("export_delivery_summary") or {})
        duckdb_summary = dict(reconciliation.get("duckdb_delivery_summary") or {})
        current_window_summary = dict(reconciliation.get("current_window_summary") or {})
        cache_payload = dict(reconciliation.get("cache_summary") or {})

        add_check(
            _validation_check(
                "export_backed_data",
                "Export-backed cost imports",
                "pass",
                f"{_int(status.get('record_count')):,} cost records are available across {_int(status.get('delivery_count')):,} imported deliveries.",
                actual=_int(status.get("record_count")),
                expected=1,
                unit="records",
            )
        )

        add_check(
            _validation_check(
                "scheduled_deliveries",
                "Observed scheduled deliveries",
                "pass" if import_count >= _VALIDATION_MIN_DELIVERIES_FOR_SIGNOFF else "warning",
                (
                    f"{import_count} imported deliveries observed."
                    if import_count >= _VALIDATION_MIN_DELIVERIES_FOR_SIGNOFF
                    else (
                        f"Only {import_count} imported delivery observed. Keep the lane in validation until at least "
                        f"{_VALIDATION_MIN_DELIVERIES_FOR_SIGNOFF} scheduled deliveries arrive."
                    )
                ),
                actual=import_count,
                expected=_VALIDATION_MIN_DELIVERIES_FOR_SIGNOFF,
                unit="deliveries",
            )
        )

        export_state = _text(export_health.get("state")).lower()
        export_reason = _text(export_health.get("reason")) or "No export delivery health is available yet."
        if export_state in {"stale", "error"}:
            export_check_state = "fail"
        elif export_state in {"healthy"}:
            export_check_state = "pass"
        elif export_state:
            export_check_state = "warning"
        else:
            export_check_state = "unavailable"
        add_check(
            _validation_check(
                "export_health",
                "Export delivery health",
                export_check_state,
                export_reason,
                actual=export_state or "unknown",
                expected="healthy",
            )
        )

        delivery_row_delta = _int(deltas.get("delivery_row_count_delta"))
        add_check(
            _validation_check(
                "delivery_row_count",
                "Delivery row count reconciliation",
                "pass" if delivery_row_delta == 0 else "fail",
                (
                    "DuckDB row count matches the staged export summary."
                    if delivery_row_delta == 0
                    else "DuckDB row count does not match the staged export summary."
                ),
                source_a="staged_export_summary",
                source_b="duckdb_delivery_summary",
                metric="row_count",
                actual=duckdb_summary.get("row_count"),
                expected=staged_summary.get("row_count"),
                delta=delivery_row_delta,
                tolerance=0,
                unit="rows",
            )
        )

        actual_cost_delta = round(_float(deltas.get("delivery_actual_cost_delta")), 2)
        add_check(
            _validation_check(
                "delivery_actual_cost",
                "Actual cost reconciliation",
                "pass" if abs(actual_cost_delta) <= _VALIDATION_COST_TOLERANCE else "fail",
                (
                    "DuckDB actual cost matches the staged export summary."
                    if abs(actual_cost_delta) <= _VALIDATION_COST_TOLERANCE
                    else "DuckDB actual cost does not match the staged export summary."
                ),
                source_a="staged_export_summary",
                source_b="duckdb_delivery_summary",
                metric="total_actual_cost",
                actual=duckdb_summary.get("total_actual_cost"),
                expected=staged_summary.get("total_actual_cost"),
                delta=actual_cost_delta,
                tolerance=_VALIDATION_COST_TOLERANCE,
                unit="currency",
            )
        )

        amortized_cost_delta = round(_float(deltas.get("delivery_amortized_cost_delta")), 2)
        add_check(
            _validation_check(
                "delivery_amortized_cost",
                "Amortized cost reconciliation",
                "pass" if abs(amortized_cost_delta) <= _VALIDATION_COST_TOLERANCE else "fail",
                (
                    "DuckDB amortized cost matches the staged export summary."
                    if abs(amortized_cost_delta) <= _VALIDATION_COST_TOLERANCE
                    else "DuckDB amortized cost does not match the staged export summary."
                ),
                source_a="staged_export_summary",
                source_b="duckdb_delivery_summary",
                metric="total_amortized_cost",
                actual=duckdb_summary.get("total_amortized_cost"),
                expected=staged_summary.get("total_amortized_cost"),
                delta=amortized_cost_delta,
                tolerance=_VALIDATION_COST_TOLERANCE,
                unit="currency",
            )
        )

        window_match = (
            _text(staged_summary.get("window_start")) == _text(duckdb_summary.get("window_start"))
            and _text(staged_summary.get("window_end")) == _text(duckdb_summary.get("window_end"))
        )
        add_check(
            _validation_check(
                "delivery_window",
                "Coverage window reconciliation",
                "pass" if window_match else "fail",
                (
                    "DuckDB coverage window matches the staged export summary."
                    if window_match
                    else "DuckDB coverage window does not match the staged export summary."
                ),
                source_a="staged_export_summary",
                source_b="duckdb_delivery_summary",
                metric="coverage_window",
                actual=f"{_text(duckdb_summary.get('window_start'))}..{_text(duckdb_summary.get('window_end'))}",
                expected=f"{_text(staged_summary.get('window_start'))}..{_text(staged_summary.get('window_end'))}",
            )
        )

        cache_delta = round(_float(deltas.get("cache_total_cost_delta")), 2)
        cache_state = "unavailable"
        cache_detail = "No cache-backed portal summary was supplied for comparison."
        if cache_payload:
            cache_state = "pass" if abs(cache_delta) <= _VALIDATION_CACHE_WARNING_DELTA else "warning"
            cache_detail = (
                "Cache-backed portal summary is aligned with the export-backed current window."
                if cache_state == "pass"
                else "Cache-backed portal summary differs from the export-backed current window. Review lookback alignment and cache timing."
            )
        add_check(
            _validation_check(
                "cache_total_cost",
                "Portal cache vs export-backed current window",
                cache_state,
                cache_detail,
                source_a="cache_summary",
                source_b="export_current_window",
                metric="total_actual_cost",
                actual=_float(cache_payload.get("total_cost")) if cache_payload else None,
                expected=current_window_summary.get("total_actual_cost"),
                delta=cache_delta if cache_payload else None,
                tolerance=_VALIDATION_CACHE_WARNING_DELTA if cache_payload else None,
                unit="currency",
            )
        )

        essential_coverage = min(
            _float(field_coverage.get("resource_id_pct")),
            _float(field_coverage.get("pricing_model_pct")),
            _float(field_coverage.get("usage_quantity_pct")),
        )
        add_check(
            _validation_check(
                "essential_field_coverage",
                "Essential CostRecord coverage",
                "pass" if essential_coverage >= _VALIDATION_ESSENTIAL_FIELD_COVERAGE_THRESHOLD else "warning",
                (
                    "Resource ID, pricing model, and usage quantity coverage meet the current validation threshold."
                    if essential_coverage >= _VALIDATION_ESSENTIAL_FIELD_COVERAGE_THRESHOLD
                    else "One or more essential CostRecord fields are below the validation threshold."
                ),
                actual=round(essential_coverage, 4),
                expected=_VALIDATION_ESSENTIAL_FIELD_COVERAGE_THRESHOLD,
                unit="ratio",
            )
        )

        if latest_import_age_hours is None:
            import_freshness_state = "warning"
            import_freshness_detail = "Latest import timestamp is unavailable."
        else:
            expected_hours = _int(export_health.get("expected_cadence_hours"))
            if expected_hours > 0 and latest_import_age_hours > expected_hours:
                import_freshness_state = "warning"
                import_freshness_detail = (
                    f"Latest import is {latest_import_age_hours:.2f} hours old, beyond the expected {expected_hours} hour cadence."
                )
            else:
                import_freshness_state = "pass"
                import_freshness_detail = f"Latest import is {latest_import_age_hours:.2f} hours old."
        add_check(
            _validation_check(
                "latest_import_freshness",
                "Latest import freshness",
                import_freshness_state,
                import_freshness_detail,
                actual=latest_import_age_hours,
                expected=_int(export_health.get("expected_cadence_hours")) or None,
                unit="hours",
            )
        )

        overall_state = "pass"
        overall_label = "Validation checks passed"
        if check_counts.get("fail", 0):
            overall_state = "fail"
            overall_label = "Validation drift detected"
        elif check_counts.get("warning", 0):
            overall_state = "warning"
            overall_label = "Needs live validation follow-through"

        signoff_ready = overall_state == "pass" and import_count >= _VALIDATION_MIN_DELIVERIES_FOR_SIGNOFF
        if signoff_ready:
            signoff_reason = "Validation checks are passing and multiple deliveries have been observed."
        elif import_count < _VALIDATION_MIN_DELIVERIES_FOR_SIGNOFF:
            signoff_reason = (
                f"Need at least {_VALIDATION_MIN_DELIVERIES_FOR_SIGNOFF} observed deliveries before calling the export lane production-ready."
            )
        elif overall_state == "fail":
            signoff_reason = "One or more reconciliation checks failed."
        else:
            signoff_reason = "Validation checks are landed, but warnings still need review before signoff."

        return {
            "available": True,
            "overall_state": overall_state,
            "overall_label": overall_label,
            "signoff_ready": signoff_ready,
            "signoff_reason": signoff_reason,
            "latest_import": latest_import,
            "latest_import_age_hours": latest_import_age_hours,
            "export_health": export_health,
            "reconciliation": reconciliation,
            "drift_summary": {
                "delivery_row_count_delta": delivery_row_delta,
                "delivery_actual_cost_delta": actual_cost_delta,
                "delivery_amortized_cost_delta": amortized_cost_delta,
                "cache_total_cost_delta": cache_delta if cache_payload else None,
            },
            "thresholds": {
                "cost_tolerance": _VALIDATION_COST_TOLERANCE,
                "cache_warning_delta": _VALIDATION_CACHE_WARNING_DELTA,
                "min_deliveries_for_signoff": _VALIDATION_MIN_DELIVERIES_FOR_SIGNOFF,
                "essential_field_coverage_threshold": _VALIDATION_ESSENTIAL_FIELD_COVERAGE_THRESHOLD,
            },
            "checks": checks,
            "check_counts": check_counts,
            "selected_portal_outputs": {
                "cache_summary": cache_payload,
                "export_current_window": current_window_summary,
            },
        }

    def record_ai_usage(
        self,
        *,
        provider: str,
        model_id: str,
        feature_surface: str,
        app_surface: str,
        actor_type: str = "",
        actor_id: str = "",
        team: str = "",
        request_count: int = 1,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_tokens: int = 0,
        latency_ms: float = 0.0,
        status: str = "succeeded",
        error_text: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        estimated_tokens = max(_int(estimated_tokens), _int(input_tokens) + _int(output_tokens))
        pricing = self.estimate_ai_cost(
            provider=_text(provider),
            model_id=_text(model_id),
            input_tokens=_int(input_tokens),
            output_tokens=_int(output_tokens),
        )
        recorded_at = datetime.now(timezone.utc)
        payload = {
            "usage_id": str(uuid.uuid4()),
            "recorded_at": recorded_at,
            "recorded_date": recorded_at.date().isoformat(),
            "provider": _text(provider),
            "model_id": _text(model_id),
            "feature_surface": _text(feature_surface),
            "app_surface": _text(app_surface),
            "actor_type": _text(actor_type),
            "actor_id": _text(actor_id),
            "team": _text(team),
            "request_count": max(_int(request_count), 1),
            "input_tokens": max(_int(input_tokens), 0),
            "output_tokens": max(_int(output_tokens), 0),
            "estimated_tokens": estimated_tokens,
            "latency_ms": round(_float(latency_ms), 3),
            "estimated_cost": pricing["estimated_cost"],
            "currency": pricing["currency"],
            "pricing_source": pricing["pricing_source"],
            "status": _text(status) or "succeeded",
            "error_text": _text(error_text),
            "metadata_json": json.dumps(dict(metadata or {}), sort_keys=True, default=str),
        }
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO ai_usage_records (
                        usage_id,
                        recorded_at,
                        recorded_date,
                        provider,
                        model_id,
                        feature_surface,
                        app_surface,
                        actor_type,
                        actor_id,
                        team,
                        request_count,
                        input_tokens,
                        output_tokens,
                        estimated_tokens,
                        latency_ms,
                        estimated_cost,
                        currency,
                        pricing_source,
                        status,
                        error_text,
                        metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        payload["usage_id"],
                        payload["recorded_at"],
                        payload["recorded_date"],
                        payload["provider"],
                        payload["model_id"],
                        payload["feature_surface"],
                        payload["app_surface"],
                        payload["actor_type"],
                        payload["actor_id"],
                        payload["team"],
                        payload["request_count"],
                        payload["input_tokens"],
                        payload["output_tokens"],
                        payload["estimated_tokens"],
                        payload["latency_ms"],
                        payload["estimated_cost"],
                        payload["currency"],
                        payload["pricing_source"],
                        payload["status"],
                        payload["error_text"],
                        payload["metadata_json"],
                    ],
                )
            finally:
                conn.close()
        return {
            "usage_id": payload["usage_id"],
            "estimated_cost": payload["estimated_cost"],
            "currency": payload["currency"],
            "pricing_source": payload["pricing_source"],
        }

    def _window(self, lookback_days: int | None = None) -> tuple[str, str] | None:
        effective_lookback = max(int(lookback_days or self._default_lookback_days), 1)
        latest = self._latest_cost_date()
        if latest is None:
            return None
        start = latest - timedelta(days=effective_lookback - 1)
        return start.isoformat(), latest.isoformat()

    def _ai_window(self, lookback_days: int | None = None) -> tuple[str, str] | None:
        effective_lookback = max(int(lookback_days or self._default_lookback_days), 1)
        latest = self._latest_ai_usage_date()
        if latest is None:
            return None
        start = latest - timedelta(days=effective_lookback - 1)
        return start.isoformat(), latest.isoformat()

    @staticmethod
    def _resource_inventory_indexes(
        cache_resources: Iterable[Mapping[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]], dict[str, dict[str, Any]]]:
        resource_by_id: dict[str, dict[str, Any]] = {}
        resource_by_lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
        cluster_by_id: dict[str, dict[str, Any]] = {}
        for raw in cache_resources or []:
            if not isinstance(raw, Mapping):
                continue
            item = dict(raw)
            normalized_id = _normalize_resource_id(item.get("id"))
            if normalized_id:
                resource_by_id[normalized_id] = item
            lookup_key = _resource_lookup_key(
                item.get("subscription_id"),
                item.get("resource_group"),
                item.get("name"),
            )
            if all(lookup_key):
                resource_by_lookup[lookup_key] = item
            resource_type = _text(item.get("resource_type")).lower() or _resource_type_from_resource_id(item.get("id")).lower()
            if resource_type == "microsoft.containerservice/managedclusters" and normalized_id:
                cluster_by_id[normalized_id] = item
            managed_by_cluster = _normalize_resource_id(item.get("managed_by"))
            if managed_by_cluster and managed_by_cluster not in cluster_by_id:
                cluster_id = _aks_cluster_id_from_resource_id(item.get("managed_by"))
                if cluster_id:
                    cluster_by_id[managed_by_cluster] = {
                        "id": item.get("managed_by"),
                        "name": _resource_name_from_resource_id(item.get("managed_by")),
                        "resource_type": _resource_type_from_resource_id(item.get("managed_by")),
                        "subscription_id": _subscription_id_from_resource_id(_text(item.get("managed_by"))),
                        "resource_group": _resource_group_from_resource_id(_text(item.get("managed_by"))),
                        "location": item.get("location") or "",
                        "tags": {},
                    }
        return resource_by_id, resource_by_lookup, cluster_by_id

    def _resource_cost_bridge_rows(
        self,
        cache_resources: Iterable[Mapping[str, Any]],
        *,
        lookback_days: int | None = None,
    ) -> dict[str, Any]:
        window = self._window(lookback_days)
        if window is None:
            return {
                "lookback_days": max(int(lookback_days or self._default_lookback_days), 1),
                "window_start": "",
                "window_end": "",
                "rows": [],
            }
        window_start, window_end = window
        resource_by_id, resource_by_lookup, cluster_by_id = self._resource_inventory_indexes(cache_resources)
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT
                        resource_id,
                        MIN(subscription_id) AS subscription_id,
                        MIN(subscription_name) AS subscription_name,
                        MIN(resource_group) AS resource_group,
                        MIN(resource_name) AS resource_name,
                        MIN(location) AS location,
                        MIN(currency) AS currency,
                        COUNT(*) AS line_item_count,
                        COALESCE(SUM(cost_actual), 0) AS actual_cost,
                        COALESCE(SUM(cost_amortized), 0) AS amortized_cost,
                        COALESCE(SUM(usage_quantity), 0) AS usage_quantity,
                        MIN(date) AS first_date,
                        MAX(date) AS last_date
                    FROM cost_records
                    WHERE date BETWEEN ? AND ?
                      AND COALESCE(resource_id, '') != ''
                    GROUP BY resource_id
                    ORDER BY actual_cost DESC, resource_id ASC
                    """
                    ,
                    [window_start, window_end],
                ).fetchall()
            finally:
                conn.close()

        bridge_rows: list[dict[str, Any]] = []
        for row in rows or []:
            resource_id = _text(row[0])
            normalized_id = _normalize_resource_id(resource_id)
            inventory_item = resource_by_id.get(normalized_id)
            match_type = ""
            if inventory_item is not None:
                match_type = "resource_id"
            else:
                lookup_key = _resource_lookup_key(row[1], row[3], row[4] or _resource_name_from_resource_id(resource_id))
                inventory_item = resource_by_lookup.get(lookup_key)
                if inventory_item is not None:
                    match_type = "subscription_group_name"
            managed_by = _text((inventory_item or {}).get("managed_by"))
            cluster_id = ""
            if inventory_item is not None:
                resource_type = _text(inventory_item.get("resource_type")).lower() or _resource_type_from_resource_id(resource_id).lower()
                if resource_type == "microsoft.containerservice/managedclusters":
                    cluster_id = _text(inventory_item.get("id"))
                elif managed_by and _normalize_resource_id(managed_by) in cluster_by_id:
                    cluster_id = managed_by
                else:
                    cluster_id = _aks_cluster_id_from_resource_id(resource_id)
            else:
                cluster_id = _aks_cluster_id_from_resource_id(resource_id)
            bridge_rows.append(
                {
                    "resource_id": resource_id,
                    "normalized_resource_id": normalized_id,
                    "subscription_id": _text(row[1]),
                    "subscription_name": _text(row[2]),
                    "resource_group": _text(row[3]),
                    "resource_name": _text(row[4]) or _resource_name_from_resource_id(resource_id),
                    "location": _text(row[5]),
                    "currency": _text(row[6] or "USD") or "USD",
                    "line_item_count": _int(row[7]),
                    "actual_cost": round(_float(row[8]), 6),
                    "amortized_cost": round(_float(row[9]), 6),
                    "usage_quantity": round(_float(row[10]), 6),
                    "first_date": _text(row[11]),
                    "last_date": _text(row[12]),
                    "matched": inventory_item is not None,
                    "bridge_match_type": match_type or "unmatched",
                    "inventory_resource_type": _text((inventory_item or {}).get("resource_type")) or _resource_type_from_resource_id(resource_id),
                    "inventory_name": _text((inventory_item or {}).get("name")) or _text(row[4]) or _resource_name_from_resource_id(resource_id),
                    "inventory_id": _text((inventory_item or {}).get("id")) or resource_id,
                    "managed_by": managed_by,
                    "cluster_id": cluster_id,
                    "cluster_detected": bool(_text(cluster_id)),
                    "node_pool": _aks_node_pool_name(inventory_item or {}),
                    "tags": dict((inventory_item or {}).get("tags") or {}),
                }
            )

        return {
            "lookback_days": max(int(lookback_days or self._default_lookback_days), 1),
            "window_start": window_start,
            "window_end": window_end,
            "rows": bridge_rows,
        }

    def get_resource_cost_bridge_summary(
        self,
        cache_resources: Iterable[Mapping[str, Any]],
        *,
        lookback_days: int | None = None,
    ) -> dict[str, Any]:
        payload = self._resource_cost_bridge_rows(cache_resources, lookback_days=lookback_days)
        rows = payload["rows"]
        matched = [row for row in rows if row.get("matched")]
        unmatched = [row for row in rows if not row.get("matched")]
        bridged_actual = round(sum(_float(row.get("actual_cost")) for row in matched), 2)
        total_actual = round(sum(_float(row.get("actual_cost")) for row in rows), 2)
        top_unmatched = [
            {
                "resource_name": row.get("resource_name"),
                "resource_id": row.get("resource_id"),
                "resource_group": row.get("resource_group"),
                "actual_cost": round(_float(row.get("actual_cost")), 2),
            }
            for row in unmatched[:5]
        ]
        return {
            "available": bool(rows),
            "lookback_days": payload["lookback_days"],
            "window_start": payload["window_start"],
            "window_end": payload["window_end"],
            "source_resource_count": len(rows),
            "matched_resource_count": len(matched),
            "unmatched_resource_count": len(unmatched),
            "bridged_actual_cost": bridged_actual,
            "unbridged_actual_cost": round(total_actual - bridged_actual, 2),
            "bridged_actual_cost_pct": round((bridged_actual / total_actual) if total_actual else 0.0, 4),
            "cluster_detected_count": sum(1 for row in rows if row.get("cluster_detected")),
            "top_unmatched_resources": top_unmatched,
        }

    def list_aks_cost_visibility(
        self,
        cache_resources: Iterable[Mapping[str, Any]],
        *,
        lookback_days: int | None = None,
    ) -> list[dict[str, Any]]:
        bridge = self._resource_cost_bridge_rows(cache_resources, lookback_days=lookback_days)
        resource_by_id, _, cluster_by_id = self._resource_inventory_indexes(cache_resources)
        cluster_rollups: dict[str, dict[str, Any]] = {}
        for row in bridge["rows"]:
            cluster_id = _normalize_resource_id(row.get("cluster_id"))
            if not cluster_id:
                continue
            cluster_resource = cluster_by_id.get(cluster_id) or resource_by_id.get(cluster_id) or {
                "id": row.get("cluster_id"),
                "name": _resource_name_from_resource_id(row.get("cluster_id")),
                "resource_type": "Microsoft.ContainerService/managedClusters",
                "subscription_id": row.get("subscription_id"),
                "resource_group": _resource_group_from_resource_id(row.get("cluster_id")),
                "location": row.get("location"),
                "tags": {},
            }
            entry = cluster_rollups.setdefault(
                cluster_id,
                {
                    "cluster_resource": cluster_resource,
                    "currency": _text(row.get("currency") or "USD") or "USD",
                    "current_monthly_cost": 0.0,
                    "amortized_monthly_cost": 0.0,
                    "usage_quantity": 0.0,
                    "line_item_count": 0,
                    "resource_count": 0,
                    "resource_types": defaultdict(lambda: {"count": 0, "actual_cost": 0.0}),
                    "node_pools": defaultdict(lambda: {"actual_cost": 0.0, "resource_count": 0}),
                },
            )
            entry["current_monthly_cost"] += _float(row.get("actual_cost"))
            entry["amortized_monthly_cost"] += _float(row.get("amortized_cost"))
            entry["usage_quantity"] += _float(row.get("usage_quantity"))
            entry["line_item_count"] += _int(row.get("line_item_count"))
            entry["resource_count"] += 1
            resource_type_label = _text(row.get("inventory_resource_type") or "Unknown")
            resource_type_bucket = entry["resource_types"][resource_type_label]
            resource_type_bucket["count"] += 1
            resource_type_bucket["actual_cost"] += _float(row.get("actual_cost"))
            pool_name = _text(row.get("node_pool"))
            if pool_name:
                pool_bucket = entry["node_pools"][pool_name]
                pool_bucket["actual_cost"] += _float(row.get("actual_cost"))
                pool_bucket["resource_count"] += 1

        results: list[dict[str, Any]] = []
        for cluster_id, entry in cluster_rollups.items():
            cluster_resource = dict(entry["cluster_resource"])
            node_pools = [
                {
                    "label": label,
                    "actual_cost": round(_float(values["actual_cost"]), 2),
                    "resource_count": _int(values["resource_count"]),
                }
                for label, values in entry["node_pools"].items()
            ]
            node_pools.sort(key=lambda item: (-_float(item["actual_cost"]), item["label"]))
            by_resource_type = [
                {
                    "label": label,
                    "actual_cost": round(_float(values["actual_cost"]), 2),
                    "resource_count": _int(values["count"]),
                }
                for label, values in entry["resource_types"].items()
            ]
            by_resource_type.sort(key=lambda item: (-_float(item["actual_cost"]), item["label"]))
            top_pool = node_pools[0] if node_pools else None
            current_monthly_cost = round(_float(entry["current_monthly_cost"]), 2)
            evidence = [
                {"label": "Cluster", "value": _text(cluster_resource.get("name"))},
                {"label": "Managed resource count", "value": str(_int(entry["resource_count"]))},
                {"label": "Export-backed current monthly cost", "value": f"{current_monthly_cost:.2f} {_text(entry['currency'])}"},
            ]
            if top_pool:
                evidence.append(
                    {
                        "label": "Top node pool",
                        "value": f"{top_pool['label']} ({top_pool['actual_cost']:.2f} {_text(entry['currency'])})",
                    }
                )
            results.append(
                {
                    "id": f"aks-visibility:{cluster_id}",
                    "category": "compute",
                    "opportunity_type": "aks_cluster_cost_visibility",
                    "source": "heuristic",
                    "title": f"Review AKS cluster spend for {_text(cluster_resource.get('name')) or 'cluster'}",
                    "summary": (
                        f"Export-backed cost data attributes {current_monthly_cost:.2f} {_text(entry['currency'])} "
                        f"to AKS cluster {_text(cluster_resource.get('name')) or 'cluster'} across "
                        f"{_int(entry['resource_count'])} bridged resource(s)."
                    ),
                    "subscription_id": _text(cluster_resource.get("subscription_id")),
                    "subscription_name": "",
                    "resource_group": _text(cluster_resource.get("resource_group")),
                    "location": _text(cluster_resource.get("location")),
                    "resource_id": _text(cluster_resource.get("id")),
                    "resource_name": _text(cluster_resource.get("name")),
                    "resource_type": _text(cluster_resource.get("resource_type")) or "Microsoft.ContainerService/managedClusters",
                    "current_monthly_cost": current_monthly_cost,
                    "estimated_monthly_savings": None,
                    "currency": _text(entry["currency"]) or "USD",
                    "quantified": False,
                    "estimate_basis": (
                        "Export-backed resource-cost bridge joined cost records to Azure inventory and managed-by "
                        "relationships for AKS cluster visibility."
                    ),
                    "effort": "medium",
                    "risk": "low",
                    "confidence": "medium" if node_pools else "low",
                    "recommended_steps": [
                        "Review node pool sizing, autoscaler settings, and baseline cluster spend.",
                        "Confirm whether cluster-managed compute should move to reservations or savings plans.",
                        "Use the bridged cost context before repointing AKS optimization workflows.",
                    ],
                    "evidence": evidence,
                    "portal_url": "https://portal.azure.com/",
                    "follow_up_route": "/azure/savings",
                    "aks_visibility": {
                        "node_pools": node_pools,
                        "by_resource_type": by_resource_type,
                        "resource_count": _int(entry["resource_count"]),
                        "line_item_count": _int(entry["line_item_count"]),
                        "current_monthly_cost": current_monthly_cost,
                        "amortized_monthly_cost": round(_float(entry["amortized_monthly_cost"]), 2),
                        "window_start": bridge["window_start"],
                        "window_end": bridge["window_end"],
                    },
                }
            )
        results.sort(key=lambda item: (-_float(item.get("current_monthly_cost")), _text(item.get("title"))))
        return results

    def get_cost_summary(self, lookback_days: int | None = None) -> dict[str, Any] | None:
        window = self._window(lookback_days)
        if window is None:
            return None
        window_start, window_end = window
        with self._lock:
            conn = self._connect()
            try:
                totals = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS record_count,
                        COALESCE(SUM(cost_actual), 0) AS total_actual_cost,
                        COALESCE(SUM(cost_amortized), 0) AS total_amortized_cost,
                        COUNT(DISTINCT currency) AS currency_count,
                        MIN(currency) AS currency,
                        MIN(date) AS coverage_start,
                        MAX(date) AS coverage_end
                    FROM cost_records
                    WHERE date BETWEEN ? AND ?
                    """,
                    [window_start, window_end],
                ).fetchone()
                top_service = conn.execute(
                    """
                    SELECT COALESCE(NULLIF(service_name, ''), 'Unknown')
                    FROM cost_records
                    WHERE date BETWEEN ? AND ?
                    GROUP BY 1
                    ORDER BY SUM(cost_actual) DESC, 1 ASC
                    LIMIT 1
                    """,
                    [window_start, window_end],
                ).fetchone()
                top_subscription = conn.execute(
                    """
                    SELECT COALESCE(NULLIF(subscription_name, ''), COALESCE(NULLIF(subscription_id, ''), 'Unknown'))
                    FROM cost_records
                    WHERE date BETWEEN ? AND ?
                    GROUP BY 1
                    ORDER BY SUM(cost_actual) DESC, 1 ASC
                    LIMIT 1
                    """,
                    [window_start, window_end],
                ).fetchone()
                top_resource_group = conn.execute(
                    """
                    SELECT COALESCE(NULLIF(resource_group, ''), 'Unknown')
                    FROM cost_records
                    WHERE date BETWEEN ? AND ?
                    GROUP BY 1
                    ORDER BY SUM(cost_actual) DESC, 1 ASC
                    LIMIT 1
                    """,
                    [window_start, window_end],
                ).fetchone()
            finally:
                conn.close()

        if totals is None or int(totals[0] or 0) == 0:
            return None

        currency_count = int(totals[3] or 0)
        currency = _text(totals[4]) if currency_count == 1 else _text(totals[4] or "USD")
        return {
            "lookback_days": max(int(lookback_days or self._default_lookback_days), 1),
            "total_cost": round(_float(totals[1]), 2),
            "total_actual_cost": round(_float(totals[1]), 2),
            "total_amortized_cost": round(_float(totals[2]), 2),
            "currency": currency or "USD",
            "top_service": _text(top_service[0] if top_service else ""),
            "top_subscription": _text(top_subscription[0] if top_subscription else ""),
            "top_resource_group": _text(top_resource_group[0] if top_resource_group else ""),
            "record_count": int(totals[0] or 0),
            "window_start": _text(totals[5]),
            "window_end": _text(totals[6]),
            "source": "exports",
            "source_label": "Export-backed local analytics",
            "export_backed": True,
        }

    def get_cost_trend(self, lookback_days: int | None = None) -> list[dict[str, Any]]:
        window = self._window(lookback_days)
        if window is None:
            return []
        window_start, window_end = window
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT
                        date,
                        COALESCE(SUM(cost_actual), 0) AS actual_cost,
                        COALESCE(SUM(cost_amortized), 0) AS amortized_cost,
                        COUNT(DISTINCT currency) AS currency_count,
                        MIN(currency) AS currency
                    FROM cost_records
                    WHERE date BETWEEN ? AND ?
                    GROUP BY date
                    ORDER BY date ASC
                    """,
                    [window_start, window_end],
                ).fetchall()
            finally:
                conn.close()

        result: list[dict[str, Any]] = []
        for row in rows:
            currency = _text(row[4]) if int(row[3] or 0) == 1 else _text(row[4] or "USD")
            actual_cost = round(_float(row[1]), 2)
            amortized_cost = round(_float(row[2]), 2)
            result.append(
                {
                    "date": _text(row[0]),
                    "cost": actual_cost,
                    "actual_cost": actual_cost,
                    "amortized_cost": amortized_cost,
                    "currency": currency or "USD",
                    "source": "exports",
                }
            )
        return result

    def get_cost_breakdown(self, group_by: str, lookback_days: int | None = None) -> list[dict[str, Any]]:
        column_map = {
            "service": "service_name",
            "subscription": "subscription_name",
            "resource_group": "resource_group",
        }
        target_column = column_map.get(_text(group_by).lower(), "service_name")
        window = self._window(lookback_days)
        if window is None:
            return []
        window_start, window_end = window
        with self._lock:
            conn = self._connect()
            try:
                total_row = conn.execute(
                    """
                    SELECT COALESCE(SUM(cost_actual), 0)
                    FROM cost_records
                    WHERE date BETWEEN ? AND ?
                    """,
                    [window_start, window_end],
                ).fetchone()
                rows = conn.execute(
                    f"""
                    SELECT
                        COALESCE(NULLIF({target_column}, ''), 'Unknown') AS label,
                        COALESCE(SUM(cost_actual), 0) AS actual_cost,
                        COALESCE(SUM(cost_amortized), 0) AS amortized_cost,
                        COUNT(DISTINCT currency) AS currency_count,
                        MIN(currency) AS currency
                    FROM cost_records
                    WHERE date BETWEEN ? AND ?
                    GROUP BY 1
                    ORDER BY actual_cost DESC, label ASC
                    """,
                    [window_start, window_end],
                ).fetchall()
            finally:
                conn.close()

        grand_total = _float((total_row or [0])[0])
        result: list[dict[str, Any]] = []
        for row in rows:
            actual_cost = round(_float(row[1]), 2)
            amortized_cost = round(_float(row[2]), 2)
            currency = _text(row[4]) if int(row[3] or 0) == 1 else _text(row[4] or "USD")
            result.append(
                {
                    "label": _text(row[0]) or "Unknown",
                    "amount": actual_cost,
                    "actual_cost": actual_cost,
                    "amortized_cost": amortized_cost,
                    "currency": currency or "USD",
                    "share": round((actual_cost / grand_total) if grand_total else 0.0, 4),
                    "source": "exports",
                }
            )
        return result

    def get_recommendation_summary(self) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            try:
                totals = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total_opportunities,
                        SUM(CASE WHEN quantified AND estimated_monthly_savings IS NOT NULL THEN 1 ELSE 0 END) AS quantified_opportunities,
                        COALESCE(SUM(CASE WHEN quantified AND estimated_monthly_savings IS NOT NULL THEN estimated_monthly_savings ELSE 0 END), 0) AS quantified_monthly_savings,
                        SUM(CASE WHEN LOWER(COALESCE(effort, '')) = 'low' AND LOWER(COALESCE(risk, '')) = 'low' THEN 1 ELSE 0 END) AS quick_win_count,
                        COALESCE(SUM(CASE WHEN LOWER(COALESCE(effort, '')) = 'low' AND LOWER(COALESCE(risk, '')) = 'low' AND quantified THEN COALESCE(estimated_monthly_savings, 0) ELSE 0 END), 0) AS quick_win_monthly_savings,
                        SUM(CASE WHEN NOT quantified THEN 1 ELSE 0 END) AS unquantified_opportunity_count,
                        MIN(currency) AS currency
                    FROM recommendations
                    """
                ).fetchone()
                if totals is None or _int(totals[0]) == 0:
                    return None

                by_category = conn.execute(
                    """
                    SELECT
                        COALESCE(NULLIF(category, ''), 'other') AS label,
                        COUNT(*) AS count,
                        COALESCE(SUM(COALESCE(estimated_monthly_savings, 0)), 0) AS estimated_monthly_savings
                    FROM recommendations
                    GROUP BY 1
                    ORDER BY estimated_monthly_savings DESC, count DESC, label ASC
                    """
                ).fetchall()
                by_opportunity_type = conn.execute(
                    """
                    SELECT
                        COALESCE(NULLIF(opportunity_type, ''), 'unknown') AS label,
                        COUNT(*) AS count,
                        COALESCE(SUM(COALESCE(estimated_monthly_savings, 0)), 0) AS estimated_monthly_savings
                    FROM recommendations
                    GROUP BY 1
                    ORDER BY estimated_monthly_savings DESC, count DESC, label ASC
                    """
                ).fetchall()
                by_effort = conn.execute(
                    """
                    SELECT LOWER(COALESCE(effort, '')) AS label, COUNT(*) AS count
                    FROM recommendations
                    GROUP BY 1
                    """
                ).fetchall()
                by_risk = conn.execute(
                    """
                    SELECT LOWER(COALESCE(risk, '')) AS label, COUNT(*) AS count
                    FROM recommendations
                    GROUP BY 1
                    """
                ).fetchall()
                by_confidence = conn.execute(
                    """
                    SELECT LOWER(COALESCE(confidence, '')) AS label, COUNT(*) AS count
                    FROM recommendations
                    GROUP BY 1
                    """
                ).fetchall()
                top_subscriptions = conn.execute(
                    """
                    SELECT
                        COALESCE(NULLIF(subscription_name, ''), COALESCE(NULLIF(subscription_id, ''), 'Unknown')) AS label,
                        COUNT(*) AS count,
                        COALESCE(SUM(COALESCE(estimated_monthly_savings, 0)), 0) AS estimated_monthly_savings
                    FROM recommendations
                    WHERE quantified = TRUE
                    GROUP BY 1
                    ORDER BY estimated_monthly_savings DESC, count DESC, label ASC
                    LIMIT 5
                    """
                ).fetchall()
                top_resource_groups = conn.execute(
                    """
                    SELECT
                        CASE
                            WHEN COALESCE(NULLIF(resource_group, ''), '') = '' THEN ''
                            WHEN COALESCE(NULLIF(subscription_name, ''), COALESCE(NULLIF(subscription_id, ''), '')) = '' THEN resource_group
                            ELSE COALESCE(NULLIF(subscription_name, ''), subscription_id) || ' / ' || resource_group
                        END AS label,
                        COUNT(*) AS count,
                        COALESCE(SUM(COALESCE(estimated_monthly_savings, 0)), 0) AS estimated_monthly_savings
                    FROM recommendations
                    WHERE quantified = TRUE AND COALESCE(NULLIF(resource_group, ''), '') != ''
                    GROUP BY 1
                    ORDER BY estimated_monthly_savings DESC, count DESC, label ASC
                    LIMIT 5
                    """
                ).fetchall()
            finally:
                conn.close()

        def _aggregate_rows(rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
            return [
                {
                    "label": _text(row[0]),
                    "count": _int(row[1]),
                    "estimated_monthly_savings": round(_float(row[2]), 2),
                }
                for row in rows
                if _text(row[0])
            ]

        count_by_effort = {_text(row[0]): _int(row[1]) for row in by_effort}
        count_by_risk = {_text(row[0]): _int(row[1]) for row in by_risk}
        count_by_confidence = {_text(row[0]): _int(row[1]) for row in by_confidence}

        return {
            "currency": _text(totals[6] or "USD") or "USD",
            "total_opportunities": _int(totals[0]),
            "quantified_opportunities": _int(totals[1]),
            "quantified_monthly_savings": round(_float(totals[2]), 2),
            "quick_win_count": _int(totals[3]),
            "quick_win_monthly_savings": round(_float(totals[4]), 2),
            "unquantified_opportunity_count": _int(totals[5]),
            "by_category": _aggregate_rows(by_category),
            "by_opportunity_type": _aggregate_rows(by_opportunity_type),
            "by_effort": [{"label": label, "count": count_by_effort[label]} for label in ["low", "medium", "high"] if count_by_effort.get(label)],
            "by_risk": [{"label": label, "count": count_by_risk[label]} for label in ["low", "medium", "high"] if count_by_risk.get(label)],
            "by_confidence": [
                {"label": label, "count": count_by_confidence[label]}
                for label in ["high", "medium", "low"]
                if count_by_confidence.get(label)
            ],
            "top_subscriptions": _aggregate_rows(top_subscriptions),
            "top_resource_groups": _aggregate_rows(top_resource_groups),
        }

    def list_recommendations(
        self,
        *,
        search: str = "",
        category: str = "",
        opportunity_type: str = "",
        subscription_id: str = "",
        resource_group: str = "",
        effort: str = "",
        risk: str = "",
        confidence: str = "",
        quantified_only: bool = False,
    ) -> list[dict[str, Any]]:
        where_sql, params = self._build_recommendation_filter_sql(
            search=search,
            category=category,
            opportunity_type=opportunity_type,
            subscription_id=subscription_id,
            resource_group=resource_group,
            effort=effort,
            risk=risk,
            confidence=confidence,
            quantified_only=quantified_only,
        )
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT {self._recommendation_select_columns_sql()}
                    FROM recommendations
                    {where_sql}
                    ORDER BY {self._recommendation_order_sql()}
                    """,
                    params,
                ).fetchall()
            finally:
                conn.close()

        return self._hydrate_recommendation_rows(rows)

    def get_recommendation(self, recommendation_id: str) -> dict[str, Any] | None:
        recommendation_id = _text(recommendation_id)
        if not recommendation_id:
            return None
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"""
                    SELECT {self._recommendation_select_columns_sql()}
                    FROM recommendations
                    WHERE recommendation_id = ?
                    """,
                    [recommendation_id],
                ).fetchall()
            finally:
                conn.close()
        hydrated = self._hydrate_recommendation_rows(rows)
        return hydrated[0] if hydrated else None

    def get_ai_cost_summary(self, lookback_days: int | None = None) -> dict[str, Any] | None:
        window = self._ai_window(lookback_days)
        if window is None:
            return None
        window_start, window_end = window
        with self._lock:
            conn = self._connect()
            try:
                totals = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS usage_record_count,
                        COALESCE(SUM(request_count), 0) AS request_count,
                        COALESCE(SUM(input_tokens), 0) AS input_tokens,
                        COALESCE(SUM(output_tokens), 0) AS output_tokens,
                        COALESCE(SUM(estimated_tokens), 0) AS estimated_tokens,
                        COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                        MIN(currency) AS currency,
                        MIN(recorded_date) AS coverage_start,
                        MAX(recorded_date) AS coverage_end
                    FROM ai_usage_records
                    WHERE recorded_date BETWEEN ? AND ?
                    """,
                    [window_start, window_end],
                ).fetchone()
                top_model = conn.execute(
                    """
                    SELECT COALESCE(NULLIF(model_id, ''), 'Unknown')
                    FROM ai_usage_records
                    WHERE recorded_date BETWEEN ? AND ?
                    GROUP BY 1
                    ORDER BY SUM(estimated_cost) DESC, SUM(request_count) DESC, 1 ASC
                    LIMIT 1
                    """,
                    [window_start, window_end],
                ).fetchone()
                top_feature = conn.execute(
                    """
                    SELECT COALESCE(NULLIF(feature_surface, ''), 'Unknown')
                    FROM ai_usage_records
                    WHERE recorded_date BETWEEN ? AND ?
                    GROUP BY 1
                    ORDER BY SUM(estimated_cost) DESC, SUM(request_count) DESC, 1 ASC
                    LIMIT 1
                    """,
                    [window_start, window_end],
                ).fetchone()
            finally:
                conn.close()
        if totals is None or _int(totals[0]) == 0:
            return None
        return {
            "lookback_days": max(int(lookback_days or self._default_lookback_days), 1),
            "usage_record_count": _int(totals[0]),
            "request_count": _int(totals[1]),
            "input_tokens": _int(totals[2]),
            "output_tokens": _int(totals[3]),
            "estimated_tokens": _int(totals[4]),
            "estimated_cost": round(_float(totals[5]), 6),
            "currency": _text(totals[6] or "USD") or "USD",
            "top_model": _text(top_model[0] if top_model else ""),
            "top_feature": _text(top_feature[0] if top_feature else ""),
            "window_start": _text(totals[7]),
            "window_end": _text(totals[8]),
        }

    def get_ai_cost_trend(self, lookback_days: int | None = None) -> list[dict[str, Any]]:
        window = self._ai_window(lookback_days)
        if window is None:
            return []
        window_start, window_end = window
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT
                        recorded_date,
                        COALESCE(SUM(request_count), 0) AS request_count,
                        COALESCE(SUM(input_tokens), 0) AS input_tokens,
                        COALESCE(SUM(output_tokens), 0) AS output_tokens,
                        COALESCE(SUM(estimated_tokens), 0) AS estimated_tokens,
                        COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                        MIN(currency) AS currency
                    FROM ai_usage_records
                    WHERE recorded_date BETWEEN ? AND ?
                    GROUP BY recorded_date
                    ORDER BY recorded_date ASC
                    """,
                    [window_start, window_end],
                ).fetchall()
            finally:
                conn.close()
        return [
            {
                "date": _text(row[0]),
                "request_count": _int(row[1]),
                "input_tokens": _int(row[2]),
                "output_tokens": _int(row[3]),
                "estimated_tokens": _int(row[4]),
                "estimated_cost": round(_float(row[5]), 6),
                "currency": _text(row[6] or "USD") or "USD",
            }
            for row in rows
        ]

    def get_ai_cost_breakdown(self, group_by: str, lookback_days: int | None = None) -> list[dict[str, Any]]:
        column_map = {
            "model": "model_id",
            "provider": "provider",
            "feature": "feature_surface",
            "app": "app_surface",
            "team": "team",
            "actor": "actor_id",
        }
        target_column = column_map.get(_text(group_by).lower(), "model_id")
        window = self._ai_window(lookback_days)
        if window is None:
            return []
        window_start, window_end = window
        with self._lock:
            conn = self._connect()
            try:
                total_row = conn.execute(
                    """
                    SELECT COALESCE(SUM(estimated_cost), 0)
                    FROM ai_usage_records
                    WHERE recorded_date BETWEEN ? AND ?
                    """,
                    [window_start, window_end],
                ).fetchone()
                rows = conn.execute(
                    f"""
                    SELECT
                        COALESCE(NULLIF({target_column}, ''), 'Unknown') AS label,
                        COALESCE(SUM(request_count), 0) AS request_count,
                        COALESCE(SUM(estimated_tokens), 0) AS estimated_tokens,
                        COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                        MIN(currency) AS currency
                    FROM ai_usage_records
                    WHERE recorded_date BETWEEN ? AND ?
                    GROUP BY 1
                    ORDER BY estimated_cost DESC, request_count DESC, label ASC
                    """,
                    [window_start, window_end],
                ).fetchall()
            finally:
                conn.close()

        grand_total = _float((total_row or [0])[0])
        return [
            {
                "label": _text(row[0]) or "Unknown",
                "request_count": _int(row[1]),
                "estimated_tokens": _int(row[2]),
                "estimated_cost": round(_float(row[3]), 6),
                "currency": _text(row[4] or "USD") or "USD",
                "share": round((_float(row[3]) / grand_total) if grand_total else 0.0, 4),
            }
            for row in rows
        ]
