from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..feishu.feishu_copy import render_user_update
from ..models import TaskPhase, TaskStatus
from ..services import DeliveryService
from .. import (
    delivery_command_executor,
    project_command_executor,
    run_completion_presenter,
)
from ..coding_commands import (
    coding_feedback_command_executor,
    coding_help_command_executor,
    coding_merge_test_command_executor,
    coding_run_command_executor,
    coding_status_command_executor,
    coding_task_control_command_executor,
    coding_task_list_command_executor,
)


class OrchestratorCommandFacadeMixin:
    def command_coding(self, raw_args: str = "") -> str:
        command, rest = self._normalize_coding_gateway_command("coding", raw_args)
        if command == "coding-help":
            return self.command_coding_help(rest)
        if command == "coding-doctor":
            return self.command_coding_doctor()
        if command == "coding-lark-preflight":
            return self._format_lark_preflight(self.tool_lark_preflight({}))
        if command == "coding-project-mcp-preflight":
            return self._format_project_mcp_preflight()
        if command == "coding-source-resolve":
            return self._format_source_resolve(rest)
        if command == "coding-task":
            return self.command_coding_task(rest)
        if command == "coding-list":
            return self.command_coding_list(rest)
        if command == "coding-project-list":
            return self.command_coding_project_list(rest)
        if command == "coding-project-init":
            return self.command_coding_project_init(rest)
        if command == "coding-project-use":
            return self.command_coding_project_use(rest)
        if command == "coding-project-status":
            return self.command_coding_project_status(rest)
        if command == "coding-project-clear":
            return self.command_coding_project_clear(rest)
        if command == "coding-use":
            return self.command_coding_use(rest)
        if command == "coding-exit":
            return self.command_coding_exit(rest)
        if command == "coding-status":
            return self.command_coding_status(rest)
        if command == "coding-continue":
            return self.command_coding_continue(rest)
        if command == "coding-change":
            return self.command_coding_change(rest)
        if command == "coding-bugfix":
            return self.command_coding_bugfix(rest)
        if command == "coding-run":
            return self.command_coding_run(rest)
        if command == "coding-analyze":
            return self.command_coding_analyze(rest)
        if command == "coding-breakdown":
            return self.command_coding_breakdown(rest)
        if command == "coding-approve-breakdown":
            return self.command_coding_approve_breakdown(rest)
        if command == "coding-materialize":
            return self.command_coding_materialize(rest)
        if command == "coding-implement":
            return self.command_coding_implement(rest)
        if command == "coding-qa":
            return self.command_coding_qa(rest)
        if command == "coding-cancel":
            return self.command_coding_cancel(rest)
        if command == "coding-restore":
            return self.command_coding_restore(rest)
        if command == "coding-delete":
            return self.command_coding_delete(rest)
        if command == "coding-prepare-merge-test":
            return self.command_prepare_merge_test(rest)
        if command == "coding-merge-test":
            return self.command_coding_merge_test(rest)
        if command == "coding-complete":
            return self.command_coding_complete(rest)
        return self.command_coding_help(raw_args)

    def command_coding_help(self, raw_args: str = "") -> str:
        return coding_help_command_executor.command_coding_help(self, raw_args)

    def command_commands_listing(self, raw_args: str = "") -> str:
        return coding_help_command_executor.command_commands_listing(self, raw_args)

    @staticmethod
    def _hermes_gateway_command_lines() -> list[str]:
        return coding_help_command_executor.hermes_gateway_command_lines()

    def command_coding_list(self, raw_args: str = "") -> str:
        return coding_task_list_command_executor.command_coding_list(self, raw_args)

    def command_coding_project_list(self, raw_args: str = "") -> str:
        return project_command_executor.command_coding_project_list(self, raw_args)

    def command_coding_project_init(self, raw_args: str = "") -> str:
        return project_command_executor.command_coding_project_init(self, raw_args)

    def command_coding_project_use(self, raw_args: str = "") -> str:
        return project_command_executor.command_coding_project_use(self, raw_args)

    def command_coding_project_status(self, raw_args: str = "") -> str:
        return project_command_executor.command_coding_project_status(self, raw_args)

    def command_coding_project_clear(self, raw_args: str = "") -> str:
        return project_command_executor.command_coding_project_clear(self, raw_args)

    def command_coding_use(self, raw_args: str) -> str:
        return coding_task_control_command_executor.command_coding_use(self, raw_args)

    def command_coding_exit(self, raw_args: str = "") -> str:
        return coding_task_control_command_executor.command_coding_exit(self, raw_args)

    def command_coding_continue(self, raw_args: str) -> str:
        return coding_feedback_command_executor.command_coding_continue(self, raw_args)

    def command_coding_change(self, raw_args: str) -> str:
        return coding_feedback_command_executor.command_coding_change(self, raw_args)

    def command_coding_bugfix(self, raw_args: str) -> str:
        return coding_feedback_command_executor.command_coding_bugfix(self, raw_args)

    def command_coding_status(self, raw_args: str) -> str:
        return coding_status_command_executor.command_coding_status(self, raw_args)

    def command_coding_cancel(self, raw_args: str) -> str:
        return coding_task_control_command_executor.command_coding_cancel(self, raw_args)

    def command_coding_restore(self, raw_args: str) -> str:
        return coding_task_control_command_executor.command_coding_restore(self, raw_args)

    def command_coding_delete(self, raw_args: str) -> str:
        return coding_task_control_command_executor.command_coding_delete(self, raw_args)

    def command_coding_run(self, raw_args: str) -> str:
        args = raw_args.split()
        if "--next" in args:
            return delivery_command_executor.command_coding_run_next(self, raw_args)
        return coding_run_command_executor.command_coding_run(self, raw_args)

    def command_coding_analyze(self, raw_args: str) -> str:
        return delivery_command_executor.command_coding_analyze(self, raw_args)

    def command_coding_breakdown(self, raw_args: str) -> str:
        return delivery_command_executor.command_coding_breakdown(self, raw_args)

    def command_coding_approve_breakdown(self, raw_args: str) -> str:
        return delivery_command_executor.command_coding_approve_breakdown(self, raw_args)

    def command_coding_materialize(self, raw_args: str) -> str:
        return delivery_command_executor.command_coding_materialize(self, raw_args)

    @staticmethod
    def _format_decomposition_blocked_message(task_id: str, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts") or {}
        report = run_completion_presenter.load_report_from_artifacts(artifacts)
        summary = run_completion_presenter.completion_user_summary(report, artifacts, summary_limit=1200)
        next_actions = run_completion_presenter.completion_next_actions(report)
        if not next_actions:
            next_actions = ["补充缺失信息后，重新发送 /coding breakdown。"]
        return render_user_update(
            title="拆解未完成",
            task_id=task_id,
            user_facing_summary=summary or "本轮没有产出可确认的交付拆解方案。",
            next_actions=run_completion_presenter.dedupe_texts(next_actions),
            risk_note=run_completion_presenter.completion_risk_note(report),
        )

    @staticmethod
    def _decomposition_for_session(report: dict[str, Any]) -> dict[str, Any]:
        return DeliveryService.decomposition_for_session(report)

    @staticmethod
    def _breakdown_is_approved(task: dict[str, Any]) -> bool:
        return DeliveryService.breakdown_is_approved(task)

    def _materialize_execution_tasks(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        return delivery_command_executor.materialize_execution_tasks(self, task)

    def _next_runnable_child(self, parent_task: dict[str, Any]) -> dict[str, Any] | None:
        children = self.ledger.list_child_tasks(parent_task["task_id"])
        return self.delivery_service.next_runnable_child(parent_task, children)

    def _rollup_requirement_status(self, task_id: str) -> dict[str, Any]:
        parent = self.ledger.get_task(task_id)
        if not parent:
            raise KeyError(task_id)
        children = self.ledger.list_child_tasks(task_id)
        if not children:
            return self.delivery_service.rollup_requirement(parent, children)
        rollup = self.delivery_service.rollup_requirement(parent, children)
        target = TaskStatus(rollup["status"])
        self._transition_requirement_rollup_status(task_id, target)
        self.ledger.update_task_session(task_id, {"rollup": rollup})
        return rollup

    def _transition_requirement_rollup_status(self, task_id: str, target: TaskStatus) -> None:
        task = self.ledger.get_task(task_id) or {}
        current = str(task.get("status") or "")
        if target == TaskStatus.DONE and current not in {TaskStatus.DONE.value, TaskStatus.READY_FOR_MERGE_TEST.value}:
            if current == TaskStatus.FAILED.value:
                self._transition_task_status(
                    task_id,
                    TaskStatus.PLANNED,
                    phase=TaskPhase.PLAN_READY,
                    reason="requirement child rollup recovered from failed",
                )
            self._transition_task_status(
                task_id,
                TaskStatus.READY_FOR_MERGE_TEST,
                phase=TaskPhase.READY_TO_MERGE_TEST,
                reason="requirement child rollup ready before done",
            )
        self._transition_task_status(
            task_id,
            target,
            phase=self._phase_for_requirement_rollup(target),
            reason="requirement child rollup",
        )

    @staticmethod
    def _phase_for_requirement_rollup(status: TaskStatus) -> TaskPhase:
        return DeliveryService.phase_for_requirement_rollup(status)

    def _purge_task_artifacts(self, task: dict[str, Any]) -> list[str]:
        task_id = str(task["task_id"])
        candidates: list[Path] = [
            self.run_root / task_id,
            self.workspace_root / task_id,
        ]
        for run in task.get("agent_runs") or []:
            artifact = run.get("artifact") or {}
            run_dir = artifact.get("run_dir")
            workspace_path = run.get("workspace_path")
            if run_dir:
                candidates.append(Path(str(run_dir)))
            if workspace_path:
                candidates.append(Path(str(workspace_path)))
        cleaned: list[str] = []
        seen: set[Path] = set()
        for path in candidates:
            resolved = path.expanduser().resolve()
            if resolved in seen or not resolved.exists():
                continue
            seen.add(resolved)
            if not self._path_is_under(resolved, self.run_root) and not self._path_is_under(resolved, self.workspace_root):
                continue
            shutil.rmtree(resolved)
            cleaned.append(str(resolved))
        return cleaned

    @staticmethod
    def _path_is_under(path: Path, root: Path) -> bool:
        root_resolved = root.expanduser().resolve()
        return path == root_resolved or root_resolved in path.parents

    def command_coding_implement(self, raw_args: str) -> str:
        return coding_run_command_executor.command_coding_implement(self, raw_args)

    def command_coding_qa(self, raw_args: str) -> str:
        return coding_run_command_executor.command_coding_qa(self, raw_args)

    def command_prepare_merge_test(self, raw_args: str) -> str:
        return coding_merge_test_command_executor.command_prepare_merge_test(self, raw_args)

    def _status_update_for_prepare_merge_test(
        self,
        task: dict[str, Any],
        *,
        assessment: dict[str, Any] | None = None,
    ) -> TaskStatus | None:
        return coding_merge_test_command_executor.status_update_for_prepare_merge_test(
            self,
            task,
            assessment=assessment,
        )

    def command_coding_merge_test(self, raw_args: str) -> str:
        return coding_merge_test_command_executor.command_coding_merge_test(self, raw_args)

    def command_coding_complete(self, raw_args: str) -> str:
        return coding_task_control_command_executor.command_coding_complete(self, raw_args)
