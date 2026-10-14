"""One-time, idempotent Jira custom-field setup for the Entra -> Jira HR sync.

Run from ``backend/``::

    python hr_jira_field_admin.py            # plan only (default) -- prints what would change
    python hr_jira_field_admin.py --apply    # perform renames/creates, then print field ids
    python hr_jira_field_admin.py --screens          # plan adding mapped fields to HRD/LIBTA screens
    python hr_jira_field_admin.py --screens --apply  # add the missing fields (never removes any)
    python hr_jira_field_admin.py --order            # plan putting the mapped fields in sheet order on the screens
    python hr_jira_field_admin.py --order --apply    # do it (only moves fields within their tab)
    python hr_jira_field_admin.py --restore-order data/hr_entra_sync_rollbacks/screen-layout-before-<date>.json --apply

Driven by ``ADP Jira Mapping v1.xlsx``. Re-running is safe: a rename is skipped when the field
already carries the target name, and a create is skipped when a custom field with that exact name
exists. Newly created fields still have to be added to the HRD / LIBTA screens in Jira admin, and
their ids pasted into ``hr_entra_field_map.FIELD_MAP`` before the sync will write them.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

_TYPES = {
    "text": ("com.atlassian.jira.plugin.system.customfieldtypes:textfield",
             "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    "select": ("com.atlassian.jira.plugin.system.customfieldtypes:select",
               "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher"),
    "date": ("com.atlassian.jira.plugin.system.customfieldtypes:datepicker",
             "com.atlassian.jira.plugin.system.customfieldtypes:daterange"),
}

# (field id, current name expected, target name) -- the sheet's "Rename" rows.
RENAMES: tuple[tuple[str, str, str], ...] = (
    ("customfield_13458", "Business Unit (New Hire)", "Business Unit"),
    ("customfield_13459", "Home Department (New Hire)", "Home Department"),
    ("customfield_12866", "Role", "Job Title"),
    ("customfield_12873", "First name", "Legal First Name"),
    ("customfield_12874", "Last name", "Legal Last Name"),
    ("customfield_12881", "Middle name", "Legal Middle Name"),
    ("customfield_12865", "Associate ID", "Position ID"),  # must run before the new Associate ID is created
    ("customfield_12870", "Start Date (New Hire)", "Hire Date"),
    ("customfield_12894", "Employment type", "Worker Category"),
)

# (name, kind, options) -- the sheet's "Create" rows.
CREATES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Preferred Name", "text", ()),
    ("Home State", "text", ()),
    ("Leadership Level 2", "text", ()),
    ("Leadership Level 3", "text", ()),
    ("People Manager (Yes/No)", "select", ("Yes", "No")),
    ("Position Status", "text", ()),
    ("Seniority Date", "date", ()),
    ("Associate ID", "text", ()),
    ("Job Class", "text", ()),
    ("Manager Email", "text", ()),
    ("Work Arrangement", "select", ("In office", "Hybrid", "Remote")),
)

MANUAL = (
    "Function (customfield_11113): sheet says 'Update options' but gives no target list -- edit options in Jira admin.",
    "Worker Category (customfield_12894): sheet says 'update options' but gives no target list -- edit options in Jira admin.",
)


# Screens the sync needs its fields on (company-managed projects; ids from the issue type screen schemes).
# HRD uses one default screen per request type; LIBTA's "create" screen is separate from edit/view.
HRD_SCREENS = (12223, 12224, 12225, 12226, 12227, 12228, 12229)
LIBTA_SCREENS = (12275, 12533)
# Company email address must be enterable when a LIBTA ticket is created (it is the Entra lookup key).
LIBTA_CREATE_SCREEN = 12274
COMPANY_EMAIL_FIELD_ID = "customfield_12879"


@dataclass
class ScreenAdd:
    screen_id: int
    tab_id: int
    field_id: str


def plan_screens(client: Any, field_ids: list[str]) -> list[ScreenAdd]:
    """Fields from ``field_ids`` missing on each target screen. Read-only."""
    base = client.base_url
    targets = [(sid, field_ids) for sid in (*HRD_SCREENS, *LIBTA_SCREENS)]
    targets.append((LIBTA_CREATE_SCREEN, [COMPANY_EMAIL_FIELD_ID]))
    adds: list[ScreenAdd] = []
    for screen_id, wanted in targets:
        resp = client.session.get(f"{base}/rest/api/3/screens/{screen_id}/tabs", timeout=30)
        client._raise_for_status(resp)
        tabs = resp.json()
        if not tabs:
            continue
        present: set[str] = set()
        for tab in tabs:
            fresp = client.session.get(f"{base}/rest/api/3/screens/{screen_id}/tabs/{tab['id']}/fields", timeout=30)
            client._raise_for_status(fresp)
            present.update(f["id"] for f in fresp.json())
        adds.extend(ScreenAdd(screen_id, int(tabs[0]["id"]), fid) for fid in wanted if fid not in present)
    return adds


def apply_screens(client: Any, adds: list[ScreenAdd]) -> None:
    for add in adds:
        resp = client.session.post(
            f"{client.base_url}/rest/api/3/screens/{add.screen_id}/tabs/{add.tab_id}/fields",
            json={"fieldId": add.field_id},
            timeout=30,
        )
        client._raise_for_status(resp)


@dataclass
class FieldMove:
    screen_id: int
    tab_id: int
    field_id: str
    after: str | None  # field id to sit directly after; None = first on the tab


def _screen_layouts(client: Any, screen_ids: list[int]) -> dict[int, dict[int, list[str]]]:
    """{screen id: {tab id: [field ids in display order]}}"""
    out: dict[int, dict[int, list[str]]] = {}
    for sid in screen_ids:
        resp = client.session.get(f"{client.base_url}/rest/api/3/screens/{sid}/tabs", timeout=30)
        client._raise_for_status(resp)
        tabs: dict[int, list[str]] = {}
        for tab in resp.json():
            fresp = client.session.get(f"{client.base_url}/rest/api/3/screens/{sid}/tabs/{tab['id']}/fields", timeout=30)
            client._raise_for_status(fresp)
            tabs[int(tab["id"])] = [f["id"] for f in fresp.json()]
        out[sid] = tabs
    return out


def plan_moves(sid: int, tab_id: int, current: list[str], desired: list[str]) -> list[FieldMove]:
    """Moves that make the desired fields (those present) one contiguous block in order, in place.

    The block sits where the earliest of them already is, so the rest of the screen keeps its relative order.
    Fields on other tabs are left alone. Returns [] when the block is already correct.
    """
    present = [f for f in desired if f in current]
    if not present:
        return []
    work = list(current)
    first = min(work.index(f) for f in present)
    anchor = work[first - 1] if first > 0 else None
    moves: list[FieldMove] = []
    for k, fid in enumerate(present):
        after = anchor if k == 0 else present[k - 1]
        idx = work.index(fid)
        target = 0 if after is None else work.index(after) + 1
        if idx == target:
            continue
        moves.append(FieldMove(sid, tab_id, fid, after))
        work.pop(idx)
        work.insert(0 if after is None else work.index(after) + 1, fid)
    return moves


def plan_order(client: Any, field_ids: list[str]) -> list[FieldMove]:
    targets = [*HRD_SCREENS, *LIBTA_SCREENS, LIBTA_CREATE_SCREEN]
    moves: list[FieldMove] = []
    for sid, tabs in _screen_layouts(client, targets).items():
        for tab_id, current in tabs.items():
            moves.extend(plan_moves(sid, tab_id, current, field_ids))
    return moves


def apply_moves(client: Any, moves: list[FieldMove]) -> None:
    for mv in moves:
        body: dict[str, str] = {"position": "First"} if mv.after is None else {"after": mv.after}
        resp = client.session.post(
            f"{client.base_url}/rest/api/3/screens/{mv.screen_id}/tabs/{mv.tab_id}/fields/{mv.field_id}/move",
            json=body,
            timeout=30,
        )
        client._raise_for_status(resp)


def plan_restore(client: Any, saved: dict[str, dict[str, Any]]) -> list[FieldMove]:
    """Moves that put each saved tab's fields back in their saved order (fields not in the save are untouched)."""
    moves: list[FieldMove] = []
    layouts = _screen_layouts(client, [int(s) for s in saved])
    for sid_text, tabs in saved.items():
        for tab_text, tab in tabs.items():
            current = layouts[int(sid_text)].get(int(tab_text), [])
            desired = [f for f in tab["fields"] if f in current]
            work = list(current)
            for k, fid in enumerate(desired):
                after = None if k == 0 else desired[k - 1]
                idx, target = work.index(fid), (0 if after is None else work.index(after) + 1)
                if idx == target:
                    continue
                moves.append(FieldMove(int(sid_text), int(tab_text), fid, after))
                work.pop(idx)
                work.insert(0 if after is None else work.index(after) + 1, fid)
    return moves


