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
        self.updated_results = []
        self.base_url = "https://jira.test"
        self.changelogs = {}  # key -> list of changelog entries
        self.forms = {}  # key -> list of {"id","name","questions":{qid:label},"answers":{qid:text}}
        self.session = self

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
        return self.updated_results if "updated >=" in jql else self.search_results

    def get(self, url, params=None, timeout=None):  # stands in for requests.Session.get
        def resp(body):
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: body})()

        if url.endswith("/_edge/tenant_info"):
            return resp({"cloudId": "cloud-1"})
        if "/jira/forms/cloud/" in url:
            key = url.split("/issue/")[1].split("/")[0]
            forms = self.forms.get(key, [])
            tail = url.split(f"/issue/{key}/form")[1]
            if tail in ("", "/"):
                return resp([{"id": f["id"], "name": f["name"]} for f in forms])
            form = next(f for f in forms if f["id"] == tail.strip("/"))
            return resp({"design": {"questions": {q: {"label": label} for q, label in form["questions"].items()}},
                         "state": {"answers": {q: {"text": t} for q, t in form["answers"].items()}}})
        key = url.split("/issue/")[1].split("/")[0]
        entries = self.changelogs.get(key, [])
        return resp({"total": len(entries), "values": entries[(params or {}).get("startAt", 0):]})


ORG_DOMAINS = [
    {"name": "x.com", "capabilities": "Email, OfficeCommunicationsOnline"},
    {"name": "librasolutionsgroup.com", "capabilities": "Email"},
    {"name": "tenant.onmicrosoft.com", "capabilities": "Email"},  # routing domain: never internal
    {"name": "relay.codetwo.online", "capabilities": "None"},  # relay entry: never internal
]


class FakeAzure:
    def __init__(self, users=None, manager=None, fail=None, domains=ORG_DOMAINS):
        self.users = users or {}
        self.manager = manager
        self.fail = fail
        self.domains = domains
        self.calls = []
        self.org_calls = 0

    def graph_request(self, method, path, params=None, headers=None, **_):
        if path == "organization":
            self.org_calls += 1
            if self.domains is None:
                raise AzureApiError("org down", status_code=500)
            return {"value": [{"verifiedDomains": self.domains}]}
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


def _person(email="rep@x.com", name="Rae Porter", account_type="customer"):
    return {"accountType": account_type, "emailAddress": email, "displayName": name}


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
    job._finish_with_note("HRD-1", "not_found", NOW, "", "dup")
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


# ---- reporter fallback ----

def test_reporter_is_used_when_ticket_has_no_email(tmp_path):
    jira = FakeJira({"HRD-1": _issue(reporter=_person("rep@x.com"))})
    azure = FakeAzure({"rep@x.com": [_user(upn="rep@x.com", displayName="Rae Porter", accountEnabled=True, userType="Member")]})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1")
    assert res["outcome"] == "synced" and res["email_source"] == "reporter" and res["fingerprint"] == ""


def test_ticket_email_wins_over_reporter(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="jdoe@x.com", reporter=_person("rep@x.com"))})
    azure = FakeAzure({"jdoe@x.com": [_user()], "rep@x.com": [_user(upn="rep@x.com")]})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1")
    assert res["email_source"] == "ticket" and res["matched_upn"] == "jdoe@x.com"


@pytest.mark.parametrize("reporter", [
    _person(account_type="app"),
    {"accountType": None},
    _person("askhr@librasolutionsgroup.com", "AskHR"),
    _person("payroll@librasolutionsgroup.com", "Payroll"),
    _person("donotreply@adp.com", "donotreply@adp.com"),
])
def test_service_style_reporters_are_never_used(tmp_path, reporter):
    jira = FakeJira({"HRD-1": _issue(reporter=reporter)})
    azure = FakeAzure()
    assert _job(tmp_path, jira, azure).sync_issue("HRD-1")["outcome"] == "no_email"
    assert azure.calls == []


