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


class _Resp:
    def __init__(self, data):
        self._d = data
        self.ok = True

    def json(self):
        return self._d


class _Session:
    def __init__(self, screens):
        self.screens = screens  # screen id -> {tab id: [field ids]}
        self.posted = []

    def get(self, url, timeout=None):
        parts = url.split("/screens/")[1].split("/")
        screen = int(parts[0])
        tabs = self.screens.get(screen, {})
        if len(parts) == 2:  # .../tabs
            return _Resp([{"id": t} for t in tabs])
        return _Resp([{"id": f} for f in tabs[int(parts[2])]])

    def post(self, url, json=None, timeout=None):
        self.posted.append((url, json))
        return _Resp({})


class _Client:
    base_url = "https://x"

    def __init__(self, screens):
        self.session = _Session(screens)

    @staticmethod
    def _raise_for_status(resp):
        pass


def _all_screens(fields):
    ids = (*a.HRD_SCREENS, *a.LIBTA_SCREENS, a.LIBTA_CREATE_SCREEN)
    return {sid: {sid * 10: list(fields)} for sid in ids}


def test_plan_screens_adds_only_missing_fields_and_company_email_to_libta_create():
    screens = _all_screens(["customfield_1"])
    screens[a.HRD_SCREENS[0]][a.HRD_SCREENS[0] * 10].append("customfield_2")
    adds = a.plan_screens(_Client(screens), ["customfield_1", "customfield_2", "customfield_3"])
    first = [x.field_id for x in adds if x.screen_id == a.HRD_SCREENS[0]]
    assert first == ["customfield_3"]
    create = [x.field_id for x in adds if x.screen_id == a.LIBTA_CREATE_SCREEN]
    assert create == [a.COMPANY_EMAIL_FIELD_ID]
    assert all(x.tab_id == x.screen_id * 10 for x in adds)


def test_plan_screens_is_empty_when_everything_present_and_apply_posts_each_add():
    full = ["customfield_1", a.COMPANY_EMAIL_FIELD_ID]
    assert a.plan_screens(_Client(_all_screens(full)), ["customfield_1"]) == []
    client = _Client(_all_screens(["customfield_9"]))
    adds = a.plan_screens(client, ["customfield_1"])
    a.apply_screens(client, adds)
    assert len(client.session.posted) == len(adds)
    assert client.session.posted[0][1] == {"fieldId": adds[0].field_id}
