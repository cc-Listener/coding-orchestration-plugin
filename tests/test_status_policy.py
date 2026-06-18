import unittest

from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.status_policy import (
    normalize_implementation_run_status,
    run_details_are_runner_failed,
    run_details_require_verification_limitations,
    run_status_details_from_report,
    status_requires_verification_limitations,
)


class StatusPolicyTest(unittest.TestCase):
    def test_report_details_preserve_known_gaps_and_structured_flags(self):
        details = run_status_details_from_report(
            {
                "status": AgentRunStatus.SUCCEEDED.value,
                "status_detail": "",
                "known_gaps": True,
                "structured": True,
            },
            RunMode.IMPLEMENTATION,
        )

        self.assertEqual(details["status"], AgentRunStatus.SUCCEEDED.value)
        self.assertTrue(details["known_gaps"])
        self.assertEqual(details["status_detail"], "ready_for_merge_test_with_known_gaps")

    def test_report_details_apply_failure_type_without_losing_raw_status(self):
        details = run_status_details_from_report(
            {
                "status": AgentRunStatus.SUCCEEDED.value,
                "raw_status": "success",
                "failure_type": "report_incomplete",
            },
            RunMode.IMPLEMENTATION,
        )

        self.assertEqual(details["status"], AgentRunStatus.BLOCKED.value)
        self.assertEqual(details["raw_status"], "success")
        self.assertEqual(details["failure_type"], "report_incomplete")

    def test_implementation_success_requires_landed_commit(self):
        for report in (
            {
                "status": AgentRunStatus.SUCCEEDED.value,
                "mode": RunMode.IMPLEMENTATION.value,
                "implementation_landed": False,
                "commit_sha": "abc123",
            },
            {
                "status": AgentRunStatus.SUCCEEDED.value,
                "mode": RunMode.IMPLEMENTATION.value,
                "implementation_landed": True,
                "commit_sha": "",
            },
        ):
            with self.subTest(report=report):
                details = normalize_implementation_run_status(report, RunMode.IMPLEMENTATION)

                self.assertEqual(details["status"], AgentRunStatus.BLOCKED.value)
                self.assertEqual(details["failure_type"], "implementation_not_landed")
                self.assertEqual(details["status_detail"], "implementation_not_landed")

    def test_control_failures_are_not_overwritten_by_landed_commit_gate(self):
        for report, expected_status, expected_detail in (
            ({"status": "timeout", "mode": RunMode.IMPLEMENTATION.value}, AgentRunStatus.FAILED.value, "timeout"),
            (
                {"status": "runner_failed", "mode": RunMode.IMPLEMENTATION.value},
                AgentRunStatus.FAILED.value,
                "runner_failed",
            ),
            ({"status": "blocked", "mode": RunMode.IMPLEMENTATION.value}, AgentRunStatus.BLOCKED.value, ""),
        ):
            with self.subTest(report=report):
                details = normalize_implementation_run_status(report, RunMode.IMPLEMENTATION)

                self.assertEqual(details["status"], expected_status)
                self.assertNotEqual(details["status_detail"], "implementation_not_landed")
                self.assertEqual(details["status_detail"] or details["failure_type"], expected_detail)

    def test_blocked_implementation_respects_explicit_not_landed_report(self):
        details = normalize_implementation_run_status(
            {
                "status": AgentRunStatus.BLOCKED.value,
                "mode": RunMode.IMPLEMENTATION.value,
                "implementation_landed": False,
                "commit_sha": "abc123",
            },
            RunMode.IMPLEMENTATION,
        )

        self.assertEqual(details["status"], AgentRunStatus.BLOCKED.value)
        self.assertEqual(details["failure_type"], "implementation_not_landed")
        self.assertEqual(details["status_detail"], "implementation_not_landed")

    def test_non_implementation_status_does_not_require_landed_commit_fields(self):
        details = normalize_implementation_run_status(
            {
                "status": AgentRunStatus.SUCCEEDED.value,
                "mode": RunMode.QA.value,
                "implementation_landed": False,
                "commit_sha": "",
            },
            RunMode.QA,
        )

        self.assertEqual(details["status"], AgentRunStatus.SUCCEEDED.value)
        self.assertNotEqual(details["failure_type"], "implementation_not_landed")

    def test_unstructured_non_merge_test_status_becomes_blocked(self):
        details = normalize_implementation_run_status(
            {
                "raw_status": "ready_for_implementation",
                "structured": False,
            },
            RunMode.IMPLEMENTATION,
        )

        self.assertEqual(details["status"], AgentRunStatus.BLOCKED.value)
        self.assertEqual(details["raw_status"], "ready_for_implementation")
        self.assertEqual(details["status_detail"], "completed_unstructured")
        self.assertFalse(details["structured"])

    def test_verification_limitations_are_required_for_partial_or_failed_details(self):
        self.assertTrue(status_requires_verification_limitations("blocked"))
        self.assertTrue(status_requires_verification_limitations("ready_for_merge_test_with_known_gaps"))
        self.assertTrue(
            run_details_require_verification_limitations(
                {"status": AgentRunStatus.SUCCEEDED.value, "structured": False}
            )
        )
        self.assertFalse(
            run_details_require_verification_limitations(
                {
                    "status": AgentRunStatus.SUCCEEDED.value,
                    "structured": True,
                    "known_gaps": False,
                    "failure_type": "",
                    "status_detail": "",
                }
            )
        )

    def test_runner_failed_detection_uses_failure_type_or_raw_status(self):
        self.assertTrue(run_details_are_runner_failed({"failure_type": "runner_failed"}))
        self.assertTrue(run_details_are_runner_failed({"raw_status": "runner_failed"}))
        self.assertFalse(run_details_are_runner_failed({"failure_type": "timeout"}))


if __name__ == "__main__":
    unittest.main()