def test_reporter_match_must_be_an_enabled_person_account(tmp_path):
    jira = FakeJira({"HRD-1": _issue(reporter=_person("rep@x.com"))})
    for user in (_user(upn="rep@x.com", accountEnabled=False),
                 _user(upn="rep@x.com", userType="Guest"),
                 _user(upn="rep@x.com", displayName="Shared Mailbox")):
        res = _job(tmp_path, jira, FakeAzure({"rep@x.com": [user]})).sync_issue("HRD-1")
        assert res["outcome"] == "no_match" and jira.updates == []


def test_external_reporter_only_ticket_ends_not_found_without_a_note(tmp_path):
    jira = FakeJira({"HRD-1": _issue(reporter=_person("dse@docusign.net", "dse@docusign.net"))})
    job = _job(tmp_path, jira, FakeAzure())
    _seed(job, "HRD-1", 20)
    job._process_pending(job.get_row("HRD-1"), NOW)
    row = job.get_row("HRD-1")
    assert row["status"] == "not_found" and jira.notes == [] and "not on a tenant domain" in row["error"]


# ---- email change re-sync ----

def _synced_job(tmp_path, jira, azure, key="HRD-1"):
    job = _job(tmp_path, jira, azure)
    _seed(job, key, 1)
    job._process_pending(job.get_row(key), NOW)
    assert job.get_row(key)["status"] == "synced"
    return job


def test_changed_email_reopens_and_resyncs_with_the_new_address(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="old@x.com")})
    azure = FakeAzure({"old@x.com": [_user(upn="old@x.com")], "new@x.com": [_user(upn="new@x.com")]})
    job = _synced_job(tmp_path, jira, azure)
    assert job.get_row("HRD-1")["lookup_fingerprint"] == "old@x.com"
    jira.issues["HRD-1"] = _issue(customfield_12879="new@x.com")
    jira.updated_results = [{"key": "HRD-1", "fields": {"customfield_12879": "new@x.com", "project": {"key": "HRD"}}}]
    assert job.run_cycle_sync(NOW) == {"discovered": 1, "processed": 1}
    row = job.get_row("HRD-1")
    assert row["status"] == "synced" and row["matched_upn"] == "new@x.com" and row["lookup_fingerprint"] == "new@x.com"
    assert len(jira.updates) == 2


def test_unchanged_email_on_an_updated_ticket_does_not_resync(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="old@x.com")})
    job = _synced_job(tmp_path, jira, FakeAzure({"old@x.com": [_user(upn="old@x.com")]}))
    jira.updated_results = [{"key": "HRD-1", "fields": {"customfield_12879": "[old@x.com|mailto:old@x.com]",
                                                        "project": {"key": "HRD"}}}]
    assert job.run_cycle_sync(NOW)["processed"] == 0 and len(jira.updates) == 1


def test_email_added_later_to_a_reporter_synced_ticket_resyncs(tmp_path):
    jira = FakeJira({"HRD-1": _issue(reporter=_person("rep@x.com"))})
    azure = FakeAzure({"rep@x.com": [_user(upn="rep@x.com")], "subj@x.com": [_user(upn="subj@x.com")]})
    job = _synced_job(tmp_path, jira, azure)
    assert job.get_row("HRD-1")["email_source"] == "reporter"
    jira.issues["HRD-1"] = _issue(customfield_12883="subj@x.com", reporter=_person("rep@x.com"))
    jira.updated_results = [{"key": "HRD-1", "fields": {"customfield_12883": "subj@x.com", "project": {"key": "HRD"}}}]
    job.run_cycle_sync(NOW)
    row = job.get_row("HRD-1")
    assert row["matched_upn"] == "subj@x.com" and row["email_source"] == "ticket"


