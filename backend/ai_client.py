"""AI provider abstraction for ticket triage analysis."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import heapq
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import requests
from requests.adapters import HTTPAdapter

from azure_finops import azure_finops_service
from config import (
    ANTHROPIC_API_KEY,
    AZURE_FINOPS_AI_TEAM_MAPPINGS,
    OLLAMA_BASE_URL,
    OLLAMA_ENABLED,
    OLLAMA_FAST_MODEL,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_MODEL,
    OLLAMA_REQUEST_TIMEOUT_SECONDS,
    OLLAMA_SECONDARY_BASE_URL,
    OLLAMA_SECONDARY_ENABLED,
    OLLAMA_SECURITY_BASE_URL,
    OLLAMA_SECURITY_ENABLED,
    OLLAMA_SECURITY_MODEL,
    OPENAI_API_KEY,
)
from models import (
    AIModel,
    AzureCitation,
    AzureCostChatResponse,
    KnowledgeBaseArticle,
    KnowledgeBaseDraft,
    TechnicianScore,
    TriageResult,
    TriageSuggestion,
)
from request_type import extract_request_type_name_from_fields

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

_CURATED_MODELS: list[dict[str, str]] = [
    {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai"},
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "openai"},
    {"id": "gpt-4.1", "name": "GPT-4.1", "provider": "openai"},
    {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini", "provider": "openai"},
    {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "provider": "anthropic"},
    {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "provider": "anthropic"},
]

_OPENAI_COPILOT_MODEL_CACHE_TTL_SECONDS = 300
_OPENAI_COPILOT_MODEL_CACHE: tuple[float, list[AIModel]] | None = None
_OLLAMA_MODEL_CACHE_TTL_SECONDS = 30
_OLLAMA_MODEL_CACHE: dict[str, tuple[float, list[AIModel]]] | None = None
_OPENAI_TEXT_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4")
_OPENAI_EXCLUDED_MODEL_TOKENS = (
    "audio",
    "image",
    "tts",
    "transcribe",
    "realtime",
    "search",
    "moderation",
    "embedding",
    "whisper",
    "dall-e",
    "sora",
)
_DEFAULT_COPILOT_MODEL_ORDER = (
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5-mini",
    "gpt-5",
    "gpt-4.1",
    "gpt-4o-mini",
    "gpt-4o",
    "claude-sonnet-4-20250514",
    "claude-haiku-4-5-20251001",
)
_DEFAULT_COPILOT_MODEL_RANK = {model_id: index for index, model_id in enumerate(_DEFAULT_COPILOT_MODEL_ORDER)}
_DEFAULT_OLLAMA_FALLBACK_MODEL_ORDER = (
    "nemotron-3-nano:4b",
)
_OLLAMA_HTTP_POOL_CONNECTIONS = 8
_OLLAMA_HTTP_POOL_MAXSIZE = 16
_OLLAMA_MAX_CONCURRENT_REQUESTS = 1
_DEFAULT_OLLAMA_REQUEST_PRIORITY = 50
_OLLAMA_REQUEST_PRIORITY_BY_FEATURE = {
    "azure_security_copilot": 0,
    "azure_cost_copilot": 20,
    "azure_alert_rule_parse": 25,
    "ticket_auto_triage": 40,
    "technician_qa": 45,
    "kb_ticket_draft": 50,
    "kb_sop_draft": 55,
    "kb_reformat": 55,
    "report_ai_summary": 70,
}

_AUTO_TRIAGE_MAX_OUTPUT_TOKENS = 450
_TECHNICIAN_QA_MAX_OUTPUT_TOKENS = 250
_AZURE_ALERT_RULE_MAX_OUTPUT_TOKENS = 220
_AZURE_COST_COPILOT_MAX_OUTPUT_TOKENS = 900
_KB_TICKET_DRAFT_MAX_OUTPUT_TOKENS = 2200
_KB_SOP_DRAFT_MAX_OUTPUT_TOKENS = 2200
_KB_REFORMAT_MAX_OUTPUT_TOKENS = 2200

_TICKET_DESCRIPTION_CHAR_LIMIT = 1800
_TICKET_STEPS_CHAR_LIMIT = 600
_TICKET_COMMENT_CHAR_LIMIT = 350
_TICKET_COMMENT_TOTAL_CHAR_LIMIT = 1800
_TICKET_COMMENT_MAX_COUNT = 6
_TICKET_KB_MATCH_MAX_COUNT = 2
_TICKET_KB_EXCERPT_CHAR_LIMIT = 400

_QA_COMMENT_MAX_COUNT = 6
_QA_COMMENT_CHAR_LIMIT = 400
_KB_EXISTING_ARTICLE_CHAR_LIMIT = 3000
_OLLAMA_RUNTIME_STATE_LOCK = threading.Lock()


def _build_ollama_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=_OLLAMA_HTTP_POOL_CONNECTIONS,
        pool_maxsize=_OLLAMA_HTTP_POOL_MAXSIZE,
        max_retries=0,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


_OLLAMA_THREAD_LOCAL = threading.local()
T = TypeVar("T")


@dataclass(frozen=True)
class OllamaRuntimeSettings:
    name: str
    enabled: bool
    base_url: str
    preferred_model_id: str


def _normalize_ollama_runtime(runtime: str | None = None) -> str:
    r = str(runtime or "").strip().lower()
    if r == "security":
        return "security"
    if r == "secondary":
        return "secondary"
    return "default"


def _get_ollama_runtime_settings(runtime: str | None = None) -> OllamaRuntimeSettings:
    normalized = _normalize_ollama_runtime(runtime)
    if normalized == "security":
        return OllamaRuntimeSettings(
            name="security",
            enabled=OLLAMA_SECURITY_ENABLED,
            base_url=OLLAMA_SECURITY_BASE_URL,
            preferred_model_id=OLLAMA_SECURITY_MODEL,
        )
    if normalized == "secondary":
        return OllamaRuntimeSettings(
            name="secondary",
            enabled=OLLAMA_SECONDARY_ENABLED,
            base_url=OLLAMA_SECONDARY_BASE_URL,
            preferred_model_id=OLLAMA_MODEL,
        )
    return OllamaRuntimeSettings(
        name="default",
        enabled=OLLAMA_ENABLED,
        base_url=OLLAMA_BASE_URL,
        preferred_model_id=OLLAMA_MODEL,
    )


def _normalize_ollama_base_url(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def _get_ollama_session(base_url: str = "") -> requests.Session:
    normalized_base_url = _normalize_ollama_base_url(base_url or OLLAMA_BASE_URL)
    sessions = getattr(_OLLAMA_THREAD_LOCAL, "sessions", None)
    if not isinstance(sessions, dict):
        sessions = {}
        _OLLAMA_THREAD_LOCAL.sessions = sessions
    session = sessions.get(normalized_base_url)
    if session is None:
        session = _build_ollama_session()
        sessions[normalized_base_url] = session
    return session


@dataclass(order=True)
class _QueuedOllamaRequest:
    priority: int
    order: int
    label: str = field(compare=False)


class OllamaRequestCoordinator:
    """Coordinate non-preemptive priority access to the local Ollama runtime."""

    def __init__(self, *, max_concurrent_requests: int = 1) -> None:
        self._max_concurrent_requests = max(1, int(max_concurrent_requests or 1))
        self._condition = threading.Condition()
        self._queue: list[_QueuedOllamaRequest] = []
        self._active_count = 0
        self._active_labels: list[str] = []
        self._counter = 0

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                "active_count": self._active_count,
                "active_labels": list(self._active_labels),
                "queued": [
                    {"priority": item.priority, "order": item.order, "label": item.label}
                    for item in sorted(self._queue)
                ],
            }

    def run(self, *, priority: int, label: str, work: Callable[[], T]) -> T:
        with self._condition:
            queued = _QueuedOllamaRequest(
                priority=int(priority),
                order=self._counter,
                label=label,
            )
            self._counter += 1
            heapq.heappush(self._queue, queued)
            while True:
                is_next = bool(self._queue) and self._queue[0] is queued
                if is_next and self._active_count < self._max_concurrent_requests:
                    heapq.heappop(self._queue)
                    self._active_count += 1
                    self._active_labels.append(label)
                    break
                self._condition.wait()
        try:
            return work()
        finally:
            with self._condition:
                self._active_count = max(0, self._active_count - 1)
                try:
                    self._active_labels.remove(label)
                except ValueError:
                    pass
                self._condition.notify_all()


_OLLAMA_REQUEST_COORDINATORS: dict[str, OllamaRequestCoordinator] = {}


def get_ollama_queue_snapshot() -> list[dict[str, Any]]:
    """Return a snapshot of every active Ollama request coordinator.

    Each entry has:
      url         – base URL of the Ollama instance
      label       – short human-readable name (primary/secondary/security)
      active      – number of requests currently executing
      queued      – list of waiting requests [{priority, label}, ...]
    Only coordinators that have been touched at least once are included.
    """
    # Build a label map from known configured URLs
    label_map: dict[str, str] = {
        _normalize_ollama_base_url(OLLAMA_BASE_URL): "primary",
        _normalize_ollama_base_url(OLLAMA_SECURITY_BASE_URL): "security",
    }
    if OLLAMA_SECONDARY_BASE_URL:
        label_map[_normalize_ollama_base_url(OLLAMA_SECONDARY_BASE_URL)] = "secondary"

    lanes: list[dict[str, Any]] = []
    with _OLLAMA_RUNTIME_STATE_LOCK:
        items = list(_OLLAMA_REQUEST_COORDINATORS.items())
    for url, coordinator in items:
        snap = coordinator.snapshot()
        lanes.append({
            "url": url,
            "label": label_map.get(url, url),
            "active": snap["active_count"],
            "active_labels": snap["active_labels"],
            "queued": [{"priority": q["priority"], "label": q["label"]} for q in snap["queued"]],
        })
    # Always include primary/secondary/security even if not yet touched, so the
    # UI can show them as idle before any work starts.
    existing_urls = {lane["url"] for lane in lanes}
    for url, label in label_map.items():
        if url and url not in existing_urls:
            lanes.append({"url": url, "label": label, "active": 0, "active_labels": [], "queued": []})
    lanes.sort(key=lambda x: {"primary": 0, "secondary": 1, "security": 2}.get(x["label"], 3))
    return lanes


# ---------------------------------------------------------------------------
# Secondary Ollama round-robin for triage / QA
# ---------------------------------------------------------------------------

# Features that participate in secondary-instance load sharing
_SECONDARY_OLLAMA_FEATURES = frozenset({"ticket_auto_triage", "technician_qa"})

# Health-check cache: {url: (checked_at, is_healthy)}
_SECONDARY_HEALTH_CACHE: tuple[float, bool] = (0.0, False)
_SECONDARY_HEALTH_TTL = 30.0  # seconds
_SECONDARY_HEALTH_LOCK = threading.Lock()

# Round-robin counter (shared across threads; atomic via GIL for CPython)
_SECONDARY_ROUND_ROBIN_COUNTER = 0


def _check_secondary_healthy() -> bool:
    """Return True if the secondary Ollama instance is reachable (cached 30s)."""
    global _SECONDARY_HEALTH_CACHE
    if not OLLAMA_SECONDARY_ENABLED or not OLLAMA_SECONDARY_BASE_URL:
        return False
    now = time.time()
    with _SECONDARY_HEALTH_LOCK:
        checked_at, healthy = _SECONDARY_HEALTH_CACHE
        if now - checked_at < _SECONDARY_HEALTH_TTL:
            return healthy
    try:
        resp = _get_ollama_session(OLLAMA_SECONDARY_BASE_URL).get(
            f"{OLLAMA_SECONDARY_BASE_URL}/api/tags",
            timeout=3.0,
        )
        is_healthy = resp.status_code == 200
    except Exception:
        is_healthy = False
    with _SECONDARY_HEALTH_LOCK:
        _SECONDARY_HEALTH_CACHE = (now, is_healthy)
    if not is_healthy:
        logger.debug("Secondary Ollama at %s is unreachable", OLLAMA_SECONDARY_BASE_URL)
    return is_healthy


def _pick_ollama_base_url_for_feature(feature_surface: str, runtime: str = "default") -> str:
    """Return the Ollama base URL to use for this feature invocation.

    For triage/QA features: round-robin between primary and secondary when
    secondary is healthy; fall back to primary when it is not.
    For all other features: always use the runtime's configured base URL.
    """
    global _SECONDARY_ROUND_ROBIN_COUNTER
    if runtime != "default" or feature_surface not in _SECONDARY_OLLAMA_FEATURES:
        return _get_ollama_runtime_settings(runtime).base_url
    if not _check_secondary_healthy():
        return OLLAMA_BASE_URL
    # Hold the lock for the read-modify-write so two concurrent threads always
    # get different counter values and are dispatched to different URLs.
    with _OLLAMA_RUNTIME_STATE_LOCK:
        counter = _SECONDARY_ROUND_ROBIN_COUNTER
        _SECONDARY_ROUND_ROBIN_COUNTER = counter + 1
    return OLLAMA_SECONDARY_BASE_URL if counter % 2 == 0 else OLLAMA_BASE_URL


def _get_ollama_request_coordinator(base_url: str) -> OllamaRequestCoordinator:
    normalized_base_url = _normalize_ollama_base_url(base_url or OLLAMA_BASE_URL)
    with _OLLAMA_RUNTIME_STATE_LOCK:
        coordinator = _OLLAMA_REQUEST_COORDINATORS.get(normalized_base_url)
        if coordinator is None:
            coordinator = OllamaRequestCoordinator(
                max_concurrent_requests=_OLLAMA_MAX_CONCURRENT_REQUESTS
            )
            _OLLAMA_REQUEST_COORDINATORS[normalized_base_url] = coordinator
        return coordinator


def _resolve_ollama_request_priority(
    feature_surface: str = "",
    explicit_priority: int | None = None,
) -> int:
    if explicit_priority is not None:
        return int(explicit_priority)
    return _OLLAMA_REQUEST_PRIORITY_BY_FEATURE.get(
        str(feature_surface or "").strip().lower(),
        _DEFAULT_OLLAMA_REQUEST_PRIORITY,
    )


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _estimate_token_count(*parts: Any) -> int:
    combined = " ".join(str(part or "") for part in parts if str(part or "").strip())
    if not combined:
        return 0
    return max(1, len(combined) // 4)


def _truncate_text(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def _latest_limited_lines(lines: list[str], *, max_items: int, max_chars: int | None = None) -> str:
    recent = [line for line in lines if str(line or "").strip()][-max_items:]
    if not recent:
        return ""
    if max_chars is None:
        return "\n".join(recent)

    kept_reversed: list[str] = []
    used = 0
    for line in reversed(recent):
        normalized = str(line or "").strip()
        if not normalized:
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        candidate = normalized if len(normalized) <= remaining else _truncate_text(normalized, remaining)
        addition = len(candidate) + (1 if kept_reversed else 0)
        if kept_reversed and addition > remaining:
            break
        kept_reversed.append(candidate)
        used += addition
        if len(candidate) < len(normalized):
            break

    return "\n".join(reversed(kept_reversed))


def select_available_ollama_model(
    available: list[AIModel],
    *,
    preferred_model_id: str = "",
    fallback_model_id: str = "",
    runtime: str = "default",
) -> str | None:
    if not available:
        return None
    runtime_settings = _get_ollama_runtime_settings(runtime)
    available_ids = {model.id for model in available if model.provider == "ollama"}
    seen: set[str] = set()
    candidates = [
        preferred_model_id,
        fallback_model_id,
        runtime_settings.preferred_model_id,
        OLLAMA_MODEL,
        *_DEFAULT_OLLAMA_FALLBACK_MODEL_ORDER,
        OLLAMA_FAST_MODEL,
    ]
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if normalized in available_ids:
            return normalized
    for model in available:
        if model.provider == "ollama":
            return model.id
    return None


_DEFAULT_AI_TEAMS_BY_FEATURE: dict[str, str] = {
    "ticket_auto_triage": "Service Desk",
    "report_ai_summary": "Service Desk",
    "technician_qa": "Service Desk",
    "kb_ticket_draft": "Service Desk",
    "kb_sop_draft": "Service Desk",
    "kb_reformat": "Service Desk",
    "azure_cost_copilot": "FinOps",
    "azure_alert_rule_parse": "FinOps",
    "azure_security_copilot": "Security",
}

_DEFAULT_AI_TEAMS_BY_APP: dict[str, str] = {
    "reports": "Service Desk",
    "tickets": "Service Desk",
    "knowledge_base": "Service Desk",
    "azure_portal": "FinOps",
    "azure_alerts": "FinOps",
}


def _normalize_ai_team_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        normalized_key = str(key or "").strip().lower()
        normalized_value = str(value or "").strip()
        if normalized_key and normalized_value:
            normalized[normalized_key] = normalized_value
    return normalized


def _resolve_ai_usage_team(
    *,
    feature_surface: str,
    app_surface: str,
    actor_id: str,
    explicit_team: str = "",
) -> tuple[str, str, str]:
    explicit = str(explicit_team or "").strip()
    if explicit:
        return explicit, "explicit", ""

    mappings = AZURE_FINOPS_AI_TEAM_MAPPINGS if isinstance(AZURE_FINOPS_AI_TEAM_MAPPINGS, dict) else {}
    actor_map = _normalize_ai_team_map(mappings.get("actor_ids"))
    feature_map = _normalize_ai_team_map(mappings.get("feature_surfaces"))
    app_map = _normalize_ai_team_map(mappings.get("app_surfaces"))

    normalized_actor_id = str(actor_id or "").strip().lower()
    if normalized_actor_id and normalized_actor_id in actor_map:
        return actor_map[normalized_actor_id], "actor_id", normalized_actor_id

    normalized_feature = str(feature_surface or "").strip().lower()
    if normalized_feature and normalized_feature in feature_map:
        return feature_map[normalized_feature], "feature_surface", normalized_feature
    if normalized_feature and normalized_feature in _DEFAULT_AI_TEAMS_BY_FEATURE:
        return _DEFAULT_AI_TEAMS_BY_FEATURE[normalized_feature], "default_feature_surface", normalized_feature

    normalized_app = str(app_surface or "").strip().lower()
    if normalized_app and normalized_app in app_map:
        return app_map[normalized_app], "app_surface", normalized_app
    if normalized_app and normalized_app in _DEFAULT_AI_TEAMS_BY_APP:
        return _DEFAULT_AI_TEAMS_BY_APP[normalized_app], "default_app_surface", normalized_app

    return "", "unmapped", ""


def _get_curated_models(provider: str) -> list[AIModel]:
    return [AIModel(**model) for model in _CURATED_MODELS if model["provider"] == provider]


def _list_ollama_models_from_api(*, runtime: str = "default") -> list[AIModel]:
    runtime_settings = _get_ollama_runtime_settings(runtime)
    response = _get_ollama_session(runtime_settings.base_url).get(
        f"{runtime_settings.base_url}/api/tags",
        timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    seen: dict[str, AIModel] = {}
    for item in payload.get("models") or []:
        model_id = str(item.get("model") or item.get("name") or "").strip()
        if not model_id:
            continue
        display_name = str(item.get("name") or model_id).strip() or model_id
        seen[model_id] = AIModel(id=model_id, name=display_name, provider="ollama")
    preference_rank = {
        model_id: index
        for index, model_id in enumerate(
            dict.fromkeys(
                (
                    runtime_settings.preferred_model_id,
                    OLLAMA_MODEL,
                    *_DEFAULT_OLLAMA_FALLBACK_MODEL_ORDER,
                    OLLAMA_FAST_MODEL,
                )
            )
        )
    }
    return sorted(
        seen.values(),
        key=lambda model: (preference_rank.get(model.id, len(preference_rank) + 1), model.id.lower()),
    )


def _get_available_ollama_models(*, runtime: str = "default") -> list[AIModel]:
    global _OLLAMA_MODEL_CACHE

    runtime_settings = _get_ollama_runtime_settings(runtime)
    if not runtime_settings.enabled:
        return []
    base_url = _normalize_ollama_base_url(runtime_settings.base_url)
    if not base_url:
        return []

    now = time.time()
    cache_store = _OLLAMA_MODEL_CACHE if isinstance(_OLLAMA_MODEL_CACHE, dict) else {}
    cached = cache_store.get(base_url)
    if cached and now - cached[0] < _OLLAMA_MODEL_CACHE_TTL_SECONDS:
        return list(cached[1])

    try:
        models = _list_ollama_models_from_api(runtime=runtime_settings.name)
    except Exception:
        logger.warning(
            "Failed to fetch %s Ollama models from %s",
            runtime_settings.name,
            runtime_settings.base_url,
            exc_info=True,
        )
        if cached:
            return list(cached[1])
        cache_store[base_url] = (now, [])
        _OLLAMA_MODEL_CACHE = cache_store
        return []

    cache_store[base_url] = (now, list(models))
    _OLLAMA_MODEL_CACHE = cache_store
    return models


def get_available_models(*, runtime: str = "default") -> list[AIModel]:
    """Return models from the active Ollama runtime."""
    runtime_settings = _get_ollama_runtime_settings(runtime)
    if not runtime_settings.enabled:
        return []
    return _get_available_ollama_models(runtime=runtime_settings.name)


def _is_openai_text_model(model_id: str) -> bool:
    lowered = model_id.strip().lower()
    if not lowered.startswith(_OPENAI_TEXT_MODEL_PREFIXES):
        return False
    return not any(token in lowered for token in _OPENAI_EXCLUDED_MODEL_TOKENS)


def _is_model_snapshot(model_id: str) -> bool:
    return bool(re.search(r"-20\d{2}-\d{2}-\d{2}$", model_id))


def _copilot_model_sort_key(model: AIModel) -> tuple[int, int, int, str]:
    provider_rank = {"openai": 0, "anthropic": 1, "ollama": 2}.get(model.provider, 3)
    default_rank = _DEFAULT_COPILOT_MODEL_RANK.get(model.id, len(_DEFAULT_COPILOT_MODEL_RANK) + 1)
    snapshot_rank = 1 if _is_model_snapshot(model.id) else 0
    return (provider_rank, default_rank, snapshot_rank, model.id.lower())


def _list_openai_copilot_models_from_api() -> list[AIModel]:
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    seen: dict[str, AIModel] = {}
    for model in client.models.list().data:
        model_id = getattr(model, "id", "").strip()
        if not model_id or not _is_openai_text_model(model_id):
            continue
        seen[model_id] = AIModel(id=model_id, name=model_id, provider="openai")
    return sorted(seen.values(), key=_copilot_model_sort_key)


def get_available_copilot_models() -> list[AIModel]:
    """Return Azure cost copilot models from the default Ollama runtime."""
    return get_available_models()


def get_available_security_copilot_models() -> list[AIModel]:
    """Return Security Copilot models from the dedicated security Ollama runtime."""
    return get_available_models(runtime="security")


def get_default_copilot_model_id(available: list[AIModel]) -> str | None:
    if not available:
        return None
    default_ollama = select_available_ollama_model(
        available,
        preferred_model_id=OLLAMA_MODEL,
    )
    if default_ollama:
        return default_ollama
    available_ids = {model.id for model in available}
    for model_id in _DEFAULT_COPILOT_MODEL_ORDER:
        if model_id in available_ids:
            return model_id
    return available[0].id


def get_default_security_copilot_model_id(available: list[AIModel]) -> str | None:
    if not available:
        return None
    default_ollama = select_available_ollama_model(
        available,
        preferred_model_id=OLLAMA_SECURITY_MODEL,
        fallback_model_id=OLLAMA_MODEL,
        runtime="security",
    )
    if default_ollama:
        return default_ollama
    return available[0].id


def _get_model_provider(model_id: str, *, ollama_runtime: str = "default") -> str | None:
    runtime_settings = _get_ollama_runtime_settings(ollama_runtime)
    if runtime_settings.enabled and model_id == runtime_settings.preferred_model_id:
        return "ollama"
    if runtime_settings.enabled and any(
        model.id == model_id for model in _get_available_ollama_models(runtime=runtime_settings.name)
    ):
        return "ollama"
    return None


# ---------------------------------------------------------------------------
# ADF text extraction
# ---------------------------------------------------------------------------


def extract_adf_text(adf: dict | None) -> str:
    """Recursively walk Atlassian Document Format and extract plain text."""
    if not adf or not isinstance(adf, dict):
        return ""

    parts: list[str] = []

    if adf.get("type") == "text":
        parts.append(adf.get("text", ""))

    for child in adf.get("content", []):
        parts.append(extract_adf_text(child))

    return "".join(parts)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

KNOWN_PRIORITIES = ["Highest", "High", "Medium", "Low"]

KNOWN_STATUSES = [
    "New", "Open", "Assigned", "In Progress", "Work in Progress",
    "Investigating", "Waiting for Customer", "Waiting for Support",
    "Pending", "Pending Customer", "Pending Vendor", "Scheduled",
    "On Hold", "Awaiting Approval", "Waiting for Approval",
    "Resolved", "Closed", "Done", "Cancelled", "Declined",
]

_SECURITY_ALERT_REQUEST_TYPE = "Security Alert"
_SECURITY_PRIORITY_REASONING = "Security Alert tickets must be triaged at High priority."
_HIGH_ENOUGH_SECURITY_PRIORITIES = {"High", "Highest"}
_NON_NEW_PRIORITY_REASONING = "Triage must assign an operational priority; tickets should not remain at New."
_REPORTER_HINT_PATTERNS = [
    re.compile(r"(?im)\b(?:occ\s+)?ticket\s+created\s+by\s*:\s*([^\n\r|*]+)"),
]

SYSTEM_PROMPT = """You are an IT helpdesk triage assistant for a Jira Service Management project (OIT).
Your job is to analyze tickets and suggest improvements for: priority, request_type, status, assignee, reporter, and an optional comment.

