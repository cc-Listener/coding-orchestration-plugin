from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import RunMode, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.run.services.run_diff_guard_service import (
    RunDiffGuardObservation,
    observe_run_diff_guard,
    snapshot_run_diff_guard,
)
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


class FakeDiffGuard:
    def __init__(self):
        self.calls = []

    def snapshot(self, root):
        self.calls.append(("snapshot", root))
        return {"src/app.ts": "before"}

    def changed_files(self, root, before):
        self.calls.append(("changed_files", root, before))
        return ["src/app.ts", ".gstack/qa-reports/qa-report-1.md"]

    def find_violations(self, *, changed_files, allowed_paths, forbidden_paths):
        self.calls.append(("find_violations", changed_files, allowed_paths, forbidden_paths))
        return [f"{path} is outside policy" for path in changed_files if path.startswith("src/")]

    def write_diff_summary(self, path, changed_files, violations):
        self.calls.append(("write_diff_summary", path, changed_files, violations))
        path.write_text("diff summary", encoding="utf-8")


class RunDiffGuardServiceTest(unittest.TestCase):
    def test_snapshot_run_diff_guard_delegates_to_diff_guard(self):
        diff_guard = FakeDiffGuard()
        root = Path("/tmp/project")

        snapshot = snapshot_run_diff_guard(diff_guard=diff_guard, execution_root=root)

        self.assertEqual(snapshot, {"src/app.ts": "before"})
        self.assertEqual(diff_guard.calls, [("snapshot", root)])

    def test_observe_run_diff_guard_filters_qa_artifacts_writes_summary_and_returns_observation(self):
        diff_guard = FakeDiffGuard()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diff_path = root / "diff.patch"
            workflow = SimpleNamespace(allowed_paths=["src/"], forbidden_paths=["dist/"])

            observation = observe_run_diff_guard(
                diff_guard=diff_guard,
                execution_root=root,
                before_snapshot={"src/app.ts": "before"},
                mode=RunMode.QA,
                workflow=workflow,
                diff_path=diff_path,
            )

            self.assertEqual(
                observation,
                RunDiffGuardObservation(
                    changed_files=["src/app.ts", ".gstack/qa-reports/qa-report-1.md"],
                    violations=["src/app.ts is outside policy"],
                ),
            )
            self.assertEqual(
                diff_guard.calls,
                [
                    ("changed_files", root, {"src/app.ts": "before"}),
                    ("find_violations", ["src/app.ts"], ["src/"], ["dist/"]),
                    (
                        "write_diff_summary",
                        diff_path,
                        ["src/app.ts", ".gstack/qa-reports/qa-report-1.md"],
                        ["src/app.ts is outside policy"],
                    ),
                ],
            )
            self.assertEqual(diff_path.read_text(encoding="utf-8"), "diff summary")

    def test_start_run_delegates_diff_guard_observation_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_diff_guard_service"
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
                diff_guard=object(),
            )
            calls = []
            original_snapshot = orchestrator_module.run_diff_guard_service.snapshot_run_diff_guard
            original_observe = orchestrator_module.run_diff_guard_service.observe_run_diff_guard

            def fake_snapshot_run_diff_guard(**kwargs):
                calls.append(("snapshot", kwargs))
                return {"service": "before"}

            def fake_observe_run_diff_guard(**kwargs):
                calls.append(("observe", kwargs))
                kwargs["diff_path"].write_text("service diff", encoding="utf-8")
                return RunDiffGuardObservation(
                    changed_files=["docs/plan.md"],
                    violations=[
                        "plan-only run modified docs/plan.md; plan-only may read external context but must not write project files"
                    ],
                )

            try:
                orchestrator_module.run_diff_guard_service.snapshot_run_diff_guard = (
                    fake_snapshot_run_diff_guard
                )
                orchestrator_module.run_diff_guard_service.observe_run_diff_guard = (
                    fake_observe_run_diff_guard
                )

                result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

                task = ledger.get_task(task_id)
                report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))
                self.assertEqual([call[0] for call in calls], ["snapshot", "observe"])
                self.assertIs(calls[0][1]["diff_guard"], orchestrator.diff_guard)
                self.assertEqual(calls[1][1]["before_snapshot"], {"service": "before"})
                self.assertEqual(calls[1][1]["mode"], RunMode.PLAN_ONLY)
                self.assertEqual(report["modified_files"], ["docs/plan.md"])
                self.assertEqual(report["status"], "blocked")
                self.assertEqual(task["agent_runs"][0]["diff_guard"]["changed_files"], ["docs/plan.md"])
                self.assertEqual(
                    task["agent_runs"][0]["diff_guard"]["violations"],
                    [
                        "plan-only run modified docs/plan.md; plan-only may read external context but must not write project files"
                    ],
                )
                self.assertEqual(Path(result["artifacts"]["diff"]).read_text(encoding="utf-8"), "service diff")
            finally:
                orchestrator_module.run_diff_guard_service.snapshot_run_diff_guard = original_snapshot
                orchestrator_module.run_diff_guard_service.observe_run_diff_guard = original_observe


if __name__ == "__main__":
    unittest.main()
