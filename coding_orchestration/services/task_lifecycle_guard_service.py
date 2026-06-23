from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import AgentRunStatus, RunMode, TaskPhase, TaskStatus, task_status_display
from .run_service import RunService


def active_coding_statuses() -> list[str]:
    return [
        TaskStatus.NEEDS_HUMAN.value,
        TaskStatus.PLANNED.value,
        TaskStatus.RUNNING.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.READY_FOR_MERGE_TEST.value,
        TaskStatus.FAILED.value,
        TaskStatus.MERGED_TEST.value,
    ]


def task_is_cancelled(task: dict[str, Any]) -> bool:
    return RunService.task_is_cancelled(task)


def cancelled_task_message(task: dict[str, Any] | str) -> str:
    task_id = task if isinstance(task, str) else str(task.get("task_id") or "unknown")
    return (
        f"[{task_id}] 已取消，不能继续操作。\n"
        f"状态：{task_status_display(TaskStatus.CANCELLED)}\n"
        "说明：已取消是人工终态保护；不会再启动计划、实现、QA 或 merge-test。"
    )


def restore_state_for_cancelled_task(host: Any, task: dict[str, Any]) -> tuple[TaskStatus, TaskPhase, str]:
    for run in reversed(task.get("agent_runs") or []):
        mode = str(run.get("mode") or "")
        status = str(run.get("status") or "")
        try:
            run_mode = RunMode(mode)
        except ValueError:
            run_mode = RunMode.PLAN_ONLY
        details = host._run_status_details_from_report(run, run_mode, fallback_status=status)
        canonical_status = str(details.get("status") or "")
        if mode == RunMode.MERGE_TEST.value:
            if details.get("structured") is False or details.get("status_detail") == "completed_unstructured":
                return (
                    TaskStatus.READY_FOR_MERGE_TEST,
                    TaskPhase.READY_TO_MERGE_TEST,
                    f"最近 merge-test 非结构化结束（{status or 'unknown'}），恢复为可重新 merge-test",
                )
            if canonical_status == AgentRunStatus.SUCCEEDED.value:
                return TaskStatus.MERGED_TEST, TaskPhase.MERGED_TEST, "最近 merge-test 已成功"
            return (
                TaskStatus.READY_FOR_MERGE_TEST,
                TaskPhase.READY_TO_MERGE_TEST,
                f"最近 merge-test 未完成（{status or 'unknown'}），恢复为可重新 merge-test",
            )
        if mode in {RunMode.IMPLEMENTATION.value, RunMode.QA.value}:
            if canonical_status == AgentRunStatus.SUCCEEDED.value and details.get("structured") is not False:
                return TaskStatus.READY_FOR_MERGE_TEST, TaskPhase.READY_TO_MERGE_TEST, f"最近 {mode} 已准备 merge-test"
            if canonical_status == AgentRunStatus.BLOCKED.value or details.get("structured") is False:
                return (
                    TaskStatus.BLOCKED,
                    TaskPhase.BLOCKED,
                    f"最近 {mode} 未提供完整结构化完成证据（{status or 'unknown'}）",
                )
            if host._run_details_are_runner_failed(details):
                return TaskStatus.FAILED, TaskPhase.RUNNER_FAILED, f"最近 {mode} runner_failed"
            if canonical_status == AgentRunStatus.FAILED.value:
                return TaskStatus.FAILED, TaskPhase.FAILED, f"最近 {mode} failed"
        if mode == RunMode.PLAN_ONLY.value and canonical_status == AgentRunStatus.SUCCEEDED.value:
            return TaskStatus.PLANNED, TaskPhase.PLAN_READY, "最近 plan-only 已完成"
    if task.get("project_path"):
        return TaskStatus.PLANNED, TaskPhase.PLAN_READY, "未找到可用 run，按已有项目上下文恢复为 planned"
    return TaskStatus.NEEDS_HUMAN, TaskPhase.DRAFT, "未找到项目上下文，恢复为 needs_human"


def reopen_merged_test_task_for_bugfix_if_needed(host: Any, task: dict[str, Any], event: Any) -> dict[str, Any]:
    if str(task.get("status") or "") != TaskStatus.MERGED_TEST.value:
        return task
    task_id = str(task["task_id"])
    host._transition_task_status(
        task_id,
        TaskStatus.PLANNED,
        phase=TaskPhase.BUGFIXING,
        reason="bugfix feedback after merged_test",
    )
    host.ledger.append_human_decision(
        task_id,
        {
            "type": "merged_test_reopened_for_bugfix",
            "previous_status": TaskStatus.MERGED_TEST.value,
            "previous_phase": task.get("phase"),
            "gateway_source": host._event_source_for_ledger(event),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return host.ledger.get_task(task_id) or task
