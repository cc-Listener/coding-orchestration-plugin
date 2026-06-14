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
            "description": "Run mode: plan_only, implementation, qa, test, merge_test, implement, or merge-test.",
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

_PROJECT_MCP_PREFLIGHT_PARAMETERS = {
    "type": "object",
    "properties": {
        "include_tools": {"type": "boolean", "description": "Whether to include MCP tools/list in the response."},
    },
    "additionalProperties": True,
}

_PROJECT_WORKITEM_SEARCH_PARAMETERS = {
    "type": "object",
    "properties": {
        "space": {"type": "string", "description": "Feishu Project space name or URL."},
        "project": {"type": "string", "description": "Alias for space."},
        "workitem_type": {"type": "string", "description": "需求 / 缺陷 / story / issue / task."},
        "type": {"type": "string", "description": "Alias for workitem_type."},
        "query": {"type": "string", "description": "Natural language or MQL search condition."},
        "limit": {"type": "integer", "description": "Max result count."},
    },
    "additionalProperties": True,
}

_PROJECT_WORKITEM_CREATE_PARAMETERS = {
    "type": "object",
    "properties": {
        "space": {"type": "string", "description": "Feishu Project space name or URL."},
        "workitem_type": {"type": "string", "description": "需求 / 缺陷 / story / issue / task."},
        "title": {"type": "string", "description": "Work item title."},
        "fields": {"type": "object", "description": "Feishu Project field values."},
        "confirm_write": {"type": "boolean", "description": "Must be true before MCP write calls are made."},
        "idempotency_key": {"type": "string", "description": "Optional idempotency key for caller-side retry control."},
    },
    "required": ["space", "workitem_type", "title"],
    "additionalProperties": True,
}

_PROJECT_INTAKE_SYNC_PARAMETERS = {
    "type": "object",
    "properties": {
        "rule": {
            "type": "object",
            "description": "Intake rule with name, space, workitem_type/type, mql/query and optional create_coding_task.",
        },
        "dry_run": {"type": "boolean", "description": "When true, search only and do not create Hermes tasks."},
        "max_items": {"type": "integer", "description": "Maximum work items to process from the search result."},
        "confirm_write_back": {
            "type": "boolean",
            "description": "Reserved for future Feishu Project status writeback after task creation.",
        },
    },
    "required": ["rule"],
    "additionalProperties": True,
}

_PROJECT_WBS_UPDATE_PARAMETERS = {
    "type": "object",
    "properties": {
        "workitem_url": {"type": "string", "description": "Feishu Project source work item URL."},
        "space": {"type": "string", "description": "Optional Feishu Project space."},
        "workitem_name": {"type": "string", "description": "Optional work item name."},
        "rows": {"type": "array", "description": "WBS rows with name, owner, schedule, estimate and actual_hours."},
        "publish": {"type": "boolean", "description": "Publish WBS draft after editing."},
        "confirm_write": {"type": "boolean", "description": "Must be true before MCP write calls are made."},
    },
    "required": ["workitem_url", "rows"],
    "additionalProperties": True,
}

_PROJECT_STATE_TRANSITION_PARAMETERS = {
    "type": "object",
    "properties": {
        "workitem_url": {"type": "string", "description": "Feishu Project work item URL."},
        "target_state": {"type": "string", "description": "Target state name."},
        "fields": {"type": "object", "description": "Optional required transition field values."},
        "confirm_write": {"type": "boolean", "description": "Must be true before MCP write calls are made."},
    },
    "required": ["workitem_url", "target_state"],
    "additionalProperties": True,
}

_PROJECT_BUGFIX_INTAKE_PARAMETERS = {
    "type": "object",
    "properties": {
        "space": {"type": "string", "description": "Feishu Project space name or URL."},
        "project": {"type": "string", "description": "Alias for space."},
        "workitem_type": {"type": "string", "description": "Issue work item type, defaults to issue."},
        "query": {"type": "string", "description": "MQL or natural-language issue search condition."},
        "mql": {"type": "string", "description": "Alias for query."},
        "transition_to": {"type": "string", "description": "Optional issue state to transition to after intake."},
        "max_items": {"type": "integer", "description": "Maximum issues to process."},
        "dry_run": {"type": "boolean", "description": "Preview without creating Hermes bugfix tasks."},
        "confirm_write": {"type": "boolean", "description": "Required when transition_to triggers MCP writes."},
    },
    "required": ["space"],
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
    _register_tool(
        register_tool,
        name="coding_project_mcp_preflight",
        schema=_tool_schema(
            "coding_project_mcp_preflight",
            "Check Feishu Project MCP availability, transport, auth and allowed tool surface.",
            _PROJECT_MCP_PREFLIGHT_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_project_mcp_preflight(_coerce_tool_args(args, kwargs)),
        description="Check Feishu Project MCP availability, transport, auth and allowed tool surface.",
    )
    _register_tool(
        register_tool,
        name="coding_project_workitem_search",
        schema=_tool_schema(
            "coding_project_workitem_search",
            "Search Feishu Project work items through the controlled MCP adapter.",
            _PROJECT_WORKITEM_SEARCH_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_project_workitem_search(_coerce_tool_args(args, kwargs)),
        description="Search Feishu Project work items through the controlled MCP adapter.",
    )
    _register_tool(
        register_tool,
        name="coding_project_workitem_create",
        schema=_tool_schema(
            "coding_project_workitem_create",
            "Create a Feishu Project work item through MCP after explicit write confirmation.",
            _PROJECT_WORKITEM_CREATE_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_project_workitem_create(_coerce_tool_args(args, kwargs)),
        description="Create a Feishu Project work item through MCP after explicit write confirmation.",
    )
    _register_tool(
        register_tool,
        name="coding_project_intake_sync",
        schema=_tool_schema(
            "coding_project_intake_sync",
            "Sync matching Feishu Project work items into Hermes coding tasks through MCP idempotently.",
            _PROJECT_INTAKE_SYNC_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_project_intake_sync(_coerce_tool_args(args, kwargs)),
        description="Sync matching Feishu Project work items into Hermes coding tasks through MCP idempotently.",
    )
    _register_tool(
        register_tool,
        name="coding_project_wbs_update",
        schema=_tool_schema(
            "coding_project_wbs_update",
            "Create, edit and optionally publish Feishu Project WBS draft rows through MCP.",
            _PROJECT_WBS_UPDATE_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_project_wbs_update(_coerce_tool_args(args, kwargs)),
        description="Create, edit and optionally publish Feishu Project WBS draft rows through MCP.",
    )
    _register_tool(
        register_tool,
        name="coding_project_state_transition",
        schema=_tool_schema(
            "coding_project_state_transition",
            "Transition Feishu Project work item state after checking required fields and transitable states.",
            _PROJECT_STATE_TRANSITION_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_project_state_transition(_coerce_tool_args(args, kwargs)),
        description="Transition Feishu Project work item state after checking required fields and transitable states.",
    )
    _register_tool(
        register_tool,
        name="coding_project_bugfix_intake",
        schema=_tool_schema(
            "coding_project_bugfix_intake",
            "Sync Feishu Project issues into Hermes bugfix tasks and optionally move issue state.",
            _PROJECT_BUGFIX_INTAKE_PARAMETERS,
        ),
        handler=lambda args=None, **kwargs: orchestrator.tool_project_bugfix_intake(_coerce_tool_args(args, kwargs)),
        description="Sync Feishu Project issues into Hermes bugfix tasks and optionally move issue state.",
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
