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
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _task_id_from_message, _write_workflow


class ImplementationSessionFlowTest(unittest.TestCase):
    def test_implementation_manifest_records_visible_session_attach_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_43141b20c03e",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={"plan_report": {"branch_slug_candidate": "orderflows-filter-actions"}},
            )
            fake_runner = FakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-visible-session"}\n')
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_43141b20c03e", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_43141b20c03e")
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["session_id"], "019e-visible-session")
            self.assertEqual(manifest["attach_command"], "codex resume 019e-visible-session")
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", manifest["resume_command"])
            self.assertTrue(manifest["dangerous_bypass"])
            self.assertIn("dependency install", manifest["elevated_permissions_reason"])
            self.assertIn("source code changes must stay", manifest["source_modification_boundary"])
            self.assertEqual(manifest["workspace_path"], str(fake_runner.calls[0]["workspace_path"]))
            self.assertEqual(manifest["source_branch"], "codex/orderflows-filter-actions-43141b20c03e")
    def test_task_reuses_one_codex_session_with_incremental_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_52725d8d6ff5",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-one-task-session"}\n')
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_52725d8d6ff5", mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            orchestrator.start_run("task_52725d8d6ff5", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            implementation_call = fake_runner.calls[1]
            manifest = implementation_call["manifest_at_start"]
            prompt = implementation_call["prompt_at_start"]
            self.assertEqual(manifest["resume_session_id"], "019e-one-task-session")
            self.assertEqual(manifest["session_id"], "019e-one-task-session")
            self.assertEqual(manifest["attach_command"], "codex resume 019e-one-task-session")
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", manifest["resume_command"])
            self.assertTrue(manifest["dangerous_bypass"])
            self.assertIn("git metadata", manifest["elevated_permission_scope"])
            self.assertIn("## 复用任务 Session 的本轮增量", prompt)
            self.assertIn("task_52725d8d6ff5", prompt)
            self.assertNotIn("## LLM Wiki 引用", prompt)
            self.assertNotIn("## 已确认的 Plan-only 计划", prompt)
    def test_hermes_autonomous_codex_runner_reuses_codex_session(self):
        class AutonomousFakeRunner(FakeRunner):
            name = "hermes_autonomous_codex"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_autonomous_session",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = AutonomousFakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-autonomous-session"}\n')
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_autonomous_session", mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            orchestrator.start_run("task_autonomous_session", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            manifest = fake_runner.calls[1]["manifest_at_start"]
            self.assertEqual(manifest["runner"], "hermes_autonomous_codex")
            self.assertEqual(manifest["resume_session_id"], "019e-autonomous-session")
            self.assertEqual(manifest["attach_command"], "codex resume 019e-autonomous-session")
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", manifest["resume_command"])
    def test_implementation_prompt_hands_confirmed_plan_to_codex_superpowers_worktree_flow(self):
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
            fake_runner = FakeRunner()
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
            plan_result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            Path(plan_result["artifacts"]["summary"]).write_text(
                "## 已确认计划\n- 修改 src/app.ts\n- 运行 rtk pnpm test",
                encoding="utf-8",
            )

            orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task(task_id)
            implementation_prompt = Path(task["artifacts"][1]["input_prompt"]).read_text(encoding="utf-8")
            run_dir = Path(task["artifacts"][1]["run_dir"])
            confirmed_plan_artifact = run_dir / "confirmed-plan.md"
            run_instructions_artifact = run_dir / "run-instructions.md"
            self.assertTrue(confirmed_plan_artifact.exists())
            self.assertTrue(run_instructions_artifact.exists())
            self.assertIn("修改 src/app.ts", confirmed_plan_artifact.read_text(encoding="utf-8"))
            self.assertIn("verification_limitations", run_instructions_artifact.read_text(encoding="utf-8"))
            self.assertIn("## 已确认计划", implementation_prompt)
            self.assertIn(str(confirmed_plan_artifact), implementation_prompt)
            self.assertIn("按已确认计划实现", implementation_prompt)
            self.assertIn("run-instructions.md", implementation_prompt)
            self.assertNotIn("verification_limitations", implementation_prompt)
            self.assertNotIn("修改 src/app.ts", implementation_prompt)
            self.assertNotIn("superpowers", implementation_prompt)
            self.assertNotIn("using-git-worktrees", implementation_prompt)
            self.assertNotIn("Hermes 控制的任务级隔离 worktree/workspace", implementation_prompt)
            self.assertNotIn("GitOps 实现阶段契约", implementation_prompt)
            self.assertNotIn("GitOps 检查清单", implementation_prompt)
    def test_implementation_run_uses_inline_fast_fix_plan_report_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["订单管理"],
                        }
                    ]
                )
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            task_id = _task_id_from_message(
                orchestrator.command_coding_task(
                    "--project bps-admin 订单管理页面商品标题复制按钮需要复制产品标题，不要复制超链接"
                )
            )
            ledger.update_task_session(
                task_id,
                {
                    "plan_report": {
                        "execution_policy_decision": {
                            "route": "fast_fix",
                            "planning": "inline",
                            "verification": "targeted",
                            "reasoning_summary": "Codex selected inline implementation.",
                        }
                    }
                },
            )

            orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task(task_id)
            implementation_prompt = Path(task["artifacts"][0]["input_prompt"]).read_text(encoding="utf-8")
            run_dir = Path(task["artifacts"][0]["run_dir"])
            confirmed_plan_artifact = run_dir / "confirmed-plan.md"
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertFalse(confirmed_plan_artifact.exists())
            self.assertEqual(manifest["execution_policy"]["route"], "fast_fix")
            self.assertEqual(manifest["execution_policy"]["planning"], "inline")
            self.assertEqual(manifest["execution_policy"]["verification"], "targeted")
            self.assertIn("codex_decision", manifest["execution_policy"]["reasons"])
            self.assertIn("## 轻量实现策略", implementation_prompt)
            self.assertIn("inline planning", implementation_prompt)
            self.assertNotIn("## 已确认计划", implementation_prompt)
            self.assertNotIn("未找到已确认 plan-only 摘要", implementation_prompt)
    def test_followup_implementation_reuses_previous_workspace(self):
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
            fake_runner = FakeRunner()
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

            orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            first_workspace = fake_runner.calls[-1]["workspace_path"]
            orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            self.assertEqual(fake_runner.calls[-1]["workspace_path"], first_workspace)
    def test_failed_timeout_task_can_continue_implementation_in_existing_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            existing_workspace = root / "workspaces" / "task_timeout_continue" / "run_previous"
            (existing_workspace / "src").mkdir(parents=True)
            (existing_workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_timeout_continue",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.FAILED.value,
                phase=TaskPhase.FAILED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/orderflows-filter-actions-timeout",
                    "worktree_path": str(existing_workspace),
                    "runner": {"resume_session_id": "019e-timeout-session"},
                },
            )
            ledger.append_agent_run(
                "task_timeout_continue",
                {
                    "run_id": "run_previous",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.TIMEOUT.value,
                    "workspace_path": str(existing_workspace),
                    "artifact": {"run_dir": str(root / "runs" / "task_timeout_continue" / "run_previous")},
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

            message = orchestrator.command_coding_implement("task_timeout_continue")

            self.assertIn("实现已完成", message)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.IMPLEMENTATION)
            self.assertEqual(fake_runner.calls[-1]["workspace_path"], existing_workspace)
            self.assertEqual(fake_runner.calls[-1]["manifest_at_start"]["resume_session_id"], "019e-timeout-session")
    def test_bug_task_links_parent_task_and_recovers_parent_run_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            wiki.upsert(
                {
                    "kind": "run_summary",
                    "title": "原任务上下文",
                    "body": "原任务修改了 shipping adapter，QA 关注库存回滚。",
                    "source_refs": [{"type": "task", "task_id": "task_parent", "run_id": "run_parent"}],
                    "project": "order-system",
                    "module": "shipping",
                    "tags": ["qa"],
                    "confidence": "medium",
                    "status": "draft",
                },
                options={"dedupe_key": "parent-run-summary"},
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

            task_id = _task_id_from_message(
                orchestrator.command_coding_task("--project 订单系统 --bug-of task_parent 修复 QA 缺陷")
            )
            orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            task = ledger.get_task(task_id)
            prompt = Path(task["artifacts"][0]["input_prompt"]).read_text(encoding="utf-8")
            run_dir = Path(task["artifacts"][0]["run_dir"])
            wiki_context = run_dir / "wiki-context.md"
            self.assertEqual(task["source"]["related_task_id"], "task_parent")
            self.assertTrue(wiki_context.exists())
            self.assertIn("库存回滚", wiki_context.read_text(encoding="utf-8"))
            self.assertIn(str(wiki_context), prompt)
            self.assertNotIn("库存回滚", prompt)
