"""Example non-destructive safe hook for Azure FinOps recommendations.

This script reads a JSON payload from stdin and prints a short JSON response.
It is intended as a dry-run starter hook for operator validation and docs.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def main() -> int:
    payload = json.load(sys.stdin)
    hook = payload.get("hook") or {}
    execution = payload.get("execution") or {}
    recommendation = payload.get("recommendation") or {}

    hook_label = _text(hook.get("label") or hook.get("key") or "safe hook")
    resource_name = _text(recommendation.get("resource_name") or recommendation.get("title") or "recommendation")
    mode = "dry run" if bool(execution.get("dry_run", True)) else "apply"

    result = {
        "status": "ok",
        "summary": f"{hook_label} completed in {mode} mode for {resource_name}.",
        "recommendation_id": _text(recommendation.get("id")),
    }
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
