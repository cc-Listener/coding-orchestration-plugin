from __future__ import annotations

import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from coding_orchestration.models import RunMode
from coding_orchestration.workspace.checkpoint_service import (
    WorkspaceCheckpointService,
    collect_qa_artifacts,
    diff_guard_changed_files_for_mode,
    git_head,
    latest_existing_implementation_workspace,
    source_base_branch_for_task,
    source_branch_for_task,
    workspace_clean_checkpoint,
    workspace_has_uncommitted_changes,
)


class FakeWorkspaceManager:
    def __init__(self, result: Path):
        self.result = result
        self.calls: list[dict[str, object]] = []

    def create_workspace(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.result


class WorkspaceCheckpointServiceTest(unittest.TestCase):
    def test_source_branch_for_task_falls_back_for_non_ascii_candidate(self):
        branch = source_branch_for_task(
            {
                "task_id": "task_9f8e7d6c5b4a",
                "requirement_summary": "订单状态修复",
                "task_session": {
                    "plan_report": {
                        "branch_slug_candidate": "修复 订单/状态!!!",
                    },
                },
            },
            "order-system",
        )

        self.assertEqual(branch, "codex/task-9f8e7d6c5b4a")

    def test_source_branch_for_task_prefers_existing_source_branch(self):
        branch = source_branch_for_task(
            {
                "task_id": "task_existing_branch",
                "task_session": {
                    "source_branch": "codex/already-created-existing_branch",
                    "plan_report": {
                        "branch_slug_candidate": "fix-order-status",
                    },
                },
            },
            "order-system",
        )

        self.assertEqual(branch, "codex/already-created-existing_branch")

    def test_source_branch_for_task_limits_sanitized_candidate_length(self):
        branch = source_branch_for_task(
            {
                "task_id": "task_long_slug",
                "task_session": {
                    "plan_report": {
                        "branch_slug_candidate": f"{'a' * 63}-bbbbbbbbbbbb",
                    },
                },
            },
            "order-system",
        )

        self.assertEqual(branch, f"codex/{'a' * 63}-long_slug")

    def test_source_branch_for_task_without_candidate_falls_back_to_task(self):
        branch = source_branch_for_task(
            {
                "task_id": "task_no_candidate",
                "task_session": {
                    "plan_report": {},
                },
            },
            "order-system",
        )

        self.assertEqual(branch, "codex/task-no_candidate")

    def test_source_base_branch_prefers_session_then_source_then_main(self):
        self.assertEqual(
            source_base_branch_for_task(
                {
                    "task_session": {"source_base_branch": "release"},
                    "source": {"base_branch": "develop"},
                }
            ),
            "release",
        )
        self.assertEqual(source_base_branch_for_task({"source": {"base_branch": "develop"}}), "develop")
        self.assertEqual(source_base_branch_for_task({"source": {}}), "main")

    def test_latest_existing_implementation_workspace_uses_latest_existing_impl_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_workspace = root / "old"
            latest_workspace = root / "latest"
            old_workspace.mkdir()
            latest_workspace.mkdir()

            workspace = latest_existing_implementation_workspace(
                {
                    "agent_runs": [
                        {"mode": RunMode.IMPLEMENTATION.value, "workspace_path": str(old_workspace)},
                        {"mode": RunMode.QA.value, "workspace_path": str(root / "qa")},
                        {"mode": RunMode.IMPLEMENTATION.value, "workspace_path": str(root / "missing")},
                        {"mode": RunMode.IMPLEMENTATION.value, "workspace_path": str(latest_workspace)},
                    ]
                }
            )

            self.assertEqual(workspace, latest_workspace)

    def test_implementation_workspace_reuses_existing_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "existing"
            existing.mkdir()
            manager = FakeWorkspaceManager(root / "new")
            service = WorkspaceCheckpointService(manager)

            workspace = service.implementation_workspace(
                {
                    "task_id": "task_1",
                    "agent_runs": [
                        {"mode": RunMode.IMPLEMENTATION.value, "workspace_path": str(existing)},
                    ],
                },
                root / "project",
                "run_new",
            )

            self.assertEqual(workspace, existing)
            self.assertEqual(manager.calls, [])

    def test_implementation_workspace_creates_new_workspace_with_branch_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = FakeWorkspaceManager(root / "new")
            service = WorkspaceCheckpointService(manager)

            workspace = service.implementation_workspace(
                {
                    "task_id": "task_1",
                    "source": {"project_name": "order", "base_branch": "develop"},
                    "task_session": {"plan_report": {"branch_slug_candidate": "fix-order-status"}},
                },
                root / "project",
                "run_new",
            )

            self.assertEqual(workspace, root / "new")
            self.assertEqual(manager.calls[0]["project_path"], root / "project")
            self.assertEqual(manager.calls[0]["task_id"], "task_1")
            self.assertEqual(manager.calls[0]["run_id"], "run_new")
            self.assertEqual(manager.calls[0]["base_branch"], "develop")
            self.assertEqual(manager.calls[0]["branch_name"], "codex/fix-order-status-1")

    def test_merge_test_workspace_uses_session_worktree_when_no_agent_run_workspace_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktree = root / "session-worktree"
            worktree.mkdir()
            service = WorkspaceCheckpointService(FakeWorkspaceManager(root / "unused"))

            workspace = service.merge_test_workspace({"task_session": {"worktree_path": str(worktree)}})

            self.assertEqual(workspace, worktree.resolve())

    def test_diff_guard_changed_files_ignores_qa_report_artifacts_only_for_qa(self):
        changed = [".gstack/qa-reports/qa-report-1.md", "src/app.ts"]

        self.assertEqual(diff_guard_changed_files_for_mode(RunMode.QA, changed), ["src/app.ts"])
        self.assertEqual(diff_guard_changed_files_for_mode(RunMode.IMPLEMENTATION, changed), changed)

    def test_collect_qa_artifacts_picks_latest_report_and_optional_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qa_dir = root / ".gstack" / "qa-reports"
            screenshots = qa_dir / "screenshots"
            screenshots.mkdir(parents=True)
            old_report = qa_dir / "qa-report-old.md"
            latest_report = qa_dir / "qa-report-latest.md"
            old_report.write_text("old", encoding="utf-8")
            time.sleep(0.01)
            latest_report.write_text("latest", encoding="utf-8")
            (qa_dir / "baseline.json").write_text("{}", encoding="utf-8")

            artifacts = collect_qa_artifacts(root)

            self.assertEqual(artifacts["report"], str(latest_report))
            self.assertEqual(artifacts["baseline"], str(qa_dir / "baseline.json"))
            self.assertEqual(artifacts["screenshots_dir"], str(screenshots))

    def test_workspace_clean_checkpoint_reports_clean_head_and_dirty_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "README.md").write_text("ok\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            clean = workspace_clean_checkpoint(root)
            self.assertEqual(clean["status"], "clean")
            self.assertEqual(clean["head"], git_head(root))
            self.assertFalse(workspace_has_uncommitted_changes(root))

            (root / "README.md").write_text("changed\n", encoding="utf-8")
            dirty = workspace_clean_checkpoint(root)
            self.assertEqual(dirty["status"], "failed")
            self.assertEqual(dirty["reason"], "implementation_commit_missing")
            self.assertTrue(workspace_has_uncommitted_changes(root))


if __name__ == "__main__":
    unittest.main()
