import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import RunMode, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import (
    FakeCommandRewriter,
    FakeGateway,
    FakeGatewayEvent,
    FakeRouter,
    FakeRunner,
    RecordingCodingOrchestrator,
    _rewrite_response,
    _write_workflow,
)


class CancelRestoreFlowTest(unittest.TestCase):
    def test_gateway_pending_action_confirmation_rejects_cancelled_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="cancelled",
                project_path=str(project),
                status=TaskStatus.CANCELLED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.CANCELLED.value,
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response("/coding merge-test task_1", intent="merge_test", confidence=0.99)
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()
            event = FakeGatewayEvent("进入coding")

            orchestrator.handle_gateway_event(event, gateway=gateway)
            orchestrator._store_pending_action_for_event(
                event,
                task_id="task_1",
                action="merge_test_retry",
                command_text="/coding merge-test task_1",
                reason="历史待确认动作",
                mode=RunMode.MERGE_TEST.value,
            )
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("确定"), gateway=gateway)

            self.assertEqual(result["reason"], "coding_pending_action_cancelled_task")
            self.assertEqual(rewriter.calls, [])
            self.assertEqual(orchestrator.auto_merge_test_started, [])
            self.assertIn("已取消，不能继续操作", gateway.messages[-1])

    def test_gateway_coding_mode_natural_language_cancel_rewrite_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_cancel",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="临时任务",
                project_path=str(root),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response(
                        "/coding cancel task_cancel",
                        intent="cancel",
                        confidence=0.98,
                        risk_level="destructive",
                        needs_confirmation=True,
                        task_id="task_cancel",
                    )
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("取消 task_cancel"), gateway=gateway)

            self.assertEqual(result["reason"], "coding_rewrite_confirmation")
            self.assertEqual(ledger.get_task("task_cancel")["status"], TaskStatus.PLANNED.value)
            self.assertIn("/coding cancel task_cancel", gateway.messages[-1])

            confirmed = orchestrator.handle_gateway_event(FakeGatewayEvent("确认"), gateway=gateway)

            self.assertEqual(confirmed["reason"], "coding_rewrite_confirmed")
            self.assertEqual(ledger.get_task("task_cancel")["status"], TaskStatus.CANCELLED.value)
            self.assertIn("已标记取消：task_cancel", gateway.messages[-1])

    def test_cancelled_active_task_rejects_continue_change_and_bugfix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="cancelled",
                project_path=str(project),
                status=TaskStatus.CANCELLED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.CANCELLED.value,
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_1"), gateway=gateway)

            continue_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding continue 补充"), gateway=gateway)
            change_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding change 改需求"), gateway=gateway)
            bugfix_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding bugfix 修一下"), gateway=gateway)

            self.assertEqual(continue_result["action"], "skip")
            self.assertEqual(change_result["action"], "skip")
            self.assertEqual(bugfix_result["action"], "skip")
            self.assertEqual(orchestrator.auto_plan_started, [])
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertTrue(all("已取消，不能继续操作" in message for message in gateway.messages[-3:]))

    def test_cancelled_task_rejects_runner_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="cancelled",
                project_path=str(project),
                status=TaskStatus.CANCELLED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.CANCELLED.value,
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            run_message = orchestrator.command_coding_run("task_1")
            implement_message = orchestrator.command_coding_implement("task_1")
            prepare_message = orchestrator.command_prepare_merge_test("task_1")
            merge_message = orchestrator.command_coding_merge_test("task_1")

            self.assertIn("已取消，不能继续操作", run_message)
            self.assertIn("已取消，不能继续操作", implement_message)
            self.assertIn("已取消，不能继续操作", prepare_message)
            self.assertIn("已取消，不能继续操作", merge_message)
            self.assertEqual(fake_runner.calls, [])

    def test_restore_cancelled_task_recovers_latest_actionable_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="cancelled",
                project_path=str(project),
                status=TaskStatus.CANCELLED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.CANCELLED.value,
                task_session={"runner": {"active_run_id": "run_stale", "active_mode": "implementation"}},
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_merge",
                    "runner": "codex_cli",
                    "mode": RunMode.MERGE_TEST.value,
                    "status": "completed_unstructured",
                    "artifact": {},
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_restore("task_1")
            task = ledger.get_task("task_1")

            self.assertIn("已恢复误取消", message)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertIsNone((task["task_session"]["runner"]).get("active_run_id"))
            self.assertEqual(task["human_decisions"][-1]["type"], "task_restored")

    def test_restore_cancelled_task_keeps_unstructured_implementation_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="cancelled",
                project_path=str(project),
                status=TaskStatus.CANCELLED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.CANCELLED.value,
                task_session={"runner": {"active_run_id": "run_stale", "active_mode": "implementation"}},
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": "completed_unstructured",
                    "structured": False,
                    "artifact": {},
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_restore("task_1")
            task = ledger.get_task("task_1")

            self.assertIn("已恢复误取消", message)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["phase"], TaskPhase.BLOCKED.value)
            self.assertIn("未提供完整结构化完成证据", message)
            self.assertIsNone((task["task_session"]["runner"]).get("active_run_id"))

    def test_restore_rejects_task_that_is_not_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="planned",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_restore("task_1")

            self.assertIn("不需要恢复", message)
            self.assertEqual(ledger.get_task("task_1")["status"], TaskStatus.PLANNED.value)

    def test_start_run_rejects_cancelled_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="cancelled",
                project_path=str(project),
                status=TaskStatus.CANCELLED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.CANCELLED.value,
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            with self.assertRaisesRegex(ValueError, "cancelled"):
                orchestrator.start_run("task_1", mode=RunMode.PLAN_ONLY)
            self.assertEqual(fake_runner.calls, [])

    def test_cancel_done_task_does_not_bypass_state_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_done",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="已经完成的任务",
                project_path=str(project),
                status=TaskStatus.DONE.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.DONE.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_cancel("task_done")
            task = ledger.get_task("task_done")

            self.assertIn("不能取消", message)
            self.assertEqual(task["status"], TaskStatus.DONE.value)
            self.assertEqual(task["phase"], TaskPhase.DONE.value)


if __name__ == "__main__":
    unittest.main()
