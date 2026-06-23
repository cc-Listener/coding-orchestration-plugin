from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import (
    AsyncFailingGateway,
    FakeGateway,
    FakeGatewayEvent,
    FakeRouter,
    FakeRunner,
    RecordingCodingOrchestrator,
    _write_workflow,
)


class QaFlowTest(unittest.TestCase):
    def test_implementation_notification_does_not_auto_run_qa_after_ready_status(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.modes = []

            def start_run(self, task_id, *, mode=RunMode.PLAN_ONLY, runner_name=None, timeout_seconds=None):
                self.modes.append(mode)
                status = TaskStatus.READY_FOR_MERGE_TEST.value
                return {
                    "task_id": task_id,
                    "run_id": f"run_{mode.value}",
                    "mode": mode.value,
                    "status": status,
                    "task_status": status,
                    "stale_completion": False,
                    "artifacts": {"report": "", "summary": "", "run_dir": f"/tmp/{mode.value}"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="done",
                project_path=str(root),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            orchestrator._run_implementation_and_notify("task_1", gateway, FakeGatewayEvent(""), loop=None)

            self.assertEqual(orchestrator.modes, [RunMode.IMPLEMENTATION])
            self.assertNotIn("QA run 已完成", gateway.messages[0])
            self.assertIn("实现已完成", gateway.messages[0])
            self.assertIn("测试为可选项", gateway.messages[0])
            self.assertIn("/coding qa task_1", gateway.messages[0])

    def test_implementation_completion_records_gateway_reply_failure(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def start_run(self, task_id, *, mode=RunMode.PLAN_ONLY, runner_name=None, timeout_seconds=None):
                run_dir = self.run_root / task_id / "run_done"
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "summary.md").write_text("实现完成。", encoding="utf-8")
                (run_dir / "report.json").write_text(
                    json.dumps(
                        {
                            "runner": "codex_cli",
                            "status": AgentRunStatus.READY_FOR_MERGE_TEST.value,
                            "mode": RunMode.IMPLEMENTATION.value,
                            "summary_markdown": "实现完成。",
                            "modified_files": ["src/order.ts"],
                            "test_commands": [],
                            "test_results": [],
                            "risks": [],
                            "verification_limitations": [],
                            "human_required": False,
                            "next_actions": [],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return {
                    "task_id": task_id,
                    "run_id": "run_done",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.READY_FOR_MERGE_TEST.value,
                    "task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                    "artifacts": {
                        "run_dir": str(run_dir),
                        "summary": str(run_dir / "summary.md"),
                        "report": str(run_dir / "report.json"),
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="done",
                project_path=str(root),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            orchestrator._run_implementation_and_notify("task_1", AsyncFailingGateway(), FakeGatewayEvent(""), loop=None)

            notification = ledger.get_task("task_1")["task_session"]["last_completion_notification"]
            status_message = orchestrator.command_coding_status("task_1")
            self.assertEqual(notification["status"], "failed")
            self.assertEqual(notification["mode"], RunMode.IMPLEMENTATION.value)
            self.assertEqual(notification["run_id"], "run_done")
            self.assertIn("feishu send failed", notification["reason"])
            self.assertIn("完成回传：失败", status_message)
            self.assertIn("feishu send failed", status_message)

    def test_gateway_qa_command_starts_manual_qa_for_task_with_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspaces" / "task_qa"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_qa",
                source={"type": "manual"},
                requirement_summary="done",
                project_path=str(root),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={"worktree_path": str(workspace), "source_branch": "codex/task_qa"},
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

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding qa task_qa"), gateway=gateway)
            task = ledger.get_task("task_qa")

            self.assertEqual(result["reason"], "handled_by_coding_orchestration")
            self.assertEqual(orchestrator.auto_qa_started[0][0], "task_qa")
            self.assertEqual(task["human_decisions"][-1]["type"], "qa_requested")
            self.assertIn("已开始 QA", gateway.messages[-1])
            self.assertIn("本次 QA 由人工显式触发", gateway.messages[-1])

    def test_targeted_implementation_notification_does_not_auto_run_heavy_qa(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.modes = []

            def start_run(self, task_id, *, mode=RunMode.PLAN_ONLY, runner_name=None, timeout_seconds=None):
                self.modes.append(mode)
                run_dir = self.run_root / task_id / f"run_{mode.value}"
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "execution-policy.json").write_text(
                    json.dumps(
                        {
                            "route": "targeted_ui_fix",
                            "verification": "targeted",
                            "allow_browser_qa": False,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                status = TaskStatus.READY_FOR_MERGE_TEST.value
                return {
                    "task_id": task_id,
                    "run_id": f"run_{mode.value}",
                    "mode": mode.value,
                    "status": status,
                    "task_status": status,
                    "stale_completion": False,
                    "artifacts": {
                        "report": "",
                        "summary": "",
                        "run_dir": str(run_dir),
                        "execution_policy": str(run_dir / "execution-policy.json"),
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="商品标题复制按钮改为复制产品标题",
                project_path=str(root),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            orchestrator._run_implementation_and_notify("task_1", gateway, FakeGatewayEvent(""), loop=None)

            self.assertEqual(orchestrator.modes, [RunMode.IMPLEMENTATION])
            self.assertNotIn("QA run 已完成", gateway.messages[0])
            self.assertIn("实现已完成", gateway.messages[0])

    def test_qa_run_reuses_task_session_collects_qa_artifacts_and_marks_ready(self):
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
                '{"type":"thread.started","thread_id":"019e-qa-thread"}\n',
                encoding="utf-8",
            )

            def write_qa_artifacts(cwd: Path) -> None:
                qa_dir = cwd / ".gstack" / "qa-reports"
                screenshots = qa_dir / "screenshots"
                screenshots.mkdir(parents=True)
                (qa_dir / "qa-report-localhost-2026-05-21.md").write_text(
                    "# QA Report\n\nHealth score: 91 -> 96\n",
                    encoding="utf-8",
                )
                (qa_dir / "baseline.json").write_text('{"healthScore":96}', encoding="utf-8")
                (screenshots / "initial.png").write_text("png", encoding="utf-8")

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
            fake_runner = FakeRunner(mutate=write_qa_artifacts, status=TaskStatus.READY_FOR_MERGE_TEST.value)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run("task_1", mode=RunMode.QA, timeout_seconds=5)
            task = ledger.get_task("task_1")
            run_dir = fake_runner.calls[-1]["run_dir"]
            prompt = Path(run_dir / "input-prompt.md").read_text(encoding="utf-8")
            run_instructions = Path(run_dir / "run-instructions.md")
            manifest = json.loads(Path(run_dir / "run-manifest.json").read_text(encoding="utf-8"))
            latest_run = task["agent_runs"][-1]

            self.assertEqual(result["task_status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.QA)
            self.assertEqual(fake_runner.calls[-1]["workspace_path"], workspace)
            self.assertIn("使用 `$qa` 执行测试链路", prompt)
            self.assertIn("run-instructions.md", prompt)
            self.assertNotIn("verification_limitations", prompt)
            self.assertTrue(run_instructions.exists())
            self.assertIn("verification_limitations", run_instructions.read_text(encoding="utf-8"))
            self.assertEqual(manifest["mode"], "qa")
            self.assertEqual(manifest["resume_session_id"], "019e-qa-thread")
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", manifest["resume_command"])
            self.assertTrue(manifest["dangerous_bypass"])
            self.assertIn("QA reports", manifest["elevated_permission_scope"])
            self.assertEqual(latest_run["qa_artifacts"]["report"].endswith("qa-report-localhost-2026-05-21.md"), True)
            self.assertEqual(latest_run["qa_artifacts"]["baseline"].endswith("baseline.json"), True)
            self.assertEqual(latest_run["qa_artifacts"]["screenshots_dir"].endswith("screenshots"), True)

    def test_qa_run_blocks_uncommitted_implementation_files_before_runner_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            (workspace / "src").mkdir(parents=True)
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=workspace, check=True, stdout=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
            subprocess.run(["git", "add", "src/app.ts"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=workspace, check=True, stdout=subprocess.PIPE)
            (workspace / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")
            status_at_runner_start: list[str] = []

            def record_clean_tree(cwd: Path) -> None:
                status_at_runner_start.append(
                    subprocess.check_output(["git", "status", "--porcelain"], cwd=cwd, text=True)
                )

            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_1"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "order"},
                requirement_summary="修复订单状态展示",
                project_path=str(workspace),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-qa-thread"},
                },
            )
            fake_runner = FakeRunner(mutate=record_clean_tree, status=TaskStatus.READY_FOR_MERGE_TEST.value)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run(task_id, mode=RunMode.QA, timeout_seconds=5)
            task = ledger.get_task(task_id)
            latest_run = task["agent_runs"][-1]
            report = json.loads(Path(latest_run["artifact"]["report"]).read_text(encoding="utf-8"))
            manifest = json.loads(Path(latest_run["artifact"]["manifest"]).read_text(encoding="utf-8"))

            self.assertEqual(status_at_runner_start, [])
            self.assertEqual(fake_runner.calls, [])
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(manifest["qa_checkpoint"]["status"], "failed")
            self.assertEqual(report["verification_limitations"][0]["reason"], "implementation_commit_missing")

    def test_qa_run_blocks_when_clean_tree_gate_fails(self):
        class FailingCheckpointOrchestrator(CodingOrchestrator):
            @staticmethod
            def _prepare_qa_checkpoint(workspace_path, task_id):
                return {
                    "status": "failed",
                    "reason": "implementation_commit_missing",
                    "error": "source worktree has uncommitted changes",
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            (workspace / "src").mkdir(parents=True)
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")

            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_1"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(workspace),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-qa-thread"},
                },
            )
            fake_runner = FakeRunner(status=TaskStatus.READY_FOR_MERGE_TEST.value)
            orchestrator = FailingCheckpointOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run(task_id, mode=RunMode.QA, timeout_seconds=5)
            task = ledger.get_task(task_id)
            report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(fake_runner.calls, [])
            self.assertEqual(result["task_status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["verification_limitations"][0]["reason"], "implementation_commit_missing")
            self.assertIn("让 Codex", report["verification_limitations"][0]["recovery_action"])
            self.assertEqual(report["qa_artifacts"], {"report": "", "baseline": "", "screenshots_dir": ""})
            self.assertEqual(report["tested_commit"], "")


if __name__ == "__main__":
    unittest.main()
