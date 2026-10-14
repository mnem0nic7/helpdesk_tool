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


# ---- field ordering ----

def test_display_order_is_every_mapped_field_exactly_once():
    import hr_entra_field_map as fm

    assert sorted(fm.DISPLAY_ORDER) == sorted(m.jira_name for m in fm.FIELD_MAP)
    ids = fm.display_order_field_ids()
    assert len(ids) == len(set(ids)) == len(fm.FIELD_MAP)
    assert fm.DISPLAY_ORDER[0] == "Preferred Name" and fm.DISPLAY_ORDER[-1] == "Associate ID"


def _apply_to(current, moves):
    work = list(current)
    for mv in moves:
        work.remove(mv.field_id)
        work.insert(0 if mv.after is None else work.index(mv.after) + 1, mv.field_id)
    return work


def test_plan_moves_makes_a_contiguous_ordered_block_in_place_keeping_other_fields_in_order():
    current = ["summary", "c", "x1", "a", "x2", "b", "x3", "d", "description"]
    moves = a.plan_moves(7, 70, current, ["a", "b", "c", "d"])
    result = _apply_to(current, moves)
    # the block starts where the earliest of its fields (c, at index 1) was
    assert result[1:5] == ["a", "b", "c", "d"]
    block = [f for f in result if f in "abcd"]
    assert block == ["a", "b", "c", "d"]
    idx = [result.index(f) for f in block]
    assert idx == list(range(idx[0], idx[0] + 4))
    assert [f for f in result if f.startswith("x")] == ["x1", "x2", "x3"]
    assert result[0] == "summary" and result[-1] == "description"


def test_plan_moves_puts_the_block_first_when_a_field_is_already_first_and_is_idempotent():
    current = ["b", "x", "a"]
    moves = a.plan_moves(1, 1, current, ["a", "b"])
    assert moves[0].after is None or moves[0].after == "b"
    result = _apply_to(current, moves)
    assert result[:2] == ["a", "b"]
    assert a.plan_moves(1, 1, result, ["a", "b"]) == []


def test_plan_moves_ignores_fields_not_on_the_tab():
    assert a.plan_moves(1, 1, ["x", "y"], ["a", "b"]) == []
    moves = a.plan_moves(1, 1, ["x", "b", "y"], ["a", "b"])
    assert moves == []  # only b is present: already a contiguous, ordered block of one


def test_plan_restore_reproduces_the_saved_order():
    saved = {"5": {"9": {"name": "Default", "fields": ["a", "b", "c", "d"]}}}
    client = _Client({5: {9: ["d", "b", "a", "c"]}})
    moves = a.plan_restore(client, saved)
    assert _apply_to(["d", "b", "a", "c"], moves) == ["a", "b", "c", "d"]
