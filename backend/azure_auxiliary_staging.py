"""Staging helpers for non-FOCUS Azure FinOps CSV datasets."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping

PRICE_SHEET_PARSER_VERSION = "price-sheet-csv-v1"
RESERVATION_RECOMMENDATIONS_PARSER_VERSION = "reservation-recommendations-csv-v1"

PRICE_SHEET_DATASET_ALIASES = {
    "price-sheet",
    "price_sheet",
    "pricesheet",
    "price-sheet-mca",
    "price-sheet-ea",
}
RESERVATION_RECOMMENDATIONS_DATASET_ALIASES = {
    "reservation-recommendations",
    "reservation_recommendations",
    "reservationrecommendations",
    "reservation-recommendation",
}

_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")
_PRICE_SHEET_ID_FIELDS = ("MeterId", "ProductId", "SkuId", "MeterName", "SkuName")


class AuxiliaryParseError(ValueError):
    """Raised when an auxiliary dataset cannot be normalized."""


@dataclass(frozen=True)
class AuxiliaryDatasetDescriptor:
    dataset_family: str
    parser_version: str


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalized_key(value: str) -> str:
    return _SEPARATOR_RE.sub("", _text(value).lower())


def _canonical_dataset_family(dataset: str) -> str:
    normalized = _text(dataset).lower().replace("_", "-")
    if normalized == "focus":
        return "focus"
    if normalized in PRICE_SHEET_DATASET_ALIASES:
        return "price_sheet"
    if normalized in RESERVATION_RECOMMENDATIONS_DATASET_ALIASES:
        return "reservation_recommendations"
    return "unknown"


def dataset_descriptor(dataset: str) -> AuxiliaryDatasetDescriptor:
    family = _canonical_dataset_family(dataset)
    if family == "price_sheet":
        return AuxiliaryDatasetDescriptor(dataset_family=family, parser_version=PRICE_SHEET_PARSER_VERSION)
    if family == "reservation_recommendations":
        return AuxiliaryDatasetDescriptor(
            dataset_family=family,
            parser_version=RESERVATION_RECOMMENDATIONS_PARSER_VERSION,
        )
    return AuxiliaryDatasetDescriptor(dataset_family=family, parser_version="")


def _read_csv_rows(content: str | bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else str(content)
    reader = csv.DictReader(io.StringIO(text))
    header = [str(field or "").strip() for field in (reader.fieldnames or []) if str(field or "").strip()]
    rows: list[dict[str, str]] = []
    for row in reader:
        rows.append({str(key or "").strip(): _text(value) for key, value in (row or {}).items() if str(key or "").strip()})
    return header, rows


def _schema_signature(header: Iterable[str]) -> str:
    canonical = "|".join(_normalized_key(column) for column in header)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _pick(row: Mapping[str, Any], *candidates: str) -> str:
    normalized = {_normalized_key(key): value for key, value in row.items()}
    for candidate in candidates:
        value = normalized.get(_normalized_key(candidate))
        if _text(value):
            return _text(value)
    return ""


def _parse_date(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:  # pragma: no cover - defensive
        raise AuxiliaryParseError(f"Invalid date value: {text}") from exc


def _decimal_to_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def describe_auxiliary_schema(content: str | bytes, dataset: str) -> dict[str, Any]:
    descriptor = dataset_descriptor(dataset)
    header, _ = _read_csv_rows(content)
    normalized_header = {_normalized_key(column) for column in header}

    if descriptor.dataset_family == "price_sheet":
        compatible = "unitprice" in normalized_header and any(_normalized_key(field) in normalized_header for field in _PRICE_SHEET_ID_FIELDS)
    elif descriptor.dataset_family == "reservation_recommendations":
        compatible = "recommendquantity" in normalized_header or "recommendedquantity" in normalized_header
    else:
        compatible = False

    return {
        "parser_version": descriptor.parser_version,
        "schema_signature": _schema_signature(header),
        "schema_compatible": compatible,
        "schema_columns": header,
    }


def stage_price_sheet_delivery(
    content: str | bytes,
    *,
    source_path: str = "",
    delivery_time: str = "",
    delivery_key: str = "",
) -> dict[str, Any]:
    header, raw_rows = _read_csv_rows(content)
    schema = describe_auxiliary_schema(content, "price-sheet")
    if not schema["schema_compatible"]:
        raise AuxiliaryParseError("Price sheet export is missing a unit price column or an identifying meter/product column")

    rows: list[dict[str, Any]] = []
    currencies: set[str] = set()
    price_types: set[str] = set()
    effective_dates: list[str] = []
    total_unit_price = Decimal("0")

    for row_number, raw in enumerate(raw_rows, start=1):
        unit_price_text = _pick(raw, "UnitPrice", "Unit Price", "RetailPrice", "Retail Price", "Price")
        if not unit_price_text:
            continue
        identifier = _pick(raw, "MeterId", "Meter ID", "ProductId", "Product ID", "SkuId", "SKU ID", "MeterName", "SkuName")
        if not identifier:
            continue
        currency = _pick(raw, "CurrencyCode", "Currency", "BillingCurrency", "Billing Currency") or "USD"
        price_type = _pick(raw, "PriceType", "Price Type", "Type") or "consumption"
        effective_start = _parse_date(_pick(raw, "EffectiveStartDate", "Effective Start Date"))
        effective_end = _parse_date(_pick(raw, "EffectiveEndDate", "Effective End Date"))
        unit_price = Decimal(str(_float(unit_price_text)))
        total_unit_price += unit_price
        currencies.add(currency)
        if price_type:
            price_types.add(price_type)
        if effective_start:
            effective_dates.append(effective_start)
        if effective_end:
            effective_dates.append(effective_end)
        rows.append(
            {
                "row_number": row_number,
                "meter_id": _pick(raw, "MeterId", "Meter ID"),
                "meter_name": _pick(raw, "MeterName", "Meter Name"),
                "meter_category": _pick(raw, "MeterCategory", "Meter Category"),
                "meter_subcategory": _pick(raw, "MeterSubCategory", "Meter SubCategory", "Meter Subcategory"),
                "meter_region": _pick(raw, "MeterRegion", "Meter Region", "Location"),
                "product_id": _pick(raw, "ProductId", "Product ID"),
                "product_name": _pick(raw, "ProductName", "Product Name", "Product"),
                "sku_id": _pick(raw, "SkuId", "SKU ID"),
                "sku_name": _pick(raw, "SkuName", "SKU Name"),
                "service_family": _pick(raw, "ServiceFamily", "Service Family"),
                "price_type": price_type,
                "term": _pick(raw, "Term"),
                "unit_of_measure": _pick(raw, "UnitOfMeasure", "Unit Of Measure"),
                "unit_price": float(unit_price),
                "market_price": _float(_pick(raw, "MarketPrice", "Market Price")),
                "base_price": _float(_pick(raw, "BasePrice", "Base Price")),
                "currency": currency,
                "billing_currency": _pick(raw, "BillingCurrency", "Billing Currency") or currency,
                "effective_start_date": effective_start,
                "effective_end_date": effective_end,
                "raw": raw,
            }
        )

    return {
        "dataset_family": "price_sheet",
        "delivery_key": delivery_key,
        "source_path": source_path,
        "delivery_time": delivery_time,
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "currencies": sorted(currencies),
            "price_types": sorted(price_types),
            "unit_price_total": _decimal_to_float(total_unit_price),
            "effective_start_date": min(effective_dates) if effective_dates else "",
            "effective_end_date": max(effective_dates) if effective_dates else "",
        },
        "schema_signature": schema["schema_signature"],
        "schema_compatible": schema["schema_compatible"],
        "parser_version": PRICE_SHEET_PARSER_VERSION,
        "header": header,
    }


def stage_reservation_recommendations_delivery(
    content: str | bytes,
    *,
    source_path: str = "",
    delivery_time: str = "",
    delivery_key: str = "",
) -> dict[str, Any]:
    header, raw_rows = _read_csv_rows(content)
    schema = describe_auxiliary_schema(content, "reservation-recommendations")
    if not schema["schema_compatible"]:
        raise AuxiliaryParseError("Reservation recommendations export is missing a recommended quantity column")

    rows: list[dict[str, Any]] = []
    terms: set[str] = set()
    scopes: set[str] = set()
    total_net_savings = Decimal("0")

    for row_number, raw in enumerate(raw_rows, start=1):
        recommended_quantity = _float(_pick(raw, "RecommendedQuantity", "Recommended Quantity"))
        if recommended_quantity <= 0:
            continue
        term = _pick(raw, "Term")
        scope = _pick(raw, "Scope", "scope")
        net_savings = Decimal(str(_float(_pick(raw, "NetSavings", "Net Savings Total", "Net Savings"))))
        total_net_savings += net_savings
        if term:
            terms.add(term)
        if scope:
            scopes.add(scope)
        rows.append(
            {
                "row_number": row_number,
                "cost_without_reserved_instances": _float(_pick(raw, "CostWithNoReservedInstances", "Cost With No ReservedInstances")),
                "first_usage_date": _parse_date(_pick(raw, "FirstUsageDate", "First UsageDate")),
                "instance_flexibility_ratio": _float(_pick(raw, "InstanceFlexibilityRatio", "Instance Flexibility Ratio")),
                "instance_flexibility_group": _pick(raw, "InstanceFlexibilityGroup", "Instance Flexibility Group"),
                "location": _pick(raw, "Location"),
                "lookback_period": _float(_pick(raw, "LookBackPeriod", "Look Back Period")),
                "meter_id": _pick(raw, "MeterId", "MeterID", "Meter ID"),
                "net_savings": float(net_savings),
                "normalized_size": _pick(raw, "NormalizedSize", "Normalized Size"),
                "recommended_quantity": recommended_quantity,
                "recommended_quantity_normalized": _float(
                    _pick(raw, "RecommendedQuantityNormalized", "Recommended Quantity Normalized")
                ),
                "resource_type": _pick(raw, "ResourceType", "Resource Type"),
                "scope": scope,
                "sku_name": _pick(raw, "SkuName", "SKU Name"),
                "sku_properties": _pick(raw, "SkuProperties", "Sku Properties"),
                "subscription_id": _pick(raw, "SubscriptionId", "Subscription ID"),
                "term": term,
                "total_cost_with_reserved_instances": _float(
                    _pick(raw, "TotalCostWithReservedInstances", "Total Cost With ReservedInstances")
                ),
                "raw": raw,
            }
        )

    return {
        "dataset_family": "reservation_recommendations",
        "delivery_key": delivery_key,
        "source_path": source_path,
        "delivery_time": delivery_time,
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "terms": sorted(terms),
            "scopes": sorted(scopes),
            "total_net_savings": _decimal_to_float(total_net_savings),
        },
        "schema_signature": schema["schema_signature"],
        "schema_compatible": schema["schema_compatible"],
        "parser_version": RESERVATION_RECOMMENDATIONS_PARSER_VERSION,
        "header": header,
    }


def stage_auxiliary_delivery(
    dataset: str,
    content: str | bytes,
    *,
    source_path: str = "",
    delivery_time: str = "",
    delivery_key: str = "",
) -> dict[str, Any]:
    descriptor = dataset_descriptor(dataset)
    if descriptor.dataset_family == "price_sheet":
        return stage_price_sheet_delivery(
            content,
            source_path=source_path,
            delivery_time=delivery_time,
            delivery_key=delivery_key,
        )
    if descriptor.dataset_family == "reservation_recommendations":
        return stage_reservation_recommendations_delivery(
            content,
            source_path=source_path,
            delivery_time=delivery_time,
            delivery_key=delivery_key,
        )
    raise AuxiliaryParseError(f"Unsupported auxiliary dataset: {dataset}")
