from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import (
    AgentRunStatus,
    RunMode,
    agent_run_status_details,
    apply_failure_type_to_run_details,
    normalize_agent_run_status,
)


REPORT_CONTRACT_FIELDS = (
    "runner",
    "status",
    "raw_status",
    "status_detail",
    "failure_type",
    "known_gaps",
    "structured",
    "mode",
    "summary_markdown",
    "modified_files",
    "test_commands",
    "test_results",
    "risks",
    "verification_limitations",
    "human_required",
    "next_actions",
    "qa_artifacts",
    "tested_commit",
    "user_facing_summary",
    "technical_summary",
    "implementation_landed",
    "commit_sha",
    "changed_files_summary",
    "branch_slug_candidate",
    "execution_policy_decision",
    "merge_readiness",
    "classification",
    "reason",
    "delivery_units",
    "execution_tasks",
    "dependencies",
    "acceptance_plan",
    "open_questions",
    "materialization_allowed",
)


def semantic_report_fields(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_facing_summary": str(report.get("user_facing_summary") or ""),
        "technical_summary": str(report.get("technical_summary") or ""),
        "implementation_landed": report.get("implementation_landed")
        if isinstance(report.get("implementation_landed"), bool)
        else False,
        "commit_sha": str(report.get("commit_sha") or ""),
        "changed_files_summary": report.get("changed_files_summary")
        if isinstance(report.get("changed_files_summary"), list)
        else [],
        "branch_slug_candidate": str(report.get("branch_slug_candidate") or ""),
        "execution_policy_decision": report.get("execution_policy_decision")
        if isinstance(report.get("execution_policy_decision"), dict)
        else {},
        "merge_readiness": report.get("merge_readiness") if isinstance(report.get("merge_readiness"), dict) else {},
        "classification": str(report.get("classification") or ""),
        "reason": str(report.get("reason") or ""),
        "delivery_units": report.get("delivery_units") if isinstance(report.get("delivery_units"), list) else [],
        "execution_tasks": report.get("execution_tasks") if isinstance(report.get("execution_tasks"), list) else [],
        "dependencies": report.get("dependencies") if isinstance(report.get("dependencies"), list) else [],
        "acceptance_plan": report.get("acceptance_plan") if isinstance(report.get("acceptance_plan"), list) else [],
        "open_questions": report.get("open_questions") if isinstance(report.get("open_questions"), list) else [],
        "materialization_allowed": bool(report.get("materialization_allowed")),
    }


def report_contract_fields(report: dict[str, Any]) -> dict[str, Any]:
    return {key: report[key] for key in REPORT_CONTRACT_FIELDS if key in report}


def normalize_report_status(status: Any, mode: RunMode) -> str:
    return normalize_agent_run_status(status, mode)


def report_status_details(report: dict[str, Any], mode: RunMode) -> dict[str, Any]:
    source_status = (
        report.get("raw_status")
        or report.get("status_detail")
        or report.get("status")
        or "completed_unstructured"
    )
    details = agent_run_status_details(source_status, mode)
    status_detail = str(report.get("status_detail") or "").strip()
    failure_type = str(report.get("failure_type") or "").strip()
    if status_detail:
        details["status_detail"] = status_detail
    if failure_type:
        details = apply_failure_type_to_run_details(details, failure_type)
    if "known_gaps" in report:
        details["known_gaps"] = bool(report.get("known_gaps"))
    if "structured" in report:
        details["structured"] = bool(report.get("structured"))
    if details["known_gaps"] and not details["status_detail"]:
        details["status_detail"] = "ready_for_merge_test_with_known_gaps"
    if details["structured"] is False and not details["status_detail"]:
        details["status_detail"] = "completed_unstructured"
    return details


def status_requires_limitation(status: Any) -> bool:
    details = agent_run_status_details(status)
    return run_details_require_limitation(details)


def report_requires_limitation(report: dict[str, Any]) -> bool:
    return run_details_require_limitation(
        {
            "status": str(report.get("status") or ""),
            "status_detail": str(report.get("status_detail") or ""),
            "failure_type": str(report.get("failure_type") or ""),
            "known_gaps": bool(report.get("known_gaps")),
            "structured": bool(report.get("structured", True)),
        }
    )


def run_details_require_limitation(details: dict[str, Any]) -> bool:
    status = str(details.get("status") or "")
    return bool(
        status in {AgentRunStatus.BLOCKED.value, AgentRunStatus.FAILED.value}
        or details.get("known_gaps")
        or details.get("failure_type")
        or details.get("status_detail") in {"completed_unstructured", "ready_for_merge_test_with_known_gaps"}
        or details.get("structured") is False
    )


def fallback_limitation_reason(status: Any) -> str:
    details = agent_run_status_details(status)
    failure_type = str(details.get("failure_type") or "")
    if failure_type == "timeout" or details.get("raw_status") == "timeout":
        return "runner_timeout"
    if failure_type == "runner_failed" or details.get("raw_status") == "runner_failed":
        return "runner_failed"
    return "structured_report_missing"


def verification_limitation(
    *,
    reason: str,
    impact: str,
    recovery_action: str,
    fallback_evidence: str,
) -> dict[str, str]:
    return {
        "reason": reason,
        "impact": impact,
        "recovery_action": recovery_action,
        "fallback_evidence": fallback_evidence,
    }


def try_parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def runner_failure_from_stdout(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if "invalid_json_schema" in text or "Invalid schema for response_format" in text:
        return {
            "reason": "codex_invalid_output_schema",
            "impact": "Codex rejected Hermes' report.schema.json before running the planning turn, so no plan or verification result was produced.",
            "recovery_action": "Fix report.schema.json generation so every object property is listed in required, then rerun the same task.",
            "fallback_evidence": str(path),
        }
    return None


def thread_id_from_stdout(path: Path) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parsed = try_parse_json(line.strip())
        if not isinstance(parsed, dict):
            continue
        if parsed.get("type") == "thread.started" and parsed.get("thread_id"):
            return str(parsed["thread_id"])
    return ""
