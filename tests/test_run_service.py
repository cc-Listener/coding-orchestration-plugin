import unittest

from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus
from coding_orchestration.services.run_service import RunService


class RunServiceTest(unittest.TestCase):
    def test_run_mode_user_labels_are_stable(self):
        self.assertEqual(RunService.run_mode_user_label(RunMode.PLAN_ONLY), "整理计划")
        self.assertEqual(RunService.run_mode_user_label(RunMode.IMPLEMENTATION), "实现")
        self.assertEqual(RunService.run_mode_user_label(RunMode.QA), "QA 验证")
        self.assertEqual(RunService.run_mode_user_label(RunMode.MERGE_TEST), "merge-test")

    def test_start_run_blocker_rejects_cancelled_and_active_tasks(self):
        service = RunService(
            cancelled_task_message=lambda task: f"cancelled:{task['task_id']}",
            active_run_message=lambda task, requested_mode=None: f"active:{requested_mode}",
        )

        self.assertEqual(
            service.start_run_blocker(
                {"task_id": "task_cancelled", "status": TaskStatus.CANCELLED.value},
                mode=RunMode.PLAN_ONLY,
            ),
            "cancelled:task_cancelled",
        )
        self.assertEqual(
            service.start_run_blocker(
                {
                    "task_id": "task_running",
                    "status": TaskStatus.RUNNING.value,
                    "task_session": {"runner": {"active_run_id": "run_1"}},
                },
                mode=RunMode.QA,
            ),
            "active:qa",
        )

    def test_start_run_blocker_uses_state_machine_for_invalid_transition(self):
        service = RunService(
            cannot_start_run_message=lambda task, mode, reason: f"{task['task_id']}:{mode.value}:{reason}",
        )

        blocked = service.start_run_blocker(
            {"task_id": "task_done", "status": TaskStatus.DONE.value},
            mode=RunMode.IMPLEMENTATION,
        )

        self.assertIn("task_done:implementation:", blocked)
        self.assertIn("invalid task transition done -> running", blocked)

    def test_implementation_requires_plan_ready(self):
        service = RunService()

        self.assertFalse(
            service.task_is_plan_ready_for_implementation(
                {"task_id": "task_new", "status": TaskStatus.NEW.value, "phase": TaskPhase.DRAFT.value}
            )
        )
        self.assertTrue(
            service.task_is_plan_ready_for_implementation(
                {"task_id": "task_plan", "phase": TaskPhase.PLAN_READY.value}
            )
        )
        self.assertTrue(
            service.task_is_plan_ready_for_implementation(
                {
                    "task_id": "task_history",
                    "phase": TaskPhase.DRAFT.value,
                    "agent_runs": [{"mode": RunMode.PLAN_ONLY.value, "status": AgentRunStatus.SUCCESS.value}],
                }
            )
        )

    def test_task_status_for_run_result_preserves_main_flow_mapping(self):
        service = RunService()

        self.assertEqual(
            service.task_status_for_run_result(RunMode.PLAN_ONLY, AgentRunStatus.SUCCESS.value),
            TaskStatus.PLANNED,
        )
        self.assertEqual(
            service.task_status_for_run_result(RunMode.IMPLEMENTATION, AgentRunStatus.SUCCESS.value),
            TaskStatus.READY_FOR_MERGE_TEST,
        )
        self.assertEqual(
            service.task_status_for_run_result(RunMode.MERGE_TEST, AgentRunStatus.SUCCESS.value),
            TaskStatus.MERGED_TEST,
        )
        self.assertEqual(
            service.task_status_for_run_result(
                RunMode.IMPLEMENTATION,
                AgentRunStatus.SUCCESS.value,
                details={"structured": False},
            ),
            TaskStatus.BLOCKED,
        )

    def test_task_phase_for_run_result_preserves_main_flow_mapping(self):
        service = RunService()

        self.assertEqual(
            service.task_phase_for_run_result(RunMode.PLAN_ONLY, AgentRunStatus.SUCCESS.value),
            TaskPhase.PLAN_READY,
        )
        self.assertEqual(
            service.task_phase_for_run_result(RunMode.QA, AgentRunStatus.SUCCESS.value),
            TaskPhase.READY_TO_MERGE_TEST,
        )
        self.assertEqual(
            service.task_phase_for_run_result(RunMode.MERGE_TEST, AgentRunStatus.SUCCESS.value),
            TaskPhase.MERGED_TEST,
        )
        self.assertEqual(
            service.task_phase_for_run_result(
                RunMode.IMPLEMENTATION,
                AgentRunStatus.FAILED.value,
                details={"status": AgentRunStatus.FAILED.value, "failure_type": "runner_failed"},
            ),
            TaskPhase.RUNNER_FAILED,
        )

    def test_timeout_seconds_for_mode_preserves_runtime_defaults_and_targeted_policy(self):
        service = RunService(
            default_timeout_seconds=3600,
            implementation_timeout_seconds=10800,
            qa_timeout_seconds=10800,
            merge_test_timeout_seconds=5400,
        )

        self.assertEqual(service.timeout_seconds_for_mode(RunMode.PLAN_ONLY), 3600)
        self.assertEqual(service.timeout_seconds_for_mode(RunMode.MERGE_TEST), 5400)
        self.assertEqual(service.timeout_seconds_for_mode(RunMode.IMPLEMENTATION), 10800)
        self.assertEqual(
            service.timeout_seconds_for_mode(
                RunMode.IMPLEMENTATION,
                execution_policy={"route": "fast_fix", "max_duration_seconds": 1200},
            ),
            1200,
        )
        self.assertEqual(
            service.timeout_seconds_for_mode(
                RunMode.QA,
                execution_policy={"verification": "full", "max_duration_seconds": 1200},
            ),
            10800,
        )
        self.assertEqual(service.timeout_seconds_for_mode(RunMode.QA, override=99), 99)

    def test_running_phase_for_mode_preserves_orchestrator_phase_mapping(self):
        service = RunService()

        self.assertEqual(service.running_phase_for_mode(RunMode.DECOMPOSITION), TaskPhase.PLANNING)
        self.assertEqual(service.running_phase_for_mode(RunMode.PLAN_ONLY), TaskPhase.PLANNING)
        self.assertEqual(service.running_phase_for_mode(RunMode.IMPLEMENTATION), TaskPhase.IMPLEMENTING)
        self.assertEqual(service.running_phase_for_mode(RunMode.QA), TaskPhase.QA_VERIFYING)
        self.assertEqual(service.running_phase_for_mode(RunMode.MERGE_TEST), TaskPhase.READY_TO_MERGE_TEST)


if __name__ == "__main__":
    unittest.main()
