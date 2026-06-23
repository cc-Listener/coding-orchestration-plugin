from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.presenters import merge_test_presenter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import (
    FakeGateway,
    FakeGatewayEvent,
    FakeRouter,
    FakeRunner,
    RecordingCodingOrchestrator,
    _write_workflow,
)


class MergeTestBlockedFlowTest(unittest.TestCase):
    def test_coding_merge_test_rejects_blocked_diff_guard_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现改动越权。",
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "verification_limitations": [
                            {
                                "reason": "diff_guard_violation",
                                "impact": "存在越权 diff，不能标记安全。",
                                "recovery_action": "先收敛改动范围或人工处理越权 diff。",
                                "fallback_evidence": "diff.patch",
                            }
                        ],
                        "human_required": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="blocked with violation",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                    "diff_guard": {"changed_files": ["../outside.ts"], "violations": ["outside path"]},
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_merge_test("task_1")
            task = ledger.get_task("task_1")

            self.assertIn("验证证据还不完整", message)
            self.assertIn("--accept-risk", message)
            self.assertNotIn("diff_guard_violation", message)
            self.assertEqual(fake_runner.calls, [])
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
    def test_blocked_merge_test_risk_confirmation_message_is_user_facing(self):
        message = merge_test_presenter.blocked_merge_test_risk_confirmation_message(
            "task_1",
            {
                "impact": "只跑了定点测试。",
                "recovery_action": "确认风险后继续 merge-test。",
                "fallback_evidence": "/tmp/run/report.json",
            },
        )

        self.assertIn("验证证据还不完整", message)
        self.assertIn("影响：只跑了定点测试。", message)
        self.assertIn("建议：确认风险后继续 merge-test。", message)
        self.assertIn("替代证据：已有运行记录可供核对。", message)
        self.assertIn("/coding merge-test task_1 --accept-risk", message)
        self.assertIn("回复“确认”会继续；回复“取消”会放弃本次继续动作。", message)
        self.assertNotIn("当前是 blocked", message)
        self.assertNotIn("风险原因：unknown", message)
        self.assertNotIn("report.json", message)
        self.assertNotIn("/tmp/run", message)
    def test_coding_merge_test_rejects_blocked_without_structured_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="blocked without report",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_merge_test("task_1")

            self.assertIn("验证证据还不完整", message)
            self.assertIn("缺少结构化验证报告", message)
            self.assertEqual(fake_runner.calls, [])
            self.assertEqual(ledger.get_task("task_1")["status"], TaskStatus.BLOCKED.value)
    def test_coding_merge_test_accepts_risk_for_blocked_without_structured_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="blocked without report but accepted",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_merge_test("task_1 --accept-risk")
            task = ledger.get_task("task_1")
            release = next(record for record in task["merge_records"] if record["type"] == "blocked_merge_test_released")

            self.assertIn("merge-test 已处理", message)
            self.assertIn("已按你的风险确认继续 merge-test", message)
            self.assertIn("缺少结构化验证报告", message)
            self.assertNotIn("missing_structured_report", message)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.MERGE_TEST)
            self.assertEqual(task["status"], TaskStatus.MERGED_TEST.value)
            self.assertEqual(release["reason"], "missing_structured_report")
            self.assertTrue(release["accepted_risk"])
            self.assertTrue(task["human_decisions"][-1]["accepted_risk"])
    def test_gateway_merge_test_releases_blocked_task_before_background_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现已完成，浏览器 QA 环境不可用。",
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "merge_readiness": {
                            "ready": True,
                            "risk_level": "medium",
                            "risk_note": "缺少浏览器交互验证证据。",
                            "required_confirmation": False,
                            "recovery_action": "人工确认后合 test，并在测试环境补跑浏览器 QA。",
                            "fallback_evidence": "qa stdout",
                        },
                        "verification_limitations": [
                            {
                                "reason": "browser_qa_unavailable",
                                "impact": "缺少浏览器交互验证证据。",
                                "recovery_action": "人工确认后合 test，并在测试环境补跑浏览器 QA。",
                                "fallback_evidence": "qa stdout",
                            }
                        ],
                        "human_required": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="blocked gateway release",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
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

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding merge-test task_1"), gateway)
            task = ledger.get_task("task_1")

            self.assertEqual(result["reason"], "handled_by_coding_orchestration")
            self.assertEqual(orchestrator.auto_merge_test_started[0][0], "task_1")
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertIn("已基于 Codex 给出的验证说明继续 merge-test", gateway.messages[-1])
            self.assertIn("缺少浏览器交互验证证据", gateway.messages[-1])
            self.assertIn("替代证据：已有运行记录可供核对。", gateway.messages[-1])
            self.assertNotIn("qa stdout", gateway.messages[-1])
            self.assertNotIn("原为 blocked", gateway.messages[-1])
            self.assertNotIn("known gaps", gateway.messages[-1])
            self.assertNotIn("codex_merge_readiness", gateway.messages[-1])
    def test_gateway_merge_test_blocked_risk_confirmation_uses_pending_accept_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="blocked missing report",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
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
            event = FakeGatewayEvent("/coding merge-test task_1")

            first = orchestrator.handle_gateway_event(event, gateway)
            pending = orchestrator._pending_action_for_event(event)
            confirmed = orchestrator.handle_gateway_event(FakeGatewayEvent("确认"), gateway)
            task = ledger.get_task("task_1")

            self.assertEqual(first["reason"], "handled_by_coding_orchestration")
            self.assertEqual(pending["command_text"], "/coding merge-test task_1 --accept-risk")
            self.assertIn("验证证据还不完整", gateway.messages[0])
            self.assertIn("缺少结构化验证报告", gateway.messages[0])
            self.assertEqual(confirmed["reason"], "coding_pending_action_confirmed")
            self.assertEqual(orchestrator.auto_merge_test_started[0][0], "task_1")
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertTrue(task["merge_records"][0]["accepted_risk"])
    def test_gateway_prepare_merge_test_stores_pending_accept_risk_for_required_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现已提交，但需要人工接受风险。",
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "merge_readiness": {
                            "ready": True,
                            "risk_level": "medium",
                            "risk_note": "只跑了定向验证，需要人工确认风险。",
                            "required_confirmation": True,
                            "recovery_action": "人工确认风险后继续 merge-test。",
                            "fallback_evidence": "summary.md",
                        },
                        "verification_limitations": [
                            {
                                "reason": "targeted_tests_only",
                                "impact": "未跑全量回归。",
                                "recovery_action": "人工接受风险后继续 merge-test。",
                                "fallback_evidence": "summary.md",
                            }
                        ],
                        "human_required": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="requires confirmation",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                    "diff_guard": {"changed_files": ["src/app.ts"], "violations": []},
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
            event = FakeGatewayEvent("/coding prepare-merge-test task_1")

            first = orchestrator.handle_gateway_event(event, gateway)
            pending = orchestrator._pending_action_for_event(event)
            confirmed = orchestrator.handle_gateway_event(FakeGatewayEvent("确认"), gateway)
            task = ledger.get_task("task_1")
            release = next(record for record in task["merge_records"] if record["type"] == "blocked_merge_test_released")

            self.assertEqual(first["reason"], "handled_by_coding_orchestration")
            self.assertIn("/coding merge-test task_1 --accept-risk", gateway.messages[0])
            self.assertEqual(pending["action"], "merge_test_accept_risk")
            self.assertEqual(pending["command_text"], "/coding merge-test task_1 --accept-risk")
            self.assertEqual(pending["mode"], RunMode.MERGE_TEST.value)
            self.assertEqual(confirmed["reason"], "coding_pending_action_confirmed")
            self.assertEqual(orchestrator.auto_merge_test_started[0][0], "task_1")
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertTrue(release["accepted_risk"])
