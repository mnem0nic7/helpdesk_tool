from __future__ import annotations

import sys
from pathlib import Path

from azure_finops_safe_hooks import AzureFinOpsSafeHookRunner


def _example_hook_command() -> list[str]:
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "azure_finops_safe_hook_echo.py"
    return [sys.executable, str(script_path)]


def test_safe_hook_runner_lists_matching_hooks():
    runner = AzureFinOpsSafeHookRunner(
        {
            "vm_echo": {
                "label": "VM Echo",
                "description": "Dry-run VM hook.",
                "command": _example_hook_command(),
                "allowed_categories": ["compute"],
                "allowed_opportunity_types": ["rightsizing"],
            },
            "storage_echo": {
                "label": "Storage Echo",
                "description": "Dry-run storage hook.",
                "command": _example_hook_command(),
                "allowed_categories": ["storage"],
            },
        }
    )

    options = runner.list_hooks_for_recommendation(
        {"category": "compute", "opportunity_type": "rightsizing", "resource_name": "vm-1"}
    )

    assert [row["key"] for row in options] == ["vm_echo"]
    assert options[0]["default_dry_run"] is True
    assert options[0]["allow_apply"] is False


def test_safe_hook_runner_executes_dry_run_hook():
    runner = AzureFinOpsSafeHookRunner(
        {
            "vm_echo": {
                "label": "VM Echo",
                "description": "Dry-run VM hook.",
                "command": _example_hook_command(),
                "allowed_categories": ["compute"],
            }
        }
    )

    result = runner.execute_hook(
        {"id": "rec-1", "category": "compute", "opportunity_type": "rightsizing", "resource_name": "vm-1"},
        hook_key="vm_echo",
        dry_run=True,
        actor_id="admin@example.com",
        note="Preview the remediation path.",
    )

    assert result["success"] is True
    assert result["action_status"] == "dry_run"
    assert result["hook_label"] == "VM Echo"
    assert "completed in dry run mode" in result["output_excerpt"]


def test_safe_hook_runner_rejects_apply_when_hook_is_dry_run_only():
    runner = AzureFinOpsSafeHookRunner(
        {
            "vm_echo": {
                "label": "VM Echo",
                "command": _example_hook_command(),
                "allowed_categories": ["compute"],
                "allow_apply": False,
            }
        }
    )

    try:
        runner.execute_hook(
            {"id": "rec-1", "category": "compute", "opportunity_type": "rightsizing", "resource_name": "vm-1"},
            hook_key="vm_echo",
            dry_run=False,
        )
    except ValueError as exc:
        assert "dry-run" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected ValueError for apply execution on a dry-run-only hook")
