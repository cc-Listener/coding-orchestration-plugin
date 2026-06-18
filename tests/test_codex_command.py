import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import RunMode
from coding_orchestration.runners.codex_command import (
    CodexCommandBuilder,
    manifest_dangerous_bypass,
    resume_session_id,
)


class CodexCommandBuilderTest(unittest.TestCase):
    def test_plan_only_command_uses_read_only_sandbox(self):
        command = CodexCommandBuilder(command="codex").build(
            run_dir=Path("/tmp/run"),
            project_path=Path("/repo/project"),
            workspace_path=None,
            mode=RunMode.PLAN_ONLY,
        )

        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertIn("--output-schema", command)
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        self.assertIn("approval_policy=\"never\"", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertEqual(command[command.index("-C") + 1], "/repo/project")
        self.assertEqual(command[-1], "-")

    def test_manifest_dangerous_bypass_uses_project_path_for_plan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"dangerous_bypass": True}),
                encoding="utf-8",
            )

            command = CodexCommandBuilder(command="codex").build(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.PLAN_ONLY,
            )

            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn("--sandbox", command)
            self.assertEqual(command[command.index("-C") + 1], "/tmp/workspace")

    def test_resume_command_uses_read_only_for_plan_only_without_bypass(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-plan-thread"}),
                encoding="utf-8",
            )

            command = CodexCommandBuilder(command="codex").build(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=None,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("019e-plan-thread", command)
            self.assertIn("sandbox_mode=\"read-only\"", command)
            self.assertIn("approval_policy=\"never\"", command)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn("--output-schema", command)
            self.assertEqual(command[-1], "-")

    def test_implementation_resume_uses_bypass_and_skips_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-task-thread"}),
                encoding="utf-8",
            )

            command = CodexCommandBuilder(command="codex").build(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.IMPLEMENTATION,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn("--output-schema", command)
            self.assertIn("019e-task-thread", command)

    def test_manifest_helpers_ignore_missing_or_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)

            self.assertEqual(resume_session_id(run_dir), "")
            self.assertFalse(manifest_dangerous_bypass(run_dir))

            (run_dir / "run-manifest.json").write_text("{invalid", encoding="utf-8")

            self.assertEqual(resume_session_id(run_dir), "")
            self.assertFalse(manifest_dangerous_bypass(run_dir))


if __name__ == "__main__":
    unittest.main()
