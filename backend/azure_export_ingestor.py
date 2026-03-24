"""Azure export ingestion scaffolding.

The future export contract/store modules are intentionally treated as duck-typed
dependencies here so this layer can stay isolated from app startup wiring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from azure_auxiliary_staging import (
    AuxiliaryParseError,
    dataset_descriptor,
    describe_auxiliary_schema,
    stage_auxiliary_delivery,
)
from azure_focus_staging import (
    FOCUS_PARSER_VERSION,
    FocusDeliveryRef,
    FocusParseError,
    describe_focus_schema,
    normalize_focus_delivery,
    stage_focus_delivery,
)

_RETRYABLE_STATUSES = {"quarantined", "failed"}


@dataclass(frozen=True)
class FocusIngestionResult:
    """A small, manifest-friendly ingestion result."""

    manifest: dict[str, Any]
    staged_model: dict[str, Any] | None
    was_duplicate: bool = False


class FocusExportIngestor:
    """Idempotent ingestion helper for Azure export deliveries."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def discover_pending_deliveries(self, deliveries: Iterable[Mapping[str, Any]]) -> list[FocusDeliveryRef]:
        normalized = [normalize_focus_delivery(delivery) for delivery in deliveries]
        normalized.sort(key=lambda item: (item.delivery_time, item.path, item.delivery_key))
        pending: list[FocusDeliveryRef] = []
        seen_in_batch: set[str] = set()
        for delivery in normalized:
            if delivery.delivery_key in seen_in_batch:
                continue
            seen_in_batch.add(delivery.delivery_key)
            manifest = self._get_manifest(delivery.delivery_key)
            if manifest and str(manifest.get("parse_status") or "") not in _RETRYABLE_STATUSES:
                continue
            pending.append(delivery)
        return pending

    def ingest_delivery(
        self,
        delivery: Mapping[str, Any],
        content: str | bytes,
    ) -> FocusIngestionResult:
        normalized = normalize_focus_delivery(delivery)
        descriptor = dataset_descriptor(normalized.dataset)
        existing = self._get_manifest(normalized.delivery_key)
        if existing and str(existing.get("parse_status") or "") not in _RETRYABLE_STATUSES:
            manifest = existing or self._manifest_for_delivery(
                normalized,
                parse_status="duplicate",
                row_count=0,
                error_details="delivery already processed",
            )
            return FocusIngestionResult(manifest=manifest, staged_model=None, was_duplicate=True)

        if descriptor.dataset_family == "focus":
            schema = describe_focus_schema(content)
            parser_version = FOCUS_PARSER_VERSION
        else:
            schema = describe_auxiliary_schema(content, normalized.dataset)
            parser_version = descriptor.parser_version or "unknown"

        try:
            if descriptor.dataset_family == "focus":
                staged_model = stage_focus_delivery(
                    content,
                    source_path=normalized.path,
                    delivery_time=normalized.delivery_time,
                    delivery_key=normalized.delivery_key,
                )
            else:
                staged_model = stage_auxiliary_delivery(
                    normalized.dataset,
                    content,
                    source_path=normalized.path,
                    delivery_time=normalized.delivery_time,
                    delivery_key=normalized.delivery_key,
                )
            staged_model["parser_version"] = parser_version
            staged_model["schema_signature"] = schema["schema_signature"]
            staged_model["schema_compatible"] = bool(schema["schema_compatible"])
            manifest = self._manifest_for_delivery(
                normalized,
                parse_status="parsed",
                row_count=len(staged_model["rows"]),
                error_details="",
                summary=staged_model["summary"],
                parser_version=parser_version,
                schema_signature=str(schema["schema_signature"] or ""),
                schema_compatible=bool(schema["schema_compatible"]),
            )
            self._store_manifest(manifest)
            self._store_stage_model(normalized.delivery_key, staged_model)
            return FocusIngestionResult(manifest=manifest, staged_model=staged_model)
        except (FocusParseError, AuxiliaryParseError) as exc:
            manifest = self._manifest_for_delivery(
                normalized,
                parse_status="quarantined",
                row_count=0,
                error_details=str(exc),
                parser_version=parser_version,
                schema_signature=str(schema["schema_signature"] or ""),
                schema_compatible=bool(schema["schema_compatible"]),
            )
            self._store_manifest(manifest)
            self._store_quarantine(manifest, content)
            return FocusIngestionResult(manifest=manifest, staged_model=None)

    def ingest_pending_deliveries(
        self,
        deliveries: Iterable[Mapping[str, Any]],
        load_content: Callable[[FocusDeliveryRef], str | bytes],
    ) -> list[FocusIngestionResult]:
        results: list[FocusIngestionResult] = []
        for delivery in self.discover_pending_deliveries(deliveries):
            results.append(self.ingest_delivery(
                {
                    "dataset": delivery.dataset,
                    "scope": delivery.scope,
                    "path": delivery.path,
                    "delivery_time": delivery.delivery_time,
                    "delivery_key": delivery.delivery_key,
                },
                load_content(delivery),
            ))
        return results

    def _manifest_for_delivery(
        self,
        delivery: FocusDeliveryRef,
        *,
        parse_status: str,
        row_count: int,
        error_details: str,
        summary: Mapping[str, Any] | None = None,
        parser_version: str = "",
        schema_signature: str = "",
        schema_compatible: bool = True,
    ) -> dict[str, Any]:
        return {
            "dataset": delivery.dataset,
            "scope": delivery.scope,
            "path": delivery.path,
            "delivery_time": delivery.delivery_time,
            "delivery_key": delivery.delivery_key,
            "parse_status": parse_status,
            "row_count": row_count,
            "error_details": error_details,
            "summary": dict(summary or {}),
            "parser_version": str(parser_version or ""),
            "schema_signature": str(schema_signature or ""),
            "schema_compatible": bool(schema_compatible),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }

    def _delivery_seen(self, delivery_key: str) -> bool:
        for method_name in (
            "has_delivery",
            "has_manifest",
            "delivery_exists",
            "manifest_exists",
        ):
            method = getattr(self._store, method_name, None)
            if callable(method):
                try:
                    return bool(method(delivery_key))
                except TypeError:
                    pass
        for method_name in ("get_manifest", "get_record", "lookup_manifest"):
            method = getattr(self._store, method_name, None)
            if callable(method):
                try:
                    return method(delivery_key) is not None
                except TypeError:
                    pass
        return False

    def _get_manifest(self, delivery_key: str) -> dict[str, Any] | None:
        for method_name in ("get_manifest", "get_record", "lookup_manifest"):
            method = getattr(self._store, method_name, None)
            if callable(method):
                try:
                    result = method(delivery_key)
                except TypeError:
                    continue
                if result is not None:
                    return dict(result)
        return None

    def _store_manifest(self, manifest: Mapping[str, Any]) -> None:
        for method_name in ("record_manifest", "upsert_manifest", "save_manifest", "insert_manifest"):
            method = getattr(self._store, method_name, None)
            if callable(method):
                method(dict(manifest))
                return

    def _store_stage_model(self, delivery_key: str, staged_model: Mapping[str, Any]) -> None:
        for method_name in (
            "record_stage_model",
            "upsert_stage_model",
            "save_stage_model",
            "store_stage_model",
        ):
            method = getattr(self._store, method_name, None)
            if callable(method):
                method(delivery_key, dict(staged_model))
                return

    def _store_quarantine(self, manifest: Mapping[str, Any], content: str | bytes) -> None:
        for method_name in ("record_quarantine", "save_quarantine", "store_quarantine"):
            method = getattr(self._store, method_name, None)
            if callable(method):
                method(dict(manifest), content)
                return