@dataclass
class Step:
    action: str  # rename | create | skip
    detail: str
    field_id: str = ""
    name: str = ""
    kind: str = ""
    options: tuple[str, ...] = ()


def plan(existing_fields: list[dict[str, Any]]) -> list[Step]:
    by_id = {f["id"]: f for f in existing_fields}
    custom_names = {f["name"] for f in existing_fields if f.get("custom")}
    steps: list[Step] = []
    renamed_to: set[str] = set()
    for fid, current, target in RENAMES:
        field = by_id.get(fid)
        if field is None:
            steps.append(Step("skip", f"{fid} not found; cannot rename to {target!r}"))
        elif field["name"] == target:
            steps.append(Step("skip", f"{fid} already named {target!r}"))
            renamed_to.add(target)
        elif field["name"] != current:
            steps.append(Step("skip", f"{fid} is named {field['name']!r}, expected {current!r}; refusing to rename"))
        else:
            steps.append(Step("rename", f"{fid}: {current!r} -> {target!r}", fid, target))
            renamed_to.add(target)
    # A name freed by a rename (Associate ID) is not "taken" for the create step.
    freed = {current for fid, current, target in RENAMES if any(s.field_id == fid and s.action == "rename" for s in steps)}
    taken = (custom_names - freed) | renamed_to
    for name, kind, options in CREATES:
        if name in taken:
            steps.append(Step("skip", f"custom field {name!r} already exists"))
        else:
            steps.append(Step("create", f"create {kind} field {name!r}" + (f" options={list(options)}" if options else ""),
                              name=name, kind=kind, options=options))
            taken.add(name)
    return steps


