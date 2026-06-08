from __future__ import annotations

from .models import AgentRunStatus, TaskStatus, canonical_task_status, normalize_agent_run_status


class InvalidTransition(ValueError):
    pass


class TaskStateMachine:
    _ALLOWED: dict[TaskStatus, set[TaskStatus]] = {
        TaskStatus.NEW: {
            TaskStatus.NEEDS_HUMAN,
            TaskStatus.PLANNED,
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
        },
        TaskStatus.NEEDS_HUMAN: {
            TaskStatus.PLANNED,
            TaskStatus.RUNNING,
            TaskStatus.CANCELLED,
        },
        TaskStatus.PLANNED: {
            TaskStatus.RUNNING,
            TaskStatus.NEEDS_HUMAN,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.RUNNING: {
            TaskStatus.PLANNED,
            TaskStatus.MERGED_TEST,
            TaskStatus.BLOCKED,
            TaskStatus.READY_FOR_MERGE_TEST,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.BLOCKED: {
            TaskStatus.PLANNED,
            TaskStatus.RUNNING,
            TaskStatus.READY_FOR_MERGE_TEST,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.READY_FOR_MERGE_TEST: {
            TaskStatus.RUNNING,
            TaskStatus.BLOCKED,
            TaskStatus.FAILED,
            TaskStatus.MERGED_TEST,
            TaskStatus.DONE,
            TaskStatus.PLANNED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.FAILED: {TaskStatus.PLANNED, TaskStatus.RUNNING, TaskStatus.CANCELLED},
        TaskStatus.MERGED_TEST: {TaskStatus.DONE, TaskStatus.PLANNED, TaskStatus.CANCELLED},
        TaskStatus.CANCELLED: {
            TaskStatus.NEEDS_HUMAN,
            TaskStatus.PLANNED,
            TaskStatus.RUNNING,
            TaskStatus.FAILED,
            TaskStatus.READY_FOR_MERGE_TEST,
            TaskStatus.MERGED_TEST,
        },
        TaskStatus.DONE: {TaskStatus.PLANNED},
    }

    _RUN_TO_TASK: dict[AgentRunStatus, TaskStatus] = {
        AgentRunStatus.RUNNING: TaskStatus.RUNNING,
        AgentRunStatus.SUCCEEDED: TaskStatus.READY_FOR_MERGE_TEST,
        AgentRunStatus.BLOCKED: TaskStatus.BLOCKED,
        AgentRunStatus.FAILED: TaskStatus.FAILED,
        AgentRunStatus.CANCELLED: TaskStatus.CANCELLED,
    }

    @classmethod
    def transition(cls, current: TaskStatus | str, target: TaskStatus | str, reason: str = "") -> TaskStatus:
        current_status = canonical_task_status(current)
        target_status = canonical_task_status(target)
        if current_status is None or target_status is None:
            raise InvalidTransition(f"invalid task transition {current} -> {target}: {reason}")
        allowed_targets = {canonical_task_status(allowed) for allowed in cls._ALLOWED[current_status]}
        if target_status not in allowed_targets:
            raise InvalidTransition(
                f"invalid task transition {current_status.value} -> {target_status.value}: {reason}"
            )
        return target_status

    @classmethod
    def task_status_for_run_status(cls, run_status: AgentRunStatus | str) -> TaskStatus:
        status = AgentRunStatus(normalize_agent_run_status(run_status))
        task_status = canonical_task_status(cls._RUN_TO_TASK[status])
        if task_status is None:
            raise InvalidTransition(f"runner status {status.value} has no task status mapping")
        return task_status

    @classmethod
    def task_status_for_source_status(cls, source_status: str) -> TaskStatus:
        mapping = {
            "ok": TaskStatus.PLANNED,
            "missing": TaskStatus.PLANNED,
            "deferred": TaskStatus.NEEDS_HUMAN,
            "auth_needed": TaskStatus.NEEDS_HUMAN,
            "permission_missing": TaskStatus.NEEDS_HUMAN,
        }
        return mapping.get(str(source_status or "").strip(), TaskStatus.NEEDS_HUMAN)
