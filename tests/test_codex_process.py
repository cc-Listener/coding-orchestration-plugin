import json
import sys
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.runners.codex_artifacts import collect_codex_artifacts
from coding_orchestration.runners.codex_process import CodexProcessRunner


class RecordingProcessCallbacks:
    def __init__(self, report_status="success"):
        self.report_status = report_status
        self.fallback_kwargs = None
        self.loaded_report = False

    def collect_artifacts(self, run_dir):
        return collect_codex_artifacts(run_dir)

    def build_fallback_report(self, **kwargs):
        self.fallback_kwargs = dict(kwargs)
        return {
            "status": AgentRunStatus.FAILED.value,
            "raw_status": kwargs["status"],
            "failure_type": kwargs["status"],
            "verification_limitations": [{"reason": kwargs["limitation_reason"]}],
        }

    def load_or_build_report(self, run_dir, mode):
        self.loaded_report = True
        return {"status": self.report_status}


class CodexProcessRunnerTest(unittest.TestCase):
    def test_process_start_failure_builds_runner_failed_report(self):
        callbacks = RecordingProcessCallbacks()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            stdin_path = run_dir / "input-prompt.md"
            stdin_path.write_text("prompt", encoding="utf-8")

            result = CodexProcessRunner(callbacks).run_subprocess(
                run_id="run_fail",
                command=["/missing/codex-binary"],
                run_dir=run_dir,
                stdin_path=stdin_path,
                timeout_seconds=1,
                mode=RunMode.IMPLEMENTATION,
            )

            self.assertEqual(result.status, AgentRunStatus.FAILED.value)
            self.assertEqual(callbacks.fallback_kwargs["limitation_reason"], "process_start_failed")
            self.assertFalse(callbacks.loaded_report)
            manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("duration_ms", manifest)

    def test_successful_process_loads_report_and_writes_timing(self):
        callbacks = RecordingProcessCallbacks(report_status="success")
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            stdin_path = run_dir / "input-prompt.md"
            stdin_path.write_text("prompt", encoding="utf-8")
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"run_id": "run_ok"}),
                encoding="utf-8",
            )

            result = CodexProcessRunner(callbacks).run_subprocess(
                run_id="run_ok",
                command=[sys.executable, "-c", "print('ok')"],
                run_dir=run_dir,
                stdin_path=stdin_path,
                timeout_seconds=5,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(result.status, AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(result.exit_code, 0)
            self.assertTrue(callbacks.loaded_report)
            self.assertEqual((run_dir / "stdout.log").read_text(encoding="utf-8").strip(), "ok")
            manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["run_id"], "run_ok")
            self.assertIn("started_at", manifest)
            self.assertIn("completed_at", manifest)
            self.assertIsInstance(manifest["duration_ms"], int)


if __name__ == "__main__":
    unittest.main()
