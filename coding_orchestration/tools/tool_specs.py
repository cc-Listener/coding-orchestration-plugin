from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    operation_id: str
    safety_level: str = "read_write"
    host_visibility: str = "public"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": copy.deepcopy(self.input_schema),
        }


_TASK_CREATE_PARAMETERS = {
    "type": "object",
    "properties": {
        "requirement": {"type": "string", "description": "Task requirement text."},
        "text": {"type": "string", "description": "Alias for requirement."},
        "project": {"type": "string", "description": "Known coding project name or path."},
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
        "task_id": {"type": "string", "description": "Coding task id."},
    },
    "required": ["task_id"],
    "additionalProperties": True,
}

_TASK_RUN_PARAMETERS = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "Coding task id."},
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
        "dry_run": {"type": "boolean", "description": "When true, search only and do not create coding tasks."},
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
        "dry_run": {"type": "boolean", "description": "Preview without creating bugfix tasks."},
        "confirm_write": {"type": "boolean", "description": "Required when transition_to triggers MCP writes."},
    },
    "required": ["space"],
    "additionalProperties": True,
}


def coding_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="coding_task_create",
            description="Create a coding task with source/project preflight.",
            input_schema=_TASK_CREATE_PARAMETERS,
            operation_id="task.create",
        ),
        ToolSpec(
            name="coding_task_status",
            description="Read coding task status, source health, runner state, and next actions.",
            input_schema=_TASK_STATUS_PARAMETERS,
            operation_id="task.status",
            safety_level="read",
        ),
        ToolSpec(
            name="coding_task_run",
            description="Start or continue a coding task run through the configured runtime.",
            input_schema=_TASK_RUN_PARAMETERS,
            operation_id="task.run",
        ),
        ToolSpec(
            name="coding_source_resolve",
            description="Resolve Feishu/Lark/Meegle source URLs before handing work to a coding runner.",
            input_schema=_SOURCE_RESOLVE_PARAMETERS,
            operation_id="source.resolve",
            safety_level="read",
        ),
        ToolSpec(
            name="coding_lark_preflight",
            description="Check external document auth and source-readiness for coding tasks.",
            input_schema=_LARK_PREFLIGHT_PARAMETERS,
            operation_id="source.lark_preflight",
            safety_level="read",
        ),
        ToolSpec(
            name="coding_project_mcp_preflight",
            description="Check Feishu Project MCP availability, transport, auth and allowed tool surface.",
            input_schema=_PROJECT_MCP_PREFLIGHT_PARAMETERS,
            operation_id="project.mcp_preflight",
            safety_level="read",
        ),
        ToolSpec(
            name="coding_project_workitem_search",
            description="Search Feishu Project work items through the controlled MCP adapter.",
            input_schema=_PROJECT_WORKITEM_SEARCH_PARAMETERS,
            operation_id="project.workitem_search",
            safety_level="read",
        ),
        ToolSpec(
            name="coding_project_workitem_create",
            description="Create a Feishu Project work item through MCP after explicit write confirmation.",
            input_schema=_PROJECT_WORKITEM_CREATE_PARAMETERS,
            operation_id="project.workitem_create",
        ),
        ToolSpec(
            name="coding_project_intake_sync",
            description="Sync matching Feishu Project work items into coding tasks through MCP idempotently.",
            input_schema=_PROJECT_INTAKE_SYNC_PARAMETERS,
            operation_id="project.intake_sync",
        ),
        ToolSpec(
            name="coding_project_wbs_update",
            description="Create, edit and optionally publish Feishu Project WBS draft rows through MCP.",
            input_schema=_PROJECT_WBS_UPDATE_PARAMETERS,
            operation_id="project.wbs_update",
        ),
        ToolSpec(
            name="coding_project_state_transition",
            description="Transition Feishu Project work item state after checking required fields and transitable states.",
            input_schema=_PROJECT_STATE_TRANSITION_PARAMETERS,
            operation_id="project.state_transition",
        ),
        ToolSpec(
            name="coding_project_bugfix_intake",
            description="Sync Feishu Project issues into bugfix tasks and optionally move issue state.",
            input_schema=_PROJECT_BUGFIX_INTAKE_PARAMETERS,
            operation_id="project.bugfix_intake",
        ),
    ]
