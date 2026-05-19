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

    def command_commands(ctx_data: Any) -> dict[str, str] | None:
        raw_args = ""
        if isinstance(ctx_data, dict):
            raw_args = str(ctx_data.get("raw_args") or ctx_data.get("args") or "")
        return {
            "decision": "handled",
            "message": orchestrator.command_commands_listing(raw_args),
        }

    ctx.register_hook("pre_gateway_dispatch", pre_gateway_dispatch)
    ctx.register_hook("command:commands", command_commands)
    ctx.register_command(
        "coding",
        orchestrator.command_coding,
        description="Coding orchestration command group",
        args_hint="<task|status|list|use|exit|continue|bugfix|run|implement|cancel|delete|prepare-merge-test|merge-test|help>",
    )
    ctx.register_command(
        "coding-help",
        orchestrator.command_coding_help,
        description="Show coding orchestration command help",
        args_hint="",
    )
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
        "coding-list",
        orchestrator.command_coding_list,
        description="List active coding tasks",
        args_hint="",
    )
    ctx.register_command(
        "coding-use",
        orchestrator.command_coding_use,
        description="Switch the active coding task in a Feishu session",
        args_hint="<task_id>",
    )
    ctx.register_command(
        "coding-exit",
        orchestrator.command_coding_exit,
        description="Exit coding mode for the current Feishu session",
        args_hint="",
    )
    ctx.register_command(
        "coding-continue",
        orchestrator.command_coding_continue,
        description="Append feedback to the active coding task",
        args_hint="<feedback>",
    )
    ctx.register_command(
        "coding-bugfix",
        orchestrator.command_coding_bugfix,
        description="Append bugfix feedback to the active coding task",
        args_hint="<feedback>",
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
        "coding-delete",
        orchestrator.command_coding_delete,
        description="Delete a coding task and clear its active binding",
        args_hint="<task_id> [--keep-artifacts] [--keep-wiki] [--force]",
    )
    ctx.register_command(
        "coding-prepare-merge-test",
        orchestrator.command_prepare_merge_test,
        description="Show manual merge-to-test instructions for a reviewed task",
        args_hint="<task_id>",
    )
    ctx.register_command(
        "coding-merge-test",
        orchestrator.command_coding_merge_test,
        description="Resume Codex and merge the reviewed source branch into test",
        args_hint="<task_id>",
    )
    ctx.register_command(
        "codex-task",
        orchestrator.command_codex_task,
        description="Compatibility alias for /coding task --runner codex_cli",
        args_hint="<request>",
    )
    ctx.register_command(
        "codex-status",
        orchestrator.command_coding_status,
        description="Compatibility alias for /coding status",
        args_hint="<task_id>",
    )
    ctx.register_command(
        "codex-list",
        orchestrator.command_coding_list,
        description="Compatibility alias for /coding list",
        args_hint="",
    )
    ctx.register_command(
        "codex-use",
        orchestrator.command_coding_use,
        description="Compatibility alias for /coding use",
        args_hint="<task_id>",
    )
    ctx.register_command(
        "codex-cancel",
        orchestrator.command_coding_cancel,
        description="Compatibility alias for /coding cancel",
        args_hint="<task_id|run_id>",
    )
    ctx.register_command(
        "codex-delete",
        orchestrator.command_coding_delete,
        description="Compatibility alias for /coding delete",
        args_hint="<task_id> [--keep-artifacts] [--keep-wiki] [--force]",
    )


__all__ = ["register"]
