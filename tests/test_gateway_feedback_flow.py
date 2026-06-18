from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
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


class GatewayFeedbackFlowTest(unittest.TestCase):
    def test_gateway_bugfix_feedback_after_review_starts_implementation(self):
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
            task_id = ledger.list_recent_tasks(statuses=[TaskStatus.PLANNED.value], limit=1)[0]["task_id"]
            orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            gateway = FakeGateway()

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding bugfix 这里有问题要更改下，order_tags后端是string，在源分支，源session上做修改"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started[0][0], task_id)
            self.assertIn("order_tags后端是string", task["requirement_summary"])
            self.assertEqual(task["human_decisions"][-1]["type"], "implementation_feedback")
            self.assertIn("开始修复", gateway.messages[-1])

    def test_gateway_bugfix_after_blocked_plan_is_routed_back_to_plan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_blocked_plan"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary=(
                    "订单管理页面 ordeflow 复制按钮改为复制产品标题；"
                    "更新 bps-admin-api-docs skill Swagger 地址；"
                    "新增平台变体名称筛选"
                ),
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_plan_blocked",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {},
                    "diff_guard": {"changed_files": [], "violations": []},
                },
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
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding use {task_id}"), gateway=gateway)

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding bugfix "
                    "Swagger 改为 https://bps-ops-api.bestfulfill.top/api/bps_ops/v1/swagger/doc.json，"
                    "平台变体名称字段是 skus"
                ),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")
            self.assertIn("skus", task["requirement_summary"])
            self.assertIn("上一次计划仍受阻", gateway.messages[-1])
            self.assertIn("不会直接开始实现", gateway.messages[-1])

    def test_gateway_bugfix_plan_supplement_before_implementation_replans(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_plan_supplement"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单列表新增 tag 字段",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_plan_ready",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": AgentRunStatus.SUCCESS.value,
                    "artifact": {},
                    "diff_guard": {"changed_files": [], "violations": []},
                },
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
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding use {task_id}"), gateway=gateway)

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding bugfix 这个不是实现 bugfix，补充 Plan：API 字段 order_tags 是 string[]"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertEqual(task["phase"], TaskPhase.PLAN_REVISION.value)
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")
            self.assertIn("order_tags", task["requirement_summary"])
            self.assertIn("重新整理计划", gateway.messages[-1])

    def test_gateway_bugfix_feedback_reopens_merged_test_task_for_implementation(self):
        class SyncImplementationOrchestrator(CodingOrchestrator):
            def _start_background_implementation(self, task_id, gateway, event):
                self.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            fake_runner = FakeRunner()
            orchestrator = SyncImplementationOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            task_id = "task_merged_bugfix"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary=".gstack 文件不要进 git",
                project_path=str(project),
                status=TaskStatus.MERGED_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.MERGED_TEST.value,
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding use {task_id}"), gateway=gateway)

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding bugfix .gstack 的文件不要放到 git 上，做一个忽略"),
                gateway=gateway,
            )
            task = ledger.get_task(task_id)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.IMPLEMENTATION)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertEqual(task["human_decisions"][-1]["type"], "implementation_feedback")
            self.assertIn("开始修复", gateway.messages[-1])

    def test_gateway_bugfix_with_image_adds_media_to_incremental_prompt(self):
        class SyncOrchestrator(CodingOrchestrator):
            def _start_background_plan_only(self, task_id, gateway, event):
                self.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            def _start_background_implementation(self, task_id, gateway, event):
                self.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            fake_runner = FakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-image-session"}\n')
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
            task_id = ledger.list_recent_tasks(limit=1)[0]["task_id"]

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding bugfix 按截图调整 grouped_items 展示\n[Image]",
                    media_urls=["/Users/xiaojing/.hermes/image_cache/grouped_items.jpg"],
                    media_types=["image/jpeg"],
                ),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            prompt = fake_runner.calls[-1]["prompt_at_start"]
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(task["human_decisions"][-1]["type"], "implementation_feedback")
            self.assertEqual(
                task["human_decisions"][-1]["media"][0]["url"],
                "/Users/xiaojing/.hermes/image_cache/grouped_items.jpg",
            )
            self.assertIn("图片附件", prompt)
            self.assertIn("media_type=image/jpeg", prompt)
            self.assertIn("/Users/xiaojing/.hermes/image_cache/grouped_items.jpg", prompt)
            self.assertIn("请根据上述图片附件理解用户提到的截图样式", prompt)

    def test_gateway_bugfix_with_image_placeholder_without_media_does_not_start_codex(self):
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
            orchestrator = RecordingOrchestrator(
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
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台订单列表批量绑定商品弹窗优化"),
                gateway=gateway,
            )

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding bugfix 按截图调整 grouped_items 展示\n[Image]"),
                gateway=gateway,
            )

            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertIn("未启动 Codex", gateway.messages[-1])
            self.assertIn("图片未捕获", gateway.messages[-1])
            self.assertIn("请重发图片或图片链接", gateway.messages[-1])

