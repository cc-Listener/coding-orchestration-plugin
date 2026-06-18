import json
import sys
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.runners.base import RunResult
from coding_orchestration.runners.codex_cli import CodexCliRunner
from coding_orchestration.runners.hermes_autonomous_codex import HermesAutonomousCodexRunner


class CodexCliProcessFacadeTest(unittest.TestCase):
    def test_hermes_autonomous_codex_runner_writes_backend_metadata(self):
        class RecordingRunner(HermesAutonomousCodexRunner):
            def run_subprocess(self, **kwargs):
                artifacts = self.collect_artifacts(kwargs["run_dir"])
                report = {
                    "runner": self.name,
                    "status": AgentRunStatus.SUCCESS.value,
                    "mode": kwargs["mode"].value,
                    "summary_markdown": "done",
                    "modified_files": [],
                    "test_commands": [],
                    "test_results": [],
                    "risks": [],
                    "verification_limitations": [],
                    "human_required": False,
                    "next_actions": [],
                    "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
                    "tested_commit": "",
                }
                return RunResult(AgentRunStatus.SUCCESS.value, 0, artifacts, report)

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "input-prompt.md").write_text("prompt", encoding="utf-8")
            runner = RecordingRunner(command="codex", skill_path="/skills/autonomous-ai-agents/codex/SKILL.md")

            result = runner.run(
                run_id="run_1",
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.IMPLEMENTATION,
                timeout_seconds=5,
            )

            metadata = json.loads((run_dir / "autonomous-codex-backend.json").read_text(encoding="utf-8"))
            self.assertEqual(result.status, AgentRunStatus.SUCCESS.value)
            self.assertEqual(metadata["runner"], "hermes_autonomous_codex")
            self.assertEqual(metadata["hermes_skill"], "autonomous-ai-agents/codex")
            self.assertEqual(metadata["skill_path"], "/skills/autonomous-ai-agents/codex/SKILL.md")

    def test_resume_implementation_subprocess_runs_from_workspace_path(self):
        class RecordingRunner(CodexCliRunner):
            def __init__(self):
                super().__init__(command="codex")
                self.recorded_cwd = None

            def run_subprocess(self, **kwargs):
                self.recorded_cwd = kwargs["cwd"]
                artifacts = self.collect_artifacts(kwargs["run_dir"])
                return RunResult(
                    status=AgentRunStatus.SUCCESS.value,
                    exit_code=0,
                    artifacts=artifacts,
                    report={
                        "runner": self.name,
                        "status": AgentRunStatus.SUCCESS.value,
                        "mode": kwargs["mode"].value,
                    },
                )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-task-thread"}),
                encoding="utf-8",
            )
            (run_dir / "input-prompt.md").write_text("prompt", encoding="utf-8")
            project_path = Path(tmp) / "project"
            workspace_path = Path(tmp) / "workspace"
            project_path.mkdir()
            workspace_path.mkdir()
            runner = RecordingRunner()

            runner.run(
                run_id="run_1",
                run_dir=run_dir,
                project_path=project_path,
                workspace_path=workspace_path,
                mode=RunMode.IMPLEMENTATION,
                timeout_seconds=5,
            )

            self.assertEqual(runner.recorded_cwd, workspace_path)

    def test_run_subprocess_creates_runner_failed_report_when_process_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            stdin_path = run_dir / "input-prompt.md"
            stdin_path.write_text("prompt", encoding="utf-8")
            runner = CodexCliRunner(command="codex")

            result = runner.run_subprocess(
                run_id="run_fail",
                command=["/missing/codex-binary"],
                run_dir=run_dir,
                stdin_path=stdin_path,
                timeout_seconds=1,
                mode=RunMode.IMPLEMENTATION,
            )

            self.assertEqual(result.status, AgentRunStatus.FAILED.value)
            self.assertEqual(result.report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(result.report["raw_status"], "runner_failed")
            self.assertEqual(result.report["failure_type"], "runner_failed")
            self.assertTrue((run_dir / "report.json").exists())
            self.assertIn("process_start_failed", result.report["verification_limitations"][0]["reason"])
            self.assertEqual(result.report["qa_artifacts"], {"report": "", "baseline": "", "screenshots_dir": ""})
            self.assertEqual(result.report["tested_commit"], "")

    def test_subprocess_run_writes_timing_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            stdin_path = run_dir / "input-prompt.md"
            stdin_path.write_text("prompt", encoding="utf-8")
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"run_id": "run_timing", "mode": "plan-only"}),
                encoding="utf-8",
            )

            result = CodexCliRunner(command="codex").run_subprocess(
                run_id="run_timing",
                command=[sys.executable, "-c", "print('unstructured output')"],
                run_dir=run_dir,
                stdin_path=stdin_path,
                timeout_seconds=5,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(result.status, AgentRunStatus.FAILED.value)
            manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["run_id"], "run_timing")
            self.assertIn("started_at", manifest)
            self.assertIn("completed_at", manifest)
            self.assertIsInstance(manifest["duration_ms"], int)
            self.assertGreaterEqual(manifest["duration_ms"], 0)
            self.assertEqual(result.report["failure_type"], "runner_failed")
            self.assertEqual(result.report["verification_limitations"][0]["reason"], "structured_report_missing")


if __name__ == "__main__":
    unittest.main()
