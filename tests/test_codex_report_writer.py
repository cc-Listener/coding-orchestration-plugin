import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.runners.codex_report import REPORT_CONTRACT_FIELDS
from coding_orchestration.runners.codex_report_writer import CodexReportWriter


class CodexReportWriterTest(unittest.TestCase):
    def test_fallback_report_writes_strict_runner_failed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("free text output", encoding="utf-8")
            (run_dir / "stderr.log").write_text("warning output", encoding="utf-8")

            report = CodexReportWriter(runner_name="codex_cli").build_fallback_report(
                run_dir=run_dir,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(report["runner"], "codex_cli")
            self.assertEqual(report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(report["raw_status"], "runner_failed")
            self.assertEqual(report["failure_type"], "runner_failed")
            self.assertEqual(
                set(report["verification_limitations"][0]),
                {"reason", "impact", "recovery_action", "fallback_evidence"},
            )
            self.assertEqual(json.loads((run_dir / "report.json").read_text(encoding="utf-8")), report)

    def test_fallback_report_matches_report_contract_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")

            report = CodexReportWriter(runner_name="codex_cli").build_fallback_report(
                run_dir=run_dir,
                mode=RunMode.PLAN_ONLY,
                status="runner_failed",
            )

            self.assertEqual(list(report), list(REPORT_CONTRACT_FIELDS))
            saved = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(list(saved), list(REPORT_CONTRACT_FIELDS))

    def test_ensure_summary_builds_actionable_summary_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)

            CodexReportWriter(runner_name="codex_cli").ensure_summary(
                run_dir,
                {
                    "status": "blocked",
                    "summary_markdown": "",
                    "next_actions": ["Retry"],
                    "risks": ["Missing report"],
                },
            )

            summary = (run_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("Status: blocked", summary)
            self.assertIn("- Retry", summary)
            self.assertIn("- Missing report", summary)

    def test_ensure_report_contract_adds_limitation_for_blocked_without_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report = CodexReportWriter(runner_name="codex_cli").ensure_report_contract(
                run_dir,
                RunMode.IMPLEMENTATION,
                {
                    "runner": "codex_cli",
                    "status": "blocked",
                    "mode": "implementation",
                    "modified_files": [],
                    "test_commands": [],
                    "test_results": [],
                    "risks": [],
                    "human_required": True,
                    "next_actions": [],
                    "summary_markdown": "",
                    "verification_limitations": [],
                },
            )

            self.assertEqual(report["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(
                report["verification_limitations"][0]["reason"],
                "blocked_or_partial_without_details",
            )
            saved = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["verification_limitations"], report["verification_limitations"])


if __name__ == "__main__":
    unittest.main()