## General Rules
- Only suggest changes where you see a clear improvement. If a field looks correct, omit it — EXCEPT for request_type which you MUST always suggest.
- Priority must be one of: {priorities}
- Status must be one of: {statuses}
- For assignee, suggest a name only if you can identify the right person from context. Otherwise omit.
- For reporter, only suggest a person when the ticket explicitly names who created the OCC/help desk request, such as "Ticket Created By: Jane Doe". Otherwise omit.
- For comments, suggest a brief triage note only if it would help the agent handling the ticket.
- Relevant internal knowledge base articles may be included. Use them as context for classification and handling notes, but do not assume facts not present in the ticket or KB excerpts.
- Provide a confidence score (0.0-1.0) and brief reasoning for each suggestion.

## Request Type Classification Rules
You MUST ALWAYS suggest a request_type. Classify every ticket into exactly one of the categories below.
Do NOT use any request type not in this list: {request_types}

**Classification procedure:**
1. Scan the ticket Summary, Description, and Comments against the keyword lists below.
2. Categories are in PRIORITY ORDER. When a ticket matches multiple categories, assign it to whichever appears FIRST in this list.
   Example: a ticket mentioning both "phishing" and "email" → Security Alert (not Email or Outlook).
3. Keyword matching is case-insensitive. Match partial words where indicated (e.g., "authenticat" matches "authentication", "authenticator").
4. If no keywords match and the ticket does not clearly fit any category, assign "Get IT help".

