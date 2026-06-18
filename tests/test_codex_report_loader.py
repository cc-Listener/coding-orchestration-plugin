import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import RunMode
from coding_orchestration.runners.codex_report_loader import (
    CodexReportLoader,
    report_has_required_fields,
)


class RecordingReportCallbacks:
    def __init__(self):
        self.incomplete_missing = None
        self.admission_rejection = None
        self.fallback_kwargs = None
        self.summary_report = None
        self.ensure_report_input = None

    def build_report_incomplete_report(self, run_dir, mode, missing):
        self.incomplete_missing = list(missing)
        return {"status": "blocked", "failure_type": "report_incomplete", "missing": list(missing)}

    def ensure_report_contract(self, run_dir, mode, report):
        self.ensure_report_input = dict(report)
        ensured = dict(report)
        ensured["ensured"] = True
        return ensured

    def build_report_admission_rejected_report(self, run_dir, mode, reason, errors):
        self.admission_rejection = (reason, list(errors))
        return {"status": "blocked", "failure_type": "report_admission_rejected", "reason": reason}

    def ensure_summary(self, run_dir, report):
        self.summary_report = dict(report)

    def build_fallback_report(self, **kwargs):
        self.fallback_kwargs = dict(kwargs)
        return {"status": kwargs["status"], "limitation_reason": kwargs["limitation_reason"]}


class CodexReportLoaderTest(unittest.TestCase):
    def test_report_has_required_fields_matches_runner_schema_gate(self):
        self.assertFalse(report_has_required_fields({"runner": "codex_cli"}))
        self.assertTrue(
            report_has_required_fields(
                {
                    "runner": "codex_cli",
                    "status": "success",
                    "mode": "plan-only",
                    "summary_markdown": "done",
                    "modified_files": [],
                    "test_commands": [],
                    "test_results": [],
                    "risks": [],
                    "human_required": False,
                    "next_actions": [],
                    "verification_limitations": [],
                }
            )
        )

    def test_valid_report_is_ensured_admitted_and_summarized(self):
        callbacks = RecordingReportCallbacks()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report = {
                "runner": "codex_cli",
                "status": "success",
                "mode": "plan-only",
                "summary_markdown": "plan",
                "modified_files": [],
                "test_commands": [],
                "test_results": [],
                "risks": [],
                "verification_limitations": [],
                "human_required": False,
                "next_actions": ["Review plan"],
                "user_facing_summary": "Plan ready.",
                "technical_summary": "Plan details.",
                "execution_policy_decision": {"route": "standard_change"},
                "branch_slug_candidate": "status-filter",
            }
            (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")

            loaded = CodexReportLoader(callbacks).load_or_build(run_dir, RunMode.PLAN_ONLY)

            self.assertTrue(loaded["ensured"])
            self.assertEqual(callbacks.ensure_report_input["summary_markdown"], "plan")
            self.assertEqual(callbacks.summary_report["summary_markdown"], "plan")
            self.assertIsNone(callbacks.incomplete_missing)
            self.assertIsNone(callbacks.fallback_kwargs)

    def test_missing_semantic_fields_builds_incomplete_report(self):
        callbacks = RecordingReportCallbacks()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report = {
                "runner": "codex_cli",
                "status": "success",
                "mode": "implementation",
                "summary_markdown": "done",
                "modified_files": [],
                "test_commands": [],
                "test_results": [],
                "risks": [],
                "verification_limitations": [],
                "human_required": False,
                "next_actions": [],
            }
            (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")

            loaded = CodexReportLoader(callbacks).load_or_build(run_dir, RunMode.IMPLEMENTATION)

            self.assertEqual(loaded["failure_type"], "report_incomplete")
            self.assertIn("user_facing_summary", callbacks.incomplete_missing)
            self.assertIn("implementation_landed", callbacks.incomplete_missing)
            self.assertIsNone(callbacks.summary_report)

    def test_invalid_schema_stdout_builds_runner_failed_fallback(self):
        callbacks = RecordingReportCallbacks()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "report.json").write_text("", encoding="utf-8")
            (run_dir / "stdout.log").write_text(
                '{"type":"error","message":"Invalid schema for response_format code=invalid_json_schema"}',
                encoding="utf-8",
            )
            (run_dir / "stderr.log").write_text("", encoding="utf-8")

            loaded = CodexReportLoader(callbacks).load_or_build(run_dir, RunMode.PLAN_ONLY)

            self.assertEqual(loaded["status"], "runner_failed")
            self.assertEqual(callbacks.fallback_kwargs["limitation_reason"], "codex_invalid_output_schema")


if __name__ == "__main__":
    unittest.main()
