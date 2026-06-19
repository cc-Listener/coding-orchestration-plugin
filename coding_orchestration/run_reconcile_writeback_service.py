from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import (
    run_ledger_projection,
    run_ledger_writeback_service,
    run_orchestration_service,
    run_session_writeback_service,
    run_status_transition_service,
    run_summary_writeback_service,
)
from .models import RunMode, TaskPhase, TaskStatus

ArtifactReportWriteCallback = Callable[..., None]
TaskTransitionCallback = Callable[..., None]
LedgerWritebackCallback = Callable[[str, dict[str, Any]], None]
SessionWritebackCallback = Callable[[str, dict[str, Any]], None]
SummaryWritebackCallback = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ReconciledRunWritebackResult:
    result_payload: dict[str, Any]
    report: dict[str, Any]
    artifact_record: dict[str, Any]
    status: str
    task_status: TaskStatus


def write_reconciled_run_finalization(
    *,
    task_id: str,
    run_id: str,
    task: dict[str, Any],
    session: dict[str, Any],
    existing_run: dict[str, Any],
    artifacts: Any,
    mode: RunMode,
    running_phase: TaskPhase,
    status: str,
    details: dict[str, Any],
    report: dict[str, Any],
    changed_files: list[str],
    runner_name: str,
    session_id: str,
    attach_command: str,
    reconciled_at: str,
    summary: str,
    write_report_artifact_callback: ArtifactReportWriteCallback,
    transition_task_status_callback: TaskTransitionCallback,
    upsert_artifact_callback: LedgerWritebackCallback,
    upsert_agent_run_callback: LedgerWritebackCallback,
    update_task_session_callback: SessionWritebackCallback,
    write_summary_callback: SummaryWritebackCallback,
) -> ReconciledRunWritebackResult:
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
    report = completion_projection.report
    write_report_artifact_callback(report_path=artifacts.report, report=report)

    run_status_transition_service.transition_reconciled_run_task_status(
        task_id=task_id,
        mode=mode,
        status=status,
        task_status=task_status,
        task_phase=task_phase,
        transition_task_status_callback=transition_task_status_callback,
    )

    ledger_records = run_ledger_projection.build_reconciled_run_ledger_writeback_records(
        artifacts=artifacts,
        existing_run=existing_run,
        run_id=run_id,
        runner_name=runner_name,
        mode=mode,
        status=status,
        report=report,
        changed_files=changed_files,
    )
    run_ledger_writeback_service.write_reconciled_run_ledger(
        task_id=task_id,
        records=ledger_records,
        upsert_artifact_callback=upsert_artifact_callback,
        upsert_agent_run_callback=upsert_agent_run_callback,
    )

    runner_update = run_orchestration_service.build_runner_session_update(
        runner_name=runner_name,
        run_id=run_id,
        status=status,
        report=report,
        session_id=session_id,
        run_still_active=False,
        attach_command=attach_command,
        reconciled_at=reconciled_at,
    )
    run_session_writeback_service.write_run_session_update(
        task_id=task_id,
        update={"runner": runner_update},
        update_task_session_callback=update_task_session_callback,
    )

    run_summary_writeback_service.write_reconciled_run_summary(
        task_id=task_id,
        run_id=run_id,
        task=task,
        session=session,
        merged_run=ledger_records.agent_run_record,
        report=report,
        summary=summary,
        write_summary_callback=write_summary_callback,
    )
    result_payload = run_orchestration_service.build_reconcile_result_payload(
        task_id=task_id,
        run_id=run_id,
        mode=mode,
        status=status,
        task_status=task_status,
        artifact_record=ledger_records.artifact_record,
    )
    return ReconciledRunWritebackResult(
        result_payload=result_payload,
        report=report,
        artifact_record=ledger_records.artifact_record,
        status=status,
        task_status=task_status,
    )
