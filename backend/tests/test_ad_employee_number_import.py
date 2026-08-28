"""Tests for the AD employee-number bulk import: CSV parsing and row-classification logic."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

import pytest


def _fresh_store():
    from ad_employee_number_import import AdEmployeeNumberImportStore
    tmp = tempfile.mktemp(suffix=".db")
    return AdEmployeeNumberImportStore(db_path=tmp)


# ---------------------------------------------------------------------------
# parse_csv_rows
# ---------------------------------------------------------------------------

def test_parse_csv_rows_returns_list_of_dicts():
    from ad_employee_number_import import parse_csv_rows

    csv_bytes = (
        b"emails_work_value,ENT_employeeNumber,name_formatted\n"
        b"jane@example.com,ABC123,Jane Doe\n"
    )

    rows = parse_csv_rows(csv_bytes)

    assert rows == [
        {"emails_work_value": "jane@example.com", "ENT_employeeNumber": "ABC123", "name_formatted": "Jane Doe"}
    ]


def test_parse_csv_rows_raises_when_email_column_missing():
    from ad_employee_number_import import parse_csv_rows

    csv_bytes = b"ENT_employeeNumber\nABC123\n"

    with pytest.raises(ValueError, match="emails_work_value"):
        parse_csv_rows(csv_bytes)


def test_parse_csv_rows_raises_when_employee_number_column_missing():
    from ad_employee_number_import import parse_csv_rows

    csv_bytes = b"emails_work_value\njane@example.com\n"

    with pytest.raises(ValueError, match="ENT_employeeNumber"):
        parse_csv_rows(csv_bytes)


# ---------------------------------------------------------------------------
# build_row_plan
# ---------------------------------------------------------------------------

def _row(email: str, employee_number: str) -> dict:
    return {"emails_work_value": email, "ENT_employeeNumber": employee_number}


def _ad_user(sam: str, display_name: str, employee_number: str) -> dict:
    return {"sam_account_name": sam, "display_name": display_name, "employee_number": employee_number}


def test_build_row_plan_tags_update_when_value_differs():
    from ad_employee_number_import import build_row_plan

    rows = [_row("jane@example.com", "NEW123")]
    ad_lookup = lambda email: _ad_user("jdoe", "Jane Doe", "OLD999")

    plan = build_row_plan(rows, ad_lookup=ad_lookup)

    assert len(plan) == 1
    assert plan[0] == {
        "row_index": 0,
        "source_email": "jane@example.com",
        "ad_sam": "jdoe",
        "ad_display_name": "Jane Doe",
        "current_employee_number": "OLD999",
        "new_employee_number": "NEW123",
        "action": "update",
    }


def test_build_row_plan_tags_no_change_when_value_matches():
    from ad_employee_number_import import build_row_plan

    rows = [_row("jane@example.com", "SAME123")]
    ad_lookup = lambda email: _ad_user("jdoe", "Jane Doe", "SAME123")

    plan = build_row_plan(rows, ad_lookup=ad_lookup)

    assert plan[0]["action"] == "no_change"


def test_build_row_plan_tags_not_found_when_no_ad_match():
    from ad_employee_number_import import build_row_plan

    rows = [_row("ghost@example.com", "NEW123")]
    ad_lookup = lambda email: None

    plan = build_row_plan(rows, ad_lookup=ad_lookup)

    assert plan[0]["action"] == "not_found"
    assert plan[0]["ad_sam"] == ""
    assert plan[0]["current_employee_number"] == ""


def test_build_row_plan_tags_not_found_when_email_blank():
    from ad_employee_number_import import build_row_plan

    rows = [_row("", "NEW123")]
    calls: list[str] = []

    def ad_lookup(email: str):
        calls.append(email)
        return _ad_user("jdoe", "Jane Doe", "OLD999")

    plan = build_row_plan(rows, ad_lookup=ad_lookup)

    assert plan[0]["action"] == "not_found"
    assert calls == []  # never looks up an empty email


def test_build_row_plan_tags_skipped_blank_when_employee_number_blank():
    from ad_employee_number_import import build_row_plan

    rows = [_row("jane@example.com", "")]
    calls: list[str] = []

    def ad_lookup(email: str):
        calls.append(email)
        return _ad_user("jdoe", "Jane Doe", "OLD999")

    plan = build_row_plan(rows, ad_lookup=ad_lookup)

    assert plan[0]["action"] == "skipped_blank"
    assert calls == []  # blank source value never triggers a lookup


def test_build_row_plan_dedupes_keeping_last_occurrence():
    from ad_employee_number_import import build_row_plan

    rows = [
        _row("jane@example.com", "FIRST111"),
        _row("jane@example.com", "SECOND222"),
    ]
    ad_lookup = lambda email: _ad_user("jdoe", "Jane Doe", "OLD999")

    plan = build_row_plan(rows, ad_lookup=ad_lookup)

    assert len(plan) == 2
    assert plan[0]["row_index"] == 0
    assert plan[0]["action"] == "skipped_duplicate"
    assert plan[1]["row_index"] == 1
    assert plan[1]["action"] == "update"
    assert plan[1]["new_employee_number"] == "SECOND222"


def test_build_row_plan_preserves_row_order_for_unrelated_rows():
    from ad_employee_number_import import build_row_plan

    rows = [
        _row("a@example.com", "A1"),
        _row("b@example.com", "B1"),
    ]
    users = {"a@example.com": _ad_user("a", "A", "OLD"), "b@example.com": _ad_user("b", "B", "OLD")}
    ad_lookup = lambda email: users.get(email)

    plan = build_row_plan(rows, ad_lookup=ad_lookup)

    assert [r["row_index"] for r in plan] == [0, 1]
    assert [r["source_email"] for r in plan] == ["a@example.com", "b@example.com"]


# ---------------------------------------------------------------------------
# AdEmployeeNumberImportStore: job CRUD
# ---------------------------------------------------------------------------

def test_create_and_get_job_round_trips():
    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="admin@example.com", filename="hr.csv", total_rows=3)

    job = store.get_job("j1")

    assert job is not None
    assert job["job_id"] == "j1"
    assert job["requested_by"] == "admin@example.com"
    assert job["filename"] == "hr.csv"
    assert job["total_rows"] == 3
    assert job["status"] == "queued"
    assert job["update_count"] == 0


def test_get_job_returns_none_for_missing():
    store = _fresh_store()
    assert store.get_job("nonexistent") is None


def test_update_job_status_sets_status_and_error():
    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="", filename="hr.csv", total_rows=0)

    store.update_job_status("j1", status="failed", error="AD unreachable")
    job = store.get_job("j1")

    assert job["status"] == "failed"
    assert job["error"] == "AD unreachable"


def test_set_job_counts_updates_summary_fields():
    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="", filename="hr.csv", total_rows=10)

    store.set_job_counts(
        "j1",
        update_count=2,
        no_change_count=5,
        not_found_count=1,
        skipped_count=2,
    )
    job = store.get_job("j1")

    assert job["update_count"] == 2
    assert job["no_change_count"] == 5
    assert job["not_found_count"] == 1
    assert job["skipped_count"] == 2


def test_list_jobs_returns_ordered_descending():
    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="a@example.com", filename="a.csv", total_rows=1)
    store.create_job(job_id="j2", requested_by="b@example.com", filename="b.csv", total_rows=1)

    jobs = store.list_jobs(limit=10)

    assert len(jobs) == 2
    assert {j["job_id"] for j in jobs} == {"j1", "j2"}


# ---------------------------------------------------------------------------
# AdEmployeeNumberImportStore: rows
# ---------------------------------------------------------------------------

def _plan_row(row_index: int, action: str, email: str = "jane@example.com") -> dict:
    return {
        "row_index": row_index,
        "source_email": email,
        "ad_sam": "jdoe",
        "ad_display_name": "Jane Doe",
        "current_employee_number": "OLD",
        "new_employee_number": "NEW",
        "action": action,
    }


def test_insert_rows_and_list_rows_round_trip():
    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="", filename="hr.csv", total_rows=2)

    row_ids = store.insert_rows("j1", [_plan_row(0, "update"), _plan_row(1, "no_change")])
    rows = store.list_rows("j1")

    assert len(row_ids) == 2
    assert [r["row_index"] for r in rows] == [0, 1]
    assert rows[0]["id"] == row_ids[0]
    assert rows[0]["action"] == "update"
    assert rows[1]["action"] == "no_change"


def test_list_rows_filters_by_action():
    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="", filename="hr.csv", total_rows=3)
    store.insert_rows("j1", [_plan_row(0, "update"), _plan_row(1, "no_change"), _plan_row(2, "update")])

    rows = store.list_rows("j1", action="update")

    assert len(rows) == 2
    assert all(r["action"] == "update" for r in rows)


def test_list_rows_paginates_with_limit_and_offset():
    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="", filename="hr.csv", total_rows=3)
    store.insert_rows("j1", [_plan_row(0, "update"), _plan_row(1, "update"), _plan_row(2, "update")])

    page = store.list_rows("j1", limit=1, offset=1)

    assert len(page) == 1
    assert page[0]["row_index"] == 1


def test_count_rows_respects_action_filter():
    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="", filename="hr.csv", total_rows=3)
    store.insert_rows("j1", [_plan_row(0, "update"), _plan_row(1, "no_change"), _plan_row(2, "update")])

    assert store.count_rows("j1") == 3
    assert store.count_rows("j1", action="update") == 2


def test_get_row_returns_single_row_by_id():
    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="", filename="hr.csv", total_rows=1)
    [row_id] = store.insert_rows("j1", [_plan_row(0, "update")])

    row = store.get_row(row_id)

    assert row["id"] == row_id
    assert row["action"] == "update"
    assert row["applied"] is False


def test_mark_row_applied_sets_applied_and_error():
    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="", filename="hr.csv", total_rows=1)
    [row_id] = store.insert_rows("j1", [_plan_row(0, "update")])

    store.mark_row_applied(row_id, applied=True, apply_error="")
    row = store.get_row(row_id)

    assert row["applied"] is True
    assert row["apply_error"] == ""

    store.mark_row_applied(row_id, applied=False, apply_error="LDAP timeout")
    row = store.get_row(row_id)

    assert row["applied"] is False
    assert row["apply_error"] == "LDAP timeout"


# ---------------------------------------------------------------------------
# AdEmployeeNumberImportStore: CSV export
# ---------------------------------------------------------------------------

def test_render_csv_contains_row_data():
    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="", filename="hr.csv", total_rows=1)
    store.insert_rows("j1", [_plan_row(0, "update", email="jane@example.com")])

    csv_content = store.render_csv("j1")

    assert "source_email" in csv_content
    assert "jane@example.com" in csv_content
    assert "update" in csv_content


def test_render_csv_returns_empty_for_missing_job():
    store = _fresh_store()
    assert store.render_csv("nonexistent") == ""


# ---------------------------------------------------------------------------
# run_matching_phase
# ---------------------------------------------------------------------------

def _csv_bytes(rows: list[tuple[str, str]]) -> bytes:
    lines = ["emails_work_value,ENT_employeeNumber"]
    lines += [f"{email},{number}" for email, number in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_run_matching_phase_persists_rows_and_marks_awaiting_confirmation():
    from ad_employee_number_import import run_matching_phase

    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="admin@example.com", filename="hr.csv", total_rows=1)

    mock_ad = MagicMock()
    mock_ad.find_user_by_upn_or_email.return_value = {
        "sam_account_name": "jdoe", "display_name": "Jane Doe", "employee_number": "OLD",
    }

    with patch.dict("sys.modules", {"ad_client": mock_ad}):
        run_matching_phase("j1", _csv_bytes([("jane@example.com", "NEW")]), store=store)

    job = store.get_job("j1")
    rows = store.list_rows("j1")

    assert job["status"] == "awaiting_confirmation"
    assert job["update_count"] == 1
    assert len(rows) == 1
    assert rows[0]["action"] == "update"
    assert rows[0]["ad_sam"] == "jdoe"


def test_run_matching_phase_marks_failed_on_bad_csv():
    from ad_employee_number_import import run_matching_phase

    store = _fresh_store()
    store.create_job(job_id="j1", requested_by="", filename="bad.csv", total_rows=0)

    bad_csv = b"not_the_right_column\nfoo\n"

    with patch.dict("sys.modules", {"ad_client": MagicMock()}):
        run_matching_phase("j1", bad_csv, store=store)

    job = store.get_job("j1")
    assert job["status"] == "failed"
    assert "emails_work_value" in job["error"]


# ---------------------------------------------------------------------------
# run_apply_phase
# ---------------------------------------------------------------------------

def _job_with_rows(store, *, rows: list[dict]) -> list[str]:
    store.create_job(job_id="j1", requested_by="", filename="hr.csv", total_rows=len(rows))
    return store.insert_rows("j1", rows)


def test_run_apply_phase_applies_update_rows_and_marks_completed():
    from ad_employee_number_import import run_apply_phase

    store = _fresh_store()
    row_ids = _job_with_rows(store, rows=[_plan_row(0, "update")])

    mock_ad = MagicMock()

    with patch.dict("sys.modules", {"ad_client": mock_ad}):
        run_apply_phase("j1", [], store=store)

    mock_ad.update_user.assert_called_once_with("jdoe", {"employeeNumber": "NEW"})
    row = store.get_row(row_ids[0])
    assert row["applied"] is True
    job = store.get_job("j1")
    assert job["status"] == "completed"
    assert job["applied_count"] == 1


def test_run_apply_phase_skips_excluded_rows():
    from ad_employee_number_import import run_apply_phase

    store = _fresh_store()
    row_ids = _job_with_rows(store, rows=[_plan_row(0, "update")])

    mock_ad = MagicMock()

    with patch.dict("sys.modules", {"ad_client": mock_ad}):
        run_apply_phase("j1", row_ids, store=store)

    mock_ad.update_user.assert_not_called()
    row = store.get_row(row_ids[0])
    assert row["applied"] is False


def test_run_apply_phase_only_touches_update_rows():
    from ad_employee_number_import import run_apply_phase

    store = _fresh_store()
    _job_with_rows(store, rows=[_plan_row(0, "no_change"), _plan_row(1, "not_found")])

    mock_ad = MagicMock()

    with patch.dict("sys.modules", {"ad_client": mock_ad}):
        run_apply_phase("j1", [], store=store)

    mock_ad.update_user.assert_not_called()


def test_run_apply_phase_records_failure_and_marks_completed_with_errors():
    from ad_employee_number_import import run_apply_phase

    store = _fresh_store()
    row_ids = _job_with_rows(store, rows=[_plan_row(0, "update")])

    mock_ad = MagicMock()
    mock_ad.update_user.side_effect = Exception("LDAP timeout")

    with patch.dict("sys.modules", {"ad_client": mock_ad}):
        run_apply_phase("j1", [], store=store)

    row = store.get_row(row_ids[0])
    assert row["applied"] is False
    assert row["apply_error"] == "LDAP timeout"
    job = store.get_job("j1")
    assert job["status"] == "completed_with_errors"
    assert job["apply_failed_count"] == 1
