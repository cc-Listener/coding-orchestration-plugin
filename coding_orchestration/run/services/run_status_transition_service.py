from __future__ import annotations

from typing import Any, Callable

from ...models import RunMode, TaskPhase, TaskStatus, canonical_task_status, task_status_display
from ...state_machine import TaskStateMachine
from . import run_session_writeback_service

TransitionTaskStatusCallback = Callable[..., dict[str, Any]]
ClearActiveRunCallback = Callable[[str, str], None]
GetTaskCallback = Callable[[str], dict[str, Any] | None]
UpdateTaskSessionCallback = Callable[[str, dict[str, Any]], None]
UpdateStatusCallback = Callable[[str, str], None]
UpdatePhaseCallback = Callable[[str, str], None]
KanbanSyncCallback = Callable[..., dict[str, Any]]


def transition_task_status(
    *,
    task_id: str,
    status: TaskStatus | str,
    phase: TaskPhase | str | None = None,
    reason: str = "",
    sync_kanban: bool = True,
    get_task_callback: GetTaskCallback,
    update_status_callback: UpdateStatusCallback,
    update_phase_callback: UpdatePhaseCallback,
    sync_status_to_kanban_callback: KanbanSyncCallback,
    kanban_sync_skipped_callback: KanbanSyncCallback,
) -> dict[str, Any]:
    task = get_task_callback(task_id)
    if not task:
        return {"ok": False, "task_id": task_id, "error": f"task not found: {task_id}"}
    requested_status = status.value if isinstance(status, TaskStatus) else str(status)
    canonical_target = canonical_task_status(requested_status)
    if canonical_target is None:
        return {"ok": False, "task_id": task_id, "error": f"invalid task status: {requested_status}"}
    target_status = canonical_target.value
    current_status = str(task.get("status") or TaskStatus.NEW.value)
    current_canonical = canonical_task_status(current_status)
    if current_canonical is None:
        return {"ok": False, "task_id": task_id, "error": f"invalid current task status: {current_status}"}
    if current_canonical.value != target_status:
        target_status = TaskStateMachine.transition(current_status, requested_status, reason=reason).value
    update_status_callback(task_id, target_status)
    if phase is not None:
        phase_value = phase.value if isinstance(phase, TaskPhase) else str(phase)
        update_phase_callback(task_id, phase_value)
    kanban_sync = (
        sync_status_to_kanban_callback(task_id, target_status, reason=reason)
        if sync_kanban
        else kanban_sync_skipped_callback(task_id, target_status, reason="kanban_sync_disabled")
    )
    return {
        "ok": True,
        "task_id": task_id,
        "status": target_status,
        "status_display": task_status_display(target_status),
        "kanban_sync": kanban_sync,
    }


def transition_missing_project_path(
    *,
    task_id: str,
    transition_task_status_callback: TransitionTaskStatusCallback,
) -> dict[str, Any]:
    return transition_task_status_callback(
        task_id,
        TaskStatus.NEEDS_HUMAN,
        reason="task has no project_path",
    )


def transition_missing_workspace(
    *,
    task_id: str,
    reason: str,
    transition_task_status_callback: TransitionTaskStatusCallback,
) -> dict[str, Any]:
    return transition_task_status_callback(
        task_id,
        TaskStatus.BLOCKED,
        phase=TaskPhase.BLOCKED,
        reason=reason,
    )


def transition_run_started(
    *,
    task_id: str,
    run_id: str,
    mode: RunMode,
    running_phase: TaskPhase,
    transition_task_status_callback: TransitionTaskStatusCallback,
    clear_active_run_callback: ClearActiveRunCallback,
) -> dict[str, Any]:
    try:
        return transition_task_status_callback(
            task_id,
            TaskStatus.RUNNING,
            phase=running_phase,
            reason=f"{mode.value} started",
        )
    except Exception:
        clear_active_run_callback(task_id, run_id)
        raise


def transition_completed_run_task_status(
    *,
    task_id: str,
    mode: RunMode,
    status: str,
    task_status: TaskStatus,
    task_phase: TaskPhase,
    stale_completion: bool,
    transition_task_status_callback: TransitionTaskStatusCallback,
) -> dict[str, Any]:
    if stale_completion:
        return {"ok": False, "status": "skipped_stale_completion"}
    return transition_task_status_callback(
        task_id,
        task_status,
        phase=task_phase,
        reason=f"{mode.value} completed with {status}",
    )


def transition_reconciled_run_task_status(
    *,
    task_id: str,
    mode: RunMode,
    status: str,
    task_status: TaskStatus,
    task_phase: TaskPhase,
    transition_task_status_callback: TransitionTaskStatusCallback,
) -> dict[str, Any]:
    return transition_task_status_callback(
        task_id,
        task_status,
        phase=task_phase,
        reason=f"{mode.value} reconciled with completed artifact status {status}",
    )


def clear_active_run_if_matches(
    *,
    task_id: str,
    run_id: str,
    get_task_callback: GetTaskCallback,
    update_task_session_callback: UpdateTaskSessionCallback,
) -> None:
    task = get_task_callback(task_id) or {}
    runner = (task.get("task_session") or {}).get("runner") or {}
    if str(runner.get("active_run_id") or "") != run_id:
        return
    run_session_writeback_service.write_run_session_update(
        task_id=task_id,
        update={
            "runner": {
                "active_run_id": None,
                "active_mode": None,
            }
        },
        update_task_session_callback=update_task_session_callback,
    )
