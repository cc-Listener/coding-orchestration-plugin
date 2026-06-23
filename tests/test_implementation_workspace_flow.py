from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import RunMode, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _task_id_from_message, _write_workflow


class ImplementationWorkspaceFlowTest(unittest.TestCase):
    def test_implementation_run_uses_workspace_and_blocks_unauthorized_diff(self):
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

            def mutate_outside_allowed(cwd: Path):
                (cwd / "deploy").mkdir()
                (cwd / "deploy" / "release.sh").write_text("echo no\n", encoding="utf-8")

            fake_runner = FakeRunner(mutate=mutate_outside_allowed)
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

            result = orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task(task_id)
            report = json.loads(Path(task["artifacts"][0]["report"]).read_text(encoding="utf-8"))
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(task["status"], "blocked")
            self.assertTrue(fake_runner.calls[0]["workspace_path"].is_dir())
            self.assertEqual(task["task_session"]["source_branch"], f"codex/task-{task_id.removeprefix('task_')}")
            self.assertEqual(task["task_session"]["worktree_path"], str(fake_runner.calls[0]["workspace_path"]))
            self.assertEqual(manifest["source_branch"], f"codex/task-{task_id.removeprefix('task_')}")
            self.assertFalse((project / "deploy" / "release.sh").exists())
            self.assertEqual(report["status"], "blocked")
            self.assertIn("deploy/release.sh", "\n".join(report["risks"]))
            self.assertEqual(report["verification_limitations"][0]["reason"], "diff_guard_violation")
    def test_implementation_branch_uses_plan_report_candidate_and_short_task_id(self):
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
                task_session={"plan_report": {"branch_slug_candidate": "fix-order-status"}},
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

            orchestrator.start_run("task_43141b20c03e", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_43141b20c03e")
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(task["task_session"]["source_branch"], "codex/fix-order-status-43141b20c03e")
            self.assertEqual(manifest["source_branch"], "codex/fix-order-status-43141b20c03e")
    def test_implementation_branch_sanitizes_plan_report_candidate_without_requirement_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_d7bd20850ef5",
                source={"type": "feishu_chat", "project_name": "bps-admin"},
                requirement_summary=(
                    "BPS运营后台新增需求：推单列表分类推单类型需要增加推单类型，"
                    "这是最新的swagger文档 http://10.15.130.144:6060/api/bps_ops/v1/swagger/index.html"
                    "#/%E8%AE%A2%E5%8D%95/post_api_bps_ops_v2_order_fulfill_task_list；"
                    "共xx条记录要替换为“共xx条记录,x单已推到OMS，x单虚拟产品无需推单”。"
                    "对应字段：推OMS = total - total_virtual；虚拟品 = total_virtual。"
                ),
                project_path=str(project),
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={"plan_report": {"branch_slug_candidate": "修复 订单/status!!!"}},
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

            orchestrator.start_run("task_d7bd20850ef5", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_d7bd20850ef5")
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(task["task_session"]["source_branch"], "codex/status-d7bd20850ef5")
            self.assertEqual(manifest["source_branch"], "codex/status-d7bd20850ef5")
    def test_implementation_branch_uses_candidate_from_prior_plan_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_plan_to_impl",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="修复订单状态展示",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(
                report_updates={
                    "branch_slug_candidate": "fix-order-status",
                    "execution_policy_decision": {
                        "route": "standard_change",
                        "planning": "plan_only",
                        "verification": "targeted",
                        "reasoning_summary": "Codex selected branch candidate.",
                    },
                    "implementation_landed": False,
                    "commit_sha": "",
                    "changed_files_summary": [],
                    "merge_readiness": {
                        "ready": False,
                        "risk_level": "unknown",
                        "risk_note": "plan-only default",
                        "required_confirmation": False,
                    },
                }
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_plan_to_impl", mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            implementation = orchestrator.start_run("task_plan_to_impl", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_plan_to_impl")
            manifest = json.loads(Path(implementation["artifacts"]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(task["task_session"]["plan_report"]["branch_slug_candidate"], "fix-order-status")
            self.assertEqual(
                task["task_session"]["plan_report"]["execution_policy_decision"]["route"],
                "standard_change",
            )
            self.assertNotIn("implementation_landed", task["task_session"]["plan_report"])
            self.assertNotIn("commit_sha", task["task_session"]["plan_report"])
            self.assertNotIn("changed_files_summary", task["task_session"]["plan_report"])
            self.assertNotIn("merge_readiness", task["task_session"]["plan_report"])
            self.assertEqual(task["task_session"]["source_branch"], "codex/fix-order-status-plan_to_impl")
            self.assertEqual(manifest["source_branch"], "codex/fix-order-status-plan_to_impl")
    def test_implementation_worktree_defaults_to_main_even_when_project_on_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            _write_workflow(project)
            (project / "main-only.txt").write_text("main\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "main baseline"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "checkout", "-b", "test"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (project / "test-only.txt").write_text("test\n", encoding="utf-8")
            subprocess.run(["git", "add", "test-only.txt"], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "test-only change"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_base_main",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="修复发货失败",
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

            orchestrator.start_run("task_base_main", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_base_main")
            workspace = fake_runner.calls[0]["workspace_path"]
            manifest = fake_runner.calls[0]["manifest_at_start"]
            branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=workspace, text=True).strip()
            self.assertEqual(branch, task["task_session"]["source_branch"])
            self.assertEqual(task["task_session"]["source_base_branch"], "main")
            self.assertEqual(manifest["source_base_branch"], "main")
            self.assertTrue((workspace / "main-only.txt").exists())
            self.assertFalse((workspace / "test-only.txt").exists())
    def test_implementation_run_commits_changes_after_runner_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            _write_workflow(project)
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "main baseline"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            def mutate_implementation(cwd: Path) -> None:
                (cwd / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")
                (cwd / "src" / "new-page.ts").write_text("export const page = true\n", encoding="utf-8")
                subprocess.run(["git", "add", "src/app.ts", "src/new-page.ts"], cwd=cwd, check=True, stdout=subprocess.PIPE)
                subprocess.run(
                    ["git", "commit", "-m", "fix(order): 修复发货失败"],
                    cwd=cwd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_impl_commit",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="修复发货失败",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(mutate=mutate_implementation)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run("task_impl_commit", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_impl_commit")
            workspace = fake_runner.calls[0]["workspace_path"]
            last_commit = subprocess.check_output(["git", "log", "-1", "--pretty=%s"], cwd=workspace, text=True).strip()
            status = subprocess.check_output(["git", "status", "--porcelain"], cwd=workspace, text=True)
            manifest = json.loads(Path(result["artifacts"]["manifest"]).read_text(encoding="utf-8"))
            latest_run = task["agent_runs"][-1]

            self.assertEqual(result["task_status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(last_commit, "fix(order): 修复发货失败")
            self.assertEqual(status, "")
            self.assertIsNone(manifest.get("implementation_checkpoint"))
            self.assertIsNone(latest_run["implementation_checkpoint"])
    def test_implementation_success_blocks_when_codex_leaves_uncommitted_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            _write_workflow(project)
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "main baseline"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            def mutate_without_commit(cwd: Path) -> None:
                (cwd / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_missing_commit",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="修复发货失败",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(mutate=mutate_without_commit)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run("task_missing_commit", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(result["task_status"], TaskStatus.BLOCKED.value)
            self.assertEqual(report["verification_limitations"][0]["reason"], "implementation_commit_missing")
            self.assertIn("Codex", report["verification_limitations"][0]["recovery_action"])
