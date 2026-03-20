"""Helpers for Azure Cost export landing-zone paths.

The contract is intentionally small and filesystem-first so tests can exercise it
without needing Azure SDK dependencies. Callers supply a canonical dataset name,
scope key, delivery date, and run identifier; the helpers build and validate the
directory layout used for raw, staged, manifest, and quarantine partitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

_ALLOWED_PARTITIONS = {"raw", "staged", "manifest", "quarantine"}
_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9_.=-]*$")


def _coerce_path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)


def _coerce_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"Unsupported date value: {type(value)!r}")


def _normalize_segment(value: str) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9_.=-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip("._-")
    if not text or not _SEGMENT_RE.match(text):
        raise ValueError(f"Invalid path segment: {value!r}")
    return text


def normalize_dataset_name(value: str) -> str:
    """Normalize a dataset name for use in landing-zone paths."""

    return _normalize_segment(value)


def build_scope_key(scope_type: str, scope_value: str) -> str:
    """Build a stable scope key for landing-zone paths."""

    return f"{_normalize_segment(scope_type)}__{_normalize_segment(scope_value)}"


def normalize_partition_name(value: str) -> str:
    partition = _normalize_segment(value)
    if partition not in _ALLOWED_PARTITIONS:
        raise ValueError(f"Unsupported landing-zone partition: {value!r}")
    return partition


@dataclass(frozen=True)
class AzureExportPathSpec:
    """Canonical landing-zone layout for a single export delivery."""

    root: Path
    dataset: str
    scope_key: str
    delivery_date: date
    run_id: str
    partition: str = "raw"

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", _coerce_path(self.root))
        object.__setattr__(self, "dataset", normalize_dataset_name(self.dataset))
        object.__setattr__(self, "scope_key", _normalize_segment(self.scope_key))
        object.__setattr__(self, "delivery_date", _coerce_date(self.delivery_date))
        object.__setattr__(self, "run_id", _normalize_segment(self.run_id))
        object.__setattr__(self, "partition", normalize_partition_name(self.partition))

    @property
    def delivery_dir(self) -> Path:
        return (
            self.root
            / self.dataset
            / self.scope_key
            / f"delivery_date={self.delivery_date.isoformat()}"
            / f"run={self.run_id}"
        )

    @property
    def path(self) -> Path:
        return self.delivery_dir / self.partition

    def partition_path(self, partition: str) -> Path:
        return self.delivery_dir / normalize_partition_name(partition)

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "dataset": self.dataset,
            "scope_key": self.scope_key,
            "delivery_date": self.delivery_date.isoformat(),
            "run_id": self.run_id,
            "partition": self.partition,
            "path": str(self.path),
        }


def build_delivery_path(
    root: str | Path,
    *,
    dataset: str,
    scope_key: str,
    delivery_date: date | datetime | str,
    run_id: str,
    partition: str = "raw",
) -> AzureExportPathSpec:
    """Build the canonical directory layout for a delivery."""

    return AzureExportPathSpec(
        root=_coerce_path(root),
        dataset=dataset,
        scope_key=scope_key,
        delivery_date=_coerce_date(delivery_date),
        run_id=run_id,
        partition=partition,
    )


def validate_delivery_path(path: str | Path, *, root: str | Path | None = None) -> AzureExportPathSpec:
    """Validate a landing-zone path and return its parsed contract details."""

    candidate = _coerce_path(path)
    root_path = _coerce_path(root) if root is not None else None

    if root_path is not None:
        try:
            relative = candidate.relative_to(root_path)
        except ValueError as exc:
            raise ValueError(f"Path {candidate} is not under the provided root {root_path}") from exc
        base_root = root_path
        parts = relative.parts
    else:
        if len(candidate.parts) < 5:
            raise ValueError(
                "Expected <dataset>/<scope_key>/delivery_date=YYYY-MM-DD/run=RUN_ID/<partition>"
            )
        parts = candidate.parts[-5:]
        prefix_parts = candidate.parts[:-5]
        base_root = Path(*prefix_parts) if prefix_parts else Path(".")

    if len(parts) != 5:
        raise ValueError(
            "Expected <dataset>/<scope_key>/delivery_date=YYYY-MM-DD/run=RUN_ID/<partition>"
        )

    dataset, scope_key, delivery_date_segment, run_segment, partition = parts
    normalized_dataset = normalize_dataset_name(dataset)
    normalized_scope_key = _normalize_segment(scope_key)

    if "__" not in normalized_scope_key:
        raise ValueError(f"Invalid scope key segment: {scope_key!r}")

    date_prefix, date_value = delivery_date_segment.split("=", 1) if "=" in delivery_date_segment else ("", "")
    run_prefix, run_value = run_segment.split("=", 1) if "=" in run_segment else ("", "")
    if date_prefix != "delivery_date" or run_prefix != "run":
        raise ValueError("Delivery paths must include delivery_date=... and run=... segments")

    parsed_date = _coerce_date(date_value)
    normalized_partition = normalize_partition_name(partition)

    spec = AzureExportPathSpec(
        root=base_root,
        dataset=normalized_dataset,
        scope_key=normalized_scope_key,
        delivery_date=parsed_date,
        run_id=run_value,
        partition=normalized_partition,
    )
    if root_path is not None and spec.path != candidate:
        raise ValueError(f"Path {candidate} does not match the canonical contract")
    return spec