def apply(client: Any, steps: list[Step]) -> dict[str, str]:
    """Execute rename/create steps; returns {name: field id} for created fields."""
    created: dict[str, str] = {}
    base = client.base_url
    for step in steps:
        if step.action == "rename":
            resp = client.session.put(f"{base}/rest/api/3/field/{step.field_id}", json={"name": step.name}, timeout=30)
            client._raise_for_status(resp)
        elif step.action == "create":
            ftype, searcher = _TYPES[step.kind]
            resp = client.session.post(
                f"{base}/rest/api/3/field",
                json={"name": step.name, "type": ftype, "searcherKey": searcher},
                timeout=30,
            )
            client._raise_for_status(resp)
            field_id = str(resp.json()["id"])
            created[step.name] = field_id
            if step.options:
                ctx = client.session.get(f"{base}/rest/api/3/field/{field_id}/context", timeout=30)
                client._raise_for_status(ctx)
                context_id = ctx.json()["values"][0]["id"]
                opt = client.session.post(
                    f"{base}/rest/api/3/field/{field_id}/context/{context_id}/option",
                    json={"options": [{"value": v} for v in step.options]},
                    timeout=30,
                )
                client._raise_for_status(opt)
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="perform the changes (default: plan only)")
    parser.add_argument("--screens", action="store_true", help="plan/add mapped fields on the HRD/LIBTA screens")
    parser.add_argument("--order", action="store_true", help="plan/apply the sheet's field order on the screens")
    parser.add_argument("--restore-order", metavar="FILE", help="restore screen field order from a saved layout JSON")
    args = parser.parse_args(argv)

    from jira_client import JiraClient

    client = JiraClient()
    if args.order or args.restore_order:
        if args.restore_order:
            import json

            with open(args.restore_order) as fh:
                moves = plan_restore(client, json.load(fh))
        else:
            import hr_entra_field_map as fmap

            moves = plan_order(client, fmap.display_order_field_ids())
        by_screen: dict[int, int] = {}
        for mv in moves:
            by_screen[mv.screen_id] = by_screen.get(mv.screen_id, 0) + 1
        for sid, n in by_screen.items():
            print(f"[MOVE] screen {sid}: {n} field move(s)")
        print(f"\n{len(moves)} move(s) on {len(by_screen)} screen(s).")
        if args.apply:
            apply_moves(client, moves)
            print("Applied.")
        else:
            print("Plan only. Re-run with --apply.")
        return 0
    if args.screens:
        import hr_entra_field_map as fmap

        ids = sorted({m.jira_field_id for m in fmap.FIELD_MAP if m.jira_field_id})
        adds = plan_screens(client, ids)
        for add in adds:
            print(f"[ADD] screen {add.screen_id} tab {add.tab_id}: {add.field_id}")
        print(f"\n{len(adds)} field(s) to add.")
        if args.apply:
            apply_screens(client, adds)
            print("Applied.")
        else:
            print("Plan only. Re-run with --screens --apply.")
        return 0
    resp = client.session.get(f"{client.base_url}/rest/api/3/field", timeout=60)
    client._raise_for_status(resp)
    steps = plan(resp.json())
    for step in steps:
        print(f"[{step.action.upper():6}] {step.detail}")
    for line in MANUAL:
        print(f"[MANUAL] {line}")
    if not args.apply:
        print("\nPlan only. Re-run with --apply to make these changes.")
        return 0
    created = apply(client, steps)
    print("\nCreated fields (paste ids into hr_entra_field_map.FIELD_MAP, then add to HRD/LIBTA screens):")
    for name, fid in created.items():
        print(f"  {name}: {fid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
