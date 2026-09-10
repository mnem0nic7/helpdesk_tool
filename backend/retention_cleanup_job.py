"""Hourly leader-only background job enforcing per-channel Teams message
retention: deletes aged messages/replies (delegated Graph call) and their
attachments (SharePoint driveItem) for every 'active' policy. Also exposes
compute_preview(), reused synchronously by the API's dry-run step so preview
and enforcement can never drift on selection logic."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import retention_graph_client as _graph_module
from retention_graph_connection import retention_graph_connection
from retention_policy_store import retention_policy_store

logger = logging.getLogger(__name__)


class RetentionCleanupJob:
    def __init__(self, *, connection_store: Any = None, policy_store: Any = None, graph_module: Any = None) -> None:
        self._connection_store = connection_store or retention_graph_connection
        self._policy_store = policy_store or retention_policy_store
        self._graph = graph_module or _graph_module
        self._bg_task: asyncio.Task | None = None

    async def _collect_items(self, policy: dict, token: str, cutoff: datetime) -> list[tuple[dict, bool]]:
        # Ordering matters: each message's aged replies are appended BEFORE the
        # message itself so replies are always deleted while their parent still
        # exists. Deleting a reply whose root message is already gone is fragile
        # (Graph can reject the reply-scoped path), so never flatten this back to
        # "all roots first, then all replies".
        loop = asyncio.get_event_loop()
        messages = await loop.run_in_executor(
            None, lambda: self._graph.list_messages_older_than(token, policy["team_id"], policy["channel_id"], cutoff),
        )
        items: list[tuple[dict, bool]] = []
        for message in messages:
            replies = await loop.run_in_executor(
                None,
                lambda m=message: self._graph.list_replies_older_than(
                    token, policy["team_id"], policy["channel_id"], m["id"], cutoff,
                ),
            )
            items.extend((r, True) for r in replies)
            items.append((message, False))
        return items

    async def compute_preview(self, policy_id: str) -> dict[str, Any]:
        policy = self._policy_store.get_policy(policy_id)
        if not policy:
            raise ValueError(f"Unknown policy {policy_id}")
        token = self._connection_store.get_valid_token()
        cutoff = datetime.now(timezone.utc) - timedelta(days=policy["retention_days"])
        items = await self._collect_items(policy, token, cutoff)
        all_items = [item for item, _is_reply in items]
        attachments_count = sum(len(item["attachments"]) for item in all_items)
        oldest = min((item["created_at"] for item in all_items), default=None)
        return {
            "messages_count": len(all_items),
            "attachments_count": attachments_count,
            "oldest_message_at": oldest,
        }

    async def _delete_item(self, item: dict, is_reply: bool, policy: dict, token: str) -> None:
        loop = asyncio.get_event_loop()
        if is_reply:
            await loop.run_in_executor(
                None,
                lambda: self._graph.delete_reply(
                    token, policy["team_id"], policy["channel_id"], item["parent_id"], item["id"],
                ),
            )
        else:
            await loop.run_in_executor(
                None, lambda: self._graph.delete_message(token, policy["team_id"], policy["channel_id"], item["id"]),
            )

    async def _delete_attachments(
        self, item: dict, policy: dict, token: str, run_id: str, site_id: str | None,
    ) -> tuple[int, bool, str | None]:
        # site_id is constant for the whole run (it's derived from policy["team_id"]
        # alone), so it's resolved at most once per run and threaded back to the
        # caller for reuse across every remaining message/attachment instead of being
        # re-resolved per attachment — avoids multiplying Graph calls (and 429
        # exposure) for channels with many aged attachments.
        loop = asyncio.get_event_loop()
        deleted = 0
        had_failure = False
        for attachment in item["attachments"]:
            try:
                if site_id is None:
                    site_id = await loop.run_in_executor(
                        None, lambda: self._graph.resolve_team_site_id(token, policy["team_id"]),
                    )
                # attachment["id"] is the Teams chatMessageAttachment id, which is NOT a
                # SharePoint driveItem id. Deleting it directly would target a
                # non-existent resource, and delete_drive_item tolerates 404s, so the
                # audit row would claim "deleted" while nothing was touched. Resolve the
                # attachment's sharing contentUrl to the real driveItem first. This call
                # is deliberately inside the same try/except as the delete, so a
                # resolution failure is recorded as status="failed" rather than swallowed.
                real_item_id = await loop.run_in_executor(
                    None, lambda: self._graph.resolve_drive_item_from_content_url(token, attachment["content_url"]),
                )
                await loop.run_in_executor(
                    None, lambda: self._graph.delete_drive_item(token, site_id, real_item_id),
                )
                self._policy_store.record_deletion(
                    run_id=run_id, item_type="attachment", item_id=real_item_id,
                    sender_or_author=item["sender_or_author"], original_created_at=item["created_at"], status="deleted",
                )
                deleted += 1
            except Exception as exc:
                # On failure the driveItem id may never have been resolved, so fall back
                # to the Teams attachment id — it still identifies the item for audit.
                had_failure = True
                self._policy_store.record_deletion(
                    run_id=run_id, item_type="attachment", item_id=attachment["id"],
                    sender_or_author=item["sender_or_author"], original_created_at=item["created_at"],
                    status="failed", error=str(exc),
                )
        return deleted, had_failure, site_id

    async def _run_policy(self, policy: dict, token: str) -> None:
        run_id = self._policy_store.start_run(policy["id"])
        cutoff = datetime.now(timezone.utc) - timedelta(days=policy["retention_days"])
        messages_deleted = 0
        attachments_deleted = 0
        had_failure = False
        site_id: str | None = None

        try:
            items = await self._collect_items(policy, token, cutoff)
        except Exception as exc:
            logger.exception("Retention job: failed to list content for policy %s", policy["id"])
            self._policy_store.finish_run(run_id, outcome="failed", messages_deleted=0, attachments_deleted=0, error=str(exc))
            return

        for item, is_reply in items:
            try:
                await self._delete_item(item, is_reply, policy, token)
            except Exception as exc:
                had_failure = True
                self._policy_store.record_deletion(
                    run_id=run_id, item_type="message", item_id=item["id"],
                    sender_or_author=item["sender_or_author"], original_created_at=item["created_at"],
                    status="failed", error=str(exc),
                )
                continue
            self._policy_store.record_deletion(
                run_id=run_id, item_type="message", item_id=item["id"],
                sender_or_author=item["sender_or_author"], original_created_at=item["created_at"], status="deleted",
            )
            messages_deleted += 1
            deleted, attachment_failure, site_id = await self._delete_attachments(item, policy, token, run_id, site_id)
            attachments_deleted += deleted
            had_failure = had_failure or attachment_failure

        outcome = "partial" if had_failure else "ok"
        self._policy_store.finish_run(
            run_id, outcome=outcome, messages_deleted=messages_deleted, attachments_deleted=attachments_deleted,
        )

    def _already_ran_this_hour(self, policy_id: str) -> bool:
        """Persisted per-policy hour gate, reusing the retention_runs table.

        Without this, a leader re-election or blue/green cutover restarts the job
        and immediately re-fires a full deletion pass for every active policy,
        because _run_loop's only pacing is an in-process sleep(3600). The most
        recent run row's started_at is the durable record of "this policy already
        ran in this UTC clock hour".
        """
        runs, _total = self._policy_store.list_runs(policy_id=policy_id, limit=1, offset=0)
        if not runs:
            return False
        started_at = str(runs[0].get("started_at") or "")
        try:
            started = datetime.fromisoformat(started_at)
        except ValueError:
            return False
        now = datetime.now(timezone.utc)
        return (started.year, started.month, started.day, started.hour) == (now.year, now.month, now.day, now.hour)

    async def run_cycle(self) -> None:
        policies = self._policy_store.list_active_policies()
        if not policies:
            return
        try:
            token = self._connection_store.get_valid_token()
        except Exception as exc:
            # get_valid_token() is documented to raise RetentionGraphConnectionError on a
            # known-bad connection, but the underlying refresh call in
            # retention_graph_connection.py is a raw `requests.post(...)` with no
            # try/except of its own, so a transient network error (ConnectionError,
            # Timeout, ...) can also escape as a plain exception. Treat any failure to
            # obtain a token the same way: fail every active policy closed for this
            # cycle rather than letting it bubble up and silently skip writing any run
            # rows at all.
            logger.warning("Retention job: no valid Graph token, skipping cycle: %s", exc)
            for policy in policies:
                run_id = self._policy_store.start_run(policy["id"])
                self._policy_store.finish_run(
                    run_id, outcome="failed", messages_deleted=0, attachments_deleted=0, error="token_invalid",
                )
            return
        for policy in policies:
            if self._already_ran_this_hour(policy["id"]):
                continue
            await self._run_policy(policy, token)

    def start_background_runner(self) -> None:
        loop = asyncio.get_event_loop()
        self._bg_task = loop.create_task(self._run_loop())

    def stop_background_runner(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_cycle()
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Retention cleanup job loop error")
                await asyncio.sleep(3600)


retention_cleanup_job = RetentionCleanupJob()
