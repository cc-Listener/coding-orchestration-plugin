from __future__ import annotations

from typing import Any

from .doctor_presenter import format_lark_preflight, format_project_mcp_preflight, format_source_resolve
from .task_status_presenter import format_task_status_payload


def register_cli(ctx: Any, orchestrator: Any) -> None:
    """Register Hermes CLI subcommands when available."""
    register_cli_command = getattr(ctx, "register_cli_command", None)
    if not callable(register_cli_command):
        return

    _register_cli_command(
        register_cli_command,
        name="coding",
        help="Inspect and repair Hermes coding orchestration state.",
        setup_fn=_setup_coding_cli,
        handler_fn=lambda args: _handle_coding_cli(orchestrator, args),
        description="Inspect coding task state, source preflight, and Hermes/Codex runtime readiness.",
    )


def _setup_coding_cli(subparser: Any) -> None:
    subcommands = subparser.add_subparsers(dest="coding_command")
    subcommands.add_parser("doctor", help="Report Lark, Kanban, Hermes runtime, and Codex readiness.")
    subcommands.add_parser("lark-preflight", help="Check lark-cli source-readiness.")
    subcommands.add_parser("project-mcp-preflight", help="Check Feishu Project MCP configuration and readiness.")

    status_parser = subcommands.add_parser("status", help="Show current or specific coding task status.")
    status_parser.add_argument("task_id", nargs="?", default="")

    source_parser = subcommands.add_parser("source-resolve", help="Resolve a Feishu/Lark/Meegle source URL.")
    source_parser.add_argument("source", nargs="+")


def _handle_coding_cli(orchestrator: Any, args: Any) -> int:
    command = str(getattr(args, "coding_command", "") or "status")
    direct_output = _handle_tool_equivalent_cli(orchestrator, command, args)
    if direct_output is not None:
        print(direct_output)
        if command == "project-mcp-preflight" and "状态：❌" in direct_output:
            return 1
        return 0

    parts = [command]
    if command == "source-resolve":
        parts.extend(str(part) for part in getattr(args, "source", []))
    elif command == "status":
        task_id = str(getattr(args, "task_id", "") or "").strip()
        if task_id:
            parts.append(task_id)

    output = orchestrator.command_coding_cli(parts)
    print(output)
    if command == "project-mcp-preflight" and "状态：❌" in output:
        return 1
    return 2 if output.startswith("Usage:") else 0


def _handle_tool_equivalent_cli(orchestrator: Any, command: str, args: Any) -> str | None:
    dispatch = getattr(orchestrator, "dispatch_tool_operation", None)
    if not callable(dispatch):
        return None
    if command == "lark-preflight":
        return format_lark_preflight(dispatch("source.lark_preflight", {}))
    if command == "source-resolve":
        text = " ".join(str(part) for part in getattr(args, "source", [])).strip()
        if not text:
            return "Usage: hermes coding source-resolve <feishu_or_meegle_url>"
        return format_source_resolve(dispatch("source.resolve", {"text": text}))
    if command == "status":
        task_id = str(getattr(args, "task_id", "") or "").strip()
        if not task_id:
            return None
        return format_task_status_payload(dispatch("task.status", {"task_id": task_id}))
    if command == "project-mcp-preflight":
        config_reader = getattr(orchestrator, "project_mcp_preflight_config", None)
        command_checker = getattr(orchestrator, "project_mcp_preflight_command_available", None)
        if not callable(config_reader) or not callable(command_checker):
            return None
        config = config_reader()
        command_available = bool(command_checker(config))
        result = None
        if _should_dispatch_project_mcp_preflight(config, command_available):
            result = dispatch("project.mcp_preflight", {"include_tools": True})
        return format_project_mcp_preflight(
            config,
            command_available=command_available,
            result=result,
        )
    return None


def _register_cli_command(register_cli_command: Any, **kwargs: Any) -> None:
    try:
        register_cli_command(**kwargs)
    except TypeError:
        name = kwargs["name"]
        handler_fn = kwargs["handler_fn"]
        register_cli_command(name, handler_fn, help=kwargs.get("help", ""))


def _should_dispatch_project_mcp_preflight(config: Any, command_available: bool) -> bool:
    enabled = bool(getattr(config, "enabled", False))
    token_configured = bool(str(getattr(config, "token", "") or "").strip())
    transport_ready = getattr(config, "transport", "") != "stdio" or command_available
    return enabled and token_configured and transport_ready
