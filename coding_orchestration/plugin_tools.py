from __future__ import annotations

from typing import Any, Callable

from .tools.tool_operation_dispatcher import ToolOperationDispatcher
from .tools.tool_specs import ToolSpec, coding_tool_specs


TOOLSET = "coding_orchestration"


def register_coding_tools(
    ctx: Any,
    orchestrator: Any,
    *,
    dispatcher: ToolOperationDispatcher | None = None,
) -> None:
    """Register Hermes-native tools when the host supports plugin tools."""
    register_tool = getattr(ctx, "register_tool", None)
    if not callable(register_tool):
        return

    specs = coding_tool_specs()
    tool_dispatcher = dispatcher or _dispatcher_from_host(orchestrator, specs)
    for spec in specs:
        _register_tool(
            register_tool,
            name=spec.name,
            schema=spec.schema(),
            handler=_handler_for(tool_dispatcher, spec),
            description=spec.description,
        )


def _handler_for(dispatcher: ToolOperationDispatcher, spec: ToolSpec) -> Callable[..., Any]:
    dispatcher.require_operation(spec.operation_id)

    def handler(args: Any = None, **kwargs: Any) -> Any:
        return dispatcher.dispatch(spec.operation_id, _coerce_tool_args(args, kwargs))

    return handler


def _dispatcher_from_host(orchestrator: Any, specs: list[ToolSpec]) -> ToolOperationDispatcher:
    dispatch_tool_operation = getattr(orchestrator, "dispatch_tool_operation")
    return ToolOperationDispatcher(
        {
            spec.operation_id: _host_operation_handler(dispatch_tool_operation, spec.operation_id)
            for spec in specs
        }
    )


def _host_operation_handler(
    dispatch_tool_operation: Callable[..., Any],
    operation_id: str,
) -> Callable[[dict[str, Any]], Any]:
    def handler(args: dict[str, Any]) -> Any:
        return dispatch_tool_operation(operation_id, args)

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
