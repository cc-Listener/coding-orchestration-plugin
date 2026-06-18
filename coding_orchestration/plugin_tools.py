from __future__ import annotations

from typing import Any, Callable

from .tool_specs import ToolSpec, coding_tool_specs


TOOLSET = "coding_orchestration"


_OPERATION_METHODS = {
    "task.create": "tool_task_create",
    "task.status": "tool_task_status",
    "task.run": "tool_task_run",
    "source.resolve": "tool_source_resolve",
    "source.lark_preflight": "tool_lark_preflight",
    "project.mcp_preflight": "tool_project_mcp_preflight",
    "project.workitem_search": "tool_project_workitem_search",
    "project.workitem_create": "tool_project_workitem_create",
    "project.intake_sync": "tool_project_intake_sync",
    "project.wbs_update": "tool_project_wbs_update",
    "project.state_transition": "tool_project_state_transition",
    "project.bugfix_intake": "tool_project_bugfix_intake",
}


def register_coding_tools(ctx: Any, orchestrator: Any) -> None:
    """Register Hermes-native tools when the host supports plugin tools."""
    register_tool = getattr(ctx, "register_tool", None)
    if not callable(register_tool):
        return

    for spec in coding_tool_specs():
        _register_tool(
            register_tool,
            name=spec.name,
            schema=spec.schema(),
            handler=_handler_for(orchestrator, spec),
            description=spec.description,
        )


def _handler_for(orchestrator: Any, spec: ToolSpec) -> Callable[..., Any]:
    method_name = _OPERATION_METHODS[spec.operation_id]

    def handler(args: Any = None, **kwargs: Any) -> Any:
        method = getattr(orchestrator, method_name)
        return method(_coerce_tool_args(args, kwargs))

    return handler


def _coerce_tool_args(args: Any = None, kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(args) if isinstance(args, dict) else {}
    for key, value in (kwargs or {}).items():
        if key.startswith("_"):
            continue
        payload[key] = value
    return payload


def _register_tool(register_tool: Callable[..., Any], **kwargs: Any) -> None:
    kwargs.setdefault("toolset", TOOLSET)
    try:
        register_tool(**kwargs)
    except TypeError:
        positional_kwargs = dict(kwargs)
        name = positional_kwargs.pop("name")
        try:
            register_tool(name, **positional_kwargs)
        except TypeError:
            legacy_kwargs = {
                key: value
                for key, value in kwargs.items()
                if key in {"name", "handler", "description"}
            }
            register_tool(**legacy_kwargs)
