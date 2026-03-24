"""Guarded safe-hook runner for Azure FinOps recommendation actions."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from config import AZURE_FINOPS_SAFE_SCRIPT_HOOKS

logger = logging.getLogger(__name__)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "on"}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [_text(item) for item in value if _text(item)]
    text = _text(value)
    return [text] if text else []


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _excerpt(value: str, limit: int = 2000) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


@dataclass(frozen=True)
class SafeScriptHookDefinition:
    hook_key: str
    label: str
    description: str
    command: tuple[str, ...]
    allowed_categories: tuple[str, ...]
    allowed_opportunity_types: tuple[str, ...]
    default_dry_run: bool
    allow_apply: bool
    repeatable: bool
    timeout_seconds: int

    def applies_to(self, recommendation: Mapping[str, Any]) -> bool:
        category = _text(recommendation.get("category")).lower()
        opportunity_type = _text(recommendation.get("opportunity_type")).lower()
        if self.allowed_categories and category not in self.allowed_categories:
            return False
        if self.allowed_opportunity_types and opportunity_type not in self.allowed_opportunity_types:
            return False
        return True

    def to_option(self) -> dict[str, Any]:
        return {
            "key": self.hook_key,
            "label": self.label,
            "description": self.description,
            "default_dry_run": self.default_dry_run,
            "allow_apply": self.allow_apply,
            "repeatable": self.repeatable,
        }


class AzureFinOpsSafeHookRunner:
    """Allowlisted safe-hook execution for persisted recommendations."""

    def __init__(self, hooks_config: Mapping[str, Any] | None = None) -> None:
        self._hooks = self._normalize_hooks(hooks_config or {})

    def _normalize_hooks(self, hooks_config: Mapping[str, Any]) -> dict[str, SafeScriptHookDefinition]:
        normalized: dict[str, SafeScriptHookDefinition] = {}
        for raw_key, raw_definition in dict(hooks_config or {}).items():
            hook_key = _text(raw_key)
            if not hook_key:
                continue
            if not isinstance(raw_definition, Mapping):
                raise RuntimeError(f"Safe hook '{hook_key}' must be configured as an object")
            command = tuple(_string_list(raw_definition.get("command")))
            if not command:
                raise RuntimeError(f"Safe hook '{hook_key}' requires a non-empty command list")
            normalized[hook_key] = SafeScriptHookDefinition(
                hook_key=hook_key,
                label=_text(raw_definition.get("label")) or hook_key,
                description=_text(raw_definition.get("description")),
                command=command,
                allowed_categories=tuple(_text(item).lower() for item in _string_list(raw_definition.get("allowed_categories"))),
                allowed_opportunity_types=tuple(
                    _text(item).lower() for item in _string_list(raw_definition.get("allowed_opportunity_types"))
                ),
                default_dry_run=_bool(raw_definition.get("default_dry_run"), True),
                allow_apply=_bool(raw_definition.get("allow_apply"), False),
                repeatable=_bool(raw_definition.get("repeatable"), True),
                timeout_seconds=max(_int(raw_definition.get("timeout_seconds"), 120), 1),
            )
        return normalized

    def list_hooks_for_recommendation(self, recommendation: Mapping[str, Any]) -> list[dict[str, Any]]:
        options = [definition.to_option() for definition in self._hooks.values() if definition.applies_to(recommendation)]
        return sorted(options, key=lambda item: (_text(item.get("label")).lower(), _text(item.get("key")).lower()))

    def execute_hook(
        self,
        recommendation: Mapping[str, Any],
        *,
        hook_key: str,
        dry_run: bool = True,
        actor_id: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        applicable_definitions = {
            definition.hook_key: definition
            for definition in self._hooks.values()
            if definition.applies_to(recommendation)
        }
        if not applicable_definitions:
            raise ValueError("No safe remediation hooks are configured for this recommendation.")

        hook_key = _text(hook_key)
        if not hook_key:
            if len(applicable_definitions) == 1:
                hook_key = next(iter(applicable_definitions))
            else:
                raise ValueError("A hook key is required when multiple safe remediation hooks are available.")

        definition = applicable_definitions.get(hook_key)
        if definition is None:
            raise ValueError("The selected safe remediation hook is not available for this recommendation.")
        if not dry_run and not definition.allow_apply:
            raise ValueError("This safe remediation hook only supports dry-run execution.")

        started_at = _utcnow()
        payload = {
            "hook": definition.to_option(),
            "execution": {
                "dry_run": bool(dry_run),
                "actor_id": _text(actor_id),
                "note": _text(note),
                "requested_at": started_at.isoformat(),
            },
            "recommendation": json.loads(json.dumps(dict(recommendation), default=str)),
        }

        try:
            completed = subprocess.run(
                list(definition.command),
                input=json.dumps(payload, sort_keys=True),
                text=True,
                capture_output=True,
                timeout=definition.timeout_seconds,
                shell=False,
                check=False,
            )
            completed_at = _utcnow()
            stdout_text = _text(completed.stdout)
            stderr_text = _text(completed.stderr)
            output_excerpt = _excerpt(stdout_text or stderr_text)
            if stdout_text:
                try:
                    stdout_payload = json.loads(stdout_text)
                except json.JSONDecodeError:
                    stdout_payload = None
                if isinstance(stdout_payload, Mapping):
                    output_excerpt = _excerpt(
                        _text(stdout_payload.get("summary"))
                        or _text(stdout_payload.get("message"))
                        or stdout_text
                    )
            action_status = "dry_run" if dry_run else "completed"
            success = completed.returncode == 0
            error = ""
            if not success:
                action_status = "failed"
                error = stderr_text or stdout_text or f"Safe remediation hook exited with code {completed.returncode}."
        except subprocess.TimeoutExpired as exc:
            completed_at = _utcnow()
            stdout_text = _text(exc.stdout)
            stderr_text = _text(exc.stderr)
            output_excerpt = _excerpt(stderr_text or stdout_text)
            success = False
            action_status = "failed"
            error = f"Safe remediation hook timed out after {definition.timeout_seconds} seconds."
        except Exception as exc:  # pragma: no cover - defensive
            completed_at = _utcnow()
            stdout_text = ""
            stderr_text = ""
            output_excerpt = ""
            success = False
            action_status = "failed"
            error = str(exc)
            logger.exception("Safe remediation hook %s failed before completion", hook_key)

        duration_ms = max(int((completed_at - started_at).total_seconds() * 1000), 0)
        return {
            "hook_key": definition.hook_key,
            "hook_label": definition.label,
            "description": definition.description,
            "dry_run": bool(dry_run),
            "allow_apply": definition.allow_apply,
            "repeatable": definition.repeatable,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_ms": duration_ms,
            "exit_code": completed.returncode if "completed" in locals() else None,
            "success": success,
            "action_status": action_status,
            "output_excerpt": output_excerpt,
            "stdout_excerpt": _excerpt(stdout_text),
            "stderr_excerpt": _excerpt(stderr_text),
            "error": _text(error),
        }


azure_finops_safe_hook_runner = AzureFinOpsSafeHookRunner(AZURE_FINOPS_SAFE_SCRIPT_HOOKS)
