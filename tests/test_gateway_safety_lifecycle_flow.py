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
from coding_orchestration.run_completion_presenter import format_stale_run_completion_message
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


class GatewaySafetyLifecycleFlowTest(unittest.TestCase):
    def test_gateway_ignores_plugin_generated_task_messages(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_implementation_started = []

            def _start_background_implementation(self, task_id, gateway, event):
                self.auto_implementation_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(ProjectRegistry([]))
            task_id = "task_echo"
            source = {
                "type": "feishu_chat",
                "raw_text": "订单流筛选需求",
                "normalized_text": "订单流筛选需求",
                "gateway_source": {
                    "platform": "feishu",
                    "chat_id": "chat_1",
                    "user_id": "user_1",
                    "chat_type": "dm",
                },
                "project_name": "bps-admin",
            }
            ledger.create_task(
                task_id=task_id,
                source=source,
                requirement_summary="订单流筛选需求",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
            )
            ledger.bind_active_task(
                binding_key="feishu:chat:chat_1",
                task_id=task_id,
                scope=source["gateway_source"],
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"[{task_id}] 已准备人工 merge-to-test。\n项目目录：{project}"),
                gateway=FakeGateway(),
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured, {"action": "skip", "reason": "ignored_coding_orchestration_echo"})
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertEqual(task["human_decisions"], [])
            self.assertEqual(orchestrator.auto_implementation_started, [])

    def test_stale_run_completion_does_not_overwrite_newer_task_state(self):
        class StaleRunner(FakeRunner):
            def __init__(self, ledger, task_id):
                super().__init__()
                self.ledger = ledger
                self.task_id = task_id

            def run(self, *, run_id, run_dir, project_path, workspace_path, mode, timeout_seconds):
                self.ledger.update_task_session(
                    self.task_id,
                    {"runner": {"active_run_id": "run_newer", "active_mode": "merge-test"}},
                )
                self.ledger.update_status(self.task_id, TaskStatus.DONE.value)
                self.ledger.update_phase(self.task_id, TaskPhase.MERGED_TEST.value)
                return super().run(
                    run_id=run_id,
                    run_dir=run_dir,
                    project_path=project_path,
                    workspace_path=workspace_path,
                    mode=mode,
                    timeout_seconds=timeout_seconds,
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            task_id = "task_stale"
            ledger.create_task(
                task_id=task_id,
                source={
                    "type": "feishu_chat",
                    "raw_text": "订单流筛选需求",
                    "normalized_text": "订单流筛选需求",
                    "project_name": "bps-admin",
                },
                requirement_summary="订单流筛选需求",
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
                runner_router=FakeRouter(StaleRunner(ledger, task_id)),
            )

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            task = ledger.get_task(task_id)
            self.assertTrue(result["stale_completion"])
            self.assertEqual(task["status"], TaskStatus.DONE.value)
            self.assertEqual(task["phase"], TaskPhase.MERGED_TEST.value)
            self.assertEqual(task["agent_runs"][-1]["stale_completion"], True)

    def test_stale_run_completion_hides_newer_run_id_from_user_summary(self):
        message = format_stale_run_completion_message(
            "task_stale",
            {
                "run_id": "run_old",
                "mode": RunMode.PLAN_ONLY.value,
                "current_task_status": TaskStatus.DONE.value,
                "observed_active_run_id": "run_newer",
                "artifacts": {"run_dir": "/tmp/run_old"},
            },
        )

        summary = message.split("调试信息：", 1)[0]
        self.assertIn("旧执行已归档", message)
        self.assertIn("任务期间已有更新执行", summary)
        self.assertNotIn("run_newer", message)
        self.assertNotIn("调试信息", message)
        self.assertNotIn("artifact=", message)

    def test_strong_implementation_confirmation_without_task_is_not_sent_to_main_agent(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_implementation_started = []

            def _start_background_implementation(self, task_id, gateway, event):
                self.auto_implementation_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("新建分支去干活"),
                gateway=gateway,
            )

            self.assertIsNone(result)
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(gateway.messages, [])
