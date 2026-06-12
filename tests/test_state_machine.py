import unittest

from coding_orchestration.models import (
    AgentRunStatus,
    RunMode,
    TaskStatus,
    agent_run_status_details,
    apply_failure_type_to_run_details,
    normalize_agent_run_status,
    task_status_display,
    task_status_label_zh,
    task_status_view,
)
from coding_orchestration.state_machine import InvalidTransition, TaskStateMachine


class TaskStateMachineTest(unittest.TestCase):
    def test_allows_review_rejection_to_return_to_planned(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.READY_FOR_MERGE_TEST,
            TaskStatus.PLANNED,
            reason="review rejected",
        )

        self.assertEqual(next_status, TaskStatus.PLANNED)

    def test_rejects_planned_directly_to_done(self):
        with self.assertRaises(InvalidTransition):
            TaskStateMachine.transition(
                TaskStatus.PLANNED,
                TaskStatus.DONE,
                reason="skip implementation and merge-test",
            )

    def test_allows_ready_task_to_enter_manual_merge_test_run(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.READY_FOR_MERGE_TEST,
            TaskStatus.RUNNING,
            reason="manual merge-test requested",
        )

        self.assertEqual(next_status, TaskStatus.RUNNING)

    def test_allows_running_plan_only_to_return_to_planned(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.RUNNING,
            TaskStatus.PLANNED,
            reason="plan-only completed",
        )

        self.assertEqual(next_status, TaskStatus.PLANNED)

    def test_allows_pre_run_startup_failure_to_failed_with_runner_detail(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.PLANNED,
            TaskStatus.FAILED,
            reason="runner failed before process start",
        )

        self.assertEqual(next_status, TaskStatus.FAILED)

    def test_allows_ready_task_to_be_blocked_by_missing_merge_workspace(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.READY_FOR_MERGE_TEST,
            TaskStatus.BLOCKED,
            reason="missing merge workspace",
        )

        self.assertEqual(next_status, TaskStatus.BLOCKED)

    def test_allows_failed_task_to_retry_queue(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.FAILED,
            TaskStatus.RUNNING,
            reason="manual retry",
        )

        self.assertEqual(next_status, TaskStatus.RUNNING)

    def test_allows_restore_cancelled_task_to_latest_actionable_state(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.CANCELLED,
            TaskStatus.READY_FOR_MERGE_TEST,
            reason="restore latest actionable state",
        )

        self.assertEqual(next_status, TaskStatus.READY_FOR_MERGE_TEST)

    def test_allows_blocked_task_to_be_released_with_known_gaps(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.BLOCKED,
            TaskStatus.READY_FOR_MERGE_TEST,
            reason="manual blocked merge-test release",
        )

        self.assertEqual(next_status, TaskStatus.READY_FOR_MERGE_TEST)

    def test_allows_running_merge_test_to_enter_merged_test(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.RUNNING,
            TaskStatus.MERGED_TEST,
            reason="merge-test completed",
        )

        self.assertEqual(next_status, TaskStatus.MERGED_TEST)

    def test_allows_merged_test_to_done_by_manual_completion(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.MERGED_TEST,
            TaskStatus.DONE,
            reason="manual completion",
        )

        self.assertEqual(next_status, TaskStatus.DONE)

    def test_maps_runner_timeout_to_failed_task(self):
        task_status = TaskStateMachine.task_status_for_run_status("timeout")

        self.assertEqual(task_status, TaskStatus.FAILED)

    def test_completed_unstructured_maps_to_ready_for_merge_test(self):
        task_status = TaskStateMachine.task_status_for_run_status("completed_unstructured")

        self.assertEqual(task_status, TaskStatus.READY_FOR_MERGE_TEST)

    def test_maps_runner_failed_to_failed_task_status(self):
        task_status = TaskStateMachine.task_status_for_run_status("runner_failed")

        self.assertEqual(task_status, TaskStatus.FAILED)

    def test_maps_known_gaps_ready_status(self):
        task_status = TaskStateMachine.task_status_for_run_status("ready_for_merge_test_with_known_gaps")

        self.assertEqual(task_status, TaskStatus.READY_FOR_MERGE_TEST)

    def test_source_deferred_is_not_blocked(self):
        task_status = TaskStateMachine.task_status_for_source_status("deferred")

        self.assertEqual(task_status, TaskStatus.NEEDS_HUMAN)

    def test_auth_needed_is_not_blocked(self):
        task_status = TaskStateMachine.task_status_for_source_status("auth_needed")

        self.assertEqual(task_status, TaskStatus.NEEDS_HUMAN)

    def test_permission_missing_is_not_blocked(self):
        task_status = TaskStateMachine.task_status_for_source_status("permission_missing")

        self.assertEqual(task_status, TaskStatus.NEEDS_HUMAN)

    def test_maps_ready_for_merge_test_status(self):
        task_status = TaskStateMachine.task_status_for_run_status("ready_for_merge_test")

        self.assertEqual(task_status, TaskStatus.READY_FOR_MERGE_TEST)

    def test_unknown_runner_status_maps_to_known_gaps_not_blocked(self):
        task_status = TaskStateMachine.task_status_for_run_status("ready_for_implementation")

        self.assertEqual(task_status, TaskStatus.READY_FOR_MERGE_TEST)

    def test_task_status_enum_contains_only_public_main_statuses(self):
        self.assertEqual(
            [status.value for status in TaskStatus],
            [
                "new",
                "needs_human",
                "planned",
                "running",
                "blocked",
                "ready_for_merge_test",
                "merged_test",
                "failed",
                "done",
                "cancelled",
            ],
        )

    def test_task_status_view_returns_only_public_main_status_fields(self):
        view = task_status_view(TaskStatus.FAILED)

        self.assertEqual(view["status"], TaskStatus.FAILED.value)
        self.assertEqual(view["status_label_zh"], "失败")
        self.assertEqual(view["status_display"], "失败(failed)")
        self.assertNotIn("machine_status", view)
        self.assertNotIn("machine_status_label_zh", view)
        self.assertNotIn("machine_status_display", view)

    def test_normalizes_external_task_like_statuses_by_mode(self):
        self.assertEqual(
            normalize_agent_run_status("ready_for_implementation", RunMode.PLAN_ONLY),
            AgentRunStatus.SUCCEEDED.value,
        )
        self.assertEqual(
            normalize_agent_run_status("plan_ready", RunMode.PLAN_ONLY),
            AgentRunStatus.SUCCEEDED.value,
        )
        self.assertEqual(
            normalize_agent_run_status("merged_test", RunMode.MERGE_TEST),
            AgentRunStatus.SUCCEEDED.value,
        )
        self.assertEqual(
            normalize_agent_run_status("planned", RunMode.IMPLEMENTATION),
            AgentRunStatus.SUCCEEDED.value,
        )

    def test_agent_run_status_enum_contains_only_public_main_statuses(self):
        self.assertEqual(
            [status.value for status in AgentRunStatus],
            ["running", "succeeded", "blocked", "failed", "cancelled"],
        )

    def test_agent_run_detail_maps_legacy_statuses_to_public_main_statuses(self):
        cases = [
            ("queued", AgentRunStatus.RUNNING.value, {"status_detail": "queued"}),
            ("success", AgentRunStatus.SUCCEEDED.value, {"raw_status": "success"}),
            ("ready_for_merge_test", AgentRunStatus.SUCCEEDED.value, {"status_detail": "ready_for_merge_test"}),
            (
                "ready_for_merge_test_with_known_gaps",
                AgentRunStatus.SUCCEEDED.value,
                {"status_detail": "ready_for_merge_test_with_known_gaps", "known_gaps": True},
            ),
            (
                "completed_unstructured",
                AgentRunStatus.SUCCEEDED.value,
                {"status_detail": "completed_unstructured", "structured": False},
            ),
            ("timeout", AgentRunStatus.FAILED.value, {"failure_type": "timeout"}),
            ("runner_failed", AgentRunStatus.FAILED.value, {"failure_type": "runner_failed"}),
            ("orphaned", AgentRunStatus.FAILED.value, {"failure_type": "orphaned"}),
        ]
        for raw_status, expected_status, expected_fields in cases:
            with self.subTest(raw_status=raw_status):
                detail = agent_run_status_details(raw_status)
                self.assertEqual(detail["status"], expected_status)
                self.assertEqual(detail["raw_status"], raw_status)
                for key, value in expected_fields.items():
                    self.assertEqual(detail[key], value)

    def test_failure_type_only_forces_failed_for_runner_failures(self):
        blocked = apply_failure_type_to_run_details(
            agent_run_status_details(AgentRunStatus.BLOCKED.value),
            "report_incomplete",
        )
        succeeded = apply_failure_type_to_run_details(
            agent_run_status_details(AgentRunStatus.SUCCEEDED.value),
            "report_incomplete",
        )
        timeout = apply_failure_type_to_run_details(
            agent_run_status_details(AgentRunStatus.BLOCKED.value),
            "timeout",
        )
        empty = apply_failure_type_to_run_details(
            agent_run_status_details(AgentRunStatus.SUCCEEDED.value),
            "",
        )

        self.assertEqual(blocked["status"], AgentRunStatus.BLOCKED.value)
        self.assertEqual(succeeded["status"], AgentRunStatus.BLOCKED.value)
        self.assertEqual(timeout["status"], AgentRunStatus.FAILED.value)
        self.assertEqual(empty["status"], AgentRunStatus.SUCCEEDED.value)

    def test_task_status_has_chinese_display_label(self):
        self.assertEqual(task_status_label_zh(TaskStatus.BLOCKED), "受阻")
        self.assertEqual(task_status_display("queued"), "未知(queued)")
        self.assertEqual(task_status_display("ready_for_merge_test"), "等待手动执行 merge test(ready_for_merge_test)")
        self.assertEqual(task_status_display("merged_test"), "已合并 test，待人工完成(merged_test)")

    def test_every_task_status_has_user_facing_chinese_display(self):
        for status in TaskStatus:
            with self.subTest(status=status.value):
                self.assertNotEqual(task_status_label_zh(status), "未知")
                self.assertEqual(task_status_display(status), f"{task_status_label_zh(status)}({status.value})")

    def test_legacy_compat_task_statuses_are_removed(self):
        task_status_values = {status.value for status in TaskStatus}
        agent_status_values = {status.value for status in AgentRunStatus}

        for removed in {
            "implementation_complete",
            "verification_partial",
            "ready_for_review",
            "source_deferred",
            "source_auth_needed",
            "source_permission_missing",
            "queued",
            "runner_failed",
            "ready_for_merge_test_with_known_gaps",
        }:
            self.assertNotIn(removed, task_status_values)
        for removed in {
            "implementation_complete",
            "verification_partial",
            "ready_for_review",
            "queued",
            "success",
            "timeout",
            "orphaned",
            "completed_unstructured",
            "ready_for_merge_test",
            "ready_for_merge_test_with_known_gaps",
            "runner_failed",
        }:
            self.assertNotIn(removed, agent_status_values)


if __name__ == "__main__":
    unittest.main()
