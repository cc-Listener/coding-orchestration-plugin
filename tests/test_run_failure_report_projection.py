import unittest

from coding_orchestration import run_orchestration_service
from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.run_failure_report_projection import (
    RunFailureReportProjection,
    build_checkpoint_failed_report_payload,
    build_runner_failed_report_payload,
)


class RunFailureReportProjectionTest(unittest.TestCase):
    def test_runner_failed_projection_lives_in_dedicated_module_with_compatibility_export(self):
        failure = build_runner_failed_report_payload(
            runner_name="codex_cli",
            mode=RunMode.IMPLEMENTATION,
            error=RuntimeError("boom"),
            stdout_path="/tmp/stdout.log",
            stderr_path="/tmp/stderr.log",
            summary_path="/tmp/summary.md",
        )

        self.assertIsInstance(failure, RunFailureReportProjection)
        self.assertIs(run_orchestration_service.build_runner_failed_report_payload, build_runner_failed_report_payload)
        self.assertEqual(failure.status, AgentRunStatus.RUNNER_FAILED.value)
        self.assertEqual(failure.report["qa_artifacts"], {"report": "", "baseline": "", "screenshots_dir": ""})
        self.assertEqual(failure.report["tested_commit"], "")

    def test_checkpoint_failed_projection_lives_in_dedicated_module_with_compatibility_export(self):
        failure = build_checkpoint_failed_report_payload(
            runner_name="codex_cli",
            mode=RunMode.MERGE_TEST,
            checkpoint={"reason": "implementation_commit_missing", "error": "dirty tree"},
            stderr_path="/tmp/stderr.log",
        )

        self.assertIsInstance(failure, RunFailureReportProjection)
        self.assertIs(
            run_orchestration_service.build_checkpoint_failed_report_payload,
            build_checkpoint_failed_report_payload,
        )
        self.assertEqual(failure.status, AgentRunStatus.BLOCKED.value)
        self.assertIn("merge-test 未启动", failure.summary)
        self.assertEqual(failure.report["verification_limitations"][0]["fallback_evidence"], "/tmp/stderr.log")


if __name__ == "__main__":
    unittest.main()
