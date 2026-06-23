from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import (
    kanban_sync_service,
    run_status_transition_service,
    task_lifecycle_guard_service,
)
from ..coding_commands import (
    coding_feedback_command_executor,
    coding_status_command_executor,
    coding_task_list_command_executor,
)
from ..models import RunMode, TaskPhase, TaskStatus
from ..presenters import task_status_presenter
from ..services import RunService


class OrchestratorTaskRuntimeFacadeMixin:
    def _sync_task_to_kanban(
        self,
        *,
        task_id: str,
        title: str,
        body: str,
        project_name: str,
        project_path: str,
        status: str,
    ) -> dict[str, Any] | None:
        return kanban_sync_service.sync_task_to_kanban(
            self,
            task_id=task_id,
            title=title,
            body=body,
            project_name=project_name,
            project_path=project_path,
            status=status,
        )

    def _transition_task_status(
        self,
        task_id: str,
        status: TaskStatus | str,
        *,
        phase: TaskPhase | str | None = None,
        reason: str = "",
        sync_kanban: bool = True,
    ) -> dict[str, Any]:
        return run_status_transition_service.transition_task_status(
            task_id=task_id,
            status=status,
            phase=phase,
            reason=reason,
            sync_kanban=sync_kanban,
            get_task_callback=self.ledger.get_task,
            update_status_callback=self.ledger.update_status,
            update_phase_callback=self.ledger.update_phase,
            sync_status_to_kanban_callback=self._sync_status_to_kanban,
            kanban_sync_skipped_callback=self._kanban_sync_skipped,
        )

    def _sync_status_to_kanban(self, task_id: str, status: TaskStatus | str, *, reason: str = "") -> dict[str, Any]:
        return kanban_sync_service.sync_status_to_kanban(self, task_id, status, reason=reason)

    def _kanban_sync_skipped(self, task_id: str, status: str, *, reason: str) -> dict[str, Any]:
        return kanban_sync_service.kanban_sync_skipped(self, task_id, status, reason=reason)

    @staticmethod
    def _kanban_sync_record_from_result(result: dict[str, Any], status_view: dict[str, str]) -> dict[str, Any]:
        return kanban_sync_service.kanban_sync_record_from_result(result, status_view)

    @staticmethod
    def _task_status_sync_fields(status_view: dict[str, str]) -> dict[str, str]:
        return kanban_sync_service.task_status_sync_fields(status_view)

    def _format_task_list_for_event(self, event: Any) -> str:
        return coding_task_list_command_executor.task_list_for_event(self, event)

    def _status_for_event(self, raw_args: str, event: Any) -> str:
        return coding_status_command_executor.status_for_event(self, raw_args, event)

    @staticmethod
    def _read_report_json(path_value: Any) -> dict[str, Any]:
        return task_status_presenter.read_report_json(path_value)

    def _continue_active_task(self, raw_args: str, event: Any, gateway: Any) -> str:
        return coding_feedback_command_executor.continue_active_task(self, raw_args, event, gateway)

    def _change_active_task(self, raw_args: str, event: Any, gateway: Any) -> str:
        return coding_feedback_command_executor.change_active_task(self, raw_args, event, gateway)

    def _bugfix_active_task(self, raw_args: str, event: Any, gateway: Any) -> str:
        return coding_feedback_command_executor.bugfix_active_task(self, raw_args, event, gateway)

    def _reopen_merged_test_task_for_bugfix_if_needed(self, task: dict[str, Any], event: Any) -> dict[str, Any]:
        return task_lifecycle_guard_service.reopen_merged_test_task_for_bugfix_if_needed(self, task, event)

    def _bind_active_task_for_event(self, task_id: str, event: Any | None) -> bool:
        return self.gateway_binding_service.bind_active_task_for_event(task_id, event)

    def _enable_coding_mode_for_event(self, event: Any | None) -> bool:
        return self.gateway_binding_service.enable_coding_mode_for_event(event)

    def _disable_coding_mode_for_event(self, event: Any | None) -> bool:
        return self.gateway_binding_service.disable_coding_mode_for_event(event)

    def _coding_mode_enabled_for_event(self, event: Any | None) -> bool:
        return self.gateway_binding_service.coding_mode_enabled_for_event(event)

    def _coding_mode_binding_key_for_event(self, event: Any | None) -> str | None:
        return self.gateway_binding_service.coding_mode_binding_key_for_event(event)

    def _active_task_for_event(self, event: Any) -> dict[str, Any] | None:
        task_id = self._active_task_id_for_event(event)
        return self.ledger.get_task(task_id) if task_id else None

    def active_task_for_session(self, *, session_id: str, platform: str = "feishu") -> str | None:
        return self.gateway_binding_service.active_task_for_session(session_id=session_id, platform=platform)

    def _active_task_id_for_event(self, event: Any) -> str | None:
        return self.gateway_binding_service.active_task_id_for_event(event)

    def _binding_key_for_event(self, event: Any | None) -> str | None:
        return self.gateway_binding_service.binding_key_for_event(event)

    @staticmethod
    def _active_coding_statuses() -> list[str]:
        return task_lifecycle_guard_service.active_coding_statuses()

    @staticmethod
    def _task_is_cancelled(task: dict[str, Any]) -> bool:
        return task_lifecycle_guard_service.task_is_cancelled(task)

    @staticmethod
    def _cancelled_task_message(task: dict[str, Any] | str) -> str:
        return task_lifecycle_guard_service.cancelled_task_message(task)

    def _restore_state_for_cancelled_task(self, task: dict[str, Any]) -> tuple[TaskStatus, TaskPhase, str]:
        return task_lifecycle_guard_service.restore_state_for_cancelled_task(self, task)

    def _record_implementation_confirmation(self, task_id: str, text: str, event: Any) -> None:
        self.ledger.update_phase(task_id, TaskPhase.PLAN_APPROVED.value)
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "implementation_confirmed",
                "text": text,
                "gateway_source": self._event_source_for_ledger(event),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _record_implementation_confirmation_before_plan_ready(self, task_id: str, text: str, event: Any) -> None:
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "implementation_confirmation_before_plan_ready",
                "text": text,
                "gateway_source": self._event_source_for_ledger(event),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _record_qa_request(self, task_id: str, text: str, event: Any | None) -> None:
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "qa_requested",
                "text": text,
                "gateway_source": self._event_source_for_ledger(event),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _task_is_plan_ready_for_implementation(task: dict[str, Any]) -> bool:
        return RunService.task_is_plan_ready_for_implementation(task)

    @staticmethod
    def _task_has_active_run(task: dict[str, Any]) -> bool:
        return RunService.task_has_active_run(task)

    def _start_run_blocker(self, task: dict[str, Any], *, mode: RunMode) -> str:
        return self.run_service.start_run_blocker(task, mode=mode)

    def _qa_start_blocker(self, task: dict[str, Any]) -> str:
        blocked = self._start_run_blocker(task, mode=RunMode.QA)
        if blocked:
            return blocked
        task_id = str(task.get("task_id") or "unknown")
        if self._merge_test_workspace(task) is None:
            return (
                f"[{task_id}] 未找到实现工作区，无法执行 QA。\n"
                "建议：请先完成实现，或恢复实现工作区后再发送 /coding qa。"
            )
        return ""

    def _clear_active_run_if_matches(self, task_id: str, run_id: str) -> None:
        run_status_transition_service.clear_active_run_if_matches(
            task_id=task_id,
            run_id=run_id,
            get_task_callback=self.ledger.get_task,
            update_task_session_callback=self.ledger.update_task_session,
        )
