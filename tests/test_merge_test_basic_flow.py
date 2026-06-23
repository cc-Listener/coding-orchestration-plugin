from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import (
    FakeCommandRewriter,
    FakeGateway,
    FakeGatewayEvent,
    FakeRouter,
    FakeRunner,
    _rewrite_response,
    _write_workflow,
)


class MergeTestBasicFlowTest(unittest.TestCase):
    def test_prepare_merge_to_test_is_manual_interface_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="done",
                project_path="/repo/order",
                status="ready_for_merge_test",
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_prepare_merge_test("task_1")

            self.assertIn("上一次实现上下文", message)
            self.assertIn("merge-test", message)
            self.assertEqual(ledger.get_task("task_1")["status"], "ready_for_merge_test")
            self.assertEqual(ledger.get_task("task_1")["phase"], "ready_to_merge_test")
    def test_prepare_merge_test_turns_blocked_implementation_into_ready_with_known_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现已完成，但测试环境不可用。",
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "merge_readiness": {
                            "ready": True,
                            "risk_level": "medium",
                            "risk_note": "缺少自动测试证据。",
                            "required_confirmation": False,
                            "recovery_action": "人工确认后合入 test，并在测试环境补验。",
                            "fallback_evidence": "stdout.log",
                        },
                        "verification_limitations": [
                            {
                                "reason": "test_environment_unavailable",
                                "impact": "缺少自动测试证据。",
                                "recovery_action": "人工确认后合入 test，并在测试环境补验。",
                                "fallback_evidence": "stdout.log",
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
                source={"type": "manual"},
                requirement_summary="implementation done with limited verification",
                project_path="/repo/order",
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
                    "status": "blocked",
                    "exit_code": 0,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
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

            message = orchestrator.command_prepare_merge_test("task_1")
            task = ledger.get_task("task_1")

            self.assertIn("已切换为等待人工执行 merge test", message)
            self.assertIn("/coding merge-test task_1", message)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertEqual(task["merge_records"][-1]["type"], "merge_test_prepared")
            self.assertEqual(task["merge_records"][-1]["known_gaps"], True)
    def test_coding_mode_prepare_merge_test_natural_language_does_not_start_implementation(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_implementation_started = []
                self.auto_merge_test_started = []

            def _start_background_implementation(self, task_id, gateway, event):
                self.auto_implementation_started.append((task_id, gateway, event))

            def _start_background_merge_test(self, task_id, gateway, event):
                self.auto_merge_test_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="done",
                project_path="/repo/order",
                status="ready_for_merge_test",
                llm_wiki_refs=[],
                human_decisions=[],
            )
            ledger.bind_active_task(
                binding_key="feishu:chat:chat_1",
                task_id="task_1",
                scope={"platform": "feishu", "chat_id": "chat_1"},
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response(
                        "/coding prepare-merge-test task_1",
                        intent="prepare_merge_test",
                        confidence=0.96,
                        risk_level="write",
                        task_id="task_1",
                        uses_active_task=True,
                    )
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("准备 merge test"), gateway=gateway)
            before_confirm = ledger.get_task("task_1")
            task = ledger.get_task("task_1")

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_executed")
            self.assertEqual(before_confirm["phase"], "ready_to_merge_test")
            self.assertEqual(task["phase"], "ready_to_merge_test")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(orchestrator.auto_merge_test_started, [])
            self.assertEqual(task["merge_records"][-1]["type"], "merge_test_prepared")
    def test_coding_merge_test_resumes_codex_session_and_marks_merged_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            (workspace / "src").mkdir()
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "stdout.log").write_text(
                '{"type":"thread.started","thread_id":"019e-test-thread"}\n',
                encoding="utf-8",
            )

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status="ready_for_merge_test",
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
                    "status": "success",
                    "artifact": {"stdout": str(impl_run / "stdout.log")},
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
            task = ledger.get_task("task_1")

            self.assertIn("merge-test 已处理", message)
            self.assertIn("未发现 QA 证据", message)
            self.assertIn("/coding complete task_1", message)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.MERGE_TEST)
            self.assertEqual(fake_runner.calls[-1]["workspace_path"], workspace)
            self.assertEqual(task["status"], "merged_test")
            self.assertEqual(task["phase"], "merged_test")
            self.assertEqual(task["merge_records"][-1]["type"], "merge_test_run")
            self.assertEqual(task["merge_records"][-1]["target_branch"], "test")
            run_dir = fake_runner.calls[-1]["run_dir"]
            prompt = Path(run_dir / "input-prompt.md").read_text(encoding="utf-8")
            manifest = json.loads(Path(run_dir / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("merge-to-test", prompt)
            self.assertIn("codex/order-task_1", prompt)
            self.assertEqual(manifest["mode"], "merge-test")
            self.assertEqual(manifest["resume_session_id"], "019e-test-thread")
            self.assertEqual(manifest["target_branch"], "test")
            self.assertTrue(manifest["dangerous_bypass"])
    def test_coding_merge_test_releases_mergeable_blocked_task_with_known_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            (workspace / "src").mkdir()
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现已完成，自动验证受环境限制。",
                        "modified_files": ["src/app.ts"],
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "merge_readiness": {
                            "ready": True,
                            "risk_level": "medium",
                            "risk_note": "缺少自动测试证据，需在 test 环境补验。",
                            "required_confirmation": False,
                            "recovery_action": "人工确认风险后执行 merge-test，并在测试环境补验。",
                            "fallback_evidence": "stdout.log",
                        },
                        "verification_limitations": [
                            {
                                "reason": "test_environment_unavailable",
                                "impact": "缺少自动测试证据，需在 test 环境补验。",
                                "recovery_action": "人工确认风险后执行 merge-test，并在测试环境补验。",
                                "fallback_evidence": "stdout.log",
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
                requirement_summary="done with known gaps",
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
            release_records = [
                record for record in task["merge_records"] if record["type"] == "blocked_merge_test_released"
            ]

            self.assertIn("已基于 Codex 给出的验证说明继续 merge-test", message)
            self.assertIn("缺少自动测试证据，需在 test 环境补验", message)
            self.assertIn("替代证据：已有运行记录可供核对。", message)
            self.assertNotIn("stdout.log", message)
            self.assertNotIn("Blocked 放行", message)
            self.assertNotIn("known gaps", message)
            self.assertNotIn("codex_merge_readiness", message)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.MERGE_TEST)
            self.assertEqual(task["status"], TaskStatus.MERGED_TEST.value)
            self.assertEqual(release_records[0]["reason"], "codex_merge_readiness")
            self.assertEqual(task["human_decisions"][-1]["type"], "blocked_merge_test_release")
    def test_prepare_merge_test_requires_accept_risk_when_codex_readiness_requires_confirmation(self):
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
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_prepare_merge_test("task_1")
            task = ledger.get_task("task_1")

            self.assertIn("验证证据还不完整", message)
            self.assertIn("只跑了定向验证", message)
            self.assertIn("/coding merge-test task_1 --accept-risk", message)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["phase"], TaskPhase.BLOCKED.value)
            self.assertEqual(task["merge_records"], [])
