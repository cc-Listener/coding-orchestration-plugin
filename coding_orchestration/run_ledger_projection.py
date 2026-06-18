from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import run_manifest_service, run_orchestration_service
from .models import RunMode, TaskStatus


@dataclass(frozen=True)
class RunLedgerWritebackRecords:
    artifact_record: dict[str, str]
    agent_run_record: dict[str, Any]
    merge_test_record: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReconciledRunLedgerWritebackRecords:
    artifact_record: dict[str, str]
    agent_run_record: dict[str, Any]


def build_run_ledger_writeback_records(
    *,
    artifacts: Any,
    run_id: str,
    runner_name: str,
    mode: RunMode,
    status: str,
    task_status: TaskStatus | str,
    report: dict[str, Any],
    exit_code: int | None,
    workspace_path: Any | None,
    source_branch: str | None,
    implementation_checkpoint: Any | None,
    qa_artifacts: dict[str, Any],
    tested_commit: str,
    stale_completion: bool,
    changed_files: list[str],
    violations: list[str],
    merge_record_created_at: str,
) -> RunLedgerWritebackRecords:
    artifact_record = run_manifest_service.artifact_record(artifacts)
    agent_run_record = run_orchestration_service.build_agent_run_record(
        run_id=run_id,
        runner_name=runner_name,
        mode=mode,
        status=status,
        report=report,
        exit_code=exit_code,
        artifact_record=artifact_record,
        workspace_path=workspace_path,
        source_branch=source_branch,
        implementation_checkpoint=implementation_checkpoint,
        qa_artifacts=qa_artifacts,
        tested_commit=tested_commit,
        stale_completion=stale_completion,
        changed_files=changed_files,
        violations=violations,
    )
    merge_test_record = None
    if mode == RunMode.MERGE_TEST and not stale_completion:
        merge_test_record = run_orchestration_service.build_merge_test_run_record(
            run_id=run_id,
            status=status,
            task_status=task_status,
            source_branch=source_branch,
            artifact_record=artifact_record,
            created_at=merge_record_created_at,
        )
    return RunLedgerWritebackRecords(
        artifact_record=artifact_record,
        agent_run_record=agent_run_record,
        merge_test_record=merge_test_record,
    )


def build_reconciled_run_ledger_writeback_records(
    *,
    artifacts: Any,
    existing_run: dict[str, Any],
    run_id: str,
    runner_name: str,
    mode: RunMode,
    status: str,
    report: dict[str, Any],
    changed_files: list[str],
) -> ReconciledRunLedgerWritebackRecords:
    artifact_record = run_manifest_service.artifact_record(artifacts)
    agent_run_record = run_orchestration_service.build_reconciled_agent_run_record(
        existing_run=existing_run,
        run_id=run_id,
        runner_name=runner_name,
        mode=mode,
        status=status,
        report=report,
        artifact_record=artifact_record,
        changed_files=changed_files,
    )
    return ReconciledRunLedgerWritebackRecords(
        artifact_record=artifact_record,
        agent_run_record=agent_run_record,
    )
