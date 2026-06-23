from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration import orchestrator as orchestrator_module
from coding_orchestration.run.projections import run_start_selection_projection
from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import RunMode, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.run_checkpoint_preparation_service import (
    RunCheckpointPreparationResult,
    prepare_run_checkpoint,
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


class RunCheckpointPreparationServiceTest(unittest.TestCase):
    def test_prepare_run_checkpoint_skips_callbacks_for_none_kind(self):
        calls = []
        preparation = run_start_selection_projection.RunManifestCheckpointPreparation(
            checkpoint_kind=run_start_selection_projection.RUN_MANIFEST_CHECKPOINT_NONE,
        )

        result = prepare_run_checkpoint(
            checkpoint_preparation=preparation,
            workspace_path=Path("/tmp/workspace"),
            task_id="task_1",
            prepare_qa_checkpoint_callback=lambda workspace_path, task_id: calls.append(
                ("qa", workspace_path, task_id)
            )
            or {"status": "clean"},
            prepare_merge_test_checkpoint_callback=lambda workspace_path, task_id: calls.append(
                ("merge", workspace_path, task_id)
            )
            or {"status": "clean"},
        )

        self.assertEqual(result, RunCheckpointPreparationResult(manifest_updates={}))
        self.assertEqual(calls, [])

    def test_prepare_run_checkpoint_calls_qa_callback_for_qa_kind(self):
        workspace = Path("/tmp/workspace")
        calls = []
        preparation = run_start_selection_projection.RunManifestCheckpointPreparation(
            checkpoint_kind=run_start_selection_projection.RUN_MANIFEST_CHECKPOINT_QA,
            manifest_field="qa_checkpoint",
        )

        result = prepare_run_checkpoint(
            checkpoint_preparation=preparation,
            workspace_path=workspace,
            task_id="task_1",
            prepare_qa_checkpoint_callback=lambda workspace_path, task_id: calls.append(
                ("qa", workspace_path, task_id)
            )
            or {"status": "clean", "head": "abc123"},
            prepare_merge_test_checkpoint_callback=lambda workspace_path, task_id: calls.append(
                ("merge", workspace_path, task_id)
            )
            or {"status": "clean"},
        )

        self.assertEqual(
            result,
            RunCheckpointPreparationResult(
                manifest_updates={"qa_checkpoint": {"status": "clean", "head": "abc123"}},
            ),
        )
        self.assertEqual(calls, [("qa", workspace, "task_1")])

    def test_prepare_run_checkpoint_calls_merge_callback_for_merge_test_kind(self):
        workspace = Path("/tmp/workspace")
        calls = []
        preparation = run_start_selection_projection.RunManifestCheckpointPreparation(
            checkpoint_kind=run_start_selection_projection.RUN_MANIFEST_CHECKPOINT_MERGE_TEST,
            manifest_field="merge_test_checkpoint",
            target_branch="test",
        )

        result = prepare_run_checkpoint(
            checkpoint_preparation=preparation,
            workspace_path=workspace,
            task_id="task_1",
            prepare_qa_checkpoint_callback=lambda workspace_path, task_id: calls.append(
                ("qa", workspace_path, task_id)
            )
            or {"status": "clean"},
            prepare_merge_test_checkpoint_callback=lambda workspace_path, task_id: calls.append(
                ("merge", workspace_path, task_id)
            )
            or {"status": "clean", "head": "def456"},
        )

        self.assertEqual(
            result,
            RunCheckpointPreparationResult(
                manifest_updates={"merge_test_checkpoint": {"status": "clean", "head": "def456"}},
            ),
        )
        self.assertEqual(calls, [("merge", workspace, "task_1")])

    def test_prepare_run_checkpoint_omits_manifest_update_when_callback_returns_none(self):
        preparation = run_start_selection_projection.RunManifestCheckpointPreparation(
            checkpoint_kind=run_start_selection_projection.RUN_MANIFEST_CHECKPOINT_QA,
            manifest_field="qa_checkpoint",
        )

        result = prepare_run_checkpoint(
            checkpoint_preparation=preparation,
            workspace_path=Path("/tmp/workspace"),
            task_id="task_1",
            prepare_qa_checkpoint_callback=lambda workspace_path, task_id: None,
            prepare_merge_test_checkpoint_callback=lambda workspace_path, task_id: {"status": "clean"},
        )

        self.assertEqual(result, RunCheckpointPreparationResult(manifest_updates={}))

    def test_start_run_delegates_checkpoint_preparation_to_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_1"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
                requirement_summary="检查订单 QA",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/orders-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-qa-thread"},
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner(status=TaskStatus.READY_FOR_MERGE_TEST.value)),
                diff_guard=MinimalDiffGuard(),
            )
            calls = []
            original_prepare = orchestrator_module.run_checkpoint_preparation_service.prepare_run_checkpoint

            def fake_prepare_run_checkpoint(**kwargs):
                calls.append(kwargs)
                return RunCheckpointPreparationResult(
                    manifest_updates={"qa_checkpoint": {"status": "clean", "head": "abc123"}},
                )

            try:
                orchestrator_module.run_checkpoint_preparation_service.prepare_run_checkpoint = (
                    fake_prepare_run_checkpoint
                )

                result = orchestrator.start_run(task_id, mode=RunMode.QA, timeout_seconds=5)

                manifest = json.loads(Path(result["artifacts"]["manifest"]).read_text(encoding="utf-8"))
                self.assertEqual(len(calls), 1)
                self.assertEqual(
                    calls[0]["checkpoint_preparation"].checkpoint_kind,
                    run_start_selection_projection.RUN_MANIFEST_CHECKPOINT_QA,
                )
                self.assertEqual(calls[0]["workspace_path"], workspace.resolve())
                self.assertEqual(calls[0]["task_id"], task_id)
                self.assertTrue(callable(calls[0]["prepare_qa_checkpoint_callback"]))
                self.assertTrue(callable(calls[0]["prepare_merge_test_checkpoint_callback"]))
                self.assertEqual(manifest["qa_checkpoint"], {"status": "clean", "head": "abc123"})
            finally:
                orchestrator_module.run_checkpoint_preparation_service.prepare_run_checkpoint = original_prepare


if __name__ == "__main__":
    unittest.main()
