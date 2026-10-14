"""Entra -> Jira HR ticket sync job."""
from datetime import datetime, timedelta, timezone

import pytest
import requests

import hr_entra_sync as s
from azure_client import AzureApiError

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
EXT = s.fmap.EXT_PREFIX


class FakeJira:
    def __init__(self, issues=None):
        self.issues = issues or {}
        self.updates = []
        self.notes = []
        self.reject = {}  # field id -> message, simulated 400
        self.searched = []
        self.search_results = []

    def get_issue(self, key):
        return self.issues[key]

    def update_issue_fields(self, key, fields):
        bad = {k: v for k, v in self.reject.items() if k in fields}
        if bad:
            resp = requests.Response()
            resp.status_code = 400
            resp._content = ('{"errors": %s}' % str(bad).replace("'", '"')).encode()
            raise requests.HTTPError("400", response=resp)
        self.updates.append((key, dict(fields)))

    def add_internal_comment(self, key, text):
        self.notes.append((key, text))

    def search_all(self, jql, fields=None, progress_callback=None):
        self.searched.append(jql)
        return self.search_results


class FakeAzure:
    def __init__(self, users=None, manager=None, fail=None):
        self.users = users or {}
        self.manager = manager
        self.fail = fail
        self.calls = []

    def graph_request(self, method, path, params=None, headers=None, **_):
        self.calls.append((path, params, headers))
        if self.fail:
            raise self.fail
        if path == "users":
            needle = params["$filter"].split("'")[1]
            return {"value": self.users.get(needle, [])}
        if path.endswith("/manager"):
            if self.manager is None:
                raise AzureApiError("nf", status_code=404)
            return self.manager
        raise AssertionError(path)


def _user(upn="jdoe@x.com", **extra):
    return {"id": "u1", "userPrincipalName": upn, "mail": upn, "title": "Engineer",
            f"{EXT}division": "Ops", **extra}


def _issue(**fields):
    return {"fields": fields}


def _job(tmp_path, jira, azure):
    return s.HrEntraSyncJob(db_path=str(tmp_path / "hr.db"), jira=jira, azure=azure)


@pytest.fixture(autouse=True)
def _window(monkeypatch):
    monkeypatch.setattr(s, "HR_ENTRA_SYNC_RETRY_MINUTES", 15)
    monkeypatch.setattr(s, "HR_ENTRA_SYNC_PROJECTS", ["HRD", "LIBTA"])


def test_sync_issue_matches_by_company_email_and_writes(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="JDoe@x.com")})
    azure = FakeAzure({"jdoe@x.com": [_user()]}, manager={"displayName": "Pat", "mail": "pat@x.com"})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1")
    assert res["outcome"] == "synced" and res["matched_via"] == "upn"
    assert jira.updates[0][1]["customfield_12866"] == "Engineer"
    assert jira.updates[0][1]["customfield_15038"] == "Pat"
    assert azure.calls[0][2] == {"ConsistencyLevel": "eventual"}


def test_falls_back_to_personal_email(tmp_path):
    jira = FakeJira({"LIBTA-1": _issue(customfield_12883="me@gmail.com")})
    azure = FakeAzure({"me@gmail.com": [_user(upn="jdoe@x.com", mail=None)]})
    res = _job(tmp_path, jira, azure).sync_issue("LIBTA-1")
    assert res["outcome"] == "synced" and res["matched_email"] == "me@gmail.com"
    assert res["matched_via"] == "other_mail"


def test_dry_run_does_not_write(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="jdoe@x.com")})
    res = _job(tmp_path, jira, FakeAzure({"jdoe@x.com": [_user()]})).sync_issue("HRD-1", dry_run=True)
    assert res["dry_run"] and res["fields_written"] and jira.updates == []


def test_rejected_fields_are_dropped_and_rest_still_written(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="jdoe@x.com")})
    jira.reject = {"customfield_13458": "Field cannot be set. It is not on the appropriate screen."}
    res = _job(tmp_path, jira, FakeAzure({"jdoe@x.com": [_user()]})).sync_issue("HRD-1")
    assert "customfield_13458" in res["fields_skipped"]
    assert "customfield_13458" not in jira.updates[0][1]
    assert jira.updates[0][1]["customfield_12866"] == "Engineer"


def test_ambiguous_match_is_never_written(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="jdoe@x.com")})
    azure = FakeAzure({"jdoe@x.com": [_user(), _user(upn="other@x.com")]})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1")
    assert res["outcome"] == "ambiguous" and jira.updates == []


