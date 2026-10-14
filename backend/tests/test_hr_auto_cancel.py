"""HR auto-cancel: osidigital.com senders -> Cancelled by HR."""
from datetime import datetime, timezone

import pytest

import hr_auto_cancel as ac

NOW = datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)


def _issue(key, email, status="New Request", project="HRD", creator=None):
    return {"key": key, "fields": {
        "reporter": {"emailAddress": email}, "creator": {"emailAddress": creator or email},
        "status": {"name": status}, "project": {"key": project}}}


class FakeJira:
    def __init__(self, issues, transitions=None):
        self.issues = issues
        self.transitions = transitions if transitions is not None else {
            "default": [{"id": "8", "to": {"name": "Closed"}}, {"id": "9", "to": {"name": "Cancelled by HR"}}]}
        self.done = []
        self.notes = []
        self.jql = []
        self.fail_transition = False

    def search_all(self, jql, fields=None, progress_callback=None):
        self.jql.append(jql)
        return self.issues

    def get_transitions(self, key):
        return self.transitions.get(key, self.transitions.get("default", []))

    def transition_issue(self, key, tid):
        if self.fail_transition:
            raise RuntimeError("boom")
        self.done.append((key, tid))

    def add_internal_comment(self, key, text):
        self.notes.append((key, text))


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(ac, "HR_AUTO_CANCEL_SENDER_DOMAINS", ["osidigital.com"])
    monkeypatch.setattr(ac, "HR_AUTO_CANCEL_STATUS", "Cancelled by HR")
    monkeypatch.setattr(ac, "HR_AUTO_CANCEL_PROJECTS", ["HRD", "LIBTA"])


def _job(tmp_path, jira):
    return ac.HrAutoCancelJob(db_path=str(tmp_path / "ac.db"), jira=jira)


def test_matches_domain_exact_and_subdomain_but_not_lookalikes():
    d = ["osidigital.com"]
    assert ac.matches_domain("support@osidigital.com", d)
    assert ac.matches_domain("a@mail.osidigital.com", d)
    assert not ac.matches_domain("a@notosidigital.com", d)
    assert not ac.matches_domain("a@osidigital.com.evil.io", d)
    assert not ac.matches_domain("", d)


def test_sender_email_falls_back_to_creator_when_reporter_email_is_hidden():
    assert ac.sender_email({"reporter": {"emailAddress": None}, "creator": {"emailAddress": "A@X.com"}}) == "a@x.com"
    assert ac.sender_email({"reporter": {}, "creator": {}}) == ""


def test_cancels_osidigital_tickets_and_leaves_an_internal_note(tmp_path):
    jira = FakeJira([_issue("HRD-1", "support@osidigital.com"), _issue("HRD-2", "someone@x.com")])
    job = _job(tmp_path, jira)
    job.run_cycle_sync(NOW)
    assert jira.done == [("HRD-1", "9")]
    assert "osidigital.com" in jira.notes[0][1] and jira.notes[0][0] == "HRD-1"
    row = job.get_row("HRD-1")
    assert row["result"] == "cancelled" and row["to_status"] == "Cancelled by HR" and row["from_status"] == "New Request"
    assert job.get_row("HRD-2") is None


def test_jql_only_considers_to_do_status_category_tickets_created_recently(tmp_path):
    jira = FakeJira([])
    _job(tmp_path, jira).run_cycle_sync(NOW)
    assert 'statusCategory = "To Do"' in jira.jql[0] and "created >= -" in jira.jql[0]
    assert "project in (HRD, LIBTA)" in jira.jql[0]


def test_once_only_a_reopened_ticket_is_never_cancelled_again(tmp_path):
    jira = FakeJira([_issue("HRD-1", "support@osidigital.com")])
    job = _job(tmp_path, jira)
    job.run_cycle_sync(NOW)
    job.run_cycle_sync(NOW)  # someone reopened it: it shows up as a To Do candidate again
    assert jira.done == [("HRD-1", "9")] and len(jira.notes) == 1


def test_a_second_runner_cannot_act_on_a_claimed_ticket(tmp_path):
    jira = FakeJira([_issue("HRD-1", "support@osidigital.com")])
    job = _job(tmp_path, jira)
    assert job._claim("HRD-1", "HRD", "support@osidigital.com", "New Request", NOW) is True
    assert job._claim("HRD-1", "HRD", "support@osidigital.com", "New Request", NOW) is False


def test_project_without_the_status_is_recorded_no_transition_and_left_alone(tmp_path):
    jira = FakeJira([_issue("LIBTA-1", "support@osidigital.com", project="LIBTA")],
                    transitions={"default": [{"id": "5", "to": {"name": "Offer Declined"}}]})
    job = _job(tmp_path, jira)
    job.run_cycle_sync(NOW)
    row = job.get_row("LIBTA-1")
    assert jira.done == [] and jira.notes == [] and row["result"] == "no_transition" and "no 'Cancelled by HR'" in row["error"]


def test_failed_transition_is_retried_then_given_up_after_max_attempts(tmp_path):
    jira = FakeJira([_issue("HRD-1", "support@osidigital.com")])
    jira.fail_transition = True
    job = _job(tmp_path, jira)
    job.run_cycle_sync(NOW)
    assert job.get_row("HRD-1")["result"] == "failed" and jira.notes == []
    jira.fail_transition = False
    job.run_cycle_sync(NOW)  # retried, now succeeds
    assert job.get_row("HRD-1")["result"] == "cancelled" and jira.done == [("HRD-1", "9")]
    # a ticket that keeps failing stops being retried
    jira2 = FakeJira([_issue("HRD-9", "support@osidigital.com")])
    jira2.fail_transition = True
    job2 = ac.HrAutoCancelJob(db_path=str(tmp_path / "ac2.db"), jira=jira2)
    for _ in range(ac._MAX_ATTEMPTS + 3):
        job2.run_cycle_sync(NOW)
    assert job2.get_row("HRD-9")["attempts"] == ac._MAX_ATTEMPTS


def test_hidden_reporter_email_is_skipped_not_guessed(tmp_path):
    jira = FakeJira([{"key": "HRD-1", "fields": {"reporter": {"emailAddress": None}, "creator": {}, "status": {"name": "x"},
                                                  "project": {"key": "HRD"}}}])
    _job(tmp_path, jira).run_cycle_sync(NOW)
    assert jira.done == []


def test_preview_lists_candidates_without_acting_or_recording(tmp_path):
    jira = FakeJira([_issue("HRD-1", "support@osidigital.com")])
    job = _job(tmp_path, jira)
    assert [c["key"] for c in job.preview()] == ["HRD-1"]
    assert jira.done == [] and job.get_row("HRD-1") is None
    job.run_cycle_sync(NOW)
    assert job.preview() == []


def test_note_failure_does_not_undo_the_cancellation(tmp_path):
    class NoteFails(FakeJira):
        def add_internal_comment(self, key, text):
            raise RuntimeError("comment API down")

    jira = NoteFails([_issue("HRD-1", "support@osidigital.com")])
    job = _job(tmp_path, jira)
    job.run_cycle_sync(NOW)
    assert jira.done == [("HRD-1", "9")] and job.get_row("HRD-1")["result"] == "cancelled"
