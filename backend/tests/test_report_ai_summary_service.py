from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import report_ai_summary_service as summary_module
from models import ReportConfig, ReportTemplate
from report_ai_summary_service import ReportAISummaryService, _SummaryGenerationResult


def _make_template(
    *,
    template_id: str,
    name: str,
    include_in_master_export: bool,
    updated_at: str = "2026-03-26T00:00:00+00:00",
) -> ReportTemplate:
    return ReportTemplate(
        id=template_id,
        site_scope="primary",
        name=name,
        description="Saved template",
        category="Executive",
        notes="",
        readiness="ready",
        is_seed=False,
        include_in_master_export=include_in_master_export,
        created_at="2026-03-26T00:00:00+00:00",
        updated_at=updated_at,
        created_by_email="",
        created_by_name="",
        updated_by_email="",
        updated_by_name="",
        config=ReportConfig(),
    )


@pytest.mark.asyncio
async def test_start_manual_batch_only_queues_master_export_templates(monkeypatch, tmp_path: Path) -> None:
    service = ReportAISummaryService(db_path=str(tmp_path / "report-ai.db"))
    included = _make_template(template_id="tpl-1", name="Included", include_in_master_export=True)
    excluded = _make_template(template_id="tpl-2", name="Excluded", include_in_master_export=False)
    monkeypatch.setattr(summary_module.report_template_store, "list_templates", lambda scope: [included, excluded])
    monkeypatch.setattr(service, "_current_data_version", lambda: "data-1")

    def _fake_generate(site_scope: str, template: ReportTemplate, source: str, data_version: str) -> _SummaryGenerationResult:
        return _SummaryGenerationResult(
            status="ready",
            source=source,
            summary=f"{template.name} summary",
            bullets=[f"{template.name} bullet"],
            fallback_used=False,
            model_used="nemotron-3-nano:4b",
            generated_at="2026-03-26T00:00:00+00:00",
            template_version=template.updated_at,
            data_version=data_version,
        )

    monkeypatch.setattr(service, "_generate_summary_result", _fake_generate)

    batch = await service.start_manual_batch("primary")
    await asyncio.gather(*list(service._batch_tasks))

    assert batch.item_count == 1
    status = service.get_batch_status(batch.batch_id, "primary")
    assert status.status == "completed"
    assert [item.template_id for item in status.items] == ["tpl-1"]
    summaries = service.list_current_summaries("primary")
    assert [summary.template_id for summary in summaries] == ["tpl-1"]


@pytest.mark.asyncio
async def test_nightly_run_processes_only_non_master_templates(monkeypatch, tmp_path: Path) -> None:
    service = ReportAISummaryService(db_path=str(tmp_path / "report-ai-nightly.db"))
    included = _make_template(template_id="tpl-included", name="Included", include_in_master_export=True)
    nightly = _make_template(template_id="tpl-nightly", name="Nightly", include_in_master_export=False)
    monkeypatch.setattr(summary_module.report_template_store, "list_templates", lambda scope: [included, nightly])
    monkeypatch.setattr(service, "_current_data_version", lambda: "data-1")

    processed: list[tuple[str, str]] = []

    async def _fake_enqueue(
        *,
        batch_id,
        site_scope: str,
        template: ReportTemplate,
        source: str,
        lane: str,
        data_version: str,
    ):
        processed.append((template.id, source))
        return None

    monkeypatch.setattr(service, "_enqueue_template_summary", _fake_enqueue)

    await service._run_nightly_once()

    assert processed == [("tpl-nightly", "nightly")]


def test_list_current_summaries_ignores_stale_summary_versions(monkeypatch, tmp_path: Path) -> None:
    service = ReportAISummaryService(db_path=str(tmp_path / "report-ai-stale.db"))
    template = _make_template(template_id="tpl-stale", name="Template", include_in_master_export=True)
    monkeypatch.setattr(summary_module.report_template_store, "list_templates", lambda scope: [template])
    monkeypatch.setattr(service, "_current_data_version", lambda: "data-1")

    stale = _SummaryGenerationResult(
        status="ready",
        source="manual",
        summary="Old summary",
        bullets=["Old bullet"],
        fallback_used=False,
        model_used="nemotron-3-nano:4b",
        generated_at="2026-03-26T00:00:00+00:00",
        template_version="2026-03-25T00:00:00+00:00",
        data_version="data-1",
    )
    service._upsert_summary(site_scope="primary", template=template, result=stale)

    assert service.list_current_summaries("primary") == []


