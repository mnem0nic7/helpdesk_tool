"""FOCUS export parsing and staged read-model helpers.

This module intentionally stays small and self-contained so the future export
contract/store layer can wire into it without forcing app startup changes.
"""

from __future__ import annotations

from collections import defaultdict
from csv import DictReader
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
from typing import Any, Iterable, Mapping


_SEMANTIC_COLUMN_GROUPS: dict[str, tuple[str, ...]] = {
    "usage_date": ("UsageDate", "Date"),
    "service_name": ("ServiceName", "ConsumedService", "MeterCategory"),
    "subscription_name": ("SubscriptionName", "SubscriptionId"),
    "resource_group_name": ("ResourceGroupName",),
    "currency": ("BillingCurrencyCode", "Currency", "PricingCurrencyCode"),
    "actual_cost": ("CostInBillingCurrency", "ActualCost", "Cost"),
}
_ACTUAL_COST_COLUMNS = ("CostInBillingCurrency", "ActualCost", "Cost")
_AMORTIZED_COST_COLUMNS = ("AmortizedCostInBillingCurrency", "AmortizedCost")
_DATE_COLUMNS = ("UsageDate", "Date")
FOCUS_PARSER_VERSION = "focus-csv-v1"


class FocusParseError(ValueError):
    """Raised when a FOCUS delivery cannot be normalized."""

    def __init__(
        self,
        message: str,
        *,
        source_path: str | None = None,
        missing_columns: Iterable[str] | None = None,
        row_number: int | None = None,
    ) -> None:
        super().__init__(message)
        self.source_path = source_path or ""
        self.missing_columns = tuple(missing_columns or ())
        self.row_number = row_number


@dataclass(frozen=True)
class FocusDeliveryRef:
    """Canonical metadata for a single export delivery."""

    dataset: str
    scope: str
    path: str
    delivery_time: str
    delivery_key: str


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decimal(value: Any, *, field_name: str, source_path: str, row_number: int) -> Decimal:
    text = _text(value)
    if not text:
        raise FocusParseError(
            f"FOCUS export row {row_number} is missing required value for {field_name}",
            source_path=source_path,
            row_number=row_number,
        )
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise FocusParseError(
            f"FOCUS export row {row_number} has invalid {field_name}: {text}",
            source_path=source_path,
            row_number=row_number,
        ) from exc


def _pick_first(row: Mapping[str, Any], candidates: Iterable[str]) -> str:
    for name in candidates:
        text = _text(row.get(name))
        if text:
            return text
    return ""


def _missing_semantic_columns(header: Iterable[str]) -> list[str]:
    header_set = {str(name) for name in header}
    missing: list[str] = []
    for semantic_name, candidates in _SEMANTIC_COLUMN_GROUPS.items():
        if not any(candidate in header_set for candidate in candidates):
            missing.append(f"{semantic_name} ({' or '.join(candidates)})")
    return missing


def _read_focus_header(content: str | bytes) -> list[str]:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else str(content)
    reader = DictReader(io.StringIO(text))
    return [str(name).strip() for name in (reader.fieldnames or []) if str(name).strip()]


def describe_focus_schema(content: str | bytes) -> dict[str, Any]:
    header = _read_focus_header(content)
    signature = ""
    if header:
        digest = hashlib.sha256("\n".join(header).encode("utf-8")).hexdigest()
        signature = f"sha256:{digest}"
    missing_columns = _missing_semantic_columns(header)
    return {
        "parser_version": FOCUS_PARSER_VERSION,
        "schema_signature": signature,
        "schema_compatible": not missing_columns,
        "schema_columns": header,
        "missing_columns": missing_columns,
    }


def _normalized_date(value: str, *, source_path: str, row_number: int) -> str:
    if not value:
        raise FocusParseError(
            f"FOCUS export row {row_number} is missing a usage date",
            source_path=source_path,
            row_number=row_number,
        )
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError as exc:
        raise FocusParseError(
            f"FOCUS export row {row_number} has invalid usage date: {value}",
            source_path=source_path,
            row_number=row_number,
        ) from exc
    return parsed.isoformat()


def normalize_focus_delivery(delivery: Mapping[str, Any]) -> FocusDeliveryRef:
    """Normalize a delivery reference without assuming the future store shape."""

    dataset = _text(delivery.get("dataset")) or "FOCUS"
    scope = _text(delivery.get("scope")) or "unknown"
    path = _text(delivery.get("path")) or _text(delivery.get("delivery_path"))
    delivery_time = _text(delivery.get("delivery_time")) or _text(delivery.get("discovered_at"))
    delivery_key = _text(delivery.get("delivery_key")) or path or f"{dataset}:{scope}:{delivery_time}"
    if not path:
        path = delivery_key
    return FocusDeliveryRef(
        dataset=dataset,
        scope=scope,
        path=path,
        delivery_time=delivery_time,
        delivery_key=delivery_key,
    )


