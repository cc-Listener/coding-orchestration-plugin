from __future__ import annotations

from typing import Any, Callable

from .run.projections import run_summary_projection

RunSummaryWritebackCallback = Callable[..., dict[str, Any]]


def write_completed_run_summary(
    *,
    task_id: str,
    run_id: str,
    runner: Any,
    project_name: Any,
    report: dict[str, Any],
    summary: str,
    write_summary_callback: RunSummaryWritebackCallback,
) -> dict[str, Any]:
    payload = run_summary_projection.build_completed_run_summary_writeback_payload(
        task_id=task_id,
        run_id=run_id,
        runner=runner,
        project_name=project_name,
        report=report,
        summary=summary,
    )
    result = write_summary_callback(**payload.as_kwargs())
    if isinstance(result, dict):
        return result
    return {"ok": False, "status": "invalid_summary_writeback_result"}


def write_reconciled_run_summary(
    *,
    task_id: str,
    run_id: str,
    task: dict[str, Any],
    session: dict[str, Any],
    merged_run: dict[str, Any],
    report: dict[str, Any],
    summary: str,
    write_summary_callback: RunSummaryWritebackCallback,
) -> dict[str, Any]:
    payload = run_summary_projection.build_reconciled_run_summary_writeback_payload(
        task_id=task_id,
        run_id=run_id,
        task=task,
        session=session,
        merged_run=merged_run,
        report=report,
        summary=summary,
    )
    result = write_summary_callback(**payload.as_kwargs())
    if isinstance(result, dict):
        return result
    return {"ok": False, "status": "invalid_summary_writeback_result"}
