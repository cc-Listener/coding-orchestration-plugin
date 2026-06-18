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
from tests.orchestrator_flow_fixtures import (
    FakeBackgroundQueuedRunner,
    FakeGateway,
    FakeGatewayEvent,
    FakeRouter,
    FakeRunner,
    _task_id_from_message,
    _write_workflow,
)


class PlanRunFlowTest(unittest.TestCase):
    def test_plan_only_completion_reply_includes_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
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
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()
            created = orchestrator._create_task_from_text("订单系统有个需求，新增发货状态筛选")

            orchestrator._run_plan_only_and_notify(
                created.task_id,
                gateway,
                FakeGatewayEvent("订单系统有个需求，新增发货状态筛选"),
                None,
            )

            self.assertIn("计划已生成", gateway.messages[0])
            self.assertIn("计划完成", gateway.messages[0])
            self.assertIn("人工 review 后合并 test", gateway.messages[0])
    def test_background_plan_only_waits_for_final_report_before_replying(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")

            class CompletingAfterStartOrchestrator(CodingOrchestrator):
                def start_run(self, task_id, *, mode=RunMode.PLAN_ONLY, runner_name=None, timeout_seconds=None):
                    result = super().start_run(
                        task_id,
                        mode=mode,
                        runner_name=runner_name,
                        timeout_seconds=timeout_seconds,
                    )
                    report_path = Path(result["artifacts"]["report"])
                    final_report = {
                        "runner": "codex",
                        "status": "success",
                        "mode": RunMode.PLAN_ONLY.value,
                        "summary_markdown": "## 计划\n- 改为复制产品标题",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": ["确认后开始实现。"],
                        "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
                        "tested_commit": "",
                    }
                    report_path.write_text(json.dumps(final_report, ensure_ascii=False), encoding="utf-8")
                    return result

            orchestrator = CompletingAfterStartOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeBackgroundQueuedRunner()),
            )
            gateway = FakeGateway()
            task_id = "task_background_done"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "order"},
                requirement_summary="复制产品标题",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.DRAFT.value,
            )

            orchestrator._run_plan_only_and_notify(
                task_id,
                gateway,
                FakeGatewayEvent("复制产品标题"),
                None,
            )
            task = ledger.get_task(task_id)

            self.assertEqual(len(gateway.messages), 1)
            self.assertIn("计划已生成", gateway.messages[0])
            self.assertIn("改为复制产品标题", gateway.messages[0])
            self.assertIn("请人工确认计划完整度和正确性", gateway.messages[0])
            self.assertNotIn("Hermes runtime 已启动后台 Codex 任务", gateway.messages[0])
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLAN_READY.value)
            self.assertIsNone(task["task_session"]["runner"].get("active_run_id"))
    def test_unstructured_completion_reply_includes_stderr_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report_path = run_dir / "report.json"
            stderr_path = run_dir / "stderr.log"
            report_path.write_text(
                json.dumps(
                    {
                        "status": "completed_unstructured",
                        "risks": ["Structured report was not produced."],
                        "next_actions": ["Review stderr."],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stderr_path.write_text("unexpected argument '--ask-for-approval' found", encoding="utf-8")

            message = CodingOrchestrator._format_run_completion_message(
                "task_1",
                {
                    "run_id": "run_1",
                    "task_status": "blocked",
                    "artifacts": {
                        "run_dir": str(run_dir),
                        "report": str(report_path),
                        "stderr": str(stderr_path),
                        "summary": str(run_dir / "summary.md"),
                    },
                },
            )

            self.assertIn("计划已生成", message)
            self.assertIn("结果状态：受阻(blocked)", message)
            self.assertIn("Structured report was not produced.", message)
            self.assertIn("unexpected argument", message)
    def test_plan_only_completion_reply_asks_human_to_confirm_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report_path = run_dir / "report.json"
            summary_path = run_dir / "summary.md"
            report_path.write_text(
                json.dumps(
                    {
                        "status": "success",
                        "risks": [],
                        "next_actions": ["确认后开始实现。"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            summary_path.write_text("## 计划\n- 增加状态筛选", encoding="utf-8")

            message = CodingOrchestrator._format_run_completion_message(
                "task_1",
                {
                    "run_id": "run_1",
                    "task_status": "ready_for_merge_test",
                    "artifacts": {
                        "run_dir": str(run_dir),
                        "report": str(report_path),
                        "summary": str(summary_path),
                    },
                },
            )

            self.assertIn("计划已生成", message)
            self.assertIn("增加状态筛选", message)
            self.assertIn("请人工确认计划完整度和正确性", message)
    def test_plan_only_run_generates_artifacts_updates_ledger_and_writes_run_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            wiki_ref = wiki.upsert(
                {
                    "kind": "verified_knowledge",
                    "title": "发货模块知识",
                    "body": "发货失败先检查 shipping service。",
                    "source_refs": [],
                    "project": "order-system",
                    "module": "shipping",
                    "tags": ["shipping"],
                    "confidence": "high",
                    "status": "verified",
                },
                options={"dedupe_key": "shipping"},
            )
            resolver = ProjectResolver(
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
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_task("--project 订单系统 修复发货失败")
            task_id = _task_id_from_message(message)
            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            task = ledger.get_task(task_id)
            self.assertEqual(result["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["llm_wiki_refs"][0]["id"], wiki_ref["id"])
            self.assertEqual(len(task["agent_runs"]), 1)
            self.assertTrue(Path(task["artifacts"][0]["input_prompt"]).exists())
            prompt = Path(task["artifacts"][0]["input_prompt"]).read_text(encoding="utf-8")
            run_dir = Path(task["artifacts"][0]["run_dir"])
            wiki_context = run_dir / "wiki-context.md"
            self.assertTrue(wiki_context.exists())
            self.assertIn("发货失败先检查 shipping service", wiki_context.read_text(encoding="utf-8"))
            self.assertIn(str(wiki_context), prompt)
            self.assertNotIn("发货失败先检查 shipping service", prompt)
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["task_id"], task_id)
            self.assertEqual(manifest["mode"], "plan-only")
            self.assertEqual(manifest["task_phase"], "draft")
            self.assertIsNone(manifest["source_branch"])
            self.assertEqual(manifest["permission_profile"], "plan_read_only")
            self.assertFalse(manifest["dangerous_bypass"])
            self.assertIsNone(manifest["elevated_permissions_reason"])
            self.assertEqual(manifest["elevated_permission_scope"], [])
            self.assertIsNone(manifest["source_modification_boundary"])
            summaries = wiki.search("计划完成", {"project": "order-system"})
            self.assertEqual(summaries[0]["kind"], "run_summary")
    def test_plan_only_runner_task_status_is_normalized_before_state_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
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
            )
            fake_runner = FakeRunner(status=TaskStatus.PLANNED.value)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_task("--project 订单系统 修复发货失败")
            task_id = _task_id_from_message(message)
            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            task = ledger.get_task(task_id)
            report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))
            self.assertEqual(result["status"], AgentRunStatus.SUCCESS.value)
            self.assertEqual(report["status"], AgentRunStatus.SUCCESS.value)
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLAN_READY.value)
            self.assertEqual(task["agent_runs"][0]["status"], AgentRunStatus.SUCCESS.value)
    def test_plan_only_blocks_if_runner_modifies_project_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
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
            )

            def mutate_during_plan(cwd: Path) -> None:
                (cwd / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")

            fake_runner = FakeRunner(mutate=mutate_during_plan)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            task_id = _task_id_from_message(
                orchestrator.command_coding_task("--project 订单系统 修复发货失败")
            )

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            task = ledger.get_task(task_id)
            report = json.loads(Path(task["artifacts"][0]["report"]).read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["verification_limitations"][0]["reason"], "diff_guard_violation")
            self.assertIn("plan-only run modified src/app.ts", "\n".join(report["risks"]))
