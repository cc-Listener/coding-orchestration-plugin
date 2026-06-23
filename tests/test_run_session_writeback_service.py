import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.run.services.run_session_writeback_service import write_run_session_update
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


class RunSessionWritebackServiceTest(unittest.TestCase):
    def test_write_run_session_update_calls_update_callback_for_non_empty_update(self):
        calls = []
        update = {
            "project_name": "orders",
            "runner": {"provider": "codex_cli", "active_run_id": "run_1"},
        }

        result = write_run_session_update(
            task_id="task_1",
            update=update,
            update_task_session_callback=lambda task_id, payload: calls.append((task_id, payload)),
        )

        self.assertIsNone(result)
        self.assertEqual(calls, [("task_1", update)])

    def test_write_run_session_update_skips_empty_update(self):
        calls = []

        result = write_run_session_update(
            task_id="task_2",
            update={},
            update_task_session_callback=lambda task_id, payload: calls.append((task_id, payload)),
        )

        self.assertIsNone(result)
        self.assertEqual(calls, [])

    def test_start_run_delegates_run_lifecycle_session_updates_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_session_writeback"
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
            original = orchestrator_module.run_session_writeback_service.write_run_session_update

            def fake_write_run_session_update(**kwargs):
                calls.append(kwargs)
                kwargs["update_task_session_callback"](kwargs["task_id"], kwargs["update"])

            try:
                orchestrator_module.run_session_writeback_service.write_run_session_update = (
                    fake_write_run_session_update
                )

                result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

                updates = [call["update"] for call in calls]
                self.assertEqual(result["task_id"], task_id)
                self.assertEqual(len(calls), 3)
                self.assertEqual(
                    updates[0],
                    {
                        "project_name": "orders",
                        "runner": {
                            "provider": "codex_cli",
                            "last_requested_mode": RunMode.PLAN_ONLY.value,
                        },
                    },
                )
                self.assertEqual(
                    updates[1],
                    {
                        "runner": {
                            "active_run_id": result["run_id"],
                            "active_mode": RunMode.PLAN_ONLY.value,
                        },
                    },
                )
                self.assertEqual(updates[2]["runner"]["last_run_id"], result["run_id"])
                self.assertEqual(updates[2]["runner"]["last_run_status"], AgentRunStatus.SUCCEEDED.value)
                self.assertTrue(callable(calls[0]["update_task_session_callback"]))
            finally:
                orchestrator_module.run_session_writeback_service.write_run_session_update = original

    def test_start_run_transition_failure_clears_active_run_via_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_session_cleanup"
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
            original_write = orchestrator_module.run_session_writeback_service.write_run_session_update
            original_transition = orchestrator._transition_task_status

            def fake_write_run_session_update(**kwargs):
                calls.append(kwargs)
                kwargs["update_task_session_callback"](kwargs["task_id"], kwargs["update"])

            def fail_transition(*args, **kwargs):
                raise RuntimeError("transition failed")

            try:
                orchestrator_module.run_session_writeback_service.write_run_session_update = (
                    fake_write_run_session_update
                )
                orchestrator._transition_task_status = fail_transition

                with self.assertRaisesRegex(RuntimeError, "transition failed"):
                    orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

                updates = [call["update"] for call in calls]
                self.assertEqual(
                    updates[-1],
                    {
                        "runner": {
                            "active_run_id": None,
                            "active_mode": None,
                        }
                    },
                )
                self.assertTrue(callable(calls[-1]["update_task_session_callback"]))
            finally:
                orchestrator._transition_task_status = original_transition
                orchestrator_module.run_session_writeback_service.write_run_session_update = original_write

    def test_reconcile_completed_active_run_delegates_runner_session_update_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "task_reconcile_session" / "run_done"
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
            (run_dir / "stdout.log").write_text(
                '{"type":"thread.started","thread_id":"thread_reconciled"}',
                encoding="utf-8",
            )
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
            task_id = "task_reconcile_session"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
                requirement_summary="订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLANNING.value,
                task_session={
                    "runner": {
                        "provider": "codex_cli",
                        "active_run_id": "run_done",
                        "active_mode": RunMode.PLAN_ONLY.value,
                    }
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
            original = orchestrator_module.run_session_writeback_service.write_run_session_update

            def fake_write_run_session_update(**kwargs):
                calls.append(kwargs)
                kwargs["update_task_session_callback"](kwargs["task_id"], kwargs["update"])

            try:
                orchestrator_module.run_session_writeback_service.write_run_session_update = (
                    fake_write_run_session_update
                )

                result = orchestrator._reconcile_completed_active_run(task_id)

                self.assertEqual(result["run_id"], "run_done")
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["task_id"], task_id)
                update = calls[0]["update"]
                self.assertEqual(update["runner"]["last_run_id"], "run_done")
                self.assertEqual(update["runner"]["active_run_id"], None)
                self.assertEqual(update["runner"]["resume_session_id"], "thread_reconciled")
                self.assertIn("reconciled_at", update["runner"])
                self.assertTrue(callable(calls[0]["update_task_session_callback"]))
            finally:
                orchestrator_module.run_session_writeback_service.write_run_session_update = original


if __name__ == "__main__":
    unittest.main()
