import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.run.services.run_summary_writeback_service import (
    write_completed_run_summary,
    write_reconciled_run_summary,
)
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


class RunSummaryWritebackServiceTest(unittest.TestCase):
    def test_write_completed_run_summary_calls_writer_callback_with_payload_contract(self):
        calls = []
        report = {"summary_markdown": "计划完成", "status": AgentRunStatus.SUCCEEDED.value}

        def fake_writer(**kwargs):
            calls.append(kwargs)
            return {"ref": "llm-wiki://task_1/run_1"}

        result = write_completed_run_summary(
            task_id="task_1",
            run_id="run_1",
            runner="codex_cli",
            project_name="orders-admin",
            report=report,
            summary="计划完成",
            write_summary_callback=fake_writer,
        )
        report["status"] = "mutated"

        self.assertEqual(result, {"ref": "llm-wiki://task_1/run_1"})
        self.assertEqual(
            calls,
            [
                {
                    "task_id": "task_1",
                    "run_id": "run_1",
                    "runner": "codex_cli",
                    "project": "orders-admin",
                    "report": {"summary_markdown": "计划完成", "status": AgentRunStatus.SUCCEEDED.value},
                    "summary": "计划完成",
                }
            ],
        )

    def test_write_reconciled_run_summary_calls_writer_callback_with_reconciled_context(self):
        calls = []

        def fake_writer(**kwargs):
            calls.append(kwargs)
            return {"ref": "llm-wiki://task_2/run_2"}

        result = write_reconciled_run_summary(
            task_id="task_2",
            run_id="run_2",
            task={"source": {"project_name": "source-project"}},
            session={"project_name": "session-project"},
            merged_run={"runner": "codex_cli"},
            report={"summary_markdown": "后台完成"},
            summary="后台完成",
            write_summary_callback=fake_writer,
        )

        self.assertEqual(result, {"ref": "llm-wiki://task_2/run_2"})
        self.assertEqual(
            calls,
            [
                {
                    "task_id": "task_2",
                    "run_id": "run_2",
                    "runner": "codex_cli",
                    "project": "session-project",
                    "report": {"summary_markdown": "后台完成"},
                    "summary": "后台完成",
                }
            ],
        )

    def test_start_run_delegates_completed_summary_writeback_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_completed_summary"
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
            )
            calls = []
            original = orchestrator_module.run_summary_writeback_service.write_completed_run_summary

            def fake_write_completed_run_summary(**kwargs):
                calls.append(kwargs)
                return {"ref": "from_service"}

            try:
                orchestrator_module.run_summary_writeback_service.write_completed_run_summary = (
                    fake_write_completed_run_summary
                )

                result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

                self.assertEqual(result["run_id"], calls[0]["run_id"])
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["task_id"], task_id)
                self.assertEqual(calls[0]["runner"], "codex_cli")
                self.assertEqual(calls[0]["project_name"], "orders")
                self.assertEqual(calls[0]["summary"], "计划完成")
                self.assertTrue(callable(calls[0]["write_summary_callback"]))
            finally:
                orchestrator_module.run_summary_writeback_service.write_completed_run_summary = original

    def test_reconcile_completed_active_run_delegates_summary_writeback_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "task_reconcile_summary" / "run_done"
            run_dir.mkdir(parents=True)
            report_path = run_dir / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": AgentRunStatus.SUCCEEDED.value,
                        "mode": RunMode.PLAN_ONLY.value,
                        "summary_markdown": "后台计划完成",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "summary.md").write_text("后台计划完成", encoding="utf-8")
            (run_dir / "stdout.log").write_text("{}", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            (run_dir / "diff.patch").write_text("", encoding="utf-8")
            artifact = {
                "run_dir": str(run_dir),
                "input_prompt": str(run_dir / "input-prompt.md"),
                "manifest": str(run_dir / "run-manifest.json"),
                "stdout": str(run_dir / "stdout.log"),
                "stderr": str(run_dir / "stderr.log"),
                "events": str(run_dir / "events.jsonl"),
                "report": str(report_path),
                "summary": str(run_dir / "summary.md"),
                "diff": str(run_dir / "diff.patch"),
            }
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_reconcile_summary"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders-source"},
                requirement_summary="订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLANNING.value,
                task_session={
                    "project_name": "orders-session",
                    "runner": {
                        "provider": "codex_cli",
                        "active_run_id": "run_done",
                        "active_mode": RunMode.PLAN_ONLY.value,
                    },
                },
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_done",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": AgentRunStatus.QUEUED.value,
                    "artifact": artifact,
                    "diff_guard": {"changed_files": [], "violations": []},
                },
            )
            ledger.append_artifact(task_id, artifact)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            calls = []
            original = orchestrator_module.run_summary_writeback_service.write_reconciled_run_summary

            def fake_write_reconciled_run_summary(**kwargs):
                calls.append(kwargs)
                return {"ref": "from_service"}

            try:
                orchestrator_module.run_summary_writeback_service.write_reconciled_run_summary = (
                    fake_write_reconciled_run_summary
                )

                result = orchestrator._reconcile_completed_active_run(task_id)

                self.assertEqual(result["run_id"], "run_done")
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["task_id"], task_id)
                self.assertEqual(calls[0]["run_id"], "run_done")
                self.assertEqual(calls[0]["session"]["project_name"], "orders-session")
                self.assertEqual(calls[0]["summary"], "后台计划完成")
                self.assertTrue(callable(calls[0]["write_summary_callback"]))
            finally:
                orchestrator_module.run_summary_writeback_service.write_reconciled_run_summary = original


if __name__ == "__main__":
    unittest.main()
