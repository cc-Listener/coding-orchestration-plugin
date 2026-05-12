import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.runners.codex_cli import CodexCliRunner


class CodexCliRunnerTest(unittest.TestCase):
    def test_plan_only_command_uses_read_only_sandbox_and_stdin_prompt(self):
        runner = CodexCliRunner(command="codex")
        command = runner.build_command(
            run_dir=Path("/tmp/run"),
            project_path=Path("/repo/project"),
            workspace_path=None,
            mode=RunMode.PLAN_ONLY,
        )

        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertIn("--json", command)
        self.assertIn("--output-schema", command)
        self.assertIn("--output-last-message", command)
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        self.assertIn("--ask-for-approval", command)
        self.assertIn("never", command)
        self.assertIn("-C", command)
        self.assertIn("/repo/project", command)
        self.assertEqual(command[-1], "-")

    def test_implementation_command_uses_workspace_write_and_workspace_path(self):
        runner = CodexCliRunner(command="codex")
        command = runner.build_command(
            run_dir=Path("/tmp/run"),
            project_path=Path("/repo/project"),
            workspace_path=Path("/tmp/workspace"),
            mode=RunMode.IMPLEMENTATION,
        )

        self.assertIn("workspace-write", command)
        self.assertIn("/tmp/workspace", command)
        self.assertNotIn("/repo/project", command[command.index("-C") + 1])

    def test_fallback_report_is_completed_unstructured(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("free text output", encoding="utf-8")
            (run_dir / "stderr.log").write_text("warning output", encoding="utf-8")
            (run_dir / "summary.md").write_text("summary", encoding="utf-8")

            report = CodexCliRunner(command="codex").build_fallback_report(
                run_dir=run_dir,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(
                report["status"],
                AgentRunStatus.COMPLETED_UNSTRUCTURED.value,
            )
            self.assertEqual(report["raw_stdout_ref"], str(run_dir / "stdout.log"))
            self.assertEqual(report["summary_ref"], str(run_dir / "summary.md"))

            saved = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, report)


if __name__ == "__main__":
    unittest.main()
