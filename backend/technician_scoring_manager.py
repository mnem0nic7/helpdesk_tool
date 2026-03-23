"""Background manager for recurring technician QA scoring."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from ai_background_worker import background_ai_worker
from ai_client import get_available_models, score_closed_ticket
from config import AUTO_TRIAGE_MODEL
from issue_cache import cache
from jira_client import JiraClient
from metrics import _is_open
from models import TechnicianScore
from site_context import SiteScope, get_scoped_issues, reset_current_site_scope, set_current_site_scope
from triage_store import TriageStore

logger = logging.getLogger(__name__)

_MANAGED_SCOPES: tuple[SiteScope, ...] = ("primary", "oasisdev")
_CACHE_WARMING_MESSAGE = "Issue cache is still warming. Wait a moment and try again."
_AUTO_TRIAGE_PRIORITY_MESSAGE = (
    "Processing new tickets takes priority over technician QA scoring. "
    "Technician QA waits until auto-prioritization and categorization are caught up."
)


def _cache_is_warming() -> bool:
    return bool(getattr(cache, "warming", False))


def _get_auto_triage_priority_state() -> dict[str, Any]:
    getter = getattr(cache, "auto_triage_status", None)
    if not callable(getter):
        return {
            "blocked": False,
            "message": "",
            "pending_count": 0,
            "running": False,
            "current_key": None,
        }

    try:
        status = getter()
    except Exception:
        logger.exception("Failed to read auto-triage priority status")
        return {
            "blocked": False,
            "message": "",
            "pending_count": 0,
            "running": False,
            "current_key": None,
        }

    pending_count = int(status.get("pending_count") or 0)
    running = bool(status.get("running"))
    current_key = str(status.get("current_key") or "").strip() or None
    blocked = running or pending_count > 0
    if not blocked:
        return {
            "blocked": False,
            "message": "",
            "pending_count": pending_count,
            "running": running,
            "current_key": current_key,
        }

    detail = _AUTO_TRIAGE_PRIORITY_MESSAGE
    if running and current_key:
        detail = (
            f"{_AUTO_TRIAGE_PRIORITY_MESSAGE} "
            f"Auto-triage is currently working on {current_key}."
        )
    elif pending_count > 0:
        detail = (
            f"{_AUTO_TRIAGE_PRIORITY_MESSAGE} "
            f"{pending_count} ticket(s) still need auto-triage."
        )
    return {
        "blocked": True,
        "message": detail,
        "pending_count": pending_count,
        "running": running,
        "current_key": current_key,
    }


def new_progress_state() -> dict[str, Any]:
    return {
        "running": False,
        "processed": 0,
        "total": 0,
        "current_key": None,
        "cancel": False,
        "last_started_at": None,
        "last_finished_at": None,
        "last_error": None,
        "trigger": "",
    }


class TechnicianScoringManager:
    """Owns manual and scheduled closed-ticket QA scoring runs."""

    def __init__(
        self,
        *,
        client: JiraClient,
        store: TriageStore,
        progress_by_scope: dict[SiteScope, dict[str, Any]],
        poll_interval_seconds: float,
    ) -> None:
        self._client = client
        self._store = store
        self._progress_by_scope = progress_by_scope
        self._poll_interval_seconds = max(1.0, float(poll_interval_seconds))
        self._bg_task: asyncio.Task[None] | None = None
        self._scope_locks: dict[SiteScope, asyncio.Lock] = {
            scope: asyncio.Lock() for scope in _MANAGED_SCOPES
        }

    def get_progress(self, scope: SiteScope) -> dict[str, Any]:
        return self._progress_by_scope.setdefault(scope, new_progress_state())

    def cancel_scope(self, scope: SiteScope) -> bool:
        progress = self.get_progress(scope)
        if not progress.get("running"):
            return False
        progress["cancel"] = True
        return True

    def get_priority_gate(self, scope: SiteScope) -> dict[str, Any]:
        if _cache_is_warming():
            return {
                "blocked": True,
                "message": _CACHE_WARMING_MESSAGE,
                "reason": "cache_warming",
                "pending_count": 0,
                "running": False,
                "current_key": None,
                "scope": scope,
            }

        auto_triage_state = _get_auto_triage_priority_state()
        if auto_triage_state["blocked"]:
            return {
                "blocked": True,
                "message": auto_triage_state["message"],
                "reason": "auto_triage_priority",
                "pending_count": auto_triage_state["pending_count"],
                "running": auto_triage_state["running"],
                "current_key": auto_triage_state["current_key"],
                "scope": scope,
            }

        return {
            "blocked": False,
            "message": "",
            "reason": "",
            "pending_count": auto_triage_state["pending_count"],
            "running": auto_triage_state["running"],
            "current_key": auto_triage_state["current_key"],
            "scope": scope,
        }

    async def start_worker(self) -> None:
        if self._bg_task and not self._bg_task.done():
            return
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

    def preview_scope_run(
        self,
        scope: SiteScope,
        *,
        reset: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        priority_gate = self.get_priority_gate(scope)
        if priority_gate["blocked"]:
            raise RuntimeError(str(priority_gate["message"]))
        model_id = self._select_model_id()
        if not model_id:
            raise RuntimeError(
                "No AI model available. Ensure Ollama is running and the configured local model is pulled before scoring technician responses."
            )
        issues_by_key, keys_to_process = self._build_scope_work(scope, reset=reset, limit=limit)
        return {
            "scope": scope,
            "model_id": model_id,
            "issues_by_key": issues_by_key,
            "keys_to_process": keys_to_process,
            "total_tickets": len(keys_to_process),
        }

    async def run_scope_once(
        self,
        scope: SiteScope,
        *,
        reset: bool = False,
        limit: int | None = None,
        trigger: str = "manual",
    ) -> dict[str, Any]:
        progress = self.get_progress(scope)
        lock = self._scope_locks[scope]
        if lock.locked():
            return {
                "started": False,
                "total_tickets": int(progress.get("total") or 0),
                "message": "Technician scoring run already in progress",
            }

        priority_gate = self.get_priority_gate(scope)
        if priority_gate["blocked"]:
            progress["last_error"] = str(priority_gate["message"])
            if trigger == "manual":
                raise RuntimeError(str(priority_gate["message"]))
            return {"started": False, "total_tickets": 0, "message": str(priority_gate["message"])}

        try:
            preview = self.preview_scope_run(scope, reset=reset, limit=limit)
        except RuntimeError as exc:
            progress["last_error"] = str(exc)
            if trigger == "manual":
                raise
            logger.warning("Skipping scheduled technician scoring for %s: %s", scope, exc)
            return {"started": False, "total_tickets": 0, "message": str(exc)}

        async with lock:
            started_at = self._utcnow().isoformat()
            progress.update(
                running=True,
                processed=0,
                total=preview["total_tickets"],
                current_key=None,
                cancel=False,
                last_started_at=started_at,
                last_finished_at=None,
                last_error=None,
                trigger=trigger,
            )

            loop = asyncio.get_running_loop()
            completed_count = 0

            try:
                for key in preview["keys_to_process"]:
                    if progress.get("cancel"):
                        logger.info(
                            "Technician scoring cancelled for %s after %d/%d",
                            scope,
                            completed_count,
                            len(preview["keys_to_process"]),
                        )
                        break

                    priority_gate = self.get_priority_gate(scope)
                    if priority_gate["blocked"]:
                        progress["last_error"] = str(priority_gate["message"])
                        logger.info(
                            "Pausing technician scoring for %s after %d/%d: %s",
                            scope,
                            completed_count,
                            len(preview["keys_to_process"]),
                            priority_gate["message"],
                        )
                        break

                    progress.update(processed=completed_count, current_key=key)
                    issue = preview["issues_by_key"].get(key)
                    if not issue or _is_open(issue):
                        completed_count += 1
                        progress["processed"] = completed_count
                        continue

                    try:
                        request_comments = await loop.run_in_executor(None, self._client.get_request_comments, key)
                    except Exception:
                        logger.exception("Failed to load request comments for %s during technician scoring", key)
                        request_comments = []

                    try:
                        async def _run_ai_scoring() -> TechnicianScore:
                            return await loop.run_in_executor(
                                None,
                                score_closed_ticket,
                                issue,
                                request_comments,
                                preview["model_id"],
                            )

                        score = await background_ai_worker.run_item(
                            lane="technician_scoring",
                            key=key,
                            work=_run_ai_scoring,
                        )
                        await loop.run_in_executor(None, self._store.save_technician_score, score)
                    except Exception:
                        logger.exception("Failed to score closed ticket %s", key)

                    completed_count += 1
                    progress["processed"] = completed_count
            except Exception as exc:
                logger.exception("Closed-ticket technician scoring failed for %s", scope)
                progress["last_error"] = str(exc)
            finally:
                progress.update(
                    running=False,
                    processed=completed_count,
                    current_key=None,
                    cancel=False,
                    last_finished_at=self._utcnow().isoformat(),
                )

        return {"started": True, "total_tickets": preview["total_tickets"]}

    async def _background_loop(self) -> None:
        while True:
            try:
                for scope in _MANAGED_SCOPES:
                    await self.run_scope_once(scope, trigger="scheduled")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Technician scoring background loop failed")
            await asyncio.sleep(self._poll_interval_seconds)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _select_model_id() -> str | None:
        available = get_available_models()
        if not available:
            return None
        available_ids = {model.id for model in available}
        if AUTO_TRIAGE_MODEL in available_ids:
            return AUTO_TRIAGE_MODEL
        return available[0].id

    def _build_scope_work(
        self,
        scope: SiteScope,
        *,
        reset: bool = False,
        limit: int | None = None,
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        token = set_current_site_scope(scope)
        try:
            issues = get_scoped_issues()
        finally:
            reset_current_site_scope(token)

        issues_by_key = {issue.get("key", ""): issue for issue in issues if issue.get("key")}
        closed_keys = [key for key, issue in issues_by_key.items() if not _is_open(issue)]
        already_scored = self._store.get_technician_scored_keys()
        keys_to_process = closed_keys if reset else [key for key in closed_keys if key not in already_scored]

        if isinstance(limit, int) and limit > 0:
            keys_to_process = keys_to_process[:limit]

        return issues_by_key, keys_to_process