def test_old_unregistered_ticket_is_picked_up_only_if_its_email_was_edited(tmp_path):
    edit = {"created": (NOW - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
            "items": [{"fieldId": "customfield_12879"}]}
    other = {"created": (NOW - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
             "items": [{"fieldId": "summary"}]}
    stale = {"created": (NOW - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
             "items": [{"fieldId": "customfield_12879"}]}
    jira = FakeJira({"HRD-1": _issue(customfield_12879="jdoe@x.com"), "HRD-2": _issue(customfield_12879="jdoe@x.com"),
                     "HRD-3": _issue(customfield_12879="jdoe@x.com")})
    jira.changelogs = {"HRD-1": [edit], "HRD-2": [other], "HRD-3": [stale]}
    jira.updated_results = [{"key": k, "fields": {"customfield_12879": "jdoe@x.com", "project": {"key": "HRD"}}}
                            for k in ("HRD-1", "HRD-2", "HRD-3")]
    job = _job(tmp_path, jira, FakeAzure())
    assert job.discover_email_changes(NOW) == 1
    assert job.get_row("HRD-1") is not None and job.get_row("HRD-2") is None and job.get_row("HRD-3") is None


def test_pending_ticket_with_changed_email_is_not_reopened(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="a@x.com")})
    job = _job(tmp_path, jira, FakeAzure())
    _seed(job, "HRD-1", 2)
    jira.updated_results = [{"key": "HRD-1", "fields": {"customfield_12879": "b@x.com", "project": {"key": "HRD"}}}]
    assert job.discover_email_changes(NOW) == 0


# ---- internal-domain rule ----

def test_internal_domains_exclude_routing_and_relay_entries(tmp_path):
    job = _job(tmp_path, FakeJira(), FakeAzure())
    assert job.internal_domains() == frozenset({"x.com", "librasolutionsgroup.com"})


def test_domains_are_cached_between_lookups(tmp_path):
    azure = FakeAzure()
    job = _job(tmp_path, FakeJira(), azure)
    job.internal_domains()
    job.internal_domains()
    assert azure.org_calls == 1


def test_domains_fail_closed_when_unavailable_and_use_stale_list_when_refresh_fails(tmp_path, monkeypatch):
    job = _job(tmp_path, FakeJira(), FakeAzure(domains=None))
    with pytest.raises(RuntimeError, match="verified domains unavailable"):
        job.internal_domains()
    good = _job(tmp_path, FakeJira(), FakeAzure())
    good.internal_domains()
    good._azure = FakeAzure(domains=None)
    good._domains_at -= s._DOMAINS_TTL_SECONDS + 1  # force a refresh that fails
    assert good.internal_domains() == frozenset({"x.com", "librasolutionsgroup.com"})


def test_external_company_email_is_not_looked_up(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="someone@gmail.com")})
    azure = FakeAzure({"someone@gmail.com": [_user(upn="someone@gmail.com")]})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1")
    assert res["outcome"] == "no_email" and res["skipped_external"] == ["someone@gmail.com"]
    assert azure.calls == [] and jira.updates == []


def test_personal_email_field_is_exempt_from_the_domain_rule(tmp_path):
    jira = FakeJira({"LIBTA-1": _issue(customfield_12883="newhire@gmail.com")})
    azure = FakeAzure({"newhire@gmail.com": [_user(upn="nh@x.com", mail=None)]})
    res = _job(tmp_path, jira, azure).sync_issue("LIBTA-1")
    assert res["outcome"] == "synced" and res["email_source"] == "ticket" and azure.org_calls == 0


def test_subdomain_of_a_tenant_domain_counts_as_internal(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="a@mail.x.com")})
    azure = FakeAzure({"a@mail.x.com": [_user(upn="a@x.com")]})
    assert _job(tmp_path, jira, azure).sync_issue("HRD-1")["outcome"] == "synced"


def test_external_company_email_falls_through_to_internal_reporter(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="x@gmail.com", reporter=_person("rep@x.com"))})
    azure = FakeAzure({"rep@x.com": [_user(upn="rep@x.com", accountEnabled=True)]})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1")
    assert res["outcome"] == "synced" and res["email_source"] == "reporter"


