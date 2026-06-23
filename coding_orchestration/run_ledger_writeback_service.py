from __future__ import annotations

from typing import Any, Callable

from .run.projections.run_ledger_projection import ReconciledRunLedgerWritebackRecords, RunLedgerWritebackRecords

LedgerWritebackCallback = Callable[[str, dict[str, Any]], None]


def write_run_ledger_completion(
    *,
    task_id: str,
    records: RunLedgerWritebackRecords,
    append_artifact_callback: LedgerWritebackCallback,
    append_agent_run_callback: LedgerWritebackCallback,
    append_merge_record_callback: LedgerWritebackCallback,
) -> None:
    append_artifact_callback(task_id, records.artifact_record)
    append_agent_run_callback(task_id, records.agent_run_record)
    if records.merge_test_record is not None:
        append_merge_record_callback(task_id, records.merge_test_record)


def write_reconciled_run_ledger(
    *,
    task_id: str,
    records: ReconciledRunLedgerWritebackRecords,
    upsert_artifact_callback: LedgerWritebackCallback,
    upsert_agent_run_callback: LedgerWritebackCallback,
) -> None:
    upsert_artifact_callback(task_id, records.artifact_record)
    upsert_agent_run_callback(task_id, records.agent_run_record)
