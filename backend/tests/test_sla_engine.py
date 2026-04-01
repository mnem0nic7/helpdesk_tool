from __future__ import annotations

from datetime import datetime, timezone

from sla_engine import _parse_dt


def test_parse_dt_handles_dict_values_and_epoch_timestamps():
    assert _parse_dt({"created": "2024-01-01T00:00:00Z"}) == datetime(
        2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc
    )
    assert _parse_dt({"value": "2024-01-01T01:00:00+00:00"}) == datetime(
        2024, 1, 1, 1, 0, 0, tzinfo=timezone.utc
    )
    assert _parse_dt({"timestamp": 1704067200000}) == datetime(
        2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc
    )
