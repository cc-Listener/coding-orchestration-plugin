from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.run.services.run_evidence_observation_service import (
    RunQaEvidenceObservation,
    observe_implementation_dirty_check,
    observe_run_qa_evidence,
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


class RunEvidenceObservationServiceTest(unittest.TestCase):
    def test_observe_run_qa_evidence_skips_callbacks_when_disabled(self):
        calls = []

        observation = observe_run_qa_evidence(
            enabled=False,
            workspace_path=Path("/tmp/workspace"),
            collect_qa_artifacts_callback=lambda workspace_path: calls.append(("artifacts", workspace_path)),
            git_head_callback=lambda workspace_path: calls.append(("head", workspace_path)),
        )

        self.assertEqual(observation, RunQaEvidenceObservation(qa_artifacts={}, tested_commit=""))
        self.assertEqual(calls, [])

    def test_observe_run_qa_evidence_collects_artifacts_and_tested_commit_when_enabled(self):
        workspace = Path("/tmp/workspace")
        calls = []

        observation = observe_run_qa_evidence(
            enabled=True,
            workspace_path=workspace,
            collect_qa_artifacts_callback=lambda workspace_path: calls.append(("artifacts", workspace_path))
            or {"report": "qa.md"},
            git_head_callback=lambda workspace_path: calls.append(("head", workspace_path)) or "abc123",
        )

        self.assertEqual(observation.qa_artifacts, {"report": "qa.md"})
        self.assertEqual(observation.tested_commit, "abc123")
        self.assertEqual(calls, [("artifacts", workspace), ("head", workspace)])

    def test_observe_implementation_dirty_check_only_calls_callback_when_required(self):
        calls = []

        skipped = observe_implementation_dirty_check(
            required=False,
            workspace_path=Path("/tmp/workspace"),
            workspace_has_uncommitted_changes_callback=lambda workspace_path: calls.append(workspace_path) or True,
        )
        observed = observe_implementation_dirty_check(
            required=True,
            workspace_path=Path("/tmp/workspace"),
            workspace_has_uncommitted_changes_callback=lambda workspace_path: calls.append(workspace_path) or True,
        )

        self.assertFalse(skipped)
        self.assertTrue(observed)
        self.assertEqual(calls, [Path("/tmp/workspace")])

    def test_start_run_delegates_qa_evidence_observation_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_evidence_observation"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
                requirement_summary="生成订单筛选计划",
                project_path=str(project),
                status=TaskStatus.NEW.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                diff_guard=MinimalDiffGuard(),
            )
            calls = []
            original_observe = orchestrator_module.run_evidence_observation_service.observe_run_qa_evidence

            def fake_observe_run_qa_evidence(**kwargs):
                calls.append(kwargs)
                return RunQaEvidenceObservation(
                    qa_artifacts={"report": "qa-report.md"},
                    tested_commit="abc123",
                )

            try:
                orchestrator_module.run_evidence_observation_service.observe_run_qa_evidence = (
                    fake_observe_run_qa_evidence
                )

                result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

                report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))
                self.assertEqual(len(calls), 1)
                self.assertFalse(calls[0]["enabled"])
                self.assertIsNone(calls[0]["workspace_path"])
                self.assertTrue(callable(calls[0]["collect_qa_artifacts_callback"]))
                self.assertEqual(calls[0]["collect_qa_artifacts_callback"].__name__, "_collect_qa_artifacts")
                self.assertTrue(callable(calls[0]["git_head_callback"]))
                self.assertEqual(calls[0]["git_head_callback"].__name__, "_git_head")
                self.assertEqual(report["qa_artifacts"], {"report": "qa-report.md"})
                self.assertEqual(report["tested_commit"], "abc123")
            finally:
                orchestrator_module.run_evidence_observation_service.observe_run_qa_evidence = original_observe

    def test_start_run_delegates_implementation_dirty_check_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_dirty_observation"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
                requirement_summary="生成订单筛选计划",
                project_path=str(project),
                status=TaskStatus.NEW.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                diff_guard=MinimalDiffGuard(),
            )
            calls = []
            original_observe = (
                orchestrator_module.run_evidence_observation_service.observe_implementation_dirty_check
            )

            def fake_observe_implementation_dirty_check(**kwargs):
                calls.append(kwargs)
                return False

            try:
                orchestrator_module.run_evidence_observation_service.observe_implementation_dirty_check = (
                    fake_observe_implementation_dirty_check
                )

                result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

                self.assertEqual(result["status"], AgentRunStatus.SUCCEEDED.value)
                self.assertEqual(len(calls), 1)
                self.assertFalse(calls[0]["required"])
                self.assertIsNone(calls[0]["workspace_path"])
                self.assertTrue(callable(calls[0]["workspace_has_uncommitted_changes_callback"]))
                self.assertEqual(
                    calls[0]["workspace_has_uncommitted_changes_callback"].__name__,
                    "_workspace_has_uncommitted_changes",
                )
            finally:
                orchestrator_module.run_evidence_observation_service.observe_implementation_dirty_check = (
                    original_observe
                )


if __name__ == "__main__":
    unittest.main()
