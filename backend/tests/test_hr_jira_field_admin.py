"""HR Jira field admin script: planning is idempotent and conservative."""
import hr_jira_field_admin as a


def _fields(names_by_id, custom_extra=()):
    out = [{"id": i, "name": n, "custom": True} for i, n in names_by_id.items()]
    out += [{"id": f"customfield_9{i}", "name": n, "custom": True} for i, n in enumerate(custom_extra)]
    return out


CURRENT = {fid: current for fid, current, _ in a.RENAMES}


def test_fresh_tenant_plans_all_renames_and_creates():
    steps = a.plan(_fields(CURRENT))
    assert sum(s.action == "rename" for s in steps) == len(a.RENAMES)
    assert sum(s.action == "create" for s in steps) == len(a.CREATES)


def test_associate_id_name_freed_by_rename_so_new_associate_id_is_created():
    steps = a.plan(_fields(CURRENT))
    assert any(s.action == "create" and s.name == "Associate ID" for s in steps)


def test_second_run_is_a_noop():
    done = {fid: target for fid, _, target in a.RENAMES}
    existing = _fields(done, custom_extra=[n for n, _, _ in a.CREATES])
    assert all(s.action == "skip" for s in a.plan(existing))


def test_unexpected_current_name_refuses_rename():
    wrong = dict(CURRENT, customfield_12866="Something Else")
    steps = a.plan(_fields(wrong))
    assert any(s.action == "skip" and "refusing" in s.detail for s in steps)


def test_duplicate_existing_custom_name_not_recreated():
    steps = a.plan(_fields(CURRENT, custom_extra=["Job Class"]))
    assert not any(s.action == "create" and s.name == "Job Class" for s in steps)
