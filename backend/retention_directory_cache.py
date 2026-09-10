"""Leader-only periodic cache of every team's channel names.

Exists only to make the Teams & Channels page's top-level search fast. Graph has no
endpoint to search channel names across every team, so matching a channel there means
fanning out to every team's channel list (see retention_graph_client.list_channels_for_teams_batch).
Doing that fan-out live on every keystroke took 30-60+ seconds against a 300+ team
tenant, so this cache does the fan-out on a background interval instead and search
reads the cached snapshot. Results can lag actual Teams state by up to
_REFRESH_INTERVAL_SECONDS — a deliberate tradeoff for a usable search box over an
always-fresh one.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import retention_graph_client as _graph_module
from retention_graph_connection import RetentionGraphConnectionError, retention_graph_connection

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL_SECONDS = 900  # 15 minutes


class RetentionDirectoryCache:
    def __init__(self, *, connection_store: Any = None, graph_module: Any = None) -> None:
        self._connection_store = connection_store or retention_graph_connection
        self._graph = graph_module or _graph_module
        self._channels_by_team: dict[str, list[dict[str, Any]]] = {}
        self._last_refreshed_at: float | None = None
        self._bg_task: asyncio.Task | None = None

    @property
    def last_refreshed_at(self) -> float | None:
        return self._last_refreshed_at

    def channels_by_team_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        # Callers only ever read this to filter; the background loop replaces the whole
        # dict reference on each refresh rather than mutating it in place, so a caller
        # never sees a half-updated snapshot.
        return self._channels_by_team

    def refresh_now(self) -> None:
        token = self._connection_store.get_valid_token()
        teams = self._graph.list_teams(token)
        team_ids = [t["id"] for t in teams]
        self._channels_by_team = self._graph.list_channels_for_teams_batch(token, team_ids)
        self._last_refreshed_at = time.time()
        logger.info("Retention directory cache refreshed: %d teams", len(self._channels_by_team))

    def start_background_runner(self) -> None:
        loop = asyncio.get_event_loop()
        self._bg_task = loop.create_task(self._run_loop())

    def stop_background_runner(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()

    async def _run_loop(self) -> None:
        while True:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.refresh_now)
            except asyncio.CancelledError:
                break
            except RetentionGraphConnectionError:
                # Not connected yet (or connection lost) is a normal, expected state
                # before/between setup — retry on the next interval without alarming logs.
                logger.info("Retention directory cache: no valid Graph connection, will retry")
            except Exception:
                logger.exception("Retention directory cache refresh failed")
            try:
                await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break


retention_directory_cache = RetentionDirectoryCache()
