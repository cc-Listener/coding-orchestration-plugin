from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunSummaryWritebackPayload:
    task_id: str
    run_id: str
    runner: str
    project: str
    report: dict[str, Any]
    summary: str

    def as_kwargs(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "runner": self.runner,
            "project": self.project,
            "report": dict(self.report),
            "summary": self.summary,
        }


def build_reconciled_run_summary_writeback_payload(
    *,
    task_id: str,
    run_id: str,
    task: dict[str, Any],
    session: dict[str, Any],
    merged_run: dict[str, Any],
    report: dict[str, Any],
    summary: str,
) -> RunSummaryWritebackPayload:
    source = task.get("source") or {}
    project = str(session.get("project_name") or source.get("project_name") or "")
    return RunSummaryWritebackPayload(
        task_id=task_id,
        run_id=run_id,
        runner=str(merged_run.get("runner") or ""),
        project=project,
        report=dict(report),
        summary=summary,
    )


def build_completed_run_summary_writeback_payload(
    *,
    task_id: str,
    run_id: str,
    runner: Any,
    project_name: Any,
    report: dict[str, Any],
    summary: str,
) -> RunSummaryWritebackPayload:
    return RunSummaryWritebackPayload(
        task_id=task_id,
        run_id=run_id,
        runner=str(runner or ""),
        project=str(project_name or ""),
        report=dict(report),
        summary=summary,
    )
