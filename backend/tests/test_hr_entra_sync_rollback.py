"""Rollback of a real sync run: restores only what the sync wrote, never a later human edit."""
import hr_entra_sync_rollback as rb

TITLE, DEPT, FUNC = "customfield_12866", "customfield_13459", "customfield_11113"


class FakeJira:
    def __init__(self, fields):
        self.fields = dict(fields)
        self.puts = []

    def get_issue(self, key):
        return {"fields": dict(self.fields)}

    def update_issue_fields(self, key, fields):
        self.puts.append(fields)
        self.fields.update(fields)


def _snap(jira):
    snap = rb.new_snapshot(jira, "HRD-1", note="test")
    jira.fields.update({TITLE: "Engineer", DEPT: "Ops", FUNC: {"value": "IT", "id": "9", "self": "x"}})
    rb.record_run(jira, snap, [TITLE, DEPT, FUNC])
    return snap


def test_snapshot_normalizes_select_values_and_records_before_and_after():
    jira = FakeJira({FUNC: {"value": "Sales", "id": "1", "self": "x"}, TITLE: None})
    snap = _snap(jira)
    assert snap["before"][FUNC] == {"value": "Sales"} and snap["before"][TITLE] is None
    assert snap["after"][FUNC] == {"value": "IT"} and snap["written"] == sorted([TITLE, DEPT, FUNC])


def test_rollback_restores_previous_values_including_clearing_empties():
    jira = FakeJira({FUNC: {"value": "Sales"}, TITLE: None})
    snap = _snap(jira)
    restore, skipped = rb.rollback(jira, snap, apply=True)
    assert skipped == {} and jira.fields[TITLE] is None and jira.fields[FUNC] == {"value": "Sales"}
    assert jira.puts[-1][TITLE] is None  # a None in the PUT clears the field


def test_plan_only_changes_nothing():
    jira = FakeJira({})
    snap = _snap(jira)
    restore, _ = rb.rollback(jira, snap, apply=False)
    assert restore and jira.puts == [] and jira.fields[TITLE] == "Engineer"


def test_later_human_edit_is_not_reverted_without_force():
    jira = FakeJira({})
    snap = _snap(jira)
    jira.fields[TITLE] = "Senior Engineer"  # someone edited after the sync
    restore, skipped = rb.rollback(jira, snap, apply=True)
    assert TITLE not in restore and "changed since" in skipped[TITLE]
    assert jira.fields[TITLE] == "Senior Engineer" and jira.fields[DEPT] is None
    forced, _ = rb.rollback(jira, snap, apply=True, force=True)
    assert TITLE in forced and jira.fields[TITLE] is None


def test_second_rollback_is_a_noop():
    jira = FakeJira({})
    snap = _snap(jira)
    rb.rollback(jira, snap, apply=True)
    puts = len(jira.puts)
    restore, skipped = rb.rollback(jira, snap, apply=True)
    assert restore == {} and len(jira.puts) == puts
    assert all("already" in why for why in skipped.values())
