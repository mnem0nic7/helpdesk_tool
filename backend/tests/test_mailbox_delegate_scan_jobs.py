from __future__ import annotations

from mailbox_delegate_scan_jobs import MailboxDelegateScanJobManager


class FakeMailboxProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_delegate_mailboxes_for_user(self, user: str, *, progress_callback=None):
        self.calls.append(user)
        if progress_callback:
            progress_callback(
                {
                    "phase": "resolving_user",
                    "progress_current": 1,
                    "progress_total": 4,
                    "progress_message": "Resolving the requested user identity",
                }
            )
            progress_callback(
                {
                    "phase": "scanning_send_on_behalf",
                    "progress_current": 2,
                    "progress_total": 4,
                    "progress_message": "Scanned 15 Exchange mailboxes for Send on behalf",
                    "scanned_mailbox_count": 15,
                }
            )
        return {
            "user": user,
            "display_name": "Delegate User",
            "principal_name": user,
            "primary_address": user,
            "provider_enabled": True,
            "supported_permission_types": ["send_on_behalf", "send_as", "full_access"],
            "permission_counts": {
                "send_on_behalf": 1,
                "send_as": 1,
                "full_access": 1,
            },
            "note": "Scanned 15 mailboxes for Send on behalf, Send As, and Full Access.",
            "mailbox_count": 1,
            "scanned_mailbox_count": 15,
            "mailboxes": [
                {
                    "identity": "shared@example.com",
                    "display_name": "Shared Mailbox",
                    "principal_name": "shared@example.com",
                    "primary_address": "shared@example.com",
                    "permission_types": ["send_on_behalf", "send_as", "full_access"],
                }
            ],
        }


def test_mailbox_delegate_scan_job_manager_processes_and_persists_results(tmp_path):
    provider = FakeMailboxProvider()
    manager = MailboxDelegateScanJobManager(
        db_path=str(tmp_path / "mailbox_delegate_jobs.db"),
        provider_factory=lambda: provider,
    )
    job = manager.create_job(
        site_scope="primary",
        user="delegate@example.com",
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )

    claimed = manager._claim_next_job()
    assert claimed is not None
    assert claimed["job_id"] == job["job_id"]

    manager._process_job(job["job_id"])
    latest = manager.get_job(job["job_id"], include_events=True)

    assert latest is not None
    assert latest["status"] == "completed"
    assert latest["phase"] == "completed"
    assert latest["mailbox_count"] == 1
    assert latest["scanned_mailbox_count"] == 15
    assert latest["mailboxes"][0]["primary_address"] == "shared@example.com"
    assert any("Queued delegate mailbox scan" in event["message"] for event in latest["events"])
    assert any("Scanned 15 Exchange mailboxes" in event["message"] for event in latest["events"])
    assert provider.calls == ["delegate@example.com"]


def test_mailbox_delegate_scan_job_manager_lists_jobs_per_requesting_user(tmp_path):
    manager = MailboxDelegateScanJobManager(
        db_path=str(tmp_path / "mailbox_delegate_jobs.db"),
        provider_factory=lambda: FakeMailboxProvider(),
    )
    job_one = manager.create_job(
        site_scope="primary",
        user="delegate-one@example.com",
        requested_by_email="tech@example.com",
        requested_by_name="Tech User",
    )
    manager.create_job(
        site_scope="primary",
        user="delegate-two@example.com",
        requested_by_email="other@example.com",
        requested_by_name="Other User",
    )

    tech_jobs = manager.list_jobs_for_user("tech@example.com")
    other_jobs = manager.list_jobs_for_user("other@example.com")

    assert len(tech_jobs) == 1
    assert tech_jobs[0]["user"] == "delegate-one@example.com"
    assert len(other_jobs) == 1
    assert other_jobs[0]["user"] == "delegate-two@example.com"
    assert manager.job_belongs_to(job_one["job_id"], "tech@example.com") is True
    assert manager.job_belongs_to(job_one["job_id"], "other@example.com") is False
