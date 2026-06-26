from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import AgentRunStatus, RunMode
from .codex_report import REPORT_CONTRACT_FIELDS


def _closed_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _execution_policy_decision_schema() -> dict[str, Any]:
    return _closed_object(
        {
            "route": {"type": "string"},
            "planning": {"type": "string"},
            "context": {"type": "string"},
            "implementation": {"type": "string"},
            "verification": {"type": "string"},
            "allow_browser_qa": {"type": "boolean"},
            "require_human_confirmation": {"type": "boolean"},
            "max_duration_seconds": {"type": "integer"},
            "reasons": _string_array(),
            "reasoning_summary": {"type": "string"},
        }
    )


def _merge_readiness_schema() -> dict[str, Any]:
    return _closed_object(
        {
            "ready": {"type": "boolean"},
            "risk_level": {"type": "string"},
            "risk_note": {"type": "string"},
            "required_confirmation": {"type": "boolean"},
            "reason": {"type": "string"},
            "impact": {"type": "string"},
            "recovery_action": {"type": "string"},
            "fallback_evidence": {"type": "string"},
        }
    )


def _delivery_unit_schema() -> dict[str, Any]:
    return _closed_object(
        {
            "unit_id": {"type": "string"},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "project_key": {"type": "string"},
            "project_path": {"type": "string"},
            "risk_level": {"type": "string"},
            "dependencies": _string_array(),
            "acceptance_criteria": _string_array(),
        }
    )


def _execution_task_schema() -> dict[str, Any]:
    return _closed_object(
        {
            "unit_id": {"type": "string"},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "project_key": {"type": "string"},
            "project_path": {"type": "string"},
            "dependencies": _string_array(),
            "acceptance_criteria": _string_array(),
            "suggested_command": {"type": "string"},
        }
    )


def _dependency_schema() -> dict[str, Any]:
    return _closed_object(
        {
            "from": {"type": "string"},
            "to": {"type": "string"},
            "reason": {"type": "string"},
        }
    )


def build_report_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(REPORT_CONTRACT_FIELDS),
        "properties": {
            "runner": {"type": "string"},
            "status": {
                "type": "string",
                "enum": [status.value for status in AgentRunStatus],
            },
            "raw_status": {"type": "string"},
            "status_detail": {"type": "string"},
            "failure_type": {"type": "string"},
            "known_gaps": {"type": "boolean"},
            "structured": {"type": "boolean"},
            "mode": {"type": "string", "enum": [mode.value for mode in RunMode]},
            "summary_markdown": {
                "type": "string",
                "description": "Human-readable Markdown summary or plan to show in Feishu.",
            },
            "modified_files": {"type": "array", "items": {"type": "string"}},
            "test_commands": {"type": "array", "items": {"type": "string"}},
            "test_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["command", "status", "output_summary"],
                    "properties": {
                        "command": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["passed", "failed", "not_run", "blocked"],
                        },
                        "output_summary": {"type": "string"},
                    },
                },
            },
            "risks": {"type": "array", "items": {"type": "string"}},
            "verification_limitations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["reason", "impact", "recovery_action", "fallback_evidence"],
                    "properties": {
                        "reason": {"type": "string"},
                        "impact": {"type": "string"},
                        "recovery_action": {"type": "string"},
                        "fallback_evidence": {"type": "string"},
                    },
                },
            },
            "human_required": {"type": "boolean"},
            "next_actions": {"type": "array", "items": {"type": "string"}},
            "qa_artifacts": {
                "type": "object",
                "additionalProperties": False,
                "required": ["report", "baseline", "screenshots_dir"],
                "properties": {
                    "report": {"type": "string"},
                    "baseline": {"type": "string"},
                    "screenshots_dir": {"type": "string"},
                },
            },
            "tested_commit": {"type": "string"},
            "user_facing_summary": {"type": "string"},
            "technical_summary": {"type": "string"},
            "implementation_landed": {"type": "boolean"},
            "commit_sha": {"type": "string"},
            "changed_files_summary": {"type": "array", "items": {"type": "string"}},
            "branch_slug_candidate": {"type": "string"},
            "execution_policy_decision": _execution_policy_decision_schema(),
            "merge_readiness": _merge_readiness_schema(),
            "classification": {
                "type": "string",
                "enum": ["", "single_execution", "multi_task", "multi_project", "needs_clarification"],
            },
            "reason": {"type": "string"},
            "delivery_units": {"type": "array", "items": _delivery_unit_schema()},
            "execution_tasks": {"type": "array", "items": _execution_task_schema()},
            "dependencies": {"type": "array", "items": _dependency_schema()},
            "acceptance_plan": {"type": "array", "items": {"type": "string"}},
            "open_questions": {"type": "array", "items": {"type": "string"}},
            "materialization_allowed": {"type": "boolean"},
        },
    }


def write_report_schema(path: Path) -> None:
    path.write_text(json.dumps(build_report_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
