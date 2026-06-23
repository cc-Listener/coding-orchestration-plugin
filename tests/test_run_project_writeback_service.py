import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.run.services.run_project_writeback_service import write_run_project_completion
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


class RunProjectWritebackServiceTest(unittest.TestCase):
    def test_write_run_project_completion_skips_stale_completion_without_callback(self):
        calls = []

        result = write_run_project_completion(
            task_id="task_1",
            mode=RunMode.IMPLEMENTATION,
            run_id="run_1",
            status=AgentRunStatus.SUCCEEDED.value,
            task_status=TaskStatus.READY_FOR_MERGE_TEST,
            report={"summary_markdown": "完成"},
            stale_completion=True,
            writeback_callback=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        self.assertEqual(result, {"ok": False, "status": "skipped_stale_completion"})
        self.assertEqual(calls, [])

    def test_write_run_project_completion_calls_callback_with_payload_contract(self):
        calls = []

        def fake_writeback(task_id, payload, *, mode):
            calls.append({"task_id": task_id, "payload": payload, "mode": mode})
            return {"ok": True, "status": "ok"}

        result = write_run_project_completion(
            task_id="task_2",
            mode=RunMode.QA,
            run_id="run_2",
            status=AgentRunStatus.SUCCEEDED.value,
            task_status=TaskStatus.READY_FOR_MERGE_TEST,
            report={"summary_markdown": "QA 完成"},
            stale_completion=False,
            writeback_callback=fake_writeback,
        )

        self.assertEqual(result, {"ok": True, "status": "ok"})
        self.assertEqual(
            calls,
            [
                {
                    "task_id": "task_2",
                    "mode": RunMode.QA,
                    "payload": {
                        "run_id": "run_2",
                        "status": AgentRunStatus.SUCCEEDED.value,
                        "task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                        "report": {"summary_markdown": "QA 完成"},
                    },
                }
            ],
        )

    def test_start_run_delegates_project_writeback_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_project_writeback"
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
            original = orchestrator_module.run_project_writeback_service.write_run_project_completion

            def fake_write_run_project_completion(**kwargs):
                calls.append(kwargs)
                return {"ok": True, "status": "from_service"}

            try:
                orchestrator_module.run_project_writeback_service.write_run_project_completion = (
                    fake_write_run_project_completion
                )

                result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

                self.assertEqual(result["project_writeback"], {"ok": True, "status": "from_service"})
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["task_id"], task_id)
                self.assertEqual(calls[0]["mode"], RunMode.PLAN_ONLY)
                self.assertEqual(calls[0]["run_id"], result["run_id"])
                self.assertFalse(calls[0]["stale_completion"])
                self.assertTrue(callable(calls[0]["writeback_callback"]))
            finally:
                orchestrator_module.run_project_writeback_service.write_run_project_completion = original


if __name__ == "__main__":
    unittest.main()
