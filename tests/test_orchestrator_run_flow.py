from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.command_rewriter import HermesCommandRewriter
from coding_orchestration.models import AgentRunStatus, ArtifactSet, RunMode, TaskKind, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_knowledge_resolver import ProjectKnowledgeResolver
from coding_orchestration.project.project_workitem_binding import ProjectWorkitemIdentity
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.runners.base import RunResult
from tests.orchestrator_flow_fixtures import (
    AsyncFailingGateway,
    ExplodingDispatchTool,
    ExplodingFeishuProjectReader,
    FakeBackgroundQueuedRunner,
    FakeCommandRewriter,
    FakeDispatchTool,
    FakeGateway,
    FakeGatewayEvent,
    FakeRouter,
    FakeRunner,
    MainFlowRunner,
    RecordingCodingOrchestrator,
    _rewrite_response,
    _task_id_from_message,
    _write_workflow,
)


class OrchestratorRunFlowTest(unittest.TestCase):
    def test_gateway_standard_task_flow_reaches_done(self):
        class SyncBackgroundOrchestrator(CodingOrchestrator):
            def _start_background_plan_only(self, task_id, gateway, event):
                self._run_plan_only_and_notify(task_id, gateway, event, loop=None)

            def _start_background_implementation(self, task_id, gateway, event):
                self._run_implementation_and_notify(task_id, gateway, event, loop=None)

            def _start_background_merge_test(self, task_id, gateway, event):
                self._run_merge_test_and_notify(task_id, gateway, event, loop=None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            runner = MainFlowRunner()
            orchestrator = SyncBackgroundOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
                    ProjectRegistry(
                        [
                            {
                                "name": "order-system",
                                "aliases": ["订单系统"],
                                "path": str(project),
                                "keywords": ["订单", "状态筛选"],
                            }
                        ]
                    )
                ),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(runner),
            )
            gateway = FakeGateway()

            created = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task 订单系统订单列表新增状态筛选"),
                gateway=gateway,
            )
            task_id = _task_id_from_message(gateway.messages[0])
            task_after_plan = ledger.get_task(task_id)
            implemented = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding implement {task_id}"),
                gateway=gateway,
            )
            merged = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding merge-test {task_id}"),
                gateway=gateway,
            )
            completed = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding complete {task_id}"),
                gateway=gateway,
            )
            task = ledger.get_task(task_id)
            modes = [call["mode"] for call in runner.calls]

            self.assertEqual(created["reason"], "handled_by_coding_orchestration")
            self.assertEqual(implemented["reason"], "handled_by_coding_orchestration")
            self.assertEqual(merged["reason"], "handled_by_coding_orchestration")
            self.assertEqual(completed["reason"], "handled_by_coding_orchestration")
            self.assertEqual(task_after_plan["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task_after_plan["phase"], TaskPhase.PLAN_READY.value)
            self.assertEqual(task["status"], TaskStatus.DONE.value)
            self.assertEqual(task["phase"], TaskPhase.DONE.value)
            self.assertEqual(modes, [RunMode.PLAN_ONLY, RunMode.IMPLEMENTATION, RunMode.MERGE_TEST])
            self.assertEqual(task["agent_runs"][-1]["mode"], RunMode.MERGE_TEST.value)
            self.assertEqual(task["merge_records"][-1]["type"], "merge_test_run")
            self.assertEqual(task["human_decisions"][-1]["type"], "task_completed")
            self.assertIn("已记录新任务", gateway.messages[0])
            self.assertTrue(any("计划已生成" in message for message in gateway.messages))
            self.assertTrue(any("实现已完成" in message for message in gateway.messages))
            self.assertTrue(any("/coding complete" in message for message in gateway.messages))

    def test_transition_task_status_updates_ledger_and_kanban_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="需求",
                project_path=str(root),
                status=TaskStatus.RUNNING.value,
                phase=TaskPhase.PLANNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={"kanban_task_id": "kb_1"},
            )
            dispatch_tool = FakeDispatchTool()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            orchestrator.set_dispatch_tool(dispatch_tool)

            result = orchestrator._transition_task_status(
                "task_1",
                TaskStatus.RUNNING,
                phase=TaskPhase.IMPLEMENTING,
                reason="run started",
            )

            task = ledger.get_task("task_1")
            self.assertTrue(result["ok"])
            self.assertEqual(task["status"], TaskStatus.RUNNING.value)
            self.assertEqual(task["phase"], TaskPhase.IMPLEMENTING.value)
            self.assertEqual(dispatch_tool.calls[0]["name"], "kanban_heartbeat")
            self.assertEqual(task["task_session"]["kanban_sync"]["status"], "ok")
            self.assertEqual(task["task_session"]["kanban_sync"]["task_status_display"], "运行中(running)")

    def test_transition_task_status_keeps_primary_status_when_kanban_sync_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="需求",
                project_path=str(root),
                status=TaskStatus.RUNNING.value,
                phase=TaskPhase.PLANNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={"kanban_task_id": "kb_1"},
            )
            dispatch_tool = ExplodingDispatchTool()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            orchestrator.set_dispatch_tool(dispatch_tool)

            result = orchestrator._transition_task_status(
                "task_1",
                TaskStatus.RUNNING,
                phase=TaskPhase.IMPLEMENTING,
                reason="run started",
            )

            task = ledger.get_task("task_1")
            self.assertTrue(result["ok"])
            self.assertEqual(task["status"], TaskStatus.RUNNING.value)
            self.assertNotEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["task_session"]["kanban_sync"]["status"], "failed")
            self.assertIn("kanban_sync_failed", task["task_session"]["kanban_sync"]["reason"])
