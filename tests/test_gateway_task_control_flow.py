from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.command_rewriter import HermesCommandRewriter
from coding_orchestration.models import AgentRunStatus, ArtifactSet, RunMode, TaskKind, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_knowledge_resolver import ProjectKnowledgeResolver
from coding_orchestration.project_workitem_binding import ProjectWorkitemIdentity
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
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


class GatewayTaskControlFlowTest(unittest.TestCase):
    def test_gateway_confirmation_starts_implementation_after_plan_ready_task(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []
                self.auto_implementation_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

            def _start_background_implementation(self, task_id, gateway, event):
                self.auto_implementation_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["策略列表"],
                        }
                    ]
                )
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            created = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，在策略列表上，新增一个状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]
            orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            task = ledger.get_task(task_id)

            confirmed = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding implement {task_id}"),
                gateway=gateway,
            )

            self.assertEqual(created["action"], "skip")
            self.assertEqual(confirmed["action"], "skip")
            self.assertEqual(task["source"]["gateway_source"]["chat_id"], "chat_1")
            self.assertEqual(task["phase"], "plan_ready")
            self.assertEqual(orchestrator.auto_implementation_started[0][0], task_id)
            self.assertIn("开始实现", gateway.messages[-1])

    def test_gateway_confirmation_before_plan_ready_is_captured_but_does_not_implement(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []
                self.auto_implementation_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

            def _start_background_implementation(self, task_id, gateway, event):
                self.auto_implementation_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["策略列表"],
                        }
                    ]
                )
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，在策略列表上，新增一个状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding implement {task_id}"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(
                task["human_decisions"][-1]["type"],
                "implementation_confirmation_before_plan_ready",
            )
            self.assertIn("必须先完成计划", gateway.messages[-1])

    def test_gateway_simple_ui_task_starts_plan_only_not_keyword_implementation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["订单管理"],
                        }
                    ]
                )
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task 订单管理页面商品标题复制按钮需要复制产品标题，不要复制超链接 --project bps-admin"),
                gateway=gateway,
            )

            task_id = orchestrator.auto_plan_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLANNING.value)
            self.assertIn("已自动开始整理计划", gateway.messages[0])
            self.assertNotIn("implementation 已自动启动", gateway.messages[0])
            self.assertNotIn("plan-only", gateway.messages[0])

    def test_gateway_multi_part_api_skill_task_starts_plan_only_not_implementation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["订单管理", "ordeflow"],
                        }
                    ]
                )
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding task "
                    "订单管理页面 ordeflow 商品标题复制按钮改为复制产品标题；"
                    "修改 bps-admin-api-docs skill 文档地址并做前后端对齐，"
                    "Swagger URL 改为 http://10.15.173.167:6060/api/bps_ops/v1/swagger/doc.json；"
                    "订单管理页面 ordeflow 增加筛选项“平台变体名称”。 "
                    "--project bps-admin"
                ),
                gateway=gateway,
            )

            task_id = orchestrator.auto_plan_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLANNING.value)
            self.assertIn("已自动开始整理计划", gateway.messages[0])

    def test_gateway_use_command_selects_active_task_when_multiple_tasks_share_chat(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["订单列表", "策略列表"],
                        }
                    ]
                )
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，订单列表新增状态筛选"),
                gateway=gateway,
            )
            task_a = orchestrator.auto_plan_started[-1][0]
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，策略列表新增状态筛选"),
                gateway=gateway,
            )
            task_b = orchestrator.auto_plan_started[-1][0]

            selected = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding use {task_a}"),
                gateway=gateway,
            )
            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding continue 列名为tag,order_tags为string[]"),
                gateway=gateway,
            )

            task_a_loaded = ledger.get_task(task_a)
            task_b_loaded = ledger.get_task(task_b)
            self.assertEqual(selected["action"], "skip")
            self.assertEqual(captured["action"], "skip")
            self.assertIn("已切换当前开发任务", gateway.messages[-2])
            self.assertIn("order_tags", task_a_loaded["requirement_summary"])
            self.assertNotIn("order_tags", task_b_loaded["requirement_summary"])

    def test_gateway_delete_command_removes_task_binding_and_artifacts(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["订单列表"],
                        }
                    ]
                )
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，订单列表新增状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]
            self.assertTrue(wiki.find_by_source_task(task_id))
            run_dir = root / "runs" / task_id / "run_1"
            workspace_dir = root / "workspaces" / task_id / "run_1"
            run_dir.mkdir(parents=True)
            workspace_dir.mkdir(parents=True)

            deleted = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding delete {task_id}"),
                gateway=gateway,
            )

            self.assertEqual(deleted["action"], "skip")
            self.assertIsNone(ledger.get_task(task_id))
            self.assertIsNone(ledger.get_active_binding("feishu:chat:chat_1"))
            self.assertEqual(wiki.find_by_source_task(task_id), [])
            self.assertFalse((root / "runs" / task_id).exists())
            self.assertFalse((root / "workspaces" / task_id).exists())
            self.assertIn("已删除开发任务", gateway.messages[-1])

    def test_gateway_continue_command_for_recent_planned_task_replans(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["订单列表"],
                        }
                    ]
                )
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            created = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，订单列表新增状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]

            feedback = (
                "1、目标页面仅为新版 /orderFlow；\n"
                "2、接口的改动，项目内的skill `bps-admin-api-docs`可以去查找\n\n"
                "根据以上反馈再重新去制定计划"
            )
            captured = orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding continue {feedback}"), gateway=gateway)

            task = ledger.get_task(task_id)
            self.assertEqual(created["action"], "skip")
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertIn("/orderFlow", task["requirement_summary"])
            self.assertIn("bps-admin-api-docs", task["requirement_summary"])
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")
            self.assertIn("重新整理计划", gateway.messages[-1])

    def test_gateway_continue_command_accepts_plain_plan_context_note(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["订单列表"],
                        }
                    ]
                )
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，订单列表新增状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding continue 列名为tag,order_tags为string[]"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertIn("order_tags", task["requirement_summary"])
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")
            self.assertIn("重新整理计划", gateway.messages[-1])

