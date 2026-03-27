"""Shared Redis state helpers with an in-memory fallback for tests."""

from __future__ import annotations

import json
import logging
import threading
from copy import deepcopy
from typing import Any

from config import REDIS_NAMESPACE, REDIS_URL

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover - optional dependency in local test envs
    redis_lib = None

logger = logging.getLogger(__name__)


class RedisStateStore:
    def __init__(self) -> None:
        self._client = None
        self._lock = threading.Lock()
        self._values: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}

    @property
    def configured(self) -> bool:
        return bool(REDIS_URL)

    @property
    def namespace(self) -> str:
        return REDIS_NAMESPACE

    @property
    def using_memory_fallback(self) -> bool:
        return self._get_client() is None

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    def _get_client(self):
        if not self.configured or redis_lib is None:
            return None
        if self._client is None:
            self._client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        return self._client

    def ping(self) -> bool:
        client = self._get_client()
        if client is None:
            return not self.configured
        return bool(client.ping())

    def status(self) -> dict[str, Any]:
        if not self.configured:
            return {"configured": False, "ready": False, "message": "REDIS_URL not configured"}
        try:
            ready = self.ping()
            return {
                "configured": True,
                "ready": ready,
                "message": "Redis ready" if ready else "Redis unavailable",
                "backend": "redis" if not self.using_memory_fallback else "memory-fallback",
            }
        except Exception as exc:
            logger.exception("Redis health check failed")
            return {"configured": True, "ready": False, "message": str(exc), "backend": "redis"}

    def get(self, key: str) -> str | None:
        client = self._get_client()
        namespaced = self._key(key)
        if client is None:
            with self._lock:
                return self._values.get(namespaced)
        value = client.get(namespaced)
        return str(value) if value is not None else None

    def set(self, key: str, value: str) -> None:
        client = self._get_client()
        namespaced = self._key(key)
        if client is None:
            with self._lock:
                self._values[namespaced] = value
            return
        client.set(namespaced, value)

    def delete(self, key: str) -> None:
        client = self._get_client()
        namespaced = self._key(key)
        if client is None:
            with self._lock:
                self._values.pop(namespaced, None)
                self._hashes.pop(namespaced, None)
            return
        client.delete(namespaced)

    def hget(self, key: str, field: str) -> str | None:
        client = self._get_client()
        namespaced = self._key(key)
        if client is None:
            with self._lock:
                return self._hashes.get(namespaced, {}).get(field)
        value = client.hget(namespaced, field)
        return str(value) if value is not None else None

    def hset(self, key: str, field: str, value: str) -> None:
        client = self._get_client()
        namespaced = self._key(key)
        if client is None:
            with self._lock:
                self._hashes.setdefault(namespaced, {})[field] = value
            return
        client.hset(namespaced, field, value)

    def hset_many(self, key: str, mapping: dict[str, str]) -> None:
        if not mapping:
            return
        client = self._get_client()
        namespaced = self._key(key)
        if client is None:
            with self._lock:
                bucket = self._hashes.setdefault(namespaced, {})
                bucket.update(mapping)
            return
        client.hset(namespaced, mapping=mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        client = self._get_client()
        namespaced = self._key(key)
        if client is None:
            with self._lock:
                return dict(self._hashes.get(namespaced, {}))
        payload = client.hgetall(namespaced)
        return {str(k): str(v) for k, v in payload.items()}

    def hdel(self, key: str, *fields: str) -> None:
        if not fields:
            return
        client = self._get_client()
        namespaced = self._key(key)
        if client is None:
            with self._lock:
                bucket = self._hashes.get(namespaced, {})
                for field in fields:
                    bucket.pop(field, None)
            return
        client.hdel(namespaced, *fields)

    def get_json(self, key: str) -> Any:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_json(self, key: str, value: Any) -> None:
        self.set(key, json.dumps(value))

    def hget_json(self, key: str, field: str) -> Any:
        raw = self.hget(key, field)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def hgetall_json(self, key: str) -> dict[str, Any]:
        raw = self.hgetall(key)
        parsed: dict[str, Any] = {}
        for field, value in raw.items():
            try:
                parsed[field] = json.loads(value)
            except json.JSONDecodeError:
                parsed[field] = deepcopy(value)
        return parsed

    def hset_json(self, key: str, field: str, value: Any) -> None:
        self.hset(key, field, json.dumps(value))

    def hset_many_json(self, key: str, mapping: dict[str, Any]) -> None:
        self.hset_many(key, {field: json.dumps(value) for field, value in mapping.items()})


redis_state_store = RedisStateStore()
