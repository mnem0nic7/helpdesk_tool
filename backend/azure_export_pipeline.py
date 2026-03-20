"""Local-filesystem-first bridge for Azure export ingestion.

This module connects the landing-zone contract, the SQLite delivery store, and
the FOCUS ingestion layer without requiring Azure SDK dependencies or app
startup changes.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from azure_export_contract import AzureExportPathSpec, validate_delivery_path
from azure_export_ingestor import FocusExportIngestor, FocusIngestionResult
from azure_export_store import AzureExportStore, ExportDeliveryMetadata


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def _default(value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")

    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_default) + "\n", encoding="utf-8")


def _safe_read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _combine_csv_files(source_files: Iterable[Path]) -> str:
    merged_lines: list[str] = []
    expected_header: str | None = None

    for source_file in source_files:
        lines = _safe_read_text(source_file).splitlines()
        if not lines:
            continue
        header = lines[0].strip()
        if not header:
            continue
        if expected_header is None:
            expected_header = header
            merged_lines.append(header)
        elif header != expected_header:
            raise ValueError(f"CSV header mismatch in delivery directory {source_file.parent}")
        merged_lines.extend(line for line in lines[1:] if line.strip())

    if not merged_lines:
        return ""
    return "\n".join(merged_lines) + "\n"


@dataclass(frozen=True)
class DiscoveredExportDelivery:
    """One canonical delivery directory and the source file inside it."""

    spec: AzureExportPathSpec
    source_files: tuple[Path, ...]
    delivery_time: str

    @property
    def delivery_key(self) -> str:
        return str(self.spec.path)

    def as_payload(self) -> dict[str, str]:
        return {
            "dataset": self.spec.dataset,
            "scope": self.spec.scope_key,
            "path": str(self.spec.path),
            "delivery_time": self.delivery_time,
            "delivery_key": self.delivery_key,
            "source_file_count": str(len(self.source_files)),
        }


class AzureExportPipelineStoreAdapter:
    """Duck-typed adapter that gives FocusExportIngestor the hooks it expects."""

    def __init__(
        self,
        store: AzureExportStore,
        *,
        root: str | Path,
        staging_root: str | Path,
        quarantine_root: str | Path,
    ) -> None:
        self._store = store
        self._root = Path(root)
        self._staging_root = Path(staging_root)
        self._quarantine_root = Path(quarantine_root)

    def _resolve_spec(self, delivery_key: str | Path) -> AzureExportPathSpec:
        candidate = Path(delivery_key)
        if not candidate.is_absolute():
            candidate = self._root / candidate
        return validate_delivery_path(candidate, root=self._root)

    def _delivery_root(self, spec: AzureExportPathSpec) -> Path:
        return spec.path.parent.relative_to(self._root)

    def _manifest_path(self, spec: AzureExportPathSpec, *, parse_status: str) -> Path:
        base = self._quarantine_root if parse_status in {"quarantined", "failed"} else self._staging_root
        return base / self._delivery_root(spec) / "manifest.json"

    def _staged_path(self, spec: AzureExportPathSpec) -> Path:
        return self._staging_root / self._delivery_root(spec) / "staged.json"

    def _quarantine_path(self, spec: AzureExportPathSpec) -> Path:
        return self._quarantine_root / self._delivery_root(spec) / "quarantine.json"

    def _payload_path(self, spec: AzureExportPathSpec) -> Path:
        return self._quarantine_root / self._delivery_root(spec) / "payload.csv"

    def _store_row(self, spec: AzureExportPathSpec, **fields: Any) -> dict[str, Any] | None:
        row = self._store.get_delivery_by_path(spec.path)
        if row is None:
            return None
        updater = getattr(self._store, "update_delivery", None)
        if callable(updater):
            return updater(row["delivery_id"], **fields)
        return row

    def has_delivery(self, delivery_key: str) -> bool:
        return self.get_manifest(delivery_key) is not None

    def get_manifest(self, delivery_key: str) -> dict[str, Any] | None:
        spec = self._resolve_spec(delivery_key)
        row = self._store.get_delivery_by_path(spec.path)
        if row is None:
            return None

        payload = dict(row)
        manifest_path = Path(payload.get("manifest_path") or self._manifest_path(spec, parse_status=payload.get("parse_status", "discovered")))
        staged_path = self._staged_path(spec)
        quarantine_path = self._quarantine_path(spec)
        payload["delivery_key"] = str(spec.path)
        payload["manifest_path"] = str(manifest_path)
        payload["staged_path"] = str(staged_path)
        payload["quarantine_path"] = str(quarantine_path)

        if manifest_path.exists():
            try:
                manifest_payload = json.loads(_safe_read_text(manifest_path))
            except json.JSONDecodeError:
                manifest_payload = {}
            if isinstance(manifest_payload, dict):
                payload.update(manifest_payload)
                payload["manifest_path"] = str(manifest_path)
                payload["staged_path"] = str(staged_path)
                payload["quarantine_path"] = str(quarantine_path)

        return payload

    def record_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        spec = self._resolve_spec(manifest.get("path") or manifest.get("delivery_key") or manifest.get("landing_path") or "")
        parse_status = str(manifest.get("parse_status") or "discovered")
        manifest_path = self._manifest_path(spec, parse_status=parse_status)
        staged_path = self._staged_path(spec)
        quarantine_path = self._quarantine_path(spec)
        manifest_payload = dict(manifest)
        manifest_payload.setdefault("dataset", spec.dataset)
        manifest_payload.setdefault("scope", spec.scope_key)
        manifest_payload.setdefault("path", str(spec.path))
        manifest_payload.setdefault("delivery_key", str(spec.path))
        manifest_payload.setdefault("delivery_time", manifest_payload.get("recorded_at") or _utcnow())
        manifest_payload["manifest_path"] = str(manifest_path)
        manifest_payload["staged_path"] = str(staged_path)
        manifest_payload["quarantine_path"] = str(quarantine_path)
        manifest_payload["parse_status"] = parse_status
        _write_json(manifest_path, manifest_payload)

        row = self._store.record_delivery(
            ExportDeliveryMetadata(
                dataset=manifest_payload["dataset"],
                scope_key=manifest_payload["scope"],
                delivery_date=spec.delivery_date,
                run_id=spec.run_id,
                landing_path=spec.path,
                parse_status=parse_status,
                row_count=int(manifest_payload.get("row_count") or 0),
                manifest_path=manifest_path,
                discovered_at=manifest_payload.get("delivery_time") or None,
                parsed_at=manifest_payload.get("recorded_at") or manifest_payload.get("delivery_time") or None,
                error_message=manifest_payload.get("error_details") or manifest_payload.get("error_message") or None,
            )
        )

        if parse_status in {"quarantined", "failed"}:
            self._store_row(spec, parse_status=parse_status, manifest_path=str(manifest_path), error_message=manifest_payload.get("error_details") or manifest_payload.get("error_message") or None)
        return row

    def record_stage_model(self, delivery_key: str, staged_model: dict[str, Any]) -> dict[str, Any] | None:
        spec = self._resolve_spec(delivery_key)
        staged_path = self._staged_path(spec)
        _write_json(staged_path, staged_model)
        return self._store_row(
            spec,
            parse_status="parsed",
            row_count=int(staged_model.get("summary", {}).get("row_count") or len(staged_model.get("rows", [])) or 0),
            parsed_at=_utcnow(),
        )

    def record_quarantine(self, manifest: dict[str, Any], content: str | bytes) -> dict[str, Any] | None:
        spec = self._resolve_spec(manifest.get("path") or manifest.get("delivery_key") or manifest.get("landing_path") or "")
        quarantine_path = self._quarantine_path(spec)
        payload_path = self._payload_path(spec)
        quarantine_payload = {
            "manifest": dict(manifest),
            "content_path": str(payload_path),
            "quarantine_path": str(quarantine_path),
            "recorded_at": _utcnow(),
        }
        _write_json(quarantine_path, quarantine_payload)
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            payload_path.write_bytes(content)
        else:
            payload_path.write_text(content, encoding="utf-8")
        return self._store_row(
            spec,
            parse_status="quarantined",
            error_message=manifest.get("error_details") or manifest.get("error_message") or "quarantined",
            parsed_at=manifest.get("recorded_at") or _utcnow(),
        )

    def upsert_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return self.record_manifest(manifest)

    def save_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return self.record_manifest(manifest)

    def insert_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return self.record_manifest(manifest)

    def save_stage_model(self, delivery_key: str, staged_model: dict[str, Any]) -> dict[str, Any] | None:
        return self.record_stage_model(delivery_key, staged_model)

    def upsert_stage_model(self, delivery_key: str, staged_model: dict[str, Any]) -> dict[str, Any] | None:
        return self.record_stage_model(delivery_key, staged_model)

    def store_stage_model(self, delivery_key: str, staged_model: dict[str, Any]) -> dict[str, Any] | None:
        return self.record_stage_model(delivery_key, staged_model)

    def save_quarantine(self, manifest: dict[str, Any], content: str | bytes) -> dict[str, Any] | None:
        return self.record_quarantine(manifest, content)

    def store_quarantine(self, manifest: dict[str, Any], content: str | bytes) -> dict[str, Any] | None:
        return self.record_quarantine(manifest, content)

    def list_deliveries(self) -> list[dict[str, Any]]:
        return self._store.list_deliveries()


class AzureExportPipeline:
    """Small orchestration layer over discovery, ingestion, and health checks."""

    def __init__(
        self,
        root: str | Path,
        *,
        store: AzureExportStore | None = None,
        staging_root: str | Path | None = None,
        quarantine_root: str | Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.staging_root = Path(staging_root or (self.root / "_staging"))
        self.quarantine_root = Path(quarantine_root or (self.root / "_quarantine"))
        self.store = store or AzureExportStore()
        self.store_adapter = AzureExportPipelineStoreAdapter(
            self.store,
            root=self.root,
            staging_root=self.staging_root,
            quarantine_root=self.quarantine_root,
        )
        self.ingestor = FocusExportIngestor(self.store_adapter)
        self._last_scan_at: str | None = None

    def discover_deliveries(self) -> list[DiscoveredExportDelivery]:
        deliveries: list[DiscoveredExportDelivery] = []
        if not self.root.exists():
            return deliveries

        for raw_dir in sorted(self.root.glob("*/*/delivery_date=*/run=*/raw")):
            if not raw_dir.is_dir():
                continue
            try:
                spec = validate_delivery_path(raw_dir, root=self.root)
            except ValueError:
                continue
            csv_files = sorted(
                candidate for candidate in raw_dir.iterdir() if candidate.is_file() and candidate.suffix.lower() == ".csv"
            )
            if not csv_files:
                continue
            delivery_time = datetime.fromtimestamp(
                max(candidate.stat().st_mtime for candidate in csv_files),
                tz=timezone.utc,
            ).isoformat()
            deliveries.append(
                DiscoveredExportDelivery(
                    spec=spec,
                    source_files=tuple(csv_files),
                    delivery_time=delivery_time,
                )
            )

        return deliveries

    def ingest_discovered_deliveries(
        self, deliveries: Iterable[DiscoveredExportDelivery] | None = None
    ) -> list[FocusIngestionResult]:
        discovered = list(deliveries or self.discover_deliveries())
        if not discovered:
            self._last_scan_at = _utcnow()
            return []

        delivery_map = {delivery.delivery_key: delivery for delivery in discovered}

        def load_content(delivery_ref: Any) -> str | bytes:
            candidate = delivery_map.get(str(getattr(delivery_ref, "path", "")))
            if candidate is None:
                candidate = delivery_map.get(str(getattr(delivery_ref, "delivery_key", "")))
            if candidate is None:
                raise KeyError(f"Unknown delivery {getattr(delivery_ref, 'path', None)!r}")
            return _combine_csv_files(candidate.source_files)

        results = self.ingestor.ingest_pending_deliveries(
            [delivery.as_payload() for delivery in discovered],
            load_content,
        )
        self._last_scan_at = _utcnow()
        return results

    def sync(self) -> list[FocusIngestionResult]:
        return self.ingest_discovered_deliveries()

    def health_summary(self) -> dict[str, Any]:
        deliveries = self.store.list_deliveries()
        status_counts = Counter(str(row.get("parse_status") or "unknown") for row in deliveries)
        latest = deliveries[-1] if deliveries else None

        summary = {
            "root": str(self.root),
            "staging_root": str(self.staging_root),
            "quarantine_root": str(self.quarantine_root),
            "last_scan_at": self._last_scan_at,
            "delivery_count": len(deliveries),
            "parsed_count": int(status_counts.get("parsed", 0)),
            "quarantined_count": int(status_counts.get("quarantined", 0)),
            "staged_snapshot_count": len(list(self.staging_root.rglob("staged.json"))) if self.staging_root.exists() else 0,
            "quarantine_artifact_count": len(list(self.quarantine_root.rglob("quarantine.json"))) if self.quarantine_root.exists() else 0,
            "status_counts": dict(status_counts),
            "latest_delivery": None,
        }
        if latest is not None:
            summary["latest_delivery"] = {
                "delivery_id": latest.get("delivery_id"),
                "landing_path": latest.get("landing_path"),
                "parse_status": latest.get("parse_status"),
                "row_count": latest.get("row_count"),
                "manifest_path": latest.get("manifest_path"),
            }
        return summary