### 1. Security Alert (HIGHEST PRIORITY)
Automated security notifications, threat reports, phishing, and security incidents.
Keywords: threat has been reported, unknown email in phisher, red canary, potentially malicious url, phish, quarantine, spam, junk mail, suspicious email, malware, ransomware, virus, trojan, compromised, breach, security incident, unauthorized access, threat published

### 2. Onboard new employees
Set up new user accounts, provision access for new hires, contractors, or interns.
Keywords: new account for, new hire, new employee, onboard, onboarding, new contractor activation, activation -, activation:, activation-, new user, new account

### 3. Offboard employees
Disable accounts, revoke access for departing employees or terminated staff.
Keywords: offboard, offboarding, termination, deactivation, employee deactivation, disable account, remove access, deactivate user, deactivation request

### 4. Password MFA Authentication
Passwords, multi-factor auth, login failures, lockouts, SSO, credential resets.
Keywords: password, credential, mfa, multi-factor, 2fa, authenticat (partial), locked out, lockout, unable to login, can't login, cant log, login issue, sign in, sign-in, sso, reset password, unlock account, password reset, password expired

### 5. VPN
VPN connectivity, FortiClient, remote access issues.
Keywords: vpn, forticlient, remote access, remote into, remote desktop, remote connect, vpn issues, vpn not connecting

### 6. Virtual Desktop
Windows Virtual Desktop (WVD), Azure Virtual Desktop (AVD), Citrix, virtual desktop environments.
Keywords: wvd, avd, virtual desktop, citrix, virtual machine desktop

### 7. Email or Outlook
Email delivery, Outlook client, shared mailboxes, distribution lists, calendar issues, aliases, auto-replies.
Keywords: email, e-mail, outlook, mailbox, inbox, alias, distribution list, autoreply, auto reply, shared mailbox, calendar invite, calendar issue, exchange, email chain, email access

### 8. Phone RingCentral
RingCentral phone system, caller ID, voicemail, phone lines, extensions.
Keywords: ring central, ringcentral, caller id, phone system, voicemail, phone line, phone number, extension, incontact

### 9. Report a computer equipment problem
Hardware failures, peripherals (monitors, keyboards, mice, docking stations), laptops, printers, equipment replacement.
Keywords: laptop, monitor, mouse, keyboard, printer, headset, dock, docking station, charge, charging, equipment, hardware, pc setup, pc replacement, hinge, screen, broken, not charging, usb, webcam, camera, extended screen

### 10. Server Infrastructure Database
Servers, Azure cloud, SSL certificates, DNS, firewalls, database admin, SQL Server, patching, port changes.
Keywords: server, azure, infrastructure, certificate, ssl, patching, sql, dba request, database, db (word boundary), port change, dns, firewall, site recovery, sql server, db write access
Note: "db " (with trailing space/boundary) to avoid false positives.

### 11. Backup and Storage
Disk space, storage allocation, backup jobs, drive access, low memory warnings.
Keywords: disk, storage, backup, space, virtual memory, drive, low memory, insufficient disk, disk space, c disk, l & w drive

### 12. Request new PC software
Install software, upgrade applications, obtain licenses, local admin rights for installation.
Keywords: install, software install, adobe, license, local admin, out of date, new software, software request, software access

### 13. Business Application Support
Specific business apps: MoveDocs, Concur, ADP, CIMI, Libra, C3, MedPort, MDM, Salesforce, Power BI, Teams, SharePoint, OneDrive, Bitbucket, GRS.
Keywords: movedocs, concur, adp, cimi, libra, c3, medport, mdm, salesforce, sales force, powerbi, power bi, bit bucket, bitbucket, grs, teams, microsoft teams, sharepoint, onedrive, one drive

### 14. Get IT help (DEFAULT — lowest priority)
General IT issues, PC performance, OS problems, sound/audio, file access, and anything that doesn't match above.
Keywords: slow, freeze, crash, blue screen, reboot, restart, performance, windows 10, windows 11, can't open, cant open, unable to save, unable to open, not working, issue, problem, error, help, sound, audio, speaker, microphone
Assign this category when no other category clearly matches.

## Response Format
Respond with ONLY valid JSON (no markdown fences):
{{
  "suggestions": [
    {{
      "field": "priority",
      "suggested_value": "High",
      "reasoning": "Customer reports complete service outage",
      "confidence": 0.85
    }},
    {{
      "field": "request_type",
      "suggested_value": "Security Alert",
      "reasoning": "Subject mentions phishing report from PhishER",
      "confidence": 0.95
    }}
  ]
}}

If no changes are needed (except request_type which is always required), return only the request_type suggestion.
"""

KB_SOP_PROMPT = """You are converting a Standard Operating Procedure (SOP) document into an internal IT helpdesk knowledge base article.

Return a single JSON object with these fields:
- "title": concise KB article title (not the SOP document title verbatim)
- "summary": one sentence describing what the article covers
- "request_type": the closest IT helpdesk category if inferable (e.g. "Email or Outlook", "VPN", "Password MFA Authentication", "Onboard new employees"), otherwise empty string
- "content": full article in markdown — ## for section headings, numbered lists for step-by-step procedures (group consecutive steps without blank lines between them), - for bullet points, and Note:/Warning:/Tip:/Important: prefixes for callouts

