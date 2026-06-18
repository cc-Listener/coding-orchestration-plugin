from __future__ import annotations

import json
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


class GatewayPendingConfirmationFlowTest(unittest.TestCase):
    def test_gateway_coding_mode_high_confidence_rewrite_with_confirmation_flag_waits_for_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding delete task_delete",
                    intent="delete",
                    confidence=0.96,
                    risk_level="destructive",
                    needs_confirmation=True,
                    task_id="task_delete",
                )
            )
            ledger.create_task(
                task_id="task_delete",
                source={"project_name": "order-system"},
                requirement_summary="临时任务",
                project_path=str(root),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
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
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("删掉 task_delete"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_confirmation")
            self.assertIsNotNone(ledger.get_task("task_delete"))
            self.assertIn("/coding delete task_delete", gateway.messages[-1])
            self.assertIn("回复“确认”执行", gateway.messages[-1])

            confirmed = orchestrator.handle_gateway_event(FakeGatewayEvent("确认"), gateway=gateway)

            self.assertEqual(confirmed["action"], "skip")
            self.assertEqual(confirmed["reason"], "coding_rewrite_confirmed")
            self.assertIsNone(ledger.get_task("task_delete"))
            self.assertIn("已删除开发任务", gateway.messages[-1])
    def test_gateway_pending_action_confirmation_preempts_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-merge-thread"},
                },
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response("/coding implement task_1", intent="implement", confidence=0.98)
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
                reason="merge-test 等待人工确认",
                run_id="run_waiting",
                mode=RunMode.MERGE_TEST.value,
            )
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("确定"), gateway=gateway)

            self.assertEqual(result["reason"], "coding_pending_action_confirmed")
            self.assertEqual(rewriter.calls, [])
            self.assertEqual(orchestrator.auto_merge_test_started[0][0], "task_1")
            task = ledger.get_task("task_1")
            self.assertEqual(task["human_decisions"][-1]["type"], "pending_action_confirmation")
            self.assertIn("已开始 merge-test", gateway.messages[-1])
    def test_gateway_confirmation_uses_latest_merge_test_human_required_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            run_dir = root / "runs" / "task_1" / "run_waiting"
            run_dir.mkdir(parents=True)
            report_path = run_dir / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": "completed_unstructured",
                        "mode": "merge-test",
                        "summary_markdown": "需要确认是否提交未跟踪文件",
                        "human_required": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-merge-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_waiting",
                    "runner": "codex_cli",
                    "mode": RunMode.MERGE_TEST.value,
                    "status": "completed_unstructured",
                    "artifact": {"report": str(report_path)},
                    "workspace_path": str(workspace),
                },
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response("/coding bugfix 未跟踪文件确定可以去做提交了", intent="bugfix_feedback", confidence=0.98)
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
            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_1"), gateway=gateway)

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("未跟踪文件确定可以去做提交了"),
                gateway=gateway,
            )

            self.assertEqual(result["reason"], "coding_pending_action_confirmed")
            self.assertEqual(rewriter.calls, [])
            self.assertEqual(orchestrator.auto_merge_test_started[0][0], "task_1")
            self.assertEqual(ledger.get_task("task_1")["human_decisions"][-1]["type"], "pending_action_confirmation")
    def test_gateway_confirmation_does_not_rewrite_while_task_run_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.IMPLEMENTING.value,
                task_session={"runner": {"active_run_id": "run_active", "active_mode": "implementation"}},
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response("/coding implement task_1", intent="implement", confidence=0.99)
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
            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_1"), gateway=gateway)

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("确定"), gateway=gateway)

            self.assertEqual(result["reason"], "coding_confirmation_active_run")
            self.assertEqual(rewriter.calls, [])
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertIn("当前执行：run_active", gateway.messages[-1])
