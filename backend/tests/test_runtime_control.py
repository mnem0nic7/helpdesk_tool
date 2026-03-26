from __future__ import annotations

import asyncio

import pytest

from runtime_control import RuntimeRoleManager


@pytest.mark.asyncio
async def test_runtime_role_manager_bootstraps_first_color_as_leader(tmp_path):
    manager = RuntimeRoleManager(
        db_path=str(tmp_path / "runtime_state.db"),
        color="blue",
        bluegreen_enabled=True,
        lease_seconds=30,
        heartbeat_seconds=1,
    )

    state = await manager.bootstrap()

    assert state.role == "leader"
    assert state.color == "blue"
    assert state.desired_leader_color == "blue"
    assert state.lease_owner_color == "blue"


@pytest.mark.asyncio
async def test_runtime_role_manager_promote_hands_off_leadership_between_colors(tmp_path):
    db_path = str(tmp_path / "runtime_state.db")
    events: list[str] = []

    async def blue_start() -> None:
        events.append("blue-start")

    async def blue_stop() -> None:
        events.append("blue-stop")

    async def green_start() -> None:
        events.append("green-start")

    async def green_stop() -> None:
        events.append("green-stop")

    blue = RuntimeRoleManager(
        db_path=db_path,
        color="blue",
        bluegreen_enabled=True,
        lease_seconds=10,
        heartbeat_seconds=1,
    )
    green = RuntimeRoleManager(
        db_path=db_path,
        color="green",
        bluegreen_enabled=True,
        lease_seconds=10,
        heartbeat_seconds=1,
    )

    blue_state = await blue.bootstrap()
    assert blue_state.role == "leader"
    await blue.start(start_leader_cb=blue_start, stop_leader_cb=blue_stop)

    green_state = await green.bootstrap()
    assert green_state.role == "follower"
    await green.start(start_leader_cb=green_start, stop_leader_cb=green_stop)

    requested = await green.request_promotion()
    assert requested.role == "follower"
    assert green.status().role == "follower"
    assert not (blue.status().role == "leader" and green.status().role == "leader")

    if blue.status().role == "leader":
        await blue.demote()

    promoted = await green.promote()
    assert promoted.role == "leader"

    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        if blue.status().role == "follower" and green.status().role == "leader":
            break
        await asyncio.sleep(0.1)

    assert green.status().role == "leader"
    assert blue.status().role == "follower"
    assert "green-start" in events
    assert "blue-stop" in events

    await blue.stop()
    await green.stop()
