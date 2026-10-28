"""Trimed roster spreadsheet as a gap-filling source for the HR Entra sync."""
import openpyxl
import pytest

import hr_trimed_sheet as sheet
from tests.test_hr_entra_sync import EXT, FakeAzure, FakeJira, _issue, _job, _user  # noqa: F401 (fixtures)
from tests.test_hr_entra_sync import _window  # noqa: F401

HEADER = [
    "Payroll Company Name", "Position ID", "Legal Last Name", "Legal First Name", "Preferred or Chosen Last Name",
    "Preferred or Chosen First Name", "Work Contact: Work Email", "Job Title Description", "Reports To Legal Name",
    "Reports to Email", "Seniority Date", "Business Unit Description", "Job Function Description",
    "Home Department Description", "Location Description", "Leadership Levels (L2)", "Leadership Levels (L3)",
    "FLSA Description", "Primary Address: State / Territory Description", "Position Status",
    "Personal Contact: Personal Email",
]
ROW = ["LIBRA", "92G001059", "Franklin", "Traci", None, None, "tfranklin@trimed-billing.com",
       "Medical Records Coordinator", "James, Brodie", "bjames@trimed-billing.com", 42527, "Trimed", "Operations",
       "Operations", "Hoover, AL", "Barber, Robert N", "James, Brodie T", "Non-exempt", "Alabama", "Active",
       "traci.franklin06@gmail.com"]


@pytest.fixture(autouse=True)
def roster(tmp_path, monkeypatch):
    path = tmp_path / "roster.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Employment Profile - Effective Date", "Effective as of 10/28/2026"])
    ws.append(HEADER)
    ws.append(ROW)
    wb.save(path)
    monkeypatch.setattr(sheet, "HR_TRIMED_SHEET_PATH", str(path))
    sheet._cache.update(path=None, mtime=None)
    return path


def test_find_row_by_work_personal_email_and_position():
    assert sheet.find_row(["tfranklin@trimed-billing.com"])["Legal Last Name"] == "Franklin"
    assert sheet.find_row(["traci.franklin06@gmail.com"]) is not None
    assert sheet.find_row(["nobody@x.com"], "92G001059") is not None
    assert sheet.find_row(["nobody@x.com"], "nope") is None


def test_missing_file_means_no_match(monkeypatch, tmp_path):
    monkeypatch.setattr(sheet, "HR_TRIMED_SHEET_PATH", str(tmp_path / "absent.xlsx"))
    assert sheet.find_row(["tfranklin@trimed-billing.com"]) is None


def test_build_issue_fields_shapes_values():
    payload, _ = sheet.build_issue_fields(sheet.find_row(["tfranklin@trimed-billing.com"]))
    assert payload["customfield_12866"] == "Medical Records Coordinator"
    assert payload["customfield_15038"] == "Brodie James"  # 'Last, First' -> 'First Last'
    assert payload["customfield_15085"] == "Traci Franklin"
    assert payload["customfield_15091"] == "2016-06-06"  # Excel serial 42527
    assert payload["customfield_13458"] == "Trimed"


def test_no_entra_match_syncs_from_sheet_alone(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12883="traci.franklin06@gmail.com")})
    res = _job(tmp_path, jira, FakeAzure()).sync_issue("HRD-1")
    assert res["outcome"] == "synced" and res["matched_via"] == "trimed_sheet"
    assert jira.updates[0][1]["customfield_12866"] == "Medical Records Coordinator"


def test_sheet_fills_only_what_entra_left_empty(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12883="traci.franklin06@gmail.com")})
    azure = FakeAzure({"traci.franklin06@gmail.com": [_user("tf@x.com", title="Entra Title", **{f"{EXT}division": None})]})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1")
    written = jira.updates[0][1]
    assert written["customfield_12866"] == "Entra Title"  # Entra wins
    assert written["customfield_13458"] == "Trimed"  # Entra had none; sheet fills
    assert "customfield_13458" in res["fields_from_sheet"] and "customfield_12866" not in res["fields_from_sheet"]


def test_no_sheet_row_keeps_no_match(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12883="stranger@gmail.com")})
    assert _job(tmp_path, jira, FakeAzure()).sync_issue("HRD-1")["outcome"] == "no_match"
