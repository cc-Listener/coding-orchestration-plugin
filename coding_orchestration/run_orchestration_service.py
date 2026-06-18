from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .run_failure_report_projection import (
    RunFailureReportProjection,
    build_checkpoint_failed_report_payload,
    build_runner_failed_report_payload,
)
from .run_report_refinement_projection import (
    BlockedReportProjection,
    RunReportRefinement,
    build_diff_guard_blocked_report,
    build_implementation_commit_missing_report,
    refine_run_report_projection,
)
from .run_prompt_projection import build_run_prompt_text
from .run_session_projection import (
    build_active_run_session_update,
    build_completion_session_update,
    build_plan_report_session_fields,
    build_plan_report_session_update,
    build_run_start_base_session_update,
    build_run_start_workspace_session_update,
    build_runner_session_update,
)
from .run_start_selection_projection import (
    RUN_CONTEXT_SOURCE_CONFIRMED_PLAN,
    RUN_CONTEXT_SOURCE_MERGE_TEST_CONTEXT,
    RUN_MANIFEST_CHECKPOINT_MERGE_TEST,
    RUN_MANIFEST_CHECKPOINT_NONE,
    RUN_MANIFEST_CHECKPOINT_QA,
    RUN_WORKSPACE_CREATE_IMPLEMENTATION,
    RUN_WORKSPACE_EXISTING_IMPLEMENTATION,
    RUN_WORKSPACE_NONE,
    RunManifestCheckpointPreparation,
    RunWorkspaceSelection,
    run_checkpoint_failed,
    run_checkpoint_for_mode,
    run_context_source_for_mode,
    run_manifest_checkpoint_preparation_for_mode,
    run_observes_qa_evidence,
    run_records_source_branch,
    run_requires_project_path,
    run_workspace_selection_for_mode,
)
from .models import AgentRunStatus, RunMode, TaskPhase, TaskStatus, normalize_agent_run_status
from .services.run_service import RunService
from .status_policy import (
    run_details_require_verification_limitations,
    run_status_details_from_report,
)


@dataclass(frozen=True)
class RunCompletionProjection:
    status: str
    task_status: TaskStatus
    task_phase: TaskPhase
    run_still_active: bool
    report: dict[str, Any]


@dataclass(frozen=True)
class StaleCompletionObservation:
    stale_completion: bool
    observed_active_run_id: str
    current_task_status: str


def build_observed_run_report(
    report: dict[str, Any],
    *,
    changed_files: list[str],
    qa_artifacts: dict[str, Any],
    tested_commit: str,
) -> dict[str, Any]:
    observed_report = dict(report)
    observed_report["modified_files"] = changed_files
    if qa_artifacts:
        observed_report["qa_artifacts"] = qa_artifacts
    if tested_commit:
        observed_report["tested_commit"] = tested_commit
    return observed_report


def latest_execution_policy_decision(task: dict[str, Any]) -> dict[str, Any]:
    session = task.get("task_session") or {}
    plan_report = session.get("plan_report") or {}
    if not isinstance(plan_report, dict):
        return {}
    decision = plan_report.get("execution_policy_decision") or {}
    return decision if isinstance(decision, dict) else {}


def build_run_diff_guard_violations(
    *,
    mode: RunMode,
    violations: list[str],
    changed_files: list[str],
) -> list[str]:
    run_violations = list(violations)
    if mode == RunMode.PLAN_ONLY:
        run_violations.extend(
            f"plan-only run modified {path}; plan-only may read external context but must not write project files"
            for path in changed_files
        )
    return run_violations


def ensure_verification_limitations(
    report: dict[str, Any],
    *,
    status: str,
    stdout_path: Any,
    stderr_path: Any,
) -> dict[str, Any]:
    projected_report = dict(report)
    projected_report.setdefault("verification_limitations", [])
    try:
        mode = RunMode(str(projected_report.get("mode") or RunMode.PLAN_ONLY.value))
    except ValueError:
        mode = RunMode.PLAN_ONLY
    details = run_status_details_from_report(projected_report, mode, fallback_status=status)
    if run_details_require_verification_limitations(details) and not projected_report["verification_limitations"]:
        projected_report["verification_limitations"] = [
            {
                "reason": "blocked_or_partial_without_details",
                "impact": "The run ended in a blocked or partial state without structured recovery details.",
                "recovery_action": "Review report risks and stdout/stderr, then rerun with explicit recovery instructions.",
                "fallback_evidence": f"{stdout_path}; {stderr_path}",
            }
        ]
    return projected_report