def test_external_reporter_is_never_looked_up_and_ends_immediately_without_a_note(tmp_path):
    jira = FakeJira({"HRD-1": _issue(reporter=_person("dse@docusign.net", "dse@docusign.net"))})
    azure = FakeAzure({"dse@docusign.net": [_user(upn="dse@x.com")]})
    job = _job(tmp_path, jira, azure)
    _seed(job, "HRD-1", 1)  # inside the retry window: no waiting needed
    job._process_pending(job.get_row("HRD-1"), NOW)
    row = job.get_row("HRD-1")
    assert row["status"] == "not_found" and "not on a tenant domain" in row["error"]
    assert azure.calls == [] and jira.notes == [] and jira.updates == []


def test_external_company_email_alone_gets_an_explanatory_note_after_the_window(tmp_path):
    jira = FakeJira({"HRD-1": _issue(customfield_12879="someone@gmail.com")})
    job = _job(tmp_path, jira, FakeAzure())
    _seed(job, "HRD-1", 20)
    job._process_pending(job.get_row("HRD-1"), NOW)
    assert job.get_row("HRD-1")["status"] == "not_found"
    assert "someone@gmail.com is not on a tenant domain" in jira.notes[0][1]


def test_domain_lookup_failure_retries_instead_of_looking_up_blindly(tmp_path):
    jira = FakeJira({"HRD-1": _issue(reporter=_person("rep@x.com"))})
    azure = FakeAzure({"rep@x.com": [_user(upn="rep@x.com", accountEnabled=True)]}, domains=None)
    job = _job(tmp_path, jira, azure)
    _seed(job, "HRD-1", 2)
    job._process_pending(job.get_row("HRD-1"), NOW)
    row = job.get_row("HRD-1")
    assert row["status"] == "pending" and "verified domains unavailable" in row["error"]
    assert azure.calls == [] and jira.updates == []


def test_email_override_is_exempt_for_dry_run_testing(tmp_path):
    jira = FakeJira({"HRD-1": _issue()})
    azure = FakeAzure({"tester@gmail.com": [_user(upn="t@x.com")]})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1", dry_run=True, email_override="tester@gmail.com")
    assert res["outcome"] == "synced" and azure.org_calls == 0


# ---- reporter is not the subject (offboarding, status change, ...) ----

def _typed(issue_type, project="HRD", **fields):
    return _issue(issuetype={"name": issue_type}, project={"key": project}, **fields)


@pytest.mark.parametrize("issue_type", ["Employee offboarding", "Status Change", "Requisition", "Employee onboarding"])
def test_reporter_fallback_never_applies_to_types_filed_on_someones_behalf(tmp_path, issue_type):
    jira = FakeJira({"HRD-1": _typed(issue_type, reporter=_person("rep@x.com"))})
    azure = FakeAzure({"rep@x.com": [_user(upn="rep@x.com", accountEnabled=True)]})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1")
    assert res["outcome"] == "no_email" and res["reporter_blocked"] is True
    assert azure.calls == [] and jira.updates == []


def test_libta_reporter_is_never_used(tmp_path):
    jira = FakeJira({"LIBTA-1": _typed("New Hire Candidate", project="LIBTA", reporter=_person("rep@x.com"))})
    azure = FakeAzure({"rep@x.com": [_user(upn="rep@x.com", accountEnabled=True)]})
    assert _job(tmp_path, jira, azure).sync_issue("LIBTA-1")["reporter_blocked"] is True
    assert azure.calls == []


def test_reporter_still_used_for_self_service_types(tmp_path):
    jira = FakeJira({"HRD-1": _typed("General Inquiry", reporter=_person("rep@x.com"))})
    azure = FakeAzure({"rep@x.com": [_user(upn="rep@x.com", accountEnabled=True)]})
    assert _job(tmp_path, jira, azure).sync_issue("HRD-1")["email_source"] == "reporter"


def test_ticket_email_still_works_on_offboarding_tickets(tmp_path):
    jira = FakeJira({"HRD-1": _typed("Employee offboarding", customfield_12883="leaver@gmail.com",
                                     reporter=_person("hr@x.com"))})
    azure = FakeAzure({"leaver@gmail.com": [_user(upn="leaver@x.com", mail=None)]})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1")
    assert res["outcome"] == "synced" and res["email_source"] == "ticket" and res["matched_upn"] == "leaver@x.com"


