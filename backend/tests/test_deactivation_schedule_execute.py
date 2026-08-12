"""Tests that the deactivation scheduler's AD steps mirror the offboarding tool's ad_* lanes."""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock

import pytest

from deactivation_schedule import DeactivationScheduleStore


def _make_store(tmp_path) -> DeactivationScheduleStore:
    return DeactivationScheduleStore(db_path=str(tmp_path / "deactivation_schedule.db"))


def _install_fake_user_admin_jobs(monkeypatch) -> MagicMock:
    fake_jobs = MagicMock()
    fake_jobs.create_job.return_value = {"job_id": "entra-job-1"}
    fake_module = types.ModuleType("user_admin_jobs")
    fake_module.user_admin_jobs = fake_jobs
    monkeypatch.setitem(sys.modules, "user_admin_jobs", fake_module)
    return fake_jobs


@pytest.mark.asyncio
async def test_execute_runs_all_ad_lanes_when_ad_sam_present(tmp_path, monkeypatch):
    import ad_client as ad

    _install_fake_user_admin_jobs(monkeypatch)

    monkeypatch.setattr(ad, "disable_user", MagicMock(return_value={}))
    monkeypatch.setattr(ad, "reset_password_random", MagicMock(return_value="generated-pw"))
    monkeypatch.setattr(
        ad,
        "remove_from_all_groups_except_domain_users",
        MagicMock(return_value={"removed": ["ITStaff"], "skipped": ["Domain Users"], "failures": []}),
    )
    monkeypatch.setattr(ad, "update_termination_attributes", MagicMock(return_value={}))
    monkeypatch.setattr(
        ad,
        "move_to_disabled_users_ou",
        MagicMock(return_value="CN=Jane Doe,OU=Disabled Users,DC=oasislegal,DC=com"),
    )

    store = _make_store(tmp_path)
    import datetime as dt
    job = store.create(
        ticket_key="OIT-1",
        display_name="Jane Doe",
        entra_user_id="entra-123",
        ad_sam="jdoe",
        run_at=dt.datetime.now(dt.timezone.utc),
        timezone_label="UTC",
        created_by="tester@example.com",
    )

    await store._execute(job)

    ad.disable_user.assert_called_once_with("jdoe")
    ad.reset_password_random.assert_called_once_with("jdoe")
    ad.remove_from_all_groups_except_domain_users.assert_called_once_with("jdoe")
    ad.update_termination_attributes.assert_called_once_with("jdoe")
    ad.move_to_disabled_users_ou.assert_called_once_with("jdoe")

    finished = store.get(job["job_id"])
    result = json.loads(finished["result_json"])
    assert finished["status"] == "completed"
    assert result["ad_disable"] == "Disabled AD account: jdoe"
    assert result["ad_reset_pw"] == "AD password reset for: jdoe"
    assert result["ad_group_cleanup"] == "Removed 1 group(s)"
    assert result["ad_attribute_cleanup"] == "Termination attributes applied"
    assert "Disabled Users" in result["ad_move_ou"]


@pytest.mark.asyncio
async def test_execute_marks_job_failed_when_ad_group_cleanup_errors(tmp_path, monkeypatch):
    import ad_client as ad

    _install_fake_user_admin_jobs(monkeypatch)

    monkeypatch.setattr(ad, "disable_user", MagicMock(return_value={}))
    monkeypatch.setattr(ad, "reset_password_random", MagicMock(return_value="generated-pw"))
    monkeypatch.setattr(
        ad,
        "remove_from_all_groups_except_domain_users",
        MagicMock(side_effect=ad.ADError("insufficient access rights")),
    )
    monkeypatch.setattr(ad, "update_termination_attributes", MagicMock(return_value={}))
    monkeypatch.setattr(ad, "move_to_disabled_users_ou", MagicMock(return_value="CN=Jane Doe,OU=Disabled Users"))

    store = _make_store(tmp_path)
    import datetime as dt
    job = store.create(
        ticket_key="OIT-2",
        display_name="Jane Doe",
        entra_user_id="entra-123",
        ad_sam="jdoe",
        run_at=dt.datetime.now(dt.timezone.utc),
        timezone_label="UTC",
        created_by="tester@example.com",
    )

    await store._execute(job)

    finished = store.get(job["job_id"])
    result = json.loads(finished["result_json"])
    assert finished["status"] == "failed"
    assert result["ad_group_cleanup"].startswith("Error:")
    # Later lanes still run even after an earlier lane errors
    ad.update_termination_attributes.assert_called_once_with("jdoe")
    ad.move_to_disabled_users_ou.assert_called_once_with("jdoe")


@pytest.mark.asyncio
async def test_execute_skips_ad_lanes_when_no_ad_sam(tmp_path, monkeypatch):
    import ad_client as ad

    _install_fake_user_admin_jobs(monkeypatch)

    monkeypatch.setattr(ad, "disable_user", MagicMock())
    monkeypatch.setattr(ad, "reset_password_random", MagicMock())
    monkeypatch.setattr(ad, "remove_from_all_groups_except_domain_users", MagicMock())
    monkeypatch.setattr(ad, "update_termination_attributes", MagicMock())
    monkeypatch.setattr(ad, "move_to_disabled_users_ou", MagicMock())

    store = _make_store(tmp_path)
    import datetime as dt
    job = store.create(
        ticket_key="OIT-3",
        display_name="No AD User",
        entra_user_id="entra-999",
        ad_sam="",
        run_at=dt.datetime.now(dt.timezone.utc),
        timezone_label="UTC",
        created_by="tester@example.com",
    )

    await store._execute(job)

    ad.disable_user.assert_not_called()
    ad.reset_password_random.assert_not_called()
    ad.remove_from_all_groups_except_domain_users.assert_not_called()
    ad.update_termination_attributes.assert_not_called()
    ad.move_to_disabled_users_ou.assert_not_called()

    finished = store.get(job["job_id"])
    result = json.loads(finished["result_json"])
    assert result["ad_group_cleanup"] == "No AD account linked"
    assert result["ad_attribute_cleanup"] == "No AD account linked"
    assert result["ad_move_ou"] == "No AD account linked"