Preserve all technical details exactly. Return only the JSON object, no preamble, no markdown fences."""


KB_REFORMAT_PROMPT = """You are reformatting an IT knowledge base article for better readability.

Restructure the content using clean markdown:
- ## for section headings (e.g. ## Description, ## Steps, ## Notes, ## Additional Information)
- ### for sub-headings
- Numbered lists for step-by-step procedures: 1. First step\n2. Second step (grouped, not separated by blank lines)
- - for unordered bullet lists
- Start callout paragraphs with one of: Note:, Warning:, Tip:, Caution:, or Important:
- **bold** for key terms or UI element names

Preserve all technical content exactly — do not add, remove, or alter any technical information.
Return ONLY the reformatted content. No preamble, no explanation, no markdown fences."""


KB_DRAFT_PROMPT = """You are maintaining the internal OIT helpdesk knowledge base.
Use the closed ticket evidence and any existing related KB article to draft either:
- an update to the existing article, or
- a new article when no existing article covers the resolution well.

Rules:
- Use only information supported by the ticket description, comments, and notes.
- Remove customer-specific details, names, email addresses, and one-off context unless it is operationally necessary.
- Focus on reusable troubleshooting and resolution guidance for technicians.
- Prefer concise section headings and action-oriented steps.
- If an existing article is provided, preserve its general scope and improve it with the new resolution details.

Respond with ONLY valid JSON:
{
  "title": "Article title",
  "request_type": "One request type name or empty string",
  "summary": "One or two sentence overview.",
  "content": "Full article body in plain text with section headings and paragraph breaks.",
  "recommended_action": "update_existing",
  "change_summary": "What this draft adds or changes."
}
"""

AZURE_COST_COPILOT_PROMPT = """You are an Azure cost and governance copilot for an internal IT operations portal.
Answer only from the provided cached Azure data.

## Data Freshness
- Every answer MUST cite how old the data is using `data_freshness.cost` (or `data_freshness.inventory` for VM counts).
- If a freshness timestamp is missing or more than 4 hours old, explicitly warn the user the figures may be stale.
- Format: "As of [timestamp], ..." or "Data last refreshed [timestamp]."

## Cost Analysis Rules
- Lead with the headline number from `cost_summary.total_cost` and the lookback period.
- Use `cost_trend_summary.wow_change_pct` to characterize direction:
  - Positive %: flag as an increase and identify the likely driver from `cost_by_service`.
  - Negative %: note the reduction and what may have caused it.
  - If `wow_change_pct` is null, state that trend comparison is unavailable.
- For "what is costing the most?" questions, use `top_resources_by_cost` for individual resource detail, then `cost_by_service` for service-level summary.

## VM Power State Rules
- Use `vm_power_state_summary.by_state` to answer VM count questions with state breakdown.
- If any VMs are in a `deallocated` or `stopped` state, proactively note that **deallocated VMs still incur costs for managed disks, reserved IPs, and snapshots** — they are not free.
- Cross-reference with `vm_inventory_summary.by_sku` to identify high-cost SKUs that are idle.

## Advisor Recommendations Rules
- Use the `advisor` list; items are pre-sorted by annual savings (highest first).
- Lead with the total `cost_summary.potential_monthly_savings` as the opportunity headline.
- For each recommendation cited, include: title, impact level, and monthly_savings amount.
- Prioritize High-impact items even if a Medium-impact item has higher savings.

## Savings Workspace Rules
- Prefer `savings_summary.quantified_monthly_savings` over raw Advisor totals when the user asks where to save money now.
- Use `savings_opportunities` as the ranked action list and mention effort, risk, confidence, and whether savings are quantified.
- Separate quantified cleanup wins from unquantified reservation strategy items.
- When the user asks for quick wins, prioritize low-effort, low-risk items first.

## General Rules
- Be concrete and action-oriented — give specific resource names, dollar amounts, and subscription names from the data.
- If the grounding data is empty or unavailable for a question, say so explicitly rather than speculating.
- Do not claim any action was performed.
- Keep the answer concise and executive-readable; use bullet points for lists of 3+ items.
"""

TECHNICIAN_SCORE_PROMPT = """You are a QA reviewer for closed IT helpdesk tickets.
Evaluate the technician's handling of a resolved or closed ticket using only the evidence provided.

Score these dimensions from 1 to 5:
- communication_score: how clearly and professionally the technician communicated with the end user
- documentation_score: how well the technician documented what they did, what fixed the issue, and any follow-up context

Scoring guidance:
- 5 = excellent, complete, clear, and customer-friendly
- 4 = strong with minor gaps
- 3 = adequate but missing useful detail
- 2 = weak, sparse, or unclear
- 1 = little to no evidence

Rules:
- Customer-facing communication should be judged mainly from public comments/replies.
- Documentation should be judged from internal notes, public replies, and the final resolution context together.
- If there are no public replies, communication_score should usually be 1 or 2.
- If the notes do not explain what was done to resolve the ticket, documentation_score should usually be 1 or 2.
- Be strict about evidence. Do not assume work happened if it is not documented.
- The input may include long ticket histories or call transcripts. Do NOT summarize the whole ticket, transcript, timeline, or action plan.
- Keep communication_notes focused only on evidence for the communication score.
- Keep documentation_notes focused only on evidence for the documentation score.
- Keep score_summary to one short sentence.
- If evidence is weak or missing, lower the score instead of writing a longer explanation.
- Do not return markdown, code fences, headings, bullets, numbered lists, or prose before/after the JSON.
- Return exactly one JSON object that starts with { and ends with }.
- Use exactly these keys and no extras:
  communication_score
  communication_notes
  documentation_score
  documentation_notes
  score_summary

Return ONLY valid JSON in this shape:
{
  "communication_score": 3,
  "communication_notes": "Short explanation of the communication quality.",
  "documentation_score": 4,
  "documentation_notes": "Short explanation of the documentation quality.",
  "score_summary": "One-sentence overall assessment."
}

Invalid responses include:
- transcript summaries
- meeting note recaps
- markdown fenced code blocks
- any text before or after the JSON object
"""

TECHNICIAN_SCORE_RETRY_PROMPT = """You are retrying a failed technician QA scoring request.
The previous answer was rejected because it was not valid JSON.

Return exactly one valid JSON object for the technician QA schema.

Rules:
- Start with { and end with }.
- Use only these keys:
  communication_score
  communication_notes
  documentation_score
  documentation_notes
  score_summary
