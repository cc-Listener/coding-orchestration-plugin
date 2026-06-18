from __future__ import annotations

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


class GatewayNaturalLanguageCommandFlowTest(unittest.TestCase):
    def test_gateway_coding_mode_list_question_does_not_create_task(self):
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
                _rewrite_response("/coding list", intent="list_tasks", confidence=0.98, risk_level="read")
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
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("现在有多少个task"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_started, [])
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])
            self.assertIn("当前没有未结束开发任务", gateway.messages[-1])
    def test_gateway_task_list_shows_status_id_project_and_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            rewriter = FakeCommandRewriter(
                _rewrite_response("/coding list", intent="list_tasks", confidence=0.98, risk_level="read")
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
            ledger.create_task(
                task_id="task_43141b20c03e",
                source={"project_name": "bps-admin"},
                requirement_summary="订单流列表增加筛选操作按钮",
                project_path="/Users/xiaojing/Desktop/project/bps-admin",
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            list_result = orchestrator.handle_gateway_event(FakeGatewayEvent("现在有多少个task"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(list_result["reason"], "coding_rewrite_executed")
            self.assertIn("任务：task_43141b20c03e", gateway.messages[-1])
            self.assertIn("状态：受阻(blocked)", gateway.messages[-1])
            self.assertIn("项目：bps-admin", gateway.messages[-1])
            self.assertIn("任务描述：订单流列表增加筛选操作按钮", gateway.messages[-1])
            self.assertIn("提示：当前会话绑定：无；使用 /coding use <task_id> 切换当前任务。", gateway.messages[-1])
            self.assertNotIn("/Users/xiaojing/Desktop/project/bps-admin", gateway.messages[-1])
    def test_gateway_coding_mode_natural_language_bugfix_rewrite_uses_active_task_and_executes_directly(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.implementation_started = []

            def _start_background_implementation(self, task_id, gateway, event):
                self.implementation_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            feedback = "查看最近对话记录，自然语言的rewrite表现不符合预期"
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    f"/coding bugfix {feedback}",
                    intent="bugfix_feedback",
                    confidence=0.92,
                    risk_level="write",
                    task_id="task_rewrite",
                    uses_active_task=True,
                )
            )
            ledger.create_task(
                task_id="task_rewrite",
                source={"project_name": "bps-admin"},
                requirement_summary="优化 Hermes Coding Mode 自然语言 rewrite",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
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
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_rewrite"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent(feedback), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_executed")
            self.assertEqual(len(rewriter.calls), 1)
            self.assertEqual(rewriter.calls[0]["active_task"]["task_id"], "task_rewrite")
            self.assertEqual(rewriter.calls[0]["active_task"]["project"], "bps-admin")
            self.assertEqual(orchestrator.implementation_started[0][0], "task_rewrite")
            task = ledger.get_task("task_rewrite")
            self.assertEqual(task["human_decisions"][-1]["type"], "implementation_feedback")
            self.assertEqual(task["human_decisions"][-1]["text"], feedback)
            self.assertIn("已收到修复反馈", gateway.messages[-1])
    def test_gateway_coding_mode_natural_language_rewrite_covers_help_use_status_and_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_nav",
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单流筛选",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response("/coding help", intent="help", confidence=0.98, risk_level="read")
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            help_result = orchestrator.handle_gateway_event(FakeGatewayEvent("帮我看一下有什么命令"), gateway=gateway)

            self.assertEqual(help_result["reason"], "coding_rewrite_executed")
            self.assertIn("Coding Orchestration 命令帮助", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding use task_nav",
                    intent="select_task",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_nav",
                )
            )
            use_event = FakeGatewayEvent("切换到 task_nav")
            use_result = orchestrator.handle_gateway_event(use_event, gateway=gateway)

            self.assertEqual(use_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator._active_task_id_for_event(use_event), "task_nav")
            self.assertIn("已切换当前开发任务", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding status task_nav",
                    intent="status_task",
                    confidence=0.98,
                    risk_level="read",
                    task_id="task_nav",
                )
            )
            status_result = orchestrator.handle_gateway_event(FakeGatewayEvent("看一下当前任务状态"), gateway=gateway)

            self.assertEqual(status_result["reason"], "coding_rewrite_executed")
            self.assertIn("[task_nav] 状态：已规划(planned)", gateway.messages[-1])
            self.assertIn("源分支：未创建", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response("/coding exit", intent="exit_task", confidence=0.98, risk_level="write")
            )
            exit_result = orchestrator.handle_gateway_event(FakeGatewayEvent("退出当前 coding 任务绑定"), gateway=gateway)
            ignored_after_exit = orchestrator.handle_gateway_event(FakeGatewayEvent("现在有多少个 task"), gateway=gateway)

            self.assertEqual(exit_result["reason"], "coding_rewrite_executed")
            self.assertIn("已退出当前飞书会话的 coding 模式", gateway.messages[-1])
            self.assertIsNone(ignored_after_exit)
    def test_gateway_coding_mode_natural_language_rewrite_covers_feedback_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_feedback",
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单流筛选",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response(
                        "/coding continue 目标页面仅为新版 /orderFlow",
                        intent="plan_feedback",
                        confidence=0.96,
                        risk_level="write",
                        task_id="task_feedback",
                        uses_active_task=True,
                    )
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_feedback"), gateway=gateway)
            continue_result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("目标页面仅为新版 /orderFlow，根据这个重新制定计划"),
                gateway=gateway,
            )

            self.assertEqual(continue_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], "task_feedback")
            task = ledger.get_task("task_feedback")
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding change 需求改成订单标签字段 order_tags",
                    intent="requirement_change",
                    confidence=0.96,
                    risk_level="write",
                    task_id="task_feedback",
                    uses_active_task=True,
                )
            )
            change_result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("需求改成订单标签字段 order_tags"),
                gateway=gateway,
            )

            self.assertEqual(change_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], "task_feedback")
            task = ledger.get_task("task_feedback")
            self.assertEqual(task["human_decisions"][-1]["type"], "requirement_change")

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding bugfix order_tags 后端是 string，在源分支修改",
                    intent="bugfix_feedback",
                    confidence=0.96,
                    risk_level="write",
                    task_id="task_feedback",
                    uses_active_task=True,
                )
            )
            bugfix_result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("这里有问题，order_tags 后端是 string，在源分支修改"),
                gateway=gateway,
            )

            self.assertEqual(bugfix_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_implementation_started[-1][0], "task_feedback")
            task = ledger.get_task("task_feedback")
            self.assertEqual(task["human_decisions"][-1]["type"], "implementation_feedback")
    def test_gateway_coding_mode_natural_language_rewrite_covers_runner_and_completion_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_merge" / "run_impl"
            workspace.mkdir(parents=True)
            (workspace / "src").mkdir()
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            qa_workspace = root / "workspaces" / "task_qa" / "run_impl"
            qa_workspace.mkdir(parents=True)
            (qa_workspace / "src").mkdir()
            (qa_workspace / "src" / "app.ts").write_text("export const qa = true\n", encoding="utf-8")
            impl_run = root / "runs" / "task_merge" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "stdout.log").write_text(
                '{"type":"thread.started","thread_id":"019e-test-thread"}\n',
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            for task_id, status, phase in [
                ("task_run", TaskStatus.PLANNED.value, TaskPhase.PLAN_READY.value),
                ("task_impl", TaskStatus.PLANNED.value, TaskPhase.PLAN_READY.value),
                ("task_prepare", TaskStatus.READY_FOR_MERGE_TEST.value, TaskPhase.READY_TO_MERGE_TEST.value),
                ("task_done", TaskStatus.MERGED_TEST.value, TaskPhase.MERGED_TEST.value),
            ]:
                ledger.create_task(
                    task_id=task_id,
                    source={"type": "manual", "project_name": "order"},
                    requirement_summary=f"{task_id} requirement",
                    project_path=str(project),
                    status=status,
                    llm_wiki_refs=[],
                    human_decisions=[],
                    phase=phase,
                )
            ledger.create_task(
                task_id="task_qa",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="qa requirement",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                task_session={
                    "source_branch": "codex/order-task_qa",
                    "worktree_path": str(qa_workspace),
                },
            )
            ledger.create_task(
                task_id="task_merge",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="merge requirement",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                task_session={
                    "source_branch": "codex/order-task_merge",
                    "worktree_path": str(workspace),
                },
            )
            ledger.append_agent_run(
                "task_merge",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": "success",
                    "artifact": {"stdout": str(impl_run / "stdout.log")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_merge",
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
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response(
                        "/coding run task_run",
                        intent="run_plan",
                        confidence=0.98,
                        risk_level="write",
                        task_id="task_run",
                    )
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            run_result = orchestrator.handle_gateway_event(FakeGatewayEvent("重新跑 task_run 的计划"), gateway=gateway)

            self.assertEqual(run_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], "task_run")
            self.assertEqual(fake_runner.calls, [])
            self.assertIn("已开始整理计划", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding implement task_impl",
                    intent="implement",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_impl",
                )
            )
            implement_result = orchestrator.handle_gateway_event(FakeGatewayEvent("task_impl 的计划确认了，开始开发"), gateway=gateway)

            self.assertEqual(implement_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_implementation_started[-1][0], "task_impl")
            self.assertIn("开始实现", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding qa task_qa",
                    intent="qa_requested",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_qa",
                )
            )
            qa_result = orchestrator.handle_gateway_event(FakeGatewayEvent("task_qa 开始测试"), gateway=gateway)

            self.assertEqual(qa_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_qa_started[-1][0], "task_qa")
            self.assertIn("已开始 QA", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding prepare-merge-test task_prepare",
                    intent="prepare_merge_test",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_prepare",
                )
            )
            prepare_result = orchestrator.handle_gateway_event(FakeGatewayEvent("task_prepare 准备 merge test"), gateway=gateway)
            task_prepare = ledger.get_task("task_prepare")

            self.assertEqual(prepare_result["reason"], "coding_rewrite_executed")
            self.assertEqual(task_prepare["merge_records"][-1]["type"], "merge_test_prepared")
            self.assertIn("/coding merge-test task_prepare", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding merge-test task_merge",
                    intent="merge_test",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_merge",
                )
            )
            merge_result = orchestrator.handle_gateway_event(FakeGatewayEvent("task_merge 去合并到 test"), gateway=gateway)
            task_merge = ledger.get_task("task_merge")

            self.assertEqual(merge_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_merge_test_started[-1][0], "task_merge")
            self.assertEqual(task_merge["merge_records"][-1]["type"], "merge_test_requested")
            self.assertIn("已开始 merge-test", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding complete task_done",
                    intent="complete_task",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_done",
                )
            )
            complete_result = orchestrator.handle_gateway_event(FakeGatewayEvent("task_done 已经合入 test，标记完成"), gateway=gateway)
            task_done = ledger.get_task("task_done")

            self.assertEqual(complete_result["reason"], "coding_rewrite_executed")
            self.assertEqual(task_done["status"], TaskStatus.DONE.value)
            self.assertEqual(task_done["phase"], TaskPhase.DONE.value)
            self.assertIn("已人工标记完成", gateway.messages[-1])
