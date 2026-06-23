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
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.run.services.run_reconcile_writeback_service import (
    ReconciledRunWritebackResult,
    write_reconciled_run_finalization,
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


def _write_active_run_artifacts(run_dir: Path, *, status: str = AgentRunStatus.SUCCEEDED.value) -> dict[str, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "runner": "codex_cli",
                "status": status,
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
    (run_dir / "stdout.log").write_text('{"type":"thread.started","thread_id":"019e-reconcile"}', encoding="utf-8")
    (run_dir / "stderr.log").write_text("", encoding="utf-8")
    (run_dir / "diff.patch").write_text("", encoding="utf-8")
    return {
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


class RunReconcileWritebackServiceTest(unittest.TestCase):
    def test_write_reconciled_run_finalization_coordinates_active_run_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = _artifact_set(root / "runs" / "task_1" / "run_active")
            calls: list[tuple[str, object]] = []

            def write_report_artifact_callback(*, report_path, report):
                calls.append(("report", dict(report)))
                report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

            result = write_reconciled_run_finalization(
                task_id="task_1",
                run_id="run_active",
                task={"task_session": {"project_name": "orders"}},
                session={"project_name": "orders"},
                existing_run={
                    "run_id": "run_active",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": AgentRunStatus.QUEUED.value,
                    "artifact": {"report": str(artifacts.report)},
                    "diff_guard": {"changed_files": []},
                },
                artifacts=artifacts,
                mode=RunMode.PLAN_ONLY,
                running_phase=TaskPhase.PLANNING,
                status=AgentRunStatus.SUCCEEDED.value,
                details={"status": AgentRunStatus.SUCCEEDED.value},
                report={
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": AgentRunStatus.SUCCEEDED.value,
                    "summary_markdown": "后台计划完成",
                    "modified_files": [],
                    "test_results": [],
                    "risks": [],
                    "verification_limitations": [],
                    "human_required": False,
                    "next_actions": [],
                },
                changed_files=[],
                runner_name="codex_cli",
                session_id="019e-reconcile",
                attach_command="codex resume 019e-reconcile",
                reconciled_at="2026-06-19T01:02:03+00:00",
                summary="后台计划完成",
                write_report_artifact_callback=write_report_artifact_callback,
                transition_task_status_callback=lambda *args, **kwargs: calls.append(("transition", kwargs)),
                upsert_artifact_callback=lambda task_id, record: calls.append(("artifact", record)),
                upsert_agent_run_callback=lambda task_id, record: calls.append(("agent_run", record)),
                update_task_session_callback=lambda task_id, update: calls.append(("session", update)),
                write_summary_callback=lambda **kwargs: calls.append(("summary", kwargs)) or {"ok": True},
            )

            self.assertIsInstance(result, ReconciledRunWritebackResult)
            self.assertEqual(result.status, AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(result.task_status, TaskStatus.PLANNED)
            self.assertEqual(result.result_payload["task_status"], TaskStatus.PLANNED.value)
            self.assertEqual(json.loads(artifacts.report.read_text(encoding="utf-8"))["task_status"], "planned")
            call_names = [name for name, _payload in calls]
            self.assertEqual(call_names, ["report", "transition", "artifact", "agent_run", "session", "summary"])
            session_call = dict(calls[4][1])
            self.assertIsNone(session_call["runner"]["active_run_id"])
            self.assertEqual(session_call["runner"]["resume_session_id"], "019e-reconcile")
            self.assertEqual(session_call["runner"]["attach_command"], "codex resume 019e-reconcile")

    def test_reconcile_completed_active_run_delegates_finalization_to_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "task_reconcile_writeback" / "run_done"
            artifact = _write_active_run_artifacts(run_dir)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_reconcile_writeback"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders-source"},
                requirement_summary="订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLANNING.value,
                task_session={
                    "project_name": "orders-session",
                    "runner": {
                        "provider": "codex_cli",
                        "active_run_id": "run_done",
                        "active_mode": RunMode.PLAN_ONLY.value,
                    },
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
            original = orchestrator_module.run_reconcile_writeback_service.write_reconciled_run_finalization

            def fake_write_reconciled_run_finalization(**kwargs):
                calls.append(kwargs)
                return ReconciledRunWritebackResult(
                    result_payload={
                        "task_id": kwargs["task_id"],
                        "run_id": kwargs["run_id"],
                        "mode": kwargs["mode"].value,
                        "status": AgentRunStatus.SUCCEEDED.value,
                        "run_status": AgentRunStatus.SUCCEEDED.value,
                        "task_status": TaskStatus.PLANNED.value,
                        "artifacts": {"report": str(kwargs["artifacts"].report)},
                        "reconciled": True,
                    },
                    report=kwargs["report"],
                    artifact_record={"report": str(kwargs["artifacts"].report)},
                    status=AgentRunStatus.SUCCEEDED.value,
                    task_status=TaskStatus.PLANNED,
                )

            try:
                orchestrator_module.run_reconcile_writeback_service.write_reconciled_run_finalization = (
                    fake_write_reconciled_run_finalization
                )

                result = orchestrator._reconcile_completed_active_run(task_id)

                self.assertEqual(result["run_id"], "run_done")
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["task_id"], task_id)
                self.assertEqual(calls[0]["run_id"], "run_done")
                self.assertEqual(calls[0]["mode"], RunMode.PLAN_ONLY)
                self.assertEqual(calls[0]["runner_name"], "codex_cli")
                self.assertEqual(calls[0]["session"]["project_name"], "orders-session")
                self.assertEqual(calls[0]["summary"], "后台计划完成")
                self.assertTrue(callable(calls[0]["write_report_artifact_callback"]))
                self.assertTrue(callable(calls[0]["transition_task_status_callback"]))
                self.assertTrue(callable(calls[0]["upsert_artifact_callback"]))
                self.assertTrue(callable(calls[0]["upsert_agent_run_callback"]))
                self.assertTrue(callable(calls[0]["update_task_session_callback"]))
                self.assertTrue(callable(calls[0]["write_summary_callback"]))
            finally:
                orchestrator_module.run_reconcile_writeback_service.write_reconciled_run_finalization = original


if __name__ == "__main__":
    unittest.main()
