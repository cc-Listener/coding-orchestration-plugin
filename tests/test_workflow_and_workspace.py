import tempfile
import unittest
from pathlib import Path

from coding_orchestration.symphony_compat.workflow_loader import WorkflowLoader
from coding_orchestration.symphony_compat.workspace_manager import WorkspaceManager


class WorkflowAndWorkspaceTest(unittest.TestCase):
    def test_workflow_loader_parses_project_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "WORKFLOW.md").write_text(
                """
# WORKFLOW

## Allowed Paths
- src/
- tests/

## Forbidden Paths
- .env
- deploy/

## Test Commands
- rtk pnpm test

## Merge Policy
manual_only

## Publish Policy
manual_only

## Recommended Runner
codex_cli
""",
                encoding="utf-8",
            )

            spec = WorkflowLoader().load(project)

            self.assertEqual(spec.allowed_paths, ["src/", "tests/"])
            self.assertEqual(spec.forbidden_paths, [".env", "deploy/"])
            self.assertEqual(spec.default_test_commands, ["rtk pnpm test"])
            self.assertEqual(spec.recommended_runner, "codex_cli")

    def test_workspace_manager_copies_non_git_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            (project / "file.txt").write_text("hello", encoding="utf-8")

            workspace = WorkspaceManager(root / "workspaces").create_workspace(
                project_path=project,
                task_id="task_1",
                run_id="run_1",
            )

            self.assertTrue((workspace / "file.txt").exists())
            self.assertEqual((workspace / "file.txt").read_text(encoding="utf-8"), "hello")


if __name__ == "__main__":
    unittest.main()
