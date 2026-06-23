from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from coding_orchestration import orchestrator as orchestrator_module
from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import RunMode, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.run.services.run_implementation_checkpoint_service import (
    RunImplementationCheckpointResult,
    write_implementation_checkpoint_if_dirty,
)
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


class MinimalDiffGuard:
    def snapshot(self, root):
        return {"root": str(root)}

    def changed_files(self, root, before):
        return []

    def find_violations(self, *, changed_files, allowed_paths, forbidden_paths):
        return []

    def write_diff_summary(self, path, changed_files, violations):
        path.write_text("", encoding="utf-8")


class _ManifestObject:
    def __init__(self):
        self.implementation_checkpoint = None


class RunImplementationCheckpointServiceTest(unittest.TestCase):
    def test_write_implementation_checkpoint_skips_when_not_dirty(self):
        manifest = _ManifestObject()
        calls = []

        result = write_implementation_checkpoint_if_dirty(
            implementation_dirty=False,
            workspace_path=Path("/tmp/workspace"),
            manifest=manifest,
            manifest_path=Path("/tmp/run-manifest.json"),
            workspace_clean_checkpoint_callback=lambda workspace_path: calls.append(
                ("checkpoint", workspace_path)
            )
            or {"status": "clean"},
            write_manifest_artifact_callback=lambda **kwargs: calls.append(("write", kwargs))
            or "run-manifest.json",
        )

        self.assertEqual(
            result,
            RunImplementationCheckpointResult(
                implementation_checkpoint=None,
                manifest_artifact=None,
                manifest_written=False,
            ),
        )
        self.assertIsNone(manifest.implementation_checkpoint)
        self.assertEqual(calls, [])

    def test_write_implementation_checkpoint_records_checkpoint_and_writes_manifest(self):
        manifest = _ManifestObject()
        workspace = Path("/tmp/workspace")
        manifest_path = Path("/tmp/run-manifest.json")
        calls = []

        def write_manifest_artifact_callback(**kwargs):
            calls.append(("write", kwargs["manifest_path"], kwargs["manifest"].implementation_checkpoint))
            return str(kwargs["manifest_path"])

        result = write_implementation_checkpoint_if_dirty(
            implementation_dirty=True,
            workspace_path=workspace,
            manifest=manifest,
            manifest_path=manifest_path,
            workspace_clean_checkpoint_callback=lambda workspace_path: calls.append(
                ("checkpoint", workspace_path)
            )
            or {"status": "failed", "reason": "implementation_commit_missing"},
            write_manifest_artifact_callback=write_manifest_artifact_callback,
        )

        checkpoint = {"status": "failed", "reason": "implementation_commit_missing"}
        self.assertEqual(
            result,
            RunImplementationCheckpointResult(
                implementation_checkpoint=checkpoint,
                manifest_artifact=str(manifest_path),
                manifest_written=True,
            ),
        )
        self.assertEqual(manifest.implementation_checkpoint, checkpoint)
        self.assertEqual(
            calls,
            [
                ("checkpoint", workspace),
                ("write", manifest_path, checkpoint),
            ],
        )

    def test_write_implementation_checkpoint_updates_dict_manifest(self):
        manifest = {}

        result = write_implementation_checkpoint_if_dirty(
            implementation_dirty=True,
            workspace_path=None,
            manifest=manifest,
            manifest_path=Path("/tmp/run-manifest.json"),
            workspace_clean_checkpoint_callback=lambda workspace_path: {"status": "skipped"},
            write_manifest_artifact_callback=lambda **kwargs: str(kwargs["manifest_path"]),
        )

        self.assertEqual(result.implementation_checkpoint, {"status": "skipped"})
        self.assertEqual(manifest["implementation_checkpoint"], {"status": "skipped"})

    def test_start_run_delegates_dirty_checkpoint_writeback_to_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, stdout=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            _write_workflow(project)
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(
                ["git", "commit", "-m", "main baseline"],
                cwd=project,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            def mutate_without_commit(cwd: Path) -> None:
                (cwd / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")

            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_dirty_checkpoint"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
                requirement_summary="修复订单状态",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(mutate=mutate_without_commit)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
                diff_guard=MinimalDiffGuard(),
            )
            calls = []
            original_writeback = (
                orchestrator_module.run_implementation_checkpoint_service.write_implementation_checkpoint_if_dirty
            )

            def fake_write_implementation_checkpoint_if_dirty(**kwargs):
                calls.append(kwargs)
                checkpoint = kwargs["workspace_clean_checkpoint_callback"](kwargs["workspace_path"])
                kwargs["manifest"].implementation_checkpoint = checkpoint
                artifact = kwargs["write_manifest_artifact_callback"](
                    manifest_path=kwargs["manifest_path"],
                    manifest=kwargs["manifest"],
                )
                return RunImplementationCheckpointResult(
                    implementation_checkpoint=checkpoint,
                    manifest_artifact=artifact,
                    manifest_written=True,
                )

            try:
                orchestrator_module.run_implementation_checkpoint_service.write_implementation_checkpoint_if_dirty = (
                    fake_write_implementation_checkpoint_if_dirty
                )

                result = orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

                manifest = json.loads(Path(result["artifacts"]["manifest"]).read_text(encoding="utf-8"))
                self.assertEqual(len(calls), 1)
                self.assertTrue(calls[0]["implementation_dirty"])
                self.assertEqual(calls[0]["workspace_path"], fake_runner.calls[0]["workspace_path"])
                self.assertEqual(calls[0]["manifest_path"], Path(result["artifacts"]["manifest"]))
                self.assertTrue(callable(calls[0]["workspace_clean_checkpoint_callback"]))
                self.assertTrue(callable(calls[0]["write_manifest_artifact_callback"]))
                self.assertEqual(manifest["implementation_checkpoint"]["status"], "failed")
            finally:
                orchestrator_module.run_implementation_checkpoint_service.write_implementation_checkpoint_if_dirty = (
                    original_writeback
                )


if __name__ == "__main__":
    unittest.main()
