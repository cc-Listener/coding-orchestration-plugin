from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, ArtifactSet, RunMode, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration import run_orchestration_service
from coding_orchestration.run_dispatch_service import dispatch_run
from coding_orchestration.runners.base import RunResult
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


def _artifact_set(run_dir: Path) -> ArtifactSet:
    return ArtifactSet(
        run_dir=run_dir,
        input_prompt=run_dir / "input-prompt.md",
        manifest=run_dir / "run-manifest.json",
        stdout=run_dir / "stdout.log",
        stderr=run_dir / "stderr.log",
        events=run_dir / "events.jsonl",
        report=run_dir / "report.json",
        summary=run_dir / "summary.md",
        diff=run_dir / "diff.patch",
    )


class DispatchRunner:
    name = "codex_cli"

    def __init__(self, *, raises: Exception | None = None):
        self.raises = raises
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        run_dir = kwargs["run_dir"]
        report = {
            "runner": self.name,
            "mode": kwargs["mode"].value,
            "status": AgentRunStatus.SUCCEEDED.value,
            "summary_markdown": "done",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": [],
        }
        return RunResult(
            status=AgentRunStatus.SUCCEEDED.value,
            exit_code=0,
            artifacts=_artifact_set(run_dir),
            report=report,
        )


class MinimalDiffGuard:
    def snapshot(self, root):
        return {"root": str(root)}

    def changed_files(self, root, before):
        return []

    def find_violations(self, *, changed_files, allowed_paths, forbidden_paths):
        return []

    def write_diff_summary(self, path, changed_files, violations):
        path.write_text("", encoding="utf-8")


class RaisingFakeRunner(FakeRunner):
    def run(self, *, run_id, run_dir, project_path, workspace_path, mode, timeout_seconds):
        self.calls.append(
            {
                "run_id": run_id,
                "run_dir": run_dir,
                "project_path": project_path,
                "workspace_path": workspace_path,
                "mode": mode,
                "timeout_seconds": timeout_seconds,
            }
        )
        raise RuntimeError("runner exploded")


