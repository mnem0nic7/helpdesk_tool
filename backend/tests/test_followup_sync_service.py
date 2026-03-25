from __future__ import annotations

from followup_sync_service import FollowUpSyncService


class _FakeClient:
    def __init__(self) -> None:
        self.comments_by_key: dict[str, list[dict]] = {}
        self.group_members_by_name: dict[str, list[dict]] = {}

    def get_request_comments(self, key: str) -> list[dict]:
        return list(self.comments_by_key.get(key, []))

    def get_group_members(self, group_name: str) -> list[dict]:
        return list(self.group_members_by_name.get(group_name, []))


def test_reconcile_issue_writes_local_authoritative_followup_fields():
    client = _FakeClient()
    client.group_members_by_name = {
        "jira-servicemanagement-users-keyjira": [{"accountId": "agent-1"}],
        "MoveDocs Service Desk Agents": [],
    }
    client.comments_by_key["OIT-100"] = [
        {"public": True, "created": "2026-03-24T10:00:00+00:00", "author": {"accountId": "agent-1"}},
        {"public": True, "created": "2026-03-24T18:00:00+00:00", "author": {"accountId": "agent-1"}},
    ]
    service = FollowUpSyncService(client=client)  # type: ignore[arg-type]
    issue = {
        "key": "OIT-100",
        "fields": {
            "created": "2026-03-24T09:00:00+00:00",
            "updated": "2026-03-24T19:00:00+00:00",
            "resolutiondate": "2026-03-24T19:00:00+00:00",
            "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
        },
    }

    changed = service.reconcile_issue(issue, force=True)

    assert changed is True
    fields = issue["fields"]
    assert fields["_movedocs_followup_status"] == "Met"
    assert fields["_movedocs_followup_last_touch_at"] == "2026-03-24T18:00:00+00:00"
    assert fields["_movedocs_followup_touch_count"] == 2
    assert fields["_movedocs_followup_source"] == "public_agent_comments"
    assert fields["_movedocs_followup_synced_for_updated"] == "2026-03-24T19:00:00+00:00"


def test_reconcile_issues_skips_old_closed_tickets_without_force():
    client = _FakeClient()
    service = FollowUpSyncService(client=client)  # type: ignore[arg-type]
    issue = {
        "key": "OIT-101",
        "fields": {
            "created": "2025-01-01T09:00:00+00:00",
            "updated": "2025-01-02T09:00:00+00:00",
            "resolutiondate": "2025-01-02T09:00:00+00:00",
            "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
        },
    }

    changed = service.reconcile_issues([issue], recent_days=35)

    assert changed == 0
    assert "_movedocs_followup_status" not in issue["fields"]


def test_reconcile_issue_uses_cached_complete_comment_payload_without_jira_fetch():
    class _NoFetchClient(_FakeClient):
        def get_request_comments(self, key: str) -> list[dict]:  # pragma: no cover - should not be called
            raise AssertionError(f"Unexpected Jira fetch for {key}")

    client = _NoFetchClient()
    client.group_members_by_name = {
        "jira-servicemanagement-users-keyjira": [{"accountId": "agent-1"}],
        "MoveDocs Service Desk Agents": [],
    }
    service = FollowUpSyncService(client=client)  # type: ignore[arg-type]
    issue = {
        "key": "OIT-102",
        "fields": {
            "created": "2026-03-24T09:00:00+00:00",
            "updated": "2026-03-24T19:00:00+00:00",
            "resolutiondate": "2026-03-24T19:00:00+00:00",
            "status": {"name": "Resolved", "statusCategory": {"name": "Done"}},
            "comment": {
                "total": 2,
                "comments": [
                    {
                        "id": "1",
                        "created": "2026-03-24T10:00:00+00:00",
                        "jsdPublic": True,
                        "author": {"accountId": "agent-1"},
                    },
                    {
                        "id": "2",
                        "created": "2026-03-24T18:00:00+00:00",
                        "jsdPublic": True,
                        "author": {"accountId": "agent-1"},
                    },
                ],
            },
        },
    }

    changed = service.reconcile_issue(issue, force=True)

    assert changed is True
    assert issue["fields"]["_movedocs_followup_status"] == "Met"
    assert issue["fields"]["_movedocs_followup_touch_count"] == 2
