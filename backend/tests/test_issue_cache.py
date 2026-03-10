from __future__ import annotations

from issue_cache import IssueCache


def _issue(key: str, summary: str, *, labels: list[str] | None = None) -> dict:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "labels": labels or [],
            "status": {"name": "Open", "statusCategory": {"name": "To Do"}},
            "created": "2026-03-09T00:00:00+00:00",
            "updated": "2026-03-09T00:00:00+00:00",
        },
    }


class _FakeClient:
    def __init__(self, updated_issues: list[dict]) -> None:
        self.updated_issues = updated_issues
        self.enriched_batches: list[list[str]] = []

    def search_all(self, jql: str, progress_callback=None) -> list[dict]:
        return list(self.updated_issues)

    def enrich_request_types(self, issues: list[dict], existing_cache=None) -> None:
        self.enriched_batches.append([issue["key"] for issue in issues])


def _build_cache(tmp_path, updated_issues: list[dict]) -> IssueCache:
    cache = IssueCache(str(tmp_path / "issues.db"))
    cache._client = _FakeClient(updated_issues)
    cache._initialized = True
    cache._auto_triage_seen = set()

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


def test_background_incremental_refresh_skips_oasisdev_updates(tmp_path):
    updated_issues = [
        _issue("OIT-100", "Primary new"),
        _issue("OIT-500", "Oasis new", labels=["oasisdev"]),
    ]
    cache = _build_cache(tmp_path, updated_issues)

    untriaged = cache._incremental_refresh(include_excluded_updates=False)

    assert cache._all_issues["OIT-100"]["fields"]["summary"] == "Primary new"
    assert cache._all_issues["OIT-500"]["fields"]["summary"] == "Oasis old"
    assert untriaged == ["OIT-100"]
    assert cache._client.enriched_batches == [["OIT-100"]]


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