def parse_focus_csv(content: str | bytes, *, source_path: str = "") -> list[dict[str, Any]]:
    """Parse a FOCUS CSV export into normalized row dictionaries."""

    if isinstance(content, bytes):
        text = content.decode("utf-8-sig")
    else:
        text = str(content)

    reader = DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    missing_columns = _missing_semantic_columns(header)
    if missing_columns:
        raise FocusParseError(
            f"FOCUS export is missing required columns: {', '.join(missing_columns)}",
            source_path=source_path,
            missing_columns=missing_columns,
        )

    rows: list[dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        if not row or not any(_text(value) for value in row.values()):
            continue
        usage_date = _normalized_date(_pick_first(row, _DATE_COLUMNS), source_path=source_path, row_number=row_number)
        actual_cost = _decimal(
            _pick_first(row, _ACTUAL_COST_COLUMNS),
            field_name="actual cost",
            source_path=source_path,
            row_number=row_number,
        )
        amortized_text = _pick_first(row, _AMORTIZED_COST_COLUMNS)
        amortized_cost = actual_cost if not amortized_text else _decimal(
            amortized_text,
            field_name="amortized cost",
            source_path=source_path,
            row_number=row_number,
        )
        rows.append(
            {
                "row_number": row_number,
                "usage_date": usage_date,
                "service_name": _pick_first(row, ("ServiceName", "ConsumedService", "MeterCategory")),
                "subscription_name": _pick_first(row, ("SubscriptionName", "SubscriptionId")),
                "resource_group_name": _pick_first(row, ("ResourceGroupName",)),
                "resource_id": _pick_first(row, ("ResourceId",)),
                "currency": _pick_first(row, ("BillingCurrencyCode", "Currency", "PricingCurrencyCode")),
                "charge_type": _pick_first(row, ("ChargeType",)),
                "meter_category": _pick_first(row, ("MeterCategory",)),
                "consumed_service": _pick_first(row, ("ConsumedService",)),
                "actual_cost": actual_cost,
                "amortized_cost": amortized_cost,
                "source_path": source_path,
                "raw": {key: _text(value) for key, value in row.items()},
            }
        )

    return rows


def _decimal_to_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _aggregate_rows(rows: Iterable[Mapping[str, Any]], key_field: str) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            key_field: "",
            "row_count": 0,
            "actual_cost": Decimal("0"),
            "amortized_cost": Decimal("0"),
        }
    )
    for row in rows:
        key = _text(row.get(key_field)) or "Unknown"
        bucket = totals[key]
        bucket[key_field] = key
        bucket["row_count"] += 1
        bucket["actual_cost"] += Decimal(str(row.get("actual_cost") or "0"))
        bucket["amortized_cost"] += Decimal(str(row.get("amortized_cost") or "0"))
    aggregated = [
        {
            key_field: bucket[key_field],
            "row_count": bucket["row_count"],
            "actual_cost": _decimal_to_float(bucket["actual_cost"]),
            "amortized_cost": _decimal_to_float(bucket["amortized_cost"]),
        }
        for bucket in totals.values()
    ]
    return sorted(aggregated, key=lambda item: (-item["actual_cost"], item[key_field]))


def build_focus_staged_model(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_path: str = "",
    delivery_time: str = "",
    delivery_key: str = "",
) -> dict[str, Any]:
    """Build the staged read model used by summary, trend, and breakdown views."""

    staged_rows = [dict(row) for row in rows]
    if not staged_rows:
        return {
            "delivery_key": delivery_key,
            "source_path": source_path,
            "delivery_time": delivery_time,
            "rows": [],
            "summary": {
                "row_count": 0,
                "currency": "",
                "currencies": [],
                "actual_cost_total": 0.0,
                "amortized_cost_total": 0.0,
                "usage_date_start": "",
                "usage_date_end": "",
            },
            "trend": [],
            "breakdowns": {"service": [], "subscription": [], "resource_group": []},
        }

    currencies = sorted({str(row.get("currency") or "").strip() for row in staged_rows if _text(row.get("currency"))})
    dates = sorted(str(row["usage_date"]) for row in staged_rows)
    actual_total = sum((Decimal(str(row.get("actual_cost") or "0")) for row in staged_rows), start=Decimal("0"))
    amortized_total = sum((Decimal(str(row.get("amortized_cost") or "0")) for row in staged_rows), start=Decimal("0"))

    trend_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"usage_date": "", "row_count": 0, "actual_cost": Decimal("0"), "amortized_cost": Decimal("0")}
    )
    for row in staged_rows:
        bucket = trend_totals[str(row["usage_date"])]
        bucket["usage_date"] = str(row["usage_date"])
        bucket["row_count"] += 1
        bucket["actual_cost"] += Decimal(str(row.get("actual_cost") or "0"))
        bucket["amortized_cost"] += Decimal(str(row.get("amortized_cost") or "0"))

    trend = [
        {
            "usage_date": bucket["usage_date"],
            "row_count": bucket["row_count"],
            "actual_cost": _decimal_to_float(bucket["actual_cost"]),
            "amortized_cost": _decimal_to_float(bucket["amortized_cost"]),
        }
        for bucket in sorted(trend_totals.values(), key=lambda item: item["usage_date"])
    ]

    breakdowns = {
        "service": _aggregate_rows(staged_rows, "service_name"),
        "subscription": _aggregate_rows(staged_rows, "subscription_name"),
        "resource_group": _aggregate_rows(staged_rows, "resource_group_name"),
    }

    return {
        "delivery_key": delivery_key,
        "source_path": source_path,
        "delivery_time": delivery_time,
        "rows": staged_rows,
        "summary": {
            "row_count": len(staged_rows),
            "currency": currencies[0] if len(currencies) == 1 else "",
            "currencies": currencies,
            "actual_cost_total": _decimal_to_float(actual_total),
            "amortized_cost_total": _decimal_to_float(amortized_total),
            "usage_date_start": dates[0],
            "usage_date_end": dates[-1],
        },
        "trend": trend,
        "breakdowns": breakdowns,
    }


def stage_focus_delivery(
    content: str | bytes,
    *,
    source_path: str = "",
    delivery_time: str = "",
    delivery_key: str = "",
) -> dict[str, Any]:
    """Parse and stage one FOCUS delivery."""

    rows = parse_focus_csv(content, source_path=source_path)
    return build_focus_staged_model(
        rows,
        source_path=source_path,
        delivery_time=delivery_time,
        delivery_key=delivery_key,
    )