def test_blocked_reporter_ticket_ends_quietly_with_no_note_and_no_write(tmp_path):
    jira = FakeJira({"HRD-1": _typed("Status Change", reporter=_person("hr@x.com"))})
    job = _job(tmp_path, jira, FakeAzure())
    _seed(job, "HRD-1", 1)
    job._process_pending(job.get_row("HRD-1"), NOW)
    row = job.get_row("HRD-1")
    assert row["status"] == "not_found" and "Employee not identified" in row["error"]
    assert jira.notes == [] and jira.updates == []


# ---- offboarding: the employee comes from the form's "Employee Work Email" ----

def _offboarding(**extra):
    return _typed("Employee offboarding", reporter=_person("hr@x.com"), **extra)


def _resignation_form(work_email, contact_email="leaver.personal@gmail.com"):
    return [{"id": "f1", "name": "Voluntary Resignation Request",
             "questions": {"38": "Employee Work Email", "51": "Contact Email Address", "46": "Additional Comments"},
             "answers": {"38": work_email, "51": contact_email, "46": "see hr@x.com"}}]


def test_offboarding_uses_the_forms_employee_work_email_not_the_reporter(tmp_path):
    jira = FakeJira({"HRD-1": _offboarding()})
    jira.forms["HRD-1"] = _resignation_form("[leaver@x.com|mailto:leaver@x.com]")
    azure = FakeAzure({"leaver@x.com": [_user(upn="leaver@x.com")], "hr@x.com": [_user(upn="hr@x.com")]})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1")
    assert res["outcome"] == "synced" and res["email_source"] == "form" and res["matched_upn"] == "leaver@x.com"
    assert [c[1]["$filter"].split("'")[1] for c in azure.calls if c[0] == "users"] == ["leaver@x.com"]


def test_only_the_work_email_question_is_used_not_other_email_answers(tmp_path):
    jira = FakeJira({"HRD-1": _offboarding()})
    jira.forms["HRD-1"] = [{"id": "f1", "name": "x", "questions": {"51": "Contact Email Address"},
                            "answers": {"51": "leaver.personal@gmail.com"}}]
    azure = FakeAzure({"leaver.personal@gmail.com": [_user(upn="leaver@x.com")]})
    res = _job(tmp_path, jira, azure).sync_issue("HRD-1")
    assert res["outcome"] == "no_email" and azure.calls == []


def test_offboarding_without_a_form_is_left_alone_not_matched_to_the_reporter(tmp_path):
    jira = FakeJira({"HRD-1": _offboarding()})
    azure = FakeAzure({"hr@x.com": [_user(upn="hr@x.com", accountEnabled=True)]})
    job = _job(tmp_path, jira, azure)
    _seed(job, "HRD-1", 1)
    job._process_pending(job.get_row("HRD-1"), NOW)
    row = job.get_row("HRD-1")
    assert row["status"] == "not_found" and "Employee not identified" in row["error"]
    assert azure.calls == [] and jira.updates == [] and jira.notes == []


def test_external_form_email_gets_a_note_after_the_window_and_is_never_looked_up(tmp_path):
    jira = FakeJira({"HRD-1": _offboarding()})
    jira.forms["HRD-1"] = _resignation_form("leaver@gmail.com")
    azure = FakeAzure({"leaver@gmail.com": [_user(upn="leaver@x.com")]})
    job = _job(tmp_path, jira, azure)
    _seed(job, "HRD-1", 20)
    job._process_pending(job.get_row("HRD-1"), NOW)
    assert azure.calls == [] and "leaver@gmail.com is not on a tenant domain" in jira.notes[0][1]


def test_forms_are_only_fetched_for_types_that_use_them(tmp_path):
    jira = FakeJira({"HRD-1": _typed("General Inquiry", reporter=_person("rep@x.com"))})
    jira.forms = None  # would raise if the job tried to read forms
    azure = FakeAzure({"rep@x.com": [_user(upn="rep@x.com", accountEnabled=True)]})
    assert _job(tmp_path, jira, azure).sync_issue("HRD-1")["email_source"] == "reporter"
