from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import FakeGateway, FakeGatewayEvent, FakeRouter, FakeRunner, _write_workflow


class GatewayCodingModeLifecycleFlowTest(unittest.TestCase):
    def test_gateway_coding_mode_exit_disables_natural_language(self):
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

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            exited = orchestrator.handle_gateway_event(FakeGatewayEvent("退出coding"), gateway=gateway)
            ignored = orchestrator.handle_gateway_event(FakeGatewayEvent("订单系统新增发货筛选"), gateway=gateway)

            self.assertEqual(exited["action"], "skip")
            self.assertIsNone(ignored)
            self.assertEqual(orchestrator.auto_started, [])
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])
    def test_gateway_coding_mode_enter_exit_are_idempotent_and_deduped(self):
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

            enter_event = FakeGatewayEvent("进入coding", message_id="msg-enter")
            entered = orchestrator.handle_gateway_event(enter_event, gateway=gateway)
            duplicated_enter = orchestrator.handle_gateway_event(enter_event, gateway=gateway)
            entered_again = orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding", message_id="msg-enter-2"), gateway=gateway)
            exit_event = FakeGatewayEvent("退出coding", message_id="msg-exit")
            exited = orchestrator.handle_gateway_event(exit_event, gateway=gateway)
            duplicated_exit = orchestrator.handle_gateway_event(exit_event, gateway=gateway)
            exited_again = orchestrator.handle_gateway_event(FakeGatewayEvent("退出coding", message_id="msg-exit-2"), gateway=gateway)

            self.assertEqual(entered["reason"], "coding_mode_entered")
            self.assertEqual(duplicated_enter["reason"], "duplicate_gateway_event")
            self.assertEqual(entered_again["reason"], "coding_mode_entered")
            self.assertEqual(exited["reason"], "coding_mode_exited")
            self.assertEqual(duplicated_exit["reason"], "duplicate_gateway_event")
            self.assertEqual(exited_again["reason"], "coding_mode_exited")
            self.assertEqual(len(gateway.messages), 4)
            self.assertIn("已进入 coding mode", gateway.messages[0])
            self.assertIn("当前已在 coding mode", gateway.messages[1])
            self.assertIn("已退出 coding mode", gateway.messages[2])
            self.assertIn("当前未开启 coding mode", gateway.messages[3])
            self.assertNotIn("已退出 coding mode", gateway.messages[3])
    def test_gateway_coding_help_lists_commands_and_usage(self):
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

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding help"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertIn("Coding Orchestration 命令帮助", gateway.messages[0])
            self.assertIn("/coding task <需求>", gateway.messages[0])
            self.assertIn("/coding status <task_id>", gateway.messages[0])
            self.assertIn("/coding change <反馈>", gateway.messages[0])
            self.assertIn("/coding project list", gateway.messages[0])
            self.assertIn("/coding project init <project_path_or_name>", gateway.messages[0])
            self.assertIn("/coding merge-test <task_id>", gateway.messages[0])
            self.assertNotIn("兼容别名", gateway.messages[0])
            self.assertNotIn("/codex", gateway.messages[0])
            self.assertNotIn("/coding-", gateway.messages[0])
    def test_gateway_legacy_coding_aliases_do_not_enter_plugin(self):
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

            coding_dash = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding-task 修复订单"), gateway=gateway)
            codex_dash = orchestrator.handle_gateway_event(FakeGatewayEvent("/codex-task 修复订单"), gateway=gateway)

            self.assertIsNone(coding_dash)
            self.assertIsNone(codex_dash)
            self.assertEqual(gateway.messages, [])
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])
