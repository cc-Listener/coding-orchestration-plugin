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
from coding_orchestration import task_status_presenter
from coding_orchestration.project_knowledge_resolver import ProjectKnowledgeResolver
from coding_orchestration.project_workitem_binding import ProjectWorkitemIdentity
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
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


class StatusReconcileFlowTest(unittest.TestCase):
    def test_coding_status_shows_latest_qa_report_health_and_known_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "workspaces" / "task_status" / ".gstack" / "qa-reports"
            report_dir.mkdir(parents=True)
            qa_report = report_dir / "qa-report-localhost-2026-05-21.md"
            qa_report.write_text("# QA Report\n\nHealth score: 81 -> 94\n", encoding="utf-8")
            run_dir = root / "runs" / "task_status" / "run_qa"
            run_dir.mkdir(parents=True)
            report_json = run_dir / "report.json"
            report_json.write_text(
                json.dumps(
                    {
                        "status": AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value,
                        "summary_markdown": "QA 完成，登录态受限",
                        "verification_limitations": [
                            {
                                "reason": "auth_required",
                                "impact": "无法覆盖登录后完整流程",
                                "recovery_action": "补充登录态后重新 QA",
                                "fallback_evidence": str(qa_report),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_status"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual"},
                requirement_summary="需求",
                project_path=str(root),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_qa",
                    "runner": "codex_cli",
                    "mode": RunMode.QA.value,
                    "status": AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value,
                    "artifact": {"report": str(report_json)},
                    "qa_artifacts": {"report": str(qa_report)},
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

            message = orchestrator.command_coding_status(task_id)

            self.assertIn("QA report：", message)
            self.assertIn(str(qa_report), message)
            self.assertIn("QA health score：81 -> 94", message)
            self.assertIn("已知缺口：", message)
            self.assertIn("auth_required", message)
            self.assertIn("补充登录态后重新 QA", message)

    def test_coding_status_reconciles_completed_active_background_plan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "task_status_reconcile" / "run_done"
            run_dir.mkdir(parents=True)
            report_json = run_dir / "report.json"
            report_json.write_text(
                json.dumps(
                    {
                        "runner": "codex",
                        "status": "blocked",
                        "mode": RunMode.PLAN_ONLY.value,
                        "summary_markdown": "需要确认目标页面和后端字段。",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": ["后端字段未确认"],
                        "verification_limitations": [
                            {
                                "reason": "field_contract_missing",
                                "impact": "不能安全实现订单筛选。",
                                "recovery_action": "确认目标页面和订单列表请求字段。",
                                "fallback_evidence": ".api-spec.json",
                            }
                        ],
                        "human_required": True,
                        "next_actions": ["确认 `/orders` 还是 `/orderFlows`。"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "summary.md").write_text("Hermes runtime 已启动后台 Codex 任务。", encoding="utf-8")
            (run_dir / "stdout.log").write_text("{}", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            (run_dir / "diff.patch").write_text("", encoding="utf-8")

            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_status_reconcile"
            artifact = {
                "run_dir": str(run_dir),
                "input_prompt": str(run_dir / "input-prompt.md"),
                "manifest": str(run_dir / "run-manifest.json"),
                "stdout": str(run_dir / "stdout.log"),
                "stderr": str(run_dir / "stderr.log"),
                "events": str(run_dir / "events.jsonl"),
                "report": str(report_json),
                "summary": str(run_dir / "summary.md"),
                "diff": str(run_dir / "diff.patch"),
            }
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLANNING.value,
                task_session={
                    "runner": {
                        "provider": "codex_cli",
                        "active_run_id": "run_done",
                        "active_mode": RunMode.PLAN_ONLY.value,
                        "last_run_status": "queued",
                    }
                },
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_done",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": "queued",
                    "artifact": artifact,
                    "diff_guard": {"changed_files": [], "violations": []},
                },
            )
            ledger.append_artifact(task_id, artifact)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            original_reader = task_status_presenter.read_report_json
            task_status_presenter.read_report_json = lambda _path: (_ for _ in ()).throw(
                AssertionError("active run reconcile must not use task status presenter to read report artifacts")
            )
            try:
                message = orchestrator._status_for_event(task_id, FakeGatewayEvent(""))
            finally:
                task_status_presenter.read_report_json = original_reader
            task = ledger.get_task(task_id)

            self.assertIn("已自动回收后台执行：run_done", message)
            self.assertIn("状态：受阻(blocked)", message)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["phase"], TaskPhase.BLOCKED.value)
            self.assertIsNone(task["task_session"]["runner"].get("active_run_id"))
            self.assertIsNone(task["task_session"]["runner"].get("active_mode"))
            self.assertEqual(task["task_session"]["runner"]["last_run_status"], "blocked")
            self.assertEqual(task["task_session"]["runner"]["provider"], "codex_cli")
            self.assertEqual(json.loads(report_json.read_text(encoding="utf-8"))["runner"], "codex_cli")
            self.assertEqual(task["agent_runs"][0]["status"], "blocked")
            self.assertEqual(task["agent_runs"][0]["runner"], "codex_cli")
            self.assertEqual(len(task["agent_runs"]), 1)
            self.assertEqual((run_dir / "summary.md").read_text(encoding="utf-8"), "需要确认目标页面和后端字段。")

    def test_reconcile_completed_implementation_blocks_when_report_is_not_landed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "task_impl_reconcile" / "run_done"
            run_dir.mkdir(parents=True)
            report_json = run_dir / "report.json"
            report_json.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": AgentRunStatus.SUCCEEDED.value,
                        "mode": RunMode.IMPLEMENTATION.value,
                        "summary_markdown": "实现未提交。",
                        "modified_files": ["src/app.ts"],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": [],
                        "implementation_landed": False,
                        "commit_sha": "",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "summary.md").write_text("Hermes runtime 已启动后台 Codex 任务。", encoding="utf-8")
            (run_dir / "stdout.log").write_text("{}", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            (run_dir / "diff.patch").write_text("", encoding="utf-8")

            task_id = "task_impl_reconcile"
            artifact = {
                "run_dir": str(run_dir),
                "input_prompt": str(run_dir / "input-prompt.md"),
                "manifest": str(run_dir / "run-manifest.json"),
                "stdout": str(run_dir / "stdout.log"),
                "stderr": str(run_dir / "stderr.log"),
                "events": str(run_dir / "events.jsonl"),
                "report": str(report_json),
                "summary": str(run_dir / "summary.md"),
                "diff": str(run_dir / "diff.patch"),
            }
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.IMPLEMENTING.value,
                task_session={
                    "runner": {
                        "provider": "codex_cli",
                        "active_run_id": "run_done",
                        "active_mode": RunMode.IMPLEMENTATION.value,
                        "last_run_status": "queued",
                    }
                },
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_done",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": "queued",
                    "artifact": artifact,
                    "diff_guard": {"changed_files": ["src/app.ts"], "violations": []},
                },
            )
            ledger.append_artifact(task_id, artifact)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator._status_for_event(task_id, FakeGatewayEvent(""))
            task = ledger.get_task(task_id)
            reconciled_report = json.loads(report_json.read_text(encoding="utf-8"))

            self.assertIn("已自动回收后台执行：run_done", message)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["phase"], TaskPhase.BLOCKED.value)
            self.assertEqual(task["agent_runs"][0]["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(task["agent_runs"][0]["failure_type"], "implementation_not_landed")
            self.assertEqual(reconciled_report["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(reconciled_report["failure_type"], "implementation_not_landed")
            self.assertEqual(reconciled_report["status_detail"], "implementation_not_landed")

    def test_start_run_reconciles_completed_active_run_before_blocking_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "task_retry_reconcile" / "run_old"
            run_dir.mkdir(parents=True)
            report_json = run_dir / "report.json"
            report_json.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": "success",
                        "mode": RunMode.PLAN_ONLY.value,
                        "summary_markdown": "旧计划已完成。",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": ["可以继续重新规划。"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "summary.md").write_text("Hermes runtime 已启动后台 Codex 任务。", encoding="utf-8")
            (run_dir / "stdout.log").write_text("{}", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            (run_dir / "diff.patch").write_text("", encoding="utf-8")

            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_retry_reconcile"
            artifact = {
                "run_dir": str(run_dir),
                "input_prompt": str(run_dir / "input-prompt.md"),
                "manifest": str(run_dir / "run-manifest.json"),
                "stdout": str(run_dir / "stdout.log"),
                "stderr": str(run_dir / "stderr.log"),
                "events": str(run_dir / "events.jsonl"),
                "report": str(report_json),
                "summary": str(run_dir / "summary.md"),
                "diff": str(run_dir / "diff.patch"),
            }
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLANNING.value,
                task_session={
                    "runner": {
                        "provider": "codex_cli",
                        "active_run_id": "run_old",
                        "active_mode": RunMode.PLAN_ONLY.value,
                        "last_run_status": "queued",
                    }
                },
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_old",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": "queued",
                    "artifact": artifact,
                    "diff_guard": {"changed_files": [], "violations": []},
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

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            task = ledger.get_task(task_id)

            self.assertEqual(result["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(len(fake_runner.calls), 1)
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["agent_runs"][0]["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(task["agent_runs"][1]["status"], AgentRunStatus.SUCCEEDED.value)

    def test_start_run_writes_execution_policy_from_plan_report_to_manifest_and_context_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_codex_policy"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="这个task需要简单修一个小问题，.gstack的文件不要放到git上，做一个忽略",
                project_path=str(project),
                status=TaskStatus.NEW.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.DRAFT.value,
                task_session={
                    "plan_report": {
                        "execution_policy_decision": {
                            "route": "fast_fix",
                            "planning": "inline",
                            "verification": "targeted",
                            "reasoning_summary": "Codex selected a fast policy.",
                        }
                    }
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

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            run_dir = Path(result["artifacts"]["run_dir"])
            context_index = json.loads((run_dir / "context-index.json").read_text(encoding="utf-8"))
            prompt = (run_dir / "input-prompt.md").read_text(encoding="utf-8")

            self.assertEqual(fake_runner.calls[0]["manifest_at_start"]["execution_policy"]["route"], "fast_fix")
            self.assertEqual(context_index["execution_policy"]["route"], "fast_fix")
            self.assertIn("execution-policy.json", prompt)
            self.assertIn("execution-policy.json", result["artifacts"]["execution_policy"])

    def test_start_run_without_plan_report_decision_uses_safe_plan_only_execution_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_missing_policy"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单管理页面商品标题复制按钮需要复制产品标题，不要复制超链接",
                project_path=str(project),
                status=TaskStatus.NEW.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.DRAFT.value,
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

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            run_dir = Path(result["artifacts"]["run_dir"])
            context_index = json.loads((run_dir / "context-index.json").read_text(encoding="utf-8"))
            policy = fake_runner.calls[0]["manifest_at_start"]["execution_policy"]

            self.assertEqual(policy["route"], "standard_change")
            self.assertEqual(policy["planning"], "plan_only")
            self.assertEqual(policy["verification"], "standard")
            self.assertEqual(policy["reasons"], ["codex_decision_missing"])
            self.assertEqual(context_index["execution_policy"]["planning"], "plan_only")
