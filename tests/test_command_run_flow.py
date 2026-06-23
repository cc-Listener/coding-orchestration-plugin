from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import (
    FakeGateway,
    FakeGatewayEvent,
    FakeRouter,
    FakeRunner,
    RecordingCodingOrchestrator,
    _task_id_from_message,
    _write_workflow,
)


class CommandRunFlowTest(unittest.TestCase):
    def test_gateway_coding_run_replies_immediately_and_starts_background_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_run",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="重新规划订单筛选",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            fake_runner = FakeRunner()
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            gateway = FakeGateway()
            event = FakeGatewayEvent("/coding run task_run")

            result = orchestrator.handle_gateway_event(event, gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertIn("[task_run] 已开始整理计划。", gateway.messages[-1])
            self.assertIn("完成后会自动回传结果", gateway.messages[-1])
            self.assertEqual(orchestrator.auto_plan_started, [("task_run", gateway, event)])
            self.assertEqual(fake_runner.calls, [])
    def test_gateway_coding_run_does_not_start_duplicate_when_task_is_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_run",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="重新规划订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLANNING.value,
                task_session={
                    "runner": {
                        "active_run_id": "run_active",
                        "active_mode": RunMode.PLAN_ONLY.value,
                    }
                },
            )
            fake_runner = FakeRunner()
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding run task_run"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertIn("当前已有执行正在进行", gateway.messages[-1])
            self.assertIn("当前执行：run_active", gateway.messages[-1])
            self.assertEqual(orchestrator.auto_plan_started, [])
            self.assertEqual(fake_runner.calls, [])
    def test_command_coding_run_starts_plan_only_for_existing_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "order-system",
                            "aliases": ["订单系统"],
                            "path": str(project),
                            "keywords": ["发货"],
                        }
                    ]
                )
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            task_id = _task_id_from_message(
                orchestrator.command_coding_task("--project 订单系统 修复发货失败")
            )

            message = orchestrator.command_coding_run(task_id)

            self.assertIn("计划已生成", message)
            self.assertIn("请人工确认计划完整度和正确性", message)
            self.assertEqual(fake_runner.calls[0]["mode"], RunMode.PLAN_ONLY)
    def test_command_coding_implement_requires_plan_ready_then_starts_implementation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "order-system",
                            "aliases": ["订单系统"],
                            "path": str(project),
                            "keywords": ["发货"],
                        }
                    ]
                )
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            task_id = _task_id_from_message(
                orchestrator.command_coding_task("--project 订单系统 修复发货失败")
            )

            blocked = orchestrator.command_coding_implement(task_id)
            orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            message = orchestrator.command_coding_implement(task_id)

            self.assertIn("必须先完成计划", blocked)
            self.assertIn("实现已完成", message)
            self.assertIn("/coding merge-test", message)
            self.assertEqual(fake_runner.calls[0]["mode"], RunMode.PLAN_ONLY)
            self.assertEqual(fake_runner.calls[1]["mode"], RunMode.IMPLEMENTATION)
    def test_command_coding_implement_can_retry_after_blocked_implementation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_retry",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="修复订单页",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[
                    {
                        "type": "implementation_confirmed",
                        "text": "开始实现",
                    }
                ],
                phase=TaskPhase.BLOCKED.value,
            )
            ledger.append_agent_run(
                "task_retry",
                {
                    "run_id": "run_blocked",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {},
                },
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

            message = orchestrator.command_coding_implement("task_retry")

            self.assertIn("实现已完成", message)
            self.assertEqual(fake_runner.calls[0]["mode"], RunMode.IMPLEMENTATION)
    def test_command_coding_run_rejects_done_task_without_stale_active_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
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
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_run("task_done")
            task = ledger.get_task("task_done")

            self.assertIn("不能启动", message)
            self.assertEqual(task["status"], TaskStatus.DONE.value)
            self.assertEqual(fake_runner.calls, [])
            self.assertFalse(((task.get("task_session") or {}).get("runner") or {}).get("active_run_id"))
    def test_background_failure_does_not_override_done_task(self):
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

            orchestrator._mark_background_run_failed("task_done", RuntimeError("late failure"), mode=RunMode.MERGE_TEST)
            task = ledger.get_task("task_done")

            self.assertEqual(task["status"], TaskStatus.DONE.value)
            self.assertEqual(task["phase"], TaskPhase.DONE.value)
