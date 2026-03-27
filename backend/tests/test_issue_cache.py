from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

from issue_cache import IssueCache


def _issue(
    key: str,
    summary: str,
    *,
    labels: list[str] | None = None,
    created: str | None = None,
    updated: str | None = None,
) -> dict:
    created_at = created or (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    updated_at = updated or created_at
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "labels": labels or [],
            "status": {"name": "Open", "statusCategory": {"name": "To Do"}},
            "created": created_at,
            "updated": updated_at,
        },
    }


class _FakeClient:
    def __init__(self, updated_issues: list[dict]) -> None:
        self.updated_issues = updated_issues
        self.enriched_batches: list[list[str]] = []
        self.search_jqls: list[str] = []

    def search_all(self, jql: str, progress_callback=None) -> list[dict]:
        self.search_jqls.append(jql)
        return list(self.updated_issues)

    def enrich_request_types(self, issues: list[dict], existing_cache=None) -> None:
        self.enriched_batches.append([issue["key"] for issue in issues])


def _build_cache(tmp_path, updated_issues: list[dict]) -> IssueCache:
    cache = IssueCache(str(tmp_path / "issues.db"))
    cache._client = _FakeClient(updated_issues)
    cache._initialized = True
    cache._auto_triage_seen = set()
    cache._sync_requestors_best_effort = lambda issues, open_only=False: None
    cache._sync_followup_authority_best_effort = (
        lambda issues, force=False, recent_days=35: None
    )

    primary_old = _issue("OIT-100", "Primary old")
    oasis_old = _issue("OIT-500", "Oasis old", labels=["oasisdev"])

    cache._all_issues = {
        primary_old["key"]: primary_old,
        oasis_old["key"]: oasis_old,
    }
    cache._issues = {
        primary_old["key"]: primary_old,
    }
    return cache


def test_manual_incremental_refresh_updates_oasisdev_tickets(tmp_path):
    updated_issues = [
        _issue("OIT-100", "Primary new"),
        _issue("OIT-500", "Oasis new", labels=["oasisdev"]),
    ]
    cache = _build_cache(tmp_path, updated_issues)

    untriaged = cache._incremental_refresh()

    assert cache._all_issues["OIT-100"]["fields"]["summary"] == "Primary new"
    assert cache._all_issues["OIT-500"]["fields"]["summary"] == "Oasis new"
    assert untriaged == ["OIT-100"]
    assert cache._client.enriched_batches == [["OIT-100", "OIT-500"]]


def test_incremental_refresh_prunes_cached_non_tracked_project_keys(tmp_path):
    updated_issues = [_issue("OIT-100", "Primary new")]
    cache = _build_cache(tmp_path, updated_issues)
    moved_issue = _issue("MSD-900", "Moved away")
    cache._all_issues[moved_issue["key"]] = moved_issue

    cache._incremental_refresh()

    assert "MSD-900" not in cache._all_issues
    assert "MSD-900" not in cache._issues


def test_incremental_refresh_expands_lookback_from_last_refresh_gap(tmp_path):
    updated_issues = [_issue("OIT-100", "Primary new")]
    cache = _build_cache(tmp_path, updated_issues)
    cache._last_refresh = datetime.now(timezone.utc) - timedelta(minutes=7, seconds=5)

    cache._incremental_refresh()

    assert cache._client.search_jqls
    jql = cache._client.search_jqls[-1]
    marker = 'updated >= "-'
    start = jql.index(marker) + len(marker)
    end = jql.index('m"', start)
    lookback_minutes = int(jql[start:end])
    assert lookback_minutes >= 10


def test_auto_triage_status_marks_existing_old_tickets_processed_once(tmp_path, monkeypatch):
    import triage_store

    monkeypatch.setattr(
        triage_store,
        "store",
        triage_store.TriageStore(str(tmp_path / "triage.db")),
    )

    cache = IssueCache(str(tmp_path / "issues.db"))
    cache._initialized = True

    old_issue = _issue(
        "OIT-100",
        "Old ticket",
        created=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
    )
    recent_issue = _issue(
        "OIT-101",
        "Recent ticket",
        created=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    )

    cache._all_issues = {
        old_issue["key"]: old_issue,
        recent_issue["key"]: recent_issue,
    }
    cache._issues = dict(cache._all_issues)

    first_status = cache.auto_triage_status("primary")

    assert first_status["pending_keys"] == ["OIT-101"]
    assert triage_store.store.get_auto_triaged_keys() == {"OIT-100"}
    assert (
        triage_store.store.get_metadata(
            "auto_triage_backfill_older_than_24h_processed_v1"
        )
        == "1"
    )

    later_old_issue = _issue(
        "OIT-102",
        "Later old ticket",
        created=(datetime.now(timezone.utc) - timedelta(hours=26)).isoformat(),
    )
    cache._all_issues[later_old_issue["key"]] = later_old_issue
    cache._issues[later_old_issue["key"]] = later_old_issue

    second_status = cache.auto_triage_status("primary")

    assert second_status["pending_keys"] == ["OIT-101", "OIT-102"]
    assert triage_store.store.get_auto_triaged_keys() == {"OIT-100"}


