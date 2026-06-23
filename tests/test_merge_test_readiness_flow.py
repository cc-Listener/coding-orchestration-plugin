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
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


class MergeTestReadinessFlowTest(unittest.TestCase):
    def test_blocked_merge_test_uses_codex_merge_readiness_for_semantic_risk(self):
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
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "merge_readiness": {
                            "ready": True,
                            "risk_level": "medium",
                            "risk_note": "验证受限，但实现提交存在且变更范围清楚。",
                            "required_confirmation": True,
                        },
                        "verification_limitations": [
                            {
                                "reason": "targeted_tests_only",
                                "impact": "未跑全量回归。",
                                "recovery_action": "人工接受风险后继续 merge-test。",
                                "fallback_evidence": "summary.md",
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
                requirement_summary="semantic risk",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/fix-order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-session"},
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
                    "source_branch": "codex/fix-order-task_1",
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

            assessment = orchestrator._blocked_task_merge_test_assessment(ledger.get_task("task_1"))

            self.assertTrue(assessment["mergeable"])
            self.assertEqual(assessment["reason"], "codex_merge_readiness")
            self.assertTrue(assessment["requires_acceptance"])
            self.assertEqual(assessment["impact"], "验证受限，但实现提交存在且变更范围清楚。")
    def test_blocked_merge_test_rejects_string_true_readiness_without_limitation_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_string_ready" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_string_ready" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现已完成，自动验证受环境限制。",
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "merge_readiness": {
                            "ready": "true",
                        },
                        "verification_limitations": [
                            {
                                "reason": "test_environment_unavailable",
                                "impact": "缺少自动测试证据，需在 test 环境补验。",
                                "recovery_action": "人工确认风险后执行 merge-test。",
                                "fallback_evidence": "stdout.log",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_string_ready",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="string ready",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_string_ready",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_string_ready",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_string_ready",
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

            assessment = orchestrator._blocked_task_merge_test_assessment(ledger.get_task("task_string_ready"))

            self.assertFalse(assessment["mergeable"])
            self.assertEqual(assessment["reason"], "codex_merge_readiness_blocked")
            self.assertNotEqual(assessment["reason"], "test_environment_unavailable")
            self.assertEqual(assessment["impact"], "Codex 判断暂不应继续 merge-test。")
    def test_blocked_merge_test_treats_empty_or_non_dict_merge_readiness_as_missing(self):
        cases = [
            ("task_empty_readiness", {}),
            ("task_string_readiness", "ready"),
        ]

        for task_id, merge_readiness in cases:
            with self.subTest(merge_readiness=merge_readiness):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    project = root / "order"
                    project.mkdir()
                    _write_workflow(project)
                    workspace = root / "workspaces" / task_id / "run_impl"
                    workspace.mkdir(parents=True)
                    impl_run = root / "runs" / task_id / "run_impl"
                    impl_run.mkdir(parents=True)
                    (impl_run / "report.json").write_text(
                        json.dumps(
                            {
                                "status": "blocked",
                                "summary_markdown": "实现已完成，自动验证受环境限制。",
                                "implementation_landed": True,
                                "commit_sha": "abc123",
                                "merge_readiness": merge_readiness,
                                "verification_limitations": [
                                    {
                                        "reason": "test_environment_unavailable",
                                        "impact": "缺少自动测试证据。",
                                        "recovery_action": "人工确认后继续 merge-test。",
                                        "fallback_evidence": "stdout.log",
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    ledger = TaskLedger(root / "ledger.db")
                    ledger.create_task(
                        task_id=task_id,
                        source={"type": "manual", "project_name": "order"},
                        requirement_summary="missing readiness",
                        project_path=str(project),
                        status=TaskStatus.BLOCKED.value,
                        llm_wiki_refs=[],
                        human_decisions=[],
                        phase=TaskPhase.BLOCKED.value,
                        task_session={
                            "source_branch": f"codex/order-{task_id}",
                            "worktree_path": str(workspace),
                            "runner": {"resume_session_id": "019e-blocked-thread"},
                        },
                    )
                    ledger.append_agent_run(
                        task_id,
                        {
                            "run_id": "run_impl",
                            "runner": "codex_cli",
                            "mode": RunMode.IMPLEMENTATION.value,
                            "status": AgentRunStatus.BLOCKED.value,
                            "artifact": {"report": str(impl_run / "report.json")},
                            "workspace_path": str(workspace),
                            "source_branch": f"codex/order-{task_id}",
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

                    assessment = orchestrator._blocked_task_merge_test_assessment(ledger.get_task(task_id))

                    self.assertFalse(assessment["mergeable"])
                    self.assertEqual(assessment["reason"], "merge_readiness_missing")
                    self.assertEqual(assessment["impact"], "结构化验证结论缺失，系统不能自动判断是否可继续。")
                    self.assertEqual(assessment["fallback_evidence"], str(impl_run / "report.json"))
    def test_blocked_merge_test_uses_not_ready_fields_without_limitation_or_summary_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_not_ready" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_not_ready" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现已完成，按摘要看似可以继续。",
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "merge_readiness": {
                            "ready": False,
                            "reason": "codex_needs_manual_check",
                            "risk_note": "Codex 判断还缺少关键路径确认。",
                            "recovery_action": "补充关键路径验证后再 merge-test。",
                            "fallback_evidence": "codex-risk.md",
                        },
                        "verification_limitations": [
                            {
                                "reason": "test_environment_unavailable",
                                "impact": "旧 limitations 不应决定 readiness。",
                                "recovery_action": "旧 limitations recovery。",
                                "fallback_evidence": "stdout.log",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_not_ready",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="not ready",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_not_ready",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_not_ready",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_not_ready",
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

            assessment = orchestrator._blocked_task_merge_test_assessment(ledger.get_task("task_not_ready"))

            self.assertFalse(assessment["mergeable"])
            self.assertEqual(assessment["reason"], "codex_needs_manual_check")
            self.assertEqual(assessment["impact"], "Codex 判断还缺少关键路径确认。")
            self.assertEqual(assessment["recovery_action"], "补充关键路径验证后再 merge-test。")
            self.assertEqual(assessment["fallback_evidence"], "codex-risk.md")
    def test_blocked_merge_test_assessment_rejects_legacy_known_gaps_without_merge_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_legacy" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_legacy" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现已完成，自动验证受环境限制。",
                        "modified_files": ["src/app.ts"],
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
                task_id="task_legacy",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="legacy known gaps",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_legacy",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_legacy",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_legacy",
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

            assessment = orchestrator._blocked_task_merge_test_assessment(ledger.get_task("task_legacy"))

            self.assertFalse(assessment["mergeable"])
            self.assertEqual(assessment["reason"], "merge_readiness_missing")
            self.assertEqual(assessment["impact"], "结构化验证结论缺失，系统不能自动判断是否可继续。")
            self.assertNotIn("/coding", assessment["recovery_action"])
            self.assertIn("merge-test", assessment["recovery_action"])
            self.assertEqual(assessment["fallback_evidence"], str(impl_run / "report.json"))
    def test_blocked_merge_test_assessment_rejects_structured_not_landed_implementation(self):
        cases = [
            {"implementation_landed": False, "commit_sha": "abc123"},
            {"implementation_landed": True, "commit_sha": ""},
            {"implementation_landed": True, "commit_sha": "abc123", "status_detail": "implementation_not_landed"},
        ]

        for index, report_overrides in enumerate(cases):
            with self.subTest(report_overrides=report_overrides):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    project = root / "order"
                    project.mkdir()
                    _write_workflow(project)
                    workspace = root / "workspaces" / f"task_{index}" / "run_impl"
                    workspace.mkdir(parents=True)
                    impl_run = root / "runs" / f"task_{index}" / "run_impl"
                    impl_run.mkdir(parents=True)
                    report = {
                        "status": "blocked",
                        "summary_markdown": "实现未落地。",
                        "modified_files": ["src/app.ts"],
                        "verification_limitations": [
                            {
                                "reason": "test_environment_unavailable",
                                "impact": "缺少自动测试证据。",
                                "recovery_action": "人工确认后合入 test，并在测试环境补验。",
                                "fallback_evidence": "stdout.log",
                            }
                        ],
                        "human_required": True,
                    }
                    report.update(report_overrides)
                    (impl_run / "report.json").write_text(
                        json.dumps(report, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    ledger = TaskLedger(root / "ledger.db")
                    task_id = f"task_{index}"
                    ledger.create_task(
                        task_id=task_id,
                        source={"type": "manual", "project_name": "order"},
                        requirement_summary="not landed",
                        project_path=str(project),
                        status=TaskStatus.BLOCKED.value,
                        llm_wiki_refs=[],
                        human_decisions=[],
                        phase=TaskPhase.BLOCKED.value,
                        task_session={
                            "source_branch": f"codex/order-{task_id}",
                            "worktree_path": str(workspace),
                            "runner": {"resume_session_id": "019e-blocked-thread"},
                        },
                    )
                    ledger.append_agent_run(
                        task_id,
                        {
                            "run_id": "run_impl",
                            "runner": "codex_cli",
                            "mode": RunMode.IMPLEMENTATION.value,
                            "status": AgentRunStatus.BLOCKED.value,
                            "artifact": {"report": str(impl_run / "report.json")},
                            "workspace_path": str(workspace),
                            "source_branch": f"codex/order-{task_id}",
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

                    assessment = orchestrator._blocked_task_merge_test_assessment(ledger.get_task(task_id))

                    self.assertFalse(assessment["mergeable"])
                    self.assertEqual(assessment["reason"], "implementation_not_landed")
    def test_blocked_merge_test_assessment_prioritizes_diff_guard_over_not_landed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_diff_guard_not_landed" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_diff_guard_not_landed" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现改动越权且未落地。",
                        "implementation_landed": False,
                        "commit_sha": "",
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
                task_id="task_diff_guard_not_landed",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="diff guard and not landed",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_diff_guard_not_landed",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_diff_guard_not_landed",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_diff_guard_not_landed",
                    "diff_guard": {"changed_files": ["../outside.ts"], "violations": ["outside path"]},
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

            assessment = orchestrator._blocked_task_merge_test_assessment(
                ledger.get_task("task_diff_guard_not_landed")
            )

            self.assertFalse(assessment["mergeable"])
            self.assertEqual(assessment["reason"], "diff_guard_violation")
