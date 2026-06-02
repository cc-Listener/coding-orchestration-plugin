import unittest

from coding_orchestration.models import (
    AgentRunStatus,
    RunMode,
    TaskStatus,
    normalize_agent_run_status,
    task_status_display,
    task_status_label_zh,
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
            TaskStatus.QUEUED,
            reason="manual merge-test requested",
        )

        self.assertEqual(next_status, TaskStatus.QUEUED)

    def test_allows_blocked_task_to_be_released_with_known_gaps(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.BLOCKED,
            TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS,
            reason="manual blocked merge-test release",
        )

        self.assertEqual(next_status, TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS)

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

    def test_maps_runner_timeout_to_runner_failed_task(self):
        task_status = TaskStateMachine.task_status_for_run_status(
            AgentRunStatus.TIMEOUT,
        )

        self.assertEqual(task_status, TaskStatus.RUNNER_FAILED)

    def test_completed_unstructured_maps_to_ready_with_known_gaps(self):
        task_status = TaskStateMachine.task_status_for_run_status(
            AgentRunStatus.COMPLETED_UNSTRUCTURED,
        )

        self.assertEqual(task_status, TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS)

    def test_maps_runner_failed_to_runner_failed_task_status(self):
        task_status = TaskStateMachine.task_status_for_run_status("runner_failed")

        self.assertEqual(task_status, TaskStatus.RUNNER_FAILED)

    def test_maps_known_gaps_ready_status(self):
        task_status = TaskStateMachine.task_status_for_run_status("ready_for_merge_test_with_known_gaps")

        self.assertEqual(task_status, TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS)

    def test_source_deferred_is_not_blocked(self):
        task_status = TaskStateMachine.task_status_for_source_status("deferred")

        self.assertEqual(task_status, TaskStatus.SOURCE_DEFERRED)

    def test_auth_needed_is_not_blocked(self):
        task_status = TaskStateMachine.task_status_for_source_status("auth_needed")

        self.assertEqual(task_status, TaskStatus.SOURCE_AUTH_NEEDED)

    def test_permission_missing_is_not_blocked(self):
        task_status = TaskStateMachine.task_status_for_source_status("permission_missing")

        self.assertEqual(task_status, TaskStatus.SOURCE_PERMISSION_MISSING)

    def test_maps_ready_for_merge_test_status(self):
        task_status = TaskStateMachine.task_status_for_run_status("ready_for_merge_test")

        self.assertEqual(task_status, TaskStatus.READY_FOR_MERGE_TEST)

    def test_unknown_runner_status_maps_to_known_gaps_not_blocked(self):
        task_status = TaskStateMachine.task_status_for_run_status("ready_for_implementation")

        self.assertEqual(task_status, TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS)

    def test_normalizes_external_task_like_statuses_by_mode(self):
        self.assertEqual(
            normalize_agent_run_status("ready_for_implementation", RunMode.PLAN_ONLY),
            AgentRunStatus.SUCCESS.value,
        )
        self.assertEqual(
            normalize_agent_run_status("plan_ready", RunMode.PLAN_ONLY),
            AgentRunStatus.SUCCESS.value,
        )
        self.assertEqual(
            normalize_agent_run_status("merged_test", RunMode.MERGE_TEST),
            AgentRunStatus.SUCCESS.value,
        )
        self.assertEqual(
            normalize_agent_run_status("planned", RunMode.IMPLEMENTATION),
            AgentRunStatus.COMPLETED_UNSTRUCTURED.value,
        )

    def test_task_status_has_chinese_display_label(self):
        self.assertEqual(task_status_label_zh(TaskStatus.BLOCKED), "受阻")
        self.assertEqual(task_status_display("ready_for_merge_test"), "等待手动执行 merge test(ready_for_merge_test)")
        self.assertEqual(task_status_display("merged_test"), "已合并 test，待人工完成(merged_test)")

    def test_legacy_compat_task_statuses_are_removed(self):
        task_status_values = {status.value for status in TaskStatus}
        agent_status_values = {status.value for status in AgentRunStatus}

        for removed in {"implementation_complete", "verification_partial", "ready_for_review"}:
            self.assertNotIn(removed, task_status_values)
            self.assertNotIn(removed, agent_status_values)


if __name__ == "__main__":
    unittest.main()
