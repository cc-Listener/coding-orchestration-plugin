import unittest

from coding_orchestration import run_orchestration_service
from coding_orchestration.models import RunMode


class RunOrchestrationReconcileRulesTest(unittest.TestCase):
    def test_run_mode_for_existing_run_prefers_report_then_run_then_runner_session(self):
        task = {
            "task_session": {
                "runner": {
                    "active_mode": RunMode.IMPLEMENTATION.value,
                    "last_requested_mode": RunMode.PLAN_ONLY.value,
                }
            }
        }

        self.assertEqual(
            run_orchestration_service.run_mode_for_existing_run(
                task,
                {"mode": RunMode.QA.value},
                {"mode": RunMode.MERGE_TEST.value},
            ),
            RunMode.MERGE_TEST,
        )
        self.assertEqual(
            run_orchestration_service.run_mode_for_existing_run(task, {"mode": RunMode.QA.value}, {}),
            RunMode.QA,
        )
        self.assertEqual(
            run_orchestration_service.run_mode_for_existing_run(task, {"mode": "invalid"}, {}),
            RunMode.IMPLEMENTATION,
        )
        self.assertEqual(
            run_orchestration_service.run_mode_for_existing_run({}, {"mode": "invalid"}, {"mode": "invalid"}),
            RunMode.PLAN_ONLY,
        )

    def test_changed_files_for_existing_run_prefers_report_and_falls_back_to_diff_guard(self):
        self.assertEqual(
            run_orchestration_service.changed_files_for_existing_run(
                {"diff_guard": {"changed_files": ["fallback.py"]}},
                {"modified_files": ["src/app.py", "", "  "]},
            ),
            ["src/app.py"],
        )
        self.assertEqual(
            run_orchestration_service.changed_files_for_existing_run(
                {"diff_guard": {"changed_files": ["src/fallback.py", None]}},
                {"modified_files": "not-a-list"},
            ),
            ["src/fallback.py", "None"],
        )
        self.assertEqual(
            run_orchestration_service.changed_files_for_existing_run({}, {}),
            [],
        )


if __name__ == "__main__":
    unittest.main()
