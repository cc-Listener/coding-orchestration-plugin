import unittest

from coding_orchestration.models import AgentRunStatus, TaskStatus
from coding_orchestration.state_machine import InvalidTransition, TaskStateMachine


class TaskStateMachineTest(unittest.TestCase):
    def test_allows_review_rejection_to_return_to_planned(self):
        next_status = TaskStateMachine.transition(
            TaskStatus.READY_FOR_REVIEW,
            TaskStatus.PLANNED,
            reason="review rejected",
        )

        self.assertEqual(next_status, TaskStatus.PLANNED)

    def test_rejects_running_directly_to_done(self):
        with self.assertRaises(InvalidTransition):
            TaskStateMachine.transition(
                TaskStatus.RUNNING,
                TaskStatus.DONE,
                reason="skip review",
            )

    def test_maps_runner_timeout_to_failed_task(self):
        task_status = TaskStateMachine.task_status_for_run_status(
            AgentRunStatus.TIMEOUT,
        )

        self.assertEqual(task_status, TaskStatus.FAILED)

    def test_completed_unstructured_blocks_for_human_review(self):
        task_status = TaskStateMachine.task_status_for_run_status(
            AgentRunStatus.COMPLETED_UNSTRUCTURED,
        )

        self.assertEqual(task_status, TaskStatus.BLOCKED)


if __name__ == "__main__":
    unittest.main()
