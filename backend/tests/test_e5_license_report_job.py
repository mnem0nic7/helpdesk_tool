"""E5 license report weekly job."""
from datetime import datetime, timezone

import pytest

import e5_license_report as r

SUNDAY_1305 = datetime(2026, 10, 18, 13, 5, tzinfo=timezone.utc)  # a Sunday
assert SUNDAY_1305.weekday() == 6


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "E5_REPORT_ENABLED", True)
    monkeypatch.setattr(r, "E5_REPORT_RECIPIENTS", ["a@x.com", "b@x.com"])
    monkeypatch.setattr(r, "E5_REPORT_WEEKDAY", 6)
    monkeypatch.setattr(r, "E5_REPORT_HOUR", 13)
    return r.E5LicenseReportJob(db_path=str(tmp_path / "e5.db"))


def _patch_fetch(monkeypatch):
    async def fake_fetch():
        users = [{"displayName": "A", "userPrincipalName": "a@x.com", "accountEnabled": False,
                  "createdDateTime": "2024-01-01T00:00:00Z", "signInActivity": None}] * 500
        return users, r.E5Seats(975, 600)

    monkeypatch.setattr(r, "fetch_e5_data", fake_fetch)


def test_is_due_only_sunday_after_hour(job):
    assert job.is_due(SUNDAY_1305) is True
    assert job.is_due(datetime(2026, 10, 18, 12, 59, tzinfo=timezone.utc)) is False
    assert job.is_due(datetime(2026, 10, 19, 13, 5, tzinfo=timezone.utc)) is False


async def test_sends_once_with_attachment_and_marks_run(job, monkeypatch):
    _patch_fetch(monkeypatch)
    sent = []

    async def fake_send(to, subject, html_body, **kw):
        sent.append((to, subject, kw))
        return True

    monkeypatch.setattr(r, "send_email", fake_send)
    assert await job.run_weekly_job(SUNDAY_1305) is True
    assert await job.run_weekly_job(SUNDAY_1305) is False  # duplicate guard
    assert len(sent) == 1
    to, subject, kw = sent[0]
    assert to == ["a@x.com", "b@x.com"]
    assert kw["attachments"][0]["name"] == "e5_license_reclaim_candidates_2026-10-18.xlsx"
    assert job.already_ran("2026-10-18")


async def test_send_failure_does_not_mark_run(job, monkeypatch):
    _patch_fetch(monkeypatch)

    async def failing_send(*a, **kw):
        return False

    monkeypatch.setattr(r, "send_email", failing_send)
    assert await job.run_weekly_job(SUNDAY_1305) is False
    assert not job.already_ran("2026-10-18")


async def test_fetch_error_skips_send(job, monkeypatch):
    async def bad_fetch():
        raise r.E5FetchError("truncated")

    monkeypatch.setattr(r, "fetch_e5_data", bad_fetch)
    called = []

    async def fake_send(*a, **kw):
        called.append(1)
        return True

    monkeypatch.setattr(r, "send_email", fake_send)
    assert await job.run_weekly_job(SUNDAY_1305) is False
    assert called == []
    assert not job.already_ran("2026-10-18")


async def test_disabled_does_nothing(job, monkeypatch):
    monkeypatch.setattr(r, "E5_REPORT_ENABLED", False)
    _patch_fetch(monkeypatch)
    assert await job.run_weekly_job(SUNDAY_1305) is False
    assert not job.already_ran("2026-10-18")


def test_config_defaults(monkeypatch):
    import importlib

    import config

    for k in ("E5_REPORT_ENABLED", "E5_REPORT_RECIPIENTS", "E5_REPORT_WEEKDAY", "E5_REPORT_HOUR"):
        monkeypatch.delenv(k, raising=False)
    cfg = importlib.reload(config)
    assert cfg.E5_REPORT_ENABLED is False
    assert cfg.E5_REPORT_WEEKDAY == 6
    assert cfg.E5_REPORT_HOUR == 13
    assert cfg.E5_REPORT_RECIPIENTS == []