- Do not include markdown, prose, commentary, bullets, headings, or code fences.
- Do not summarize the transcript or timeline.
- Keep notes short and evidence-based.
"""


def _build_ticket_context(
    issue: dict[str, Any],
    kb_matches: list[KnowledgeBaseArticle] | None = None,
) -> str:
    """Build a text representation of a ticket for the AI prompt."""
    fields = issue.get("fields", {})

    # Basic info
    key = issue.get("key", "")
    summary = fields.get("summary", "")
    description = _truncate_text(extract_adf_text(fields.get("description")), _TICKET_DESCRIPTION_CHAR_LIMIT)

    # Status
    status_obj = fields.get("status") or {}
    status = status_obj.get("name", "Unknown")

    # Priority
    priority_obj = fields.get("priority") or {}
    priority = priority_obj.get("name", "None")

    # Assignee
    assignee_obj = fields.get("assignee") or {}
    assignee = (
        assignee_obj.get("displayName", "Unassigned")
        if isinstance(assignee_obj, dict)
        else "Unassigned"
    )

    # Issue type
    issuetype_obj = fields.get("issuetype") or {}
    issue_type = issuetype_obj.get("name", "")

    # Request type
    request_type = extract_request_type_name_from_fields(fields)

    # Reporter
    reporter_obj = fields.get("reporter") or {}
    reporter = (
        reporter_obj.get("displayName", "Unknown")
        if isinstance(reporter_obj, dict)
        else "Unknown"
    )
    reporter_hint = _extract_reporter_hint_from_text(description)

    # Dates
    created = fields.get("created", "")
    updated = fields.get("updated", "")
    resolved = fields.get("resolutiondate") or ""

    # Labels
    labels = fields.get("labels") or []

    # Components
    components = [
        c.get("name", "") for c in (fields.get("components") or [])
        if isinstance(c, dict)
    ]

    # Organizations
    orgs_raw = fields.get("customfield_10700") or []
    organizations = [
        o.get("name", "") for o in orgs_raw if isinstance(o, dict)
    ]

    # Comments (all)
    comment_data = fields.get("comment") or {}
    comments = comment_data.get("comments", []) if isinstance(comment_data, dict) else []
    comment_texts: list[str] = []
    for c in comments:
        author = (c.get("author") or {}).get("displayName", "Unknown")
        date = str(c.get("created") or "")[:19].replace("T", " ")
        body = _truncate_text(extract_adf_text(c.get("body")), _TICKET_COMMENT_CHAR_LIMIT)
        if body:
            comment_texts.append(f"  [{author} | {date}]: {body}")

    # Steps to re-create (customfield_11121)
    steps = _truncate_text(extract_adf_text(fields.get("customfield_11121")), _TICKET_STEPS_CHAR_LIMIT)

    # Work category
    work_category = fields.get("customfield_11239") or ""

    lines = [
        f"Ticket: {key}",
        f"Type: {issue_type}",
        f"Request Type: {request_type or 'Not set'}",
        f"Summary: {summary}",
        f"Status: {status}",
        f"Priority: {priority}",
        f"Reporter: {reporter}",
        *([f"Reporter Hint From Ticket Text: {reporter_hint}"] if reporter_hint else []),
        f"Assignee: {assignee}",
        f"Labels: {', '.join(labels) if labels else 'None'}",
        f"Components: {', '.join(components) if components else 'None'}",
        f"Organizations: {', '.join(organizations) if organizations else 'None'}",
        f"Work Category: {work_category or 'Not set'}",
        f"Created: {created}",
        f"Updated: {updated}",
        *([ f"Resolved: {resolved}" ] if resolved else []),
    ]
    if description:
        lines.append(f"Description:\n{description}")
    if steps:
        lines.append(f"Steps to Re-Create:\n{steps}")
    if comment_texts:
        comment_block = _latest_limited_lines(
            comment_texts,
            max_items=_TICKET_COMMENT_MAX_COUNT,
            max_chars=_TICKET_COMMENT_TOTAL_CHAR_LIMIT,
        )
        lines.append(f"Comments ({min(len(comment_texts), _TICKET_COMMENT_MAX_COUNT)} shown of {len(comment_texts)} non-empty):\n{comment_block}")
    if kb_matches:
        kb_lines = []
        for article in kb_matches[:_TICKET_KB_MATCH_MAX_COUNT]:
            excerpt = _truncate_text(article.content, _TICKET_KB_EXCERPT_CHAR_LIMIT)
            kb_lines.append(
                f"- {article.title} ({article.request_type or 'General'}): {article.summary or 'No summary'}\n"
                f"{excerpt}"
            )
        lines.append("Relevant Knowledge Base Articles:\n" + "\n\n".join(kb_lines))

    return "\n".join(lines)


def _extract_comment_body(comment: dict[str, Any]) -> str:
    body = comment.get("body")
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        return extract_adf_text(body)
    return ""


def _build_technician_score_context(
    issue: dict[str, Any],
    request_comments: list[dict[str, Any]],
) -> str:
    """Build a closed-ticket QA context focused on technician communication."""
    fields = issue.get("fields", {})
    key = issue.get("key", "")
    summary = fields.get("summary", "")
    description = extract_adf_text(fields.get("description"))
    steps = extract_adf_text(fields.get("customfield_11121"))
    status_obj = fields.get("status") or {}
    status = status_obj.get("name", "Unknown")
    resolution = ((fields.get("resolution") or {}).get("name") or "")
    resolved = fields.get("resolutiondate") or ""
    assignee_obj = fields.get("assignee") or {}
    assignee = (
        assignee_obj.get("displayName", "Unassigned")
        if isinstance(assignee_obj, dict)
        else "Unassigned"
    )
    request_type = extract_request_type_name_from_fields(fields)

    public_comments: list[str] = []
    internal_comments: list[str] = []
    for comment in request_comments:
        author = ((comment.get("author") or {}).get("displayName") or "Unknown")
        created = str(comment.get("created") or "")[:19].replace("T", " ")
        body = _truncate_text(_extract_comment_body(comment), _QA_COMMENT_CHAR_LIMIT)
        if not body:
            continue
        line = f"[{author} | {created}]: {body}"
        if comment.get("public"):
            public_comments.append(line)
        else:
            internal_comments.append(line)

    lines = [
        f"Ticket: {key}",
        f"Summary: {summary}",
        f"Request Type: {request_type or 'Not set'}",
        f"Status: {status}",
        f"Resolution: {resolution or 'Not set'}",
        f"Resolved: {resolved or 'Not set'}",
        f"Assignee: {assignee}",
    ]
    if description:
        lines.append(f"Description:\n{description}")
    if steps:
        lines.append(f"Steps to Re-Create:\n{steps}")
    lines.append(
        "Customer-Facing Comments:\n"
        + (_latest_limited_lines(public_comments, max_items=_QA_COMMENT_MAX_COUNT) if public_comments else "None")
    )
    lines.append(
        "Internal Notes:\n"
        + (_latest_limited_lines(internal_comments, max_items=_QA_COMMENT_MAX_COUNT) if internal_comments else "None")
    )
    return "\n".join(lines)


def _build_kb_draft_context(
    issue: dict[str, Any],
    request_comments: list[dict[str, Any]],
    existing_article: KnowledgeBaseArticle | None,
) -> str:
    """Build the context for an AI-generated KB draft."""
    ticket_context = _build_technician_score_context(issue, request_comments)
    if not existing_article:
        return ticket_context + "\n\nExisting KB Article:\nNone"
    return (
        ticket_context
        + "\n\nExisting KB Article:\n"
        + f"Title: {existing_article.title}\n"
        + f"Request Type: {existing_article.request_type or 'Not set'}\n"
        + f"Summary: {existing_article.summary or 'None'}\n"
        + f"Content:\n{_truncate_text(existing_article.content, _KB_EXISTING_ARTICLE_CHAR_LIMIT)}"
    )


# ---------------------------------------------------------------------------
# AI API calls
# ---------------------------------------------------------------------------


def _extract_openai_response_text(resp: Any, model_id: str) -> str:
    text = (getattr(resp, "output_text", "") or "").strip()
    if text:
        return text

    parts: list[str] = []
    for output_item in getattr(resp, "output", []) or []:
        content = getattr(output_item, "content", None)
        if content is None and isinstance(output_item, dict):
            content = output_item.get("content")
        for content_item in content or []:
            item_type = getattr(content_item, "type", None)
            if item_type is None and isinstance(content_item, dict):
                item_type = content_item.get("type")
            if item_type not in {"text", "output_text"}:
                continue
            value = getattr(content_item, "text", None)
            if value is None and isinstance(content_item, dict):
                value = content_item.get("text")
            if isinstance(value, dict):
                value = value.get("value") or value.get("text")
            if value:
                parts.append(str(value))

    text = "".join(parts).strip()
    if text:
        return text

    incomplete_details = getattr(resp, "incomplete_details", None)
    incomplete_reason = getattr(incomplete_details, "reason", None)
    if incomplete_reason is None and isinstance(incomplete_details, dict):
        incomplete_reason = incomplete_details.get("reason")
    raise RuntimeError(
        f"OpenAI model '{model_id}' returned no text output"
        + (
            f" (status={getattr(resp, 'status', 'unknown')}, reason={incomplete_reason or 'unknown'})"
            if incomplete_reason or getattr(resp, "status", None)
            else ""
        )
    )


def _extract_openai_usage(resp: Any) -> dict[str, int]:
    usage = getattr(resp, "usage", None)
    if usage is None and isinstance(resp, dict):
        usage = resp.get("usage")
    if usage is None:
        return {}
    if not isinstance(usage, dict):
        usage = {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
    return {
        "input_tokens": _int(usage.get("input_tokens") or usage.get("prompt_tokens")),
        "output_tokens": _int(usage.get("output_tokens") or usage.get("completion_tokens")),
        "total_tokens": _int(usage.get("total_tokens")),
    }


def _invoke_openai(
    model_id: str,
    system: str,
    user_msg: str,
    *,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    api_mode: str = "responses",
) -> tuple[str, dict[str, Any]]:
    """Call OpenAI API and return response text plus usage."""
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    if api_mode == "chat_completions":
        kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": max_output_tokens or 2000,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = client.chat.completions.create(**kwargs)
        text = str((resp.choices[0].message.content or "")).strip()
        if not text:
            raise RuntimeError(f"OpenAI model '{model_id}' returned no text output")
        return text, _extract_openai_usage(resp)

    kwargs = {
        "model": model_id,
        "instructions": system,
        "input": user_msg,
        "max_output_tokens": max_output_tokens or 2000,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = client.responses.create(**kwargs)
    return _extract_openai_response_text(resp, model_id), _extract_openai_usage(resp)


def _call_openai(model_id: str, system: str, user_msg: str) -> str:
    return _invoke_openai(model_id, system, user_msg)[0]


def _invoke_anthropic(
    model_id: str,
    system: str,
    user_msg: str,
    *,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call Anthropic API and return response text plus usage."""
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=model_id,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0.3 if temperature is None else temperature,
        max_tokens=max_output_tokens or 1000,
    )
    usage = getattr(resp, "usage", None)
    return resp.content[0].text, {
        "input_tokens": _int(getattr(usage, "input_tokens", None)),
        "output_tokens": _int(getattr(usage, "output_tokens", None)),
        "total_tokens": _int(getattr(usage, "input_tokens", None)) + _int(getattr(usage, "output_tokens", None)),
    }


def _call_anthropic(model_id: str, system: str, user_msg: str) -> str:
    return _invoke_anthropic(model_id, system, user_msg)[0]


def _invoke_ollama(
    model_id: str,
    system: str,
    user_msg: str,
    *,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    json_output: bool = False,
    priority: int | None = None,
    queue_label: str = "",
    runtime: str = "default",
    feature_surface: str = "",
) -> tuple[str, dict[str, Any]]:
    """Call a local Ollama model and return response text plus usage."""
    runtime_settings = _get_ollama_runtime_settings(runtime)
    # For triage/QA features, round-robin between primary and secondary Ollama
    base_url = _pick_ollama_base_url_for_feature(feature_surface, runtime)
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
    }
    if OLLAMA_KEEP_ALIVE:
        payload["keep_alive"] = OLLAMA_KEEP_ALIVE
    if json_output:
        payload["format"] = "json"
        payload["think"] = False
    options: dict[str, Any] = {}
    if temperature is not None:
        options["temperature"] = temperature
    if max_output_tokens is not None:
        options["num_predict"] = max_output_tokens
    if options:
        payload["options"] = options

    def _run_request() -> tuple[str, dict[str, Any]]:
        response = _get_ollama_session(base_url).post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        message = data.get("message") or {}
        text = str(message.get("content") or "").strip()
        if text:
            return text, {
                "input_tokens": _int(data.get("prompt_eval_count")),
                "output_tokens": _int(data.get("eval_count")),
                "total_tokens": _int(data.get("prompt_eval_count")) + _int(data.get("eval_count")),
            }
        raise RuntimeError(f"Ollama model '{model_id}' returned no text output")

    return _get_ollama_request_coordinator(base_url).run(
        priority=_resolve_ollama_request_priority(feature_surface=feature_surface, explicit_priority=priority),
        label=queue_label or model_id,
        work=_run_request,
    )


def _call_ollama(
    model_id: str,
    system: str,
    user_msg: str,
    *,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    json_output: bool = False,
    priority: int | None = None,
    queue_label: str = "",
    runtime: str = "default",
) -> str:
    return _invoke_ollama(
        model_id,
        system,
        user_msg,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        json_output=json_output,
        priority=priority,
        queue_label=queue_label,
        runtime=runtime,
    )[0]


