# backend/tests/test_retention_directory_cache.py
from __future__ import annotations

from unittest.mock import MagicMock


def _cache_with_stores():
    from retention_directory_cache import RetentionDirectoryCache
    connection_store = MagicMock()
    connection_store.get_valid_token.return_value = "token"
    graph_module = MagicMock()
    cache = RetentionDirectoryCache(connection_store=connection_store, graph_module=graph_module)
    return cache, connection_store, graph_module


def test_channels_by_team_snapshot_starts_empty():
    cache, _connection_store, _graph_module = _cache_with_stores()
    assert cache.channels_by_team_snapshot() == {}
    assert cache.last_refreshed_at is None


def test_refresh_now_populates_the_snapshot_from_teams_and_batched_channels():
    cache, _connection_store, graph_module = _cache_with_stores()
    graph_module.list_teams.return_value = [{"id": "t1", "name": "Eng"}, {"id": "t2", "name": "Sales"}]
    graph_module.list_channels_for_teams_batch.return_value = {
        "t1": [{"id": "c1", "name": "General"}],
        "t2": [{"id": "c2", "name": "General"}],
    }

    cache.refresh_now()

    graph_module.list_channels_for_teams_batch.assert_called_once_with("token", ["t1", "t2"])
    assert cache.channels_by_team_snapshot() == {
        "t1": [{"id": "c1", "name": "General"}],
        "t2": [{"id": "c2", "name": "General"}],
    }
    assert cache.last_refreshed_at is not None


def test_refresh_now_propagates_a_disconnected_token_error():
    from retention_graph_connection import RetentionGraphConnectionError

    cache, connection_store, graph_module = _cache_with_stores()
    connection_store.get_valid_token.side_effect = RetentionGraphConnectionError("disconnected")

    try:
        cache.refresh_now()
        assert False, "expected RetentionGraphConnectionError"
    except RetentionGraphConnectionError:
        pass
    graph_module.list_teams.assert_not_called()
    assert cache.channels_by_team_snapshot() == {}


async def test_run_loop_survives_a_disconnected_connection_and_keeps_looping(monkeypatch):
    import asyncio
    from retention_graph_connection import RetentionGraphConnectionError

    cache, connection_store, _graph_module = _cache_with_stores()
    connection_store.get_valid_token.side_effect = RetentionGraphConnectionError("disconnected")

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    try:
        await cache._run_loop()
    except asyncio.CancelledError:
        pass

    assert sleep_calls  # the loop reached the sleep step instead of crashing out
