import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.runners.codex_report import (
    fallback_limitation_reason,
    report_contract_fields,
    report_status_details,
    runner_failure_from_stdout,
    semantic_report_fields,
    thread_id_from_stdout,
    verification_limitation,
)


class CodexReportPolicyTest(unittest.TestCase):
    def test_report_status_details_keeps_report_incomplete_blocked(self):
        details = report_status_details(
            {
                "status": AgentRunStatus.BLOCKED.value,
                "mode": RunMode.IMPLEMENTATION.value,
                "failure_type": "report_incomplete",
            },
            RunMode.IMPLEMENTATION,
        )

        self.assertEqual(details["status"], AgentRunStatus.BLOCKED.value)
        self.assertEqual(details["failure_type"], "report_incomplete")

    def test_semantic_report_fields_normalizes_missing_or_wrong_types(self):
        fields = semantic_report_fields(
            {
                "user_facing_summary": None,
                "technical_summary": 42,
                "implementation_landed": "yes",
                "commit_sha": 123,
                "changed_files_summary": "src/app.py",
                "execution_policy_decision": [],
                "merge_readiness": [],
                "delivery_units": {},
                "materialization_allowed": "non-empty",
            }
        )

        self.assertEqual(fields["user_facing_summary"], "")
        self.assertEqual(fields["technical_summary"], "42")
        self.assertFalse(fields["implementation_landed"])
        self.assertEqual(fields["commit_sha"], "123")
        self.assertEqual(fields["changed_files_summary"], [])
        self.assertEqual(fields["execution_policy_decision"], {})
        self.assertEqual(fields["merge_readiness"], {})
        self.assertEqual(fields["delivery_units"], [])
        self.assertTrue(fields["materialization_allowed"])

    def test_report_contract_fields_preserves_strict_order_and_known_keys_only(self):
        fields = report_contract_fields(
            {
                "mode": "plan-only",
                "runner": "codex_cli",
                "status": "succeeded",
                "unexpected": "ignored",
                "summary_markdown": "done",
            }
        )

        self.assertEqual(list(fields), ["runner", "status", "mode", "summary_markdown"])
        self.assertNotIn("unexpected", fields)

    def test_fallback_limitation_reason_uses_runner_status(self):
        self.assertEqual(fallback_limitation_reason("timeout"), "runner_timeout")
        self.assertEqual(fallback_limitation_reason("runner_failed"), "runner_failed")
        self.assertEqual(fallback_limitation_reason("unknown"), "structured_report_missing")

    def test_verification_limitation_shape_is_stable(self):
        limitation = verification_limitation(
            reason="blocked",
            impact="cannot trust run",
            recovery_action="rerun",
            fallback_evidence="stdout.log",
        )

        self.assertEqual(
            limitation,
            {
                "reason": "blocked",
                "impact": "cannot trust run",
                "recovery_action": "rerun",
                "fallback_evidence": "stdout.log",
            },
        )

    def test_runner_failure_from_stdout_detects_invalid_output_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout_path = Path(tmp) / "stdout.log"
            stdout_path.write_text(
                "\n".join(
                    [
                        '{"type":"thread.started","thread_id":"thread_1"}',
                        '{"type":"error","message":"Invalid schema for response_format '
                        "'codex_output_schema'. code=invalid_json_schema\"}",
                    ]
                ),
                encoding="utf-8",
            )

            failure = runner_failure_from_stdout(stdout_path)

            self.assertIsNotNone(failure)
            self.assertEqual(failure["reason"], "codex_invalid_output_schema")
            self.assertEqual(failure["fallback_evidence"], str(stdout_path))

    def test_thread_id_from_stdout_reads_json_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout_path = Path(tmp) / "stdout.log"
            stdout_path.write_text(
                "\n".join(
                    [
                        "not json",
                        json.dumps({"type": "thread.started", "thread_id": "thread_123"}),
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(thread_id_from_stdout(stdout_path), "thread_123")


if __name__ == "__main__":
    unittest.main()
