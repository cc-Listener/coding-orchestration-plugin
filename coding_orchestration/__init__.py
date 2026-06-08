"""Hermes coding orchestration user plugin.

Source is intended to live in a normal project checkout and be symlinked into
``~/.hermes/plugins/coding_orchestration``.
"""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

from .cli import register_cli
from .orchestrator import CodingOrchestrator
from .plugin_tools import register_coding_tools


_REGISTRY_FLAG = "_hermes_coding_orchestration_registered"
_BUILTIN_TOOLS_REGISTERED = False


def register(ctx: Any) -> None:
    """Hermes plugin entry point."""
    if getattr(builtins, _REGISTRY_FLAG, False):
        return
    setattr(builtins, _REGISTRY_FLAG, True)

    try:
        _register_once(ctx)
    except Exception:
        if getattr(builtins, _REGISTRY_FLAG, False):
            delattr(builtins, _REGISTRY_FLAG)
        raise


def _register_once(ctx: Any) -> None:
    orchestrator = CodingOrchestrator.from_default_config()
    if hasattr(ctx, "dispatch_tool") and hasattr(orchestrator, "set_dispatch_tool"):
        orchestrator.set_dispatch_tool(_wrap_dispatch_tool(ctx.dispatch_tool))

    def pre_gateway_dispatch(event: Any, gateway: Any = None, session_store: Any = None) -> dict | None:
        return orchestrator.handle_gateway_event(
            event=event,
            gateway=gateway,
            session_store=session_store,
        )

    ctx.register_hook("pre_gateway_dispatch", pre_gateway_dispatch)
    if hasattr(orchestrator, "pre_llm_call"):
        ctx.register_hook("pre_llm_call", orchestrator.pre_llm_call)
    ctx.register_command(
        "coding",
        orchestrator.command_coding,
        description="Coding orchestration command group",
        args_hint="<task|project|status|list|use|exit|continue|change|bugfix|run|implement|qa|complete|cancel|delete|prepare-merge-test|merge-test|help>",
    )
    register_coding_tools(ctx, orchestrator)
    register_cli(ctx, orchestrator)
    if hasattr(ctx, "register_skill"):
        ctx.register_skill(
            "hermes-coding-operator",
            Path(__file__).parent / "skills" / "hermes-coding-operator" / "SKILL.md",
            description="Handle low-confidence Hermes Coding Mode handoff.",
        )


def _wrap_dispatch_tool(dispatch_tool: Any):
    def dispatch_with_builtin_tools(name: str, args: dict, *positional: Any, **kwargs: Any):
        _ensure_builtin_tools_registered()
        return dispatch_tool(name, args, *positional, **kwargs)

    return dispatch_with_builtin_tools


def _ensure_builtin_tools_registered() -> None:
    """Ensure Hermes core tools are imported before plugin code dispatches them."""
    global _BUILTIN_TOOLS_REGISTERED
    if _BUILTIN_TOOLS_REGISTERED:
        return
    try:
        from tools.registry import discover_builtin_tools, registry
    except Exception:
        return
    if registry.get_entry("terminal") is not None:
        _BUILTIN_TOOLS_REGISTERED = True
        return
    discover_builtin_tools()
    if registry.get_entry("terminal") is not None:
        _BUILTIN_TOOLS_REGISTERED = True


__all__ = ["register"]
