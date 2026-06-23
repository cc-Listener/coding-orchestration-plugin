from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.commands.command_rewriter import HermesCommandRewriter
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


class GatewayChangeContinueFlowTest(unittest.TestCase):
    def test_gateway_change_feedback_replans_without_starting_implementation(self):
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
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，导出订单增加tag字段"),
                gateway=FakeGateway(),
            )
            task_id = orchestrator.auto_plan_started[0][0]
            gateway = FakeGateway()

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding change 需求改成同时支持订单标签和商品标签，需要先分析影响"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertIn("商品标签", task["requirement_summary"])
            self.assertEqual(task["human_decisions"][-1]["type"], "requirement_change")
            self.assertEqual(task["phase"], TaskPhase.PLAN_REVISION.value)
            self.assertIn("需求变更", gateway.messages[-1])
            self.assertIn("变更影响", gateway.messages[-1])

    def test_gateway_change_with_image_adds_media_to_plan_prompt(self):
        class SyncOrchestrator(CodingOrchestrator):
            def _start_background_plan_only(self, task_id, gateway, event):
                self.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            def _start_background_implementation(self, task_id, gateway, event):
                raise AssertionError("change should not start implementation")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            fake_runner = FakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-change-image-session"}\n')
            orchestrator = SyncOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
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
                ),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台订单列表批量绑定商品弹窗优化"),
                gateway=gateway,
            )

            orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding change 需求改成按截图增加变体ID展示\n[Image]",
                    media_urls=["https://example.com/variant-preview.png"],
                    media_types=["image/png"],
                ),
                gateway=gateway,
            )

            task = ledger.list_recent_tasks(limit=1)[0]
            prompt = fake_runner.calls[-1]["prompt_at_start"]
            self.assertEqual(task["human_decisions"][-1]["type"], "requirement_change")
            self.assertEqual(task["human_decisions"][-1]["media"][0]["url"], "https://example.com/variant-preview.png")
            self.assertIn("图片附件", prompt)
            self.assertIn("media_type=image/png", prompt)
            self.assertIn("https://example.com/variant-preview.png", prompt)
            self.assertIn("请根据上述图片附件理解用户提到的截图样式", prompt)

    def test_gateway_continue_command_records_runtime_feedback(self):
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
                FakeGatewayEvent("/coding task BPS运营后台有个需求，导出订单增加tag字段"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]
            ledger.update_status(task_id, TaskStatus.RUNNING.value)

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding continue order_tags后端是string，在源分支源session上做修改"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(task["human_decisions"][-1]["type"], "runtime_feedback")
            self.assertIn("order_tags后端是string", task["requirement_summary"])
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertIn("任务正在运行，已记录本次反馈", gateway.messages[-1])

    def test_gateway_continue_command_restarts_failed_plan_only(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

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
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner(status="failed")),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task 订单系统有个需求，新增发货状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]
            orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding continue 补充一下，只处理发货失败状态"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")
            self.assertIn("重新整理计划", gateway.messages[-1])