def test_followup_bootstrap_backfills_cached_recent_issues(tmp_path):
    cache = IssueCache(str(tmp_path / "issues.db"))
    cache._initialized = True

    recent_issue = _issue(
        "OIT-200",
        "Recent ticket",
        created=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
    )
    old_issue = _issue(
        "OIT-201",
        "Old ticket",
        created=(datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
    )

    cache._all_issues = {
        recent_issue["key"]: recent_issue,
        old_issue["key"]: old_issue,
    }
    cache._issues = dict(cache._all_issues)

    def _fake_followup_sync(issues, *, force=False, recent_days=35):
        del force, recent_days
        for issue in issues:
            if issue["key"] == "OIT-200":
                issue.setdefault("fields", {})["_movedocs_followup_status"] = "Running"

    cache._sync_followup_authority_best_effort = _fake_followup_sync

    changed = cache._backfill_recent_followup_authority_from_cache()

    assert changed == 1
    assert cache._all_issues["OIT-200"]["fields"]["_movedocs_followup_status"] == "Running"
    assert "_movedocs_followup_status" not in cache._all_issues["OIT-201"]["fields"]


def test_upsert_issue_stores_occ_ticket_id_from_description(tmp_path):
    db_path = tmp_path / "issues.db"
    cache = IssueCache(str(db_path))
    cache._initialized = True

    issue = _issue("OIT-210", "Imported from OCC")
    issue["fields"]["description"] = "OCC Ticket Created By: Libra PhishER | OCC Ticket ID: LIBRA-SR-075203"

    cache.upsert_issue(issue)

    assert cache._all_issues["OIT-210"]["fields"]["_movedocs_occ_ticket_id"] == "LIBRA-SR-075203"

    restored = IssueCache(str(db_path))
    assert restored._load_from_db() is True
    assert restored._all_issues["OIT-210"]["fields"]["_movedocs_occ_ticket_id"] == "LIBRA-SR-075203"


def test_occ_ticket_id_backfill_updates_cached_legacy_issues_once(tmp_path):
    db_path = tmp_path / "issues.db"
    cache = IssueCache(str(db_path))
    cache._initialized = True

    legacy_issue = _issue("OIT-211", "Legacy OCC ticket")
    legacy_issue["fields"]["description"] = "Please see OCC Ticket ID: libra-sr-000111 for the source alert."
    cache._all_issues = {legacy_issue["key"]: legacy_issue}
    cache._issues = dict(cache._all_issues)

    changed = cache.ensure_occ_ticket_id_backfill()

    assert changed == 1
    assert cache._all_issues["OIT-211"]["fields"]["_movedocs_occ_ticket_id"] == "LIBRA-SR-000111"
    assert cache.ensure_occ_ticket_id_backfill() == 0

    restored = IssueCache(str(db_path))
    assert restored._load_from_db() is True
    assert restored._all_issues["OIT-211"]["fields"]["_movedocs_occ_ticket_id"] == "LIBRA-SR-000111"


def test_load_from_db_drops_non_tracked_project_keys(tmp_path):
    db_path = tmp_path / "issues.db"
    cache = IssueCache(str(db_path))
    oit_issue = _issue("OIT-100", "Tracked")
    msd_issue = _issue("MSD-100", "Moved away")

    cache._upsert_to_db([oit_issue, msd_issue])

    restored = IssueCache(str(db_path))

    assert restored._load_from_db() is True
    assert set(restored._all_issues) == {"OIT-100"}
    assert "MSD-100" not in restored._issues
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM issues WHERE key = ?", ("MSD-100",)).fetchone()[0]
    assert count == 0


def test_init_restores_last_refresh_from_metadata(tmp_path):
    db_path = tmp_path / "issues.db"
    IssueCache(str(db_path))
    expected = "2026-03-26T08:00:00+00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_refresh', ?)",
            (expected,),
        )

    restored = IssueCache(str(db_path))

    assert restored.last_refresh is not None
    assert restored.last_refresh.isoformat() == expected
    assert restored.status()["last_refresh"] == expected


def test_upsert_issue_ignores_non_tracked_project_keys(tmp_path):
    cache = IssueCache(str(tmp_path / "issues.db"))
    cache._initialized = True
    cache._all_issues = {"OIT-100": _issue("OIT-100", "Tracked")}
    cache._issues = dict(cache._all_issues)

    cache.upsert_issue(_issue("MSD-101", "Moved away"))

    assert set(cache._all_issues) == {"OIT-100"}
    assert set(cache._issues) == {"OIT-100"}