def build_completion_report_payload(
    *,
    report: dict[str, Any],
    status: str,
    task_status: TaskStatus | str,
    details: dict[str, Any],
    known_gaps: bool = False,
) -> dict[str, Any]:
    task_status_value = task_status.value if isinstance(task_status, TaskStatus) else str(task_status)
    projected_report = dict(report)
    projected_report["run_status"] = status
    projected_report["status"] = status
    projected_report["task_status"] = task_status_value
    projected_report.update(details)
    if known_gaps:
        projected_report["known_gaps"] = True
    return projected_report


def build_agent_run_record(
    *,
    run_id: str,
    runner_name: str,
    mode: RunMode,
    status: str,
    report: dict[str, Any],
    exit_code: int | None,
    artifact_record: dict[str, Any],
    workspace_path: Any | None,
    source_branch: str | None,
    implementation_checkpoint: Any | None,
    qa_artifacts: dict[str, Any],
    tested_commit: str,
    stale_completion: bool,
    changed_files: list[str],
    violations: list[str],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "runner": runner_name,
        "mode": mode.value,
        "status": status,
        "raw_status": str(report.get("raw_status") or ""),
        "status_detail": str(report.get("status_detail") or ""),
        "failure_type": str(report.get("failure_type") or ""),
        "known_gaps": bool(report.get("known_gaps")),
        "structured": bool(report.get("structured", True)),
        "exit_code": exit_code,
        "artifact": artifact_record,
        "workspace_path": str(workspace_path) if workspace_path else None,
        "source_branch": source_branch if run_records_source_branch(mode) else None,
        "target_branch": "test" if mode == RunMode.MERGE_TEST else None,
        "implementation_checkpoint": implementation_checkpoint if mode == RunMode.IMPLEMENTATION else None,
        "qa_artifacts": qa_artifacts,
        "tested_commit": tested_commit,
        "stale_completion": stale_completion,
        "diff_guard": {
            "changed_files": changed_files,
            "violations": violations,
        },
    }


def build_reconciled_agent_run_record(
    *,
    existing_run: dict[str, Any],
    run_id: str,
    runner_name: str,
    mode: RunMode | str,
    status: str,
    report: dict[str, Any],
    artifact_record: dict[str, Any],
    changed_files: list[str],
) -> dict[str, Any]:
    mode_value = mode.value if isinstance(mode, RunMode) else str(mode)
    merged_run = dict(existing_run)
    report_qa_artifacts = report.get("qa_artifacts")
    merged_run.update(
        {
            "run_id": run_id,
            "runner": runner_name,
            "mode": mode_value,
            "status": status,
            "raw_status": str(report.get("raw_status") or ""),
            "status_detail": str(report.get("status_detail") or ""),
            "failure_type": str(report.get("failure_type") or ""),
            "known_gaps": bool(report.get("known_gaps")),
            "structured": bool(report.get("structured", True)),
            "artifact": artifact_record,
            "qa_artifacts": report_qa_artifacts
            if isinstance(report_qa_artifacts, dict)
            else merged_run.get("qa_artifacts", {}),
            "tested_commit": str(report.get("tested_commit") or merged_run.get("tested_commit") or ""),
            "stale_completion": False,
            "diff_guard": {
                "changed_files": changed_files,
                "violations": list((merged_run.get("diff_guard") or {}).get("violations") or []),
            },
        }
    )
    return merged_run


def build_merge_test_run_record(
    *,
    run_id: str,
    status: str,
    task_status: TaskStatus | str,
    source_branch: str | None,
    artifact_record: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    task_status_value = task_status.value if isinstance(task_status, TaskStatus) else str(task_status)
    return {
        "type": "merge_test_run",
        "run_id": run_id,
        "status": status,
        "task_status": task_status_value,
        "source_branch": source_branch,
        "target_branch": "test",
        "artifact": artifact_record,
        "created_at": created_at,
    }


def build_project_writeback_payload(
    *,
    run_id: str,
    status: str,
    task_status: TaskStatus | str,
    report: dict[str, Any],
) -> dict[str, Any]:
    task_status_value = task_status.value if isinstance(task_status, TaskStatus) else str(task_status)
    return {
        "run_id": run_id,
        "status": status,
        "task_status": task_status_value,
        "report": report,
    }


def build_start_run_result_payload(
    *,
    task_id: str,
    run_id: str,
    mode: RunMode | str,
    status: str,
    task_status: TaskStatus | str,
    stale_completion: bool,
    current_task_status: Any,
    observed_active_run_id: str,
    artifact_record: dict[str, Any],
    report: dict[str, Any],
    project_writeback: dict[str, Any],
) -> dict[str, Any]:
    mode_value = mode.value if isinstance(mode, RunMode) else str(mode)
    task_status_value = task_status.value if isinstance(task_status, TaskStatus) else str(task_status)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "mode": mode_value,
        "status": status,
        "run_status": status,
        "task_status": task_status_value,
        "stale_completion": stale_completion,
        "current_task_status": current_task_status if stale_completion else task_status_value,
        "observed_active_run_id": observed_active_run_id if stale_completion else "",
        "artifacts": artifact_record,
        "report": report,
        "project_writeback": project_writeback,
    }


