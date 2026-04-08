"""Central scheduler for background AI work.

This scheduler owns background AI prioritization:
1. New-ticket auto-triage always runs first.
2. Closed-ticket technician QA runs only when triage is caught up.
3. After every single AI item completes, the scheduler re-checks triage
   before choosing the next item.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from site_context import SiteScope

logger = logging.getLogger(__name__)

_MANAGED_SCOPES: tuple[SiteScope, ...] = ("primary", "oasisdev")


class _IssueCacheProtocol(Protocol):
    @property
    def warming(self) -> bool: ...

    def auto_triage_status(self, scope: SiteScope | None = None) -> dict[str, Any]: ...

    async def _auto_triage_new_tickets(
        self,
        new_keys: list[str],
        progress: dict[str, Any] | None = None,
        model_id: str | None = None,
    ) -> None: ...


class _TechnicianScoringManagerProtocol(Protocol):
    async def run_scope_once(
        self,
        scope: SiteScope,
        *,
        reset: bool = False,
        limit: int | None = None,
        trigger: str = "manual",
    ) -> dict[str, Any]: ...

    def preview_scope_run(
        self,
        scope: SiteScope,
        *,
        reset: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]: ...

    def get_progress(self, scope: SiteScope) -> dict[str, Any]: ...


class AIWorkScheduler:
    """Single background scheduler for auto-triage and technician QA."""

    def __init__(
        self,
        *,
        cache: _IssueCacheProtocol,
        technician_scoring_manager: _TechnicianScoringManagerProtocol,
        qa_poll_interval_seconds: float,
        idle_interval_seconds: float = 5.0,
        defer_interval_seconds: float = 2.0,
    ) -> None:
        self._cache = cache
        self._technician_scoring_manager = technician_scoring_manager
        self._qa_poll_interval_seconds = max(1.0, float(qa_poll_interval_seconds))
        self._idle_interval_seconds = max(0.25, float(idle_interval_seconds))
        self._defer_interval_seconds = max(0.25, float(defer_interval_seconds))
        self._bg_task: asyncio.Task[None] | None = None
        self._next_qa_sweep_at = self._utcnow()

    async def start_worker(self) -> None:
        if self._bg_task and not self._bg_task.done():
            return
        self._next_qa_sweep_at = self._utcnow()
        self._bg_task = asyncio.get_running_loop().create_task(self._background_loop())

    async def stop_worker(self) -> None:
        if not self._bg_task:
            return
        self._bg_task.cancel()
        try:
            await self._bg_task
        except asyncio.CancelledError:
            pass
        self._bg_task = None

    async def _background_loop(self) -> None:
        while True:
            try:
                outcome = await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AI background scheduler loop failed")
                outcome = "deferred"

            if outcome == "processed":
                # Yield after each completed item so API requests are not starved
                # when the scheduler is working through a long backlog.
                await asyncio.sleep(0)
                continue
            if outcome == "deferred":
                await asyncio.sleep(self._defer_interval_seconds)
                continue
            await asyncio.sleep(self._idle_interval_seconds)

    async def _run_once(self) -> str:
        if bool(getattr(self._cache, "warming", False)):
            return "deferred"

        triage_plan = await asyncio.get_running_loop().run_in_executor(
            None,
            self._next_auto_triage_plan,
        )
        if triage_plan["action"] == "deferred":
            return "deferred"
        if triage_plan["action"] == "process":
            keys = [str(k) for k in triage_plan["keys"]]
            scope = str(triage_plan["scope"])
            logger.info("AI scheduler: processing auto-triage for %s (%s)", ", ".join(keys), scope)
            await self._cache._auto_triage_new_tickets(keys)
            return "processed"

        if not self._qa_sweep_due():
            return "idle"

        qa_outcome = await self._run_next_qa_item()
        if qa_outcome == "idle":
            self._schedule_next_qa_sweep()
        return qa_outcome

    def _next_auto_triage_plan(self) -> dict[str, Any]:
        try:
            overall_status = self._cache.auto_triage_status()
        except Exception:
            logger.exception("AI scheduler: failed to read global auto-triage status")
            return {"action": "deferred"}

        if bool(overall_status.get("running")):
            return {"action": "deferred"}

        for scope in _MANAGED_SCOPES:
            try:
                scoped_status = self._cache.auto_triage_status(scope)
            except Exception:
                logger.exception("AI scheduler: failed to read auto-triage status for %s", scope)
                return {"action": "deferred"}

            pending_keys = scoped_status.get("pending_keys") or []
            if pending_keys:
                from ai_client import _check_secondary_healthy
                from config import OLLAMA_SECONDARY_ENABLED
                batch_size = 2 if (OLLAMA_SECONDARY_ENABLED and _check_secondary_healthy()) else 1
                return {
                    "action": "process",
                    "scope": scope,
                    "keys": [str(k) for k in pending_keys[:batch_size]],
                }

        return {"action": "none"}

    async def _run_next_qa_item(self) -> str:
        if self._any_qa_scope_running():
            return "deferred"

        for scope in _MANAGED_SCOPES:
            try:
                preview = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda scope=scope: self._technician_scoring_manager.preview_scope_run(scope, limit=1),
                )
            except RuntimeError as exc:
                message = str(exc)
                if "Processing new tickets takes priority" in message or "warming" in message.lower():
                    return "deferred"
                logger.warning("AI scheduler: skipping technician QA for %s: %s", scope, exc)
                continue
            except Exception:
                logger.exception("AI scheduler: failed to preview technician QA for %s", scope)
                continue

            if int(preview.get("total_tickets") or 0) <= 0:
                continue

            logger.info("AI scheduler: processing technician QA for %s", scope)
            await self._technician_scoring_manager.run_scope_once(
                scope,
                limit=1,
                trigger="scheduled",
            )
            return "processed"

        return "idle"

    def _any_qa_scope_running(self) -> bool:
        for scope in _MANAGED_SCOPES:
            progress = self._technician_scoring_manager.get_progress(scope)
            if bool(progress.get("running")):
                return True
        return False

    def _qa_sweep_due(self) -> bool:
        return self._utcnow() >= self._next_qa_sweep_at

    def _schedule_next_qa_sweep(self) -> None:
        self._next_qa_sweep_at = self._utcnow() + timedelta(seconds=self._qa_poll_interval_seconds)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)
