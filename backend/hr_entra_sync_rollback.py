"""Snapshot and roll back a real Entra -> Jira sync run on one ticket.

Take a snapshot immediately before a real run, then restore it later if asked::

    python hr_entra_sync_rollback.py data/hr_entra_sync_rollbacks/HRD-2163-<ts>.json           # plan only
    python hr_entra_sync_rollback.py data/hr_entra_sync_rollbacks/HRD-2163-<ts>.json --apply
    python hr_entra_sync_rollback.py <file> --apply --force   # also revert fields edited since the run

By default a field is only reverted if it still holds the value the sync wrote, so a person's later edit is never undone.
Snapshots contain ticket field values (employee data): they live under ``data/`` (git-ignored); never commit them.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

import hr_entra_field_map as fmap


def _plain(value: Any) -> Any:
    """Reduce a Jira field value to a comparable, PUT-able shape (select -> {"value": ...})."""
    if isinstance(value, dict) and "value" in value:
        return {"value": value["value"]}
    return value


def capture(jira: Any, issue_key: str, field_ids: list[str]) -> dict[str, Any]:
    fields = jira.get_issue(issue_key).get("fields") or {}
    return {fid: _plain(fields.get(fid)) for fid in field_ids}


def new_snapshot(jira: Any, issue_key: str, note: str = "") -> dict[str, Any]:
    ids = sorted({m.jira_field_id for m in fmap.FIELD_MAP if m.jira_field_id})
    names = {m.jira_field_id: m.jira_name for m in fmap.FIELD_MAP if m.jira_field_id}
    return {
        "issue_key": issue_key,
        "note": note,
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "names": names,
        "before": capture(jira, issue_key, ids),
        "written": [],
        "after": {},
    }


def record_run(jira: Any, snapshot: dict[str, Any], written_field_ids: list[str]) -> None:
    snapshot["ran_at"] = datetime.now(timezone.utc).isoformat()
    snapshot["written"] = sorted(written_field_ids)
    snapshot["after"] = capture(jira, snapshot["issue_key"], snapshot["written"])


def plan(jira: Any, snapshot: dict[str, Any], *, force: bool = False) -> tuple[dict[str, Any], dict[str, str]]:
    """(fields to restore, {field id: reason skipped}). A field edited after the run is skipped unless ``force``."""
    current = capture(jira, snapshot["issue_key"], snapshot["written"])
    restore: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    for fid in snapshot["written"]:
        before, after, now = snapshot["before"].get(fid), snapshot["after"].get(fid), current.get(fid)
        if now == before:
            skipped[fid] = "already at the pre-run value"
        elif now != after and not force:
            skipped[fid] = "changed since the sync ran (use --force to revert anyway)"
        else:
            restore[fid] = before
    return restore, skipped


def rollback(jira: Any, snapshot: dict[str, Any], *, apply: bool, force: bool = False) -> tuple[dict[str, Any], dict[str, str]]:
    restore, skipped = plan(jira, snapshot, force=force)
    if apply and restore:
        jira.update_issue_fields(snapshot["issue_key"], restore)
    return restore, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("snapshot", help="snapshot JSON written before the real run")
    parser.add_argument("--apply", action="store_true", help="perform the rollback (default: plan only)")
    parser.add_argument("--force", action="store_true", help="also revert fields changed since the run")
    args = parser.parse_args(argv)
    with open(args.snapshot) as fh:
        snap = json.load(fh)
    from jira_client import JiraClient

    jira = JiraClient()
    restore, skipped = rollback(jira, snap, apply=args.apply, force=args.force)
    names = snap.get("names", {})
    for fid in restore:
        print(f"[{'RESTORE' if args.apply else 'WOULD RESTORE'}] {names.get(fid, fid)} ({fid})")
    for fid, why in skipped.items():
        print(f"[SKIP] {names.get(fid, fid)} ({fid}): {why}")
    if not args.apply:
        print(f"\nPlan only for {snap['issue_key']}. Re-run with --apply to roll back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
