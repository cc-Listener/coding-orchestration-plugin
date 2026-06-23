"""Hermes CLI registration boundary."""

from .registration import (
    _handle_coding_cli,
    _handle_tool_equivalent_cli,
    _register_cli_command,
    _setup_coding_cli,
    _should_dispatch_project_mcp_preflight,
    register_cli,
)

__all__ = ["register_cli"]
