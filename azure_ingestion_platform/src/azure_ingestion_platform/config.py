from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any


def _env_json(name: str, default: dict[str, Any]) -> dict[str, Any]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return dict(default)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return dict(default)
    return parsed if isinstance(parsed, dict) else dict(default)


def _normalized_fernet_key(secret: str) -> bytes:
    raw = secret.strip() or "local-dev-encryption-key"
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("utf-8"))
        if len(decoded) == 32:
            return raw.encode("utf-8")
    except Exception:
        pass
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@dataclass(slots=True)
class Settings:
    app_name: str = field(default_factory=lambda: os.getenv("APP_NAME", "azure-ingestion-platform"))
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "sqlite+pysqlite:///./azure_ingestion_platform.db",
        )
    )
    platform_client_id: str = field(default_factory=lambda: os.getenv("PLATFORM_ENTRA_CLIENT_ID", ""))
    platform_client_secret: str = field(default_factory=lambda: os.getenv("PLATFORM_ENTRA_CLIENT_SECRET", ""))
    platform_redirect_uri: str = field(
        default_factory=lambda: os.getenv("PLATFORM_ENTRA_REDIRECT_URI", "http://localhost:8081/api/v1/onboarding/callback")
    )
    platform_encryption_key: bytes = field(
        default_factory=lambda: _normalized_fernet_key(os.getenv("PLATFORM_ENCRYPTION_KEY", "local-dev-encryption-key"))
    )
    scheduler_poll_seconds: int = field(default_factory=lambda: int(os.getenv("SCHEDULER_POLL_SECONDS", "30")))
    worker_poll_seconds: int = field(default_factory=lambda: int(os.getenv("WORKER_POLL_SECONDS", "5")))
    ingestion_max_attempts: int = field(default_factory=lambda: int(os.getenv("INGESTION_MAX_ATTEMPTS", "5")))
    retry_base_seconds: float = field(default_factory=lambda: float(os.getenv("RETRY_BASE_SECONDS", "1.0")))
    retry_max_seconds: float = field(default_factory=lambda: float(os.getenv("RETRY_MAX_SECONDS", "30.0")))
    source_concurrency_limits: dict[str, Any] = field(
        default_factory=lambda: _env_json(
            "SOURCE_CONCURRENCY_LIMITS_JSON",
            {
                "resource_graph": 2,
                "activity_log": 2,
                "change_analysis": 1,
                "metrics": 2,
                "cost_exports": 1,
                "cost_query": 1,
                "advisor": 1,
                "entra_directory_audits": 1,
                "entra_signins": 1,
            },
        )
    )
    collector_intervals_minutes: dict[str, Any] = field(
        default_factory=lambda: _env_json(
            "COLLECTOR_INTERVALS_MINUTES_JSON",
            {
                "resource_graph": 360,
                "activity_log": 5,
                "change_analysis": 15,
                "metrics": 15,
                "cost_exports": 360,
                "cost_query": 120,
                "advisor": 720,
                "entra_directory_audits": 15,
                "entra_signins": 15,
            },
        )
    )


settings = Settings()
