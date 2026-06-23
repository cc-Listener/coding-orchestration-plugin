from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.presenters import merge_test_presenter
from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, ArtifactSet, RunMode, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.runners.base import RunResult
from tests.orchestrator_flow_fixtures import (
    FakeGateway,
    FakeGatewayEvent,
    FakeRouter,
    FakeRunner,
    RecordingCodingOrchestrator,
    _write_workflow,
)


class MergeTestQaGateFlowTest(unittest.TestCase):
    def test_coding_merge_test_requires_confirmation_when_latest_qa_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "stdout.log").write_text(
                '{"type":"thread.started","thread_id":"019e-test-thread"}\n',
                encoding="utf-8",
            )
            qa_report = root / "runs" / "task_1" / "run_qa" / "report.json"
            qa_report.parent.mkdir(parents=True)
            qa_report.write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "summary_markdown": "QA 失败",
                        "verification_limitations": [
                            {
                                "reason": "qa_failed",
                                "impact": "核心流程仍有失败",
                                "recovery_action": "修复失败流程后重新 QA",
                                "fallback_evidence": "stdout",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": "implementation",
                    "status": "ready_for_merge_test",
                    "artifact": {"stdout": str(impl_run / "stdout.log")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_qa",
                    "runner": "codex_cli",
                    "mode": RunMode.QA.value,
                    "status": "failed",
                    "artifact": {"report": str(qa_report)},
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

            blocked_message = orchestrator.command_coding_merge_test("task_1")
            confirmed_message = orchestrator.command_coding_merge_test("task_1 --confirm-qa-risk")

            self.assertIn("最近一次 QA 证据不够完整", blocked_message)
            self.assertIn("--confirm-qa-risk", blocked_message)
            self.assertIn("修复失败流程后重新 QA", blocked_message)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.MERGE_TEST)
            self.assertIn("merge-test 已处理", confirmed_message)
    def test_merge_test_qa_risk_confirmation_message_is_user_facing(self):
        message = merge_test_presenter.merge_test_qa_risk_confirmation_message(
            "task_1",
            {
                "status": "failed",
                "impact": "缺少可信 QA 通过证据",
                "recovery_action": "修复失败流程后重新 QA",
            },
            include_reply_hint=False,
        )

        self.assertIn("最近一次 QA 证据不够完整", message)
        self.assertIn("影响：缺少可信 QA 通过证据", message)
        self.assertIn("建议：修复失败流程后重新 QA", message)
        self.assertIn("/coding merge-test task_1 --confirm-qa-risk", message)
        self.assertNotIn("最近 QA run 状态为 failed", message)
    def test_gateway_merge_test_qa_risk_confirmation_uses_pending_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "stdout.log").write_text(
                '{"type":"thread.started","thread_id":"019e-test-thread"}\n',
                encoding="utf-8",
            )
            qa_report = root / "runs" / "task_1" / "run_qa" / "report.json"
            qa_report.parent.mkdir(parents=True)
            qa_report.write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "summary_markdown": "QA 失败",
                        "verification_limitations": [
                            {
                                "reason": "qa_failed",
                                "impact": "核心流程仍有失败",
                                "recovery_action": "修复失败流程后重新 QA",
                                "fallback_evidence": "stdout",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-test-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": "implementation",
                    "status": "ready_for_merge_test",
                    "artifact": {"stdout": str(impl_run / "stdout.log")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_qa",
                    "runner": "codex_cli",
                    "mode": RunMode.QA.value,
                    "status": "failed",
                    "artifact": {"report": str(qa_report)},
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

            blocked = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding merge-test task_1"),
                gateway=gateway,
            )
            confirmed = orchestrator.handle_gateway_event(FakeGatewayEvent("确认继续"), gateway=gateway)

            self.assertEqual(blocked["reason"], "handled_by_coding_orchestration")
            self.assertIn("最近一次 QA 证据不够完整", gateway.messages[-2])
            self.assertIn("回复“确认”继续", gateway.messages[-2])
            self.assertEqual(confirmed["reason"], "coding_pending_action_confirmed")
            self.assertEqual(orchestrator.auto_merge_test_started[0][0], "task_1")
    def test_coding_merge_test_does_not_require_confirmation_when_latest_qa_succeeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            qa_report = root / "runs" / "task_1" / "run_qa" / "report.json"
            qa_report.parent.mkdir(parents=True)
            qa_report.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": AgentRunStatus.SUCCEEDED.value,
                        "raw_status": AgentRunStatus.SUCCEEDED.value,
                        "status_detail": "",
                        "failure_type": "",
                        "known_gaps": False,
                        "structured": True,
                        "mode": RunMode.QA.value,
                        "summary_markdown": "QA passed",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": [],
                        "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
                        "tested_commit": "",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_qa",
                    "runner": "codex_cli",
                    "mode": RunMode.QA.value,
                    "status": AgentRunStatus.SUCCEEDED.value,
                    "raw_status": AgentRunStatus.SUCCEEDED.value,
                    "known_gaps": False,
                    "artifact": {"report": str(qa_report)},
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_merge_test("task_1")

            self.assertNotIn("--confirm-qa-risk", message)
            self.assertEqual((ledger.get_task("task_1") or {})["status"], TaskStatus.MERGED_TEST.value)
    def test_merge_test_human_required_keeps_task_ready_and_stores_pending_action(self):
        class HumanRequiredMergeRunner(FakeRunner):
            def run(self, *, run_id, run_dir, project_path, workspace_path, mode, timeout_seconds):
                (run_dir / "stdout.log").write_text(
                    '{"type":"thread.started","thread_id":"019e-merge-thread"}\n',
                    encoding="utf-8",
                )
                (run_dir / "stderr.log").write_text("", encoding="utf-8")
                (run_dir / "summary.md").write_text("需要确认未跟踪文件", encoding="utf-8")
                report = {
                    "runner": self.name,
                    "status": "completed_unstructured",
                    "mode": mode.value,
                    "summary_markdown": "需要确认未跟踪文件",
                    "modified_files": [],
                    "test_commands": [],
                    "test_results": [],
                    "risks": ["需要人工确认"],
                    "verification_limitations": [
                        {
                            "reason": "merge_test_human_confirmation",
                            "impact": "merge-test 尚未完成",
                            "recovery_action": "确认后重试 merge-test",
                            "fallback_evidence": str(run_dir / "stdout.log"),
                        }
                    ],
                    "human_required": True,
                    "next_actions": ["确认后继续 merge-test"],
                }
                (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
                artifacts = ArtifactSet(
                    run_dir=run_dir,
                    input_prompt=run_dir / "input-prompt.md",
                    manifest=run_dir / "run-manifest.json",
                    stdout=run_dir / "stdout.log",
                    stderr=run_dir / "stderr.log",
                    events=run_dir / "events.jsonl",
                    report=run_dir / "report.json",
                    summary=run_dir / "summary.md",
                    diff=run_dir / "diff.patch",
                )
                return RunResult(
                    status=AgentRunStatus.COMPLETED_UNSTRUCTURED.value,
                    exit_code=0,
                    artifacts=artifacts,
                    report=report,
                )

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
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(HumanRequiredMergeRunner()),
            )
            gateway = FakeGateway()
            event = FakeGatewayEvent("event")

            orchestrator._run_merge_test_and_notify("task_1", gateway, event, None)

            task = ledger.get_task("task_1")
            pending = orchestrator._pending_action_for_event(event)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertEqual(pending["command_text"], "/coding merge-test task_1")
            self.assertIn("回复“确认”继续当前 merge-test", gateway.messages[-1])
    def test_merge_test_blocks_uncommitted_implementation_files_before_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            (workspace / "src").mkdir(parents=True)
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=workspace, check=True, stdout=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
            subprocess.run(["git", "add", "src/app.ts"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=workspace, check=True, stdout=subprocess.PIPE)
            (workspace / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")
            (workspace / "src" / "new-page.ts").write_text("export const page = true\n", encoding="utf-8")
            status_at_runner_start: list[str] = []

            def record_clean_tree(cwd: Path) -> None:
                status_at_runner_start.append(
                    subprocess.check_output(["git", "status", "--porcelain"], cwd=cwd, text=True)
                )

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="新增订单导出",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-merge-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value,
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            fake_runner = FakeRunner(mutate=record_clean_tree)
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
            latest_run = task["agent_runs"][-1]
            report = json.loads(Path(latest_run["artifact"]["report"]).read_text(encoding="utf-8"))
            manifest = json.loads(Path(latest_run["artifact"]["manifest"]).read_text(encoding="utf-8"))

            self.assertEqual(status_at_runner_start, [])
            self.assertEqual(fake_runner.calls, [])
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(manifest["merge_test_checkpoint"]["status"], "failed")
            self.assertEqual(report["verification_limitations"][0]["reason"], "implementation_commit_missing")
            self.assertIn("实现工作区仍有未提交改动", message)
