from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..models import (
    AgentRunStatus,
    RunMode,
    TaskPhase,
    TaskStatus,
    agent_run_status_details,
    normalize_agent_run_status,
)
from ..state_machine import TaskStateMachine
from ..policies.status_policy import run_details_are_runner_failed


CancelledTaskMessage = Callable[[dict[str, Any]], str]
ActiveRunMessage = Callable[..., str]
CannotStartRunMessage = Callable[..., str]


@dataclass
class RunService:
    cancelled_task_message: CancelledTaskMessage | None = None
    active_run_message: ActiveRunMessage | None = None
    cannot_start_run_message: CannotStartRunMessage | None = None
    default_timeout_seconds: int = 3600
    implementation_timeout_seconds: int = 10800
    qa_timeout_seconds: int = 10800
    merge_test_timeout_seconds: int = 5400

    def start_run_blocker(self, task: dict[str, Any], *, mode: RunMode) -> str:
        if self.task_is_cancelled(task):
            return self._cancelled_task_message(task)
        if self.task_has_active_run(task):
            return self._active_run_message(task, requested_mode=mode.value)
        current_status = str(task.get("status") or TaskStatus.NEW.value)
        try:
            TaskStateMachine.transition(current_status, TaskStatus.RUNNING, reason=f"{mode.value} start")
        except ValueError as exc:
            return self._cannot_start_run_message(task, mode=mode, reason=str(exc))
        return ""

    @staticmethod
    def task_is_cancelled(task: dict[str, Any]) -> bool:
        return str(task.get("status") or "") == TaskStatus.CANCELLED.value

    @staticmethod
    def task_has_active_run(task: dict[str, Any]) -> bool:
        runner = (task.get("task_session") or {}).get("runner") or {}
        return bool(runner.get("active_run_id")) or str(task.get("status") or "") == TaskStatus.RUNNING.value

    @staticmethod
    def task_is_plan_ready_for_implementation(task: dict[str, Any]) -> bool:
        if str(task.get("phase") or "") in {TaskPhase.PLAN_READY.value, TaskPhase.PLAN_APPROVED.value}:
            return True
        for decision in reversed(task.get("human_decisions") or []):
            if decision.get("type") == "implementation_confirmed":
                return True
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") == RunMode.IMPLEMENTATION.value:
                return True
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") == RunMode.PLAN_ONLY.value and run.get("status") == AgentRunStatus.SUCCESS.value:
                return True
        return False

    @staticmethod
    def run_mode_user_label(mode: RunMode | str | None) -> str:
        value = mode.value if isinstance(mode, RunMode) else str(mode or "").strip()
        labels = {
            RunMode.DECOMPOSITION.value: "需求拆解",
            RunMode.PLAN_ONLY.value: "整理计划",
            RunMode.IMPLEMENTATION.value: "实现",
            RunMode.QA.value: "QA 验证",
            RunMode.MERGE_TEST.value: "merge-test",
        }
        return labels.get(value, value or "未记录")

    def timeout_seconds_for_mode(
        self,
        mode: RunMode,
        override: int | None = None,
        *,
        execution_policy: dict[str, Any] | None = None,
    ) -> int:
        if override is not None:
            return override
        policy_timeout = self.policy_timeout_seconds(execution_policy)
        if mode == RunMode.IMPLEMENTATION:
            if policy_timeout and self.policy_uses_targeted_verification(execution_policy):
                return min(self.implementation_timeout_seconds, policy_timeout)
            return self.implementation_timeout_seconds
        if mode == RunMode.QA:
            if policy_timeout and self.policy_uses_targeted_verification(execution_policy):
                return min(self.qa_timeout_seconds, policy_timeout)
            return self.qa_timeout_seconds
        if mode == RunMode.MERGE_TEST:
            return self.merge_test_timeout_seconds
        return self.default_timeout_seconds

    @staticmethod
    def policy_timeout_seconds(execution_policy: dict[str, Any] | None) -> int:
        if not isinstance(execution_policy, dict):
            return 0
        try:
            value = int(execution_policy.get("max_duration_seconds") or 0)
        except (TypeError, ValueError):
            return 0
        return value if value > 0 else 0

    @staticmethod
    def policy_uses_targeted_verification(execution_policy: dict[str, Any] | None) -> bool:
        if not isinstance(execution_policy, dict):
            return False
        route = str(execution_policy.get("route") or "")
        verification = str(execution_policy.get("verification") or "")
        return verification == "targeted" or route in {"fast_fix", "targeted_ui_fix"}

    @staticmethod
    def running_phase_for_mode(mode: RunMode) -> TaskPhase:
        if mode in {RunMode.DECOMPOSITION, RunMode.PLAN_ONLY}:
            return TaskPhase.PLANNING
        if mode == RunMode.QA:
            return TaskPhase.QA_VERIFYING
        if mode == RunMode.MERGE_TEST:
            return TaskPhase.READY_TO_MERGE_TEST
        return TaskPhase.IMPLEMENTING

    @staticmethod
    def task_status_for_run_result(
        mode: RunMode,
        status: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> TaskStatus:
        if details and details.get("structured") is False:
            return TaskStatus.BLOCKED
        status = normalize_agent_run_status(status, mode)
        if mode == RunMode.DECOMPOSITION and status == AgentRunStatus.SUCCEEDED.value:
            return TaskStatus.PLANNED
        if mode == RunMode.PLAN_ONLY and status == AgentRunStatus.SUCCESS.value:
            return TaskStatus.PLANNED
        if mode in {RunMode.IMPLEMENTATION, RunMode.QA} and status in {
            AgentRunStatus.SUCCESS.value,
            AgentRunStatus.READY_FOR_MERGE_TEST.value,
        }:
            return TaskStatus.READY_FOR_MERGE_TEST
        if mode in {RunMode.IMPLEMENTATION, RunMode.QA} and status in {
            AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value,
        }:
            return TaskStatus.READY_FOR_MERGE_TEST
        if mode == RunMode.MERGE_TEST and status == AgentRunStatus.SUCCESS.value:
            return TaskStatus.MERGED_TEST
        return TaskStateMachine.task_status_for_run_status(status)

    @staticmethod
    def task_phase_for_run_result(
        mode: RunMode,
        status: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> TaskPhase:
        status = normalize_agent_run_status(status, mode)
        details = details or agent_run_status_details(status, mode)
        if details.get("structured") is False:
            return TaskPhase.BLOCKED
        if RunService.run_details_are_runner_failed(details):
            return TaskPhase.RUNNER_FAILED
        if mode == RunMode.DECOMPOSITION:
            if status == AgentRunStatus.SUCCEEDED.value:
                return TaskPhase.PLAN_READY
            if status == AgentRunStatus.BLOCKED.value:
                return TaskPhase.BLOCKED
            if status == AgentRunStatus.CANCELLED.value:
                return TaskPhase.CANCELLED
            return TaskPhase.FAILED
        if mode == RunMode.PLAN_ONLY:
            if status == AgentRunStatus.SUCCEEDED.value:
                return TaskPhase.PLAN_READY
            if status == AgentRunStatus.BLOCKED.value:
                return TaskPhase.BLOCKED
            return TaskPhase.FAILED
        if mode == RunMode.MERGE_TEST:
            if status == AgentRunStatus.SUCCEEDED.value:
                return TaskPhase.MERGED_TEST
            if status == AgentRunStatus.BLOCKED.value:
                return TaskPhase.BLOCKED
            if status == AgentRunStatus.CANCELLED.value:
                return TaskPhase.CANCELLED
            return TaskPhase.FAILED
        if mode == RunMode.QA:
            if status == AgentRunStatus.SUCCEEDED.value:
                return TaskPhase.READY_TO_MERGE_TEST
            if status == AgentRunStatus.BLOCKED.value:
                return TaskPhase.BLOCKED
            if status == AgentRunStatus.CANCELLED.value:
                return TaskPhase.CANCELLED
            return TaskPhase.FAILED
        if status == AgentRunStatus.SUCCEEDED.value:
            return TaskPhase.READY_TO_MERGE_TEST
        if status == AgentRunStatus.BLOCKED.value:
            return TaskPhase.BLOCKED
        if status == AgentRunStatus.CANCELLED.value:
            return TaskPhase.CANCELLED
        return TaskPhase.FAILED

    @staticmethod
    def run_details_are_runner_failed(details: dict[str, Any]) -> bool:
        return run_details_are_runner_failed(details)

    def _cancelled_task_message(self, task: dict[str, Any]) -> str:
        if self.cancelled_task_message is not None:
            return self.cancelled_task_message(task)
        return f"[{task.get('task_id') or 'unknown'}] 已取消，不能继续操作。"

    def _active_run_message(self, task: dict[str, Any], *, requested_mode: str | None = None) -> str:
        if self.active_run_message is not None:
            try:
                return self.active_run_message(task, requested_mode=requested_mode)
            except TypeError:
                return self.active_run_message(task)
        return f"[{task.get('task_id') or 'unknown'}] 当前已有执行正在进行。"

    def _cannot_start_run_message(self, task: dict[str, Any], *, mode: RunMode, reason: str) -> str:
        if self.cannot_start_run_message is not None:
            try:
                return self.cannot_start_run_message(task, mode=mode, reason=reason)
            except TypeError:
                return self.cannot_start_run_message(task, mode, reason)
        return f"[{task.get('task_id') or 'unknown'}] 当前状态不能启动{self.run_mode_user_label(mode)}执行。\n原因：{reason}"
