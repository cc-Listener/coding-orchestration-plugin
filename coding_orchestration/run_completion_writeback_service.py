from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import (
    run_orchestration_service,
)
from .models import RunMode, TaskPhase, TaskStatus
from .run.projections import run_ledger_projection
from .run.services import (
    run_ledger_writeback_service,
    run_project_writeback_service,
    run_session_writeback_service,
    run_status_transition_service,
    run_summary_writeback_service,
)

ArtifactReportWriteCallback = Callable[..., None]
ArtifactSummaryReadCallback = Callable[..., str]
TaskTransitionCallback = Callable[..., None]
LedgerWritebackCallback = Callable[[str, dict[str, Any]], None]
SessionWritebackCallback = Callable[[str, dict[str, Any]], None]
SummaryWritebackCallback = Callable[..., dict[str, Any]]
ProjectWritebackCallback = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class CompletedRunWritebackResult:
    result_payload: dict[str, Any]
    report: dict[str, Any]
    artifact_record: dict[str, Any]
    project_writeback: dict[str, Any]
    stale_completion: bool
    status: str
    task_status: TaskStatus


def write_completed_run_finalization(
    *,
    task_id: str,
    run_id: str,
    mode: RunMode,
    running_phase: TaskPhase,
    status: str,
    details: dict[str, Any],
    report: dict[str, Any],
    current_task: dict[str, Any],
    artifacts: Any,
    runner_name: str,
    exit_code: int | None,
    workspace_path: Any | None,
    source_branch: str | None,
    implementation_checkpoint: Any | None,
    qa_artifacts: dict[str, Any],
    tested_commit: str,
    changed_files: list[str],
    violations: list[str],
    session_id: str,
    attach_command: str,
    project_name: str,
    merge_record_created_at: str,
    write_report_artifact_callback: ArtifactReportWriteCallback,
    read_summary_artifact_callback: ArtifactSummaryReadCallback,
    transition_task_status_callback: TaskTransitionCallback,
    append_artifact_callback: LedgerWritebackCallback,
    append_agent_run_callback: LedgerWritebackCallback,
    append_merge_record_callback: LedgerWritebackCallback,
    update_task_session_callback: SessionWritebackCallback,
    write_summary_callback: SummaryWritebackCallback,
    project_writeback_callback: ProjectWritebackCallback,
) -> CompletedRunWritebackResult:
    completion_projection = run_orchestration_service.project_run_completion(
        mode=mode,
        status=status,
        details=details,
        report=report,
        running_phase=running_phase,
    )
    status = completion_projection.status
    task_status = completion_projection.task_status
    task_phase = completion_projection.task_phase
    run_still_active = completion_projection.run_still_active
    report = completion_projection.report
    write_report_artifact_callback(report_path=artifacts.report, report=report)

    stale_observation = run_orchestration_service.observe_stale_completion(current_task, run_id=run_id)
    run_status_transition_service.transition_completed_run_task_status(
        task_id=task_id,
        mode=mode,
        status=status,
        task_status=task_status,
        task_phase=task_phase,
        stale_completion=stale_observation.stale_completion,
        transition_task_status_callback=transition_task_status_callback,
    )
    ledger_records = run_ledger_projection.build_run_ledger_writeback_records(
        artifacts=artifacts,
        run_id=run_id,
        runner_name=runner_name,
        mode=mode,
        status=status,
        task_status=task_status,
        report=report,
        exit_code=exit_code,
        workspace_path=workspace_path,
        source_branch=source_branch,
        implementation_checkpoint=implementation_checkpoint,
        qa_artifacts=qa_artifacts,
        tested_commit=tested_commit,
        stale_completion=stale_observation.stale_completion,
        changed_files=changed_files,
        violations=violations,
        merge_record_created_at=merge_record_created_at
        if mode == RunMode.MERGE_TEST and not stale_observation.stale_completion
        else "",
    )
    run_ledger_writeback_service.write_run_ledger_completion(
        task_id=task_id,
        records=ledger_records,
        append_artifact_callback=append_artifact_callback,
        append_agent_run_callback=append_agent_run_callback,
        append_merge_record_callback=append_merge_record_callback,
    )
    if not stale_observation.stale_completion:
        completion_session_update = run_orchestration_service.build_completion_session_update(
            mode=mode,
            report=report,
            stale_completion=stale_observation.stale_completion,
            runner_name=runner_name,
            run_id=run_id,
            status=status,
            session_id=session_id,
            run_still_active=run_still_active,
            attach_command=attach_command,
        )
        run_session_writeback_service.write_run_session_update(
            task_id=task_id,
            update=completion_session_update,
            update_task_session_callback=update_task_session_callback,
        )
    summary = read_summary_artifact_callback(summary_path=artifacts.summary)
    run_summary_writeback_service.write_completed_run_summary(
        task_id=task_id,
        run_id=run_id,
        runner=runner_name,
        project_name=project_name,
        report=report,
        summary=summary,
        write_summary_callback=write_summary_callback,
    )
    project_writeback = run_project_writeback_service.write_run_project_completion(
        task_id=task_id,
        mode=mode,
        run_id=run_id,
        status=status,
        task_status=task_status,
        report=report,
        stale_completion=stale_observation.stale_completion,
        writeback_callback=project_writeback_callback,
    )
    result_payload = run_orchestration_service.build_start_run_result_payload(
        task_id=task_id,
        run_id=run_id,
        mode=mode,
        status=status,
        task_status=task_status,
        stale_completion=stale_observation.stale_completion,
        current_task_status=stale_observation.current_task_status,
        observed_active_run_id=stale_observation.observed_active_run_id,
        artifact_record=ledger_records.artifact_record,
        report=report,
        project_writeback=project_writeback,
    )
    return CompletedRunWritebackResult(
        result_payload=result_payload,
        report=report,
        artifact_record=ledger_records.artifact_record,
        project_writeback=project_writeback,
        stale_completion=stale_observation.stale_completion,
        status=status,
        task_status=task_status,
    )
