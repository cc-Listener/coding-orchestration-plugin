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
from coding_orchestration.run_status_transition_service import (
    clear_active_run_if_matches,
    transition_completed_run_task_status,
    transition_missing_project_path,
    transition_missing_workspace,
    transition_reconciled_run_task_status,
    transition_run_started,
    transition_task_status,
)
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


class MinimalDiffGuard:
    def snapshot(self, root):
        return {"root": str(root)}

    def changed_files(self, root, before):
        return []

    def find_violations(self, *, changed_files, allowed_paths, forbidden_paths):
        return []

    def write_diff_summary(self, path, changed_files, violations):
        path.write_text("", encoding="utf-8")


class RunStatusTransitionServiceTest(unittest.TestCase):
    def test_transition_task_status_updates_status_phase_and_kanban_via_callbacks(self):
        updates = []
        phases = []
        kanban = []

        def sync_kanban(task_id, status, *, reason=""):
            kanban.append((task_id, status, reason))
            return {"status": "ok"}

        result = transition_task_status(
            task_id="task_status",
            status=TaskStatus.RUNNING,
            phase=TaskPhase.IMPLEMENTING,
            reason="implementation started",
            get_task_callback=lambda task_id: {"status": TaskStatus.PLANNED.value},
            update_status_callback=lambda task_id, status: updates.append((task_id, status)),
            update_phase_callback=lambda task_id, phase: phases.append((task_id, phase)),
            sync_status_to_kanban_callback=sync_kanban,
            kanban_sync_skipped_callback=lambda task_id, status, *, reason="": {"status": "skipped"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], TaskStatus.RUNNING.value)
        self.assertEqual(updates, [("task_status", TaskStatus.RUNNING.value)])
        self.assertEqual(phases, [("task_status", TaskPhase.IMPLEMENTING.value)])
        self.assertEqual(kanban, [("task_status", TaskStatus.RUNNING.value, "implementation started")])

    def test_transition_run_started_clears_active_run_when_transition_fails(self):
        transitions = []
        cleanups = []

        def fail_transition(task_id, status, *, phase=None, reason=""):
            transitions.append((task_id, status, phase, reason))
            raise RuntimeError("transition failed")

        with self.assertRaisesRegex(RuntimeError, "transition failed"):
            transition_run_started(
                task_id="task_1",
                run_id="run_1",
                mode=RunMode.PLAN_ONLY,
                running_phase=TaskPhase.PLANNING,
                transition_task_status_callback=fail_transition,
                clear_active_run_callback=lambda task_id, run_id: cleanups.append((task_id, run_id)),
            )

        self.assertEqual(
            transitions,
            [("task_1", TaskStatus.RUNNING, TaskPhase.PLANNING, "plan-only started")],
        )
        self.assertEqual(cleanups, [("task_1", "run_1")])

    def test_missing_project_and_workspace_transitions_use_structured_status(self):
        transitions = []

        def record_transition(task_id, status, *, phase=None, reason=""):
            transitions.append((task_id, status, phase, reason))
            return {"ok": True}

        transition_missing_project_path(
            task_id="task_missing_project",
            transition_task_status_callback=record_transition,
        )
        transition_missing_workspace(
            task_id="task_missing_workspace",
            reason="implementation workspace missing",
            transition_task_status_callback=record_transition,
        )

        self.assertEqual(
            transitions,
            [
                ("task_missing_project", TaskStatus.NEEDS_HUMAN, None, "task has no project_path"),
                (
                    "task_missing_workspace",
                    TaskStatus.BLOCKED,
                    TaskPhase.BLOCKED,
                    "implementation workspace missing",
                ),
            ],
        )

    def test_completion_transition_skips_stale_completion(self):
        transitions = []

        result = transition_completed_run_task_status(
            task_id="task_2",
            mode=RunMode.QA,
            status=AgentRunStatus.SUCCEEDED.value,
            task_status=TaskStatus.READY_FOR_MERGE_TEST,
            task_phase=TaskPhase.READY_TO_MERGE_TEST,
            stale_completion=True,
            transition_task_status_callback=lambda *args, **kwargs: transitions.append((args, kwargs)),
        )

        self.assertEqual(result, {"ok": False, "status": "skipped_stale_completion"})
        self.assertEqual(transitions, [])

    def test_clear_active_run_if_matches_uses_session_writeback_callback(self):
        updates = []

        clear_active_run_if_matches(
            task_id="task_3",
            run_id="run_active",
            get_task_callback=lambda task_id: {
                "task_session": {
                    "runner": {
                        "active_run_id": "run_active",
                        "active_mode": RunMode.PLAN_ONLY.value,
                    }
                }
            },
            update_task_session_callback=lambda task_id, update: updates.append((task_id, update)),
        )

        self.assertEqual(
            updates,
            [
                (
                    "task_3",
                    {
                        "runner": {
                            "active_run_id": None,
                            "active_mode": None,
                        }
                    },
                )
            ],
        )

    def test_start_run_delegates_running_and_completion_transitions_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_transition_start"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
                requirement_summary="生成订单筛选计划",
                project_path=str(project),
                status=TaskStatus.NEW.value,
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
                diff_guard=MinimalDiffGuard(),
            )
            start_calls = []
            completion_calls = []
            original_started = orchestrator_module.run_status_transition_service.transition_run_started
            original_completed = (
                orchestrator_module.run_status_transition_service.transition_completed_run_task_status
            )

            def fake_started(**kwargs):
                start_calls.append(kwargs)
                return kwargs["transition_task_status_callback"](
                    kwargs["task_id"],
                    TaskStatus.RUNNING,
                    phase=kwargs["running_phase"],
                    reason=f"{kwargs['mode'].value} started",
                )

            def fake_completed(**kwargs):
                completion_calls.append(kwargs)
                return kwargs["transition_task_status_callback"](
                    kwargs["task_id"],
                    kwargs["task_status"],
                    phase=kwargs["task_phase"],
                    reason=f"{kwargs['mode'].value} completed with {kwargs['status']}",
                )

            try:
                orchestrator_module.run_status_transition_service.transition_run_started = fake_started
                orchestrator_module.run_status_transition_service.transition_completed_run_task_status = (
                    fake_completed
                )

                result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

                self.assertEqual(len(start_calls), 1)
                self.assertEqual(start_calls[0]["task_id"], task_id)
                self.assertEqual(start_calls[0]["run_id"], result["run_id"])
                self.assertEqual(start_calls[0]["mode"], RunMode.PLAN_ONLY)
                self.assertEqual(start_calls[0]["running_phase"], TaskPhase.PLANNING)
                self.assertIs(start_calls[0]["transition_task_status_callback"].__self__, orchestrator)
                self.assertIs(start_calls[0]["clear_active_run_callback"].__self__, orchestrator)
                self.assertEqual(len(completion_calls), 1)
                self.assertEqual(completion_calls[0]["task_status"], TaskStatus.PLANNED)
                self.assertEqual(completion_calls[0]["task_phase"], TaskPhase.PLAN_READY)
                self.assertFalse(completion_calls[0]["stale_completion"])
                self.assertEqual(result["task_status"], TaskStatus.PLANNED.value)
            finally:
                orchestrator_module.run_status_transition_service.transition_run_started = original_started
                orchestrator_module.run_status_transition_service.transition_completed_run_task_status = (
                    original_completed
                )

    def test_reconcile_completed_active_run_delegates_transition_to_service(self):
        from coding_orchestration import orchestrator as orchestrator_module

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "task_reconcile_transition" / "run_done"
            run_dir.mkdir(parents=True)
            report_path = run_dir / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": AgentRunStatus.SUCCEEDED.value,
                        "mode": RunMode.PLAN_ONLY.value,
                        "summary_markdown": "后台计划完成",
                        "modified_files": [],
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
            (run_dir / "summary.md").write_text("后台计划完成", encoding="utf-8")
            (run_dir / "stdout.log").write_text("", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            (run_dir / "diff.patch").write_text("", encoding="utf-8")
            artifact = {
                "run_dir": str(run_dir),
                "input_prompt": str(run_dir / "input-prompt.md"),
                "manifest": str(run_dir / "run-manifest.json"),
                "stdout": str(run_dir / "stdout.log"),
                "stderr": str(run_dir / "stderr.log"),
                "events": str(run_dir / "events.jsonl"),
                "report": str(report_path),
                "summary": str(run_dir / "summary.md"),
                "diff": str(run_dir / "diff.patch"),
            }
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_reconcile_transition"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
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
                    }
                },
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_done",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": AgentRunStatus.QUEUED.value,
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
            calls = []
            original_reconciled = (
                orchestrator_module.run_status_transition_service.transition_reconciled_run_task_status
            )

            def fake_reconciled(**kwargs):
                calls.append(kwargs)
                return kwargs["transition_task_status_callback"](
                    kwargs["task_id"],
                    kwargs["task_status"],
                    phase=kwargs["task_phase"],
                    reason=f"{kwargs['mode'].value} reconciled with completed artifact status {kwargs['status']}",
                )

            try:
                orchestrator_module.run_status_transition_service.transition_reconciled_run_task_status = (
                    fake_reconciled
                )

                result = orchestrator._reconcile_completed_active_run(task_id)

                self.assertIsNotNone(result)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["task_id"], task_id)
                self.assertEqual(calls[0]["mode"], RunMode.PLAN_ONLY)
                self.assertEqual(calls[0]["task_status"], TaskStatus.PLANNED)
                self.assertEqual(calls[0]["task_phase"], TaskPhase.PLAN_READY)
                self.assertEqual(result["task_status"], TaskStatus.PLANNED.value)
            finally:
                orchestrator_module.run_status_transition_service.transition_reconciled_run_task_status = (
                    original_reconciled
                )


if __name__ == "__main__":
    unittest.main()
