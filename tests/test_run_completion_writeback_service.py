from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration import orchestrator as orchestrator_module
from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, ArtifactSet, RunMode, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.run.services.run_completion_writeback_service import (
    CompletedRunWritebackResult,
    write_completed_run_finalization,
)
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


def _artifact_set(run_dir: Path) -> ArtifactSet:
    run_dir.mkdir(parents=True, exist_ok=True)
    return ArtifactSet(
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


class RunCompletionWritebackServiceTest(unittest.TestCase):
    def test_write_completed_run_finalization_coordinates_fresh_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = _artifact_set(root / "runs" / "task_1" / "run_1")
            artifacts.summary.write_text("计划完成", encoding="utf-8")
            calls: list[tuple[str, object]] = []

            def write_report_artifact_callback(*, report_path, report):
                calls.append(("report", dict(report)))
                report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

            result = write_completed_run_finalization(
                task_id="task_1",
                run_id="run_1",
                mode=RunMode.PLAN_ONLY,
                running_phase=TaskPhase.PLANNING,
                status=AgentRunStatus.SUCCEEDED.value,
                details={"status": AgentRunStatus.SUCCEEDED.value},
                report={
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": AgentRunStatus.SUCCEEDED.value,
                    "summary_markdown": "计划完成",
                    "modified_files": [],
                    "test_results": [],
                    "risks": [],
                    "verification_limitations": [],
                    "human_required": False,
                    "next_actions": [],
                },
                current_task={
                    "status": TaskStatus.RUNNING.value,
                    "task_session": {"runner": {"active_run_id": "run_1"}},
                },
                artifacts=artifacts,
                runner_name="codex_cli",
                exit_code=0,
                workspace_path=None,
                source_branch=None,
                implementation_checkpoint=None,
                qa_artifacts={},
                tested_commit="",
                changed_files=[],
                violations=[],
                session_id="019e-session",
                attach_command="codex resume 019e-session",
                project_name="orders",
                merge_record_created_at="",
                write_report_artifact_callback=write_report_artifact_callback,
                read_summary_artifact_callback=lambda *, summary_path: summary_path.read_text(encoding="utf-8"),
                transition_task_status_callback=lambda *args, **kwargs: calls.append(("transition", kwargs)),
                append_artifact_callback=lambda task_id, record: calls.append(("artifact", record)),
                append_agent_run_callback=lambda task_id, record: calls.append(("agent_run", record)),
                append_merge_record_callback=lambda task_id, record: calls.append(("merge", record)),
                update_task_session_callback=lambda task_id, update: calls.append(("session", update)),
                write_summary_callback=lambda **kwargs: calls.append(("summary", kwargs)) or {"ok": True},
                project_writeback_callback=lambda task_id, payload, **kwargs: calls.append(("project", payload))
                or {"ok": True, "status": "updated"},
            )

            self.assertIsInstance(result, CompletedRunWritebackResult)
            self.assertEqual(result.status, AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(result.task_status, TaskStatus.PLANNED)
            self.assertFalse(result.stale_completion)
            self.assertEqual(result.result_payload["task_status"], TaskStatus.PLANNED.value)
            self.assertEqual(result.result_payload["project_writeback"]["status"], "updated")
            self.assertEqual(json.loads(artifacts.report.read_text(encoding="utf-8"))["task_status"], "planned")
            call_names = [name for name, _payload in calls]
            self.assertEqual(
                call_names,
                ["report", "transition", "artifact", "agent_run", "session", "summary", "project"],
            )
            session_call = dict(calls[4][1])
            self.assertEqual(session_call["runner"]["resume_session_id"], "019e-session")
            self.assertEqual(session_call["runner"]["attach_command"], "codex resume 019e-session")

    def test_write_completed_run_finalization_preserves_stale_completion_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = _artifact_set(root / "runs" / "task_2" / "run_old")
            artifacts.summary.write_text("旧 run 完成", encoding="utf-8")
            calls: list[tuple[str, object]] = []

            result = write_completed_run_finalization(
                task_id="task_2",
                run_id="run_old",
                mode=RunMode.IMPLEMENTATION,
                running_phase=TaskPhase.IMPLEMENTING,
                status=AgentRunStatus.SUCCEEDED.value,
                details={"status": AgentRunStatus.SUCCEEDED.value},
                report={
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.SUCCEEDED.value,
                    "summary_markdown": "旧 run 完成",
                    "modified_files": ["src/app.ts"],
                    "test_results": [],
                    "risks": [],
                    "verification_limitations": [],
                    "human_required": False,
                    "next_actions": [],
                    "implementation_landed": True,
                },
                current_task={
                    "status": TaskStatus.RUNNING.value,
                    "task_session": {"runner": {"active_run_id": "run_new"}},
                },
                artifacts=artifacts,
                runner_name="codex_cli",
                exit_code=0,
                workspace_path=root / "workspace",
                source_branch="codex/orders-task_2",
                implementation_checkpoint={"commit": "abc123"},
                qa_artifacts={},
                tested_commit="",
                changed_files=["src/app.ts"],
                violations=[],
                session_id="019e-old",
                attach_command="codex resume 019e-old",
                project_name="orders",
                merge_record_created_at="",
                write_report_artifact_callback=lambda *, report_path, report: calls.append(("report", dict(report))),
                read_summary_artifact_callback=lambda *, summary_path: summary_path.read_text(encoding="utf-8"),
                transition_task_status_callback=lambda *args, **kwargs: calls.append(("transition", kwargs)),
                append_artifact_callback=lambda task_id, record: calls.append(("artifact", record)),
                append_agent_run_callback=lambda task_id, record: calls.append(("agent_run", record)),
                append_merge_record_callback=lambda task_id, record: calls.append(("merge", record)),
                update_task_session_callback=lambda task_id, update: calls.append(("session", update)),
                write_summary_callback=lambda **kwargs: calls.append(("summary", kwargs)) or {"ok": True},
                project_writeback_callback=lambda task_id, payload, **kwargs: calls.append(("project", payload)),
            )

            self.assertTrue(result.stale_completion)
            self.assertEqual(result.result_payload["current_task_status"], TaskStatus.RUNNING.value)
            self.assertEqual(result.result_payload["observed_active_run_id"], "run_new")
            agent_run = next(payload for name, payload in calls if name == "agent_run")
            self.assertTrue(agent_run["stale_completion"])
            call_names = [name for name, _payload in calls]
            self.assertNotIn("session", call_names)
            self.assertNotIn("project", call_names)

    def test_start_run_delegates_completed_writeback_to_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_completion_writeback"
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
            )
            calls = []
            original = orchestrator_module.run_completion_writeback_service.write_completed_run_finalization

            def fake_write_completed_run_finalization(**kwargs):
                calls.append(kwargs)
                return CompletedRunWritebackResult(
                    result_payload={
                        "task_id": kwargs["task_id"],
                        "run_id": kwargs["run_id"],
                        "mode": kwargs["mode"].value,
                        "status": AgentRunStatus.SUCCEEDED.value,
                        "run_status": AgentRunStatus.SUCCEEDED.value,
                        "task_status": TaskStatus.PLANNED.value,
                        "stale_completion": False,
                        "current_task_status": TaskStatus.PLANNED.value,
                        "observed_active_run_id": "",
                        "artifacts": {"report": str(kwargs["artifacts"].report)},
                        "report": kwargs["report"],
                        "project_writeback": {"ok": True},
                    },
                    report=kwargs["report"],
                    artifact_record={"report": str(kwargs["artifacts"].report)},
                    project_writeback={"ok": True},
                    stale_completion=False,
                    status=AgentRunStatus.SUCCEEDED.value,
                    task_status=TaskStatus.PLANNED,
                )

            try:
                orchestrator_module.run_completion_writeback_service.write_completed_run_finalization = (
                    fake_write_completed_run_finalization
                )

                result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["task_id"], task_id)
                self.assertEqual(calls[0]["run_id"], result["run_id"])
                self.assertEqual(calls[0]["mode"], RunMode.PLAN_ONLY)
                self.assertEqual(calls[0]["runner_name"], "codex_cli")
                self.assertTrue(callable(calls[0]["write_report_artifact_callback"]))
                self.assertTrue(callable(calls[0]["transition_task_status_callback"]))
                self.assertTrue(callable(calls[0]["append_artifact_callback"]))
                self.assertTrue(callable(calls[0]["append_agent_run_callback"]))
                self.assertTrue(callable(calls[0]["update_task_session_callback"]))
                self.assertTrue(callable(calls[0]["write_summary_callback"]))
                self.assertTrue(callable(calls[0]["project_writeback_callback"]))
                self.assertEqual(result["project_writeback"], {"ok": True})
            finally:
                orchestrator_module.run_completion_writeback_service.write_completed_run_finalization = original


if __name__ == "__main__":
    unittest.main()
