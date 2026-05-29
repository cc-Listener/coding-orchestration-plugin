from __future__ import annotations

from .models import AgentRunStatus, TaskStatus


class InvalidTransition(ValueError):
    pass


class TaskStateMachine:
    _ALLOWED: dict[TaskStatus, set[TaskStatus]] = {
        TaskStatus.NEW: {TaskStatus.NEEDS_HUMAN, TaskStatus.PLANNED, TaskStatus.QUEUED},
        TaskStatus.NEEDS_HUMAN: {TaskStatus.PLANNED, TaskStatus.CANCELLED},
        TaskStatus.PLANNED: {TaskStatus.QUEUED, TaskStatus.NEEDS_HUMAN, TaskStatus.CANCELLED},
        TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED},
        TaskStatus.RUNNING: {
            TaskStatus.MERGED_TEST,
            TaskStatus.BLOCKED,
            TaskStatus.READY_FOR_MERGE_TEST,
            TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS,
            TaskStatus.RUNNER_FAILED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.BLOCKED: {
            TaskStatus.PLANNED,
            TaskStatus.QUEUED,
            TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS,
            TaskStatus.CANCELLED,
        },
        TaskStatus.READY_FOR_MERGE_TEST: {
            TaskStatus.QUEUED,
            TaskStatus.DONE,
            TaskStatus.PLANNED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS: {
            TaskStatus.QUEUED,
            TaskStatus.DONE,
            TaskStatus.PLANNED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.RUNNER_FAILED: {TaskStatus.PLANNED, TaskStatus.CANCELLED},
        TaskStatus.FAILED: {TaskStatus.PLANNED, TaskStatus.CANCELLED},
        TaskStatus.MERGED_TEST: {TaskStatus.DONE, TaskStatus.PLANNED, TaskStatus.CANCELLED},
        TaskStatus.CANCELLED: {TaskStatus.PLANNED},
        TaskStatus.DONE: {TaskStatus.PLANNED},
    }

    _RUN_TO_TASK: dict[AgentRunStatus, TaskStatus] = {
        AgentRunStatus.QUEUED: TaskStatus.QUEUED,
        AgentRunStatus.RUNNING: TaskStatus.RUNNING,
        AgentRunStatus.SUCCESS: TaskStatus.READY_FOR_MERGE_TEST,
        AgentRunStatus.FAILED: TaskStatus.FAILED,
        AgentRunStatus.BLOCKED: TaskStatus.BLOCKED,
        AgentRunStatus.CANCELLED: TaskStatus.CANCELLED,
        AgentRunStatus.TIMEOUT: TaskStatus.RUNNER_FAILED,
        AgentRunStatus.ORPHANED: TaskStatus.FAILED,
        AgentRunStatus.COMPLETED_UNSTRUCTURED: TaskStatus.BLOCKED,
        AgentRunStatus.READY_FOR_MERGE_TEST: TaskStatus.READY_FOR_MERGE_TEST,
        AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS: TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS,
        AgentRunStatus.RUNNER_FAILED: TaskStatus.RUNNER_FAILED,
    }

    @classmethod
    def transition(cls, current: TaskStatus | str, target: TaskStatus | str, reason: str = "") -> TaskStatus:
        current_status = TaskStatus(current)
        target_status = TaskStatus(target)
        if target_status not in cls._ALLOWED[current_status]:
            raise InvalidTransition(
                f"invalid task transition {current_status.value} -> {target_status.value}: {reason}"
            )
        return target_status

    @classmethod
    def task_status_for_run_status(cls, run_status: AgentRunStatus | str) -> TaskStatus:
        status = AgentRunStatus(run_status)
        return cls._RUN_TO_TASK[status]
