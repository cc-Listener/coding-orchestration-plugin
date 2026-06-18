from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


class ImplementationResultFlowTest(unittest.TestCase):
    def test_implementation_unstructured_status_stays_blocked_on_real_run_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_unstructured_impl",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(
                status="completed_unstructured",
                report_updates={
                    "implementation_landed": True,
                    "commit_sha": "abc123",
                    "changed_files_summary": ["src/app.ts: implementation landed"],
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run("task_unstructured_impl", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            task = ledger.get_task("task_unstructured_impl")
            report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(result["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(result["task_status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["phase"], TaskPhase.BLOCKED.value)
            self.assertEqual(report["status"], AgentRunStatus.BLOCKED.value)
            self.assertFalse(report["structured"])
            self.assertEqual(report["status_detail"], "completed_unstructured")
            self.assertEqual(report["task_status"], TaskStatus.BLOCKED.value)
    def test_implementation_unknown_status_stays_blocked_on_real_run_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_unknown_impl",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(
                status="ready_for_implementation",
                report_updates={
                    "implementation_landed": True,
                    "commit_sha": "abc123",
                    "changed_files_summary": ["src/app.ts: implementation landed"],
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run("task_unknown_impl", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            task = ledger.get_task("task_unknown_impl")
            report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(result["task_status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(report["status"], AgentRunStatus.BLOCKED.value)
            self.assertFalse(report["structured"])
            self.assertEqual(report["raw_status"], "ready_for_implementation")
            self.assertEqual(report["status_detail"], "completed_unstructured")
    def test_orchestrator_does_not_have_report_says_no_implementation_keyword_scanner(self):
        self.assertFalse(hasattr(CodingOrchestrator, "_report_says_no_implementation"))
    def test_implementation_default_timeout_is_longer_than_plan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_timeout_defaults",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
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

            orchestrator.start_run("task_timeout_defaults", mode=RunMode.IMPLEMENTATION)

            manifest = fake_runner.calls[0]["manifest_at_start"]
            self.assertEqual(fake_runner.calls[0]["timeout_seconds"], 10800)
            self.assertEqual(manifest["timeout_seconds"], 10800)
            self.assertGreater(manifest["timeout_seconds"], orchestrator.default_timeout_seconds)
    def test_implementation_success_enters_ready_for_merge_test_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_ready_merge",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
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

            result = orchestrator.start_run("task_ready_merge", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            task = ledger.get_task("task_ready_merge")

            self.assertEqual(result["task_status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
    def test_implementation_completion_message_prompts_manual_merge_test(self):
        message = CodingOrchestrator._format_implementation_completion_message(
            "task_ready_merge",
            {
                "run_id": "run_impl",
                "task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                "artifacts": {"report": "", "summary": "", "run_dir": "/tmp/run_impl"},
            },
        )

        self.assertIn("实现已完成", message)
        self.assertIn("结果状态：等待手动执行 merge test(ready_for_merge_test)", message)
        self.assertIn("/coding qa task_ready_merge", message)
        self.assertIn("/coding merge-test task_ready_merge", message)
        self.assertIn("测试为可选项", message)
        self.assertIn("QA 和 merge-test 都需要人工触发", message)
    def test_implementation_completion_message_uses_user_facing_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report = {
                "user_facing_summary": "已修复订单状态展示，并提交实现。",
                "technical_summary": "修改状态映射。",
                "next_actions": ["发送 /coding qa task_1 继续测试"],
                "risk_note": "只跑了定点测试。",
                "risks": [],
            }
            (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
            result = {
                "run_id": "run_1",
                "task_status": "ready_for_merge_test",
                "artifacts": {
                    "report": str(run_dir / "report.json"),
                    "run_dir": str(run_dir),
                },
            }

            message = CodingOrchestrator._format_implementation_completion_message("task_1", result)

            self.assertIn("实现已完成", message)
            self.assertIn("结果状态：等待手动执行 merge test(ready_for_merge_test)", message)
            self.assertIn("已修复订单状态展示", message)
            self.assertIn("/coding qa task_1", message)
            self.assertIn("风险提示：只跑了定点测试。", message)
            self.assertNotIn("implementation run 已完成", message)
            self.assertNotIn("artifact：", message)
            self.assertNotIn("artifact=", message)
            self.assertNotIn("调试信息", message)
    def test_implementation_completion_message_keeps_failed_status_visible(self):
        message = CodingOrchestrator._format_implementation_completion_message(
            "task_failed",
            {
                "run_id": "run_failed",
                "task_status": TaskStatus.FAILED.value,
                "artifacts": {"report": "", "summary": "", "run_dir": "/tmp/run_failed"},
            },
        )

        self.assertIn("结果状态：失败(failed)", message)
        self.assertNotIn("artifact=", message)
        self.assertNotIn("调试信息", message)
    def test_implementation_completion_message_dedupes_next_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            action = "如人工确认现有验证已足够，发送 /coding merge-test task_1。"
            report = {
                "user_facing_summary": "已提交实现。",
                "next_actions": [action, action],
                "risks": [],
            }
            (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")

            message = CodingOrchestrator._format_implementation_completion_message(
                "task_1",
                {
                    "run_id": "run_1",
                    "task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                    "artifacts": {"report": str(run_dir / "report.json"), "run_dir": str(run_dir)},
                },
            )

            self.assertEqual(message.count(action), 1)
    def test_implementation_blocked_after_changes_stays_blocked_without_codex_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_known_gaps",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )

            def mutate_allowed_file(cwd: Path):
                (cwd / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")

            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner(mutate=mutate_allowed_file, status="blocked")),
            )

            result = orchestrator.start_run("task_known_gaps", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            task = ledger.get_task("task_known_gaps")
            report = json.loads(Path(task["artifacts"][0]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(result["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(result["task_status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["phase"], TaskPhase.BLOCKED.value)
            self.assertEqual(report["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(report["raw_status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(report["status_detail"], "")
            self.assertEqual(report["task_status"], TaskStatus.BLOCKED.value)
            self.assertFalse(report["known_gaps"])
            self.assertEqual(report["verification_limitations"][0]["reason"], "blocked_or_partial_without_details")
    def test_implementation_timeout_after_changes_stays_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_timeout",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )

            def mutate_allowed_file(cwd: Path):
                (cwd / "src" / "app.ts").write_text("export const ok = 'timeout-progress'\n", encoding="utf-8")

            runner_timeout_limitation = {
                "reason": "runner_timeout",
                "impact": "Runner timed out before final report.",
                "recovery_action": "Resume the same Codex session and continue.",
                "fallback_evidence": "stdout.log; stderr.log",
            }
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(
                    FakeRunner(
                        mutate=mutate_allowed_file,
                        status="timeout",
                        verification_limitations=[runner_timeout_limitation],
                    )
                ),
            )

            result = orchestrator.start_run("task_timeout", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            task = ledger.get_task("task_timeout")
            report = json.loads(Path(task["artifacts"][0]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(result["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(result["task_status"], TaskStatus.FAILED.value)
            self.assertEqual(task["status"], TaskStatus.FAILED.value)
            self.assertEqual(task["phase"], TaskPhase.FAILED.value)
            self.assertEqual(report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(report["raw_status"], "timeout")
            self.assertEqual(report["failure_type"], "timeout")
            self.assertEqual(report["task_status"], TaskStatus.FAILED.value)
            self.assertFalse(report["known_gaps"])
            self.assertEqual(report["verification_limitations"][0]["reason"], "runner_timeout")
    def test_implementation_timeout_without_changes_stays_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_timeout_empty",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner(status="timeout")),
            )

            result = orchestrator.start_run("task_timeout_empty", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            task = ledger.get_task("task_timeout_empty")
            report = json.loads(Path(task["artifacts"][0]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(result["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(result["task_status"], TaskStatus.FAILED.value)
            self.assertEqual(task["status"], TaskStatus.FAILED.value)
            self.assertEqual(task["phase"], TaskPhase.FAILED.value)
            self.assertEqual(report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(report["task_status"], TaskStatus.FAILED.value)
            self.assertEqual(report["raw_status"], "timeout")
            self.assertEqual(report["failure_type"], "timeout")
            self.assertEqual(report["verification_limitations"][0]["reason"], "blocked_or_partial_without_details")
