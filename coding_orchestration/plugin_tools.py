from __future__ import annotations

from typing import Any, Callable


TOOLSET = "coding_orchestration"


_TASK_CREATE_PARAMETERS = {
    "type": "object",
    "properties": {
        "requirement": {"type": "string", "description": "Task requirement text."},
        "text": {"type": "string", "description": "Alias for requirement."},
        "project": {"type": "string", "description": "Known Hermes coding project name or path."},
        "runner": {"type": "string", "description": "Optional runner override."},
        "source_url": {"type": "string", "description": "Optional Feishu/Lark/Meegle source URL."},
        "url": {"type": "string", "description": "Alias for source_url."},
    },
    "required": ["requirement"],
    "additionalProperties": True,
}

_TASK_STATUS_PARAMETERS = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "Hermes coding task id."},
    },
    "required": ["task_id"],
    "additionalProperties": True,
}

_TASK_RUN_PARAMETERS = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "Hermes coding task id."},
        "mode": {
            "type": "string",
            "description": "Run mode: plan_only, implementation, merge_test, implement, or merge-test.",
        },
    },
    "required": ["task_id"],
    "additionalProperties": True,
}

_SOURCE_RESOLVE_PARAMETERS = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "Feishu/Lark/Meegle source URL."},
        "text": {"type": "string", "description": "Text containing a source URL."},
    },
    "additionalProperties": True,
}

_LARK_PREFLIGHT_PARAMETERS = {
    "type": "object",
    "properties": {
        "source_url": {"type": "string", "description": "Optional source URL to include in preflight context."},
    },
    "additionalProperties": True,
}


def _tool_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": parameters,
    }


def register_coding_tools(ctx: Any, orchestrator: Any) -> None:
    """Register Hermes-native tools when the host supports plugin tools."""
    register_tool = getattr(ctx, "register_tool", None)
    if not callable(register_tool):
        return

    _register_tool(
        register_tool,
        name="coding_task_create",
        schema=_tool_schema(
            "coding_task_create",
            "Create a Hermes coding task with source/project preflight.",
            _TASK_CREATE_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_task_create(_coerce_tool_args(args, kwargs)),
        description="Create a Hermes coding task with source/project preflight.",
    )
    _register_tool(
        register_tool,
        name="coding_task_status",
        schema=_tool_schema(
            "coding_task_status",
            "Read coding task status, source health, runner state, and next actions.",
            _TASK_STATUS_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_task_status(_coerce_tool_args(args, kwargs)),
        description="Read coding task status, source health, runner state, and next actions.",
    )
    _register_tool(
        register_tool,
        name="coding_task_run",
        schema=_tool_schema(
            "coding_task_run",
            "Start or continue a coding task run through Hermes runtime.",
            _TASK_RUN_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_task_run(_coerce_tool_args(args, kwargs)),
        description="Start or continue a coding task run through Hermes runtime.",
    )
    _register_tool(
        register_tool,
        name="coding_source_resolve",
        schema=_tool_schema(
            "coding_source_resolve",
            "Resolve Feishu/Lark/Meegle source URLs before handing work to a coding runner.",
            _SOURCE_RESOLVE_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_source_resolve(_coerce_tool_args(args, kwargs)),
        description="Resolve Feishu/Lark/Meegle source URLs before handing work to a coding runner.",
    )
    _register_tool(
        register_tool,
        name="coding_lark_preflight",
        schema=_tool_schema(
            "coding_lark_preflight",
            "Check lark-cli document auth and source-readiness for coding tasks.",
            _LARK_PREFLIGHT_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_lark_preflight(_coerce_tool_args(args, kwargs)),
        description="Check lark-cli document auth and source-readiness for coding tasks.",
    )


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