def invoke_model_text(
    model_id: str,
    system: str,
    user_msg: str,
    *,
    feature_surface: str,
    app_surface: str,
    actor_type: str = "",
    actor_id: str = "",
    team: str = "",
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    json_output: bool = False,
    openai_api_mode: str = "responses",
    metadata: dict[str, Any] | None = None,
    ollama_priority: int | None = None,
    ollama_runtime: str | None = None,
    queue_label: str = "",
) -> str:
    resolved_ollama_runtime = _normalize_ollama_runtime(
        ollama_runtime
        or ("security" if str(feature_surface or "").strip().lower() == "azure_security_copilot" else "default")
    )
    provider = _get_model_provider(model_id, ollama_runtime=resolved_ollama_runtime)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")

    started = time.perf_counter()
    response_text = ""
    usage: dict[str, Any] = {}
    error_text = ""
    status = "succeeded"
    try:
        if provider == "openai":
            response_text, usage = _invoke_openai(
                model_id,
                system,
                user_msg,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                api_mode=openai_api_mode,
            )
        elif provider == "anthropic":
            response_text, usage = _invoke_anthropic(
                model_id,
                system,
                user_msg,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        elif provider == "ollama":
            response_text, usage = _invoke_ollama(
                model_id,
                system,
                user_msg,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                json_output=json_output,
                priority=_resolve_ollama_request_priority(
                    feature_surface=feature_surface,
                    explicit_priority=ollama_priority,
                ),
                queue_label=queue_label or feature_surface or app_surface or model_id,
                runtime=resolved_ollama_runtime,
                feature_surface=feature_surface,
            )
        else:
            raise ValueError(f"Unsupported provider: {provider}")
        return response_text
    except Exception as exc:
        status = "failed"
        error_text = str(exc)
        raise
    finally:
        input_tokens = _int(usage.get("input_tokens"))
        output_tokens = _int(usage.get("output_tokens"))
        estimated_total = _int(usage.get("total_tokens"))
        if input_tokens <= 0:
            input_tokens = _estimate_token_count(system, user_msg)
        if output_tokens <= 0 and response_text:
            output_tokens = _estimate_token_count(response_text)
        if estimated_total <= 0:
            estimated_total = input_tokens + output_tokens
        resolved_team, team_source, team_source_key = _resolve_ai_usage_team(
            feature_surface=feature_surface,
            app_surface=app_surface,
            actor_id=actor_id,
            explicit_team=team,
        )
        usage_metadata = dict(metadata or {})
        usage_metadata.setdefault("team_source", team_source)
        if team_source_key:
            usage_metadata.setdefault("team_source_key", team_source_key)
        try:
            azure_finops_service.record_ai_usage(
                provider=provider,
                model_id=model_id,
                feature_surface=feature_surface,
                app_surface=app_surface,
                actor_type=actor_type,
                actor_id=actor_id,
                team=resolved_team,
                request_count=1,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_tokens=estimated_total,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                status=status,
                error_text=error_text,
                metadata=usage_metadata,
            )
        except Exception:
            logger.exception("Failed to persist AI usage record for %s (%s)", feature_surface, model_id)


def _parse_suggestions(raw: str, issue: dict[str, Any]) -> list[TriageSuggestion]:
    """Parse AI response JSON into TriageSuggestion list."""
    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse AI response as JSON: %s", text[:200])
        return []

    fields_data = issue.get("fields", {})

    # Extract current request type name
    current_rt = extract_request_type_name_from_fields(fields_data)

    current_values = {
        "priority": (fields_data.get("priority") or {}).get("name", ""),
        "request_type": current_rt,
        "status": (fields_data.get("status") or {}).get("name", ""),
        "assignee": (
            (fields_data.get("assignee") or {}).get("displayName", "Unassigned")
            if isinstance(fields_data.get("assignee"), dict)
            else "Unassigned"
        ),
        "reporter": (
            (fields_data.get("reporter") or {}).get("displayName", "Unknown")
            if isinstance(fields_data.get("reporter"), dict)
            else "Unknown"
        ),
        "comment": "",
    }

    suggestions: list[TriageSuggestion] = []
    for s in data.get("suggestions", []):
        field = s.get("field", "")
        if field not in current_values:
            continue
        suggestions.append(
            TriageSuggestion(
                field=field,
                current_value=current_values.get(field, ""),
                suggested_value=s.get("suggested_value", ""),
                reasoning=s.get("reasoning", ""),
                confidence=float(s.get("confidence", 0.5)),
            )
        )
    return suggestions


def _extract_reporter_hint_from_text(text: str) -> str:
    """Extract a reporter name from ticket text when an OCC-created-by hint exists."""
    if not text:
        return ""
    for pattern in _REPORTER_HINT_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        candidate = re.sub(r"\s+", " ", match.group(1)).strip(" \t|:-")
        if candidate:
            return candidate
    return ""


def _enforce_reporter_hint(issue: dict[str, Any], suggestions: list[TriageSuggestion]) -> list[TriageSuggestion]:
    """Inject or replace reporter suggestions from explicit OCC-created-by text."""
    fields = issue.get("fields", {})
    description = extract_adf_text(fields.get("description"))
    reporter_hint = _extract_reporter_hint_from_text(description)
    if not reporter_hint:
        return suggestions

    reporter_obj = fields.get("reporter") or {}
    current_reporter = (
        reporter_obj.get("displayName", "Unknown")
        if isinstance(reporter_obj, dict)
        else "Unknown"
    )
    if reporter_hint.lower() == current_reporter.strip().lower():
        return [s for s in suggestions if s.field != "reporter"]

    normalized: list[TriageSuggestion] = []
    replaced = False
    for suggestion in suggestions:
        if suggestion.field != "reporter":
            normalized.append(suggestion)
            continue
        if not replaced:
            normalized.append(
                TriageSuggestion(
                    field="reporter",
                    current_value=current_reporter,
                    suggested_value=reporter_hint,
                    reasoning=f'Ticket description explicitly says "Ticket Created By: {reporter_hint}".',
                    confidence=max(suggestion.confidence, 0.99),
                )
            )
            replaced = True
    if not replaced:
        normalized.append(
            TriageSuggestion(
                field="reporter",
                current_value=current_reporter,
                suggested_value=reporter_hint,
                reasoning=f'Ticket description explicitly says "Ticket Created By: {reporter_hint}".',
                confidence=0.99,
            )
        )
    return normalized


def _enforce_security_priority(issue: dict[str, Any], suggestions: list[TriageSuggestion]) -> list[TriageSuggestion]:
    """Force security-classified tickets to carry a High priority suggestion.

    The AI prompt already asks for this behavior, but auto-triage needs a
    deterministic server-side rule so Security Alert tickets are never left at
    low priority due to model drift or omissions.
    """
    if not suggestions:
        return suggestions

    fields = issue.get("fields", {})
    current_request_type = extract_request_type_name_from_fields(fields)
    request_type_suggestion = next(
        (s for s in suggestions if s.field == "request_type"),
        None,
    )

    if request_type_suggestion is not None:
        is_security_ticket = request_type_suggestion.suggested_value == _SECURITY_ALERT_REQUEST_TYPE
    else:
        is_security_ticket = current_request_type == _SECURITY_ALERT_REQUEST_TYPE

    if not is_security_ticket:
        return suggestions

    current_priority = (fields.get("priority") or {}).get("name", "")
    if current_priority in _HIGH_ENOUGH_SECURITY_PRIORITIES:
        return [s for s in suggestions if s.field != "priority"]

    normalized: list[TriageSuggestion] = []
    priority_replaced = False
    for suggestion in suggestions:
        if suggestion.field != "priority":
            normalized.append(suggestion)
            continue
        if not priority_replaced:
            normalized.append(
                TriageSuggestion(
                    field="priority",
                    current_value=suggestion.current_value or current_priority,
                    suggested_value="High",
                    reasoning=_SECURITY_PRIORITY_REASONING,
                    confidence=max(suggestion.confidence, 0.99),
                )
            )
            priority_replaced = True

    if not priority_replaced:
        normalized.append(
            TriageSuggestion(
                field="priority",
                current_value=current_priority,
                suggested_value="High",
                reasoning=_SECURITY_PRIORITY_REASONING,
                confidence=0.99,
            )
        )

    return normalized


def normalize_triage_priority_value(value: str) -> str:
    """Return a triage-safe operational priority.

    Jira may expose `New` as a valid priority, but triage should never leave a
    ticket there. We normalize it to `Low`, which is the lowest operational
    priority after a triage pass.
    """
    normalized = str(value or "").strip()
    if normalized.lower() == "new":
        return "Low"
    return normalized


def _enforce_non_new_priority(issue: dict[str, Any], suggestions: list[TriageSuggestion]) -> list[TriageSuggestion]:
    """Ensure triage never leaves a ticket at the placeholder `New` priority."""
    fields = issue.get("fields", {})
    current_priority = str((fields.get("priority") or {}).get("name") or "").strip()

    normalized: list[TriageSuggestion] = []
    saw_priority = False
    for suggestion in suggestions:
        if suggestion.field != "priority":
            normalized.append(suggestion)
            continue
        saw_priority = True
        target_priority = normalize_triage_priority_value(suggestion.suggested_value)
        if target_priority == suggestion.suggested_value:
            normalized.append(suggestion)
            continue
        normalized.append(
            TriageSuggestion(
                field="priority",
                current_value=suggestion.current_value or current_priority,
                suggested_value=target_priority,
                reasoning=_NON_NEW_PRIORITY_REASONING,
                confidence=max(suggestion.confidence, 0.9),
            )
        )

    if current_priority.lower() == "new" and not saw_priority:
        normalized.append(
            TriageSuggestion(
                field="priority",
                current_value=current_priority,
                suggested_value="Low",
                reasoning=_NON_NEW_PRIORITY_REASONING,
                confidence=0.9,
            )
        )

    return normalized


# ---------------------------------------------------------------------------
# Main analysis entry point
# ---------------------------------------------------------------------------


def analyze_ticket(
    issue: dict[str, Any],
    model_id: str,
    *,
    queue_label: str = "",
    ollama_runtime: str | None = None,
) -> TriageResult:
    """Analyze a single ticket and return triage suggestions."""
    provider = _get_model_provider(model_id)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")
    fields = issue.get("fields", {})
    request_type = extract_request_type_name_from_fields(fields)

    system = SYSTEM_PROMPT.format(
        priorities=", ".join(KNOWN_PRIORITIES),
        request_types=", ".join(get_request_type_names()),
        statuses=", ".join(KNOWN_STATUSES),
    )
    from knowledge_base import kb_store

    base_context = _build_ticket_context(issue)
    kb_matches = kb_store.find_relevant_articles(
        request_type=request_type,
        query_text=base_context,
        limit=3,
    )
    user_msg = _build_ticket_context(issue, kb_matches=kb_matches)

    logger.info("Analyzing %s with %s (%s)", issue.get("key"), model_id, provider)
    ticket_key = issue.get("key", "")
    raw = invoke_model_text(
        model_id,
        system,
        user_msg,
        feature_surface="ticket_auto_triage",
        app_surface="tickets",
        actor_type="system",
        actor_id="auto-triage",
        max_output_tokens=_AUTO_TRIAGE_MAX_OUTPUT_TOKENS,
        json_output=True,
        metadata={"ticket_key": ticket_key},
        queue_label=queue_label or (f"triage:{ticket_key}" if ticket_key else "triage"),
        ollama_runtime=ollama_runtime,
    )

    suggestions = _enforce_reporter_hint(
        issue,
        _enforce_security_priority(
            issue,
            _enforce_non_new_priority(issue, _parse_suggestions(raw, issue)),
        ),
    )

    return TriageResult(
        key=issue.get("key", ""),
        suggestions=suggestions,
        model_used=model_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _parse_technician_score(raw: str, key: str, model_id: str) -> TechnicianScore:
    """Parse AI response JSON into a TechnicianScore."""
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                logger.error("Failed to parse technician score JSON: %s", text[:200])
                raise ValueError("Model returned invalid technician score JSON") from exc
        else:
            logger.error("Failed to parse technician score JSON: %s", text[:200])
            raise ValueError("Model returned invalid technician score JSON")
    if not isinstance(data, dict):
        raise ValueError("Model returned invalid technician score JSON")

    def _clamp_score(value: Any) -> int:
        try:
            numeric = int(round(float(value)))
        except (TypeError, ValueError):
            numeric = 1
        return max(1, min(5, numeric))

    return TechnicianScore(
        key=key,
        communication_score=_clamp_score(data.get("communication_score")),
        communication_notes=str(data.get("communication_notes", "")).strip(),
        documentation_score=_clamp_score(data.get("documentation_score")),
        documentation_notes=str(data.get("documentation_notes", "")).strip(),
        score_summary=str(data.get("score_summary", "")).strip(),
        model_used=model_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _build_fallback_technician_score(
    issue: dict[str, Any],
    request_comments: list[dict[str, Any]],
    model_id: str,
    *,
    reason: str,
) -> TechnicianScore:
    """Return a conservative deterministic score when the model fails twice."""
    public_count = 0
    internal_count = 0
    for comment in request_comments:
        body = _truncate_text(_extract_comment_body(comment), _QA_COMMENT_CHAR_LIMIT).strip()
        if not body:
            continue
        if comment.get("public"):
            public_count += 1
        else:
            internal_count += 1

    fields = issue.get("fields", {})
    has_resolution = bool((fields.get("resolution") or {}).get("name") or fields.get("resolutiondate"))
    has_description = bool(extract_adf_text(fields.get("description")).strip())
    has_steps = bool(extract_adf_text(fields.get("customfield_11121")).strip())

    communication_score = 1
    if public_count >= 1:
        communication_score = 2
    if public_count >= 2:
        communication_score = 3
    if public_count >= 4:
        communication_score = 4

    documentation_score = 1
    if has_resolution:
        documentation_score += 1
    if internal_count >= 1 or public_count >= 1:
        documentation_score += 1
    if internal_count >= 2 or (has_description and has_steps):
        documentation_score += 1
    documentation_score = max(1, min(4, documentation_score))

    communication_notes = (
        f"Fallback score after invalid model output. Ticket shows {public_count} public comment(s)."
        if public_count
        else "Fallback score after invalid model output. No public comments are documented."
    )
    documentation_evidence: list[str] = []
    if internal_count:
        documentation_evidence.append(f"{internal_count} internal note(s)")
    if has_resolution:
        documentation_evidence.append("a recorded resolution")
    if has_description or has_steps:
        documentation_evidence.append("ticket context")
    documentation_notes = (
        "Fallback score after invalid model output. Evidence includes "
        + ", ".join(documentation_evidence)
        + "."
        if documentation_evidence
        else "Fallback score after invalid model output. Very little documented resolution evidence is available."
    )

    summary_reason = reason.strip() or "the model failed twice"
    return TechnicianScore(
        key=issue.get("key", ""),
        communication_score=communication_score,
        communication_notes=communication_notes,
        documentation_score=documentation_score,
        documentation_notes=documentation_notes,
        score_summary=f"Fallback QA score saved because {summary_reason}.",
        model_used=model_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _parse_kb_draft(
    raw: str,
    key: str,
    model_id: str,
    existing_article: KnowledgeBaseArticle | None,
    fallback_request_type: str = "",
) -> KnowledgeBaseDraft:
    """Parse AI response JSON into a KB draft payload."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse KB draft JSON: %s", text[:200])
        raise ValueError("Model returned invalid KB draft JSON") from exc

    request_type = str(data.get("request_type", "")).strip() or fallback_request_type

    recommended_action = str(data.get("recommended_action", "")).strip().lower()
    if recommended_action not in {"update_existing", "create_new"}:
        recommended_action = "update_existing" if existing_article else "create_new"

    return KnowledgeBaseDraft(
        title=str(data.get("title", "")).strip() or (existing_article.title if existing_article else f"{key} Resolution"),
        request_type=request_type or (existing_article.request_type if existing_article else ""),
        summary=str(data.get("summary", "")).strip(),
        content=str(data.get("content", "")).strip(),
        model_used=model_id,
        source_ticket_key=key,
        suggested_article_id=existing_article.id if existing_article else None,
        suggested_article_title=existing_article.title if existing_article else "",
        recommended_action=recommended_action,
        change_summary=str(data.get("change_summary", "")).strip(),
    )


def score_closed_ticket(
    issue: dict[str, Any],
    request_comments: list[dict[str, Any]],
    model_id: str,
    *,
    queue_label: str = "",
    ollama_runtime: str | None = None,
) -> TechnicianScore:
    """Score technician communication/documentation for a closed ticket."""
    provider = _get_model_provider(model_id)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")

    ticket_key = issue.get("key", "")
    _ql = queue_label or (f"qa:{ticket_key}" if ticket_key else "qa")
    user_msg = _build_technician_score_context(issue, request_comments)
    logger.info("Scoring technician QA for %s with %s (%s)", ticket_key, model_id, provider)
    raw = invoke_model_text(
        model_id,
        TECHNICIAN_SCORE_PROMPT,
        user_msg,
        feature_surface="technician_qa",
        app_surface="tickets",
        actor_type="system",
        actor_id="technician-qa",
        max_output_tokens=_TECHNICIAN_QA_MAX_OUTPUT_TOKENS,
        json_output=True,
        metadata={"ticket_key": ticket_key},
        queue_label=_ql,
        ollama_runtime=ollama_runtime,
    )
    try:
        return _parse_technician_score(raw, ticket_key, model_id)
    except ValueError as exc:
        logger.warning("Retrying technician QA scoring for %s after invalid JSON output", ticket_key)
        retry_raw = invoke_model_text(
            model_id,
            TECHNICIAN_SCORE_RETRY_PROMPT,
            user_msg,
            feature_surface="technician_qa",
            app_surface="tickets",
            actor_type="system",
            actor_id="technician-qa",
            temperature=0.0,
            max_output_tokens=_TECHNICIAN_QA_MAX_OUTPUT_TOKENS,
            json_output=True,
            metadata={"ticket_key": ticket_key, "retry": "json_format"},
            queue_label=_ql,
            ollama_runtime=ollama_runtime,
        )
        try:
            return _parse_technician_score(retry_raw, issue.get("key", ""), model_id)
        except ValueError as retry_exc:
            logger.warning(
                "Technician QA fallback scoring for %s after repeated invalid JSON output: %s",
                issue.get("key"),
                retry_exc,
            )
            return _build_fallback_technician_score(
                issue,
                request_comments,
                model_id,
                reason=str(retry_exc or exc),
            )


def draft_kb_article(
    issue: dict[str, Any],
    request_comments: list[dict[str, Any]],
    model_id: str,
    existing_article: KnowledgeBaseArticle | None = None,
) -> KnowledgeBaseDraft:
    """Generate a KB draft from a closed ticket and optional existing article."""
    provider = _get_model_provider(model_id)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")

    user_msg = _build_kb_draft_context(issue, request_comments, existing_article)
    logger.info("Drafting KB article for %s with %s (%s)", issue.get("key"), model_id, provider)
    raw = invoke_model_text(
        model_id,
        KB_DRAFT_PROMPT,
        user_msg,
        feature_surface="kb_ticket_draft",
        app_surface="knowledge_base",
        actor_type="system",
        actor_id="kb-draft",
        max_output_tokens=_KB_TICKET_DRAFT_MAX_OUTPUT_TOKENS,
        json_output=True,
        metadata={"ticket_key": issue.get("key", ""), "existing_article_id": existing_article.id if existing_article else ""},
    )

    return _parse_kb_draft(
        raw,
        issue.get("key", ""),
        model_id,
        existing_article,
        fallback_request_type=extract_request_type_name_from_fields(issue.get("fields", {})),
    )


def draft_kb_from_sop(text: str, filename: str, model_id: str) -> KnowledgeBaseDraft:
    """Convert extracted SOP text into a KB article draft using AI."""
    provider = _get_model_provider(model_id)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")

    # Truncate to avoid token overrun on very long SOPs
    user_msg = f"Source file: {filename}\n\nSOP content:\n{text[:8000]}"
    logger.info("Drafting KB article from SOP '%s' with %s (%s)", filename, model_id, provider)
    raw = invoke_model_text(
        model_id,
        KB_SOP_PROMPT,
        user_msg,
        feature_surface="kb_sop_draft",
        app_surface="knowledge_base",
        actor_type="system",
        actor_id="kb-sop-draft",
        temperature=0.2,
        max_output_tokens=_KB_SOP_DRAFT_MAX_OUTPUT_TOKENS,
        json_output=True,
        openai_api_mode="chat_completions",
        metadata={"filename": filename},
    )

    return _parse_sop_draft(raw, filename, model_id)


def _parse_sop_draft(raw: str, filename: str, model_id: str) -> KnowledgeBaseDraft:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        import re
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group()) if m else {}
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ")
    return KnowledgeBaseDraft(
        title=str(data.get("title") or stem),
        request_type=str(data.get("request_type") or ""),
        summary=str(data.get("summary") or ""),
        content=str(data.get("content") or ""),
        model_used=model_id,
        source_ticket_key="",
        suggested_article_id=None,
        suggested_article_title="",
        recommended_action="create_new",
        change_summary=f"Converted from {filename}",
    )


def reformat_kb_article_content(article: KnowledgeBaseArticle, model_id: str) -> str:
    """Reformat an existing KB article's content as structured markdown."""
    provider = _get_model_provider(model_id)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")

    user_msg = (
        f"Article Title: {article.title}\n"
        f"Request Type: {article.request_type or 'General'}\n\n"
        f"Current content:\n{article.content}"
    )
    logger.info("Reformatting KB article %s with %s (%s)", article.id, model_id, provider)
    return invoke_model_text(
        model_id,
        KB_REFORMAT_PROMPT,
        user_msg,
        feature_surface="kb_reformat",
        app_surface="knowledge_base",
        actor_type="system",
        actor_id="kb-reformat",
        temperature=0.2,
        max_output_tokens=_KB_REFORMAT_MAX_OUTPUT_TOKENS,
        openai_api_mode="chat_completions",
        metadata={"article_id": article.id},
    ).strip()


def _compact_azure_cost_context(context: dict[str, Any]) -> dict[str, Any]:
    finops_status = context.get("finops_status") or {}
    return {
        "cost_summary": context.get("export_cost_summary") or context.get("cost_summary") or {},
        "cost_trend_summary": context.get("cost_trend_summary") or {},
        "cost_trend": list((context.get("export_cost_trend") or context.get("cost_trend") or [])[:30]),
        "cost_by_service": list((context.get("export_cost_by_service") or context.get("cost_by_service") or [])[:10]),
        "top_resources_by_cost": list((context.get("top_resources_by_cost") or [])[:10]),
        "vm_inventory_summary": {
            "total_vm_count": int((context.get("vm_inventory_summary") or {}).get("total_vm_count") or 0),
            "by_sku": list(((context.get("vm_inventory_summary") or {}).get("by_sku") or [])[:10]),
        },
        "vm_power_state_summary": context.get("vm_power_state_summary") or {},
        "advisor": list((context.get("advisor") or [])[:10]),
        "savings_summary": context.get("savings_summary") or {},
        "savings_opportunities": list((context.get("savings_opportunities") or [])[:10]),
        "data_freshness": context.get("data_freshness") or {},
        "finops_status": {
            "available": bool(finops_status.get("available")),
            "record_count": int(finops_status.get("record_count") or 0),
            "coverage_start": finops_status.get("coverage_start"),
            "coverage_end": finops_status.get("coverage_end"),
            "field_coverage": finops_status.get("field_coverage") or {},
            "ai_usage": finops_status.get("ai_usage") or {},
        },
    }


def answer_azure_cost_question(
    question: str,
    context: dict[str, Any],
    model_id: str,
    *,
    actor_type: str = "",
    actor_id: str = "",
    team: str = "",
) -> AzureCostChatResponse:
    """Answer an Azure cost-management question from grounded cached data."""
    provider = _get_model_provider(model_id)
    if not provider:
        raise ValueError(f"Unknown model: {model_id}")

    compact_context = _compact_azure_cost_context(context)
    user_msg = (
        f"Question:\n{question.strip()}\n\n"
        "Grounding data:\n"
        f"{json.dumps(compact_context, separators=(',', ':'))}"
    )

    logger.info("Answering Azure cost question with %s (%s)", model_id, provider)
    raw = invoke_model_text(
        model_id,
        AZURE_COST_COPILOT_PROMPT,
        user_msg,
        feature_surface="azure_cost_copilot",
        app_surface="azure_portal",
        actor_type=actor_type,
        actor_id=actor_id,
        team=team,
        max_output_tokens=_AZURE_COST_COPILOT_MAX_OUTPUT_TOKENS,
        metadata={"question_length": len(question.strip())},
    )

    citations = [
        AzureCitation(
            source_type="summary",
            label="Cost summary",
            detail=f"Lookback {compact_context.get('cost_summary', {}).get('lookback_days', '')} days",
        ),
        AzureCitation(
            source_type="trend",
            label="Daily trend",
            detail=f"{len(compact_context.get('cost_trend') or [])} daily points",
        ),
        AzureCitation(
            source_type="breakdown",
            label="Top services",
            detail=f"{len(compact_context.get('cost_by_service') or [])} grouped rows",
        ),
        AzureCitation(
            source_type="inventory",
            label="VM inventory by SKU",
            detail=(
                f"{len((context.get('vm_inventory_summary') or {}).get('by_sku') or [])} SKU rows"
                f" across {int((context.get('vm_inventory_summary') or {}).get('total_vm_count') or 0)} VMs"
            ),
        ),
        AzureCitation(
            source_type="advisor",
            label="Advisor recommendations",
            detail=f"{len(compact_context.get('advisor') or [])} recommendations",
        ),
        AzureCitation(
            source_type="savings",
            label="Savings opportunities",
            detail=f"{len(compact_context.get('savings_opportunities') or [])} ranked items",
        ),
    ]
    export_summary = context.get("export_cost_summary") or {}
    if export_summary:
        citations.append(
            AzureCitation(
                source_type="exports",
                label="Export-backed cost summary",
                detail=(
                    f"{export_summary.get('record_count', 0)} rows from "
                    f"{export_summary.get('window_start', '')} to {export_summary.get('window_end', '')}"
                ),
            )
        )
    return AzureCostChatResponse(
        answer=raw.strip(),
        model_used=model_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        citations=citations,
    )


# ---------------------------------------------------------------------------
# Suggestion validation against live Jira data
# ---------------------------------------------------------------------------

# TTL-cached lookups to avoid hammering the Jira API on every validation.
_priority_cache: tuple[float, set[str]] = (0.0, set())
_user_cache: tuple[float, dict[str, str]] = (0.0, {})  # display_name_lower -> accountId
_rt_cache: tuple[float, dict[str, str]] = (0.0, {})  # name -> requestTypeId
_CACHE_TTL = 600  # 10 minutes

# Service desk ID (auto-detected on first call)
_service_desk_id: str | None = None


def _get_service_desk_id() -> str:
    """Auto-detect the service desk ID for the configured project."""
    global _service_desk_id
    if _service_desk_id:
        return _service_desk_id

    from jira_client import JiraClient
    from config import JIRA_PROJECT
    client = JiraClient()
    url = f"{client.base_url}/rest/servicedeskapi/servicedesk"
    resp = client.session.get(url)
    resp.raise_for_status()
    desks = resp.json().get("values", [])
    # Prefer the desk matching the configured project key (e.g. OIT)
    for d in desks:
        if d.get("projectKey", "").upper() == JIRA_PROJECT.upper():
            _service_desk_id = str(d.get("id", "1"))
            logger.info("Auto-detected service desk ID: %s (project %s)", _service_desk_id, JIRA_PROJECT)
            return _service_desk_id
    # Fallback to first desk
    if desks:
        _service_desk_id = str(desks[0].get("id", "1"))
    else:
        _service_desk_id = "1"
    logger.info("Auto-detected service desk ID: %s (fallback)", _service_desk_id)
    return _service_desk_id


# Approved request types — only these should be assigned during triage
_APPROVED_REQUEST_TYPES: set[str] = {
    "Security Alert",
    "Get IT help",
    "Email or Outlook",
    "Password MFA Authentication",
    "Server Infrastructure Database",
    "Business Application Support",
    "VPN",
    "Backup and Storage",
    "Report a computer equipment problem",
    "Request a new user account",
    "Offboard employees",
    "Onboard new employees",
    "Phone RingCentral",
    "Virtual Desktop",
    "Request new PC software",
}


def _get_request_types() -> dict[str, str]:
    """Return {name: requestTypeId} for approved request types, cached with TTL."""
    global _rt_cache
    now = time.monotonic()
    if _rt_cache[1] and now - _rt_cache[0] < _CACHE_TTL:
        return _rt_cache[1]

    from jira_client import JiraClient
    try:
        client = JiraClient()
        sd_id = _get_service_desk_id()
        raw = client.get_request_types(sd_id)
        # Only include approved request types
        rt_map = {}
        for rt in raw:
            name = rt.get("name", "")
            rid = rt.get("id")
            if not name or not rid:
                continue
            if name in _APPROVED_REQUEST_TYPES:
                rt_map[name] = str(rid)
        _rt_cache = (now, rt_map)
        logger.info("Validation: cached %d request types: %s", len(rt_map), list(rt_map.keys()))
        return rt_map
    except Exception:
        logger.exception("Validation: failed to fetch request types")
        return {}


def get_request_type_names() -> list[str]:
    """Return list of valid request type names."""
    return list(_get_request_types().keys())


def get_request_type_id(name: str) -> str | None:
    """Return the request type ID for a given name, or None."""
    return _get_request_types().get(name)


def _get_valid_priorities() -> set[str]:
    """Return the set of valid priority names, cached with TTL."""
    global _priority_cache
    now = time.monotonic()
    if _priority_cache[1] and now - _priority_cache[0] < _CACHE_TTL:
        return _priority_cache[1]

    from jira_client import JiraClient
    try:
        client = JiraClient()
        raw = client.get_priorities()
        names = {p.get("name", "") for p in raw if p.get("name")}
        _priority_cache = (now, names)
        logger.info("Validation: cached %d valid priorities: %s", len(names), names)
        return names
    except Exception:
        logger.exception("Validation: failed to fetch priorities from Jira")
        # Fall back to hardcoded list so we don't block analysis
        return set(KNOWN_PRIORITIES)


def _get_valid_users() -> dict[str, str]:
    """Return {display_name_lower: accountId} for assignable users, cached with TTL."""
    global _user_cache
    now = time.monotonic()
    if _user_cache[1] and now - _user_cache[0] < _CACHE_TTL:
        return _user_cache[1]

    from jira_client import JiraClient
    from config import JIRA_PROJECT
    try:
        client = JiraClient()
        raw = client.get_users_assignable(JIRA_PROJECT)
        users = {
            u.get("displayName", "").lower(): u.get("accountId", "")
            for u in raw
            if u.get("displayName") and u.get("accountId")
        }
        _user_cache = (now, users)
        logger.info("Validation: cached %d assignable users", len(users))
        return users
    except Exception:
        logger.exception("Validation: failed to fetch assignable users from Jira")
        return {}


def _get_reachable_statuses(key: str) -> set[str]:
    """Return the set of status names reachable via transitions for an issue."""
    from jira_client import JiraClient
    try:
        client = JiraClient()
        transitions = client.get_transitions(key)
        names = set()
        for t in transitions:
            # Transition name (e.g. "Start Progress")
            names.add(t.get("name", "").lower())
            # Target status name (e.g. "In Progress")
            to_status = t.get("to", {})
            if isinstance(to_status, dict):
                names.add(to_status.get("name", "").lower())
        return names
    except Exception:
        logger.exception("Validation: failed to fetch transitions for %s", key)
        return set()


def validate_suggestions(key: str, suggestions: list[TriageSuggestion]) -> list[TriageSuggestion]:
    """Filter out suggestions that reference invalid priorities, users, or statuses.

    Returns the subset of suggestions that are valid. Invalid ones are logged
    and silently dropped so the user only sees actionable suggestions.
    """
    if not suggestions:
        return suggestions

    valid: list[TriageSuggestion] = []
    priorities: set[str] | None = None
    users: dict[str, str] | None = None
    reachable: set[str] | None = None

    for s in suggestions:
        if s.field == "priority":
            if priorities is None:
                priorities = _get_valid_priorities()
            if s.suggested_value not in priorities:
                logger.warning(
                    "Validation: dropping %s priority suggestion '%s' — "
                    "not in valid priorities %s",
                    key, s.suggested_value, priorities,
                )
                continue

        elif s.field == "request_type":
            valid_rts = get_request_type_names()
            if s.suggested_value not in valid_rts:
                logger.warning(
                    "Validation: dropping %s request_type suggestion '%s' — "
                    "not a valid request type",
                    key, s.suggested_value,
                )
                continue

        elif s.field == "assignee":
            if users is None:
                users = _get_valid_users()
            if s.suggested_value.lower() not in users:
                logger.warning(
                    "Validation: dropping %s assignee suggestion '%s' — "
                    "not an assignable user",
                    key, s.suggested_value,
                )
                continue

        elif s.field == "reporter":
            from jira_client import JiraClient
            try:
                account_id = JiraClient().find_user_account_id(s.suggested_value)
            except Exception:
                logger.exception("Validation: failed to resolve reporter '%s' for %s", s.suggested_value, key)
                continue
            if not account_id:
                logger.warning(
                    "Validation: dropping %s reporter suggestion '%s' — "
                    "no exact Jira user match found",
                    key, s.suggested_value,
                )
                continue

        elif s.field == "status":
            if reachable is None:
                reachable = _get_reachable_statuses(key)
            if s.suggested_value.lower() not in reachable:
                logger.warning(
                    "Validation: dropping %s status suggestion '%s' — "
                    "not a reachable transition (available: %s)",
                    key, s.suggested_value, reachable,
                )
                continue

        # comment and other fields pass through without validation
        valid.append(s)

    dropped = len(suggestions) - len(valid)
    if dropped:
        logger.info("Validation: %s — kept %d/%d suggestions (%d invalid dropped)",
                     key, len(valid), len(suggestions), dropped)
    return valid
