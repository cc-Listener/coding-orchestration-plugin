"""Hermes coding orchestration user plugin.

Source is intended to live in a normal project checkout and be symlinked into
``~/.hermes/plugins/coding_orchestration``.
"""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

from .orchestrator import CodingOrchestrator


_REGISTRY_FLAG = "_hermes_coding_orchestration_registered"


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

    def pre_gateway_dispatch(event: Any, gateway: Any = None, session_store: Any = None) -> dict | None:
        return orchestrator.handle_gateway_event(
            event=event,
            gateway=gateway,
            session_store=session_store,
        )

    ctx.register_hook("pre_gateway_dispatch", pre_gateway_dispatch)
    ctx.register_command(
        "coding",
        orchestrator.command_coding,
        description="Coding orchestration command group",
        args_hint="<task|project|status|list|use|exit|continue|change|bugfix|run|implement|complete|cancel|delete|prepare-merge-test|merge-test|help>",
    )
    if hasattr(ctx, "register_skill"):
        ctx.register_skill(
            "hermes-coding-operator",
            Path(__file__).parent / "skills" / "hermes-coding-operator" / "SKILL.md",
            description="Handle low-confidence Hermes Coding Mode handoff.",
        )


__all__ = ["register"]
