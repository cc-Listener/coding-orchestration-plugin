from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_orchestration.command_rewriter import HermesCommandRewriter
from coding_orchestration import gateway_rewrite_presenter
from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_knowledge_resolver import ProjectKnowledgeResolver
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import (
    ExplodingFeishuProjectReader,
    FakeCommandRewriter,
    FakeGateway,
    FakeGatewayEvent,
    FakeRouter,
    FakeRunner,
    RecordingCodingOrchestrator,
    _rewrite_response,
    _task_id_from_message,
    _write_workflow,
)


class GatewayRewriteFlowTest(unittest.TestCase):
    def test_command_rewriter_prompt_lists_restore_and_hermes_fallback(self):
        prompt = HermesCommandRewriter._system_prompt()

        self.assertIn("/coding project list", prompt)
        self.assertIn("/coding project init <project_path_or_name>", prompt)
        self.assertIn("/coding project use <project_name>", prompt)
        self.assertIn("/coding restore <task_id>", prompt)
        self.assertIn("active_project", prompt)
        self.assertIn("intent=unknown", prompt)
        self.assertIn("Hermes 主 agent", prompt)
    def test_low_confidence_rewrite_needs_human_message_uses_user_language(self):
        message = gateway_rewrite_presenter.format_rewrite_needs_human_confirmation_message(
            "帮我处理一下",
            {"canonical_command": None, "confidence": 0.12, "reason": "缺少项目和任务目标。"},
            "缺少项目",
        )

        self.assertIn("我还不能确定要执行哪个 coding 动作", message)
        self.assertIn("请补充项目或直接发送 /coding task", message)
        self.assertNotIn("置信度", message)
        self.assertNotIn("LLM 理由", message)
    def test_low_confidence_rewrite_needs_human_message_sanitizes_internal_rejection(self):
        message = gateway_rewrite_presenter.format_rewrite_needs_human_confirmation_message(
            "帮我处理一下",
            {"canonical_command": None, "confidence": 0.12, "reason": "缺少项目和任务目标。"},
            "置信度 0.12 低于阈值 0.85。",
        )

        self.assertIn("我还不能确定要执行哪个 coding 动作", message)
        self.assertIn("需要补充：请补充项目、任务目标或要执行的动作。", message)
        self.assertNotIn("置信度", message)
        self.assertNotIn("阈值", message)
    def test_gateway_natural_language_does_not_enter_plugin(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            rewriter = FakeCommandRewriter(_rewrite_response("/coding task 订单系统有个需求，新增发货状态筛选"))
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
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("订单系统有个需求，新增发货状态筛选"),
                gateway=gateway,
            )

            self.assertIsNone(result)
            self.assertEqual(orchestrator.auto_started, [])
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])
            self.assertEqual(gateway.messages, [])
            self.assertEqual(rewriter.calls, [])
    def test_gateway_coding_mode_high_confidence_natural_language_creates_task(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            rewriter = FakeCommandRewriter(_rewrite_response("/coding task 订单系统新增发货状态筛选"))
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
                    ProjectRegistry(
                        [
                            {
                                "name": "order-system",
                                "aliases": ["订单系统"],
                                "path": str(project),
                                "keywords": ["发货", "状态筛选"],
                            }
                        ]
                    )
                ),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            entered = orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("订单系统新增发货状态筛选"),
                gateway=gateway,
            )

            self.assertEqual(entered["action"], "skip")
            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_executed")
            self.assertEqual(len(rewriter.calls), 1)
            self.assertEqual(rewriter.calls[0]["user_text"], "订单系统新增发货状态筛选")
            self.assertTrue(rewriter.calls[0]["coding_mode_enabled"])
            self.assertIn("已进入 coding mode", gateway.messages[-2])
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["source"]["raw_text"], "订单系统新增发货状态筛选")
            self.assertIn("已记录新任务", gateway.messages[-1])
    def test_gateway_coding_mode_project_task_with_feishu_wiki_source_creates_deferred_task(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bestvoy-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            raw_text = (
                "项目名称：商户后台，文件夹名称为 bestvoy-admin。"
                "新增需求：MarketPlace APP 后台模块。"
                "需求来源：https://bestfulfill.feishu.cn/wiki/YNU8wYMwBiJv5AkYQIJcQ4donsh。"
                "目标：按照需求文档 11. Marketplace APP 点实现。"
            )
            rewriter = FakeCommandRewriter(_rewrite_response(f"/coding task {raw_text} --project bestvoy-admin"))
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
                    ProjectRegistry(
                        [
                            {
                                "name": "bestvoy-admin",
                                "aliases": ["商户后台"],
                                "path": str(project),
                            }
                        ]
                    )
                ),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
                feishu_project_reader=ExplodingFeishuProjectReader(),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent(raw_text), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_executed")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task = ledger.get_task(orchestrator.auto_started[0][0])
            self.assertEqual(task["status"], TaskStatus.NEEDS_HUMAN.value)
            self.assertEqual(task["source"]["project_name"], "bestvoy-admin")
            self.assertEqual(Path(task["project_path"]).resolve(), project.resolve())
            source_context = task["source"]["source_context"]
            self.assertEqual(source_context["read_status"], "indexed")
            self.assertEqual(source_context["source_type"], "feishu_wiki")
            self.assertTrue(source_context["codex_resolvable"])
            self.assertEqual(source_context["resolution_owner"], "codex")
            self.assertIn("rtk lark-cli docs +fetch", source_context["lark_cli_command"])
    def test_gateway_coding_mode_low_confidence_natural_language_hands_off_to_hermes(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    None,
                    intent="unknown",
                    confidence=0.42,
                    risk_level="unknown",
                    needs_human_review=True,
                )
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("帮我看一下"), gateway=gateway)

            self.assertEqual(result["action"], "rewrite")
            self.assertEqual(result["reason"], "coding_rewrite_handoff_to_hermes")
            self.assertIn("我还不能确定这句话要创建或操作哪个开发任务", result["text"])
            self.assertIn("原话：帮我看一下", result["text"])
            self.assertIn("可用入口：/coding task --project", result["text"])
            self.assertNotIn("上下文 JSON", result["text"])
            self.assertNotIn("intent", result["text"])
            self.assertNotIn("allowed_commands", result["text"])
            self.assertNotIn("置信度", result["text"])
            self.assertEqual(orchestrator.auto_started, [])
            tasks = ledger.list_recent_tasks(limit=5)
            self.assertEqual(tasks, [])
            self.assertEqual(len(rewriter.calls), 1)
            self.assertNotIn("需要人工二次确认", gateway.messages[-1])
    def test_gateway_coding_mode_unknown_null_rewrite_hands_context_to_hermes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            ledger.create_task(
                task_id="task_active",
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="优化订单列表查询",
                project_path=str(root),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    None,
                    intent="unknown",
                    confidence=0.11,
                    risk_level="unknown",
                    needs_human_review=True,
                )
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_active"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("这个先讨论下"), gateway=gateway)

            self.assertEqual(result["action"], "rewrite")
            self.assertEqual(result["reason"], "coding_rewrite_handoff_to_hermes")
            self.assertIn("没有创建任务，也没有启动执行", result["text"])
            self.assertNotIn("上下文 JSON", result["text"])
            self.assertIn("task_active", result["text"])
            self.assertIn("优化订单列表查询", result["text"])
            self.assertEqual(ledger.get_task("task_active")["status"], TaskStatus.PLANNED.value)
    def test_gateway_coding_mode_low_confidence_handoff_includes_operator_skill_and_project_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            wiki.upsert(
                {
                    "kind": "project_profile",
                    "title": "bps-admin 项目画像",
                    "body": "BPS运营后台 订单列表",
                    "project": "bps-admin",
                    "project_id": "bps-admin",
                    "name": "bps-admin",
                    "aliases": ["BPS运营后台"],
                    "local_paths": [str(project)],
                    "status": "verified",
                },
                options={"dedupe_key": "project:bps-admin"},
            )
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    None,
                    intent="unknown",
                    confidence=0.2,
                    risk_level="unknown",
                    needs_human_review=True,
                )
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding project use bps-admin"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("这个怎么处理"), gateway=gateway)

            self.assertEqual(result["action"], "rewrite")
            self.assertNotIn("上下文 JSON", result["text"])
            self.assertNotIn("recommended_skill", result["text"])
            self.assertNotIn("active_project", result["text"])
            self.assertNotIn("known_projects", result["text"])
            self.assertIn("当前项目：bps-admin", result["text"])
            self.assertIn("bps-admin", result["text"])
    def test_low_confidence_handoff_includes_actionable_next_step_for_failed_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "no-reader-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    None,
                    intent="unknown",
                    confidence=0.2,
                    risk_level="unknown",
                    needs_human_review=True,
                )
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()
            task_id = "task_failed_plan"
            ledger.create_task(
                task_id=task_id,
                source={"type": "feishu_chat", "raw_text": "新增 Marketplace APP 后台模块"},
                requirement_summary="新增 Marketplace APP 后台模块",
                project_path=None,
                status=TaskStatus.FAILED.value,
                phase=TaskPhase.PLAN_REVISION.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )

            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding project init {project}"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding use {task_id}"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("开始启动任务，匹配到这个项目"), gateway=gateway)

            self.assertEqual(result["action"], "rewrite")
            self.assertNotIn("上下文 JSON", result["text"])
            self.assertNotIn('"phase": "plan_revision"', result["text"])
            self.assertIn("当前任务建议下一步", result["text"])
            self.assertIn(f"/coding run {task_id}", result["text"])
