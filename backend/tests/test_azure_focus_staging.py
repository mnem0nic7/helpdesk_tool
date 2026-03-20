from __future__ import annotations

from pathlib import Path

import pytest

from azure_focus_staging import FocusParseError, build_focus_staged_model, parse_focus_csv, stage_focus_delivery


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "azure_focus"


def test_stage_focus_delivery_builds_summary_trend_and_breakdowns():
    content = (FIXTURE_DIR / "focus_daily_sample.csv").read_text(encoding="utf-8")

    model = stage_focus_delivery(
        content,
        source_path=str(FIXTURE_DIR / "focus_daily_sample.csv"),
        delivery_time="2026-03-20T08:00:00+00:00",
        delivery_key="delivery-001",
    )

    assert model["delivery_key"] == "delivery-001"
    assert model["summary"]["row_count"] == 4
    assert model["summary"]["currency"] == "USD"
    assert model["summary"]["actual_cost_total"] == pytest.approx(25.5)
    assert model["summary"]["amortized_cost_total"] == pytest.approx(22.5)
    assert model["summary"]["usage_date_start"] == "2026-03-18"
    assert model["summary"]["usage_date_end"] == "2026-03-19"
    assert len(model["trend"]) == 2
    assert model["trend"][0]["usage_date"] == "2026-03-18"
    assert model["trend"][0]["actual_cost"] == pytest.approx(15.0)
    assert model["breakdowns"]["service"][0]["service_name"] == "Compute"
    assert model["breakdowns"]["service"][0]["actual_cost"] == pytest.approx(17.5)
    assert model["breakdowns"]["subscription"][0]["subscription_name"] == "Prod Subscription"
    assert model["breakdowns"]["resource_group"][0]["resource_group_name"] == "rg-app"


def test_parse_focus_csv_rejects_missing_cost_columns():
    content = (FIXTURE_DIR / "focus_malformed_missing_cost.csv").read_text(encoding="utf-8")

    with pytest.raises(FocusParseError) as exc_info:
        parse_focus_csv(content, source_path=str(FIXTURE_DIR / "focus_malformed_missing_cost.csv"))

    message = str(exc_info.value)
    assert "missing required columns" in message
    assert "CostInBillingCurrency" in message


def test_parse_focus_csv_accepts_fallback_headers():
    content = (FIXTURE_DIR / "focus_fallback_headers.csv").read_text(encoding="utf-8")

    rows = parse_focus_csv(content, source_path=str(FIXTURE_DIR / "focus_fallback_headers.csv"))

    assert len(rows) == 2
    assert rows[0]["service_name"] == "Microsoft.Compute"
    assert rows[0]["subscription_name"] == "sub-prod"
    assert rows[0]["actual_cost"] == pytest.approx(10.0)
    assert rows[1]["service_name"] == "Microsoft.Storage"
    assert rows[1]["actual_cost"] == pytest.approx(5.0)


def test_build_focus_staged_model_handles_empty_inputs():
    model = build_focus_staged_model([], source_path="empty.csv", delivery_time="2026-03-20T00:00:00+00:00")

    assert model["rows"] == []
    assert model["summary"]["row_count"] == 0
    assert model["trend"] == []
    assert model["breakdowns"] == {"service": [], "subscription": [], "resource_group": []}
