from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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


class GatewayCommandGroupFlowTest(unittest.TestCase):
    def test_commands_listing_includes_coding_plugin_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            text = orchestrator.command_commands_listing("")

            self.assertIn("Coding Orchestration Plugin Commands", text)
            self.assertIn("/coding task <需求>", text)
            self.assertIn("/coding status <task_id>", text)
            self.assertIn("/coding change <反馈>", text)
            self.assertIn("/coding project list", text)
            self.assertIn("/coding project clear", text)
            self.assertIn("/coding delete <task_id>", text)
            self.assertIn("普通自然语言不会自动创建开发任务", text)

    def test_gateway_commands_is_intercepted_before_hermes_builtin_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("/commands"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "handled_by_coding_orchestration_commands")
            self.assertIn("Coding Orchestration Plugin Commands", gateway.messages[0])
            self.assertIn("/coding task <需求>", gateway.messages[0])
            self.assertIn("/coding status <task_id>", gateway.messages[0])

    def test_gateway_coding_doctor_is_intercepted_before_main_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding doctor"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "handled_by_coding_orchestration")
            self.assertIn("编码流程健康检查", gateway.messages[0])
            self.assertIn("\n\n飞书项目 MCP\n状态：❌ 未启用", gateway.messages[0])
            self.assertIn("\n\nHermes\n状态：❌ 不可用", gateway.messages[0])
            self.assertIn("\n\nCodex\n状态：❌ 不可用", gateway.messages[0])
            self.assertIn("验证命令：\nrtk hermes coding project-mcp-preflight", gateway.messages[0])
            self.assertNotIn("任务账本", gateway.messages[0])
            self.assertNotIn("定时检查建议", gateway.messages[0])
            self.assertNotIn("ledger.db", gateway.messages[0])

    def test_command_coding_project_mcp_preflight_uses_project_mcp_formatter(self):
        class ProjectMcpDiagnosticOrchestrator(CodingOrchestrator):
            def project_mcp_preflight_config(self):
                return SimpleNamespace(
                    enabled=True,
                    transport="stdio",
                    domain="https://project.feishu.cn",
                    command=["npx"],
                    token="configured-token",
                    config_file_hint="~/.hermes/coding-orchestration/mcp.json",
                    token_config_ref="mcpServers.feishu-project.env.MCP_USER_TOKEN",
                    server_config_ref="mcpServers.feishu-project",
                )

            def project_mcp_preflight_command_available(self, config):
                return True

            def tool_project_mcp_preflight(self, payload):
                return {"ok": True, "allowed_tools": ["story.search"]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = ProjectMcpDiagnosticOrchestrator(
                ledger=TaskLedger(root / "ledger.db"),
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            output = orchestrator.command_coding("project-mcp-preflight")

            self.assertIn("飞书项目 MCP 检查", output)
            self.assertIn("状态：✅ 可用", output)
            self.assertIn("工具白名单：story.search", output)

    def test_gateway_diagnostic_commands_are_intercepted_before_main_agent(self):
        class DiagnosticOrchestrator(CodingOrchestrator):
            def tool_lark_preflight(self, payload):
                self.diagnostic_calls.append(("lark", payload))
                return {"ok": True}

            def tool_source_resolve(self, payload):
                self.diagnostic_calls.append(("source", payload))
                return {
                    "source_status": "indexed",
                    "task_status": "ready",
                    "source_type": "feishu_docx",
                    "url": payload["text"],
                }

            def project_mcp_preflight_config(self):
                return SimpleNamespace(
                    enabled=True,
                    transport="stdio",
                    domain="https://project.feishu.cn",
                    command=["npx"],
                    token="configured-token",
                    config_file_hint="~/.hermes/coding-orchestration/mcp.json",
                    token_config_ref="mcpServers.feishu-project.env.MCP_USER_TOKEN",
                    server_config_ref="mcpServers.feishu-project",
                )

            def project_mcp_preflight_command_available(self, config):
                self.diagnostic_calls.append(("project_mcp_command", config))
                return True

            def tool_project_mcp_preflight(self, payload):
                self.diagnostic_calls.append(("project_mcp", payload))
                return {"ok": True, "allowed_tools": ["story.search"]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            orchestrator = DiagnosticOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            orchestrator.diagnostic_calls = []
            gateway = FakeGateway()

            lark_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding lark-preflight"), gateway=gateway)
            project_mcp_result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding project-mcp-preflight"),
                gateway=gateway,
            )
            source_result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding source-resolve https://example.test/docx/Token123"),
                gateway=gateway,
            )

            self.assertEqual(lark_result["action"], "skip")
            self.assertEqual(project_mcp_result["action"], "skip")
            self.assertEqual(source_result["action"], "skip")
            self.assertEqual(
                [call[0] for call in orchestrator.diagnostic_calls],
                ["lark", "project_mcp_command", "project_mcp", "source"],
            )
            self.assertIn("飞书权限检查", gateway.messages[0])
            self.assertIn("状态：✅ 可用", gateway.messages[0])
            self.assertIn("飞书项目 MCP 检查", gateway.messages[1])
            self.assertIn("状态：✅ 可用", gateway.messages[1])
            self.assertIn("工具白名单：story.search", gateway.messages[1])
            self.assertIn("来源解析", gateway.messages[2])
            self.assertIn("链接：https://example.test/docx/Token123", gateway.messages[2])

    def test_gateway_coding_group_task_command_creates_task(self):
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
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
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
                ),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task 订单系统有个需求，新增发货状态筛选"),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id = orchestrator.auto_started[0][0]
            self.assertEqual(ledger.get_task(task_id)["status"], "planned")
            self.assertIn(f"任务：{task_id}", gateway.messages[0])
            self.assertIn("需求小结：订单系统有个需求，新增发货状态筛选", gateway.messages[0])

    def test_command_coding_group_dispatches_task_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
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
                ),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            response = orchestrator.command_coding("task 订单系统有个需求，新增发货状态筛选")

            self.assertIn("已记录新任务", response)
            self.assertIn("需求小结：订单系统有个需求，新增发货状态筛选", response)
            self.assertEqual(len(ledger.list_recent_tasks(limit=5)), 1)

    def test_gateway_coding_group_status_command_dispatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            task_id = "task_status"
            ledger.create_task(
                task_id=task_id,
                source={"type": "feishu_chat", "raw_text": "需求", "normalized_text": "需求"},
                requirement_summary="需求",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding status {task_id}"),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertIn(f"[{task_id}] 状态：已规划(planned)", gateway.messages[0])
            self.assertNotIn("phase：", gateway.messages[0])
