from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import AgentRunStatus, RunMode
from .codex_report import REPORT_CONTRACT_FIELDS


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
            "execution_policy_decision": {"type": "object", "additionalProperties": True},
            "merge_readiness": {"type": "object", "additionalProperties": True},
            "classification": {
                "type": "string",
                "enum": ["", "single_execution", "multi_task", "multi_project", "needs_clarification"],
            },
            "reason": {"type": "string"},
            "delivery_units": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "execution_tasks": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "dependencies": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "acceptance_plan": {"type": "array", "items": {"type": "string"}},
            "open_questions": {"type": "array", "items": {"type": "string"}},
            "materialization_allowed": {"type": "boolean"},
        },
    }


def write_report_schema(path: Path) -> None:
    path.write_text(json.dumps(build_report_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
