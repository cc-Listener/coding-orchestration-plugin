"""Hermes coding orchestration user plugin.

Source is intended to live in a normal project checkout and be symlinked into
``~/.hermes/plugins/coding_orchestration``.
"""

from __future__ import annotations

from typing import Any

from .orchestrator import CodingOrchestrator


def register(ctx: Any) -> None:
    """Hermes plugin entry point."""
    orchestrator = CodingOrchestrator.from_default_config()

    def pre_gateway_dispatch(event: Any, gateway: Any = None, session_store: Any = None) -> dict | None:
        return orchestrator.handle_gateway_event(
            event=event,
            gateway=gateway,
            session_store=session_store,
        )

    ctx.register_hook("pre_gateway_dispatch", pre_gateway_dispatch)
    ctx.register_command(
        "coding-task",
        orchestrator.command_coding_task,
        description="Create a controlled coding task",
        args_hint="<request>",
    )
    ctx.register_command(
        "coding-status",
        orchestrator.command_coding_status,
        description="Show coding task status",
        args_hint="<task_id>",
    )
    ctx.register_command(
        "coding-run",
        orchestrator.command_coding_run,
        description="Start a plan-only coding run for an existing task",
        args_hint="<task_id>",
    )
    ctx.register_command(
        "coding-implement",
        orchestrator.command_coding_implement,
        description="Start an implementation coding run for an existing task",
        args_hint="<task_id>",
    )
    ctx.register_command(
        "coding-cancel",
        orchestrator.command_coding_cancel,
        description="Cancel a coding run",
        args_hint="<task_id|run_id>",
    )
    ctx.register_command(
        "coding-prepare-merge-test",
        orchestrator.command_prepare_merge_test,
        description="Show manual merge-to-test instructions for a reviewed task",
        args_hint="<task_id>",
    )
    ctx.register_command(
        "codex-task",
        orchestrator.command_codex_task,
        description="Compatibility alias for /coding-task --runner codex_cli",
        args_hint="<request>",
    )
    ctx.register_command(
        "codex-status",
        orchestrator.command_coding_status,
        description="Compatibility alias for /coding-status",
        args_hint="<task_id>",
    )
    ctx.register_command(
        "codex-cancel",
        orchestrator.command_coding_cancel,
        description="Compatibility alias for /coding-cancel",
        args_hint="<task_id|run_id>",
    )


__all__ = ["register"]