def build_reconcile_result_payload(
    *,
    task_id: str,
    run_id: str,
    mode: RunMode | str,
    status: str,
    task_status: TaskStatus | str,
    artifact_record: dict[str, Any],
) -> dict[str, Any]:
    mode_value = mode.value if isinstance(mode, RunMode) else str(mode)
    task_status_value = task_status.value if isinstance(task_status, TaskStatus) else str(task_status)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "mode": mode_value,
        "status": status,
        "task_status": task_status_value,
        "artifacts": artifact_record,
        "reconciled": True,
    }


def run_mode_for_existing_run(
    task: dict[str, Any],
    run: dict[str, Any],
    report: dict[str, Any],
) -> RunMode:
    runner_session = (task.get("task_session") or {}).get("runner") or {}
    candidates = [
        report.get("mode"),
        run.get("mode"),
        runner_session.get("active_mode"),
        runner_session.get("last_requested_mode"),
    ]
    for candidate in candidates:
        try:
            return RunMode(str(candidate))
        except ValueError:
            continue
    return RunMode.PLAN_ONLY


def changed_files_for_existing_run(run: dict[str, Any], report: dict[str, Any]) -> list[str]:
    candidates = report.get("modified_files")
    if not isinstance(candidates, list):
        diff_guard = run.get("diff_guard") if isinstance(run.get("diff_guard"), dict) else {}
        candidates = diff_guard.get("changed_files")
    if not isinstance(candidates, list):
        return []
    return [str(item) for item in candidates if str(item).strip()]


def observe_stale_completion(current_task: dict[str, Any], *, run_id: str) -> StaleCompletionObservation:
    current_runner = (current_task.get("task_session") or {}).get("runner") or {}
    observed_active_run_id = str(current_runner.get("active_run_id") or "")
    current_task_status = str(current_task.get("status") or "")
    stale_completion = bool(observed_active_run_id and observed_active_run_id != run_id) or (
        current_task_status == TaskStatus.CANCELLED.value
    )
    return StaleCompletionObservation(
        stale_completion=stale_completion,
        observed_active_run_id=observed_active_run_id,
        current_task_status=current_task_status,
    )


def project_run_completion(
    *,
    mode: RunMode,
    status: str,
    details: dict[str, Any],
    report: dict[str, Any],
    running_phase: TaskPhase,
) -> RunCompletionProjection:
    normalized_status = normalize_agent_run_status(status, mode)
    task_status = RunService.task_status_for_run_result(mode, normalized_status, details=details)
    task_phase = RunService.task_phase_for_run_result(mode, normalized_status, details=details)
    run_still_active = normalized_status == AgentRunStatus.RUNNING.value
    if run_still_active:
        task_status = TaskStatus.RUNNING
        task_phase = running_phase
    merge_test_human_required_known_gap = False
    if (
        mode == RunMode.MERGE_TEST
        and bool(report.get("human_required"))
        and normalized_status
        not in {
            AgentRunStatus.BLOCKED.value,
            AgentRunStatus.FAILED.value,
            AgentRunStatus.CANCELLED.value,
        }
    ):
        task_status = TaskStatus.READY_FOR_MERGE_TEST
        task_phase = TaskPhase.READY_TO_MERGE_TEST
        merge_test_human_required_known_gap = True
    projected_report = build_completion_report_payload(
        report=report,
        status=normalized_status,
        task_status=task_status,
        details=details,
        known_gaps=merge_test_human_required_known_gap,
    )
    return RunCompletionProjection(
        status=normalized_status,
        task_status=task_status,
        task_phase=task_phase,
        run_still_active=run_still_active,
        report=projected_report,
    )
