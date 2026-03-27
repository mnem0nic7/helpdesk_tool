"""Blue-green runtime role control and shared leader lease management."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from config import (
    APP_RUNTIME_BLUEGREEN_ENABLED,
    APP_RUNTIME_COLOR,
    APP_RUNTIME_HEARTBEAT_SECONDS,
    APP_RUNTIME_LEASE_SECONDS,
    DATA_DIR,
)
from postgres_utils import connect_postgres, ensure_postgres_schema, postgres_enabled
from sqlite_utils import connect_sqlite

logger = logging.getLogger(__name__)

_DB_PATH = Path(DATA_DIR) / "runtime_state.db"
_LEASE_SINGLETON_ID = 1


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


@dataclass
class RuntimeState:
    color: str
    role: str
    desired_leader_color: str | None
    lease_owner_color: str | None
    lease_expires_at: str | None
    bluegreen_enabled: bool
    leader_ready: bool


class RuntimeRoleManager:
    """Coordinate leader/follower app roles for blue-green deploys."""

    def __init__(
        self,
        *,
        db_path: str | None = None,
        color: str | None = None,
        bluegreen_enabled: bool = APP_RUNTIME_BLUEGREEN_ENABLED,
        lease_seconds: int = APP_RUNTIME_LEASE_SECONDS,
        heartbeat_seconds: int = APP_RUNTIME_HEARTBEAT_SECONDS,
    ) -> None:
        self._db_path = db_path or str(_DB_PATH)
        self._use_postgres = postgres_enabled() and db_path is None
        self._color = (color or APP_RUNTIME_COLOR or "single").strip().lower() or "single"
        self._bluegreen_enabled = bool(bluegreen_enabled)
        self._lease_seconds = max(5, int(lease_seconds))
        self._heartbeat_seconds = max(1, int(heartbeat_seconds))
        self._role = "leader" if not self._bluegreen_enabled else "follower"
        self._leader_ready = not self._bluegreen_enabled
        self._desired_leader_color: str | None = None
        self._lease_owner_color: str | None = None
        self._lease_expires_at: str | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._start_leader_cb: Callable[[], Awaitable[None]] | None = None
        self._stop_leader_cb: Callable[[], Awaitable[None]] | None = None
        self._lock = asyncio.Lock()
        self._init_db()

    def _connect_sqlite(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _connect(self):
        if self._use_postgres:
            ensure_postgres_schema()
            return connect_postgres()
        return self._connect_sqlite()

    def _backfill_from_sqlite_if_needed(self) -> None:
        if not self._use_postgres:
            return
        sqlite_path = Path(self._db_path)
        if not sqlite_path.exists():
            return
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT desired_leader_color, lease_owner_color, lease_expires_at
                FROM runtime_leader_state
                WHERE singleton_id = %s
                """,
                (_LEASE_SINGLETON_ID,),
            ).fetchone()
            if row and any(str(row[column] or "").strip() for column in ("desired_leader_color", "lease_owner_color", "lease_expires_at")):
                return
        with self._connect_sqlite() as sqlite_conn:
            row = sqlite_conn.execute(
                """
                SELECT desired_leader_color, lease_owner_color, lease_expires_at
                FROM runtime_leader_state
                WHERE singleton_id = ?
                """,
                (_LEASE_SINGLETON_ID,),
            ).fetchone()
        if row is None:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_leader_state (
                    singleton_id, desired_leader_color, lease_owner_color, lease_expires_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    desired_leader_color = excluded.desired_leader_color,
                    lease_owner_color = excluded.lease_owner_color,
                    lease_expires_at = excluded.lease_expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    _LEASE_SINGLETON_ID,
                    str(row["desired_leader_color"] or ""),
                    str(row["lease_owner_color"] or ""),
                    str(row["lease_expires_at"] or ""),
                    _utcnow_iso(),
                ),
            )

    def _init_db(self) -> None:
        if self._use_postgres:
            ensure_postgres_schema()
            self._backfill_from_sqlite_if_needed()
            return
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_leader_state (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    desired_leader_color TEXT NOT NULL DEFAULT '',
                    lease_owner_color TEXT NOT NULL DEFAULT '',
                    lease_expires_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                INSERT INTO runtime_leader_state (
                    singleton_id, desired_leader_color, lease_owner_color, lease_expires_at, updated_at
                ) VALUES (1, '', '', '', ?)
                ON CONFLICT(singleton_id) DO NOTHING
                """,
                (_utcnow_iso(),),
            )

    def _read_store(self) -> tuple[str | None, str | None, str | None]:
        with self._connect() as conn:
            if self._use_postgres:
                row = conn.execute(
                    """
                    SELECT desired_leader_color, lease_owner_color, lease_expires_at
                    FROM runtime_leader_state
                    WHERE singleton_id = %s
                    """,
                    (_LEASE_SINGLETON_ID,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT desired_leader_color, lease_owner_color, lease_expires_at
                    FROM runtime_leader_state
                    WHERE singleton_id = ?
                    """,
                    (_LEASE_SINGLETON_ID,),
                ).fetchone()
        if row is None:
            return None, None, None
        desired = str(row["desired_leader_color"] or "").strip().lower() or None
        owner = str(row["lease_owner_color"] or "").strip().lower() or None
        expires_at = str(row["lease_expires_at"] or "").strip() or None
        return desired, owner, expires_at

    def _claim_lease_sync(self, *, set_desired_to_self: bool = False, force_takeover: bool = False) -> bool:
        now = _utcnow()
        expires_at = (now + timedelta(seconds=self._lease_seconds)).isoformat()
        with self._connect() as conn:
            if self._use_postgres:
                row = conn.execute(
                    """
                    SELECT desired_leader_color, lease_owner_color, lease_expires_at
                    FROM runtime_leader_state
                    WHERE singleton_id = %s
                    """,
                    (_LEASE_SINGLETON_ID,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT desired_leader_color, lease_owner_color, lease_expires_at
                    FROM runtime_leader_state
                    WHERE singleton_id = ?
                    """,
                    (_LEASE_SINGLETON_ID,),
                ).fetchone()
            desired = str((row["desired_leader_color"] if row else "") or "").strip().lower()
            owner = str((row["lease_owner_color"] if row else "") or "").strip().lower()
            owner_expires_at = _parse_dt(str((row["lease_expires_at"] if row else "") or ""))
            lease_active = bool(owner and owner_expires_at and owner_expires_at > now)

            if force_takeover:
                desired = self._color
                owner = ""
                lease_active = False

            if set_desired_to_self or not desired:
                desired = self._color

            can_claim = (
                desired == self._color
                and (
                    not owner
                    or owner == self._color
                    or not lease_active
                )
            )
            if not can_claim:
                if self._use_postgres:
                    conn.execute(
                        """
                        UPDATE runtime_leader_state
                        SET desired_leader_color = %s, updated_at = %s
                        WHERE singleton_id = %s
                        """,
                        (desired, now.isoformat(), _LEASE_SINGLETON_ID),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE runtime_leader_state
                        SET desired_leader_color = ?, updated_at = ?
                        WHERE singleton_id = ?
                        """,
                        (desired, now.isoformat(), _LEASE_SINGLETON_ID),
                    )
                return False

            if self._use_postgres:
                conn.execute(
                    """
                    UPDATE runtime_leader_state
                    SET desired_leader_color = %s,
                        lease_owner_color = %s,
                        lease_expires_at = %s,
                        updated_at = %s
                    WHERE singleton_id = %s
                    """,
                    (self._color, self._color, expires_at, now.isoformat(), _LEASE_SINGLETON_ID),
                )
            else:
                conn.execute(
                    """
                    UPDATE runtime_leader_state
                    SET desired_leader_color = ?,
                        lease_owner_color = ?,
                        lease_expires_at = ?,
                        updated_at = ?
                    WHERE singleton_id = ?
                    """,
                    (self._color, self._color, expires_at, now.isoformat(), _LEASE_SINGLETON_ID),
                )
        return True

    def _release_lease_sync(self) -> None:
        with self._connect() as conn:
            if self._use_postgres:
                conn.execute(
                    """
                    UPDATE runtime_leader_state
                    SET lease_owner_color = '',
                        lease_expires_at = '',
                        updated_at = %s
                    WHERE singleton_id = %s AND lease_owner_color = %s
                    """,
                    (_utcnow_iso(), _LEASE_SINGLETON_ID, self._color),
                )
            else:
                conn.execute(
                    """
                    UPDATE runtime_leader_state
                    SET lease_owner_color = '',
                        lease_expires_at = '',
                        updated_at = ?
                    WHERE singleton_id = ? AND lease_owner_color = ?
                    """,
                    (_utcnow_iso(), _LEASE_SINGLETON_ID, self._color),
                )

    def _set_desired_leader_sync(self, color: str | None, *, clear_lease: bool = False) -> None:
        normalized = str(color or "").strip().lower()
        with self._connect() as conn:
            if clear_lease:
                if self._use_postgres:
                    conn.execute(
                        """
                        UPDATE runtime_leader_state
                        SET desired_leader_color = %s,
                            lease_owner_color = '',
                            lease_expires_at = '',
                            updated_at = %s
                        WHERE singleton_id = %s
                        """,
                        (normalized, _utcnow_iso(), _LEASE_SINGLETON_ID),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE runtime_leader_state
                        SET desired_leader_color = ?,
                            lease_owner_color = '',
                            lease_expires_at = '',
                            updated_at = ?
                        WHERE singleton_id = ?
                        """,
                        (normalized, _utcnow_iso(), _LEASE_SINGLETON_ID),
                    )
            else:
                if self._use_postgres:
                    conn.execute(
                        """
                        UPDATE runtime_leader_state
                        SET desired_leader_color = %s,
                            updated_at = %s
                        WHERE singleton_id = %s
                        """,
                        (normalized, _utcnow_iso(), _LEASE_SINGLETON_ID),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE runtime_leader_state
                        SET desired_leader_color = ?,
                            updated_at = ?
                        WHERE singleton_id = ?
                        """,
                        (normalized, _utcnow_iso(), _LEASE_SINGLETON_ID),
                    )

    async def bootstrap(self) -> RuntimeState:
        if not self._bluegreen_enabled:
            self._role = "leader"
            self._leader_ready = True
            self._desired_leader_color = self._color
            self._lease_owner_color = self._color
            self._lease_expires_at = None
            return self.status()

        desired, owner, expires_at = await asyncio.to_thread(self._read_store)
        if desired == self._color or (not desired and not owner):
            claimed = await asyncio.to_thread(self._claim_lease_sync, set_desired_to_self=True)
            desired, owner, expires_at = await asyncio.to_thread(self._read_store)
            if claimed:
                self._role = "leader"
                self._leader_ready = True
        self._desired_leader_color = desired
        self._lease_owner_color = owner
        self._lease_expires_at = expires_at
        return self.status()

    async def start(
        self,
        *,
        start_leader_cb: Callable[[], Awaitable[None]],
        stop_leader_cb: Callable[[], Awaitable[None]],
    ) -> None:
        self._start_leader_cb = start_leader_cb
        self._stop_leader_cb = stop_leader_cb
        if not self._bluegreen_enabled:
            return
        if self._monitor_task and not self._monitor_task.done():
            return
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        task = self._monitor_task
        self._monitor_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._bluegreen_enabled and self._role == "leader":
            await asyncio.to_thread(self._release_lease_sync)

    async def promote(self) -> RuntimeState:
        if not self._bluegreen_enabled:
            return self.status()
        await self.request_promotion()
        deadline = asyncio.get_running_loop().time() + max(10, self._lease_seconds)
        while asyncio.get_running_loop().time() < deadline:
            await self._reconcile(force=True)
            if self._role == "leader":
                return self.status()
            await asyncio.sleep(0.25)
        raise TimeoutError(f"Timed out promoting runtime color '{self._color}' to leader")

    async def request_promotion(self) -> RuntimeState:
        if not self._bluegreen_enabled:
            return self.status()
        await asyncio.to_thread(self._set_desired_leader_sync, self._color, clear_lease=False)
        await self._reconcile(force=True)
        return self.status()

    async def demote(self) -> RuntimeState:
        if not self._bluegreen_enabled:
            return self.status()
        desired, _, _ = await asyncio.to_thread(self._read_store)
        if desired == self._color:
            raise RuntimeError("Cannot demote the desired leader color without promoting another color first")
        await self._reconcile(force=True)
        return self.status()

    async def _monitor_loop(self) -> None:
        while True:
            try:
                await self._reconcile(force=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Runtime role monitor failed")
            await asyncio.sleep(self._heartbeat_seconds)

    async def _reconcile(self, *, force: bool) -> None:
        async with self._lock:
            desired, owner, expires_at = await asyncio.to_thread(self._read_store)
            self._desired_leader_color = desired
            self._lease_owner_color = owner
            self._lease_expires_at = expires_at

            if not self._bluegreen_enabled:
                if self._role != "leader":
                    self._role = "leader"
                    self._leader_ready = True
                return

            if desired == self._color:
                claimed = await asyncio.to_thread(self._claim_lease_sync)
                if claimed:
                    _, owner, expires_at = await asyncio.to_thread(self._read_store)
                    self._lease_owner_color = owner
                    self._lease_expires_at = expires_at
                    if self._role != "leader":
                        logger.info("Runtime role: promoting %s to leader", self._color)
                        if self._start_leader_cb is not None:
                            await self._start_leader_cb()
                        self._role = "leader"
                    self._leader_ready = True
                elif self._role == "leader":
                    logger.warning("Runtime role: %s lost leader lease; demoting to follower", self._color)
                    if self._stop_leader_cb is not None:
                        await self._stop_leader_cb()
                    self._role = "follower"
                    self._leader_ready = False
                return

            if self._role == "leader":
                logger.info("Runtime role: demoting %s to follower", self._color)
                if self._stop_leader_cb is not None:
                    await self._stop_leader_cb()
                await asyncio.to_thread(self._release_lease_sync)
                self._role = "follower"
                self._leader_ready = False
            elif force and owner == self._color:
                await asyncio.to_thread(self._release_lease_sync)
                self._lease_owner_color = None
                self._lease_expires_at = None

    def status(self) -> RuntimeState:
        return RuntimeState(
            color=self._color,
            role=self._role,
            desired_leader_color=self._desired_leader_color,
            lease_owner_color=self._lease_owner_color,
            lease_expires_at=self._lease_expires_at,
            bluegreen_enabled=self._bluegreen_enabled,
            leader_ready=self._leader_ready,
        )


runtime_role_manager = RuntimeRoleManager()
