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


class GatewayProjectTaskFlowTest(unittest.TestCase):
    def test_coding_task_rejects_blank_or_flag_only_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
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
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            blank = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding task   "), gateway=gateway)
            blank_message = gateway.messages[-1]
            flag_only_message = orchestrator.command_coding_task("  --project 订单系统   ")
            missing_flag_value_message = orchestrator.command_coding_task("  --project   ")
            missing_delete_message = orchestrator.command_coding_delete("")
            missing_use = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use   "), gateway=gateway)
            missing_use_message = gateway.messages[-1]

            self.assertEqual(blank["reason"], "handled_by_coding_orchestration")
            self.assertEqual(missing_use["reason"], "handled_by_coding_orchestration")
            self.assertIn("请提供任务需求", blank_message)
            self.assertIn("请提供任务需求", flag_only_message)
            self.assertIn("--project 缺少参数值", missing_flag_value_message)
            self.assertIn("请提供任务 ID", missing_delete_message)
            self.assertIn("/coding delete <task_id>", missing_delete_message)
            self.assertIn("请提供任务 ID", missing_use_message)
            self.assertIn("/coding use <task_id>", missing_use_message)
            self.assertNotIn("task_xxx", f"{missing_delete_message}\n{missing_use_message}")
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])

    def test_gateway_project_commands_manage_active_project_without_creating_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            init_result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding project init {project}"),
                gateway=gateway,
            )
            status_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding project status"), gateway=gateway)
            list_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding project list"), gateway=gateway)
            clear_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding project clear"), gateway=gateway)
            status_after_clear = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding project status"),
                gateway=gateway,
            )

            self.assertEqual(init_result["action"], "skip")
            self.assertEqual(status_result["action"], "skip")
            self.assertEqual(list_result["action"], "skip")
            self.assertEqual(clear_result["action"], "skip")
            self.assertEqual(status_after_clear["action"], "skip")
            self.assertIn("已初始化项目", gateway.messages[-5])
            self.assertIn("当前项目", gateway.messages[-5])
            self.assertIn("bps-admin", gateway.messages[-4])
            self.assertIn(str(project.resolve()), gateway.messages[-4])
            self.assertIn("初始化质量：", gateway.messages[-4])
            self.assertIn("质量门缺口：", gateway.messages[-4])
            self.assertIn("当前已知项目", gateway.messages[-3])
            self.assertIn("当前", gateway.messages[-3])
            self.assertIn("已清除当前项目", gateway.messages[-2])
            self.assertIn("当前没有绑定项目", gateway.messages[-1])
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])

    def test_active_project_is_used_when_rewrite_creates_task_without_project_flag(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response("/coding task 订单列表新增状态筛选")
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding project init {project}"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("订单列表新增状态筛选"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task = ledger.get_task(orchestrator.auto_started[0][0])
            self.assertEqual(task["source"]["project_name"], "bps-admin")
            self.assertEqual(task["project_path"], str(project.resolve()))
            self.assertEqual(task["source"]["active_project_context"]["name"], "bps-admin")
            self.assertIn("active_project", orchestrator.command_rewriter.calls[0])
            self.assertEqual(orchestrator.command_rewriter.calls[0]["active_project"]["name"], "bps-admin")

    def test_task_creation_resolves_project_folder_mentioned_in_requirement(self):
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
            sibling = root / "known-parent"
            sibling.mkdir()
            _write_workflow(project)
            _write_workflow(sibling)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(
                    ProjectRegistry(
                        [
                            {
                                "name": "known-parent",
                                "path": str(sibling),
                            }
                        ]
                    )
                ),
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
            text = "项目名称：商户后台，文件夹名称为`bestvoy-admin`\n帮我做一个需求：MarketPlace APP后台模块"

            result = orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding task {text}"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task = ledger.get_task(orchestrator.auto_started[0][0])
            self.assertEqual(task["project_path"], str(project.resolve()))
            self.assertEqual(task["source"]["project_name"], "bestvoy-admin")
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertIsNotNone(orchestrator._find_project_profile("商户后台"))

    def test_gateway_run_backfills_missing_task_project_from_active_project(self):
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
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
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
            task_id = "task_needs_project"
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

            result = orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding run {task_id}"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_started[0][0], task_id)
            task = ledger.get_task(task_id)
            self.assertEqual(task["project_path"], str(project.resolve()))
            self.assertEqual(task["source"]["project_name"], "bestvoy-admin")
            self.assertEqual(task["task_session"]["project_name"], "bestvoy-admin")
            decision_types = [item["type"] for item in task["human_decisions"]]
            self.assertIn("project_context_applied_from_active_project", decision_types)

    def test_continue_project_clarification_updates_failed_task_instead_of_plan_feedback(self):
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
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
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
            task_id = "task_missing_project"
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
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding use {task_id}"), gateway=gateway)

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    f"/coding continue 这个task 的项目是商户后台，对应项目 bestvoy-admin，路径 {project}"
                ),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_started[0][0], task_id)
            task = ledger.get_task(task_id)
            self.assertEqual(task["project_path"], str(project.resolve()))
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLANNING.value)
            decision_types = [item["type"] for item in task["human_decisions"]]
            self.assertIn("human_clarification", decision_types)
            self.assertNotIn("plan_feedback", decision_types)

    def test_gateway_event_handles_feishu_escaped_project_slug_and_media(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

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
                            "aliases": ["BPS运营后台", "bps-admin"],
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

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding task 这是bps\\-admin的一个前端需求，主要改动订单列表\n[Image]",
                    media_urls=["/Users/xiaojing/.hermes/image_cache/img_a.jpg"],
                    media_types=["image/jpeg"],
                ),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["source"]["project_name"], "bps-admin")
            self.assertIn("bps-admin", task["requirement_summary"])
            self.assertEqual(
                task["source"]["media"][0]["url"],
                "/Users/xiaojing/.hermes/image_cache/img_a.jpg",
            )
            self.assertEqual(task["llm_wiki_refs"][0]["kind"], "draft_knowledge")
            draft = wiki.read(task["llm_wiki_refs"][0]["id"])
            self.assertIn(
                {
                    "type": "media",
                    "url": "/Users/xiaojing/.hermes/image_cache/img_a.jpg",
                    "media_type": "image/jpeg",
                },
                draft["source_refs"],
            )

    def test_gateway_event_resolves_project_from_llm_wiki_profile_without_registry_entry(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "crm-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            wiki.upsert(
                {
                    "kind": "project_profile",
                    "title": "CRM Admin 项目画像",
                    "body": "CRM后台 客户列表 客户筛选",
                    "project": "crm-admin",
                    "project_id": "crm-admin",
                    "name": "crm-admin",
                    "aliases": ["CRM后台"],
                    "local_paths": [str(project)],
                    "modules": [
                        {
                            "name": "客户列表",
                            "keywords": ["客户列表", "客户筛选"],
                            "paths": ["src/customer"],
                        }
                    ],
                    "status": "verified",
                },
                options={"dedupe_key": "project:crm-admin"},
            )
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
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

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task CRM后台有个需求，客户列表新增状态筛选"),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["source"]["project_name"], "crm-admin")
            self.assertEqual(task["project_path"], str(project))
            self.assertEqual(task["source"]["match_evidence"][0]["source"], "llm_wiki")

    def test_human_clarification_with_project_folder_updates_task_and_starts_plan(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_project = root / "bps-admin"
            bootstrap_project.mkdir()
            _write_workflow(bootstrap_project)
            oms_project = root / "oms_operation_web"
            oms_project.mkdir()
            _write_workflow(oms_project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            registry = ProjectRegistry(
                [
                    {
                        "name": "bps-admin",
                        "aliases": ["BPS运营后台"],
                        "path": str(bootstrap_project),
                        "keywords": ["订单列表"],
                    }
                ]
            )
            resolver = ProjectKnowledgeResolver.from_registry(wiki=wiki, registry=registry)
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
                FakeGatewayEvent("/coding task oms后台订单2.0需求改版，按照 Figma 设计图重新实现订单列表"),
                gateway=gateway,
            )
            task_id = _task_id_from_message(gateway.messages[0])

            clarified = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding continue 这是oms后台的项目文件夹名称`oms_operation_web`"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            profile = wiki.read("project:oms_operation_web")
            self.assertEqual(created["action"], "skip")
            self.assertEqual(clarified["action"], "skip")
            self.assertEqual(orchestrator.auto_started[-1][0], task_id)
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLANNING.value)
            self.assertEqual(task["project_path"], str(oms_project.resolve()))
            self.assertEqual(task["source"]["project_name"], "oms_operation_web")
            self.assertEqual(task["task_session"]["project_name"], "oms_operation_web")
            self.assertEqual(task["source"]["match_evidence"][0]["source"], "human_project_folder")
            self.assertIn("已补充项目上下文", gateway.messages[-1])
            self.assertIsNotNone(profile)
            self.assertIn("oms后台", profile["aliases"])
            self.assertNotIn("这是oms后台", profile["aliases"])
            self.assertEqual(profile["local_paths"], [str(oms_project.resolve())])
















































if __name__ == "__main__":
    unittest.main()
