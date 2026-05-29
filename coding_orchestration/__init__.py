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
        "coding",
        orchestrator.command_coding,
        description="Coding orchestration command group",
        args_hint="<task|status|list|use|exit|continue|change|bugfix|run|implement|complete|cancel|delete|prepare-merge-test|merge-test|help>",
    )


__all__ = ["register"]
