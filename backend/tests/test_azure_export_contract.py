from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from azure_export_contract import (
    AzureExportPathSpec,
    build_delivery_path,
    build_scope_key,
    normalize_dataset_name,
    normalize_partition_name,
    validate_delivery_path,
)


def test_build_and_validate_delivery_path_round_trips(tmp_path):
    root = tmp_path / "landing-zone"
    scope_key = build_scope_key("subscription", "SUB-123")

    spec = build_delivery_path(
        root,
        dataset="FOCUS",
        scope_key=scope_key,
        delivery_date=date(2026, 3, 20),
        run_id="RUN-001",
    )

    assert isinstance(spec, AzureExportPathSpec)
    assert spec.dataset == "focus"
    assert spec.scope_key == "subscription__sub-123"
    assert spec.path == root / "focus" / "subscription__sub-123" / "delivery_date=2026-03-20" / "run=run-001" / "raw"
    assert spec.partition_path("staged") == root / "focus" / "subscription__sub-123" / "delivery_date=2026-03-20" / "run=run-001" / "staged"

    parsed = validate_delivery_path(spec.path, root=root)

    assert parsed == spec
    assert parsed.as_dict()["path"] == str(spec.path)


def test_contract_rejects_invalid_paths_and_partitions(tmp_path):
    root = tmp_path / "landing-zone"

    with pytest.raises(ValueError, match="Unsupported landing-zone partition"):
        normalize_partition_name("archive")

    with pytest.raises(ValueError, match="Invalid path segment"):
        normalize_dataset_name(" ")

    candidate = Path("/elsewhere/focus/subscription__sub-123/delivery_date=2026-03-20/run=run-001/raw")
    with pytest.raises(ValueError, match="not under the provided root"):
        validate_delivery_path(candidate, root=root)