def test_list_current_summaries_reuses_latest_summary_after_restart_when_refresh_token_is_not_loaded(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = ReportAISummaryService(db_path=str(tmp_path / "report-ai-restart.db"))
    template = _make_template(template_id="tpl-restart", name="Template", include_in_master_export=True)
    prompt_version = summary_module._REPORT_AI_SUMMARY_PROMPT_VERSION
    monkeypatch.setattr(summary_module.report_template_store, "list_templates", lambda scope: [template])

    latest = _SummaryGenerationResult(
        status="ready",
        source="manual",
        summary="Persisted summary",
        bullets=["Persisted bullet"],
        fallback_used=False,
        model_used="nemotron-3-nano:4b",
        generated_at="2026-03-26T00:00:00+00:00",
        template_version=template.updated_at,
        data_version=f"2026-03-26T08:00:00+00:00|{prompt_version}",
    )
    service._upsert_summary(site_scope="primary", template=template, result=latest)
    monkeypatch.setattr(service, "_current_data_version", lambda: f"|{prompt_version}")

    summaries = service.list_current_summaries("primary")

    assert [summary.template_id for summary in summaries] == ["tpl-restart"]
    assert summaries[0].summary == "Persisted summary"


def test_current_data_version_includes_prompt_contract(monkeypatch, tmp_path: Path) -> None:
    service = ReportAISummaryService(db_path=str(tmp_path / "report-ai-version.db"))
    monkeypatch.setattr(summary_module.cache, "status", lambda: {"last_refresh": "2026-03-26T08:00:00+00:00"})

    assert service._current_data_version() == "2026-03-26T08:00:00+00:00|v2_7day_master_exec_focus"


def test_build_summary_prompt_for_manual_master_batch_uses_7_day_exec_guidance(tmp_path: Path) -> None:
    service = ReportAISummaryService(db_path=str(tmp_path / "report-ai-prompt.db"))
    template = _make_template(template_id="tpl-master", name="SLA Compliance Rate", include_in_master_export=True)
    context = {
        "kpis": [
            {
                "label": "SLA Compliance Rate %",
                "type": "percent",
                "value_7d": 0.73,
                "value_30d": 0.767,
                "prior_7d": 0.81,
                "delta": -0.08,
            },
            {
                "label": "MTTR P95 (h)",
                "type": "hours",
                "value_7d": 292.4,
                "value_30d": 2623.1,
                "prior_7d": 180.0,
                "delta": 112.4,
            },
        ],
        "prior_7_window_start": date(2026, 3, 13),
        "prior_7_window_end": date(2026, 3, 19),
        "sla_rows_7": [
            {"group": "Met", "count": 40, "avg_ttr_hours": 12.0},
            {"group": "BREACHED", "count": 8, "avg_ttr_hours": 96.0},
        ],
        "first_response_rows_7": [
            {"group": "Met", "count": 43, "avg_ttr_hours": 4.0},
            {"group": "BREACHED", "count": 5, "avg_ttr_hours": 16.0},
        ],
        "followup_rows_7": [
            {"group": "Met", "count": 31},
            {"group": "BREACHED", "count": 17},
        ],
        "mttr_priority_rows_7": [
            {"group": "High", "avg_ttr_hours": 50.7, "p95_ttr_hours": 303.8},
            {"group": "Highest", "avg_ttr_hours": 254.9, "p95_ttr_hours": 838.0},
        ],
        "top_category_rows_7": [
            {"group": "Security Alert", "count": 32, "avg_ttr_hours": 18.0, "p95_ttr_hours": 48.0},
            {"group": "Emailed Request", "count": 14, "avg_ttr_hours": 11.0, "p95_ttr_hours": 24.0},
        ],
        "problem_areas": ["Worst MTTR tail: Highest has P95 838.0h."],
        "gaps": [],
    }

    system, user = service._build_summary_prompt(
        template=template,
        context=context,
        window_label="30 Day",
        window_start=date(2026, 2, 26),
        window_end=date(2026, 3, 26),
        source="manual",
    )

    assert "Lead with current 7-day performance" in system
    assert "Do not use bullets, numbered lists, labels, or headings" in system
    assert "2-Hour Response + Daily Follow-Up" in user
    assert "Top weekly request categories" in user
    assert "delta_vs_prior_7d" in user
    assert "Prompt mode: master" in user
    assert '{"summary":"..."}' in user


def test_build_fallback_result_returns_conversational_summary_without_bullets(tmp_path: Path) -> None:
    service = ReportAISummaryService(db_path=str(tmp_path / "report-ai-fallback.db"))
    template = _make_template(template_id="tpl-fallback", name="SLA Compliance Rate", include_in_master_export=True)

    class _FakeBuilder:
        def _detect_escalation_anomaly(self, trend_rows):
            return None

        def _build_key_findings(self, context, *, anomaly):
            return [
                "🔴 SLA Compliance: 73.0% met in the last 7 days (30d context: 76.7%). 8 tickets breached.",
                "🔴 MTTR Tail Risk: overall 7d P95 is 292.4h. Highest is the slowest priority band.",
            ]

    result = service._build_fallback_result(
        template=template,
        builder=_FakeBuilder(),
        context={"trend_rows": []},
        source="manual",
        data_version="data-1",
        error="model unavailable",
    )

    assert result.status == "fallback"
    assert result.bullets == []
    assert "Over the last 7 days, SLA compliance was 73.0% met" in result.summary
    assert "MTTR remained a watch area" in result.summary


def test_generate_summary_result_accepts_summary_without_bullets(monkeypatch, tmp_path: Path) -> None:
    service = ReportAISummaryService(db_path=str(tmp_path / "report-ai-generate.db"))
    template = _make_template(template_id="tpl-generate", name="Executive", include_in_master_export=True)
    context = {
        "kpis": [
            {"value_7d": 0.73, "value_30d": 0.767, "prior_7d": 0.81, "delta": -0.08, "label": "SLA", "type": "percent"},
            {"value_7d": 292.4, "value_30d": 2623.1, "prior_7d": 180.0, "delta": 112.4, "label": "MTTR", "type": "hours"},
            {"value_7d": 0.90, "value_30d": 0.92, "prior_7d": 0.91, "delta": -0.01, "label": "First Response", "type": "percent"},
            {"value_7d": 12, "value_30d": 15, "prior_7d": 10, "delta": 2, "label": "Backlog", "type": "integer"},
        ],
        "prior_7_window_start": date(2026, 3, 13),
        "prior_7_window_end": date(2026, 3, 19),
        "sla_rows_7": [{"group": "Met", "count": 7}, {"group": "BREACHED", "count": 1, "avg_ttr_hours": 96.0}],
        "first_response_rows_7": [{"group": "Met", "count": 7}, {"group": "BREACHED", "count": 1}],
        "followup_rows_7": [{"group": "Met", "count": 6}, {"group": "BREACHED", "count": 2}],
        "mttr_priority_rows_7": [{"group": "Highest", "avg_ttr_hours": 254.9, "p95_ttr_hours": 838.0}],
        "top_category_rows_7": [{"group": "Security Alert", "count": 32, "avg_ttr_hours": 18.0, "p95_ttr_hours": 48.0}],
        "problem_areas": ["Highest priority tickets are aging."],
        "gaps": [],
    }

    class _FakeBuilder:
        def __init__(self, *args, **kwargs):
            self.today = date(2026, 3, 26)

        def _facts_for_config(self, config):
            return []

        def _build_dashboard_context(self, **kwargs):
            return context

    monkeypatch.setattr(service, "_issues_for_site_scope", lambda scope: [])
    monkeypatch.setattr(service, "_resolve_model_id", lambda: "nemotron-3-nano:4b")
    monkeypatch.setattr(summary_module, "ReportWorkbookBuilder", _FakeBuilder)
    monkeypatch.setattr(
        summary_module,
        "resolve_report_window_spec",
        lambda config, today: SimpleNamespace(label="30 Day", start=date(2026, 2, 26), end=date(2026, 3, 26)),
    )
    monkeypatch.setattr(
        summary_module,
        "invoke_model_text",
        lambda *args, **kwargs: '{"summary":"Over the last 7 days, SLA performance improved and the backlog stayed manageable."}',
    )

    result = service._generate_summary_result("primary", template, "manual", "data-1")

    assert result.status == "ready"
    assert result.summary == "Over the last 7 days, SLA performance improved and the backlog stayed manageable."
    assert result.bullets == []
