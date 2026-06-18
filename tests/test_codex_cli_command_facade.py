import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import RunMode
from coding_orchestration.runners.codex_cli import CodexCliRunner


class CodexCliCommandFacadeTest(unittest.TestCase):
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
        self.assertEqual(command[command.index("--output-last-message") + 1], "/tmp/run/report.json")
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        self.assertNotIn("--ask-for-approval", command)
        self.assertIn("approval_policy=\"never\"", command)
        self.assertIn("-C", command)
        self.assertIn("/repo/project", command)
        self.assertEqual(command[-1], "-")

    def test_plan_only_command_uses_bypass_when_manifest_requires_source_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"dangerous_bypass": True}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=None,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(command[:2], ["codex", "exec"])
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn("--sandbox", command)
            self.assertNotIn("approval_policy=\"never\"", command)
            self.assertIn("-C", command)
            self.assertIn("/repo/project", command)
            self.assertEqual(command[-1], "-")

    def test_plan_only_resume_uses_read_only_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-plan-thread"}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=None,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("--json", command)
            self.assertIn("019e-plan-thread", command)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertIn("sandbox_mode=\"read-only\"", command)
            self.assertIn("approval_policy=\"never\"", command)
            self.assertEqual(command[-1], "-")

    def test_plan_only_resume_uses_bypass_when_manifest_requires_source_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-plan-thread", "dangerous_bypass": True}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=None,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn("sandbox_mode=\"read-only\"", command)
            self.assertNotIn("approval_policy=\"never\"", command)
            self.assertIn("019e-plan-thread", command)
            self.assertEqual(command[-1], "-")

    def test_implementation_command_uses_controlled_bypass_and_workspace_path(self):
        runner = CodexCliRunner(command="codex")
        command = runner.build_command(
            run_dir=Path("/tmp/run"),
            project_path=Path("/repo/project"),
            workspace_path=Path("/tmp/workspace"),
            mode=RunMode.IMPLEMENTATION,
        )

        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertIn("--output-schema", command)
        self.assertNotIn("--sandbox", command)
        self.assertNotIn("workspace-write", command)
        self.assertIn("/tmp/workspace", command)
        self.assertNotIn("/repo/project", command[command.index("-C") + 1])

    def test_qa_command_uses_controlled_bypass_and_workspace_path(self):
        runner = CodexCliRunner(command="codex")
        command = runner.build_command(
            run_dir=Path("/tmp/run"),
            project_path=Path("/repo/project"),
            workspace_path=Path("/tmp/workspace"),
            mode=RunMode.QA,
        )

        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertIn("--output-schema", command)
        self.assertNotIn("--sandbox", command)
        self.assertIn("/tmp/workspace", command)

    def test_implementation_command_resumes_task_session_when_manifest_has_resume_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-task-thread"}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.IMPLEMENTATION,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("--json", command)
            self.assertIn("019e-task-thread", command)
            self.assertIn("--output-last-message", command)
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn("sandbox_mode=\"workspace-write\"", command)
            self.assertNotIn("approval_policy=\"never\"", command)
            self.assertEqual(command[-1], "-")
            self.assertNotIn("--output-schema", command)

    def test_merge_test_command_resumes_session_with_bypass(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-test-thread"}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.MERGE_TEST,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertIn("--json", command)
            self.assertIn("019e-test-thread", command)
            self.assertIn("--output-last-message", command)
            self.assertEqual(command[-1], "-")

    def test_qa_command_resumes_task_session_with_controlled_bypass(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-qa-thread"}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.QA,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("--json", command)
            self.assertIn("019e-qa-thread", command)
            self.assertIn("--output-last-message", command)
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn("sandbox_mode=\"workspace-write\"", command)
            self.assertNotIn("approval_policy=\"never\"", command)
            self.assertEqual(command[-1], "-")

    def test_plan_only_subprocess_runs_from_project_path(self):
        self.assertEqual(
            CodexCliRunner.subprocess_cwd(
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.PLAN_ONLY,
            ),
            Path("/repo/project"),
        )


if __name__ == "__main__":
    unittest.main()