class RunDispatchServiceTest(unittest.TestCase):
    def test_dispatch_run_uses_checkpoint_failure_result_without_starting_runner(self):
        runner = DispatchRunner()
        checkpoint_results = []

        def checkpoint_failed_result(**kwargs):
            checkpoint_results.append(kwargs)
            return RunResult(
                status=AgentRunStatus.BLOCKED.value,
                exit_code=None,
                artifacts=_artifact_set(kwargs["run_dir"]),
                report={"status": AgentRunStatus.BLOCKED.value},
            )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()

            result = dispatch_run(
                runner=runner,
                run_id="run_1",
                run_dir=run_dir,
                project_path=Path(tmp) / "project",
                workspace_path=Path(tmp) / "workspace",
                mode=RunMode.QA,
                timeout_seconds=30,
                checkpoint={"status": "failed", "reason": "dirty"},
                checkpoint_failed_callback=lambda checkpoint: True,
                checkpoint_failed_result_callback=checkpoint_failed_result,
                runner_failed_result_callback=lambda **kwargs: None,
            )

            self.assertEqual(result.status, AgentRunStatus.BLOCKED.value)
            self.assertEqual(runner.calls, [])
            self.assertEqual(checkpoint_results[0]["runner_name"], "codex_cli")
            self.assertEqual(checkpoint_results[0]["mode"], RunMode.QA)
            self.assertEqual(checkpoint_results[0]["checkpoint"], {"status": "failed", "reason": "dirty"})

    def test_dispatch_run_calls_runner_with_original_run_context(self):
        runner = DispatchRunner()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            project_path = Path(tmp) / "project"
            workspace_path = Path(tmp) / "workspace"
            run_dir.mkdir()

            result = dispatch_run(
                runner=runner,
                run_id="run_2",
                run_dir=run_dir,
                project_path=project_path,
                workspace_path=workspace_path,
                mode=RunMode.IMPLEMENTATION,
                timeout_seconds=45,
                checkpoint=None,
                checkpoint_failed_callback=lambda checkpoint: False,
                checkpoint_failed_result_callback=lambda **kwargs: None,
                runner_failed_result_callback=lambda **kwargs: None,
            )

            self.assertEqual(result.status, AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(
                runner.calls,
                [
                    {
                        "run_id": "run_2",
                        "run_dir": run_dir,
                        "project_path": project_path,
                        "workspace_path": workspace_path,
                        "mode": RunMode.IMPLEMENTATION,
                        "timeout_seconds": 45,
                    }
                ],
            )

    def test_dispatch_run_converts_runner_exception_to_failed_result(self):
        runner = DispatchRunner(raises=RuntimeError("runner exploded"))
        failures = []

        def runner_failed_result(**kwargs):
            failures.append(kwargs)
            return RunResult(
                status=AgentRunStatus.RUNNER_FAILED.value,
                exit_code=None,
                artifacts=_artifact_set(kwargs["run_dir"]),
                report={"status": AgentRunStatus.RUNNER_FAILED.value},
            )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()

            result = dispatch_run(
                runner=runner,
                run_id="run_3",
                run_dir=run_dir,
                project_path=Path(tmp) / "project",
                workspace_path=Path(tmp) / "workspace",
                mode=RunMode.PLAN_ONLY,
                timeout_seconds=15,
                checkpoint=None,
                checkpoint_failed_callback=lambda checkpoint: False,
                checkpoint_failed_result_callback=lambda **kwargs: None,
                runner_failed_result_callback=runner_failed_result,
            )

            self.assertEqual(result.status, AgentRunStatus.RUNNER_FAILED.value)
            self.assertEqual(failures[0]["runner_name"], "codex_cli")
            self.assertEqual(failures[0]["mode"], RunMode.PLAN_ONLY)
            self.assertIsInstance(failures[0]["error"], RuntimeError)

    def test_start_run_delegates_checkpoint_and_runner_execution_to_dispatch_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_dispatch_service"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
                requirement_summary="生成订单筛选计划",
                project_path=str(project),
                status=TaskStatus.NEW.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(runner),
                diff_guard=MinimalDiffGuard(),
            )
            calls = []
            original_dispatch = orchestrator_module.run_dispatch_service.dispatch_run

            def fake_dispatch_run(**kwargs):
                calls.append(kwargs)
                run_dir = kwargs["run_dir"]
                artifacts = _artifact_set(run_dir)
                report = {
                    "runner": kwargs["runner"].name,
                    "mode": kwargs["mode"].value,
                    "status": AgentRunStatus.SUCCEEDED.value,
                    "summary_markdown": "计划完成",
                    "modified_files": [],
                    "test_commands": [],
                    "test_results": [],
                    "risks": [],
                    "verification_limitations": [],
                    "human_required": False,
                    "next_actions": [],
                }
                artifacts.stdout.write_text("", encoding="utf-8")
                artifacts.stderr.write_text("", encoding="utf-8")
                artifacts.summary.write_text("计划完成", encoding="utf-8")
                artifacts.report.write_text(json.dumps(report), encoding="utf-8")
                return RunResult(
                    status=AgentRunStatus.SUCCEEDED.value,
                    exit_code=0,
                    artifacts=artifacts,
                    report=report,
                )

            try:
                orchestrator_module.run_dispatch_service.dispatch_run = fake_dispatch_run

                result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

                self.assertEqual(len(calls), 1)
                self.assertIs(calls[0]["runner"], runner)
                self.assertEqual(calls[0]["run_id"], result["run_id"])
                self.assertEqual(calls[0]["run_dir"].resolve(), Path(result["artifacts"]["run_dir"]).resolve())
                self.assertEqual(calls[0]["project_path"].resolve(), project.resolve())
                self.assertIsNone(calls[0]["workspace_path"])
                self.assertEqual(calls[0]["mode"], RunMode.PLAN_ONLY)
                self.assertEqual(calls[0]["timeout_seconds"], 5)
                self.assertIsNone(calls[0]["checkpoint"])
                self.assertIs(
                    calls[0]["checkpoint_failed_callback"],
                    run_orchestration_service.run_checkpoint_failed,
                )
                self.assertIs(calls[0]["checkpoint_failed_result_callback"].__self__, orchestrator)
                self.assertEqual(
                    calls[0]["checkpoint_failed_result_callback"].__name__,
                    "_checkpoint_failed_result",
                )
                self.assertIs(calls[0]["runner_failed_result_callback"].__self__, orchestrator)
                self.assertEqual(
                    calls[0]["runner_failed_result_callback"].__name__,
                    "_runner_failed_result",
                )
                self.assertEqual(runner.calls, [])
                self.assertEqual(result["status"], AgentRunStatus.SUCCEEDED.value)
            finally:
                orchestrator_module.run_dispatch_service.dispatch_run = original_dispatch

    def test_start_run_converts_runner_exception_to_structured_runner_failed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_dispatch_exception"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
                requirement_summary="生成订单筛选计划",
                project_path=str(project),
                status=TaskStatus.NEW.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            runner = RaisingFakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(runner),
                diff_guard=MinimalDiffGuard(),
            )

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            task = ledger.get_task(task_id)
            report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(result["status"], AgentRunStatus.RUNNER_FAILED.value)
            self.assertEqual(result["task_status"], TaskStatus.FAILED.value)
            self.assertEqual(task["agent_runs"][-1]["status"], AgentRunStatus.RUNNER_FAILED.value)
            self.assertEqual(report["status"], AgentRunStatus.RUNNER_FAILED.value)
            self.assertEqual(report["failure_type"], "runner_failed")
            self.assertEqual(report["verification_limitations"][0]["reason"], "runner_exception")
            self.assertIn("runner exploded", report["summary_markdown"])


if __name__ == "__main__":
    unittest.main()
