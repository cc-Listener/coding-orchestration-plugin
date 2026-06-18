from __future__ import annotations

from typing import Any, Callable

from .models import RunMode, TaskStatus
from .run_orchestration_service import build_project_writeback_payload

ProjectWritebackCallback = Callable[[str, dict[str, Any]], dict[str, Any]]


def write_run_project_completion(
    *,
    task_id: str,
    mode: RunMode,
    run_id: str,
    status: str,
    task_status: TaskStatus | str,
    report: dict[str, Any],
    stale_completion: bool,
    writeback_callback: ProjectWritebackCallback,
) -> dict[str, Any]:
    if stale_completion:
        return {"ok": False, "status": "skipped_stale_completion"}

    payload = build_project_writeback_payload(
        run_id=run_id,
        status=status,
        task_status=task_status,
        report=report,
    )
    result = writeback_callback(task_id, payload, mode=mode)
    if isinstance(result, dict):
        return result
    return {"ok": False, "status": "invalid_writeback_result"}
