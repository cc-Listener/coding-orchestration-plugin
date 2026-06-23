from __future__ import annotations

import shutil
from typing import Any

from ..presenters.doctor_presenter import (
    format_lark_preflight,
    format_project_mcp_preflight as render_project_mcp_preflight,
    format_source_resolve as render_source_resolve,
    render_doctor_summary,
)
from ..feishu.feishu_project_mcp import FeishuProjectMcpConfig
from ..models import RunMode


def command_coding_cli(host: Any, args: Any = None) -> str:
    if args is None:
        parts: list[str] = []
    elif isinstance(args, str):
        parts = args.split()
    else:
        parts = [str(part) for part in args]
    command = parts[0] if parts else "status"
    rest = parts[1:]
    if command == "doctor":
        return command_coding_doctor(host)
    if command == "lark-preflight":
        return format_lark_preflight_result(host.tool_lark_preflight({}))
    if command == "project-mcp-preflight":
        return format_project_mcp_preflight(host)
    if command == "source-resolve":
        return format_source_resolve(host, " ".join(rest))
    if command == "status":
        return host.command_coding_status(" ".join(rest)) if rest else host.command_coding_list("")
    return "Usage: hermes coding <doctor|status|lark-preflight|project-mcp-preflight|source-resolve>"


def command_coding_doctor(host: Any) -> str:
    lark = host.tool_lark_preflight({})
    project_mcp = host.tool_project_mcp_preflight({"include_tools": False})
    kanban_available = bool(getattr(getattr(host, "kanban_bridge", None), "available", lambda: False)())
    runtime_available = hermes_runtime_available(host)
    router = getattr(host, "runner_router", None)
    default_runner = str(getattr(router, "default_runner", "unknown"))
    try:
        codex_decision = router.codex_backend_decision(RunMode.IMPLEMENTATION) if router else None
    except Exception:
        codex_decision = None
    codex_backend = getattr(codex_decision, "backend", "unknown")
    hermes_provider = getattr(codex_decision, "hermes_provider", "")
    return render_doctor_summary(
        lark=lark,
        project_mcp=project_mcp,
        kanban_available=kanban_available,
        runtime_available=runtime_available,
        default_runner=default_runner,
        codex_backend=codex_backend,
        hermes_provider=hermes_provider,
    )


def format_lark_preflight_result(result: dict[str, Any]) -> str:
    return format_lark_preflight(result)


def project_mcp_preflight_config(host: Any) -> FeishuProjectMcpConfig:
    return host._project_mcp_adapter().config


def project_mcp_preflight_command_available(config: FeishuProjectMcpConfig) -> bool:
    if config.transport != "stdio":
        return True
    command = config.command[0] if config.command else "npx"
    return shutil.which(command) is not None


def format_project_mcp_preflight(host: Any) -> str:
    config = host.project_mcp_preflight_config()
    command_available = host.project_mcp_preflight_command_available(config)
    result: dict[str, Any] | None = None
    if _should_dispatch_project_mcp_preflight(config, command_available):
        result = host.tool_project_mcp_preflight({"include_tools": True})
    return render_project_mcp_preflight(
        config,
        command_available=command_available,
        result=result,
    )


def format_source_resolve(host: Any, text: str) -> str:
    if not text.strip():
        return "Usage: hermes coding source-resolve <feishu_or_meegle_url>"
    result = host.tool_source_resolve({"text": text})
    return render_source_resolve(result)


def hermes_runtime_available(host: Any) -> bool:
    for runner in getattr(getattr(host, "runner_router", None), "runners", {}).values():
        runtime = getattr(runner, "hermes_runtime", None)
        if runtime is not None and runtime.available():
            return True
    return False


def gateway_immediate_route_message(host: Any, handler_key: str, raw_args: str) -> str | None:
    handlers = {
        "doctor": lambda: command_coding_doctor(host),
        "lark_preflight": lambda: format_lark_preflight_result(host.tool_lark_preflight({})),
        "project_mcp_preflight": lambda: format_project_mcp_preflight(host),
        "source_resolve": lambda: format_source_resolve(host, raw_args),
    }
    handler = handlers.get(handler_key)
    return handler() if handler is not None else None


def _should_dispatch_project_mcp_preflight(config: Any, command_available: bool) -> bool:
    return bool(config.enabled) and bool(str(config.token or "").strip()) and (
        config.transport != "stdio" or command_available
    )