def test_apostrophe_email_is_escaped_in_graph_filter(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="[o'brien@x.com|mailto:o'brien@x.com]")})
    azure = FakeAzure()
    assert _job(tmp_path, jira, azure).sync_issue("HRD-1")["outcome"] == "no_match"
    flt = azure.calls[0][1]["$filter"]
    assert "mail eq 'o''brien@x.com'" in flt  # doubled quote: cannot break out of the literal


def test_discover_registers_once_and_scopes_jql(tmp_path):
    jira = FakeJira()
    jira.search_results = [{"key": "HRD-5", "fields": {"project": {"key": "HRD"}}}]
    job = _job(tmp_path, jira, FakeAzure())
    assert job.discover_new_issues(NOW) == 1
    assert job.discover_new_issues(NOW) == 0
    assert "project in (HRD, LIBTA)" in jira.searched[0] and "created >=" in jira.searched[0]


def _seed(job, key, age_minutes):
    job._register(key, key.split("-")[0], NOW - timedelta(minutes=age_minutes))


def test_no_match_inside_window_stays_pending_without_note(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="jdoe@x.com")})
    job = _job(tmp_path, jira, FakeAzure())
    _seed(job, "HRD-1", 5)
    job._process_pending(job.get_row("HRD-1"), NOW)
    row = job.get_row("HRD-1")
    assert row["status"] == "pending" and row["attempts"] == 1 and jira.notes == []


def test_no_match_after_window_posts_one_internal_note(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="jdoe@x.com")})
    job = _job(tmp_path, jira, FakeAzure())
    _seed(job, "HRD-1", 16)
    job._process_pending(job.get_row("HRD-1"), NOW)
    assert job.get_row("HRD-1")["status"] == "not_found"
    assert len(jira.notes) == 1 and "jdoe@x.com" in jira.notes[0][1]
    # A second runner (blue/green) racing in must not post again.
    job._finish_with_note("HRD-1", "not_found", NOW, "dup")
    assert len(jira.notes) == 1


def test_late_provisioned_user_syncs_within_window(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="jdoe@x.com")})
    azure = FakeAzure()
    job = _job(tmp_path, jira, azure)
    _seed(job, "HRD-1", 3)
    job._process_pending(job.get_row("HRD-1"), NOW)
    azure.users["jdoe@x.com"] = [_user()]
    job._process_pending(job.get_row("HRD-1"), NOW)
    row = job.get_row("HRD-1")
    assert row["status"] == "synced" and row["matched_upn"] == "jdoe@x.com"
    assert jira.notes == [] and len(jira.updates) == 1


def test_graph_error_retries_then_fails_after_window_without_note(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="jdoe@x.com")})
    job = _job(tmp_path, jira, FakeAzure(fail=AzureApiError("boom", status_code=500)))
    _seed(job, "HRD-1", 2)
    job._process_pending(job.get_row("HRD-1"), NOW)
    assert job.get_row("HRD-1")["status"] == "pending" and "boom" in job.get_row("HRD-1")["error"]
    _seed(job, "HRD-2", 20)
    jira.issues["HRD-2"] = _issue(customfield_12879="jdoe@x.com")
    job._process_pending(job.get_row("HRD-2"), NOW)
    assert job.get_row("HRD-2")["status"] == "failed" and jira.notes == []


def test_missing_email_posts_explanatory_note_after_window(tmp_path):
    jira = FakeJira({"LIBTA-9": _issue()})
    job = _job(tmp_path, jira, FakeAzure())
    _seed(job, "LIBTA-9", 30)
    job._process_pending(job.get_row("LIBTA-9"), NOW)
    assert job.get_row("LIBTA-9")["status"] == "not_found"
    assert "no work or personal email" in jira.notes[0][1]


def test_run_cycle_sync_end_to_end(tmp_path):
    jira = FakeJira({"HRD-7": _issue(customfield_12879="jdoe@x.com")})
    jira.search_results = [{"key": "HRD-7", "fields": {"project": {"key": "HRD"}}}]
    job = _job(tmp_path, jira, FakeAzure({"jdoe@x.com": [_user()]}))
    assert job.run_cycle_sync(NOW) == {"discovered": 1, "processed": 1}
    assert job.get_row("HRD-7")["status"] == "synced"
    # Next cycle: already terminal, nothing to process and no second write.
    assert job.run_cycle_sync(NOW) == {"discovered": 0, "processed": 0}
    assert len(jira.updates) == 1
